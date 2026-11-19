"""InsightFace 2d106 landmarks -> guideline 50-point mapping.

`2d106det` (part of the buffalo_l pack) is a stronger, older-people/profile-robust
landmark model than the MediaPipe face mesh, but it has its own topology. This
module maps it onto the same 7 skeletons, reusing the order-independent helpers
from `geometry.py` (corners from extremes, fraction sampling from the width).

Index layout of the 106-point model (matches the published 106->68 conversion
tables, and the eye/brow/mouth ranges used by insightface tooling):

    0-32    face contour (jaw)
    33-42   image-left eye          (10 points, 6 of them map to dlib 36-41)
    43-51   image-left eyebrow      (9)
    52-71   mouth                   (12 outer + 8 inner)
    72-86   nose                    (72-74 bridge, 86 bridge base, 75-86 base)
    87-96   image-right eye         (10)
    97-105  image-right eyebrow     (9)

Image-left/image-right follow the guideline ("decided on the image"), i.e.
`longmaytrai`/`mattrai` are on the left side of the picture.

Everything here is pure geometry: no model dependency, so it is unit tested with
synthetic landmarks.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .geometry import Point, brow5, eye8, lips_inner8, lips_outer12, nose4

# --- index sets (membership matters, order does not) ----------------------- #
EYE_IMAGE_LEFT = tuple(range(33, 43))
EYE_IMAGE_RIGHT = tuple(range(87, 97))
BROW_IMAGE_LEFT = tuple(range(43, 52))
BROW_IMAGE_RIGHT = tuple(range(97, 106))

# 52-71 -> dlib 48-59 (outer ring) and 60-67 (inner ring)
LIPS_OUTER = (52, 64, 63, 71, 67, 68, 61, 58, 59, 53, 56, 55)
LIPS_INNER = (65, 66, 62, 70, 69, 57, 60, 54)

NOSE_BRIDGE = (72, 73, 74, 86)

# pose helpers
NOSE_TIP = 86
FACE_CONTOUR = tuple(range(33))

ID_COUNT = 106


def _pick(landmarks: Sequence[Point], indices: Sequence[int]) -> List[Point]:
    return [landmarks[i] for i in indices]


def pose(landmarks: Sequence[Point], width: int = 0, height: int = 0) -> Tuple[float, float]:
    """Cheap yaw descriptor in [-1, 1] plus an approximate angle, same convention
    as the MediaPipe backend: positive means the nose points to image right.

    Uses the nose tip against the eye midpoint, so the sign is fixed by image
    geometry and does not depend on which jaw index is which side.
    """
    if len(landmarks) < ID_COUNT:
        return 0.0, 0.0
    # image-left eye centroid, image-right eye centroid, and the nose tip
    lx = sum(landmarks[i][0] for i in EYE_IMAGE_LEFT) / len(EYE_IMAGE_LEFT)
    rx = sum(landmarks[i][0] for i in EYE_IMAGE_RIGHT) / len(EYE_IMAGE_RIGHT)
    span = abs(rx - lx)
    if span < 1e-6:
        return 0.0, 0.0

    mid = (lx + rx) / 2.0
    ratio = (landmarks[NOSE_TIP][0] - mid) / span
    ratio = max(-1.0, min(1.0, ratio))
    # rough mapping, only used for the state heuristic and for display
    deg = 90.0 * max(-1.0, min(1.0, ratio * 2.0))
    return ratio, deg


def bbox(landmarks: Sequence[Point]) -> Tuple[float, float, float, float]:
    xs = [landmarks[i][0] for i in FACE_CONTOUR]
    ys = [landmarks[i][1] for i in FACE_CONTOUR]
    return (min(xs), min(ys), max(xs), max(ys))


def to_groups(landmarks: Sequence[Point]) -> Dict[str, List[Point]]:
    """106 points (pixels) -> the 7 guideline skeletons."""
    if len(landmarks) < ID_COUNT:
        raise ValueError(f"expected 106 landmarks, got {len(landmarks)}")

    return {
        "longmaytrai": brow5(_pick(landmarks, BROW_IMAGE_LEFT)),
        "longmayphai": brow5(_pick(landmarks, BROW_IMAGE_RIGHT)),
        "songmui": nose4(_pick(landmarks, NOSE_BRIDGE)),
        "mattrai": eye8(_pick(landmarks, EYE_IMAGE_LEFT)),
        "matphai": eye8(_pick(landmarks, EYE_IMAGE_RIGHT)),
        "moingoai": lips_outer12(_pick(landmarks, LIPS_OUTER)),
        "moitrong": lips_inner8(_pick(landmarks, LIPS_INNER)),
    }
