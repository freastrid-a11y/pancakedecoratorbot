"""The camera features in the browser, end to end.

    python tests/test_camera_ui.py

1. Starts pi/camera_server.py with the sample photo as the "camera" and opens the
   display from it, like on the Pi: live view, Take photo, and the automatic photo
   after the robot's POST /api/syrup-done.
2. "This computer" mode with Chrome's built-in fake webcam.
3. A wrong Pi address shows a clear error.
"""
import json
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright
from _util import ROOT, INDEX, OUT, launch, collect_errors, real_errors


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); return port


port = free_port()
base = f"http://127.0.0.1:{port}"
server = subprocess.Popen([sys.executable, str(ROOT / "pi" / "camera_server.py"), "--camera", "file",
                           "--host", "127.0.0.1", "--port", str(port)], stderr=subprocess.DEVNULL)
for _ in range(50):
    try:
        urllib.request.urlopen(base + "/api/status", timeout=1); break
    except Exception:
        time.sleep(0.1)

NEW_PHOTO = "() => S.src !== window.__before && S.demo === null"
MARK = "() => { window.__before = S.src; }"

try:
    with sync_playwright() as p:
        browser = launch(p, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])

        # ---- 1. served from the Pi ----
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page(); errors = collect_errors(page)
        page.goto(base + "/")
        page.wait_for_function("CAM.source === 'pi'", timeout=5000)
        page.wait_for_selector("#live:not([hidden])")
        page.wait_for_function("document.querySelector('#live').naturalWidth > 0", timeout=5000)
        print("ok  page from the Pi opens on the Raspberry Pi tab with the live view:", page.inner_text("#piMsg"))
        page.screenshot(path=str(OUT / "camera-pi-live.png"))

        page.evaluate(MARK); page.click("#piSnap")
        page.wait_for_function(NEW_PHOTO, timeout=5000)
        assert page.is_hidden("#live")
        found = page.evaluate("[S.A.found, S.A.syrupPx > 0, S.spots.length]")
        assert found[0] and found[1] and found[2] > 0, found
        print("ok  Take photo: pancake and syrup found,", found[2], "spots planned")

        page.click("#piLive"); page.wait_for_selector("#live:not([hidden])")
        page.evaluate(MARK)
        req = urllib.request.Request(base + "/api/syrup-done", data=b"", method="POST")
        print("    robot says syrup done:", json.load(urllib.request.urlopen(req)))
        page.wait_for_function(NEW_PHOTO, timeout=4000)
        assert page.is_hidden("#live")
        print("ok  automatic photo after syrup-done:", page.inner_text("#piMsg"))
        page.wait_for_timeout(200)
        page.screenshot(path=str(OUT / "camera-pi-auto.png"))

        page.uncheck("#piAuto"); page.evaluate(MARK)
        urllib.request.urlopen(urllib.request.Request(base + "/api/syrup-done", data=b"", method="POST"))
        page.wait_for_timeout(2000)
        assert page.evaluate("S.src === window.__before"), "auto-capture should be off"
        print("ok  no photo when auto-capture is unchecked")
        assert not real_errors(errors), errors
        ctx.close()

        # ---- 2. this computer's webcam (fake) ----
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page(); errors = collect_errors(page)
        page.goto(base + "/?source=webcam")
        page.click("#camStart")
        page.wait_for_function("document.querySelector('#liveVideo').videoWidth > 0", timeout=5000)
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "camera-webcam-live.png"))
        page.evaluate(MARK); page.click("#camSnap")
        page.wait_for_function(NEW_PHOTO, timeout=5000)
        assert page.is_hidden("#liveVideo")
        cams = page.evaluate("[...document.querySelectorAll('#camSelect option')].map(o=>o.textContent)")
        print("ok  webcam live view and photo; cameras listed:", cams)
        assert not real_errors(errors), errors
        ctx.close()

        # ---- 3. wrong address, and back to demos ----
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page(); errors = collect_errors(page)
        page.goto(INDEX + f"?source=pi&pi=127.0.0.1:{free_port()}")
        page.wait_for_function("document.querySelector('#piMsg').classList.contains('err')", timeout=8000)
        print("ok  wrong address:", page.inner_text("#piMsg"))
        assert page.is_disabled("#piSnap")
        page.click("#srcSeg button[data-v=demo]"); page.click("#demos .btn >> nth=2")
        assert page.evaluate("S.demo") == "star"
        print("ok  back to the demos")
        page.screenshot(path=str(OUT / "camera-pi-error.png"))
        print("ERRORS:", real_errors(errors))
        assert not real_errors(errors)
        browser.close()
    print("ALL PASSED")
finally:
    server.terminate()
