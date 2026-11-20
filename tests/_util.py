"""Shared helpers for the browser tests."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "test-output"
OUT.mkdir(exist_ok=True)
INDEX = (ROOT / "index.html").as_uri()


def launch(p, **kw):
    """Launch Chromium. Set CHROMIUM_PATH to use a browser other than Playwright's own."""
    exe = os.environ.get("CHROMIUM_PATH")
    if exe:
        kw["executable_path"] = exe
    return p.chromium.launch(**kw)


def collect_errors(page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    return errors


def real_errors(errors):
    # A font-loading error is normal when offline.
    return [e for e in errors if "fonts.g" not in e and "ERR_" not in e and "Failed to load resource" not in e]
