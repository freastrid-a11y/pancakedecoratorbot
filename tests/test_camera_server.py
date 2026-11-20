"""Tests pi/camera_server.py with no camera and no extra packages (standard library only).

    python tests/test_camera_server.py

If opencv-python is installed, it also runs the USB-webcam code path, using a short
video file made from the sample photo in place of a webcam.
"""
import json
import os
import pathlib
import sys
import tempfile
import threading
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pi"))
import camera_server as cs  # noqa: E402
import robot_client  # noqa: E402

SAMPLE = ROOT / "pi" / "sample_pancake.jpg"


def serve(camera):
    camera.start()
    httpd = cs.build_server(camera, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def get(url, **kw):
    with urllib.request.urlopen(url, timeout=5, **kw) as r:
        return r.status, dict(r.headers), r.read()


def check_server(camera, label):
    httpd, base = serve(camera)
    try:
        code, h, body = get(base + "/api/status")
        st = json.loads(body)
        assert code == 200 and st["camera_ok"], st
        assert h["Access-Control-Allow-Origin"] == "*"
        assert st["syrup_done"] == 0

        code, h, jpeg = get(base + "/api/snapshot.jpg")
        assert code == 200 and h["Content-Type"] == "image/jpeg" and jpeg[:2] == b"\xff\xd8", h

        # MJPEG stream: read the first part
        with urllib.request.urlopen(base + "/api/stream", timeout=5) as r:
            assert r.headers["Content-Type"].startswith("multipart/x-mixed-replace"), r.headers
            head = r.read(200)
            assert head.startswith(b"--pancakeframe\r\nContent-Type: image/jpeg"), head[:60]

        # the robot signals "syrup done" twice
        assert robot_client.syrup_done(base) == 1
        assert robot_client.syrup_done(base) == 2
        assert json.loads(get(base + "/api/status")[2])["syrup_done"] == 2
        assert robot_client.snapshot(base)[:2] == b"\xff\xd8"

        # the display files are served, and nothing else in the repo is
        code, h, html = get(base + "/")
        assert code == 200 and b'<script src="script.js">' in html
        assert get(base + "/script.js")[0] == 200 and get(base + "/styles.css")[0] == 200
        for bad in ("/.git/config", "/pi/camera_server.py", "/../etc/passwd"):
            try:
                get(base + bad)
                raise AssertionError(bad + " should be 404")
            except urllib.error.HTTPError as e:
                assert e.code == 404, (bad, e.code)
        print(f"ok  {label}: status, snapshot, stream, syrup-done, static files")
    finally:
        httpd.shutdown()
        camera.stop()


def check_broken_camera():
    cam = cs.FileCamera(str(ROOT / "does-not-exist.jpg"))
    httpd, base = serve(cam)
    try:
        st = json.loads(get(base + "/api/status")[2])
        assert st["camera_ok"] is False and "No such file" in st["error"], st
        try:
            get(base + "/api/snapshot.jpg")
            raise AssertionError("snapshot should fail")
        except urllib.error.HTTPError as e:
            assert e.code == 503
        print("ok  broken camera is reported through /api/status, snapshot gives 503")
    finally:
        httpd.shutdown()


def main():
    check_server(cs.FileCamera(str(SAMPLE)), "file camera")
    check_broken_camera()
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("skip  USB webcam path (pip install opencv-python-headless to run it)")
    else:
        img = cv2.imread(str(SAMPLE))
        tmp = tempfile.mkdtemp()
        video = os.path.join(tmp, "pancake.avi")
        w = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"MJPG"), 10, (img.shape[1], img.shape[0]))
        for i in range(20):
            w.write(np.roll(img, i, axis=1))
        w.release()
        check_server(cs.OpenCVCamera(video), "OpenCV (video file standing in for a USB webcam)")
    print("ALL PASSED")


if __name__ == "__main__":
    main()
