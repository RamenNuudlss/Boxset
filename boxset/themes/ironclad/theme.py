"""Ironclad: heavy machinery. Armour plate, blast doors, turning rings, lens
flares and sparks, in steel, electric blue and furnace orange.

Every film gets a blast door on the main menu with a frame from the film behind
it, its own page over a full-screen frame, and scene selection. While a film
plays, the remote's Pop-up Menu button brings up a progress bar in the same
style: how far in you are, every chapter as a segment you can jump to, Resume
and Menu.

Drawn with HTML (the menus) and Pillow (the pop-up). All of the artwork is made
here; the pictures are frames from your own films, and, if you add them, your
own posters and emblems: a poster per film (chosen in the settings, or a picture
beside the film with the same name, or poster.jpg in its folder) and an emblem
for each side of the title.
"""
from __future__ import annotations

import os
import random

from PIL import Image, ImageDraw, ImageFont

import boxset
from boxset.core import BaseTheme, act

LOOP = 8.0                       # seconds of animation, looping seamlessly
FONTS = os.path.join(os.path.dirname(boxset.__file__), "fonts")


def font_uri(name: str) -> str:
    import pathlib
    return pathlib.Path(os.path.join(FONTS, name)).as_uri()


# ============================================================================ CSS
CSS = """
@font-face { font-family: Heavy; src: url(F_HEAVY_I); font-style: italic; }
@font-face { font-family: Heavy; src: url(F_HEAVY); }
@font-face { font-family: Cond; src: url(F_COND); }
@font-face { font-family: Body; src: url(F_BODY); }
* { box-sizing: border-box; }
html, body { margin: 0; width: 1920px; height: 1080px; overflow: hidden; background: #05070a; }
body { font-family: Cond, sans-serif; color: #e9f3f8; position: relative; }
.abs { position: absolute; }

/* ---- the room: plate steel, a hex grid, light from the core -------------- */
.bg { position: absolute; inset: 0;
  background:
    radial-gradient(1200px 700px at 50% 44%, rgba(A_RGB, .20), transparent 70%),
    radial-gradient(900px 520px at 50% 108%, rgba(B_RGB, .22), transparent 70%),
    linear-gradient(180deg, #0a0e13 0%, #141b23 46%, #0a0d11 100%); }
.hex { position: absolute; inset: -40px; opacity: .55;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='84' height='48.5'><path d='M21 0 L63 0 L84 24.25 L63 48.5 L21 48.5 L0 24.25 Z M0 24.25 L-21 0 M84 24.25 L105 0 M0 24.25 L-21 48.5 M84 24.25 L105 48.5' fill='none' stroke='%23324150' stroke-width='1.2'/></svg>");
  -webkit-mask-image: radial-gradient(1100px 640px at 50% 46%, #000 20%, transparent 78%);
  animation: drift 8s linear infinite; }
@keyframes drift { to { transform: translate(84px, 48.5px); } }

/* ---- the machine: rings that turn behind everything ---------------------- */
.machine { position: absolute; left: 960px; top: 470px; width: 0; height: 0; }
.ring { position: absolute; border-radius: 50%; left: 50%; top: 50%; }
.r1 { width: 1500px; height: 1500px; margin: -750px;
  background: repeating-conic-gradient(from 0deg, rgba(A_RGB, .00) 0 6deg, rgba(A_RGB, .16) 6deg 7.5deg);
  -webkit-mask-image: radial-gradient(circle, transparent 690px, #000 692px, #000 742px, transparent 744px);
  animation: turn15 8s linear infinite; }
.r2 { width: 1240px; height: 1240px; margin: -620px;
  background: repeating-conic-gradient(from 0deg, rgba(190, 215, 230, .13) 0 14deg, transparent 14deg 30deg);
  -webkit-mask-image: radial-gradient(circle, transparent 560px, #000 562px, #000 612px, transparent 614px);
  animation: turn30r 8s linear infinite; }
.r3 { width: 980px; height: 980px; margin: -490px; border: 2px solid rgba(A_RGB, .30);
  box-shadow: 0 0 60px rgba(A_RGB, .22), inset 0 0 90px rgba(A_RGB, .14); }
.r4 { width: 900px; height: 900px; margin: -450px;
  background: repeating-conic-gradient(from 0deg, rgba(B_RGB, .30) 0 2deg, transparent 2deg 60deg);
  -webkit-mask-image: radial-gradient(circle, transparent 400px, #000 402px, #000 448px, transparent 450px);
  animation: turn60 8s linear infinite; }
@keyframes turn15 { to { transform: rotate(15deg); } }
@keyframes turn30r { to { transform: rotate(-30deg); } }
@keyframes turn60 { to { transform: rotate(60deg); } }
.rays { position: absolute; left: 960px; top: 470px; width: 2600px; height: 2600px; margin: -1300px; border-radius: 50%;
  background: repeating-conic-gradient(from 0deg, rgba(A_RGB, .10) 0 4deg, transparent 4deg 22deg, rgba(A_RGB, .05) 22deg 24deg, transparent 24deg 45deg);
  -webkit-mask-image: radial-gradient(circle, #000 0, rgba(0,0,0,.5) 420px, transparent 1150px);
  animation: turn45 8s linear infinite; }
@keyframes turn45 { to { transform: rotate(45deg); } }
.chev { position: absolute; height: 18px; width: 300px;
  background: repeating-linear-gradient(-55deg, B_HEX 0 12px, transparent 12px 26px); opacity: .85; }
.core { position: absolute; left: 960px; top: 470px; width: 760px; height: 760px; margin: -380px;
  border-radius: 50%; background: radial-gradient(circle, rgba(A_RGB, .34), rgba(A_RGB, .08) 45%, transparent 70%);
  animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: .55; transform: scale(1.06); } }

/* ---- light: anamorphic streaks that sweep through, sparks that rise ------- */
.flare { position: absolute; height: 6px; border-radius: 3px; filter: blur(2px); mix-blend-mode: screen;
  background: linear-gradient(90deg, transparent, rgba(A_RGB, .0) 10%, rgba(210, 245, 255, .95) 50%, rgba(A_RGB, .0) 90%, transparent); }
.flare::after { content: ""; position: absolute; left: 50%; top: 50%; width: 260px; height: 120px; margin: -60px -130px;
  background: radial-gradient(closest-side, rgba(220, 248, 255, .55), rgba(A_RGB, .20) 45%, transparent 75%); }
.fl1 { top: 236px; left: 0; width: 1500px; animation: sweep 8s linear infinite; }
.fl2 { top: 842px; left: 0; width: 900px; opacity: .7; animation: sweepr 8s linear infinite; }
.fl3 { top: 470px; left: 210px; width: 1500px; height: 3px; opacity: .55; animation: pulse 4s ease-in-out infinite; }
@keyframes sweep { from { transform: translateX(-1700px); } to { transform: translateX(2100px); } }
@keyframes sweepr { from { transform: translateX(2100px); } to { transform: translateX(-1100px); } }
.spark { position: absolute; bottom: -20px; width: 4px; height: 4px; border-radius: 50%;
  background: #ffd9a0; box-shadow: 0 0 8px 2px rgba(B_RGB, .9), 0 14px 10px -2px rgba(B_RGB, .35);
  animation: rise linear infinite; }
@keyframes rise { 0% { transform: translate(0, 0) scale(1); opacity: 0; } 8% { opacity: 1; }
  70% { opacity: .9; } 100% { transform: translate(var(--dx), -760px) scale(.3); opacity: 0; } }

/* ---- lettering -------------------------------------------------------------- */
.metal { font-family: Heavy; font-style: italic; text-transform: uppercase; line-height: .86;
  background: linear-gradient(180deg, #ffffff 0%, #dfeaf0 30%, #7f909c 52%, #e9f2f6 60%, #9aa9b3 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  filter: drop-shadow(0 3px 0 #06090c) drop-shadow(0 0 26px rgba(A_RGB, .55)); }
.kick { font-family: Cond; letter-spacing: .42em; text-transform: uppercase; color: A_HEX;
  text-shadow: 0 0 14px rgba(A_RGB, .8); }
.small { font-family: Cond; letter-spacing: .22em; text-transform: uppercase; color: #93a6b3; }
.glyphs { position: absolute; height: 22px; overflow: hidden; opacity: .75; }
.glyphs > div { height: 22px; width: 3000px; background-repeat: repeat-x; animation: tick 8s linear infinite; }
@keyframes tick { to { transform: translateX(-600px); } }

/* ---- a blast door: one film -------------------------------------------------- */
.door { position: absolute; }
.door .shell { position: absolute; inset: 0;
  clip-path: polygon(34px 0, calc(100% - 34px) 0, 100% 34px, 100% calc(100% - 34px), calc(100% - 34px) 100%, 34px 100%, 0 calc(100% - 34px), 0 34px);
  background: linear-gradient(180deg, #5d6975 0%, #2b333c 8%, #171c22 50%, #232a32 92%, #48525c 100%); }
.door .shot { position: absolute; left: 12px; right: 12px; top: 12px; background-size: cover; background-position: center;
  clip-path: polygon(26px 0, calc(100% - 26px) 0, 100% 26px, 100% 100%, 0 100%, 0 26px);
  filter: contrast(1.18) saturate(1.15) brightness(.92); }
.door .shot::before { content: ""; position: absolute; inset: 0;
  background: linear-gradient(160deg, rgba(20, 130, 170, .34), transparent 45%, rgba(255, 130, 30, .30)); mix-blend-mode: soft-light; }
.door .shot::after { content: ""; position: absolute; inset: 0;
  background: repeating-linear-gradient(180deg, rgba(0, 0, 0, .0) 0 3px, rgba(0, 0, 0, .22) 3px 4px),
              linear-gradient(180deg, rgba(5, 8, 11, .0) 55%, rgba(5, 8, 11, .92) 100%); }
.door .scan { position: absolute; left: 12px; right: 12px; top: -90px; height: 90px; mix-blend-mode: screen;
  background: linear-gradient(180deg, transparent, rgba(A_RGB, .28), transparent); animation: scan 4s linear infinite; }
@keyframes scan { from { transform: translateY(0); } to { transform: translateY(var(--travel)); } }
.door .hazard { position: absolute; left: 12px; right: 12px; height: 16px;
  background: repeating-linear-gradient(-45deg, B_HEX 0 14px, #12161b 14px 28px); opacity: .92; }
.door .no { position: absolute; left: 30px; font-family: Heavy; font-style: italic; font-size: 96px; line-height: .8;
  color: rgba(233, 243, 248, .16); -webkit-text-stroke: 2px rgba(A_RGB, .55); }
.door .plate { position: absolute; left: 30px; right: 30px; }
.door .ttl { font-family: Heavy; font-style: italic; text-transform: uppercase; line-height: .9; color: #f2f8fb;
  text-shadow: 0 2px 0 #06090c, 0 0 22px rgba(A_RGB, .45); }
.door .rivet { position: absolute; width: 9px; height: 9px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #aebac4, #3a444d 60%, #12161a); }
.door .seam { position: absolute; left: 12px; right: 12px; height: 3px; background: A_HEX;
  box-shadow: 0 0 16px 2px rgba(A_RGB, .8); animation: pulse 2s ease-in-out infinite; }

/* ---- with a poster: the door is the poster ------------------------------------- */
.door .poster { position: absolute; left: 12px; right: 12px; top: 12px; bottom: 12px; background-size: cover; background-position: top center;
  clip-path: polygon(26px 0, calc(100% - 26px) 0, 100% 26px, 100% calc(100% - 26px), calc(100% - 26px) 100%, 26px 100%, 0 calc(100% - 26px), 0 26px); }
.door .poster::after { content: ""; position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(5, 8, 11, .25) 0, transparent 12%, transparent 87%, rgba(5, 8, 11, .94) 95%),
              linear-gradient(115deg, rgba(255, 255, 255, .10) 0, transparent 28%); }
.door .strip { position: absolute; left: 30px; right: 30px; bottom: 22px; display: flex; align-items: baseline; gap: 16px;
  font-family: Cond; font-size: 22px; letter-spacing: .2em; color: #b9c8d2; text-transform: uppercase; white-space: nowrap; }
.door .strip b { font-family: Heavy; font-style: italic; font-size: 44px; letter-spacing: .02em; color: A_HEX; text-shadow: 0 0 16px rgba(A_RGB, .8); }
.emblem { position: absolute; background-size: contain; background-repeat: no-repeat; background-position: center; }
.emblem.l { filter: drop-shadow(0 0 3px rgba(255,255,255,.5)) drop-shadow(0 0 26px rgba(A_RGB, .85)) brightness(1.12); }
.emblem.r { filter: drop-shadow(0 0 3px rgba(255,255,255,.5)) drop-shadow(0 0 26px rgba(B_RGB, .85)) brightness(1.12); }
.emblem.ghost { opacity: .085; filter: grayscale(1) brightness(1.6); animation: pulse 4s ease-in-out infinite; }
.one-sheet { position: absolute; }
.one-sheet .shell { position: absolute; inset: 0; background: linear-gradient(180deg, #6a7682 0%, #2b333c 6%, #171c22 50%, #232a32 94%, #4b555f 100%);
  clip-path: polygon(30px 0, 100% 0, 100% calc(100% - 30px), calc(100% - 30px) 100%, 0 100%, 0 30px);
  }
.one-sheet .art { position: absolute; inset: 12px; background-size: cover; background-position: top center;
  clip-path: polygon(22px 0, 100% 0, 100% calc(100% - 22px), calc(100% - 22px) 100%, 0 100%, 0 22px); }
.one-sheet .art::after { content: ""; position: absolute; inset: 0; background: linear-gradient(115deg, rgba(255,255,255,.14) 0, transparent 30%); }
.one-sheet .glow { position: absolute; inset: -30px; background: radial-gradient(closest-side, rgba(A_RGB, .30), transparent 78%); }

/* ---- what the remote moves: brackets that lock onto a door ------------------- */
.lock { position: absolute; }
.lock i { position: absolute; width: 74px; height: 74px; border: 0 solid transparent; }
.lock .tl { left: 0; top: 0; border-left-width: 8px; border-top-width: 8px; }
.lock .tr { right: 0; top: 0; border-right-width: 8px; border-top-width: 8px; }
.lock .bl { left: 0; bottom: 0; border-left-width: 8px; border-bottom-width: 8px; }
.lock .br { right: 0; bottom: 0; border-right-width: 8px; border-bottom-width: 8px; }
.lock .edge { position: absolute; left: 110px; right: 110px; height: 4px; opacity: 0; }
.lock .tag { position: absolute; left: 50%; bottom: -8px; transform: translateX(-50%); padding: 7px 26px 6px;
  font-family: Heavy; font-style: italic; font-size: 30px; letter-spacing: .12em; white-space: nowrap; opacity: 0;
  clip-path: polygon(14px 0, 100% 0, calc(100% - 14px) 100%, 0 100%); }
.lock[data-state="selected"] i, .lock[data-state="activated"] i { border-color: A_HEX; }
.lock[data-state="selected"] .edge, .lock[data-state="activated"] .edge { opacity: 1; background: A_HEX; }
.lock[data-state="selected"] .tag { opacity: 1; background: A_HEX; color: #041018; }
.lock[data-state="activated"] i { border-color: B_HEX; }
.lock[data-state="activated"] .edge { background: B_HEX; }
.lock[data-state="activated"] .tag { opacity: 1; background: B_HEX; color: #140800; }

/* ---- plate buttons ------------------------------------------------------------ */
.btn { position: absolute; height: 78px; padding: 0 44px 0 34px; display: flex; align-items: center; gap: 18px;
  font-family: Heavy; font-style: italic; font-size: 44px; letter-spacing: .06em; text-transform: uppercase; white-space: nowrap;
  clip-path: polygon(22px 0, 100% 0, calc(100% - 22px) 100%, 0 100%); }
.btn .mk { width: 0; height: 0; border-left: 20px solid currentColor; border-top: 13px solid transparent; border-bottom: 13px solid transparent; }
.btn[data-state="normal"] { background: #222a32; color: #b9c8d2; box-shadow: inset 0 3px 0 #4b5661, inset 0 -3px 0 #0c1014; }
.btn[data-state="selected"] { background: A_HEX; color: #041018; box-shadow: inset 0 3px 0 #d9f7ff, inset 0 -3px 0 rgba(0,0,0,.35); }
.btn[data-state="activated"] { background: B_HEX; color: #140800; box-shadow: inset 0 3px 0 #ffe0b8, inset 0 -3px 0 rgba(0,0,0,.35); }
.btn.sm { height: 58px; font-size: 32px; padding: 0 34px 0 26px; }

/* ---- finishing: grade, vignette, letterbox ----------------------------------- */
.grade { position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(1500px 900px at 50% 46%, transparent 55%, rgba(0, 0, 0, .78) 100%),
              repeating-linear-gradient(180deg, rgba(255,255,255,.018) 0 2px, transparent 2px 4px); }
.bar { position: absolute; left: 0; right: 0; height: 54px; background: #020304; }
.bar.t { top: 0; border-bottom: 2px solid #1c242c; } .bar.b { bottom: 0; border-top: 2px solid #1c242c; }
.hint { position: absolute; bottom: 14px; font-family: Cond; font-size: 22px; letter-spacing: .28em; color: #5f7180; text-transform: uppercase; }

/* ---- a film's own page --------------------------------------------------------- */
.back { position: absolute; inset: 0; background-size: cover; background-position: center;
  filter: contrast(1.15) saturate(1.2) brightness(.82); animation: push 8s ease-in-out infinite; }
@keyframes push { 0%, 100% { transform: scale(1.03); } 50% { transform: scale(1.10) translateX(-14px); } }
.back-grade { position: absolute; inset: 0;
  background: linear-gradient(90deg, rgba(4, 7, 10, .96) 0%, rgba(4, 7, 10, .84) 30%, rgba(4, 7, 10, .25) 62%, rgba(4, 7, 10, .55) 100%),
              linear-gradient(160deg, rgba(20, 130, 170, .30), transparent 50%, rgba(255, 120, 20, .26)); }
.reticle { position: absolute; width: 520px; height: 520px; border-radius: 50%; border: 2px solid rgba(A_RGB, .5);
  box-shadow: 0 0 40px rgba(A_RGB, .25), inset 0 0 60px rgba(A_RGB, .12); }
.reticle::before { content: ""; position: absolute; inset: -34px; border-radius: 50%;
  background: repeating-conic-gradient(from 0deg, rgba(A_RGB, .85) 0 3deg, transparent 3deg 90deg);
  -webkit-mask-image: radial-gradient(circle, transparent 276px, #000 278px, #000 292px, transparent 294px);
  animation: turn90 8s linear infinite; }
.reticle::after { content: ""; position: absolute; inset: 60px; border-radius: 50%;
  background: repeating-conic-gradient(from 0deg, rgba(233, 243, 248, .5) 0 1deg, transparent 1deg 10deg);
  -webkit-mask-image: radial-gradient(circle, transparent 184px, #000 186px, #000 198px, transparent 200px);
  animation: turn30r 8s linear infinite; }
@keyframes turn90 { to { transform: rotate(90deg); } }
.readout { position: absolute; font-family: Cond; font-size: 26px; letter-spacing: .24em; color: #9fb3c0; text-transform: uppercase; }
.readout b { display: block; font-family: Heavy; font-style: italic; font-size: 54px; letter-spacing: .04em; color: #f2f8fb;
  text-shadow: 0 0 18px rgba(A_RGB, .55); }
.rule { position: absolute; height: 3px; background: linear-gradient(90deg, A_HEX, rgba(A_RGB, 0)); box-shadow: 0 0 14px rgba(A_RGB, .7); }

/* ---- scene selection ------------------------------------------------------------ */
.cell { position: absolute; background-size: cover; background-position: center;
  clip-path: polygon(18px 0, 100% 0, 100% calc(100% - 18px), calc(100% - 18px) 100%, 0 100%, 0 18px);
  filter: contrast(1.12) saturate(1.1); }
.cell-frame { position: absolute; background: linear-gradient(180deg, #56626d, #1b2128 30%, #1b2128 70%, #414b55);
  clip-path: polygon(22px 0, 100% 0, 100% calc(100% - 22px), calc(100% - 22px) 100%, 0 100%, 0 22px); }
.cap { position: absolute; font-family: Heavy; font-style: italic; font-size: 34px; color: #dce8ee; }
.cap span { font-family: Cond; font-style: normal; font-size: 24px; letter-spacing: .18em; color: #7f93a1; margin-left: 14px; }
"""


