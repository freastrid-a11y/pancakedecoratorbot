"""Helpers for the robot's own code to talk to camera_server.py.

    from robot_client import syrup_done, snapshot

    ... robot finishes drawing ...
    syrup_done()                     # displays take the photo and show the topping guide
    jpeg = snapshot()                # the robot can also grab a photo itself (e.g. for the ILC loop)

Standard library only. Run it directly to send one "syrup done" signal:

    python3 pi/robot_client.py [http://localhost:8000]
"""
import json
import sys
import urllib.request

DEFAULT_URL = "http://localhost:8000"


def syrup_done(base=DEFAULT_URL, timeout=3.0):
    """Tell every connected display that the syrup is finished. Returns the signal count."""
    req = urllib.request.Request(base.rstrip("/") + "/api/syrup-done", data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["syrup_done"]


def snapshot(base=DEFAULT_URL, timeout=5.0):
    """One fresh JPEG (bytes) from the overhead camera."""
    with urllib.request.urlopen(base.rstrip("/") + "/api/snapshot.jpg", timeout=timeout) as r:
        return r.read()


if __name__ == "__main__":
    print("syrup done signal #%d sent" % syrup_done(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
