from __future__ import annotations

import hashlib
import io
import os
from collections import Counter, defaultdict
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, Field

try:
    import imagehash
except ImportError:
    imagehash = None


class RunRequest(BaseModel):
    cvat_host: str = Field(..., description="CVAT origin, for example http://localhost:8080")
    token: str = Field(..., description="CVAT Personal Access Token")
    job_id: int = Field(..., ge=1)
    min_box_side_px: float = Field(
        float(os.getenv("AUTOQC_MIN_BOX_SIDE_PX", "12")),
        ge=0,
    )
    dup_box_iou: float = Field(
        float(os.getenv("AUTOQC_DUP_BOX_IOU", "0.90")),
        ge=0,
        le=1,
    )
    phash_dist: int = Field(
        int(os.getenv("AUTOQC_PHASH_DIST", "16")),
        ge=0,
    )
    warn_ratio_hold: float = Field(
        float(os.getenv("AUTOQC_WARN_RATIO_HOLD", "0.10")),
        ge=0,
        le=1,
    )


app = FastAPI(title="CVAT AutoQC", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def normalize_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host:
        raise HTTPException(status_code=400, detail="CVAT host is required")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host


def auth_headers(token: str) -> dict[str, str]:
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="CVAT token is required")
    return {"Authorization": f"Token {token}", "Accept": "application/json"}


def frame_included_shape(shape: dict[str, Any]) -> bool:
    return not bool(shape.get("outside"))


def rect_area(shape: dict[str, Any]) -> float:
    points = shape.get("points") or []
    if len(points) < 4:
        return 0.0
    x1, y1, x2, y2 = map(float, points[:4])
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def rect_iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    pa, pb = a.get("points") or [], b.get("points") or []
    if len(pa) < 4 or len(pb) < 4:
        return 0.0
    ax1, ay1, ax2, ay2 = map(float, pa[:4])
    bx1, by1, bx2, by2 = map(float, pb[:4])
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = rect_area(a) + rect_area(b) - inter
    return inter / union if union > 0 else 0.0


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "CVAT AutoQC", "version": "1.0.0"}


