"""Measuring syrup lines in a camera photo.

* syrup_mask: which pixels are syrup. A Python port of the display's detection
  (script.js): find golden pancake pixels, take their median colour, and call anything
  clearly different "syrup".
* Calibration: a homography from robot millimetres to camera pixels, found from a few
  dots the robot draws at known positions (handles a slightly tilted camera too).
* measure: the syrup width and sideways offset at every point of every stroke.

Needs only numpy. decode_image() needs OpenCV or Pillow to read JPEG bytes.
"""
import itertools
import json
from dataclasses import dataclass

import numpy as np

# The calibration pattern: robot positions (mm) of the dots. Asymmetric on purpose
# (the extra dot at top right), so each dot in the photo can be matched to its position.
CALIBRATION_DOTS = np.array([[-40, -40], [40, -40], [40, 40], [-40, 40], [18, -40]], float)
CALIBRATION_DOT_MM = 6.0


# --------------------------------------------------------------------------- images
def decode_image(data):
    """JPEG/PNG bytes -> RGB uint8 array."""
    try:
        import cv2
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("not an image")
        return img[:, :, ::-1].copy()
    except ImportError:
        import io
        from PIL import Image
        return np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))


def write_png(path, rgb):
    """Save an RGB uint8 array as PNG with only the standard library."""
    import struct
    import zlib
    rgb = np.ascontiguousarray(rgb, np.uint8)
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# --------------------------------------------------------------------------- syrup
def pancake_pixels(rgb):
    """Golden-brown pixels (same rule as the display: hue 12-55 deg, sat >= .22, value >= .40)."""
    c = rgb.astype(float)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx, mn = c.max(-1), c.min(-1)
    dl = mx - mn
    with np.errstate(divide="ignore", invalid="ignore"):
        hue = np.where(mx == r, 60 * (((g - b) / dl) % 6),
                       np.where(mx == g, 60 * ((b - r) / dl + 2), 60 * ((r - g) / dl + 4)))
        sat = np.where(mx > 0, dl / mx, 0)
    hue = np.where(dl > 0, hue, 0)
    return (hue >= 12) & (hue <= 55) & (sat >= 0.22) & (mx / 255 >= 0.40)


def pancake_circle(rgb):
    """(cx, cy, radius) in pixels of the pancake, or None."""
    cand = pancake_pixels(rgb)
    ys, xs = np.nonzero(cand)
    if len(xs) < 0.03 * cand.size:
        return None
    cx, cy, rad = xs.mean(), ys.mean(), float(max(rgb.shape))
    for _ in range(3):
        d = np.hypot(xs - cx, ys - cy)
        k = d < rad * 1.05
        rad = float(np.percentile(d[k], 97))
        cx, cy = xs[k].mean(), ys[k].mean()
    return cx, cy, rad


def _shift_and(m, op):
    out = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            s = np.zeros_like(m)
            ys = slice(max(dy, 0), m.shape[0] + min(dy, 0))
            yd = slice(max(-dy, 0), m.shape[0] + min(-dy, 0))
            xs = slice(max(dx, 0), m.shape[1] + min(dx, 0))
            xd = slice(max(-dx, 0), m.shape[1] + min(-dx, 0))
            s[yd, xd] = m[ys, xs]
            out = op(out, s)
    return out


def syrup_mask(rgb, threshold=55.0, region=None):
    """Boolean mask of syrup pixels. `region` (bool mask) limits where syrup may be."""
    cand = pancake_pixels(rgb)
    circ = pancake_circle(rgb)
    if region is None:
        if circ is None:
            region = np.ones(cand.shape, bool)
        else:
            yy, xx = np.mgrid[0:rgb.shape[0], 0:rgb.shape[1]]
            region = np.hypot(xx - circ[0], yy - circ[1]) < circ[2] * 0.96
    ref = cand & region if (cand & region).any() else cand
    pc = np.median(rgb[ref].astype(float), axis=0) if ref.any() else np.array([210, 150, 70.0])
    d = rgb.astype(float) - pc
    dist = np.sqrt(2 * d[..., 0] ** 2 + 4 * d[..., 1] ** 2 + 3 * d[..., 2] ** 2) / 3
    m = (dist > threshold) & region
    m = _shift_and(_shift_and(m, np.logical_and), np.logical_or)   # remove specks
    return m


