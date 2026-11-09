# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import base64
import io
import json
import os

from PIL import Image
from ultralytics import YOLO


MODEL_PATH = os.environ.get("MODEL_PATH", "/opt/nuclio/yolo26n-objv1-150.pt")
DEVICE = os.environ.get("DEVICE", "cpu")
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
    "pickup truck": "truck",
    "fire truck": "truck",
}


def _to_target_label(name):
    label = name.strip().lower()
    label = LABEL_ALIASES.get(label, label)
    return label if label in TARGET_LABELS else None


def init_context(context):
    context.logger.info(f"Loading YOLO26 model from {MODEL_PATH} (device={DEVICE})")
    context.user_data.model = YOLO(MODEL_PATH)
    context.logger.info(f"YOLO26 model loaded, labels: {sorted(TARGET_LABELS)}")


def handler(context, event):
    data = event.body
    image = Image.open(io.BytesIO(base64.b64decode(data["image"]))).convert("RGB")
    threshold = float(data.get("threshold", 0.25))

    prediction = context.user_data.model.predict(
        image,
        conf=threshold,
        device=DEVICE,
        verbose=False,
    )[0]

    shapes = []
    boxes = prediction.boxes
    if boxes is not None:
        for xyxy, confidence, class_id in zip(
            boxes.xyxy.tolist(),
            boxes.conf.tolist(),
            boxes.cls.tolist(),
        ):
            label = _to_target_label(prediction.names[int(class_id)])
            if label is None:
                continue
            shapes.append(
                {
                    "confidence": str(confidence),
                    "label": label,
                    "points": [float(value) for value in xyxy],
                    "type": "rectangle",
                }
            )

    return context.Response(
        body=json.dumps(shapes),
        headers={},
        content_type="application/json",
        status_code=200,
    )
