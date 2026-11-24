"""Iterative learning control (ILC) for syrup line width.

Each pancake is one trial. After it, the photo gives the width error at every point of
every stroke, and the command for the next pancake becomes

    command_next(i) = Q( command(i) - gain * scale * error(i + lead) )

* error is relative: (measured - target) / target.
* lead shifts the correction earlier along the path. The pump reacts late, so the
  syrup at point i+lead was caused by the command at point i.
* Q is a moving average along the path, so camera noise doesn't make the pump jitter.
* scale turns relative width error into command units: for flow, the nominal flow
  (too wide -> less flow); for speed, minus the nominal speed (too wide -> faster).
* Points where the width can't be measured (crossings) get no correction.

Corrections are saved per design in a JSON file, with the error history, so each
letter and shape keeps improving across pancakes and robot restarts.
"""
import json
import os
import time
from dataclasses import asdict, dataclass

import numpy as np

from .designs import Design
from .vision import Calibration, measure


@dataclass
class ILCSettings:
    control: str = "flow"       # "flow" (pump) or "speed" (travel speed)
    spacing: float = 2.0        # mm between control points
    gain: float = 0.5           # fraction of the error corrected per pancake (0.3-0.7)
    lead_mm: float = None       # flow: ~ speed x (pump dead time + lag), default 8 mm;
                                # speed acts at once, default 0
    smooth_mm: float = 6.0      # Q-filter width along the path
    nominal: float = 0.75       # starting command: flow (0..1) or speed (mm/s)
    lo: float = 0.05            # command limits
    hi: float = 1.0
    threshold: float = 55.0     # syrup detection threshold (same as the display's slider)

    def __post_init__(self):
        if self.lead_mm is None:
            self.lead_mm = 8.0 if self.control == "flow" else 0.0


def moving_average(x, n):
    if n <= 1 or len(x) < 3:
        return x
    n = min(n, len(x) if len(x) % 2 else len(x) - 1)
    r = n // 2
    xp = np.pad(x, r, mode="edge")
    return np.convolve(xp, np.ones(2 * r + 1) / (2 * r + 1), mode="valid")


def ilc_update(cmd, width, target, valid, s: ILCSettings):
    """One ILC step for one stroke. Returns the next command array."""
    cmd = np.asarray(cmd, float)
    e = np.clip((np.asarray(width) - target) / target, -1.0, 1.5)
    e = np.where(valid, e, 0.0)
    lead = int(round(s.lead_mm / s.spacing))
    if lead > 0:
        e = np.concatenate([e[lead:], np.full(lead, e[-1])])   # error at i+lead drives point i
    scale = s.nominal if s.control == "flow" else -s.nominal
    new = cmd - s.gain * scale * e
    new = moving_average(new, int(round(s.smooth_mm / s.spacing)) | 1)
    return np.clip(new, s.lo, s.hi)


def stats(width, target, valid):
    """Summary numbers for one pancake (over measurable points)."""
    w = np.concatenate([np.asarray(m)[np.asarray(v)] for m, v in zip(width, valid)])
    t = np.concatenate([np.full(int(np.sum(v)), tt) for tt, v in zip(target, valid)])
    e = w - t
    return {"rms_mm": float(np.sqrt(np.mean(e ** 2))), "max_mm": float(np.max(np.abs(e))),
            "within_1mm": float(np.mean(np.abs(e) <= 1.0)), "gaps": int(np.sum(w == 0)),
            "points": int(len(w))}


class CorrectionStore:
    """corrections/<design>.json: the learned command per stroke point, plus history."""

    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

    def path(self, name):
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return os.path.join(self.folder, safe + ".json")

    def load(self, name):
        try:
            with open(self.path(name)) as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def save(self, name, data):
        tmp = self.path(name) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path(name))


class Learner:
    """What the robot code uses:

        learner = Learner("corrections", calibration, ILCSettings(control="flow"))
        points, cmds = learner.commands(design)    # draw each stroke with these
        ... draw, then take a photo ...
        report = learner.update(design, rgb_photo)
    """

    def __init__(self, folder, calibration: Calibration, settings: ILCSettings = None):
        self.store = CorrectionStore(folder)
        self.calib = calibration
        self.s = settings or ILCSettings()

    def _state(self, design: Design):
        points = design.resampled(self.s.spacing)
        data = self.store.load(design.name)
        ok = (data and data.get("control") == self.s.control and data.get("spacing") == self.s.spacing
              and [len(c) for c in data["commands"]] == [len(p) for p in points])
        if not ok:   # new design, or the design/settings changed: start from nominal
            data = {"design": design.name, "control": self.s.control, "spacing": self.s.spacing,
                    "commands": [[self.s.nominal] * len(p) for p in points], "history": []}
        return points, data

    def commands(self, design: Design):
        """(points per stroke, command per point) for the next pancake."""
        points, data = self._state(design)
        return points, [np.asarray(c, float) for c in data["commands"]]

    def update(self, design: Design, rgb, learn=True):
        """Measure the photo of the pancake just drawn, and (if learn) save new commands.
        Returns a report dict: stats, plus the per-stroke measurements."""
        points, data = self._state(design)
        targets = [s.width for s in design.strokes]
        meas, mask = measure(rgb, points, targets, self.calib, self.s.threshold, self.s.spacing)
        st = stats([m.width for m in meas], targets, [m.valid for m in meas])
        st["pancake"] = len(data["history"]) + 1
        st["time"] = time.time()
        if learn:
            data["commands"] = [ilc_update(c, m.width, t, m.valid, self.s).round(4).tolist()
                                for c, m, t in zip(data["commands"], meas, targets)]
            data["history"].append(st)
            data["settings"] = asdict(self.s)
            self.store.save(design.name, data)
        return {"stats": st, "measurements": meas, "mask": mask}

    def reset(self, design_name):
        """Forget what was learned for one design."""
        try:
            os.remove(self.store.path(design_name))
        except FileNotFoundError:
            pass
