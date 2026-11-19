from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SERVER_DIR / "tools"
EXTENSION_DIR = SERVER_DIR.parent / "face50-extension"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from labels_spec import build_labels  # noqa: E402
from setup_task import build_plan  # noqa: E402

from app.face50.topology import GROUPS  # noqa: E402


def test_seven_skeletons_with_fifty_points():
    labels = build_labels()
    assert [label["name"] for label in labels] == [group.name for group in GROUPS]
    assert sum(len(label["sublabels"]) for label in labels) == 50

    seen = []
    for label, group in zip(labels, GROUPS):
        assert label["type"] == "skeleton"
        names = [sub["name"] for sub in label["sublabels"]]
        assert names == [f"p{group.first + i}" for i in range(group.count)]
        assert all(sub["type"] == "points" for sub in label["sublabels"])
        seen.extend(names)
    assert seen == [f"p{i}" for i in range(50)]


def test_svg_references_every_sublabel_once():
    for label in build_labels():
        for sub in label["sublabels"]:
            assert label["svg"].count(f'data-label-name="{sub["name"]}"') == 1
        assert label["svg"].count("<circle") == len(label["sublabels"])
        assert 'data-label-id' not in label["svg"]


def test_checked_in_labels_file_matches_generator():
    text = (SERVER_DIR / "labels_raw.json").read_text(encoding="utf-8")
    assert json.loads(text) == build_labels()


def test_extension_copy_matches_server_copy():
    server = json.loads((SERVER_DIR / "labels_raw.json").read_text(encoding="utf-8"))
    extension = json.loads((EXTENSION_DIR / "labels_raw.json").read_text(encoding="utf-8"))
    assert extension == server, (
        "face50-extension/labels_raw.json is stale - regenerate it with "
        "`python tools/labels_spec.py --out ../face50-extension/labels_raw.json`"
    )


def test_plan_creates_missing_labels_before_touching_existing_ones():
    desired = build_labels()
    existing = [{"id": 11, "name": "person", "type": "rectangle", "sublabels": []}]
    payload, notes, problems = build_plan(existing, desired)
    assert not problems
    assert [label["name"] for label in payload] == [group.name for group in GROUPS]
    assert all("id" not in label for label in payload)


def test_plan_only_adds_missing_sublabels():
    desired = build_labels()
    existing = [
        {
            "id": 7,
            "name": "longmaytrai",
            "type": "skeleton",
            "sublabels": [{"id": 70, "name": "p0", "type": "points"}],
        }
    ]
    payload, notes, problems = build_plan(existing, desired)
    assert not problems
    first = payload[0]
    assert first["id"] == 7
    assert [sub["name"] for sub in first["sublabels"]] == ["p1", "p2", "p3", "p4"]
    assert len(payload) == len(GROUPS)


def test_plan_refuses_to_rewrite_a_conflicting_label():
    desired = build_labels()
    existing = [{"id": 5, "name": "mattrai", "type": "polygon", "sublabels": []}]
    payload, _notes, problems = build_plan(existing, desired)
    assert problems and "mattrai" in problems[0]
    assert all(label["name"] != "mattrai" for label in payload)


def test_plan_is_idempotent():
    desired = build_labels()
    existing = [
        {
            "id": i,
            "name": label["name"],
            "type": "skeleton",
            "sublabels": [{"id": 100 + j, "name": sub["name"]} for j, sub in enumerate(label["sublabels"])],
        }
        for i, label in enumerate(desired, start=1)
    ]
    payload, notes, problems = build_plan(existing, desired)
    assert not problems
    assert payload == []
    assert len(notes) == len(GROUPS)


if __name__ == "__main__":  # tiny runner for machines without pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
