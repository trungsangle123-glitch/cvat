# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import base64
import hashlib
import io
import json
import os

import numpy as np
from PIL import Image
from sam3.model_builder import build_sam3_image_model

CHECKPOINT_PATH = os.environ.get("CHECKPOINT_PATH", "/opt/nuclio/sam3/sam3.pt")
DEVICE = os.environ.get("DEVICE", "cpu")


def mask_to_rle(mask):
    """Convert a binary mask to CVAT's compressed RLE with the bbox suffix."""
    height, width = mask.shape
    pixels = (np.asarray(mask).reshape(-1) != 0).astype(np.uint8)
    if pixels.size == 0:
        return []

    changes = np.flatnonzero(pixels[1:] != pixels[:-1]) + 1
    rle = np.diff(np.concatenate(([0], changes, [pixels.size]))).tolist()
    if pixels[0] == 1:
        rle.insert(0, 0)

    rle.extend([0, 0, width - 1, height - 1])
    return rle


class ModelHandler:
    def __init__(self):
        self.model = build_sam3_image_model(
            device=DEVICE,
            checkpoint_path=CHECKPOINT_PATH,
            load_from_HF=False,
            enable_inst_interactivity=True,
        )
        self.predictor = self.model.inst_interactive_predictor
        self.latest_image_hash = None

    def set_image(self, image):
        image_hash = hashlib.sha1(image.tobytes()).digest()
        if image_hash != self.latest_image_hash:
            self.predictor.set_image(np.array(image))
            self.latest_image_hash = image_hash

    @staticmethod
    def _parse_box(obj_bbox):
        if not obj_bbox:
            return None
        if len(obj_bbox) == 2 and isinstance(obj_bbox[0], (list, tuple)):
            (x1, y1), (x2, y2) = obj_bbox
        else:
            x1, y1, x2, y2 = obj_bbox
        return [float(x1), float(y1), float(x2), float(y2)]

    def handle(self, image, pos_points, neg_points, obj_bbox):
        self.set_image(image)

        point_coords = [[float(x), float(y)] for x, y in [*pos_points, *neg_points]]
        point_labels = [1] * len(pos_points) + [0] * len(neg_points)
        box = self._parse_box(obj_bbox)

        if not point_coords and box is None:
            return None

        masks, ious, _ = self.predictor.predict(
            point_coords=np.asarray(point_coords, dtype=np.float32) if point_coords else None,
            point_labels=np.asarray(point_labels, dtype=np.int32) if point_labels else None,
            box=np.asarray(box, dtype=np.float32) if box is not None else None,
            multimask_output=len(point_coords) <= 1 and box is None,
        )

        best_mask = masks[int(np.argmax(ious))]
        return mask_to_rle(best_mask.astype(np.uint8))


def init_context(context):
    context.logger.info(f"Loading SAM 3 from {CHECKPOINT_PATH} (device={DEVICE})")
    context.user_data.model = ModelHandler()
    context.logger.info("SAM 3 model loaded")


def handler(context, event):
    data = event.body
    image = Image.open(io.BytesIO(base64.b64decode(data["image"]))).convert("RGB")

    points = context.user_data.model.handle(
        image,
        data.get("pos_points") or [],
        data.get("neg_points") or [],
        data.get("obj_bbox"),
    )

    shapes = []
    if points:
        shapes.append(
            {
                "points": points,
                "group": 0,
                "source": "semi-auto",
                "attributes": [],
                "occluded": False,
                "rotation": 0,
                "type": "mask",
            }
        )

    return context.Response(
        body=json.dumps({"shapes": shapes}),
        headers={},
        content_type="application/json",
        status_code=200,
    )
