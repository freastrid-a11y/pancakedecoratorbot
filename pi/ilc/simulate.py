#!/usr/bin/env python3
"""Run the ILC loop on the simulated robot: draw, photograph, compare, adjust, repeat.

    python3 pi/ilc/simulate.py                       # all designs, 10 pancakes each
    python3 pi/ilc/simulate.py --design heart -n 15
    python3 pi/ilc/simulate.py --control speed       # learn travel speed instead of pump flow
    python3 pi/ilc/simulate.py --no-ilc              # baseline: same commands every pancake
    python3 pi/ilc/simulate.py --gain 0.3 --lead-mm 4

Prints the width error for every pancake and a before -> after summary, and saves
to test-output/ilc/: photos of the first and last pancake (side by side, with the
measured syrup outlined), and report-<control>.html with the photos and charts.
Needs only numpy.
"""
import argparse
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ilc.designs import BUILTIN, get_design                                     # noqa: E402
from ilc.learn import ILCSettings, Learner, stats                                # noqa: E402
from ilc.simulator import Camera, Nominal, RobotModel, SimRobot, render          # noqa: E402
from ilc.vision import CALIBRATION_DOT_MM, CALIBRATION_DOTS, apply_h, calibrate, write_png  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(design_names, pancakes=10, control="flow", gain=0.5, lead_mm=None, smooth_mm=6.0,
        learn=True, seed=1, out=None, quiet=False):
    say = (lambda *a: None) if quiet else print
    nominal = Nominal()
    camera = Camera.overhead()

    # 1. calibrate the camera from a photo of dots, as on the real robot
    dots = [(x, y, CALIBRATION_DOT_MM) for x, y in CALIBRATION_DOTS]
    calib = calibrate(render(camera, dots=dots, seed=seed))
    test = np.array([[0, 0], [60, 0], [0, -60], [-50, 50]], float)
    cal_err_mm = np.hypot(*(apply_h(calib.H, test) - apply_h(camera.H, test)).T).max() / calib.px_per_mm
    say(f"camera calibrated from {len(dots)} dots: {calib.px_per_mm:.2f} px/mm, "
        f"fit residual {calib.residual_px:.2f} px, position error {cal_err_mm:.2f} mm")

    if control == "flow":
        s = ILCSettings("flow", gain=gain, lead_mm=lead_mm, smooth_mm=smooth_mm,
                        nominal=nominal.flow_for(5.0), lo=0.05, hi=1.0)
    else:
        s = ILCSettings("speed", gain=gain, lead_mm=lead_mm, smooth_mm=smooth_mm,
                        nominal=nominal.speed, lo=8.0, hi=60.0)
    folder = tempfile.mkdtemp(prefix="ilc-sim-")
    reports = []
    learner = Learner(folder, calib, s)
    results = {}
    for name in design_names:
        design = get_design(name)
        robot = SimRobot(RobotModel(), nominal, control, seed=seed)
        say(f"\n{design.name}: {len(design.strokes)} stroke(s), learning {control}"
            + ("" if learn else " (ILC OFF)"))
        say("  pancake   measured RMS   true RMS   within ±1 mm   end blobs")
        rows, photos, profiles = [], [], []
        for k in range(1, pancakes + 1):
            points, cmds = learner.commands(design)
            drawn = robot.draw(points, cmds)
            photo = render(camera, drawn, seed=seed * 1000 + k)
            rep = learner.update(design, photo, learn=learn)
            m = rep["stats"]
            truth = stats([d.width for d in drawn], [st.width for st in design.strokes],
                          [x.valid for x in rep["measurements"]])
            blob = sum(d.blob_volume for d in drawn)
            rows.append({"pancake": k, "measured_rms": m["rms_mm"], "true_rms": truth["rms_mm"],
                         "within_1mm": m["within_1mm"], "blob_mm3": blob})
            bar = "█" * int(round(m["rms_mm"] * 10))
            say(f"  {k:5d}     {m['rms_mm']:6.2f} mm    {truth['rms_mm']:6.2f} mm      "
                f"{m['within_1mm'] * 100:5.0f}%       {blob:6.0f} mm³  {bar}")
            if k in (1, pancakes):
                photos.append(outlined(photo, rep["mask"], camera, points))
                profiles.append([(x.width.tolist(), x.valid.tolist()) for x in rep["measurements"]])
        results[design.name] = rows
        if out:
            os.makedirs(out, exist_ok=True)
            tag = f"{control}{'' if learn else '-noilc'}"
            for which, img in (("first", photos[0]), ("last", photos[-1])):
                write_png(os.path.join(out, f"{design.name}-{tag}-{which}.png"), img)
            gap = np.full((photos[0].shape[0], 12, 3), 255, np.uint8)
            path = os.path.join(out, f"{design.name}-{tag}.png")
            write_png(path, np.concatenate([photos[0], gap, photos[-1]], axis=1))
            reports.append({"design": design.name, "tag": tag, "rows": rows, "profiles": profiles,
                            "targets": [st.width for st in design.strokes]})
            say(f"  saved {os.path.relpath(path)} (pancake 1 | pancake {pancakes})")

    say(f"\nBefore -> after ({'learning ' + control if learn else 'learning OFF'}): "
        f"true width error, pancake 1 -> pancake {pancakes}")
    for name, rows in results.items():
        a, b = rows[0], rows[-1]
        change = (b["true_rms"] - a["true_rms"]) / a["true_rms"] * 100
        say(f"  {name:8} {a['true_rms']:5.2f} mm -> {b['true_rms']:5.2f} mm  ({change:+4.0f}%)   "
            f"within ±1 mm: {a['within_1mm'] * 100:3.0f}% -> {b['within_1mm'] * 100:3.0f}%   "
            f"end blobs: {a['blob_mm3']:4.0f} -> {b['blob_mm3']:4.0f} mm³")
    if out and reports:
        from ilc.report import write_report
        path = write_report(out, reports, control, learn, pancakes)
        say(f"\nReport with before/after photos and charts: {os.path.relpath(path)}")
    return results


