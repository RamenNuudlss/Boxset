"""Contact sheet: every rendered screen with its default button highlighted."""
from __future__ import annotations

import io
import json
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

from .draw import FONT_DIR, FONTS
from .probe import need

VIDEO_EXT = (".mp4", ".mkv", ".m2ts", ".mov", ".webm")


def background_frame(path: str, at: float = 1.0) -> Image.Image:
    if path.lower().endswith(VIDEO_EXT):
        out = subprocess.run([need("ffmpeg"), "-v", "error", "-ss", str(at), "-i", path, "-frames:v", "1",
                              "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True, check=True)
        return Image.open(io.BytesIO(out.stdout))
    return Image.open(path)


def compose(build_dir: str, menu: dict, selected: str | None = None, at: float = 1.0) -> Image.Image:
    im = background_frame(os.path.join(build_dir, menu["background"]), at).convert("RGBA")
    sel = selected or menu["default_button"]
    for b in menu["buttons"]:
        state = "selected" if b["id"] == sel else "normal"
        btn = Image.open(os.path.join(build_dir, b[state])).convert("RGBA")
        im.alpha_composite(btn, (b["x"], b["y"]))
    return im.convert("RGB")


def contact_sheet(build_dir: str, cols: int = 3, thumb_w: int = 640) -> str:
    with open(os.path.join(build_dir, "menus.json"), encoding="utf-8") as fh:
        menus = json.load(fh)["menus"]
    th = thumb_w * 9 // 16
    pad, label_h = 16, 30
    rows = (len(menus) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (thumb_w + pad) + pad, rows * (th + label_h + pad) + pad), (24, 26, 30))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype(os.path.join(FONT_DIR, FONTS["semi"]), 18)
    for i, m in enumerate(menus):
        r, c = divmod(i, cols)
        x, y = pad + c * (thumb_w + pad), pad + r * (th + label_h + pad)
        sheet.paste(compose(build_dir, m).resize((thumb_w, th), Image.LANCZOS), (x, y + label_h))
        motion = "  · motion" if m["background"].lower().endswith(VIDEO_EXT) else ""
        music = "  · music" if m.get("music") else ""
        d.text((x, y + 4), f"{m['id']}  ({len(m['buttons'])} buttons){motion}{music}", font=f, fill=(200, 204, 210))
    out = os.path.join(build_dir, "menus_preview.jpg")
    sheet.save(out, quality=88)
    return out
