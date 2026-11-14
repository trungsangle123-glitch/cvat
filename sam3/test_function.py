#!/usr/bin/env python3
"""Send a test request to a deployed SAM 3 Nuclio function.

Usage:
    python3 test_function.py <node-port> <image> [x y]
    python3 test_function.py <node-port> <image> --prompt <text>

The point prompt defaults to the center of the image.
"""

import base64
import json
import sys
import time
import urllib.request


def main():
    port = sys.argv[1]
    image_path = sys.argv[2]
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    try:
        from PIL import Image

        with Image.open(image_path) as image:
            width, height = image.size
    except ImportError:
        width = height = 512

    if len(sys.argv) >= 5 and sys.argv[3] == "--prompt":
        payload_data = {"image": image_b64, "prompt": " ".join(sys.argv[4:])}
    else:
        if len(sys.argv) >= 5:
            x, y = float(sys.argv[3]), float(sys.argv[4])
        else:
            x, y = width / 2, height / 2
        payload_data = {
            "image": image_b64,
            "pos_points": [[x, y]],
            "neg_points": [],
            "obj_bbox": None,
        }

    payload = json.dumps(payload_data).encode()

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.loads(response.read())
    elapsed = time.monotonic() - started

    shapes = result.get("shapes", [])
    print(f"elapsed_sec={elapsed:.1f} shapes={len(shapes)}")
    for i, shape in enumerate(shapes):
        points = shape["points"]
        left, top, right, bottom = points[-4:]
        print(
            f"  [{i}] type={shape['type']} runs={len(points) - 4} "
            f"bbox=({left}, {top}, {right}, {bottom})"
        )


if __name__ == "__main__":
    main()
