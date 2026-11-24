"""Syrup designs as strokes the robot follows.

A design is a list of strokes. A stroke is a path in millimetres in the robot's
coordinates (design centred on 0,0, +x right, +y towards the camera image's bottom)
plus the line width we want. The ILC code splits each stroke into points every
`spacing` mm, and keeps one command (pump flow or travel speed) per point.

Designs can also be loaded from JSON:

    {"name": "my-heart", "width_mm": 5,
     "strokes": [[[0, 23], [-10, 5], ...], [[...], ...]]}
"""
import json
import math
from dataclasses import dataclass, field

import numpy as np

# The display's demo pancakes are drawn at 226 px radius for a 150 mm pancake.
DEMO_MM_PER_PX = 75.0 / 226.0


@dataclass
class Stroke:
    path: np.ndarray            # (N, 2) mm, the robot's path
    width: float = 5.0          # target line width, mm


@dataclass
class Design:
    name: str
    strokes: list = field(default_factory=list)

    def resampled(self, spacing=2.0):
        """Points every `spacing` mm along each stroke: list of (N_i, 2) arrays."""
        return [resample(s.path, spacing) for s in self.strokes]

    def to_json(self):
        return {"name": self.name,
                "strokes": [{"width_mm": s.width, "path": np.round(s.path, 3).tolist()} for s in self.strokes]}


def resample(path, spacing):
    """Evenly spaced points along a polyline, always including both ends."""
    path = np.asarray(path, float)
    seg = np.hypot(*np.diff(path, axis=0).T)
    keep = np.concatenate([[True], seg > 1e-9])
    path, seg = path[keep], seg[seg > 1e-9]
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(round(s[-1] / spacing)) + 1)
    t = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(t, s, path[:, 0]), np.interp(t, s, path[:, 1])], axis=1)


def _bezier(p0, p1, p2, p3, n=80):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def _arc(cx, cy, r, a0, a1, n=120):
    a = np.linspace(a0, a1, n)
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], axis=1)


def _demo_px(points):
    return np.asarray(points, float) * DEMO_MM_PER_PX


def heart(width=5.0):
    a = _bezier((0, 70), (-130, -10), (-70, -125), (0, -55))
    b = _bezier((0, -55), (70, -125), (130, -10), (0, 70))
    return Design("heart", [Stroke(_demo_px(np.vstack([a, b[1:]])), width)])


def star(width=5.0):
    pts = [(math.cos(-math.pi / 2 + i * math.pi / 5) * (42 if i % 2 else 100),
            math.sin(-math.pi / 2 + i * math.pi / 5) * (42 if i % 2 else 100)) for i in range(11)]
    return Design("star", [Stroke(_demo_px(pts), width)])


def spiral(width=5.0):
    t = np.arange(0, 4.6 * math.pi, 0.05)
    r = 6 + 10.5 * t
    return Design("spiral", [Stroke(_demo_px(np.stack([np.cos(t) * r, np.sin(t) * r], 1)), width)])


def smiley(width=5.0):
    face = _arc(0, 0, 92, 0, 2 * math.pi, 200)
    mouth = _arc(0, 14, 43, 0.12 * math.pi, 0.88 * math.pi, 80)
    return Design("smiley", [Stroke(_demo_px(face), width), Stroke(_demo_px(mouth), width)])


def letter_a(width=5.0):
    apex, left, right = (0, -30), (-22, 27), (22, 27)
    yb = 8
    xb = 22 * (yb + 30) / 57
    return Design("A", [Stroke(np.array([left, apex, right], float), width),
                        Stroke(np.array([(-xb, yb), (xb, yb)], float), width)])


BUILTIN = {"heart": heart, "star": star, "spiral": spiral, "smiley": smiley, "A": letter_a}


def get_design(name_or_path, width=5.0):
    """A built-in design by name, or a design JSON file."""
    if name_or_path in BUILTIN:
        return BUILTIN[name_or_path](width)
    with open(name_or_path) as f:
        d = json.load(f)
    default_w = d.get("width_mm", width)
    strokes = []
    for s in d["strokes"]:
        if isinstance(s, dict):
            strokes.append(Stroke(np.asarray(s["path"], float), s.get("width_mm", default_w)))
        else:
            strokes.append(Stroke(np.asarray(s, float), default_w))
    return Design(d.get("name", name_or_path), strokes)
