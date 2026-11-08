"""Marquee: an old movie palace. Velvet curtains, an Art Deco marquee with
chasing bulbs (recorded as a motion background), a letterboard film list,
admission-ticket film pages and 35mm film-strip scene selection.

Drawn entirely in HTML/CSS (see boxset/html.py for how screens are captured).

Settings (shown in the app's Menu view):
  title_small      "THE COMPLETE"
  title_big        "SAGA"
  timeline_order   [1, 2, 4, ...]   adds a "Story order" ticket + playlist
  main_music       "music/overture.mp3"   loops under the main menu
  motion           true             animate the marquee bulbs (set false for a still menu)
"""
from __future__ import annotations

from boxset.core import BaseTheme, act

LOOP_SECONDS = 6.0   # bulb chase period is 1.2 s, so 6 s loops seamlessly

CSS = r"""
@font-face { font-family: 'Limelight'; src: url(fonts/Limelight-Regular.ttf); }
@font-face { font-family: 'Bebas'; src: url(fonts/BebasNeue-Regular.ttf); }
@font-face { font-family: 'Courier Prime'; src: url(fonts/CourierPrime-Regular.ttf); }
@font-face { font-family: 'Courier Prime'; font-weight: 700; src: url(fonts/CourierPrime-Bold.ttf); }

html, body { margin: 0; width: 1920px; height: 1080px; overflow: hidden; }
body { background: #1b0505; color: #f5e6c4; font-family: 'Courier Prime', monospace; position: relative; }
* { box-sizing: border-box; }
.abs { position: absolute; }

/* velvet curtain: soft vertical folds + vignette */
.curtain { position: absolute; inset: 0;
  background:
    radial-gradient(ellipse at 50% 38%, rgba(0,0,0,0) 0%, rgba(0,0,0,.25) 55%, rgba(0,0,0,.78) 100%),
    repeating-linear-gradient(90deg, #4a0a0e 0px, #6e1016 38px, #8a1a1f 62px, #6e1016 86px, #3d080b 128px); }
.curtain.dim::after { content: ''; position: absolute; inset: 0; background: rgba(10,2,2,.55); }
.valance { position: absolute; left: 0; right: 0; top: 0; height: 64px;
  background: repeating-linear-gradient(90deg, #5c0c11 0 60px, #7d151b 60px 120px);
  box-shadow: 0 10px 24px rgba(0,0,0,.6); }
.valance::after { content: ''; position: absolute; left: 0; right: 0; bottom: -10px; height: 12px;
  background: repeating-linear-gradient(90deg, #d4a63c 0 10px, transparent 10px 20px); }

/* gold Art Deco frame */
.deco { position: absolute; border: 4px solid #d4a63c; box-shadow: 0 0 0 10px #2a0707, 0 0 0 13px #b88a2a, 0 30px 60px rgba(0,0,0,.6); }
.deco::before { content: ''; position: absolute; inset: 14px; border: 1.5px solid rgba(212,166,60,.6); }

/* marquee bulbs */
.bulb { position: absolute; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%;
  background: radial-gradient(circle at 40% 35%, #fffbe8 0%, #ffd56b 45%, #c98a1c 100%);
  box-shadow: 0 0 12px 4px rgba(255,200,90,.65);
  animation: chase 1.2s steps(1, end) infinite; }
@keyframes chase {
  0%   { background: radial-gradient(circle at 40% 35%, #fffbe8 0%, #ffd56b 45%, #c98a1c 100%); box-shadow: 0 0 14px 5px rgba(255,200,90,.7); }
  33.3% { background: radial-gradient(circle at 40% 35%, #8a6a35 0%, #5a3d14 60%, #3a2509 100%); box-shadow: none; }
}

.mq-small { font-family: 'Limelight'; font-size: 54px; letter-spacing: 10px; color: #ffd56b;
  text-shadow: 0 0 18px rgba(255,190,70,.55); }
.mq-big { font-family: 'Limelight'; font-size: 200px; line-height: .95; color: #fff4d6;
  text-shadow: 0 0 22px rgba(255,214,120,.6), 0 4px 0 #8a5a12; }
.mq-sub { font-size: 26px; letter-spacing: 6px; color: #f0d9a8; }

/* tickets */
.tk { position: absolute; }
.ticket { position: absolute; inset: 0; background: #d9c69a; color: #3a0b0b;
  -webkit-mask: radial-gradient(circle at 0 50%, transparent 16px, #000 17px) left / 51% 100% no-repeat,
                radial-gradient(circle at 100% 50%, transparent 16px, #000 17px) right / 51% 100% no-repeat; }
.ticket::before { content: ''; position: absolute; inset: 12px 28px; border: 2px dashed rgba(58,11,11,.45); }
.tk-top { position: absolute; left: 48px; top: 22px; font-weight: 700; font-size: 18px; letter-spacing: 6px; opacity: .8; }
.tk-main { position: absolute; left: 48px; top: 50px; font-family: 'Bebas'; font-size: 56px; letter-spacing: 3px; line-height: 1; }
.tk-sub { position: absolute; left: 48px; bottom: 22px; font-size: 18px; opacity: .85; }
.tk-no { position: absolute; right: 44px; top: 22px; font-weight: 700; font-size: 16px; letter-spacing: 3px; opacity: .65; }
.tk[data-state="selected"] { filter: drop-shadow(0 0 9px rgba(255,200,80,.9)); }
[data-state="selected"] .ticket { background: #ffcc4d; color: #2a0505; }
[data-state="activated"] .ticket { background: #fff8e6; color: #2a0505; }

/* small text buttons */
.link { position: absolute; font-weight: 700; font-size: 22px; letter-spacing: 5px; color: #e9cf98; padding: 10px 18px;
  border: 2px solid transparent; }
.link[data-state="selected"] { color: #2a0505; background: #ffcc4d; border-color: #ffcc4d; }
.link[data-state="activated"] { color: #2a0505; background: #fff8e6; }

/* letterboard */
.board { position: absolute; background:
    repeating-linear-gradient(180deg, #f4ecd8 0 15px, #d9cfb6 15px 17px);
  box-shadow: inset 0 0 40px rgba(0,0,0,.18); }
.board-head { position: absolute; left: 0; right: 0; top: 0; height: 104px; background: #2a0707;
  display: flex; align-items: center; justify-content: center; gap: 40px;
  font-family: 'Limelight'; font-size: 58px; letter-spacing: 12px; color: #ffd56b; text-shadow: 0 0 16px rgba(255,190,70,.5); }
.lb { position: absolute; height: 62px; display: flex; align-items: center; gap: 30px; padding: 0 34px;
  font-family: 'Bebas'; font-size: 50px; letter-spacing: 5px; color: #171212; }
.lb-num { width: 70px; color: #8c1a1f; }
.lb-title { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lb-year { font-size: 40px; color: #4a3d3d; }
.lb-info { display: none; font-family: 'Courier Prime'; font-weight: 700; font-size: 22px; letter-spacing: 2px; }
.lb[data-state="selected"], .lb[data-state="activated"] { background: #a8121d; color: #fff3d6; }
.lb[data-state="activated"] { background: #2a0707; }
.lb[data-state="selected"] .lb-num, .lb[data-state="activated"] .lb-num { color: #ffcc4d; }
.lb[data-state="selected"] .lb-year, .lb[data-state="activated"] .lb-year { display: none; }
.lb[data-state="selected"] .lb-info, .lb[data-state="activated"] .lb-info { display: block; color: #ffe2a3; }
.lb-tag { font-family: 'Courier Prime'; font-weight: 700; font-size: 15px; letter-spacing: 3px; border: 2px solid currentColor;
  padding: 2px 8px; margin-left: 18px; vertical-align: middle; }

/* admission ticket (film page) */
.big-ticket { position: absolute; background: #e8d7ad; color: #3a0b0b;
  -webkit-mask: radial-gradient(circle at 0 0, transparent 30px, #000 31px) top left / 51% 51% no-repeat,
                radial-gradient(circle at 100% 0, transparent 30px, #000 31px) top right / 51% 51% no-repeat,
                radial-gradient(circle at 0 100%, transparent 30px, #000 31px) bottom left / 51% 51% no-repeat,
                radial-gradient(circle at 100% 100%, transparent 30px, #000 31px) bottom right / 51% 51% no-repeat;
  filter: drop-shadow(0 30px 50px rgba(0,0,0,.6)); }
.bt-inner { position: absolute; inset: 22px; border: 3px double rgba(58,11,11,.55); }
.perf { position: absolute; top: 30px; bottom: 30px; width: 0; border-left: 4px dotted rgba(58,11,11,.5); }
.bt-kicker { font-weight: 700; font-size: 22px; letter-spacing: 8px; }
.bt-title { font-family: 'Limelight'; line-height: 1.02; color: #2a0505; }
.bt-meta { font-size: 26px; letter-spacing: 3px; }
.stub { position: absolute; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; text-align: center; }
.stub-no { font-family: 'Bebas'; font-size: 150px; line-height: .9; color: #a8121d; }

/* 35mm film strip */
.strip { position: absolute; left: 0; right: 0; height: 360px; background: #120d0b;
  box-shadow: 0 16px 40px rgba(0,0,0,.6); }
.strip::before, .strip::after { content: ''; position: absolute; left: 0; right: 0; height: 20px;
  background: repeating-linear-gradient(90deg, transparent 0 14px, #d9c8a0 14px 38px, transparent 38px 52px); }
.strip::before { top: 10px; } .strip::after { bottom: 10px; }
.frame-img { position: absolute; object-fit: cover; background: #2a2220; }
.fr { position: absolute; }
.fr-ring { position: absolute; left: 0; top: 0; border: 4px solid #3a302a; }
.fr-label { position: absolute; left: 0; font-weight: 700; font-size: 22px; letter-spacing: 3px; color: #e9cf98; }
.fr-time { position: absolute; font-size: 20px; letter-spacing: 2px; color: #b9a27a; }
.fr[data-state="selected"] .fr-ring { border: 7px solid #ffcc4d; box-shadow: 0 0 12px rgba(255,200,80,.85); }
.fr[data-state="selected"] .fr-label { color: #ffcc4d; }
.fr[data-state="activated"] .fr-ring { border: 7px solid #fff8e6; }
.fr[data-state="activated"] .fr-label { color: #fff8e6; }

.hint { position: absolute; bottom: 40px; font-size: 20px; letter-spacing: 4px; color: #d9bf8a; }
.title-gold { font-family: 'Limelight'; color: #ffd56b; text-shadow: 0 0 16px rgba(255,190,70,.45); }
"""


