"""Render menu screens written in HTML/CSS with a headless browser.

How a theme writes a screen
---------------------------
Each screen is a 1920x1080 web page. Mark every button with attributes:

    <a data-button="play" data-action="title:5" data-default
       data-nav-down="scenes" data-pad="24">PLAY FILM</a>

    data-button    id of the button (unique on the page)
    data-action    what it does: title:N, chapter:N:C, menu:ID, menu:ID#BUTTON,
                   playall, playlist:ID, lastmenu
    data-default   (optional) highlighted when the menu opens
    data-nav-up / -down / -left / -right   (optional) d-pad targets; without
                   them the player moves to the nearest button
    data-pad       (optional) extra pixels captured around the element, for glows

Style the three looks with [data-state="normal"], [data-state="selected"] and
[data-state="activated"] on the button element. The renderer:

  * shoots the page with the buttons hidden  -> the menu background
  * shoots it once per state with only the buttons showing -> button art
  * optionally records CSS/JS animation frame by frame -> a looping video background
    (JS-driven animation can hook in with  window.boxsetFrame = (ms) => {...})

Relative URLs (fonts, images) resolve against the theme folder. Use ctx.uri(path)
for files elsewhere, like chapter thumbnails.
"""
from __future__ import annotations

import io
import os
import pathlib
import shutil
import subprocess

from PIL import Image

from .probe import need

W, H = 1920, 1080

_PREP_JS = r"""
() => {
  const s = document.createElement('style');
  s.id = 'boxset-style';
  s.textContent = `
    html.bx-no-buttons [data-button] { opacity: 0 !important; }
    html.bx-buttons-only, html.bx-buttons-only body { background: transparent !important; }
    html.bx-buttons-only .bx-off { opacity: 0 !important; }
    html.bx-buttons-only .bx-anc { background: transparent !important; border-color: transparent !important;
      box-shadow: none !important; outline-color: transparent !important; filter: none !important;
      backdrop-filter: none !important; }
    html.bx-buttons-only .bx-anc::before, html.bx-buttons-only .bx-anc::after { opacity: 0 !important; }
  `;
  document.head.appendChild(s);
  const buttons = [...document.querySelectorAll('[data-button]')];
  const inside = el => buttons.some(b => b.contains(el));
  for (const el of document.body.querySelectorAll('*')) {
    if (el.matches('[data-button]') || inside(el)) continue;
    if (buttons.some(b => el.contains(b))) el.classList.add('bx-anc');
    else el.classList.add('bx-off');
  }
  return buttons.length;
}
"""

_FREEZE_JS = r"""
(ms) => {
  for (const a of document.getAnimations()) { a.pause(); a.currentTime = ms; }
  if (typeof window.boxsetFrame === 'function') window.boxsetFrame(ms);
}
"""

_BUTTONS_JS = r"""
() => [...document.querySelectorAll('[data-button]')].map(b => {
  const r = b.getBoundingClientRect();
  const pad = parseFloat(b.dataset.pad || '0');
  return {
    id: b.dataset.button, action: b.dataset.action || '',
    default: b.hasAttribute('data-default'),
    auto: b.hasAttribute('data-auto'),
    nav: Object.fromEntries(['up','down','left','right']
          .filter(d => b.getAttribute('data-nav-' + d))
          .map(d => [d, b.getAttribute('data-nav-' + d)])),
    box: [r.left - pad, r.top - pad, r.right + pad, r.bottom + pad],
  };
})
"""


def file_uri(path: str) -> str:
    return pathlib.Path(os.path.abspath(path)).as_uri()


