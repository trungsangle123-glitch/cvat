"""Generate the CVAT label definitions for Facial Landmark-50.

The task/job must contain 7 skeleton labels whose sublabels are the 50 points.
Point ids live in the sublabel names (`p0` ... `p49`); the extension and the
server both map sublabels by the last integer in the name.

`build_labels()` is the single source of truth for `labels_raw.json`.
Run it directly to regenerate the file:

    python tools/labels_spec.py --out labels_raw.json

The SVG template is what CVAT uses when a skeleton is drawn by hand, so it has
to reference every sublabel (`data-label-name="pN"`, rewritten by the server to
`data-label-id` on creation). Coordinates are a schematic face, only for
convenience - the model writes absolute pixel coordinates.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SERVER_DIR = TOOLS_DIR.parent

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.face50.topology import GROUPS, Group  # noqa: E402

COLORS = {
    "longmaytrai": "#e11d48",
    "longmayphai": "#f97316",
    "songmui": "#eab308",
    "mattrai": "#22c55e",
    "matphai": "#14b8a6",
    "moingoai": "#3b82f6",
    "moitrong": "#a855f7",
}

# Schematic positions in a 100 x 100 template box (SVG y grows downwards).
_BROWS = {
    "longmaytrai": [(20.0, 33.0), (24.0, 30.0), (29.0, 28.5), (34.0, 29.0), (38.0, 31.0)],
    "longmayphai": [(62.0, 31.0), (66.0, 29.0), (71.0, 28.5), (76.0, 30.0), (80.0, 33.0)],
}
_NOSE = [(50.0, 36.0), (49.5, 43.0), (49.0, 50.0), (48.5, 57.0)]
_ELLIPSES = {
    "mattrai": ((30.0, 42.0), 8.0, 4.0),
    "matphai": ((70.0, 42.0), 8.0, 4.0),
    "moingoai": ((50.0, 72.0), 13.0, 6.5),
    "moitrong": ((50.0, 72.0), 7.0, 3.2),
}


def _ring(center: tuple[float, float], rx: float, ry: float, count: int) -> list[tuple[float, float]]:
    """Closed contour, clockwise on screen, starting at the leftmost point.

    Screen coordinates have y growing downwards, so a decreasing angle walks
    clockwise: 180deg (left) -> 270deg (top) -> 0deg (right) -> 90deg (bottom).
    """
    cx, cy = center
    points = []
    for i in range(count):
        angle = math.radians(180 - (360.0 / count) * i)
        points.append((round(cx + rx * math.cos(angle), 2), round(cy + ry * math.sin(angle), 2)))
    return points


def group_points(group: Group) -> list[tuple[float, float]]:
    if group.name in _BROWS:
        return list(_BROWS[group.name])
    if group.name == "songmui":
        return list(_NOSE)
    if group.name in _ELLIPSES:
        center, rx, ry = _ELLIPSES[group.name]
        return _ring(center, rx, ry, group.count)
    raise KeyError(f"no template layout for group {group.name!r}")


def build_svg(groups=GROUPS) -> str:
    """Inner SVG markup (CVAT stores the template without the <svg> wrapper)."""
    parts: list[str] = []
    points: dict[int, tuple[float, float]] = {}

    for group in groups:
        for offset, (x, y) in enumerate(group_points(group)):
            point_id = group.first + offset
            points[point_id] = (x, y)
            parts.append(
                f'<circle data-type="element" data-element-id="{point_id}" '
                f'data-node-id="{point_id}" data-label-name="p{point_id}" '
                f'cx="{x}" cy="{y}" r="0.8" fill="{COLORS[group.name]}" '
                f'stroke="black" stroke-width="0.1" />'
            )

    edges: list[tuple[int, int]] = []
    for group in groups:
        ids = list(range(group.first, group.first + group.count))
        edges.extend(zip(ids, ids[1:]))
        if group.closed:
            edges.append((ids[-1], ids[0]))

    for start, end in edges:
        (x1, y1), (x2, y2) = points[start], points[end]
        parts.append(
            f'<line data-type="edge" data-node-from="{start}" data-node-to="{end}" '
            f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="black" stroke-width="0.5" />'
        )

    return "".join(parts)


def build_labels() -> list[dict]:
    """CVAT label payload: 7 skeletons, sublabels p0..p49, no attributes."""
    labels = []
    for group in GROUPS:
        sublabels = [
            {
                "name": f"p{group.first + offset}",
                "color": COLORS[group.name],
                "type": "points",
                "attributes": [],
            }
            for offset in range(group.count)
        ]
        labels.append(
            {
                "name": group.name,
                "color": COLORS[group.name],
                "type": "skeleton",
                "attributes": [],
                "svg": build_svg((group,)),
                "sublabels": sublabels,
            }
        )
    return labels


def build_task_payload() -> dict:
    return {"labels": build_labels()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=SERVER_DIR / "labels_raw.json",
        help="where to write labels_raw.json (default: face50-server/labels_raw.json)",
    )
    parser.add_argument("--print", dest="print_only", action="store_true", help="print, do not write")
    args = parser.parse_args(argv)

    text = json.dumps(build_labels(), indent=2, ensure_ascii=False)
    if args.print_only:
        print(text)
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    total = sum(len(label["sublabels"]) for label in build_labels())
    print(f"wrote {args.out} (7 labels, {total} sublabels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
