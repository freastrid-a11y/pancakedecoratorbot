"""Tests for the ILC module (pi/ilc), using the simulated robot. Needs only numpy.

    python tests/test_ilc.py
"""
import os
import pathlib
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pi"))
from ilc import ILCSettings, Learner, ilc_update, get_design, calibrate, CALIBRATION_DOTS   # noqa: E402
from ilc.designs import Design, Stroke                                                       # noqa: E402
from ilc.simulator import Camera, Nominal, SimRobot, StrokeResult, render                    # noqa: E402
from ilc.vision import CALIBRATION_DOT_MM, Calibration, apply_h, measure                     # noqa: E402
from ilc.simulate import run                                                                 # noqa: E402

cam = Camera.overhead()
nominal = Nominal()


def check(cond, msg):
    assert cond, msg
    print("ok ", msg)


# --- designs
d = get_design("heart")
pts = d.resampled(2.0)[0]
steps = np.hypot(*np.diff(pts, axis=0).T)
check(abs(np.median(steps) - 2.0) < 0.05 and steps.min() > 1.0, f"heart resampled every {np.median(steps):.2f} mm")

# --- calibration
dots = [(x, y, CALIBRATION_DOT_MM) for x, y in CALIBRATION_DOTS]
cal = calibrate(render(cam, dots=dots, seed=3))
test = np.array([[0, 0], [70, 0], [0, 70], [-50, -50]], float)
err = np.hypot(*(apply_h(cal.H, test) - apply_h(cam.H, test)).T).max() / cal.px_per_mm
check(err < 0.3, f"calibration from dots: positions within {err:.2f} mm")
tmp = tempfile.mkdtemp()
cal.save(os.path.join(tmp, "cal.json"))
check(np.allclose(Calibration.load(os.path.join(tmp, "cal.json")).H, cal.H), "calibration saves and loads")

# --- measuring known widths
line = np.stack([np.linspace(-40, 40, 41), np.zeros(41)], 1)
for w in (3.0, 5.0, 7.0):
    s = StrokeResult(line, np.full(41, w), 0.0, np.zeros(41))
    m, _ = measure(render(cam, [s], seed=4), [line], [5.0], Calibration(cam.H))
    got = m[0].width[5:-5]
    check(np.abs(got - w).max() < 0.5, f"measures a {w:.0f} mm line as {got.mean():.2f} mm (max error {np.abs(got - w).max():.2f})")
check(np.nanmax(np.abs(m[0].offset[5:-5])) < 0.5, "line centred on the path has ~0 offset")

# --- crossings and corners are not measured
A = get_design("A")
ptsA = A.resampled(2.0)
m, _ = measure(render(cam, [], seed=5), ptsA, [5, 5], Calibration(cam.H))
apex = int(np.argmin(ptsA[0][:, 1]))
check(not m[0].valid[apex] and not m[1].valid[0] and not m[1].valid[-1] and m[0].valid[3] and m[0].valid[20],
      "the A's apex and crossbar ends are skipped, the middle of the legs is measured")

# --- the update rule
s = ILCSettings("flow", nominal=0.75, lead_mm=4, smooth_mm=1)
cmd = np.full(20, 0.75)
wide = np.full(20, 5.0); wide[10] = 7.0
new = ilc_update(cmd, wide, 5.0, np.ones(20, bool), s)
check(np.argmin(new) == 8 and new[8] < 0.75 and np.allclose(new[:8], 0.75),
      "too wide -> less flow, 4 mm (2 points) earlier")
sp = ILCSettings("speed", nominal=25, lo=8, hi=60, smooth_mm=1)
check(sp.lead_mm == 0 and ilc_update(np.full(20, 25.0), wide, 5.0, np.ones(20, bool), sp)[10] > 25,
      "speed: no lead by default, too wide -> faster")
check(np.allclose(ilc_update(cmd, wide, 5.0, np.zeros(20, bool), s), 0.75), "unmeasurable points change nothing")

