#!/usr/bin/env python3
"""Camera server for the pancake decorator robot.

Runs on the Raspberry Pi. It owns the overhead camera and shares it with
everything else over HTTP, so the display and the robot code never fight
over the camera (only one program can open a camera at a time).

    python3 pi/camera_server.py                      # auto: Pi Camera Module, else USB webcam 0
    python3 pi/camera_server.py --camera usb --device 1
    python3 pi/camera_server.py --camera file --image pi/sample_pancake.jpg   # no camera needed

Then open http://raspberrypi.local:8000 on any screen on the same network.

Endpoints
    GET  /                    the Topping Guide display (index.html, styles.css, script.js)
    GET  /api/status          {"camera": "...", "camera_ok": true, "syrup_done": 3, ...}
    GET  /api/snapshot.jpg    one fresh JPEG from the camera
    GET  /api/stream          live MJPEG stream (use as an <img> src)
    POST /api/syrup-done      the robot calls this when it has finished the syrup;
                              displays with auto-capture on take the photo within ~1 s

Only the Python standard library is required. The camera backends need
picamera2 (Pi Camera Module) or opencv-python (USB webcam / video file).
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_FILES = {"/": "index.html", "/index.html": "index.html",
                "/styles.css": "styles.css", "/script.js": "script.js"}
BOUNDARY = "pancakeframe"


# --------------------------------------------------------------------------- cameras
class Camera:
    """Base class: a background thread keeps the latest JPEG ready."""
    name = "camera"

    def __init__(self, fps=10.0, quality=85):
        self.fps, self.quality = fps, quality
        self.ok, self.error = False, "starting"
        self._jpeg, self._frame_id = None, 0
        self._cond = threading.Condition()
        self._stop = threading.Event()

    def start(self):
        try:
            self.open()
        except Exception as e:  # report through /api/status instead of crashing
            self.ok, self.error = False, f"{type(e).__name__}: {e}"
            print(f"[camera] could not open {self.name} camera: {self.error}", file=sys.stderr)
            return self
        try:  # first frame now, so /api/status is accurate as soon as the server is up
            self._jpeg, self._frame_id = self.grab(), 1
            self.ok, self.error = True, None
        except Exception as e:
            self.ok, self.error = False, f"{type(e).__name__}: {e}"
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        period = 1.0 / self.fps
        fails = 0
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                jpeg = self.grab()
                fails = 0
                with self._cond:
                    self._jpeg, self._frame_id = jpeg, self._frame_id + 1
                    self.ok, self.error = True, None
                    self._cond.notify_all()
            except Exception as e:
                fails += 1
                if fails >= 5:
                    self.ok, self.error = False, f"{type(e).__name__}: {e}"
                time.sleep(0.5)
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    def frame(self, newer_than=None, timeout=3.0):
        """Latest JPEG; if newer_than is given, wait for a frame newer than that id."""
        with self._cond:
            self._cond.wait_for(lambda: self._jpeg is not None and
                                (newer_than is None or self._frame_id > newer_than), timeout)
            return self._jpeg, self._frame_id

    def fresh(self, timeout=3.0):
        """A frame captured after this call started (not one buffered earlier)."""
        with self._cond:
            current = self._frame_id
        return self.frame(newer_than=current, timeout=timeout)[0]

    def stop(self):
        self._stop.set()
        self.close()

    # subclasses implement these
    def open(self): ...
    def grab(self) -> bytes: ...
    def close(self): ...


class FileCamera(Camera):
    """Serves a still image as if it were a camera. For testing without hardware."""
    name = "file"

    def __init__(self, path, **kw):
        super().__init__(**kw)
        self.path = path

    def open(self):
        with open(self.path, "rb") as f:
            self.data = f.read()
        if not self.data.startswith(b"\xff\xd8"):
            raise ValueError(f"{self.path} is not a JPEG")

    def grab(self):
        return self.data


class OpenCVCamera(Camera):
    """USB webcam (device number) or a video file, through OpenCV."""
    name = "usb"

    def __init__(self, device=0, width=1280, height=960, **kw):
        super().__init__(**kw)
        self.device, self.width, self.height = device, width, height
        self.cap = None

    def open(self):
        import cv2
        self.cv2 = cv2
        src = int(self.device) if str(self.device).isdigit() else self.device
        self.is_file = not isinstance(src, int)
        if self.is_file:
            self.name = "video file"
        self.cap = cv2.VideoCapture(src)
        if not self.cap.isOpened():
            raise RuntimeError(f"can't open camera/video {self.device!r}")
        if not self.is_file:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

    def grab(self):
        ok, img = self.cap.read()
        if not ok and self.is_file:  # loop video files
            self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, 0)
            ok, img = self.cap.read()
        if not ok:
            raise RuntimeError("camera returned no frame")
        ok, buf = self.cv2.imencode(".jpg", img, [self.cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return buf.tobytes()

    def close(self):
        if self.cap is not None:
            self.cap.release()


class PiCamera(Camera):
    """Raspberry Pi Camera Module, through picamera2 (preinstalled on Raspberry Pi OS)."""
    name = "Pi Camera Module"

    def __init__(self, width=1280, height=960, **kw):
        super().__init__(**kw)
        self.size = (width, height)
        self.cam = None

    def open(self):
        import io
        from picamera2 import Picamera2
        self.io = io
        self.cam = Picamera2()
        self.cam.configure(self.cam.create_video_configuration(main={"size": self.size, "format": "RGB888"}))
        self.cam.start()
        time.sleep(1.0)  # let auto-exposure settle

    def grab(self):
        buf = self.io.BytesIO()
        self.cam.capture_file(buf, format="jpeg")
        return buf.getvalue()

    def close(self):
        if self.cam is not None:
            self.cam.stop()


def make_camera(args):
    kw = dict(fps=args.fps, quality=args.quality)
    if args.camera == "file":
        return FileCamera(args.image, fps=min(args.fps, 2.0), quality=args.quality)
    if args.camera == "usb":
        return OpenCVCamera(args.device, args.width, args.height, **kw)
    if args.camera == "pi":
        return PiCamera(args.width, args.height, **kw)
    # auto: Pi Camera Module if picamera2 finds one, else USB webcam
    try:
        from picamera2 import Picamera2
        if Picamera2.global_camera_info():
            return PiCamera(args.width, args.height, **kw)
    except Exception:
        pass
    return OpenCVCamera(args.device, args.width, args.height, **kw)


# --------------------------------------------------------------------------- server
class State:
    def __init__(self, camera):
        self.camera = camera
        self.lock = threading.Lock()
        self.syrup_done = 0
        self.syrup_done_at = None


class Handler(BaseHTTPRequestHandler):
    server_version = "PancakeCamera/1.0"
    state: State = None  # set in main()

    def log_message(self, fmt, *a):
        if not self.path.startswith(("/api/status", "/api/stream")):  # those are very chatty
            sys.stderr.write("[http] %s %s\n" % (self.address_string(), fmt % a))

    def _cors(self):
        # The display may be opened from a laptop (file:// or another server), so allow any origin.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        st, cam = self.state, self.state.camera
        if path == "/api/status":
            with st.lock:
                self._json({"camera": cam.name, "camera_ok": cam.ok, "error": cam.error,
                            "syrup_done": st.syrup_done, "syrup_done_at": st.syrup_done_at,
                            "time": time.time()})
        elif path == "/api/snapshot.jpg":
            jpeg = cam.fresh()
            if jpeg is None:
                self._json({"error": cam.error or "no frame yet"}, 503)
            else:
                self._send(200, jpeg, "image/jpeg")
        elif path == "/api/stream":
            self._stream()
        elif path in STATIC_FILES:
            fp = os.path.join(ROOT, STATIC_FILES[path])
            try:
                with open(fp, "rb") as f:
                    body = f.read()
            except OSError:
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, body, ctype)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if path == "/api/syrup-done":
            st = self.state
            with st.lock:
                st.syrup_done += 1
                st.syrup_done_at = time.time()
                n = st.syrup_done
            print(f"[robot] syrup done (#{n})", file=sys.stderr)
            self._json({"syrup_done": n})
        else:
            self._json({"error": "not found"}, 404)

    def _stream(self):
        cam = self.state.camera
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last = None
        try:
            while True:
                jpeg, fid = cam.frame(newer_than=last, timeout=5.0)
                if jpeg is None or fid == last:  # no new frame in 5 s
                    if not cam.ok:
                        break
                    continue
                last = fid
                self.wfile.write(f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                                 f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # viewer closed the page or switched to a photo


def build_server(camera, host="0.0.0.0", port=8000):
    handler = type("BoundHandler", (Handler,), {"state": State(camera)})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--camera", choices=["auto", "pi", "usb", "file"], default="auto",
                   help="which camera to use (default: auto)")
    p.add_argument("--device", default="0", help="USB webcam number, or a video file path (default: 0)")
    p.add_argument("--image", default=os.path.join(ROOT, "pi", "sample_pancake.jpg"),
                   help="JPEG to serve with --camera file")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=960)
    p.add_argument("--fps", type=float, default=10.0, help="live view frame rate (default: 10)")
    p.add_argument("--quality", type=int, default=85, help="JPEG quality (default: 85)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    camera = make_camera(args).start()
    httpd = build_server(camera, args.host, args.port)
    print(f"[server] {camera.name} camera {'ready' if camera.ok else 'NOT working: ' + str(camera.error)}")
    print(f"[server] open http://<this-pi>:{args.port}  (e.g. http://raspberrypi.local:{args.port})")
    print(f"[server] robot: POST http://localhost:{args.port}/api/syrup-done when the syrup is finished")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        camera.stop()


if __name__ == "__main__":
    main()