def blobs(mask, min_px=10):
    """Connected blobs of a mask: list of (centroid_x, centroid_y, area_px)."""
    try:
        from scipy import ndimage
        lab, n = ndimage.label(mask)
        out = []
        for i in range(1, n + 1):
            ys, xs = np.nonzero(lab == i)
            if len(xs) >= min_px:
                out.append((xs.mean(), ys.mean(), len(xs)))
        return out
    except ImportError:
        pass
    seen = np.zeros(mask.shape, bool)
    h, w = mask.shape
    out = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, xs, ys = [(y0, x0)], [], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            xs.append(x); ys.append(y)
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    stack.append((yy, xx))
        if len(xs) >= min_px:
            out.append((float(np.mean(xs)), float(np.mean(ys)), len(xs)))
    return out


# --------------------------------------------------------------------------- calibration
def fit_homography(src, dst):
    """3x3 H with dst ~ H @ src, from >= 4 point pairs (normalised DLT)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)

    def norm(p):
        c = p.mean(0)
        s = np.sqrt(2) / np.mean(np.hypot(*(p - c).T))
        return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])
    Ts, Td = norm(src), norm(dst)
    a = apply_h(Ts, src)
    b = apply_h(Td, dst)
    A = []
    for (x, y), (u, v) in zip(a, b):
        A.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        A.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    H = np.linalg.svd(np.asarray(A))[2][-1].reshape(3, 3)
    H = np.linalg.inv(Td) @ H @ Ts
    return H / H[2, 2]


def apply_h(H, pts):
    pts = np.asarray(pts, float)
    p = np.c_[pts, np.ones(len(pts))] @ H.T
    return p[:, :2] / p[:, 2:3]


@dataclass
class Calibration:
    H: np.ndarray               # robot mm -> image px
    residual_px: float = 0.0

    @property
    def px_per_mm(self):
        p = apply_h(self.H, [[0, 0], [1, 0], [0, 1]])
        return float((np.hypot(*(p[1] - p[0])) + np.hypot(*(p[2] - p[0]))) / 2)

    def save(self, path):
        with open(path, "w") as f:
            json.dump({"H": self.H.tolist(), "residual_px": self.residual_px}, f, indent=2)

    @staticmethod
    def load(path):
        with open(path) as f:
            d = json.load(f)
        return Calibration(np.asarray(d["H"], float), d.get("residual_px", 0.0))


def calibrate(rgb, robot_dots=CALIBRATION_DOTS, threshold=55.0):
    """Find the calibration dots in a photo and fit robot mm -> pixel.

    The robot draws a small dot of syrup at each of `robot_dots` on a pancake; this finds
    them, works out which is which, and returns a Calibration. Raises ValueError if the
    dots can't be found."""
    found = blobs(syrup_mask(rgb, threshold), min_px=8)
    n = len(robot_dots)
    if len(found) < n:
        raise ValueError(f"found {len(found)} dots in the photo, expected {n}")
    found = sorted(found, key=lambda b: -b[2])[:n]          # the n biggest blobs
    pts = np.array([(x, y) for x, y, _ in found])
    best = None
    for perm in itertools.permutations(range(n)):
        H = fit_homography(robot_dots, pts[list(perm)])
        err = np.hypot(*(apply_h(H, robot_dots) - pts[list(perm)]).T).max()
        # reject mirror-image fits: the robot's +x/+y must not flip in the image
        if np.linalg.det(H[:2, :2]) <= 0:
            continue
        if best is None or err < best[0]:
            best = (err, H)
    if best is None:
        raise ValueError("could not match the dots to the pattern")
    return Calibration(best[1], float(best[0]))


# --------------------------------------------------------------------------- measuring
@dataclass
class StrokeMeasurement:
    width: np.ndarray       # (N,) measured syrup width, mm (0 = no syrup found)
    offset: np.ndarray      # (N,) how far the line's centre is from the path, mm (+ = left of travel)
    valid: np.ndarray       # (N,) False where another stroke is too close to measure this one


def _normals(pts):
    d = np.gradient(pts, axis=0)
    d /= np.maximum(np.hypot(*d.T), 1e-9)[:, None]
    return np.stack([d[:, 1], -d[:, 0]], axis=1)


