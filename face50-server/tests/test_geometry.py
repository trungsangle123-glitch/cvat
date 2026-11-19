from __future__ import annotations

import math
import random

from app.face50.geometry import (
    brow5, derive_50, eye8, lips_inner8, lips_outer12, nose4,
    point_in_polygon, self_intersects,
)
from app.face50.states import (
    OCCLUDED, OUTSIDE, VISIBLE, StateConfig, assign_states, summarize,
)
from app.face50.topology import GROUPS, MESH


def eye_ring(rng, cx=100.0, cy=100.0, rx=30.0, ry=12.0):
    pts = []
    for i in range(16):
        a = 2 * math.pi * i / 16
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    rng.shuffle(pts)
    return pts


def lips_ring(rng, cx=100.0, cy=200.0, rx=40.0, ry=20.0):
    pts = []
    for i in range(20):
        a = 2 * math.pi * i / 20
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    rng.shuffle(pts)
    return pts


def test_eye8_clockwise_from_leftmost():
    rng = random.Random(1)
    pts = eye8(eye_ring(rng))
    assert len(pts) == 8
    xs = [p[0] for p in pts]
    assert xs[0] == min(xs)
    assert xs[4] == max(xs)
    assert xs[0] <= xs[1] <= xs[2] <= xs[3] <= xs[4]
    assert xs[4] >= xs[5] >= xs[6] >= xs[7]
    for i in range(3):
        assert pts[1 + i][1] < pts[7 - i][1]  # upper lid above lower lid


def test_eye8_closed_eye_does_not_crash():
    pts = []
    for i in range(16):
        a = 2 * math.pi * i / 16
        pts.append((100 + 30 * math.cos(a), 100 + 0.5 * math.sin(a)))
    out = eye8(pts)
    assert len(out) == 8
    assert all(math.isfinite(v) for p in out for v in p)


def test_brow5_top_edge_and_order():
    rng = random.Random(2)
    pts = [(100 + i * 5, 50 - (i * i) / 10 + rng.uniform(-1, 1)) for i in range(10)]
    pts += [(x, y + 6) for x, y in pts]  # lower edge, must be ignored
    out = brow5(pts)
    assert len(out) == 5
    assert out[0][0] < out[1][0] < out[2][0] < out[3][0] < out[4][0]
    for x, y in out:  # stays on the top curve, not on the lower edge
        expected = 50 - ((x - 100) / 5) ** 2 / 10
        assert abs(y - expected) < 2.5


def test_nose4_top_to_bottom():
    pts = [(100, 100), (101, 110), (102, 120), (103, 130), (104, 140)]
    out = nose4(pts)
    assert len(out) == 4
    assert out[0][1] == 100 and out[-1][1] == 140
    assert out[0][1] < out[1][1] < out[2][1] < out[3][1]


def test_lips12_fractions_and_corners():
    rng = random.Random(3)
    pts = lips_outer12(lips_ring(rng))
    assert len(pts) == 12
    assert pts[0][0] == min(p[0] for p in pts)
    assert pts[6][0] == max(p[0] for p in pts)
    # corners sit between the upper and lower border in a closed ellipse
    assert pts[3][1] < pts[0][1] < pts[9][1]


def test_lips8_inside_lips12():
    rng = random.Random(4)
    outer = lips_outer12(lips_ring(rng, rx=40, ry=20))
    inner = lips_inner8(lips_ring(rng, rx=30, ry=10))
    assert len(inner) == 8
    assert all(point_in_polygon(p, outer) for p in inner)


def test_derive_50_counts_and_ids():
    # 468 landmarks is overkill here: build one that satisfies the index sets
    lm = [(float(i % 50) * 10, float(i // 50) * 10) for i in range(468)]
    groups = derive_50(lm, MESH)
    assert [len(groups[g.name]) for g in GROUPS] == [g.count for g in GROUPS]
    assert sum(len(v) for v in groups.values()) == 50


def test_states_outside_off_frame():
    groups = {g.name: [(10.0 + i, 10.0) for i in range(g.count)] for g in GROUPS}
    groups["songmui"] = [(-5.0, 10.0), (5.0, 10.0), (6.0, 10.0), (7.0, 10.0)]
    states, _ = assign_states(groups, 1280, 720, 0.0, StateConfig())
    by_id = {s.id: s for s in states}
    assert by_id[10].state == OUTSIDE
    assert by_id[11].state == VISIBLE


def test_states_yaw_far_side_and_threshold():
    groups = {g.name: [(100.0 + i, 100.0) for i in range(g.count)] for g in GROUPS}
    states, warnings = assign_states(groups, 1280, 720, 0.95, StateConfig())
    by_id = {s.id: s for s in states}
    # image-left groups are far side -> below threshold -> Outside (strict)
    assert by_id[0].state == OUTSIDE
    assert by_id[14].state == OUTSIDE
    # near side stays visible
    assert by_id[5].state == VISIBLE
    assert any("outside" in w for w in warnings)


def test_states_moderate_yaw_keeps_the_far_side():
    # a ~30 degree turn must not erase the far eye/brow (regression: a frontal
    # portrait used to lose 13 points because of an over-eager yaw threshold)
    groups = {g.name: [(100.0 + i, 100.0) for i in range(g.count)] for g in GROUPS}
    states, _ = assign_states(groups, 1280, 720, 0.35, StateConfig())
    assert summarize(states) == {VISIBLE: 50, OCCLUDED: 0, OUTSIDE: 0}


def test_states_lenient_marks_occluded():
    groups = {g.name: [(100.0 + i, 100.0) for i in range(g.count)] for g in GROUPS}
    states, _ = assign_states(groups, 1280, 720, 0.95, StateConfig(strict=False))
    by_id = {s.id: s for s in states}
    assert by_id[0].state in {OUTSIDE, OCCLUDED}
    assert by_id[0].state != VISIBLE


def test_summary_counts():
    groups = {g.name: [(1.0, 1.0)] * g.count for g in GROUPS}
    states, _ = assign_states(groups, 100, 100, 0.0, StateConfig())
    assert summarize(states) == {VISIBLE: 50, OCCLUDED: 0, OUTSIDE: 0}


def test_self_intersection_helper():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert not self_intersects(square, True)
    bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]
    assert self_intersects(bowtie, True)