def page(body: str, title: str = "menu") -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def bulbs(x, y, w, h, spacing=46):
    """Bulbs evenly around a rectangle, staggered in 3 groups so they chase."""
    pts = []
    nx, ny = max(2, round(w / spacing)), max(2, round(h / spacing))
    for i in range(nx):
        pts.append((x + w * i / nx, y))
    for i in range(ny):
        pts.append((x + w, y + h * i / ny))
    for i in range(nx):
        pts.append((x + w - w * i / nx, y + h))
    for i in range(ny):
        pts.append((x, y + h - h * i / ny))
    return "".join(f"<div class='bulb' style='left:{px:.0f}px;top:{py:.0f}px;animation-delay:-{(k % 3) * 0.4:.1f}s'></div>"
                   for k, (px, py) in enumerate(pts))


def ticket(bid, x, y, w, h, top, main, sub, no, action, nav=None, default=False):
    navs = "".join(f" data-nav-{d}='{t}'" for d, t in (nav or {}).items())
    return (f"<div class='tk' data-button='{bid}' data-action='{action}'{' data-default' if default else ''}{navs}"
            f" data-pad='22' style='left:{x}px;top:{y}px;width:{w}px;height:{h}px'>"
            f"<div class='ticket'><div class='tk-top'>{top}</div><div class='tk-no'>{no}</div>"
            f"<div class='tk-main'>{main}</div><div class='tk-sub'>{sub}</div></div></div>")