def outlined(photo, mask, camera, points, crop=0.82):
    """Photo with the detected syrup outlined in magenta and the planned path in cyan, cropped."""
    img = photo.copy()
    edge = mask & ~(np.roll(mask, 1, 0) & np.roll(mask, -1, 0) & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))
    img[edge] = (255, 40, 200)
    for pts in points:
        for x, y in apply_h(camera.H, pts).round().astype(int):
            if 0 <= y < img.shape[0] and 0 <= x < img.shape[1]:
                img[y, x] = (60, 230, 255)
    n = img.shape[0]
    c = apply_h(camera.H, [[0, 0]])[0].astype(int)
    r = int(n * crop / 2)
    y0, x0 = max(0, c[1] - r), max(0, c[0] - r)
    return img[y0:y0 + 2 * r, x0:x0 + 2 * r]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--design", default="all", help="one of %s, a design JSON file, or 'all'" % ", ".join(BUILTIN))
    p.add_argument("-n", "--pancakes", type=int, default=10)
    p.add_argument("--control", choices=["flow", "speed"], default="flow")
    p.add_argument("--gain", type=float, default=0.5)
    p.add_argument("--lead-mm", type=float, default=None,
                   help="how far ahead the error is used (default: 8 for flow, 0 for speed)")
    p.add_argument("--smooth-mm", type=float, default=6.0)
    p.add_argument("--no-ilc", action="store_true", help="keep the first pancake's commands (baseline)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default=os.path.join(ROOT, "test-output", "ilc"))
    a = p.parse_args(argv)
    names = list(BUILTIN) if a.design == "all" else [a.design]
    run(names, a.pancakes, a.control, a.gain, a.lead_mm, a.smooth_mm, not a.no_ilc, a.seed, a.out)


if __name__ == "__main__":
    main()