@app.post("/run")
async def run(req: RunRequest) -> dict[str, Any]:
    host = normalize_host(req.cvat_host)
    headers = auth_headers(req.token)
    issues: list[dict[str, Any]] = []
    frame_stats: Counter[int] = Counter()

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        job_res = await client.get(f"{host}/api/jobs/{req.job_id}", headers=headers)
        if job_res.status_code >= 400:
            raise HTTPException(job_res.status_code, f"Cannot read CVAT job: {job_res.text[:300]}")
        job = job_res.json()

        labels_res = await client.get(
            f"{host}/api/labels",
            params={"job_id": req.job_id, "page_size": 1000},
            headers=headers,
        )
        if labels_res.status_code >= 400:
            raise HTTPException(labels_res.status_code, f"Cannot read CVAT labels: {labels_res.text[:300]}")
        labels_payload = labels_res.json()
        labels = labels_payload if isinstance(labels_payload, list) else labels_payload.get("results", [])
        label_names = {int(label["id"]): str(label["name"]) for label in labels}

        ann_res = await client.get(f"{host}/api/jobs/{req.job_id}/annotations", headers=headers)
        if ann_res.status_code >= 400:
            raise HTTPException(ann_res.status_code, f"Cannot read CVAT annotations: {ann_res.text[:300]}")
        annotations = ann_res.json()

        shapes = [
            shape
            for shape in annotations.get("shapes", [])
            if shape.get("type") == "rectangle" and frame_included_shape(shape)
        ]
        shapes_by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for shape in shapes:
            shapes_by_frame[int(shape["frame"])].append(shape)

        frame_count = int(job.get("size") or job.get("stop", 0) - job.get("start", 0) + 1)
        frame_start = int(job.get("start") or 0)
        frame_stop = int(job.get("stop") if job.get("stop") is not None else frame_start + frame_count - 1)
        frame_numbers = list(range(frame_start, frame_stop + 1))

        for frame in frame_numbers:
            frame_shapes = shapes_by_frame.get(frame, [])
            frame_stats[frame] = len(frame_shapes)
            if not frame_shapes:
                issues.append({
                    "severity": "warn",
                    "code": "EMPTY_FRAME",
                    "frame": frame,
                    "shape_id": None,
                    "message": "Frame không có rectangle annotation.",
                })

            previous: list[dict[str, Any]] = []
            for shape in frame_shapes:
                shape_id = int(shape.get("id") or 0)
                points = shape.get("points") or []
                if len(points) < 4:
                    issues.append({
                        "severity": "error",
                        "code": "BAD_FORMAT",
                        "frame": frame,
                        "shape_id": shape_id,
                        "message": "Rectangle không đủ 4 toạ độ.",
                    })
                    continue

                x1, y1, x2, y2 = map(float, points[:4])
                width = max(0.0, x2 - x1)
                height = max(0.0, y2 - y1)
                if width <= 0 or height <= 0:
                    issues.append({
                        "severity": "error",
                        "code": "BOX_ZERO",
                        "frame": frame,
                        "shape_id": shape_id,
                        "message": "Box có chiều rộng hoặc chiều cao bằng 0.",
                    })
                    continue

                data_res = await client.get(
                    f"{host}/api/jobs/{req.job_id}/data",
                    params={"type": "frame", "number": frame, "quality": "original"},
                    headers=headers,
                )
                if data_res.status_code < 400:
                    try:
                        image = Image.open(io.BytesIO(data_res.content))
                        image_width, image_height = image.size
                        if x1 < 0 or y1 < 0 or x2 > image_width or y2 > image_height:
                            issues.append({
                                "severity": "error",
                                "code": "BOX_OUT_OF_IMAGE",
                                "frame": frame,
                                "shape_id": shape_id,
                                "message": f"Box vượt ra ngoài ảnh {image_width}x{image_height}.",
                            })
                        if min(width, height) < req.min_box_side_px:
                            issues.append({
                                "severity": "warn",
                                "code": "BOX_TINY",
                                "frame": frame,
                                "shape_id": shape_id,
                                "message": f"Cạnh ngắn của box là {min(width, height):.1f}px.",
                            })
                    except Exception:
                        pass

                for previous_shape in previous:
                    if previous_shape.get("label_id") != shape.get("label_id"):
                        continue
                    if rect_iou(previous_shape, shape) > req.dup_box_iou:
                        issues.append({
                            "severity": "error",
                            "code": "DUP_BOX",
                            "frame": frame,
                            "shape_id": shape_id,
                            "message": "Box trùng box trước đó cùng lớp.",
                        })
                        break
                previous.append(shape)

        if imagehash is not None:
            hashes: dict[int, Any] = {}
            for frame in frame_numbers:
                res = await client.get(
                    f"{host}/api/jobs/{req.job_id}/data",
                    params={"type": "frame", "number": frame, "quality": "original"},
                    headers=headers,
                )
                if res.status_code >= 400:
                    continue
                try:
                    image = Image.open(io.BytesIO(res.content)).convert("RGB")
                    digest = hashlib.md5(res.content).hexdigest()
                    phash = imagehash.phash(image)
                    duplicate_of = None
                    for other_frame, other in hashes.items():
                        if digest == other["md5"]:
                            duplicate_of = other_frame
                            break
                        if phash - other["phash"] <= req.phash_dist:
                            duplicate_of = other_frame
                            break
                    if duplicate_of is not None:
                        issues.append({
                            "severity": "error",
                            "code": "DUP_IMAGE_NEAR",
                            "frame": frame,
                            "shape_id": None,
                            "message": f"Ảnh trùng hoặc gần trùng frame {duplicate_of}.",
                        })
                    else:
                        hashes[frame] = {"md5": digest, "phash": phash}
                except Exception:
                    issues.append({
                        "severity": "error",
                        "code": "CORRUPT_IMAGE",
                        "frame": frame,
                        "shape_id": None,
                        "message": "Không đọc được frame ảnh.",
                    })

    n_errors = sum(issue["severity"] == "error" for issue in issues)
    warning_frames = {
        issue["frame"]
        for issue in issues
        if issue["severity"] == "warn" and issue["frame"] is not None
    }
    n_images = len(frame_numbers)
    warn_ratio = round(len(warning_frames) / n_images, 4) if n_images else 0.0

    if n_errors:
        decision = "Rework"
        reasons = [f"Còn {n_errors} lỗi bắt buộc."]
    elif warn_ratio >= req.warn_ratio_hold:
        decision = "Hold"
        reasons = [f"{len(warning_frames)}/{n_images} frame có cảnh báo ({warn_ratio:.2%})."]
    else:
        decision = "Release"
        reasons = [f"{len(warning_frames)}/{n_images} frame có cảnh báo ({warn_ratio:.2%})."]

    return {
        "decision": decision,
        "reasons": reasons,
        "n_errors": n_errors,
        "n_warn_frames": len(warning_frames),
        "n_frames": n_images,
        "warn_ratio": warn_ratio,
        "issues": issues,
        "labels": label_names,
        "job": {
            "id": req.job_id,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
            "stage": job.get("stage"),
            "state": job.get("state"),
        },
    }
