# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import base64
import io
import json
import os

import torch
from PIL import Image
from torchvision.ops import batched_nms
from ultralytics import YOLO


MODEL_PATH = os.environ.get("MODEL_PATH", "/opt/nuclio/yolo26n-objv1-150.pt")
DEVICE = os.environ.get("DEVICE", "cpu")
IMGSZ = int(os.environ.get("IMGSZ", "960"))              # tăng nếu xe nhỏ/xa
PRED_IOU = float(os.environ.get("PRED_IOU", "0.6"))      # NMS bên trong YOLO
MERGE_IOU = float(os.environ.get("MERGE_IOU", "0.5"))    # NMS sau khi gộp lớp
CROSS_CLASS_IOU = float(os.environ.get("CROSS_CLASS_IOU", "0.8"))  # car vs van trên cùng 1 xe
TARGET_LABELS = {
    label.strip().lower()
    for label in os.environ.get("TARGET_LABELS", "car,truck,bus,van").split(",")
    if label.strip()
}

# Objects365 has several vehicle subclasses. Map them into the four labels
# exposed by this CVAT function so they are not silently dropped.
LABEL_ALIASES = {
    "suv": "car",
    "sports car": "car",
    "race car": "car",
    "taxi": "car",
    "pickup truck": "car",
    "minivan": "van",
    "minibus": "bus",
    "tractor": "truck",
    "tractor trailer": "truck",
    "fire truck": "truck",
    "heavy truck": "truck",
}


def _to_target_label(name):
    label = name.strip().lower()
    label = LABEL_ALIASES.get(label, label)
    return label if label in TARGET_LABELS else None


def _dedupe(boxes, scores, labels):
    """NMS after alias mapping: first per merged label, then across labels."""
    if not boxes:
        return []

    label_names = sorted(TARGET_LABELS)
    b = torch.tensor(boxes, dtype=torch.float32)
    s = torch.tensor(scores, dtype=torch.float32)
    ids = torch.tensor([label_names.index(l) for l in labels])

    # 1) trùng trong cùng nhãn đã gộp (car/suv/sports car -> car)
    keep = batched_nms(b, s, ids, MERGE_IOU)
    b, s, ids = b[keep], s[keep], ids[keep]

    # 2) cùng một xe nhưng bị đoán 2 nhãn khác nhau (car vs van):
    #    chỉ giữ nhãn có confidence cao hơn, ngưỡng cao để không xoá xe đỗ sát nhau
    keep = batched_nms(b, s, torch.zeros_like(ids), CROSS_CLASS_IOU)
    b, s, ids = b[keep], s[keep], ids[keep]

    return [
        (box.tolist(), float(score), label_names[int(i)])
        for box, score, i in zip(b, s, ids)
    ]


def init_context(context):
    context.logger.info(f"Loading YOLO26 model from {MODEL_PATH} (device={DEVICE})")
    context.user_data.model = YOLO(MODEL_PATH)
    context.logger.info(
        f"YOLO26 model loaded, labels: {sorted(TARGET_LABELS)}, imgsz={IMGSZ}"
    )


def handler(context, event):
    data = event.body
    image = Image.open(io.BytesIO(base64.b64decode(data["image"]))).convert("RGB")
    threshold = float(data.get("threshold", 0.25))

    prediction = context.user_data.model.predict(
        image,
        conf=threshold,
        iou=PRED_IOU,
        imgsz=IMGSZ,
        device=DEVICE,
        verbose=False,
    )[0]

    boxes, scores, labels = [], [], []
    pboxes = prediction.boxes
    if pboxes is not None:
        for xyxy, confidence, class_id in zip(
            pboxes.xyxy.tolist(),
            pboxes.conf.tolist(),
            pboxes.cls.tolist(),
        ):
            label = _to_target_label(prediction.names[int(class_id)])
            if label is None:
                continue
            boxes.append([float(v) for v in xyxy])
            scores.append(float(confidence))
            labels.append(label)

    shapes = [
        {
            "confidence": str(score),
            "label": label,
            "points": box,
            "type": "rectangle",
        }
        for box, score, label in _dedupe(boxes, scores, labels)
    ]

    return context.Response(
        body=json.dumps(shapes),
        headers={},
        content_type="application/json",
        status_code=200,
    )