def page(body: str, a: str, b: str) -> str:
    def rgb(h):
        h = h.lstrip("#")
        return ", ".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    css = (CSS.replace("F_HEAVY_I", font_uri("BarlowCondensed-ExtraBoldItalic.ttf"))
              .replace("F_HEAVY", font_uri("BarlowCondensed-ExtraBold.ttf"))
              .replace("F_COND", font_uri("BarlowCondensed-Bold.ttf"))
              .replace("F_BODY", font_uri("Barlow-SemiBold.ttf"))
              .replace("A_RGB", rgb(a)).replace("B_RGB", rgb(b)).replace("A_HEX", a).replace("B_HEX", b))
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


# ============================================================================ pieces
def glyph_strip(seed: int, colour: str) -> str:
    """A row of made-up machine script as an SVG data URI, 600 px wide so it
    tiles: each sign is a few strokes on a 3 x 3 lattice."""
    rnd = random.Random(seed)
    strokes = []
    pts = [(x, y) for y in (2, 10, 18) for x in (0, 7, 14)]
    for g in range(30):
        ox = g * 20 + 3
        for _ in range(rnd.randint(3, 5)):
            (x1, y1), (x2, y2) = rnd.sample(pts, 2)
            if abs(x1 - x2) == 14 and abs(y1 - y2) == 16:
                continue                            # no full diagonals: keeps the signs blocky
            strokes.append(f"M{ox + x1} {y1 + 1}L{ox + x2} {y2 + 1}")
    path = "".join(strokes)
    from urllib.parse import quote
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='600' height='22'>"
           f"<path d='{path}' stroke='{colour}' stroke-width='2.4' stroke-linecap='square' fill='none'/></svg>")
    return f"url(data:image/svg+xml,{quote(svg)})"


