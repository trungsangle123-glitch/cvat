"""Facial Landmark-50 topology (see Face_Landmark50_Annotation_Guideline_V1.docx).

The guideline defines 7 CVAT skeletons covering 50 points with continuous ids:

    0-4    longmaytrai   left eyebrow  (5)    open contour
    5-9    longmayphai   right eyebrow (5)    open contour
    10-13  songmui       nose bridge   (4)    open contour
    14-21  mattrai       left eye      (8)    closed contour, starts leftmost
    22-29  matphai       right eye     (8)    closed contour, starts leftmost
    30-41  moingoai      outer lips   (12)    closed contour, starts leftmost
    42-49  moitrong      inner lips   (8)    closed contour, starts leftmost

Point ids never reset between skeletons, and every closed contour runs clockwise
starting from its leftmost point.

MESH holds MediaPipe FaceMesh (468 point) index *sets*. Only the set membership
matters for the derivation below - geometry decides ordering, so a wrong index
inside a set cannot reorder the 50 output points. Verify/adjust the sets with
`POST /render` (see README) or by editing this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Tuple


@dataclass(frozen=True)
class Group:
    name: str
    first: int
    count: int
    threshold: int  # guideline 3.1: min points that must be visible, else Outside
    kind: Literal["brow", "nose", "eye", "lips_outer", "lips_inner"]
    closed: bool


GROUPS: Tuple[Group, ...] = (
    Group("longmaytrai", 0, 5, 3, "brow", False),
    Group("longmayphai", 5, 5, 3, "brow", False),
    Group("songmui", 10, 4, 2, "nose", False),
    Group("mattrai", 14, 8, 4, "eye", True),
    Group("matphai", 22, 8, 4, "eye", True),
    Group("moingoai", 30, 12, 6, "lips_outer", True),
    Group("moitrong", 42, 8, 4, "lips_inner", True),
)

GROUP_BY_NAME: Dict[str, Group] = {g.name: g for g in GROUPS}

# Image-left groups are the subject's right side (guideline 1: left/right are
# decided on the image, mirror effects are ignored).
FAR_SIDE_GROUPS = {
    +1: ("longmaytrai", "mattrai"),  # nose shifted to image right -> far side is image left
    -1: ("longmayphai", "matphai"),
}

# MediaPipe FaceMesh index sets. Iris points (>=468) are not used.
MESH = {
    # eye contours (16 points each)
    "eye_image_left": (
        33, 246, 161, 160, 159, 158, 157, 173, 133,
        155, 154, 153, 145, 144, 163, 7,
    ),
    "eye_image_right": (
        263, 466, 388, 387, 386, 385, 384, 398, 362,
        382, 381, 380, 374, 373, 390, 249,
    ),
    # eyebrow ridges
    "brow_image_left": (46, 53, 52, 65, 55, 70, 63, 105, 66, 107),
    "brow_image_right": (276, 283, 282, 295, 285, 300, 293, 334, 296, 336),
    # nose bridge: nasion -> above the nostrils (not the tip)
    "nose_bridge": (168, 6, 197, 195, 5),
    # outer lip ring (20): 61 left corner, 291 right corner, 0 top, 17 bottom
    "lips_outer": (
        61, 185, 40, 39, 37, 0, 267, 269, 270, 409,
        291, 375, 321, 405, 314, 17, 84, 181, 91, 146,
    ),
    # inner lip ring (20): 78 left corner, 308 right corner, 13 top, 14 bottom
    "lips_inner": (
        78, 191, 80, 81, 82, 13, 312, 311, 310, 415,
        308, 324, 318, 402, 317, 14, 87, 178, 88, 95,
    ),
}

# Used for head pose / face box.
CHEEK_LEFT = 234
CHEEK_RIGHT = 454
NOSE_TIP = 1
FACE_OVAL = (
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379,
    378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127,
    162, 21, 54, 103, 67, 109,
)

# Guideline 2.1: outer lip points 31-35 sit at these width fractions of the
# upper lip (left corner -> right corner); 37-41 divide the lower lip evenly.
OUTER_LIP_TOP_FRACTIONS = (0.18, 0.36, 0.50, 0.66, 0.84)
OUTER_LIP_BOTTOM_FRACTIONS = (5 / 6, 4 / 6, 3 / 6, 2 / 6, 1 / 6)
INNER_LIP_UPPER_FRACTIONS = (0.25, 0.50, 0.75)
INNER_LIP_LOWER_FRACTIONS = (0.75, 0.50, 0.25)
EYE_UPPER_FRACTIONS = (0.25, 0.50, 0.75)
EYE_LOWER_FRACTIONS = (0.75, 0.50, 0.25)
BROW_FRACTIONS = (0.0, 0.25, 0.50, 0.75, 1.0)
NOSE_FRACTIONS = (0.0, 1 / 3, 2 / 3, 1.0)