# --- the store
L = Learner(tmp, cal, ILCSettings(nominal=0.75))
p0, c0 = L.commands(d)
check(all(np.allclose(c, 0.75) for c in c0), "new design starts at the nominal command")
robot = SimRobot(seed=2)
rep = L.update(d, render(cam, robot.draw(p0, c0), seed=6))
_, c1 = L.commands(d)
check(not np.allclose(c1[0], 0.75) and rep["stats"]["pancake"] == 1, "corrections are saved after a pancake")
check(Learner(tmp, cal, ILCSettings(nominal=0.75)).commands(d)[1][0].tolist() == c1[0].tolist(),
      "a new Learner (robot restart) picks the corrections up again")
check(np.allclose(Learner(tmp, cal, ILCSettings(nominal=0.75, spacing=3.0)).commands(d)[1][0], 0.75),
      "changing the point spacing starts over instead of misusing old corrections")
L.reset("heart")
check(np.allclose(L.commands(d)[1][0], 0.75), "reset forgets a design")

# --- learning converges on the simulator
for control in ("flow", "speed"):
    res = run(["heart", "star", "spiral"], pancakes=8, control=control, quiet=True)
    for name, rows in res.items():
        first, last = rows[0]["true_rms"], rows[-1]["true_rms"]
        check(last < 0.5 * first and last < 0.5,
              f"{control:5} {name:6}: true width error {first:.2f} -> {last:.2f} mm in 8 pancakes")
base = run(["heart"], pancakes=4, learn=False, quiet=True)["heart"]
check(abs(base[0]["true_rms"] - base[-1]["true_rms"]) < 0.15, "with learning off, nothing improves (baseline)")

# --- the real-robot loop, through the camera server (needs OpenCV or Pillow for JPEG)
try:
    import cv2
    def to_jpeg(rgb): return cv2.imencode(".jpg", rgb[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
except ImportError:
    try:
        import io
        from PIL import Image
        def to_jpeg(rgb):
            b = io.BytesIO(); Image.fromarray(rgb).save(b, "JPEG", quality=92); return b.getvalue()
    except ImportError:
        to_jpeg = None
if to_jpeg is None:
    print("skip  robot loop through the camera server (install opencv-python-headless or pillow)")
else:
    import subprocess
    import threading
    import camera_server as cs
    from ilc.robot_loop import RobotLoop

    class SimCamera(cs.Camera):
        """Stands in for the overhead camera: shows whatever the simulated robot drew last."""
        name = "simulated"
        def __init__(self):
            super().__init__(fps=5)
            self.jpeg = to_jpeg(render(cam, dots=dots, seed=7))
        def grab(self):
            return self.jpeg

    simcam = SimCamera().start()
    httpd = cs.build_server(simcam, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    folder = tempfile.mkdtemp()
    out = subprocess.run([sys.executable, str(ROOT / "pi/ilc/robot_loop.py"), "--server", url, "calibrate",
                          "--out", os.path.join(folder, "calibration.json")], capture_output=True, text=True)
    check(out.returncode == 0 and "saved" in out.stdout, "robot_loop.py calibrate: " + out.stdout.strip().splitlines()[-1])

    loop = RobotLoop(ILCSettings(nominal=nominal.flow_for(5)), server=url,
                     calibration_file=os.path.join(folder, "calibration.json"),
                     corrections=os.path.join(folder, "corrections"))
    robot = SimRobot(seed=9)
    k = [0]
    def draw(points, commands):     # what the robot team's code will do; here: the simulator
        k[0] += 1
        simcam.jpeg = to_jpeg(render(cam, robot.draw(points, commands), seed=100 + k[0]))
        time.sleep(0.4)             # the server's camera thread picks up the new frame
    import time
    errs = [loop.pancake("heart", draw, settle_s=0)["stats"]["rms_mm"] for _ in range(6)]
    # single pancakes vary randomly (syrup, batter), so compare the average of the last three
    check(np.mean(errs[-3:]) < 0.75 * errs[0], "RobotLoop.pancake() learns through the camera server: "
          + " -> ".join(f"{e:.2f}" for e in errs) + " mm")
    st = subprocess.run([sys.executable, str(ROOT / "pi/ilc/robot_loop.py"), "status",
                         "--corrections", os.path.join(folder, "corrections")], capture_output=True, text=True)
    check("heart" in st.stdout and "6 pancakes" in st.stdout, "robot_loop.py status: " + st.stdout.strip())
    check(len(os.listdir(os.path.join(folder, "corrections", "photos"))) == 6, "each pancake's photo is kept")
    httpd.shutdown()
print("ALL PASSED")