def reliable_points(points_list, widths, spacing):
    """Points whose cross-section only crosses their own line: not near other strokes, not
    where the same stroke comes back (like the start and end of a closed heart), and not
    at sharp corners (where the cross-section cuts through both arms of the corner)."""
    out = []
    allp = [(si, i, p) for si, pts in enumerate(points_list) for i, p in enumerate(pts)]
    P = np.array([p for _, _, p in allp])
    S = np.array([si for si, _, _ in allp])
    I = np.array([i for _, i, _ in allp])
    for si, pts in enumerate(points_list):
        ok = np.ones(len(pts), bool)
        clear = 1.6 * widths[si]
        for i, p in enumerate(pts):
            d = np.hypot(*(P - p).T)
            near = d < clear
            other = near & ((S != si) | (np.abs(I - i) * spacing > 1.5 * clear))
            ok[i] = not other.any()
        # sharp corners: heading changes a lot within about one line width either side
        k = max(1, int(np.ceil(1.5 * widths[si] / spacing)))
        if len(pts) > 2 * k:
            d = np.diff(pts, axis=0)
            head = np.arctan2(d[:, 1], d[:, 0])
            for i in range(len(pts)):
                a, b = max(0, i - k), min(len(d) - 1, i + k - 1)
                turn = np.abs((np.diff(head[a:b + 1]) + np.pi) % (2 * np.pi) - np.pi).sum()
                if turn > np.radians(50):
                    ok[i] = False
        out.append(ok)
    return out


def measure(rgb, points_list, widths, calib, threshold=55.0, spacing=2.0, step=0.15):
    """Measure syrup width/offset at every stroke point. Returns (list of StrokeMeasurement, mask)."""
    h, w = rgb.shape[:2]
    # only look near the strokes, so plate and table never count as syrup
    allpts = np.vstack(points_list)
    px = apply_h(calib.H, allpts)
    reach = max(widths) * 3.0 * calib.px_per_mm
    region = np.zeros((h, w), bool)
    yy, xx = np.mgrid[0:h, 0:w]
    for cx, cy in px:
        x0, x1 = int(max(0, cx - reach)), int(min(w, cx + reach + 1))
        y0, y1 = int(max(0, cy - reach)), int(min(h, cy + reach + 1))
        if x0 < x1 and y0 < y1:
            region[y0:y1, x0:x1] |= (xx[y0:y1, x0:x1] - cx) ** 2 + (yy[y0:y1, x0:x1] - cy) ** 2 < reach ** 2
    mask = syrup_mask(rgb, threshold, region)
    valid = reliable_points(points_list, widths, spacing)
    out = []
    for si, pts in enumerate(points_list):
        target = widths[si]
        reach_mm = 2.5 * target
        t = np.arange(-reach_mm, reach_mm + 1e-9, step)
        c0 = len(t) // 2
        nrm = _normals(pts)
        samp = pts[:, None, :] + t[None, :, None] * nrm[:, None, :]          # (N, T, 2) mm
        sp = apply_h(calib.H, samp.reshape(-1, 2)).reshape(len(pts), len(t), 2)
        xi = np.clip(np.round(sp[..., 0]).astype(int), 0, w - 1)
        yi = np.clip(np.round(sp[..., 1]).astype(int), 0, h - 1)
        line = mask[yi, xi]
        inside = (sp[..., 0] >= 0) & (sp[..., 0] < w) & (sp[..., 1] >= 0) & (sp[..., 1] < h)
        line &= inside
        width = np.zeros(len(pts))
        offset = np.full(len(pts), np.nan)
        near = int(round(target / step))
        for i in range(len(pts)):
            row = line[i]
            if row[c0]:
                start = c0
            else:   # line missed the path: nearest syrup within one target width
                cand = [j for j in range(max(0, c0 - near), min(len(t), c0 + near + 1)) if row[j]]
                if not cand:
                    continue
                start = min(cand, key=lambda j: abs(j - c0))
            lo = hi = start
            while lo > 0 and row[lo - 1]:
                lo -= 1
            while hi < len(t) - 1 and row[hi + 1]:
                hi += 1
            width[i] = (hi - lo + 1) * step
            offset[i] = (t[lo] + t[hi]) / 2
        out.append(StrokeMeasurement(width, offset, valid[si]))
    return out, mask
