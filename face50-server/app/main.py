"""Facial Landmark-50 annotation service.

POST /predict  {image: <base64|data-url>} -> 7 skeletons / 50 points with states
POST /render   {image: <base64|data-url>} -> annotated PNG (debug / verification)
GET  /health   -> backend + version
GET  /topology -> group layout and MediaPipe index sets
"""

from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .face50.pipeline import Pipeline, decode_image
from .face50.render import png_base64, render_overlay
from .face50.states import StateConfig
from .face50.topology import GROUPS, MESH

VERSION = "1.0.0"


class ImageRequest(BaseModel):
    image: str = Field(..., description="base64 or data: URL of a JPEG/PNG frame")
    face: Literal["largest", "center"] = "largest"
    strict: Optional[bool] = None
    show_ids: bool = True


def _state_config() -> StateConfig:
    return StateConfig(
        strict=os.getenv("FACE50_STRICT", "1") not in {"0", "false", "False"},
        far_side_start=float(os.getenv("FACE50_FAR_SIDE_START", "0.45")),
        far_side_full=float(os.getenv("FACE50_FAR_SIDE_FULL", "0.85")),
        border_px=float(os.getenv("FACE50_BORDER_PX", "0")),
    )


app = FastAPI(title="CVAT Face Landmark-50", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_pipeline: Optional[Pipeline] = None


def pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline


@app.on_event("startup")
def _warmup() -> None:
    """Fail fast if mediapipe cannot start, and remove first-call latency."""
    from PIL import Image

    pipeline().analyze(Image.new("RGB", (64, 64), (0, 0, 0)))


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "version": VERSION,
        "model": pipeline().name,
        "groups": len(GROUPS),
        "points": 50,
        "strict": _state_config().strict,
    }


@app.get("/topology")
def topology() -> dict:
    return {
        "groups": [
            {
                "name": g.name,
                "first_id": g.first,
                "count": g.count,
                "threshold": g.threshold,
                "closed": g.closed,
            }
            for g in GROUPS
        ],
        "mesh": {k: list(v) for k, v in MESH.items()},
    }


@app.post("/predict")
def predict(req: ImageRequest) -> dict:
    try:
        image = decode_image(req.image)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cannot decode image: {exc}") from exc
    try:
        return pipeline().analyze(image, req.face, req.strict, _state_config())
    except Exception as exc:  # pragma: no cover - model failures
        raise HTTPException(status_code=500, detail=f"inference failed: {exc}") from exc


@app.post("/render")
def render(req: ImageRequest) -> dict:
    try:
        image = decode_image(req.image)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cannot decode image: {exc}") from exc
    result = pipeline().analyze(image, req.face, req.strict, _state_config())
    png = render_overlay(image, result, show_ids=req.show_ids)
    return {"image": png_base64(png), "result": result}
