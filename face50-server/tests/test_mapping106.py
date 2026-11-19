"""Unit tests for the InsightFace 106 -> 50 mapping.

Only the index tables and the pure-geometry conversion are tested here; the
model itself needs the ONNX pack and is verified by the A/B script instead.
"""

from __future__ import annotations

import math

import pytest

from app.face50.geometry import point_in_polygon, self_intersects
from app.face50.mapping106 import (
    BROW_IMAGE_LEFT,
    BROW_IMAGE_RIGHT,
    EYE_IMAGE_LEFT,
    EYE_IMAGE_RIGHT,
    ID_COUNT,
    LIPS_INNER,
    LIPS_OUTER,
    NOSE_BRIDGE,
    bbox,
    pose,
    to_groups,
)

# Published 106 -> dlib 48..67 conversion, kept literal on purpose: if the
# tables in mapping106.py drift from the reference, this test fails.
REFERENCE_OUTER = [52, 64, 63, 71, 67, 68, 61, 58, 59, 53, 56, 55]
REFERENCE_INNER = [65, 66, 62, 70, 69, 57, 60, 54]

OUTER_IDS = sorted(LIPS_OUTER)
INNER_IDS = sorted(LIPS_INNER)


def synthetic_106(cx=200.0, cy=200.0):
    """A face-shaped 106-point cloud in the documented index groups."""
    pts = [(0.0, 0.0)] * ID_COUNT

    # 0-32 jaw: ellipse from the image-left ear over the chin to the right ear
    for i in range(33):
        a = math.pi + math.pi * i / 32.0
        pts[i] = (cx + 90 * math.cos(a), cy - 100 * math.sin(a))

    def ring(center, rx, ry, ids):
        for k, idx in enumerate(ids):
            a = 2 * math.pi * k / len(ids)
            pts[idx] = (center[0] + rx * math.cos(a), center[1] + ry * math.sin(a))

    def arc(center, rx, ry, ids, start=math.pi, end=0.0):
        for k, idx in enumerate(ids):
            a = start + (end - start) * k / (len(ids) - 1)
            pts[idx] = (center[0] + rx * math.cos(a), center[1] + ry * math.sin(a))

    # 33-42 / 87-96 eyes (image left is the smaller x)
    ring((cx - 35, cy - 10), 22, 10, range(33, 43))
    ring((cx + 35, cy - 10), 22, 10, range(87, 97))
    # 43-51 / 97-105 brows, above the eyes
    arc((cx - 35, cy - 25), 30, 12, range(43, 52))
    arc((cx + 35, cy - 25), 30, 12, range(97, 106))
    # 52-71 mouth: outer ring on the outer ids, inner ring on the inner ids
    ring((cx, cy + 55), 34, 16, OUTER_IDS)
    ring((cx, cy + 55), 22, 9, INNER_IDS)
    # 72-86 nose: bridge from nasion (72) up top to the base (86)
    for k, idx in enumerate(range(72, 87)):
        t = k / 14.0
        pts[idx] = (cx, cy - 30 + 75 * t)
    return pts


def test_tables_match_published_conversion():
    assert list(LIPS_OUTER) == REFERENCE_OUTER
    assert list(LIPS_INNER) == REFERENCE_INNER


def test_index_sets_partition_the_landmark_groups():
    used = (
        set(range(33, 43)) | set(range(43, 52)) | set(range(52, 72))
        | set(range(72, 87)) | set(range(87, 97)) | set(range(97, 106))
    )
    assert used == set(range(33, 106))
    assert len(set(LIPS_OUTER)) == 12
    assert len(set(LIPS_INNER)) == 8
    assert set(LIPS_OUTER).isdisjoint(LIPS_INNER)
    assert set(LIPS_OUTER) | set(LIPS_INNER) == set(range(52, 72))
    assert EYE_IMAGE_LEFT == tuple(range(33, 43))
    assert EYE_IMAGE_RIGHT == tuple(range(87, 97))
    assert BROW_IMAGE_LEFT == tuple(range(43, 52))
    assert BROW_IMAGE_RIGHT == tuple(range(97, 106))
    assert NOSE_BRIDGE == (72, 73, 74, 86)


def test_to_groups_has_guideline_shape():
    groups = to_groups(synthetic_106())
    counts = {k: len(v) for k, v in groups.items()}
    assert counts == {
        "longmaytrai": 5,
        "longmayphai": 5,
        "songmui": 4,
        "mattrai": 8,
        "matphai": 8,
        "moingoai": 12,
        "moitrong": 8,
    }
    total = sum(counts.values())
    assert total == 50


def test_to_groups_ordering_invariants():
    groups = to_groups(synthetic_106())

    for name in ("longmaytrai", "longmayphai"):
        xs = [p[0] for p in groups[name]]
        assert xs == sorted(xs), name

    for name in ("mattrai", "matphai"):
        pts = groups[name]
        xs = [p[0] for p in pts]
        assert xs[0] == min(xs), f"{name} should start at the leftmost point"
        assert xs[4] == max(xs), f"{name} should have the rightmost point at index 4"

    outer = groups["moingoai"]
    xs = [p[0] for p in outer]
    assert xs[0] == min(xs)
    assert xs[6] == max(xs)
    assert not self_intersects(outer)

    for p in groups["moitrong"]:
        assert point_in_polygon(p, outer), "inner lip must be inside the outer lip"


def test_image_left_group_is_on_the_left():
    groups = to_groups(synthetic_106())
    left = sum(p[0] for p in groups["mattrai"]) / 8
    right = sum(p[0] for p in groups["matphai"]) / 8
    assert left < right


def test_pose_reads_head_turn():
    pts = synthetic_106()
    ratio, deg = pose(pts, 400, 400)
    assert abs(ratio) < 0.1 and abs(deg) < 10

    pts[86] = (pts[86][0] + 40, pts[86][1])
    ratio, deg = pose(pts, 400, 400)
    assert ratio > 0.2 and deg > 0


def test_bbox_follows_the_jaw():
    pts = synthetic_106()
    x1, y1, x2, y2 = bbox(pts)
    assert x1 < x2 and y1 < y2
    assert x1 <= 200.0 <= x2


def test_rejects_wrong_point_count():
    with pytest.raises(ValueError):
        to_groups(synthetic_106()[:50])
