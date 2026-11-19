"""Pure-geometry derivation of the 50 guideline points from FaceMesh contours.

No model dependency, no numpy: this module is unit tested on synthetic contours.

Design rule: contours are taken as *sets* of points. Corners are the extreme
points, upper/lower borders are split by the corner chord, and intermediate
points are sampled at the width fractions required by the guideline. This makes
the result independent of the order in which the mesh indices are listed.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _unique_sorted_x(points: Iterable[Point], mode: str) -> List[Point]:
    """Collapse points sharing an x into a single top (min y) or bottom (max y) point."""
    buckets: dict[float, float] = {}
    for x, y in points:
        key = round(x, 3)
        if key not in buckets:
            buckets[key] = y
        elif mode == "upper":
            buckets[key] = min(buckets[key], y)
        else:
            buckets[key] = max(buckets[key], y)
    return sorted(buckets.items())


def envelope(points: Sequence[Point], mode: str = "upper") -> List[Point]:
    """Monotone-in-x top/bottom edge of a point cloud."""
    return _unique_sorted_x(points, "upper" if mode == "upper" else "lower")


def y_at_x(curve: Sequence[Point], x: float) -> float:
    """y of a piecewise-linear curve at a given x (clamped at the ends)."""
    if not curve:
        raise ValueError("empty curve")
    if x <= curve[0][0]:
        return curve[0][1]
    if x >= curve[-1][0]:
        return curve[-1][1]
    for (x1, y1), (x2, y2) in zip(curve, curve[1:]):
        if x1 <= x <= x2:
            if abs(x2 - x1) < 1e-9:
                return (y1 + y2) / 2
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return curve[-1][1]


def resample_arclength(points: Sequence[Point], fractions: Sequence[float]) -> List[Point]:
    """Points at given arc-length fractions of an open polyline (0..1)."""
    pts = list(points)
    if not pts:
        raise ValueError("empty polyline")
    if len(pts) == 1:
        return [pts[0]] * len(fractions)

    seg = [_dist(a, b) for a, b in zip(pts, pts[1:])]
    total = sum(seg)
    if total < 1e-9:
        return [pts[0]] * len(fractions)

    out: List[Point] = []
    for f in fractions:
        target = max(0.0, min(1.0, f)) * total
        acc = 0.0
        for i, length in enumerate(seg):
            if acc + length >= target or i == len(seg) - 1:
                t = 0.0 if length < 1e-9 else (target - acc) / length
                out.append(_lerp(pts[i], pts[i + 1], min(1.0, max(0.0, t))))
                break
            acc += length
    return out


def ring_side(ring: Sequence[Point]) -> Tuple[Point, Point, List[Point], List[Point]]:
    """Split a closed contour into (leftmost, rightmost, upper, lower).

    Upper/lower are classified by the signed distance to the chord between the
    two extreme points. y grows downwards, so 'above the chord' is negative.
    """
    left = min(ring, key=lambda p: (p[0], p[1]))
    right = max(ring, key=lambda p: (p[0], -p[1]))

    dx = right[0] - left[0]
    dy = right[1] - left[1]
    norm = math.hypot(dx, dy) or 1.0

    upper: List[Point] = []
    lower: List[Point] = []
    for p in ring:
        if p == left or p == right:
            continue
        cross = (dx * (p[1] - left[1]) - dy * (p[0] - left[0])) / norm
        if cross < 0:
            upper.append(p)
        elif cross > 0:
            lower.append(p)
    return left, right, upper, lower


def _x_fractions(left: Point, right: Point, fractions: Sequence[float]) -> List[float]:
    width = right[0] - left[0]
    return [left[0] + width * f for f in fractions]


# --------------------------------------------------------------------------- #
# Per-skeleton derivations
# --------------------------------------------------------------------------- #

def eye8(ring: Sequence[Point]) -> List[Point]:
    """8-point closed eye contour: leftmost, 3 upper, rightmost, 3 lower."""
    left, right, upper, lower = ring_side(ring)
    up = envelope(upper or ring, "upper")
    down = envelope(lower or ring, "lower")

    xs_up = _x_fractions(left, right, (0.25, 0.50, 0.75))
    xs_down = _x_fractions(left, right, (0.75, 0.50, 0.25))

    pts = [left]
    pts += [(x, y_at_x(up, x)) for x in xs_up]
    pts.append(right)
    pts += [(x, y_at_x(down, x)) for x in xs_down]
    return pts


def brow5(points: Sequence[Point]) -> List[Point]:
    """5 points along the upper brow edge, leftmost end -> rightmost end."""
    edge = envelope(points, "upper")
    if len(edge) < 2:
        raise ValueError("brow needs at least two distinct x values")
    left = edge[0]
    right = edge[-1]
    pts = [left]
    pts += [(x, y_at_x(edge, x)) for x in _x_fractions(left, right, (0.25, 0.50, 0.75))]
    pts.append(right)
    return pts


def nose4(points: Sequence[Point]) -> List[Point]:
    """4 points evenly spaced along the bridge, top (nasion) -> base."""
    ordered = sorted(points, key=lambda p: (p[1], p[0]))
    return resample_arclength(ordered, (0.0, 1 / 3, 2 / 3, 1.0))


def lips_outer12(ring: Sequence[Point]) -> List[Point]:
    left, right, upper, lower = ring_side(ring)
    up = envelope(upper or ring, "upper")
    down = envelope(lower or ring, "lower")

    pts = [left]
    pts += [(x, y_at_x(up, x)) for x in
            _x_fractions(left, right, (0.18, 0.36, 0.50, 0.66, 0.84))]
    pts.append(right)
    pts += [(x, y_at_x(down, x)) for x in
            _x_fractions(left, right, (5 / 6, 4 / 6, 3 / 6, 2 / 6, 1 / 6))]
    return pts


def lips_inner8(ring: Sequence[Point]) -> List[Point]:
    left, right, upper, lower = ring_side(ring)
    up = envelope(upper or ring, "upper")
    down = envelope(lower or ring, "lower")

    pts = [left]
    pts += [(x, y_at_x(up, x)) for x in _x_fractions(left, right, (0.25, 0.50, 0.75))]
    pts.append(right)
    pts += [(x, y_at_x(down, x)) for x in _x_fractions(left, right, (0.75, 0.50, 0.25))]
    return pts


def derive_50(landmarks: Sequence[Point], mesh: dict) -> dict[str, List[Point]]:
    """landmarks: 468 (x, y) pixel points. Returns group name -> 50-scheme points."""
    lm = landmarks

    def pick(indices: Sequence[int]) -> List[Point]:
        return [lm[i] for i in indices]

    out: dict[str, List[Point]] = {
        "longmaytrai": brow5(pick(mesh["brow_image_left"])),
        "longmayphai": brow5(pick(mesh["brow_image_right"])),
        "songmui": nose4(pick(mesh["nose_bridge"])),
        "mattrai": eye8(pick(mesh["eye_image_left"])),
        "matphai": eye8(pick(mesh["eye_image_right"])),
        "moingoai": lips_outer12(pick(mesh["lips_outer"])),
        "moitrong": lips_inner8(pick(mesh["lips_inner"])),
    }
    return out


# --------------------------------------------------------------------------- #
# Sanity checks reported to the annotator as warnings
# --------------------------------------------------------------------------- #

def _segments(poly: Sequence[Point], closed: bool) -> List[Tuple[Point, Point]]:
    segs = list(zip(poly, poly[1:]))
    if closed and len(poly) > 2:
        segs.append((poly[-1], poly[0]))
    return segs


def _ccw(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    d1 = _ccw(p3, p4, p1)
    d2 = _ccw(p3, p4, p2)
    d3 = _ccw(p1, p2, p3)
    d4 = _ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def self_intersects(poly: Sequence[Point], closed: bool = True) -> bool:
    segs = _segments(poly, closed)
    for i, (a, b) in enumerate(segs):
        for j, (c, d) in enumerate(segs):
            if abs(i - j) <= 1:
                continue
            if closed and {i, j} == {0, len(segs) - 1}:
                continue
            if _segments_cross(a, b, c, d):
                return True
    return False


def point_in_polygon(pt: Point, poly: Sequence[Point]) -> bool:
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in _segments(poly, True):
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xin > x:
                inside = not inside
    return inside
