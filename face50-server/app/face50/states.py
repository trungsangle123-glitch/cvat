"""Guideline section 3/3.1/4: per-point CVAT states.

CVAT has exactly two flags per point, so the three guideline states map to:

    visible   Outside=0, Occluded=0
    occluded  Outside=0, Occluded=1
    outside   Outside=1

The landmark model cannot detect occluders (hands, sunglasses, wheel), so the
state is a heuristic from:
  * image bounds,
  * head yaw (far-side regions lose evidence progressively),
  * guideline 3.1 thresholds per skeleton.

Annotators are required to review every frame anyway (guideline 1), and the
extension shows the counts per state so mistakes are visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .geometry import point_in_polygon, self_intersects
from .topology import FAR_SIDE_GROUPS, GROUPS, Group

VISIBLE = "visible"
OCCLUDED = "occluded"
OUTSIDE = "outside"


@dataclass
class StateConfig:
    strict: bool = True            # 3.1: below threshold -> Outside the whole skeleton
    far_side_start: float = 0.45   # |yaw ratio| where the far side starts losing points
    far_side_full: float = 0.85    # |yaw ratio| where the whole far group is gone
    border_px: float = 0.0         # extra margin treated as outside


@dataclass
class PointState:
    id: int
    x: float
    y: float
    state: str


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _occluded_indices(group: Group, yaw_ratio: float, cfg: StateConfig) -> set[int]:
    """Indices of a far-side group that are considered hidden.

    The far end of the contour loses evidence first; on closed contours the
    neighbouring point on the other border goes with it.
    """
    if yaw_ratio == 0:
        return set()
    sign = 1 if yaw_ratio > 0 else -1
    if group.name not in FAR_SIDE_GROUPS[sign]:
        return set()

    magnitude = abs(yaw_ratio)
    if magnitude <= cfg.far_side_start:
        return set()
    span = max(1e-6, cfg.far_side_full - cfg.far_side_start)
    ratio = min(1.0, (magnitude - cfg.far_side_start) / span)
    count = int(round(group.count * ratio))
    if count <= 0:
        return set()

    far_first = yaw_ratio > 0  # image-left groups are far when the nose points right
    n = group.count
    order = sorted(range(n), key=lambda i: min(i, n - 1 - i) if group.closed else i)
    if not far_first:
        order = [n - 1 - i for i in order]
    return set(order[:count])


def assign_states(
    points_by_group: Dict[str, Sequence[Tuple[float, float]]],
    width: int,
    height: int,
    yaw_ratio: float,
    cfg: StateConfig | None = None,
) -> Tuple[List[PointState], List[str]]:
    cfg = cfg or StateConfig()
    out: List[PointState] = []
    warnings: List[str] = []

    max_x = max(0.0, width - 1.0)
    max_y = max(0.0, height - 1.0)

    for group in GROUPS:
        pts = list(points_by_group.get(group.name, []))
        if len(pts) != group.count:
            raise ValueError(f"{group.name}: expected {group.count} points, got {len(pts)}")

        hidden = _occluded_indices(group, yaw_ratio, cfg)

        states: List[str] = []
        coords: List[Tuple[float, float]] = []

        for i, (x, y) in enumerate(pts):
            px = _clamp(x, 0.0, max_x)
            py = _clamp(y, 0.0, max_y)
            coords.append((px, py))

            off_frame = (
                x < -cfg.border_px or y < -cfg.border_px
                or x > max_x + cfg.border_px or y > max_y + cfg.border_px
            )
            if off_frame:
                states.append(OUTSIDE)
                continue

            states.append(OCCLUDED if i in hidden else VISIBLE)

        visible = sum(1 for s in states if s == VISIBLE)
        if cfg.strict and visible < group.threshold:
            states = [OUTSIDE] * group.count
        elif not cfg.strict and visible < group.threshold:
            # keep what is in frame, but never claim it is visible
            states = [OUTSIDE if s == OUTSIDE else OCCLUDED for s in states]

        for i, (state, (px, py)) in enumerate(zip(states, coords)):
            out.append(PointState(group.first + i, round(px, 1), round(py, 1), state))

        if all(s == OUTSIDE for s in states):
            warnings.append(f"{group.name}: outside (visible {visible}/{group.count} < {group.threshold})")
        elif self_intersects(pts, group.closed):
            warnings.append(f"{group.name}: contour tu cat (kiem tra lai thu tu diem)")

    # topology check from guideline 7: moitrong must stay inside moingoai
    outer = list(points_by_group.get("moingoai", []))
    inner = list(points_by_group.get("moitrong", []))
    if len(outer) >= 3 and inner:
        leaked = sum(0 if point_in_polygon(p, outer) else 1 for p in inner)
        if leaked:
            warnings.append(f"moitrong: {leaked}/8 diem nam ngoai moingoai")

    return out, warnings


def summarize(states: Sequence[PointState]) -> Dict[str, int]:
    return {
        VISIBLE: sum(1 for s in states if s.state == VISIBLE),
        OCCLUDED: sum(1 for s in states if s.state == OCCLUDED),
        OUTSIDE: sum(1 for s in states if s.state == OUTSIDE),
    }
