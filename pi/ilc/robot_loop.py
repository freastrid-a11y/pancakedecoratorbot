#!/usr/bin/env python3
"""Connecting the ILC loop to the real robot, through the camera server.

1. Calibrate once (and again whenever the camera or robot moves):

       python3 pi/ilc/robot_loop.py calibrate

   The robot first draws the calibration dots (CALIBRATION_DOTS in vision.py, in mm, on a
   pancake or paper), then this takes a photo from the camera server, finds the dots and
   saves pi/ilc/calibration.json.

2. In the robot's own code, for every pancake:

       import sys; sys.path.insert(0, "pi")
       from ilc.robot_loop import RobotLoop

       loop = RobotLoop()                       # loads calibration.json and corrections/
       def draw(points, commands):              # YOUR code: follow each stroke's points (mm),
           ...                                  # setting the pump (or speed) at each point
       report = loop.pancake("heart", draw)     # draw, signal syrup-done, photo, learn
       print(report["stats"])

3. See what has been learned:

       python3 pi/ilc/robot_loop.py status

The camera server (pi/camera_server.py) must be running.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ilc.designs import get_design                                  # noqa: E402
from ilc.learn import ILCSettings, Learner                          # noqa: E402
from ilc.vision import Calibration, calibrate, decode_image, write_png   # noqa: E402
from robot_client import snapshot, syrup_done                       # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CALIBRATION_FILE = os.path.join(HERE, "calibration.json")
CORRECTIONS = os.path.join(HERE, "corrections")
SERVER = "http://localhost:8000"


class RobotLoop:
    def __init__(self, settings=None, server=SERVER, calibration_file=CALIBRATION_FILE,
                 corrections=CORRECTIONS, save_photos=True):
        if not os.path.exists(calibration_file):
            raise FileNotFoundError(f"{calibration_file} not found: run `python3 pi/ilc/robot_loop.py calibrate` first")
        self.server = server
        self.learner = Learner(corrections, Calibration.load(calibration_file), settings or ILCSettings())
        self.photos = os.path.join(corrections, "photos") if save_photos else None

    def pancake(self, design_name, draw, learn=True, settle_s=0.5):
        """One trial: draw with the learned commands, photograph, measure, update."""
        design = get_design(design_name)
        points, commands = self.learner.commands(design)
        draw(points, commands)
        time.sleep(settle_s)                 # let the syrup stop spreading
        syrup_done(self.server)              # displays take their photo too
        rgb = decode_image(snapshot(self.server))
        report = self.learner.update(design, rgb, learn=learn)
        if self.photos:
            os.makedirs(self.photos, exist_ok=True)
            write_png(os.path.join(self.photos, f"{design.name}-{report['stats']['pancake']:03d}.png"), rgb)
        return report


def cmd_calibrate(a):
    rgb = decode_image(snapshot(a.server))
    cal = calibrate(rgb, threshold=a.threshold)
    cal.save(a.out)
    print(f"saved {a.out}: {cal.px_per_mm:.2f} px/mm, dots fit to within {cal.residual_px:.2f} px")
    if cal.residual_px > 3:
        print("warning: the fit is poor. Check that all dots are visible and nothing else on the pancake looks like syrup.")


def cmd_status(a):
    if not os.path.isdir(a.corrections):
        print("nothing learned yet")
        return
    for f in sorted(os.listdir(a.corrections)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(a.corrections, f)) as fh:
            d = json.load(fh)
        h = d.get("history", [])
        trend = " -> ".join(f"{x['rms_mm']:.2f}" for x in h[-6:])
        print(f"{d['design']:12} {d['control']:5} {len(h):3d} pancakes   width error (mm): {trend}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default=SERVER)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate", help="find the calibration dots in a camera photo")
    c.add_argument("--out", default=CALIBRATION_FILE)
    c.add_argument("--threshold", type=float, default=55.0)
    s = sub.add_parser("status", help="show what has been learned per design")
    s.add_argument("--corrections", default=CORRECTIONS)
    a = p.parse_args()
    {"calibrate": cmd_calibrate, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
