"""A simulated syrup robot and overhead camera, for trying the ILC loop without hardware.

The physics are simple but have the effects that make real syrup lines uneven, and that
repeat every time the same shape is drawn (which is exactly what ILC can learn):

* Pump lag: flow follows the command after a dead time, then a first-order lag. So the
  start of each stroke comes out thin, and the pump keeps flowing after the robot stops,
  leaving a blob at the end of each stroke.
* Corners: the robot slows down for tight curves (acceleration limit), so the same flow
  puts more syrup there, and corners come out wide.
* The real pump and syrup don't match the numbers the controller assumes (thickness,
  maximum flow), so even straight lines start out too wide or thin.
* Pancake-to-pancake randomness (syrup temperature, batter), which ILC can't learn and
  shouldn't chase.

Line width model: syrup spreads to a roughly constant thickness h, so
    width = volume per mm / h = flow / (speed * h)
"""
from dataclasses import dataclass, replace

import numpy as np


@dataclass
class RobotModel:
    q_max: float = 250.0        # pump flow at command 1.0, mm^3/s
    dead_time: float = 0.15     # s before the pump responds
    tau: float = 0.30           # s, pump/tube lag time constant
    thickness: float = 1.25     # mm the syrup spreads to
    a_max: float = 250.0        # mm/s^2, robot acceleration limit (also on curves)
    spread: float = 1.2         # mm, syrup flowing along the line evens out the width a bit
    variation: float = 0.04     # pancake-to-pancake randomness (fraction, 1 sigma)


@dataclass
class Nominal:
    """What the controller *thinks* the robot does. Used for the first pancake."""
    speed: float = 25.0         # mm/s
    q_max: float = 250.0
    thickness: float = 1.5

    def flow_for(self, width):
        """Flow command (0..1) that should give `width` at the nominal speed."""
        return width * self.speed * self.thickness / self.q_max

    def speed_for(self, width, flow):
        return flow * self.q_max / (width * self.thickness)


@dataclass
class StrokeResult:
    points: np.ndarray      # (N, 2) mm
    width: np.ndarray       # (N,) actual syrup width at each point, mm
    blob_volume: float      # mm^3 that dripped at the end after the robot stopped
    speed: np.ndarray       # (N,) actual speed, mm/s


def speed_profile(points, v_cmd, a_max):
    """Actual robot speed at each point: starts and ends at rest, slows for curves."""
    d = np.diff(points, axis=0)
    seg = np.hypot(*d.T)
    n = len(points)
    v = np.array(v_cmd, float).copy()
    # curvature limit: v^2 * kappa <= a_max
    if n > 2:
        a1, a2 = np.arctan2(d[:-1, 1], d[:-1, 0]), np.arctan2(d[1:, 1], d[1:, 0])
        turn = np.abs((a2 - a1 + np.pi) % (2 * np.pi) - np.pi)
        kappa = turn / np.maximum(1e-6, 0.5 * (seg[:-1] + seg[1:]))
        v[1:-1] = np.minimum(v[1:-1], np.sqrt(a_max / np.maximum(kappa, 1e-6)))
    v[0] = v[-1] = 0.0
    for i in range(n - 1):              # can't speed up faster than a_max
        v[i + 1] = min(v[i + 1], np.sqrt(v[i] ** 2 + 2 * a_max * seg[i]))
    for i in range(n - 2, -1, -1):      # ... or slow down faster than a_max
        v[i] = min(v[i], np.sqrt(v[i + 1] ** 2 + 2 * a_max * seg[i]))
    return v, seg


def draw_stroke(points, flow_cmd, speed_cmd, model, gain=1.0, thick=1.0, dt=0.004):
    """Simulate one stroke. flow_cmd and speed_cmd are per point; returns StrokeResult."""
    v, seg = speed_profile(points, speed_cmd, model.a_max)
    v_seg = np.maximum(0.5 * (v[:-1] + v[1:]), 0.5)
    t_pts = np.concatenate([[0.0], np.cumsum(seg / v_seg)])
    t_end = t_pts[-1]
    t = np.arange(0.0, t_end + model.dead_time + 8 * model.tau, dt)
    # command as a function of time (held per segment, zero after the stroke)
    idx = np.clip(np.searchsorted(t_pts, t - model.dead_time, side="right") - 1, 0, len(points) - 2)
    u = np.where((t - model.dead_time >= 0) & (t - model.dead_time < t_end), np.asarray(flow_cmd)[idx], 0.0)
    q = np.empty_like(t)
    qk, k = 0.0, dt / model.tau
    q_max = model.q_max * gain
    for i in range(len(t)):
        qk += k * (q_max * u[i] - qk)
        q[i] = qk
    # volume laid on each segment = integral of flow while the robot is on it
    cum = np.concatenate([[0.0], np.cumsum(q) * dt])
    vol_at = np.interp(t_pts, np.concatenate([t, [t[-1] + dt]]), cum)
    seg_vol = np.diff(vol_at)
    h = model.thickness * thick
    seg_w = seg_vol / (h * np.maximum(seg, 1e-6))
    width = np.empty(len(points))
    width[0], width[-1] = seg_w[0], seg_w[-1]
    width[1:-1] = 0.5 * (seg_w[:-1] + seg_w[1:])
    width = _smooth(width, model.spread / max(1e-6, np.mean(seg)))
    blob = cum[-1] - vol_at[-1]
    return StrokeResult(points, width, float(blob), v)


def _smooth(x, sigma_pts):
    if sigma_pts < 0.3 or len(x) < 3:
        return x
    r = int(np.ceil(3 * sigma_pts))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_pts) ** 2)
    k /= k.sum()
    xp = np.pad(x, r, mode="edge")
    return np.convolve(xp, k, mode="valid")


