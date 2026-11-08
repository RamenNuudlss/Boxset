"""Drawing primitives for menu art.

Everything is drawn at SS x resolution and downscaled on save, which gives
clean anti-aliased edges on polygons (Pillow doesn't anti-alias those).
Coordinates passed in are always in final 1920x1080 space.
"""
from __future__ import annotations

import math
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

SS = 2  # supersample factor
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

FONTS = {
    "black_i": "BarlowCondensed-BlackItalic.ttf",
    "xbold_i": "BarlowCondensed-ExtraBoldItalic.ttf",
    "xbold": "BarlowCondensed-ExtraBold.ttf",
    "bold": "BarlowCondensed-Bold.ttf",
    "med": "Barlow-Medium.ttf",
    "semi": "Barlow-SemiBold.ttf",
}

SKEW = math.tan(math.radians(12))


@lru_cache(maxsize=None)
def font(name: str, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(FONT_DIR, FONTS[name]), max(1, round(size * SS)))


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t: float):
    """Blend colour a toward b by t (0..1). Returns an RGB tuple."""
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Surface:
    def __init__(self, w: int, h: int, bg=None):
        self.w, self.h = w, h
        self.img = Image.new("RGBA", (w * SS, h * SS), bg + (255,) if bg else (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    # -- geometry ---------------------------------------------------------
    @staticmethod
    def _p(pts):
        return [(x * SS, y * SS) for x, y in pts]

    def rect(self, x, y, w, h, fill=None, outline=None, width=1):
        self.d.rectangle([x * SS, y * SS, (x + w) * SS - 1, (y + h) * SS - 1],
                         fill=fill, outline=outline, width=round(width * SS) if outline else 0)

    def poly(self, pts, fill=None, outline=None, width=1):
        self.d.polygon(self._p(pts), fill=fill)
        if outline:
            self.d.line(self._p(pts + [pts[0]]), fill=outline, width=round(width * SS), joint="curve")

    def line(self, x1, y1, x2, y2, fill, width=1):
        self.d.line([(x1 * SS, y1 * SS), (x2 * SS, y2 * SS)], fill=fill, width=max(1, round(width * SS)))

    def circle(self, cx, cy, r, fill=None, outline=None, width=1):
        self.d.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS],
                       fill=fill, outline=outline, width=round(width * SS) if outline else 0)

    def arc(self, cx, cy, r, start, end, fill, width):
        rr = r + width / 2  # Pillow draws the stroke inward from the bbox edge
        self.d.arc([(cx - rr) * SS, (cy - rr) * SS, (cx + rr) * SS, (cy + rr) * SS],
                   start, end, fill=fill, width=round(width * SS))

    @staticmethod
    def skew_pts(x, y, w, h):
        """Parallelogram matching CSS skewX(-12deg) around the box centre."""
        o = h * SKEW / 2
        return [(x + o, y), (x + w + o, y), (x + w - o, y + h), (x - o, y + h)]

    def skew_box(self, x, y, w, h, fill=None, outline=None, width=2):
        pts = self.skew_pts(x, y, w, h)
        if fill:
            self.poly(pts, fill=fill)
        if outline:
            # inset the outline so its full width stays inside the shape
            i = width / 2
            self.poly(self.skew_pts(x + i, y + i, w - 2 * i, h - 2 * i), outline=outline, width=width)

    # -- text ---------------------------------------------------------------
    @staticmethod
    def text_width(s: str, f: ImageFont.FreeTypeFont, tracking: float = 0) -> float:
        if not tracking:
            return f.getlength(s) / SS
        return (sum(f.getlength(c) for c in s) + tracking * SS * (len(s) - 1)) / SS

    def text(self, x, y, s, f, fill, anchor="ls", tracking=0.0):
        """Draw text with optional letter-spacing. anchor: l/m/r + s (baseline) or m (middle)."""
        if not s:
            return
        h_anchor, v_anchor = anchor[0], anchor[1]
        w = self.text_width(s, f, tracking)
        if h_anchor == "m":
            x -= w / 2
        elif h_anchor == "r":
            x -= w
        a = "l" + v_anchor
        if not tracking:
            self.d.text((x * SS, y * SS), s, font=f, fill=fill, anchor=a)
            return
        cx = x * SS
        for c in s:
            self.d.text((cx, y * SS), c, font=f, fill=fill, anchor=a)
            cx += f.getlength(c) + tracking * SS

    def outline_text(self, x, y, s, f, stroke, width, anchor="ls"):
        """Hollow text: only the outline is drawn (composited from its own layer)."""
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((x * SS, y * SS), s, font=f, fill=(0, 0, 0, 0), anchor=anchor,
                stroke_width=round(width * SS), stroke_fill=stroke)
        self.img.alpha_composite(layer)

    def paste(self, im: Image.Image, x, y):
        im = im.convert("RGBA").resize((round(im.width * SS), round(im.height * SS)), Image.LANCZOS)
        self.img.alpha_composite(im, (round(x * SS), round(y * SS)))

    # -- output -------------------------------------------------------------
    def image(self) -> Image.Image:
        return self.img.resize((self.w, self.h), Image.LANCZOS)

    def save(self, path: str, opaque: bool = False):
        im = self.image()
        if opaque:
            im = im.convert("RGB")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        im.save(path, optimize=True)


