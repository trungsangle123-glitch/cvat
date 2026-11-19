"""A/B two backends on the same frames: how far apart are their 50 points?

Run it inside an image that has both mediapipe and insightface installed:

    docker run --rm \
      -v D:\\frames:/data:ro -v D:\\face50\\models:/app/models:ro \
      cvat-face50:latest python tools/ab_backends.py /data/frame_0001.jpg

Prints the distance between the two 50-point sets (the same ordered list the
extension would write) and saves ``<name>_ab.png``: green = facemesh, blue =
insight106, with the point id printed next to every fifth facemesh point.

If the median distance is tens of pixels, the 106-index tables in
``app/face50/mapping106.py`` do not match the model and must be fixed before
using ``FACE50_BACKEND=insight106``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import numpy as np
from PIL import Image, ImageDraw

from app.face50.geometry import derive_50
from app.face50.model import FaceMeshBackend, InsightFaceBackend, pick_face
from app.face50.topology import GROUPS, MESH

Point = Tuple[float, float]


def flatten(groups: Dict[str, List[Point]]) -> List[Point]:
    out: List[Point] = []
    for group in GROUPS:
        out.extend(groups[group.name])
    return out


def analyse(path: Path) -> None:
    image = Image.open(path).convert("RGB")
    rgb = np.asarray(image)
    height, width = rgb.shape[:2]

    mesh = FaceMeshBackend()
    insight = InsightFaceBackend()

    mesh_face = pick_face(mesh.detect(rgb), width, height)
    ins_face = pick_face(insight.detect(rgb), width, height)

    if mesh_face is None or ins_face is None:
        print(f"{path.name}: skipped (facemesh={mesh_face is not None}, "
              f"insight106={ins_face is not None})")
        return

    a = flatten(derive_50(mesh_face.points, MESH))
    b = flatten(ins_face.groups or {})
    assert len(a) == len(b) == 50, (len(a), len(b))

    d = np.hypot(*(np.asarray(a) - np.asarray(b)).T)
    print(f"{path.name}: yaw facemesh={mesh_face.yaw_ratio:+.2f} "
          f"insight106={ins_face.yaw_ratio:+.2f}")
    print(f"  distance px  median={np.median(d):.1f} mean={d.mean():.1f} "
          f"p95={np.percentile(d, 95):.1f} max={d.max():.1f}")

    for group in GROUPS:
        ids = list(range(group.first, group.first + group.count))
        part = d[ids]
        print(f"  {group.name:<11} median={np.median(part):5.1f} max={part.max():5.1f}")

    draw = ImageDraw.Draw(image)
    for i, (x, y) in enumerate(b):
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(0, 160, 255))
    for i, (x, y) in enumerate(a):
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(0, 200, 0))
        if i % 5 == 0:
            draw.text((x + 4, y - 10), str(i), fill=(255, 220, 0))
    out = path.with_name(path.stem + "_ab.png")
    image.save(out)
    print(f"  wrote {out}")


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        analyse(Path(arg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
