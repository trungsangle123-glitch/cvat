"""Image -> 50 landmark response used by the browser extension."""

from __future__ import annotations

import base64
import io
import time
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

from .geometry import derive_50
from .model import build_backend, pick_face
from .states import StateConfig, assign_states, summarize
from .topology import GROUPS, MESH


class Pipeline:
    def __init__(self) -> None:
        self.backend = build_backend()

    @property
    def name(self) -> str:
        return self.backend.name

    def analyze(
        self,
        image: Image.Image,
        face_mode: str = "largest",
        strict: Optional[bool] = None,
        state_cfg: Optional[StateConfig] = None,
    ) -> Dict:
        started = time.perf_counter()
        rgb = np.asarray(image.convert("RGB"))
        height, width = rgb.shape[:2]

        faces = self.backend.detect(rgb)
        face = pick_face(faces, width, height, face_mode)

        base = {
            "width": width,
            "height": height,
            "model": self.name,
            "faces_found": len(faces),
            "detected": face is not None,
        }

        if face is None:
            base.update({
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "face": None,
                "skeletons": [],
                "summary": {"visible": 0, "occluded": 0, "outside": 0},
                "warnings": ["khong tim thay khuon mat nao trong frame"],
            })
            return base

        cfg = state_cfg or StateConfig()
        if strict is not None:
            cfg = StateConfig(
                strict=strict,
                far_side_start=cfg.far_side_start,
                far_side_full=cfg.far_side_full,
                border_px=cfg.border_px,
            )

        groups = face.groups or derive_50(face.points, MESH)
        states, warnings = assign_states(
            groups, width, height, face.yaw_ratio, cfg,
        )
        by_id = {s.id: s for s in states}

        skeletons: List[Dict] = []
        for group in GROUPS:
            points = [
                {"id": i, "x": by_id[i].x, "y": by_id[i].y, "state": by_id[i].state}
                for i in range(group.first, group.first + group.count)
            ]
            skeletons.append({
                "name": group.name,
                "first_id": group.first,
                "closed": group.closed,
                "points": points,
            })

        summary = summarize(states)
        if summary["visible"] == 0:
            warnings.append("tat ca 50 diem deu khong nhin thay - can review thu cong")

        base.update({
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "face": {
                "bbox": [round(v, 1) for v in face.bbox],
                "score": round(face.score, 3),
                "yaw_ratio": round(face.yaw_ratio, 3),
                "yaw_deg": round(face.yaw_deg, 1),
            },
            "skeletons": skeletons,
            "summary": summary,
            "warnings": warnings,
        })
        return base


def decode_image(payload: str) -> Image.Image:
    data = payload.strip()
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    raw = base64.b64decode(data)
    image = Image.open(io.BytesIO(raw))
    image.load()
    return image.convert("RGB")