class SimRobot:
    """Draws designs with given commands. One instance = one robot; each draw() = one pancake."""

    def __init__(self, model=None, nominal=None, control="flow", seed=0):
        self.model = model or RobotModel()
        self.nominal = nominal or Nominal()
        self.control = control
        self.rng = np.random.default_rng(seed)

    def draw(self, points_list, commands):
        """points_list: per-stroke (N,2) mm; commands: per-stroke (N,) flow or speed."""
        m = self.model
        gain = 1 + m.variation * self.rng.standard_normal()       # this pancake's pump
        thick = 1 + m.variation * self.rng.standard_normal()      # this pancake's syrup
        out = []
        for pts, cmd in zip(points_list, commands):
            cmd = np.asarray(cmd, float)
            if self.control == "flow":
                flow, speed = cmd, np.full(len(pts), self.nominal.speed)
            else:
                flow, speed = np.full(len(pts), self.nominal_flow), cmd
            out.append(draw_stroke(pts, flow, speed, m, gain, thick))
        return out

    @property
    def nominal_flow(self):
        """Constant pump command used when learning speed instead of flow."""
        return self.nominal.flow_for(5.0)


# --------------------------------------------------------------------------- camera
@dataclass
class Camera:
    """Maps robot mm to image pixels with a homography (so tilt is included)."""
    H: np.ndarray
    size: int = 800

    @staticmethod
    def overhead(size=800, px_per_mm=4.2, rotation_deg=7.0, offset=(14.0, -9.0), tilt=0.0003):
        """A camera roughly above the pancake: scaled, a little rotated and off-centre, slightly tilted."""
        a = np.radians(rotation_deg)
        c, s = np.cos(a), np.sin(a)
        H = np.array([[px_per_mm * c, -px_per_mm * s, size / 2 + offset[0]],
                      [px_per_mm * s, px_per_mm * c, size / 2 + offset[1]],
                      [tilt, -tilt * 0.5, 1.0]])
        return Camera(H, size)


def apply_h(H, pts):
    pts = np.asarray(pts, float)
    p = np.c_[pts, np.ones(len(pts))] @ H.T
    return p[:, :2] / p[:, 2:3]


def render(camera, strokes=(), dots=(), pancake_center=(1.5, -2.0), pancake_diam=150.0,
           seed=0, noise=4.0):
    """A photo (H, W, 3 uint8) of a pancake with the syrup from `strokes` (StrokeResults)
    and calibration `dots` ((x, y, diameter) in mm) on it."""
    rng = np.random.default_rng(seed)
    n = camera.size
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    mm = apply_h(np.linalg.inv(camera.H), np.c_[xx.ravel(), yy.ravel()]).reshape(n, n, 2)
    X, Y = mm[..., 0], mm[..., 1]
    img = np.empty((n, n, 3))
    img[:] = (40, 48, 57)                                                     # table
    R = pancake_diam / 2
    r = np.hypot(X - pancake_center[0], Y - pancake_center[1])
    img[r < R * 1.25] = (235, 232, 225)                                       # plate
    inside = r < R
    f = np.clip(r / R, 0, 1)[..., None]
    gold = (1 - f) * np.array([236, 186, 98]) + f * np.array([196, 132, 54])
    img[inside] = gold[inside]
    syrup = np.zeros((n, n), bool)
    span_k = np.abs(camera.H[:2, :2]).max() * 1.6

    def box(px, py, rad):
        c = apply_h(camera.H, [[px, py]])[0]
        span = rad * span_k + 3
        x0, x1 = int(max(0, c[0] - span)), int(min(n, c[0] + span + 1))
        y0, y1 = int(max(0, c[1] - span)), int(min(n, c[1] + span + 1))
        if x0 >= x1 or y0 >= y1:
            return None
        sl = (slice(y0, y1), slice(x0, x1))
        return sl, (X[sl] - px) ** 2 + (Y[sl] - py) ** 2 < rad ** 2

    for _ in range(260):                                                      # browning speckles
        a, rr = rng.uniform(0, 2 * np.pi), np.sqrt(rng.uniform()) * R * 0.95
        cx, cy = pancake_center[0] + np.cos(a) * rr, pancake_center[1] + np.sin(a) * rr
        rad = rng.uniform(0.6, 2.4)
        col = np.array([150 + rng.uniform(0, 40), 90 + rng.uniform(0, 30), 30])
        alpha = rng.uniform(0.08, 0.2)
        b = box(cx, cy, rad)
        if b:
            sl, m = b
            m = m & inside[sl]
            sub = img[sl]
            sub[m] = (1 - alpha) * sub[m] + alpha * col

    def stamp(px, py, rad):
        b = box(px, py, rad)
        if b:
            syrup[b[0]] |= b[1]

    for s in strokes:
        # dense points so the line has no gaps
        L = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(s.points, axis=0).T))])
        tt = np.arange(0, L[-1] + 1e-9, 0.35)
        px, py = np.interp(tt, L, s.points[:, 0]), np.interp(tt, L, s.points[:, 1])
        w = np.interp(tt, L, s.width)
        for x, y, ww in zip(px, py, w):
            if ww > 0.15:
                stamp(x, y, ww / 2)
        if s.blob_volume > 0:
            h = 1.25
            stamp(*s.points[-1], np.sqrt(s.blob_volume / (np.pi * h)))
    for x, y, d in dots:
        stamp(x, y, d / 2)
    img[syrup] = (58, 30, 17)
    img += rng.normal(0, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)