class HtmlRenderer:
    def __init__(self, ctx):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("This theme draws with HTML and needs Playwright: pip install playwright")
        self.ctx = ctx
        self._pw = sync_playwright().start()
        self._browser = self._launch()
        self._page = self._browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        self._dir = os.path.join(ctx.out, "html")
        os.makedirs(self._dir, exist_ok=True)

    def _launch(self):
        errors = []
        attempts = [{}, {"channel": "msedge"}, {"channel": "chrome"}]
        for exe in ("google-chrome", "chrome", "chromium", "chromium-browser", "msedge"):
            p = shutil.which(exe)
            if p:
                attempts.append({"executable_path": p})
        for kw in attempts:
            try:
                return self._pw.chromium.launch(headless=True, **kw)
            except Exception as e:  # try the next browser
                errors.append(str(e).splitlines()[0])
        raise RuntimeError("Couldn't start a browser for HTML themes. Install Microsoft Edge or Chrome, "
                           "or run: playwright install chromium\n" + "\n".join(errors))

    def close(self):
        try:
            self._browser.close()
        finally:
            self._pw.stop()

    # ------------------------------------------------------------------ load
    def _load(self, name: str, html: str, base: str | None):
        base = base or self.ctx.theme_dir
        if "<base " not in html:
            tag = f'<base href="{file_uri(base)}/">'
            html = html.replace("<head>", "<head>" + tag, 1) if "<head>" in html else tag + html
        path = os.path.join(self._dir, f"{name}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        pg = self._page
        pg.goto(file_uri(path), wait_until="load")
        pg.evaluate("document.fonts.ready.then(() => true)")
        pg.evaluate("""Promise.all([...document.images].map(i => i.complete ? 0 :
                       new Promise(r => { i.onload = i.onerror = r; })))""")
        return pg

    def _shot(self, transparent=False, fmt="png") -> Image.Image:
        data = self._page.screenshot(type=fmt, omit_background=transparent, full_page=False,
                                     **({"quality": 92} if fmt == "jpeg" else {}))
        return Image.open(io.BytesIO(data))

    # ------------------------------------------------------------------ public
    def capture(self, name: str, html: str, base: str | None = None, at_ms: float = 0):
        """Render a screen. Returns (background, buttons) where buttons is a list of dicts
        with id, x, y, images{state: Image}, action, nav, default."""
        pg = self._load(name, html, base)
        count = pg.evaluate(_PREP_JS)
        pg.evaluate(_FREEZE_JS, at_ms)
        info = pg.evaluate(_BUTTONS_JS) if count else []

        pg.evaluate("document.documentElement.classList.add('bx-no-buttons')")
        background = self._shot().convert("RGB")
        pg.evaluate("document.documentElement.classList.remove('bx-no-buttons')")

        shots = {}
        if info:
            pg.evaluate("document.documentElement.classList.add('bx-buttons-only')")
            for st in ("normal", "selected", "activated"):
                pg.evaluate("(s) => document.querySelectorAll('[data-button]').forEach(b => b.dataset.state = s)", st)
                pg.evaluate(_FREEZE_JS, at_ms)
                shots[st] = self._shot(transparent=True).convert("RGBA")
                # re-measure: a state may grow the element (scale, wider border...)
                for b, nb in zip(info, pg.evaluate(_BUTTONS_JS)):
                    b["box"] = [min(b["box"][0], nb["box"][0]), min(b["box"][1], nb["box"][1]),
                                max(b["box"][2], nb["box"][2]), max(b["box"][3], nb["box"][3])]
            pg.evaluate("document.documentElement.classList.remove('bx-buttons-only')")

        buttons = []
        for b in info:
            l, t, r, btm = [round(v) for v in b["box"]]
            l, t, r, btm = max(0, l), max(0, t), min(W, r), min(H, btm)
            crops = {st: shots[st].crop((l, t, r, btm)) for st in shots}
            # trim to the area any state actually paints
            boxes = [c.getchannel("A").getbbox() for c in crops.values()]
            boxes = [x for x in boxes if x]
            if boxes:
                bl, bt = min(x[0] for x in boxes), min(x[1] for x in boxes)
                br, bb = max(x[2] for x in boxes), max(x[3] for x in boxes)
                crops = {st: c.crop((bl, bt, br, bb)) for st, c in crops.items()}
                l, t = l + bl, t + bt
            buttons.append({"id": b["id"], "x": l, "y": t, "images": crops, "action": b["action"],
                            "nav": b["nav"], "default": b["default"], "auto": b.get("auto", False)})
        return background, buttons

    def record(self, name: str, seconds: float, fps=(24000, 1001)) -> str:
        """Record the currently loaded screen's animation (buttons hidden) to an MP4 loop.
        Call right after capture() for the same screen."""
        pg = self._page
        pg.evaluate("document.documentElement.classList.add('bx-no-buttons')")
        num, den = fps
        frames = round(seconds * num / den)
        out = os.path.join(self._dir, f"{name}_motion.mp4")
        proc = subprocess.Popen(
            [need("ffmpeg"), "-v", "error", "-y", "-f", "image2pipe", "-framerate", f"{num}/{den}",
             "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "14",
             "-pix_fmt", "yuv420p", "-r", f"{num}/{den}", out],
            stdin=subprocess.PIPE)
        try:
            for i in range(frames):
                self.ctx.check()             # Stop works mid-recording
                pg.evaluate(_FREEZE_JS, i * 1000 * den / num)
                proc.stdin.write(pg.screenshot(type="jpeg", quality=93))
                if i and i % 120 == 0:
                    self.ctx.log(f"    recorded {i}/{frames} frames")
        finally:
            proc.stdin.close()
            proc.wait()
        pg.evaluate("document.documentElement.classList.remove('bx-no-buttons')")
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed while recording the '{name}' motion background")
        return out

    def menu(self, menu_id: str, html: str, music: str | None = None, animate: float | None = None,
             base: str | None = None):
        """Render an HTML screen straight into a menu: background (still or recorded
        animation), every marked button, actions and navigation."""
        self.ctx.check()
        bg, buttons = self.capture(menu_id, html, base)
        background = bg
        if animate:
            self.ctx.log(f"    recording {animate:g}s motion background for '{menu_id}'")
            background = self.record(menu_id, animate)
        m = self.ctx.menu(menu_id, background, music=music, loop_seconds=animate)
        for b in buttons:
            m.button(b["id"], b["x"], b["y"], b["images"], b["action"], b["nav"], default=b["default"],
                     auto=b.get("auto", False))
        return m

    def image(self, html: str, width: int, height: int, transparent: bool = True) -> Image.Image:
        """Render any HTML snippet to an image (handy inside image-drawn themes)."""
        self._page.set_viewport_size({"width": width, "height": height})
        try:
            self._load("_snippet", html, None)
            return self._shot(transparent=transparent).convert("RGBA")
        finally:
            self._page.set_viewport_size({"width": W, "height": H})