def link(bid, x, y, label, action, nav=None):
    navs = "".join(f" data-nav-{d}='{t}'" for d, t in (nav or {}).items())
    return (f"<div class='link' data-button='{bid}' data-action='{action}'{navs} style='left:{x}px;top:{y}px'>"
            f"{label}</div>")


class Theme(BaseTheme):
    name = "Marquee"
    description = "Vintage movie palace: chasing marquee bulbs, letterboard, tickets, film strips."
    author = "Boxset"
    version = "1.0"
    limits = {"min_films": 1, "max_films": 11}
    options = [
        {"key": "title_small", "label": "Marquee, first line", "type": "text", "default": "THE COMPLETE"},
        {"key": "title_big", "label": "Marquee, main line", "type": "text", "default": "COLLECTION"},
        {"key": "motion", "label": "Animated marquee lights", "type": "bool", "default": True},
        {"key": "main_music", "label": "Main menu music", "type": "file", "filter": "audio",
         "help": "Loops while the main menu is showing. MP3, WAV, FLAC or M4A."},
        {"key": "timeline_order", "label": "Story order", "type": "order",
         "help": "Adds a Story order ticket that plays the films in story order."},
    ]

    def build(self, ctx):
        o = self.options
        self.ctx, e = ctx, ctx.esc
        self.e = e
        films = ctx.films
        self.n = len(films)
        if self.n > 11:
            raise RuntimeError("The Marquee letterboard fits up to 11 films.")
        order = o.get("timeline_order") or ctx.collection.timeline_order
        timeline = order if order and list(order) != list(range(1, self.n + 1)) else None
        ctx.playlist("release", list(range(1, self.n + 1)))
        if timeline:
            ctx.playlist("timeline", timeline)
        music = ctx.user_file(o["main_music"]) if o.get("main_music") else None

        ctx.log("  marquee (main)")
        self.main(o, timeline, music)
        ctx.log("  letterboard")
        self.board()
        for f in films:
            ctx.log(f"  ticket {f.number:02d}: {f.title}")
            self.film_page(f)
            if len(f.chapters) > 1:
                self.scenes(f)
        for f in ctx.films:  # each film returns to its own page when it ends
            ctx.after_film(f.number, act.menu(f"film{f.number:02d}", "roll"))
        ctx.start("main")

    # ------------------------------------------------------------------ main
    def main(self, o, timeline, music):
        ctx, e = self.ctx, self.e
        years = [f.year for f in ctx.films if f.year]
        span = f" · {min(years)}–{max(years)}" if years else ""
        hrs = round(ctx.total_seconds / 3600)
        tickets = [("play", "ADMIT ALL", "PLAY THE SAGA", f"{self.n} features, release order", act.playlist("release")),
                   ("pick", "ADMIT ONE", "PICK A FEATURE", "choose any film or scene", act.menu("board", "row01"))]
        if timeline:
            tickets.append(("story", "ADMIT ALL", "STORY ORDER", "in the order events happen", act.playlist("timeline")))
        w, gap = 460, 64
        x0 = (1920 - (len(tickets) * w + (len(tickets) - 1) * gap)) // 2
        ids = [t[0] for t in tickets]
        tk_html = ""
        for i, (bid, top, main, sub, action) in enumerate(tickets):
            nav = {"left": ids[i - 1], "right": ids[(i + 1) % len(ids)]}
            tk_html += ticket(bid, x0 + i * (w + gap), 700, w, 170, top, main, sub, f"No. {i + 1:03d}", action,
                              nav, default=(i == 0))
        body = f"""
        <div class='curtain'></div><div class='valance'></div>
        <div class='deco' style='left:250px;top:110px;width:1420px;height:500px;background:#1a0505'></div>
        {bulbs(250, 110, 1420, 500)}
        <div class='abs' style='left:250px;top:150px;width:1420px;text-align:center'>
          <div class='mq-small'>{e(o.get('title_small', 'THE COMPLETE'))}</div>
          <div class='mq-big'>{e(o.get('title_big', 'COLLECTION'))}</div>
          <div class='mq-sub' style='margin-top:26px'>{self.n} FEATURES{span} · {hrs} HOURS</div>
        </div>
        {tk_html}
        <div class='hint' style='left:96px'>&#9664; &#9654; CHOOSE A TICKET &nbsp;·&nbsp; OK TO ENTER</div>
        <div class='hint' style='right:96px'>ONE DISC · NO INTERMISSION</div>
        """
        animate = LOOP_SECONDS if o.get("motion", True) else None
        ctx.html.menu("main", page(body, "Marquee"), music=music, animate=animate)

    # ------------------------------------------------------------- letterboard
    def board(self):
        ctx, e = self.ctx, self.e
        rows = ""
        top0, pitch = 196, 68
        for f in ctx.films:
            up = f"row{f.number - 1:02d}" if f.number > 1 else "lobby"
            down = f"row{f.number + 1:02d}" if f.number < self.n else "lobby"
            info = " · ".join(x for x in [f.runtime, e(f.place).upper()] if x)
            tag = "<span class='lb-tag'>SPIN-OFF</span>" if f.spinoff else ""
            rows += (f"<div class='lb' data-button='row{f.number:02d}' data-action='{act.menu(f'film{f.number:02d}', 'roll')}'"
                     f" data-nav-up='{up}' data-nav-down='{down}'{' data-default' if f.number == 1 else ''}"
                     f" style='left:150px;top:{top0 + (f.number - 1) * pitch}px;width:1620px'>"
                     f"<span class='lb-num'>{f.number:02d}</span><span class='lb-title'>{e(f.title).upper()}{tag}</span>"
                     f"<span class='lb-year'>{f.year or ''}</span><span class='lb-info'>{info}</span></div>")
        body = f"""
        <div class='curtain dim'></div>
        <div class='board deco' style='left:120px;top:60px;width:1680px;height:{top0 - 60 + self.n * pitch + 24}px'>
          <div class='board-head'><span>&#9733;</span>NOW SHOWING<span>&#9733;</span></div>
        </div>
        {rows}
        {link('lobby', 96, 994, '&#9664; LOBBY', act.menu('main', 'pick'), {'up': f'row{self.n:02d}', 'down': 'row01'})}
        <div class='hint' style='right:96px'>&#9650; &#9660; CHOOSE A FEATURE &nbsp;·&nbsp; OK FOR TICKETS</div>
        """
        ctx.html.menu("board", page(body, "Now showing"))

    # ------------------------------------------------------------- film page
    def film_page(self, f):
        ctx, e = self.ctx, self.e
        title = e(f.title).upper()
        L = len(f.title)
        size = 128 if L <= 10 else 104 if L <= 15 else 84 if L <= 24 else 70
        meta = " · ".join(x for x in [str(f.year or ""), f.runtime, e(f.place).upper()] if x)
        kicker = "FEATURE PRESENTATION" + (" · SPIN-OFF" if f.spinoff else "")
        has_scenes = len(f.chapters) > 1
        nxt = ctx.films[f.number] if f.number < self.n else None
        tk = [("roll", "NOW PLAYING", "ROLL FILM", "from the opening frame", act.title(f.number))]
        if has_scenes:
            tk.append(("scenes", "REELS", "SCENES", f"{len(f.chapters)} chapters", act.menu(f"sc{f.number:02d}p1", "f1")))
        if nxt:
            tk.append(("next", "NEXT FEATURE", "NEXT FILM", e(nxt.title)[:30], act.menu(f"film{nxt.number:02d}", "next")))
        else:
            tk.append(("next", "THAT'S A WRAP", "LOBBY", "back to the marquee", act.menu("main", "play")))
        w, gap = 460, 64
        x0 = (1920 - (len(tk) * w + (len(tk) - 1) * gap)) // 2
        ids = [t[0] for t in tk]
        tk_html = ""
        for i, (bid, top, main, sub, action) in enumerate(tk):
            nav = {"left": ids[i - 1], "right": ids[(i + 1) % len(ids)], "up": "back"}
            tk_html += ticket(bid, x0 + i * (w + gap), 800, w, 160, top, main, sub, f"No. {f.number:02d}-{i + 1}",
                              action, nav, default=(i == 0))
        body = f"""
        <div class='curtain'></div><div class='valance'></div>
        <div class='big-ticket' style='left:180px;top:130px;width:1560px;height:600px'>
          <div class='bt-inner'></div>
          <div class='perf' style='left:1160px'></div>
          <div class='abs' style='left:90px;top:80px;width:1020px'>
            <div class='bt-kicker'>ADMIT ONE &nbsp;·&nbsp; {kicker}</div>
            <div style='height:400px;display:flex;align-items:center'>
              <div class='bt-title' style='font-size:{size}px'>{title}</div>
            </div>
            <div class='bt-meta'>{meta}</div>
          </div>
          <div class='stub' style='left:1180px;top:60px;width:340px;height:480px'>
            <div class='bt-kicker'>FEATURE</div>
            <div class='stub-no'>{f.number:02d}</div>
            <div class='bt-kicker'>OF {self.n:02d}</div>
            <div class='bt-meta' style='font-size:18px;margin-top:18px'>KEEP THIS STUB</div>
          </div>
        </div>
        {tk_html}
        {link('back', 80, 84, '&#9664; ALL FEATURES', act.menu('board', f'row{f.number:02d}'), {'down': 'roll'})}
        """
        ctx.html.menu(f"film{f.number:02d}", page(body, f.title))

    # ------------------------------------------------------------ film strips
    def scenes(self, f):
        ctx, e = self.ctx, self.e
        pages = ctx.pages(f.chapters, 8)
        fw, fh, gap = 396, 223, 56
        x0 = (1920 - (4 * fw + 3 * gap)) // 2
        for p, chunk in enumerate(pages, 1):
            imgs, frames = "", ""
            for j, ch in enumerate(chunk):
                row, col = divmod(j, 4)
                x, y = x0 + col * (fw + gap), 214 + row * 400
                src = f"src='{ctx.uri(ch.thumb)}'" if ch.thumb else ""
                imgs += f"<img class='frame-img' {src} style='left:{x}px;top:{y}px;width:{fw}px;height:{fh}px'>"
                frames += (f"<div class='fr' data-button='f{j + 1}' data-action='{act.chapter(f.number, ch.number)}'"
                           f"{' data-default' if j == 0 else ''} data-pad='16'"
                           f" style='left:{x - 7}px;top:{y - 7}px;width:{fw + 14}px;height:{fh + 74}px'>"
                           f"<div class='fr-ring' style='width:{fw + 14}px;height:{fh + 14}px'></div>"
                           f"<div class='fr-label' style='top:{fh + 30}px'>SCENE {ch.number:02d}</div>"
                           f"<div class='fr-time' style='top:{fh + 32}px;right:0'>{ch.timecode}</div></div>")
            nav_links = link("back", 80, 40, "&#9664; BACK TO TICKET", act.menu(f"film{f.number:02d}", "scenes"))
            if p > 1:
                nav_links += link("prev", 600, 980, "&#9664; PREVIOUS REEL", act.menu(f"sc{f.number:02d}p{p - 1}", "f1"))
            if p < len(pages):
                nav_links += link("nextreel", 1050, 980, "NEXT REEL &#9654;", act.menu(f"sc{f.number:02d}p{p + 1}", "f1"))
            body = f"""
            <div class='curtain dim'></div>
            <div class='abs title-gold' style='right:96px;top:44px;font-size:44px;letter-spacing:6px'>
              REEL {p} OF {len(pages)} &nbsp;·&nbsp; {e(f.title).upper()[:34]}</div>
            <div class='strip' style='top:178px'></div>
            {"<div class='strip' style='top:578px'></div>" if len(chunk) > 4 else ""}
            {imgs}{frames}{nav_links}
            """
            ctx.html.menu(f"sc{f.number:02d}p{p}", page(body, "Scenes"))
