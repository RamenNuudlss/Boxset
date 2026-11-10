"""Subtitles for the disc.

A Blu-ray's subtitles are pictures (PGS). Two kinds of source become them:

* Picture subtitles already made for a 1080p Blu-ray (PGS in an MKV) are copied
  as they are.
* Text subtitles (SRT, ASS, WebVTT, MP4 text; inside the film's file or in a file
  beside it) are drawn here, white with a black outline, and written as PGS.

Text in scripts that need shaping or right-to-left layout (Arabic, Hebrew, Thai,
Indic scripts) is left out rather than drawn wrongly, as are DVD-style picture
subtitles, which FFmpeg can't turn into PGS.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass

from . import probe

MAX_TRACKS = 8
W, H = 1920, 1080
FONT_SIZE = 54
OUTLINE = 3
MARGIN = 64                 # from the bottom (or top) of the frame to the text
LINE_GAP = 8
MAX_WIDTH = W - 2 * 160     # lines wider than this are wrapped


@dataclass
class Cue:
    start: float
    end: float
    text: str
    top: bool = False       # shown at the top of the picture ({\an8} and friends)


# ------------------------------------------------------------------ choosing
def usable(media) -> list:
    """The subtitle streams of a film that can go on the disc, in file order,
    files beside the film last."""
    return [s for s in media.subs if s.kind][:MAX_TRACKS]


def skipped(media) -> list[str]:
    """Why any subtitle stream was left out, in words."""
    notes = []
    for s in media.subs:
        if s.kind:
            continue
        if s.codec in probe.PGS_SUBS:
            notes.append(f"{s.language} picture subtitles made for {s.width}x{s.height}, not 1080p")
        elif s.codec in ("dvd_subtitle", "dvdsub", "dvb_subtitle"):
            notes.append(f"{s.language} DVD-style picture subtitles")
        else:
            notes.append(f"{s.language} subtitles in a format Boxset doesn't read ({s.codec})")
    extra = len([s for s in media.subs if s.kind]) - MAX_TRACKS
    if extra > 0:
        notes.append(f"{extra} more subtitle track{'s' if extra > 1 else ''} than the {MAX_TRACKS} a disc gets")
    return notes


# ------------------------------------------------------------------ reading text
_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
_TAGS = re.compile(r"<[^>]{0,40}>|\{\\[^}]*\}")
_TOP = re.compile(r"\{\\an?[789]\}|\{\\a(5|6|7)\}")


def parse_srt(text: str) -> list[Cue]:
    cues, lines, span = [], [], None

    def flush():
        if span and lines:
            raw = "\n".join(lines)
            body = "\n".join(ln.strip() for ln in _TAGS.sub("", raw).splitlines() if ln.strip())
            if body and span[1] > span[0]:
                cues.append(Cue(span[0], span[1], body, bool(_TOP.search(raw))))

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _TIME.search(line)
        if not m:
            lines.append(line)
            continue
        if lines and lines[-1].strip().isdigit():
            lines.pop()                     # the number of the cue these times start
        flush()
        g = m.groups()
        a = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3].ljust(3, "0")) / 1000
        b = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7].ljust(3, "0")) / 1000
        span, lines = (a, b), []
    flush()
    cues.sort(key=lambda c: c.start)
    return cues


def read_cues(media_path: str, sub) -> list[Cue]:
    """A text subtitle stream (or file) as cues, by way of FFmpeg's SRT output."""
    cmd = [probe.need("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error"]
    if sub.file:
        cmd += ["-i", sub.file, "-map", "0:s:0"]
    else:
        cmd += ["-i", media_path, "-map", f"0:s:{sub.index}"]
    cmd += ["-f", "srt", "pipe:1"]
    out = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace").strip()[-300:] or "FFmpeg couldn't read it")
    return parse_srt(out.stdout.decode("utf-8", "replace"))


# ------------------------------------------------------------------ fonts
def _is_cjk(ch: str) -> bool:
    c = ord(ch)
    return (0x2E80 <= c <= 0x9FFF or 0xAC00 <= c <= 0xD7AF or 0xF900 <= c <= 0xFAFF
            or 0xFF00 <= c <= 0xFFEF or 0x20000 <= c <= 0x2FA1F)


def _needs_shaping(ch: str) -> bool:
    c = ord(ch)
    return (0x0590 <= c <= 0x08FF          # Hebrew, Arabic, Syriac, Thaana
            or 0x0900 <= c <= 0x0DFF       # Indic scripts
            or 0x0E00 <= c <= 0x0EFF       # Thai, Lao
            or 0x1000 <= c <= 0x109F       # Myanmar
            or 0x1780 <= c <= 0x17FF       # Khmer
            or 0xFB1D <= c <= 0xFDFF or 0xFE70 <= c <= 0xFEFF)


def drawable(cues: list[Cue]) -> bool:
    """False when the text is in a script this simple drawing would get wrong."""
    odd = sum(1 for c in cues for ch in c.text if _needs_shaping(ch))
    return odd == 0


def _font_dirs() -> list[str]:
    dirs = []
    if sys.platform == "win32":
        dirs.append(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    elif sys.platform == "darwin":
        dirs += ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts"]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
    return dirs


_LATIN_FONTS = ("segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
                "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf")
_CJK_FONTS = ("msyhbd.ttc", "msyh.ttc", "YuGothB.ttc", "meiryob.ttc", "malgunbd.ttf", "malgun.ttf",
              "PingFang.ttc", "NotoSansCJK-Bold.ttc", "NotoSansCJK-Regular.ttc", "simhei.ttf")
_font_cache: dict = {}


def _find(names) -> str | None:
    wanted = {n.lower(): i for i, n in enumerate(names)}
    best = None
    for d in _font_dirs():
        for root, _, files in os.walk(d):
            for f in files:
                rank = wanted.get(f.lower())
                if rank is not None and (best is None or rank < best[0]):
                    best = (rank, os.path.join(root, f))
    return best[1] if best else None


def font_for(cjk: bool):
    """The font for subtitles: a system font that covers Latin, Greek and Cyrillic
    (or Chinese, Japanese and Korean), else the Latin font bundled with Boxset."""
    from PIL import ImageFont
    if cjk not in _font_cache:
        path = _find(_CJK_FONTS if cjk else _LATIN_FONTS)
        if not path and cjk:
            _font_cache[cjk] = None
        else:
            path = path or os.path.join(os.path.dirname(__file__), "fonts", "Barlow-SemiBold.ttf")
            _font_cache[cjk] = ImageFont.truetype(path, FONT_SIZE)
    return _font_cache[cjk]


# ------------------------------------------------------------------ drawing
def _wrap(draw, text: str, font) -> list[str]:
    out = []
    for line in text.split("\n"):
        if draw.textlength(line, font=font) <= MAX_WIDTH:
            out.append(line)
            continue
        words, cur = (line.split(" ") if " " in line else list(line)), ""
        joiner = " " if " " in line else ""
        for w in words:
            trial = (cur + joiner + w) if cur else w
            if cur and draw.textlength(trial, font=font) > MAX_WIDTH:
                out.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            out.append(cur)
    return out[:4]              # more than four lines would cover the picture


def draw_cue(cue: Cue, font):
    """One cue as (index bytes, w, h, x, y) for bdmvkit's PGS writer, or None if
    nothing visible came out."""
    from PIL import Image, ImageDraw
    from bdmvkit import pgs
    probe_img = Image.new("RGBA", (8, 8))
    d0 = ImageDraw.Draw(probe_img)
    lines = _wrap(d0, cue.text, font)
    asc, desc = font.getmetrics()
    line_h = asc + desc + LINE_GAP
    height = line_h * len(lines) + 2 * OUTLINE + 4
    img = Image.new("RGBA", (W, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        width = d.textlength(line, font=font)
        d.text(((W - width) / 2, OUTLINE + 2 + i * line_h), line, font=font, fill=(255, 255, 255, 255),
               stroke_width=OUTLINE, stroke_fill=(0, 0, 0, 255))
    pic = pgs.indexed(img.tobytes(), W, height)
    if pic is None:
        return None
    idx, w, h, x, y = pic
    top = MARGIN if cue.top else H - MARGIN - height
    return idx, w, h, x, y + max(0, top)


def write_sup(cues: list[Cue], out: str, tempo: float = 1.0, check=None) -> int:
    """Draw `cues` into the PGS file `out`; returns how many made it. `tempo`
    stretches their times to match a film that plays slower on the disc."""
    from bdmvkit import pgs
    cjk = any(_is_cjk(ch) for c in cues for ch in c.text)
    font = font_for(cjk)
    if font is None:
        raise RuntimeError("no font on this PC covers Chinese, Japanese or Korean text")
    timed = [Cue(c.start * tempo, c.end * tempo, c.text, c.top) for c in cues]
    entries = pgs.palette("#FFFFFF", "#000000")
    pictures = []
    for cue, span in zip(timed, pgs.timeline(timed)):
        if check:
            check()
        if span is None:
            continue
        pic = draw_cue(cue, font)
        if pic is not None:
            pictures.append((span[0], span[1], pic, entries))
    pgs.write_sup(out, pictures, (W, H))
    return len(pictures)