def glyphs(x, y, w, seed, colour) -> str:
    return (f"<div class='glyphs' style='left:{x}px;top:{y}px;width:{w}px'>"
            f"<div style='background-image:{glyph_strip(seed, colour)}'></div></div>")


def sparks(n: int, seed: int) -> str:
    rnd = random.Random(seed)
    out = ""
    for _ in range(n):
        period = rnd.choice((4, 4, 8))
        out += (f"<div class='spark' style='left:{rnd.randint(40, 1880)}px;--dx:{rnd.randint(-160, 160)}px;"
                f"animation-duration:{period}s;animation-delay:-{rnd.uniform(0, period):.2f}s;"
                f"width:{rnd.choice((3, 4, 5))}px;height:{rnd.choice((3, 4))}px'></div>")
    return out


def split_title(title: str) -> tuple[str, str]:
    """("TRANSFORMERS", "REVENGE OF THE FALLEN") for a title with a subtitle, else ("", title)."""
    for sep in (": ", " - ", " – ", " — "):
        if sep in title:
            a, b = title.split(sep, 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    return "", title


def fit(text: str, steps) -> int:
    """A font size for `text` from [(max letters, size), ...]."""
    for limit, size in steps:
        if len(text) <= limit:
            return size
    return steps[-1][1]


def btn(bid, x, y, label, action, nav=None, default=False, small=False, right=False) -> str:
    navs = "".join(f" data-nav-{d}='{t}'" for d, t in (nav or {}).items())
    side = f"right:{x}px" if right else f"left:{x}px"
    return (f"<div class='btn{' sm' if small else ''}' data-button='{bid}' data-action='{action}'{navs}"
            f"{' data-default' if default else ''} style='{side};top:{y}px'><span class='mk'></span>{label}</div>")


def lock(bid, x, y, w, h, tag, action, nav=None, default=False) -> str:
    navs = "".join(f" data-nav-{d}='{t}'" for d, t in (nav or {}).items())
    return (f"<div class='lock' data-button='{bid}' data-action='{action}'{navs}{' data-default' if default else ''} data-pad='8'"
            f" style='left:{x}px;top:{y}px;width:{w}px;height:{h}px'>"
            f"<i class='tl'></i><i class='tr'></i><i class='bl'></i><i class='br'></i>"
            f"<div class='edge' style='top:0'></div><div class='edge' style='bottom:0'></div>"
            f"<div class='tag'>{tag}</div></div>")


# ============================================================================ the theme
class Theme(BaseTheme):
    name = "Ironclad"
    description = "Heavy machinery: blast doors, turning rings, lens flares and sparks. Adds an in-film progress bar."
    author = "Boxset"
    version = "1.0"
    limits = {"min_films": 1, "max_films": 5}
    options = [
        {"key": "title", "label": "Title", "type": "text", "default": "THE COLLECTION"},
        {"key": "tagline", "label": "Line above the title", "type": "text", "default": "THE COMPLETE"},
        {"key": "accent", "label": "Energy colour", "type": "color", "default": "#3FD9FF",
         "choices": ["#3FD9FF", "#7CFF6B", "#C59BFF", "#FF4D4D"]},
        {"key": "heat", "label": "Spark colour", "type": "color", "default": "#FF8A1F",
         "choices": ["#FF8A1F", "#FFD23F", "#FF4D4D"]},
        {"key": "motion", "label": "Moving backgrounds", "type": "bool", "default": True,
         "help": "Turning rings, light sweeps and sparks. Off renders faster."},
        {"key": "popup", "label": "Progress bar during the film", "type": "bool", "default": True,
         "help": "Shown by the remote's Pop-up Menu button: time, chapters to jump to, Resume and Menu."},
        {"key": "main_music", "label": "Main menu music", "type": "file", "filter": "audio",
         "help": "Loops while the main menu is showing. MP3, WAV, FLAC or M4A."},
        {"key": "emblem_left", "label": "Emblem, left of the title", "type": "file", "filter": "image",
         "help": "Your own picture (PNG or JPG). A white background is removed."},
        {"key": "emblem_right", "label": "Emblem, right of the title", "type": "file", "filter": "image"},
        {"key": "poster1", "label": "Poster, film 1", "type": "file", "filter": "image",
         "help": "Your own picture, upright (2:3). Left empty, Boxset looks beside the film for a picture "
                 "with the film's name, or poster.jpg."},
        {"key": "poster2", "label": "Poster, film 2", "type": "file", "filter": "image"},
        {"key": "poster3", "label": "Poster, film 3", "type": "file", "filter": "image"},
        {"key": "poster4", "label": "Poster, film 4", "type": "file", "filter": "image"},
        {"key": "poster5", "label": "Poster, film 5", "type": "file", "filter": "image"},
    ]

    # ------------------------------------------------------------------ the user's own pictures
    def poster(self, f) -> str | None:
        """Film f's poster: the one chosen in the settings, else a picture beside
        the film (same name, name-poster, or poster / folder / cover)."""
        chosen = self.options.get(f"poster{f.number}")
        if chosen:
            path = self.ctx.user_file(chosen)
            if os.path.isfile(path):
                return path
            self.ctx.log(f"    poster for film {f.number} not found: {chosen}")
        folder, name = os.path.split(f.file)
        stem = os.path.splitext(name)[0]
        for base in (stem, stem + "-poster", stem + ".poster", "poster", "folder", "cover"):
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                path = os.path.join(folder, base + ext)
                if os.path.isfile(path):
                    return path
        return None

    def emblem(self, side: str) -> str:
        """The emblem chosen for a side as a URL ('' if none), its white (or any
        flat, pale) background made see-through."""
        chosen = self.options.get(f"emblem_{side}")
        if not chosen:
            return ""
        src = self.ctx.user_file(chosen)
        if not os.path.isfile(src):
            self.ctx.log(f"    emblem not found: {chosen}")
            return ""
        folder = os.path.join(self.ctx.out, "frames")
        os.makedirs(folder, exist_ok=True)
        out = os.path.join(folder, f"emblem_{side}_{int(os.path.getmtime(src))}.png")
        if not os.path.exists(out):
            im = Image.open(src)
            has_alpha = im.mode in ("RGBA", "LA") and im.getchannel("A").getextrema()[0] < 250
            im = im.convert("RGBA")
            if not has_alpha:                      # white paper -> nothing; the edge fades over 30 levels
                r, g, b, _ = im.split()
                from PIL import ImageChops
                darkest = ImageChops.darker(ImageChops.darker(r, g), b)
                im.putalpha(darkest.point(lambda v: 255 if v < 215 else max(0, round((245 - v) * 8.5))))
            box = im.getchannel("A").getbbox()
            if box:
                im = im.crop(box)
            im.thumbnail((1200, 1200), Image.LANCZOS)
            im.save(out)
        return self.ctx.uri(out)

    def build(self, ctx):
        o = self.options
        self.ctx, self.e = ctx, ctx.esc
        self.a, self.b = o["accent"], o["heat"]
        self.n = len(ctx.films)
        if self.n > 5:
            raise RuntimeError("Ironclad has room for up to 5 films.")
        self.animate = LOOP if o.get("motion", True) else None
        music = ctx.user_file(o["main_music"]) if o.get("main_music") else None
        ctx.log("  main bay")
        self.main(music)
        for f in ctx.films:
            ctx.log(f"  film {f.number:02d}: {f.title}")
            self.film_page(f)
            if len(f.chapters) > 1:
                self.scenes(f)
            nxt = ctx.films[f.number % self.n]           # when a film ends: the bay, on the next door
            ctx.after_film(f.number, act.menu("main", f"film{nxt.number}"))
        if o.get("popup", True) and not hasattr(ctx, "popup"):
            ctx.log("  progress bar skipped: this version of Boxset can't put a pop-up in a film yet")
        elif o.get("popup", True):
            for f in ctx.films:
                ctx.log(f"  progress bar {f.number:02d}")
                Hud(f, self.n, self.a, self.b).build(ctx.popup(f.number))
        ctx.start("main")

    def page(self, body: str) -> str:
        return page(body, self.a, self.b)

    def _frame(self, number: int, seconds: float, width: int = 1920):
        """A frame from a film as a JPEG (for Boxset versions without ctx.frame)."""
        import subprocess
        from boxset.probe import need
        film = self.ctx.film(number)
        seconds = max(0.0, min(float(seconds), max(0.0, film.duration - 1)))
        folder = os.path.join(self.ctx.out, "frames")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"film{number:02d}_{round(seconds * 10):07d}_{width}.jpg")
        if not os.path.exists(path):
            subprocess.run([need("ffmpeg"), "-v", "error", "-y", "-ss", f"{seconds:.3f}", "-i", film.file,
                            "-frames:v", "1", "-vf", f"scale={width}:-2:flags=lanczos", "-q:v", "2", path],
                           check=False, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return path if os.path.exists(path) else None

    def shot(self, film, part: float, width: int = 1920) -> str:
        """A frame from `part` of the way through the film, as a URL ('' if there's none)."""
        grab = getattr(self.ctx, "frame", None) or self._frame
        path = grab(film.number, film.duration * part, width)
        if not path:
            thumbs = [c.thumb for c in film.chapters if c.thumb]
            path = thumbs[len(thumbs) // 2] if thumbs else None
        return self.ctx.uri(path) if path else ""

    # ------------------------------------------------------------------ main
    def main(self, music):
        ctx, e, o, n = self.ctx, self.e, self.options, self.n
        posters = {f.number: self.poster(f) for f in ctx.films}
        with_posters = any(posters.values())
        w = {1: 620, 2: 600, 3: 520, 4: 396, 5: 300}[n]
        gap = {1: 0, 2: 110, 3: 70, 4: 60, 5: 60}[n]
        h, top = 590, 300
        if with_posters:                           # upright doors, the poster filling each
            w = {1: 400, 2: 400, 3: 400, 4: 370, 5: 300}[n]
            gap = {1: 0, 2: 170, 3: 130, 4: 70, 5: 60}[n]
            h = round((w - 24) * 1.5) + 24
            top = 296 + (600 - h) // 2
        x0 = (1920 - (n * w + (n - 1) * gap)) // 2
        shot_h = 330
        doors, locks = "", ""
        ids = [f"film{f.number}" for f in ctx.films]
        for i, f in enumerate(ctx.films):
            x = x0 + i * (w + gap)
            kick, ttl = split_title(f.title)
            size = fit(ttl, [(9, 78), (13, 64), (18, 54), (24, 46), (34, 38), (99, 32)])
            if n >= 4:
                size = round(size * .78)
            meta = " &nbsp;·&nbsp; ".join(x_ for x_ in [str(f.year or ""), f.runtime] if x_)
            src = self.shot(f, .32, 960)
            if with_posters:
                art = ctx.uri(posters[f.number]) if posters[f.number] else src
                doors += f"""
            <div class='door' style='left:{x}px;top:{top}px;width:{w}px;height:{h}px'>
              <div class='shell'></div>
              <div class='poster' style='background-image:url("{art}")'></div>
              <div class='abs' style='left:0;right:0;top:12px;height:{h - 24}px;overflow:hidden'><div class='scan' style='--travel:{h + 70}px'></div></div>
              <div class='strip'><b>{f.number:02d}</b><span>{meta}</span></div>
              <div class='seam' style='bottom:10px;animation-delay:-{i * .5:.1f}s'></div>
              <div class='rivet' style='left:16px;top:44px'></div><div class='rivet' style='right:16px;top:44px'></div>
            </div>"""
                nav = {"left": ids[i - 1], "right": ids[(i + 1) % n], "down": "all" if n > 1 else ids[i]}
                locks += lock(ids[i], x - 18, top - 18, w + 36, h + 36, "OPEN", act.menu(f"film{f.number:02d}", "play"),
                              nav, default=(i == 0))
                continue
            doors += f"""
            <div class='door' style='left:{x}px;top:{top}px;width:{w}px;height:{h}px'>
              <div class='shell'></div>
              <div class='shot' style='height:{shot_h}px;background-image:url("{src}")'></div>
              <div class='abs' style='left:0;right:0;top:12px;height:{shot_h}px;overflow:hidden'><div class='scan' style='--travel:{shot_h + 90}px'></div></div>
              <div class='hazard' style='top:{shot_h + 12}px'></div>
              <div class='seam' style='top:{shot_h + 30}px;animation-delay:-{i * .5:.1f}s'></div>
              <div class='no' style='top:{shot_h - 62}px'>{f.number:02d}</div>
              <div class='plate' style='top:{shot_h + 62}px'>
                <div class='kick' style='font-size:22px;margin-bottom:10px'>{e(kick) or 'FILM ' + str(f.number)}</div>
                <div class='ttl' style='font-size:{size}px'>{e(ttl)}</div>
                <div class='small' style='font-size:22px;margin-top:14px'>{meta}</div>
              </div>
              <div class='rivet' style='left:16px;top:{shot_h + 50}px'></div><div class='rivet' style='right:16px;top:{shot_h + 50}px'></div>
              <div class='rivet' style='left:16px;bottom:44px'></div><div class='rivet' style='right:16px;bottom:44px'></div>
            </div>"""
            nav = {"left": ids[i - 1], "right": ids[(i + 1) % n], "down": "all" if n > 1 else ids[i]}
            locks += lock(ids[i], x - 18, top - 18, w + 36, h + 36, "OPEN", act.menu(f"film{f.number:02d}", "play"),
                          nav, default=(i == 0))
        years = [f.year for f in ctx.films if f.year]
        span = f"{min(years)} – {max(years)} &nbsp;·&nbsp; " if len(set(years)) > 1 else ""
        hours = ctx.total_seconds / 3600
        title = o.get("title") or ""
        tsize = fit(title, [(10, 150), (14, 128), (20, 104), (28, 82), (99, 64)])
        all_btn = (f"<div class='btn' data-button='all' data-action='{act.playall()}' data-nav-up='{ids[n // 2]}'"
                   f" style='left:50%;top:942px;transform:translateX(-50%)'><span class='mk'></span>PLAY ALL</div>") if n > 1 else ""
        el, er = self.emblem("left"), self.emblem("right")
        marks = ""
        if el or er:
            half = min(700, max(380, len(title) * tsize * .23 + 60))        # half the title's width, roughly
            for src, side, x in ((el, "l", 960 - half - 190), (er, "r", 960 + half + 20)):
                if src:
                    ghost_x = -170 if side == "l" else 1270
                    marks += (f"<div class='emblem ghost' style='left:{ghost_x}px;top:150px;width:820px;height:820px;"
                              f"background-image:url(\"{src}\")'></div>"
                              f"<div class='emblem {side}' style='left:{x:.0f}px;top:66px;width:170px;height:190px;"
                              f"background-image:url(\"{src}\")'></div>")
        strips = "" if marks else glyphs(96, 76, 520, 11, self.a) + glyphs(1304, 76, 520, 23, self.a)
        body = f"""
        <div class='bg'></div><div class='hex'></div>
        <div class='machine'><div class='ring r1'></div><div class='ring r2'></div><div class='ring r3'></div><div class='ring r4'></div></div>
        <div class='rays'></div><div class='core'></div>
        {marks}
        {sparks(46, 7)}
        {strips}
        <div class='abs' style='left:0;right:0;top:70px;text-align:center'>
          <div class='kick' style='font-size:30px'>{e(o.get('tagline') or '')}</div>
          <div class='metal' style='font-size:{tsize}px;margin-top:8px'>{e(title)}</div>
        </div>
        {doors}
        <div class='flare fl1'></div><div class='flare fl2'></div><div class='flare fl3'></div>
        <div class='grade'></div>
        <div class='bar t'></div><div class='bar b'></div>
        <div class='chev' style='left:96px;top:18px'></div><div class='chev' style='right:96px;top:18px;transform:scaleX(-1)'></div>
        {all_btn}
        {locks}
        <div class='hint' style='left:96px'>&#9664; &#9654; choose a film &nbsp;·&nbsp; ok to open</div>
        <div class='hint' style='right:96px'>{span}{n} film{'s' if n != 1 else ''} &nbsp;·&nbsp; {hours:.1f} hours</div>
        """
        ctx.html.menu("main", self.page(body), music=music, animate=self.animate)

    # ------------------------------------------------------------------ one film
    def film_page(self, f):
        ctx, e, n = self.ctx, self.e, self.n
        kick, ttl = split_title(f.title)
        size = fit(ttl, [(8, 210), (12, 170), (16, 138), (22, 112), (30, 92), (99, 74)])
        has_scenes = len(f.chapters) > 1
        ids = ["play"] + (["scenes"] if has_scenes else []) + ["back"]
        labels = {"play": ("PLAY FILM", act.title(f.number)),
                  "scenes": ("SCENE SELECTION", act.menu(f"sc{f.number:02d}p1", "c1")),
                  "back": ("ALL FILMS", act.menu("main", f"film{f.number}"))}
        buttons = ""
        for i, bid in enumerate(ids):
            nav = {"up": ids[i - 1], "down": ids[(i + 1) % len(ids)]}
            buttons += btn(bid, 96 + i * 26, 690 + i * 96, labels[bid][0], labels[bid][1], nav, default=(i == 0))
        poster = self.poster(f)
        if poster:
            feature = (f"<div class='reticle' style='left:1250px;top:190px'></div>"
                       f"<div class='one-sheet' style='left:1320px;top:120px;width:380px;height:558px'>"
                       f"<div class='glow'></div><div class='shell'></div>"
                       f"<div class='art' style='background-image:url(\"{ctx.uri(poster)}\")'></div></div>")
        else:
            feature = "<div class='reticle' style='left:1190px;top:230px'></div>"
        el = self.emblem("left")
        mark = (f"<div class='emblem l' style='left:96px;top:132px;width:92px;height:100px;background-image:url(\"{el}\")'></div>"
                if el else "")
        tx = 212 if el else 96
        body = f"""
        <div class='back' style='background-image:url("{self.shot(f, .55)}")'></div>
        <div class='back-grade'></div>
        {feature}{mark}
        {sparks(22, 30 + f.number)}
        <div class='flare fl1' style='top:604px'></div><div class='flare fl3' style='top:490px;left:1000px;width:900px'></div>
        {glyphs(tx, 112, 600, 40 + f.number, self.a)}
        <div class='abs' style='left:{tx}px;top:150px;width:1140px'>
          <div class='kick' style='font-size:34px'>{e(kick) or f'FILM {f.number} OF {n}'}</div>
        </div>
        <div class='abs' style='left:96px;top:{250 if el else 200}px;width:{1180 if poster else 1240}px'>
          <div class='metal' style='font-size:{round(size * (.86 if poster else 1))}px;padding-right:30px'>{e(ttl)}</div>
        </div>
        <div class='rule' style='left:96px;top:640px;width:900px'></div>
        <div class='readout' style='left:1240px;top:800px'>running time<b>{f.runtime}</b></div>
        <div class='readout' style='left:1540px;top:800px'>chapters<b>{len(f.chapters):02d}</b></div>
        <div class='readout' style='left:1240px;top:910px'>released<b>{f.year or '—'}</b></div>
        <div class='readout' style='left:1540px;top:910px'>film<b>{f.number:02d} / {n:02d}</b></div>
        <div class='grade'></div>
        <div class='bar t'></div><div class='bar b'></div>
        {buttons}
        """
        ctx.html.menu(f"film{f.number:02d}", self.page(body), animate=self.animate)

    # ------------------------------------------------------------------ scenes
    def scenes(self, f):
        ctx, e = self.ctx, self.e
        pages = ctx.pages(f.chapters, 8)
        cw, ch, gx, gy = 400, 225, 48, 108
        x0 = (1920 - (4 * cw + 3 * gx)) // 2
        kick, ttl = split_title(f.title)
        for p, chunk in enumerate(pages, 1):
            cells, locks = "", ""
            for j, c in enumerate(chunk):
                row, col = divmod(j, 4)
                x, y = x0 + col * (cw + gx), 236 + row * (ch + gy)
                src = f"background-image:url(\"{ctx.uri(c.thumb)}\")" if c.thumb else "background:#10161c"
                cells += (f"<div class='cell-frame' style='left:{x - 8}px;top:{y - 8}px;width:{cw + 16}px;height:{ch + 16}px'></div>"
                          f"<div class='cell' style='left:{x}px;top:{y}px;width:{cw}px;height:{ch}px;{src}'></div>"
                          f"<div class='cap' style='left:{x}px;top:{y + ch + 16}px'>{c.number:02d}<span>{c.timecode}</span></div>")
                locks += lock(f"c{j + 1}", x - 12, y - 12, cw + 24, ch + 24, "PLAY", act.chapter(f.number, c.number),
                              default=(j == 0))
            links = btn("back", 96, 962, "BACK", act.menu(f"film{f.number:02d}", "scenes"), small=True)
            if p > 1:
                links += btn("prev", 700, 962, "PREVIOUS", act.menu(f"sc{f.number:02d}p{p - 1}", "c1"), small=True)
            if p < len(pages):
                links += btn("next", 1000, 962, "MORE SCENES", act.menu(f"sc{f.number:02d}p{p + 1}", "c1"), small=True)
            body = f"""
            <div class='bg'></div><div class='hex' style='animation:none'></div>
            <div class='abs' style='left:96px;top:76px'>
              <div class='kick' style='font-size:26px'>SCENE SELECTION &nbsp;·&nbsp; {p} / {len(pages)}</div>
              <div class='metal' style='font-size:76px;margin-top:8px;padding-right:20px'>{e(ttl)[:40]}</div>
            </div>
            {glyphs(1224, 96, 600, 60 + p, self.a)}
            {cells}
            <div class='grade'></div><div class='bar t'></div><div class='bar b'></div>
            {locks}{links}
            """
            ctx.html.menu(f"sc{f.number:02d}p{p}", self.page(body))


# ============================================================================ the in-film progress bar
SS = 2                           # drawn at twice the size and scaled down, for smooth edges


def _hex(h: str, alpha: int = 255) -> tuple:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _mix(c1, c2, k: float) -> tuple:
    return tuple(round(a + (b - a) * k) for a, b in zip(c1, c2))


def _font(name: str, size: int):
    return ImageFont.truetype(os.path.join(FONTS, name), size * SS)


def _clock(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60}:{m % 60:02d}"


class Hud:
    """The pop-up: a slab of armour along the bottom of the picture.

        [ time ][ ====== progress, one segment per chapter ====== ][ RESUME ][ MENU ]

    It is drawn as tiles that sit edge to edge (a Blu-ray's buttons can't overlap),
    each tile only when it changes, so a two-hour film needs a few hundred small
    pictures, not thousands."""
    X0, Y0, W, H = 96, 852, 1728, 168
    TIME_W, BTN_W = 316, 176
    TRACK_Y, TRACK_H = 78, 34
    PLATE_ALPHA = 236

    def __init__(self, film, n_films: int, accent: str, heat: str):
        self.film, self.n_films = film, n_films
        self.a, self.b = _hex(accent), _hex(heat)
        self.bar_x = self.X0 + self.TIME_W
        self.bar_w = self.W - self.TIME_W - 2 * self.BTN_W
        self.f_big = _font("BarlowCondensed-ExtraBoldItalic.ttf", 86)
        self.f_mid = _font("BarlowCondensed-ExtraBoldItalic.ttf", 36)
        self.f_btn = _font("BarlowCondensed-ExtraBoldItalic.ttf", 34)
        self.f_lab = _font("BarlowCondensed-Bold.ttf", 20)
        self.f_num = _font("BarlowCondensed-Bold.ttf", 22)
        self.f_tag = _font("BarlowCondensed-ExtraBold.ttf", 24)
        self.cache: dict = {}
        # one segment per chapter; chapters too short to hit share a segment
        d = film.duration
        self.columns = []                # [first chapter, x from the bar's left, width]
        for c in film.chapters:
            x = round(self.bar_w * c.start / d)
            if self.columns and x - self.columns[-1][1] < 14:
                continue
            self.columns.append([c, x, 0])
        for k, col in enumerate(self.columns):
            end = self.columns[k + 1][1] if k + 1 < len(self.columns) else self.bar_w
            col[2] = end - col[1]

    # ---------------------------------------------------------------- drawing
    def plate(self, w: int, lit: bool = False, cut: str = "") -> Image.Image:
        """A tile of the slab, `w` wide (at drawing size): steel, lighter along
        the top edge. cut: "l" or "r" slices that end off at an angle."""
        W, H = w * SS, self.H * SS
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        top, mid, low = (30, 39, 48), (20, 27, 34), (10, 14, 18)
        if lit:
            top, mid, low = (44, 60, 72), (30, 44, 55), (16, 24, 31)
        for y in range(H):
            k = y / (H - 1)
            c = _mix(top, mid, k / .45) if k < .45 else _mix(mid, low, (k - .45) / .55)
            d.line([(0, y), (W, y)], fill=c + (self.PLATE_ALPHA,))
        d.rectangle([0, 0, W, 3 * SS - 1], fill=(96, 110, 122, 255))                 # the top edge catches the light
        d.rectangle([0, 3 * SS, W, 5 * SS - 1], fill=self.a[:3] + (255,))            # a line of energy under it
        d.rectangle([0, H - 4 * SS, W, H], fill=(5, 7, 9, 255))
        if cut:
            c = 30 * SS
            mask = Image.new("L", (W, H), 255)
            md = ImageDraw.Draw(mask)
            if "l" in cut:
                md.polygon([(0, 0), (c, 0), (0, c)], fill=0)
                md.polygon([(0, H), (c, H), (0, H - c)], fill=0)
            if "r" in cut:
                md.polygon([(W, 0), (W - c, 0), (W, c)], fill=0)
                md.polygon([(W, H), (W - c, H), (W, H - c)], fill=0)
            im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", (W, H), 0), mask))
        return im

    def done(self, im: Image.Image) -> Image.Image:
        """Scale a drawn tile down to its real size; pixels are solid or absent,
        with the slab's own see-through level in between kept as it is."""
        out = im.resize((im.width // SS, im.height // SS), Image.LANCZOS)
        a = out.getchannel("A").point(lambda v: 0 if v < 110 else (self.PLATE_ALPHA if v < 246 else 255))
        out.putalpha(a)
        return out

    def text(self, d, xy, s, font, fill, spacing: float = 0.0, anchor: str = "l"):
        """Text with letter spacing (in ems); anchor l, m or r. Returns its width."""
        gap = spacing * font.size
        widths = [d.textlength(ch, font=font) for ch in s]
        total = sum(widths) + gap * max(0, len(s) - 1)
        x, y = xy
        x = x - total / 2 if anchor == "m" else x - total if anchor == "r" else x
        for ch, w in zip(s, widths):
            d.text((x, y), ch, font=font, fill=fill)
            x += w + gap
        return total

    def time_tile(self, t: float, chapter) -> Image.Image:
        im = self.plate(self.TIME_W, cut="l")
        d = ImageDraw.Draw(im)
        S = SS
        self.text(d, (44 * S, 20 * S), f"FILM {self.film.number:02d}  ·  ELAPSED", self.f_lab, self.a, .16)
        w = self.text(d, (42 * S, 36 * S), _clock(t), self.f_big, (242, 248, 251, 255))
        self.text(d, (42 * S + w + 12 * S, 82 * S), "/ " + _clock(self.film.duration), self.f_mid, (128, 146, 160, 255))
        self.text(d, (44 * S, 134 * S), f"CHAPTER {chapter.number:02d} OF {len(self.film.chapters):02d}", self.f_lab,
                  (150, 168, 181, 255), .16)
        d.rectangle([im.width - 3 * S, 14 * S, im.width - 1, im.height - 14 * S], fill=(6, 9, 12, 255))   # seam
        return self.done(im)

    def column_tile(self, k: int, fill: int, head, current: bool, selected: bool) -> Image.Image:
        """Segment k of the bar: `fill` of its pixels done, the playhead at `head`
        (pixels in, or None), lit when it's the chapter playing or the one chosen."""
        key = (k, fill, head, current, selected)
        if key in self.cache:
            return self.cache[key]
        chapter, x0, w = self.columns[k]
        S = SS
        im = self.plate(w, lit=selected)
        d = ImageDraw.Draw(im)
        W, H = im.size
        ty, th = self.TRACK_Y * S, self.TRACK_H * S
        d.rectangle([0, ty - 3 * S, W, ty + th + 3 * S], fill=(44, 55, 64, 255))       # the track's rim
        d.rectangle([0, ty, W, ty + th], fill=(5, 8, 11, 255))
        if fill > 0:
            fw = fill * S
            d.rectangle([0, ty, fw, ty + th], fill=self.a)
            d.rectangle([0, ty, fw, ty + 5 * S], fill=_mix(self.a, (255, 255, 255, 255), .62))
            d.rectangle([0, ty + th - 7 * S, fw, ty + th], fill=_mix(self.a, (0, 0, 0, 255), .38))
            step = 22 * S                                    # slashes, lined up across segments
            gx = -((x0 * S) % step)
            while gx < fw:
                d.polygon([(gx, ty + th), (gx + 8 * S, ty + th), (gx + 8 * S + th // 2, ty), (gx + th // 2, ty)],
                          fill=_mix(self.a, (0, 0, 0, 255), .30))
                gx += step
            if fw < W:
                d.rectangle([fw, ty, W, ty + th], fill=(5, 8, 11, 255))
        else:
            step = 22 * S                                    # faint marks where the bar will fill
            gx = -((x0 * S) % step)
            while gx < W:
                d.rectangle([gx, ty + th // 2 - S, gx + 6 * S, ty + th // 2 + S], fill=(34, 44, 52, 255))
                gx += step
        if k:                                                # a gap between segments
            d.rectangle([0, ty - 3 * S, 2 * S, ty + th + 3 * S], fill=(12, 16, 20, 255))
        # the chapter's number above the track
        label = f"{chapter.number:02d}"
        if w >= 26:
            if selected:
                tw = d.textlength(label, font=self.f_tag) + 16 * S
                tx = min(max(6 * S, 0), max(0, W - tw - 4 * S))
                d.polygon([(tx + 6 * S, 24 * S), (tx + tw, 24 * S), (tx + tw - 6 * S, 56 * S), (tx, 56 * S)], fill=self.a)
                self.text(d, (tx + tw / 2, 25 * S), label, self.f_tag, (4, 16, 24, 255), anchor="m")
            else:
                colour = self.b if current else (120, 138, 151, 255)
                self.text(d, (8 * S, 28 * S), label, self.f_num, colour)
                d.rectangle([2 * S if k else 0, 58 * S, 4 * S if k else 2 * S, ty - 3 * S], fill=colour)
        if selected:
            if w >= 84:
                self.text(d, (W / 2, 124 * S), chapter.timecode, self.f_num, self.a, anchor="m")
            b = 3 * S
            for box in ([0, 8 * S, W - 1, 8 * S + b], [0, H - 8 * S - b, W - 1, H - 8 * S],
                        [0, 8 * S, b, H - 8 * S], [W - 1 - b, 8 * S, W - 1, H - 8 * S]):
                d.rectangle(box, fill=self.a)
        elif current and w >= 26:                            # a marker over the chapter playing
            d.polygon([(8 * S, 12 * S), (26 * S, 12 * S), (17 * S, 22 * S)], fill=self.b)
        if head is not None:
            hx = min(max(head * S, 4 * S), W - 4 * S)
            d.rectangle([hx - 3 * S, ty - 14 * S, hx + 3 * S, ty + th + 14 * S], fill=(255, 244, 228, 255))
            d.rectangle([hx - 5 * S, ty - 14 * S, hx - 3 * S, ty + th + 14 * S], fill=self.b)
            d.rectangle([hx + 3 * S, ty - 14 * S, hx + 5 * S, ty + th + 14 * S], fill=self.b)
        self.cache[key] = self.done(im)
        return self.cache[key]

    def button_tile(self, label: str, selected: bool, cut: str = "") -> Image.Image:
        key = (label, selected)
        if key in self.cache:
            return self.cache[key]
        S = SS
        im = self.plate(self.BTN_W, cut=cut)
        d = ImageDraw.Draw(im)
        W, H = im.size
        d.rectangle([0, 14 * S, 2 * S, H - 14 * S], fill=(6, 9, 12, 255))             # seam
        box = [16 * S, 44 * S, W - 16 * S, H - 44 * S]
        if cut:
            box[2] -= 10 * S
        if selected:
            d.polygon([(box[0] + 14 * S, box[1]), (box[2], box[1]), (box[2] - 14 * S, box[3]), (box[0], box[3])], fill=self.a)
            ink = (4, 16, 24, 255)
        else:
            d.polygon([(box[0] + 14 * S, box[1]), (box[2], box[1]), (box[2] - 14 * S, box[3]), (box[0], box[3])],
                      fill=(38, 48, 57, 255))
            d.line([(box[0] + 14 * S, box[1]), (box[2], box[1])], fill=(92, 106, 118, 255), width=2 * S)
            ink = (198, 212, 221, 255)
        self.text(d, ((box[0] + box[2]) / 2, 62 * S), label, self.f_btn, ink, .04, anchor="m")
        self.cache[key] = self.done(im)
        return self.cache[key]

    def title_tile(self) -> Image.Image:
        S = SS
        _, ttl = split_title(self.film.title)
        ttl = ttl.upper()[:44]
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        f = _font("BarlowCondensed-Bold.ttf", 24)
        tw = sum(probe.textlength(ch, font=f) for ch in ttl) + .14 * f.size * (len(ttl) - 1)
        W, H = int(tw + 96 * S), 40 * S
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.polygon([(0, 0), (W - 26 * S, 0), (W, H), (0, H)], fill=(14, 19, 24, self.PLATE_ALPHA))
        d.rectangle([0, 0, 8 * S, H], fill=self.b)
        self.text(d, (30 * S, 5 * S), ttl, f, (226, 236, 242, 255), .14)
        return self.done(im)

    # ---------------------------------------------------------------- frames
    def build(self, pop):
        film, n = self.film, self.film.number
        y = self.Y0
        title = self.title_tile()
        last = len(self.columns) - 1
        ids = [f"c{k + 1}" for k in range(len(self.columns))]
        for t in pop.moments(every=60):
            fr = pop.frame(t)
            now = pop.chapter_at(t)
            head_x = self.bar_w * t / film.duration                 # where the playhead is, along the bar
            fr.label("title", self.X0 + 30, y - 40, title)
            fr.label("time", self.X0, y, self.time_tile(t, now))
            current = 0
            for k, (chapter, x, w) in enumerate(self.columns):
                if chapter.start <= t + 0.001:
                    current = k
            for k, (chapter, x, w) in enumerate(self.columns):
                fill = max(0, min(w, round(head_x - x)))
                head = round(head_x - x) if x <= head_x < x + w or (k == last and head_x >= x + w) else None
                nav = {"left": ids[k - 1] if k else "menu", "right": ids[k + 1] if k < last else "resume"}
                fr.button(ids[k], self.bar_x + x, y,
                          {"normal": self.column_tile(k, fill, head, k == current, False),
                           "selected": self.column_tile(k, fill, head, k == current, True)},
                          act.chapter(n, chapter.number), nav)
            bx = self.bar_x + self.bar_w
            fr.button("resume", bx, y, {"normal": self.button_tile("RESUME", False), "selected": self.button_tile("RESUME", True)},
                      act.close(), {"left": ids[current], "right": "menu"})
            fr.button("menu", bx + self.BTN_W, y,
                      {"normal": self.button_tile("MENU", False, "r"), "selected": self.button_tile("MENU", True, "r")},
                      act.menu("main", f"film{n}"), {"left": "resume", "right": ids[0]})
            fr.default = "resume"
