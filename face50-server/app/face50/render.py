"""Debug rendering: draw the derived 50 points so index sets can be verified."""

from __future__ import annotations

import base64
import io
from typing import Dict

from PIL import Image, ImageDraw, ImageFont

from .topology import GROUPS

GROUP_COLORS = {
    "longmaytrai": (0, 200, 255),
    "longmayphai": (0, 200, 255),
    "songmui": (170, 120, 255),
    "mattrai": (0, 220, 120),
    "matphai": (0, 220, 120),
    "moingoai": (255, 180, 0),
    "moitrong": (255, 80, 180),
}

STATE_COLORS = {
    "visible": (40, 230, 90),
    "occluded": (255, 160, 0),
    "outside": (255, 60, 60),
}


def render_overlay(image: Image.Image, result: Dict, show_ids: bool = True) -> Image.Image:
    img = image.convert("RGB").copy()
    # upscale small images so the points are readable
    scale = 1
    if max(img.size) < 900:
        scale = 2
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover
        font = None

    radius = max(2, round(min(img.size) / 260))
    if not result.get("detected"):
        draw.text((10, 10), "no face detected", fill=(255, 60, 60), font=font)
        return img

    for sk in result.get("skeletons", []):
        pts = [(p["x"] * scale, p["y"] * scale) for p in sk["points"]]
        if not pts:
            continue
        color = GROUP_COLORS.get(sk["name"], (255, 255, 255))
        path = pts + ([pts[0]] if sk.get("closed") else [])
        draw.line(path, fill=color, width=max(1, radius // 2))

    for sk in result.get("skeletons", []):
        for p in sk["points"]:
            x, y = p["x"] * scale, p["y"] * scale
            c = STATE_COLORS.get(p["state"], (255, 255, 255))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=c, outline=(0, 0, 0))
            if show_ids:
                draw.text((x + radius + 1, y - radius - 4), str(p["id"]), fill=(255, 255, 255), font=font)

    header = f"faces={result.get('faces_found')} yaw={result.get('face', {}).get('yaw_deg')}deg " \
             f"V/O/X={result['summary']['visible']}/{result['summary']['occluded']}/{result['summary']['outside']}"
    draw.rectangle((0, 0, min(img.width, 8 + 7 * len(header)), 14), fill=(0, 0, 0))
    draw.text((4, 1), header, fill=(255, 255, 255), font=font)
    return img


def png_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