def fit_lines(s: str, f_name: str, max_w: float, max_lines: int, sizes, tracking=0.0):
    """Pick the biggest size where `s` wraps into <= max_lines lines no wider than max_w."""
    words = s.split()
    for size in sizes:
        f = font(f_name, size)
        lines, cur = [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if Surface.text_width(trial, f, tracking) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(Surface.text_width(l, f, tracking) <= max_w for l in lines):
            return size, lines
    return sizes[-1], [s]


# -- the tachometer dial -------------------------------------------------------

def dial_angle(film_number: int, count: int) -> float:
    """Clockwise angle (deg, 0 = 3 o'clock) for a film's tick on a 270-degree dial."""
    if count <= 1:
        return 270.0
    return 135 + (film_number - 1) * (270 / (count - 1))


def draw_dial(s: Surface, x, y, size, count, accent, theme, needle=None,
              highlight=None, label_dim=None, redline_from=None):
    """Draw the film-counter dial into a size x size box at (x, y).

    needle: film number the needle points at (None = no needle)
    highlight: film number whose label is drawn in the accent colour
    """
    k = size / 1000
    cx, cy = x + size / 2, y + size / 2
    P = lambda a, r: (cx + r * k * math.cos(math.radians(a)), cy + r * k * math.sin(math.radians(a)))

    s.circle(cx, cy, 460 * k, fill=theme["panel"], outline=theme["edge"], width=2 * k)
    s.arc(cx, cy, 410 * k, 135, 45, theme["line"], 3 * k)
    rl = redline_from or max(1, count - 1)
    s.arc(cx, cy, 402 * k, dial_angle(rl, count) % 360, 45, accent, 16 * k)

    step = 270 / max(1, count - 1)
    minor = 4
    for i in range(count - 1):
        for m in range(1, minor + 1):
            a = dial_angle(i + 1, count) + m * step / (minor + 1)
            s.line(*P(a, 392), *P(a, 410), fill=theme["muted"], width=3 * k)
    lbl_font = font("xbold_i", 56 * k)
    for n in range(1, count + 1):
        a = dial_angle(n, count)
        s.line(*P(a, 366), *P(a, 410), fill=theme["text"], width=8 * k)
        if n == highlight:
            col = accent
        elif label_dim is not None:
            col = label_dim if n < rl else theme["muted"]
        else:
            col = accent if n >= rl else theme["text"]
        lx, ly = P(a, 316)
        s.text(lx, ly, str(n), lbl_font, col, anchor="mm")

    if needle is not None:
        a = math.radians(dial_angle(needle, count))
        rot = lambda px, py: (cx + (px * math.cos(a) - py * math.sin(a)) * k,
                              cy + (px * math.sin(a) + py * math.cos(a)) * k)
        s.poly([rot(-30, -6), rot(320, -2), rot(320, 2), rot(-30, 6)], fill=accent)
        s.poly([rot(-70, -8), rot(-30, -6), rot(-30, 6), rot(-70, 8)], fill=mix(theme["panel"], theme["text"], 0.5))
    s.circle(cx, cy, 42 * k, fill=theme["bg"], outline=theme["text"], width=5 * k)
    s.circle(cx, cy, 13 * k, fill=accent)
    return cx, cy, k


# -- small icons (stroke style, drawn with lines) ---------------------------

def icon_chevron(s: Surface, x, y, size, col, direction="right", width=2.5):
    h = size * 0.35
    if direction == "right":
        pts = [(x - h / 2, y - h), (x + h / 2, y), (x - h / 2, y + h)]
    elif direction == "left":
        pts = [(x + h / 2, y - h), (x - h / 2, y), (x + h / 2, y + h)]
    elif direction == "up":
        pts = [(x - h, y + h / 2), (x, y - h / 2), (x + h, y + h / 2)]
    else:
        pts = [(x - h, y - h / 2), (x, y + h / 2), (x + h, y - h / 2)]
    s.d.line(s._p(pts), fill=col, width=round(width * SS), joint="curve")


def icon_play(s: Surface, x, y, size, col):
    h = size / 2
    s.poly([(x - h * 0.6, y - h), (x + h * 0.9, y), (x - h * 0.6, y + h)], fill=col)


def icon_grid(s: Surface, x, y, size, col, width=2.2):
    q = size * 0.3
    g = size * 0.08
    for dx in (-1, 1):
        for dy in (-1, 1):
            bx = x + (g if dx > 0 else -g - q)
            by = y + (g if dy > 0 else -g - q)
            s.rect(bx, by, q, q, outline=col, width=width)


def icon_ok(s: Surface, x, y, size, col, width=2):
    s.circle(x, y, size * 0.38, outline=col, width=width)
    s.circle(x, y, size * 0.12, outline=col, width=width)


def icon_updown(s: Surface, x, y, size, col):
    icon_chevron(s, x, y - size * 0.24, size * 0.85, col, "up", 2)
    icon_chevron(s, x, y + size * 0.24, size * 0.85, col, "down", 2)
