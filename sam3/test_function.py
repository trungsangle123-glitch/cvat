#!/usr/bin/env python3
"""Send a test interactor request to a deployed SAM 3 Nuclio function.

Usage:
    python3 test_function.py <node-port> <image> [x y]

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

    if len(sys.argv) >= 5:
        x, y = float(sys.argv[3]), float(sys.argv[4])
    else:
        x, y = width / 2, height / 2

    payload = json.dumps(
        {"image": image_b64, "pos_points": [[x, y]], "neg_points": [], "obj_bbox": None}
    ).encode()

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
    if shapes:
        points = shapes[0]["points"]
        print(f"type={shapes[0]['type']} points={len(points)} bbox={points[-4:]}")


if __name__ == "__main__":
    main()
