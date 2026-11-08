"""Tachometer: night-street racing look. A dial numbered 1..N counts the films;
each film page swings the needle to that film's number.

Settings (shown in the app's Menu view):
  title_small      "THE COMPLETE"
  title_big        "SAGA"
  accent           "#FF6B1A"
  scene_selection  true
  timeline_order   [1, 2, 4, ...]   adds a "Timeline order" button + playlist
"""
from __future__ import annotations

from boxset.core import BaseTheme, act
from boxset.draw import (Surface, draw_dial, fit_lines, font, hex_rgb, icon_chevron, icon_grid,
                          icon_ok, icon_play, icon_updown, mix)

W, H = 1920, 1080
L, R = 96, 1824
M = 14  # transparent margin around button art

THEME = {
    "bg": hex_rgb("#0A0B0D"), "panel": hex_rgb("#0F1114"), "button": hex_rgb("#121418"),
    "edge": hex_rgb("#1E2128"), "line": hex_rgb("#2A2E36"), "dark": hex_rgb("#3A3F48"),
    "dim": hex_rgb("#5C616B"), "muted": hex_rgb("#9A9EA6"), "soft": hex_rgb("#C9CCD2"),
    "text": hex_rgb("#F4F2EE"),
}
PER_PAGE = 8


def total_label(seconds):
    m = round(seconds / 60)
    return f"{m // 60} HRS {m % 60} MIN"


def clip(s, n):
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


class Theme(BaseTheme):
    name = "Tachometer"
    description = "Dark street-racing look built around a film-counter dial."
    author = "Boxset"
    version = "1.0"
    limits = {"min_films": 2, "max_films": 12}
    options = [
        {"key": "title_small", "label": "Title, first line", "type": "text", "default": "THE COMPLETE"},
        {"key": "title_big", "label": "Title, main line", "type": "text", "default": "COLLECTION"},
        {"key": "accent", "label": "Accent colour", "type": "color", "default": "#FF6B1A",
         "choices": ["#FF6B1A", "#2FB8FF", "#FFC21A", "#FF3D5A", "#3BD18A"]},
        {"key": "scene_selection", "label": "Scene selection pages", "type": "bool", "default": True},
        {"key": "timeline_order", "label": "Story order", "type": "order",
         "help": "Adds a Timeline order button that plays the films in story order."},
    ]

    # ------------------------------------------------------------- entry point
    def build(self, ctx):
        o = self.options
        self.ctx = ctx
        self.t = THEME
        self.accent = hex_rgb(o.get("accent", "#FF6B1A"))
        self.films = ctx.films
        self.n = len(self.films)
        if not 2 <= self.n <= 12:
            raise RuntimeError("The Tachometer theme handles 2 to 12 films per disc.")
        self.title_small = o.get("title_small", "THE COMPLETE")
        self.title_big = o.get("title_big", "COLLECTION")
        self.scenes = bool(o.get("scene_selection", True))
        order = o.get("timeline_order") or ctx.collection.timeline_order
        self.timeline = order if order and list(order) != list(range(1, self.n + 1)) else None
        years = [f.year for f in self.films if f.year]
        self.years = (min(years), max(years)) if years else None

        ctx.playlist("release", list(range(1, self.n + 1)))
        if self.timeline:
            ctx.playlist("timeline", self.timeline)

        ctx.log("  main menu")
        self.render_main()
        ctx.log("  film list")
        self.render_films()
        for f in self.films:
            ctx.log(f"  film {f.number:02d}: {f.title}")
            self.render_film(f)
            if self.has_scenes(f):
                self.render_chapters(f)
        for f in ctx.films:  # each film returns to its own page when it ends
            ctx.after_film(f.number, act.menu(f"film{f.number:02d}", "play"))
        ctx.start("main")

    def has_scenes(self, f):
        return self.scenes and len(f.chapters) > 1

    # ------------------------------------------------------------------ util
    def states(self):
        t, a = self.t, self.accent
        return {
            "normal": dict(fill=t["button"], edge=t["line"], fg=t["text"], sub=t["muted"], num=t["dim"], chev=False),
            "selected": dict(fill=a, edge=a, fg=t["bg"], sub=mix(t["bg"], a, 0.25), num=t["bg"], chev=True),
            "activated": dict(fill=t["text"], edge=t["text"], fg=t["bg"], sub=mix(t["bg"], t["text"], 0.3), num=t["bg"], chev=True),
        }

    def btn(self, menu, bid, x, y, w, h, draw, action, nav=None, default=False):
        imgs = {}
        for state, col in self.states().items():
            s = Surface(w + 2 * M, h + 2 * M)
            draw(s, M, M, w, h, col, state)
            imgs[state] = s.image()
        return menu.button(bid, x - M, y - M, imgs, action, nav, default=default)

    def new_bg(self):
        s = Surface(W, H, self.t["bg"])
        col = mix(self.t["bg"], self.t["text"], 0.12)
        x = 0
        while x < W:
            s.rect(x, H - 124, 96, 6, fill=col)
            x += 168
        return s

    def speed_lines(self, s, lines):
        for x1, y, x2, w, a in lines:
            s.line(x1, y, x2, y, mix(self.t["bg"], self.t["text"], a), w)

    def footer(self, s, hints, right=""):
        f = font("med", 18)
        x = L
        for icon, label in hints:
            icon(s, x + 13, H - 62, 26, self.t["text"])
            s.text(x + 38, H - 55, label, f, self.t["muted"], tracking=3)
            x += 38 + s.text_width(label, f, 3) + 40
        if right:
            s.text(R, H - 55, right, f, self.t["muted"], anchor="rs", tracking=3)

    def skew_mark(self, s, x, y, size=14):
        s.poly(s.skew_pts(x, y, size, size), fill=self.accent)

    # --------------------------------------------------------- button styles
    def big_button(self, title, sub=None, icon=None, kicker=None):
        def draw(s, ox, oy, w, h, c, state):
            s.skew_box(ox, oy, w, h, fill=c["fill"], outline=c["edge"], width=2)
            tx = ox + 28
            if icon:
                icon(s, ox + 42, oy + h / 2, 28, c["fg"])
                tx = ox + 76
            if kicker:
                s.text(tx, oy + h / 2 - 6, kicker, font("semi", 15), c["sub"], tracking=4)
                s.text(tx, oy + h / 2 + 24, title, font("xbold", 32), c["fg"], tracking=2)
            elif sub:
                s.text(tx, oy + 42, title, font("xbold", 38), c["fg"], tracking=2)
                s.text(tx, oy + h - 16, sub, font("med", 17), c["sub"], tracking=1)
            else:
                s.text(tx, oy + h / 2 + 13, title, font("xbold", 38), c["fg"], tracking=2)
            if c["chev"] or kicker:
                icon_chevron(s, ox + w - 34, oy + h / 2, 34, c["fg"])
        return draw

    def link_button(self, label, direction="left"):
        def draw(s, ox, oy, w, h, c, state):
            col = {"normal": self.t["muted"], "selected": self.accent, "activated": self.t["text"]}[state]
            f = font("semi", 20)
            if direction == "left":
                icon_chevron(s, ox + 10, oy + h / 2, 28, col, "left")
                s.text(ox + 30, oy + h / 2 + 7, label, f, col, tracking=4)
                lw = 30 + s.text_width(label, f, 4)
            else:
                s.text(ox + w, oy + h / 2 + 7, label, f, col, anchor="rs", tracking=4)
                lw = s.text_width(label, f, 4)
            if state != "normal":
                s.rect(ox if direction == "left" else ox + w - lw, oy + h - 6, lw, 4, fill=col)
        return draw

    def small_button(self, label, direction):
        def draw(s, ox, oy, w, h, c, state):
            fill = {"normal": None, "selected": self.accent, "activated": self.t["text"]}[state]
            edge = self.t["dark"] if state == "normal" else fill
            fg = self.t["text"] if state == "normal" else self.t["bg"]
            s.skew_box(ox, oy, w, h, fill=fill, outline=edge, width=2)
            f = font("xbold", 26)
            if direction == "left":
                icon_chevron(s, ox + 30, oy + h / 2, 26, fg, "left")
                s.text(ox + 52, oy + h / 2 + 9, label, f, fg, tracking=2)
            else:
                s.text(ox + w - 52, oy + h / 2 + 9, label, f, fg, anchor="rs", tracking=2)
                icon_chevron(s, ox + w - 30, oy + h / 2, 26, fg, "right")
        return draw

    # ------------------------------------------------------------------ main
    def render_main(self):
        t, a, ctx = self.t, self.accent, self.ctx
        s = self.new_bg()
        self.speed_lines(s, [(0, 742, 640, 1, .10), (120, 768, 900, 2, .06), (0, 804, 420, 1, .12),
                             (260, 188, 980, 1, .07), (0, 214, 540, 2, .05)])
        cx, cy, k = draw_dial(s, 1010, 70, 880, self.n, a, t, needle=self.n)
        s.text(cx, cy - 118 * k, str(self.n), font("black_i", 150 * k), t["text"], anchor="ms")
        s.text(cx, cy - 76 * k, "FILMS ON THIS DISC", font("semi", 20 * k), t["muted"], anchor="ms", tracking=6 * k)

        self.skew_mark(s, L, 60)
        s.text(L + 30, 74, "BLU-RAY COLLECTION", font("semi", 20), t["muted"], tracking=5)
        if self.years:
            s.text(R, 74, f"{self.years[0]} — {self.years[1]}", font("semi", 20), t["muted"], anchor="rs", tracking=5)

        s.text(L, 222, self.title_small, font("xbold_i", 64), a, tracking=2)
        size = 260
        while size > 120 and s.text_width(self.title_big, font("black_i", size), -4 * size / 260) > 880:
            size -= 10
        s.text(L - 10, 230 + size * 0.80, self.title_big, font("black_i", size), t["text"], tracking=-4 * size / 260)

        f = font("med", 22)
        x = L
        for i, p in enumerate([f"{self.n} FILMS", total_label(ctx.total_seconds), "1 DISC"]):
            if i:
                s.text(x, 500, "/", f, t["dark"])
                x += s.text_width("/", f) + 28
            s.text(x, 500, p, f, t["muted"], tracking=3)
            x += s.text_width(p, f, 3) + 28
        self.footer(s, [(icon_updown, "NAVIGATE"), (icon_ok, "SELECT")], "DISC 1 OF 1")

        m = ctx.menu("main", s.image())
        items = [("play", "PLAY THE SAGA" if self.n > 3 else "PLAY ALL",
                  f"All {self.n} films back to back, in release order", act.playlist("release")),
                 ("select", "SELECT A FILM", f"Pick any of the {self.n}, then play or jump to a scene",
                  act.menu("films", "row01"))]
        if self.timeline:
            items.append(("timeline", "TIMELINE ORDER", self._timeline_hint(), act.playlist("timeline")))
        for i, (bid, title, sub, action) in enumerate(items):
            self.btn(m, bid, L, 560 + i * 98, 620, 84, self.big_button(title, sub), action)
        m.chain([b[0] for b in items])
        m.default = "play"

    def _timeline_hint(self):
        order = self.timeline
        f = max(self.films, key=lambda f: abs(order.index(f.number) - (f.number - 1)))
        pos = order.index(f.number) + 1
        suffix = "th" if 11 <= pos % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(pos % 10, "th")
        return f"Story chronology: {f.title.split(':')[-1].strip()} plays {pos}{suffix}"

    # ----------------------------------------------------------------- films
    def render_films(self):
        t, a, ctx = self.t, self.accent, self.ctx
        s = self.new_bg()
        f = font("black_i", 64)
        s.text(L, 108, "SELECT A FILM", f, t["text"], tracking=1)
        s.text(L + s.text_width("SELECT A FILM", f, 1) + 24, 108, "RELEASE ORDER", font("semi", 20), t["muted"], tracking=5)
        cx, cy, k = draw_dial(s, 1190, 150, 560, self.n, a, t, needle=None, label_dim=t["dim"])
        stats = [(str(self.n), "FILMS"), (f"{round(ctx.total_seconds / 3600)}", "HOURS")]
        if self.years:
            stats.append((f"{self.years[0]}–{str(self.years[1])[2:]}", "YEARS"))
        sx = cx - (len(stats) - 1) * 110
        for i, (v, lbl) in enumerate(stats):
            x = sx + i * 220
            s.text(x, 820, v, font("xbold_i", 64), t["text"], anchor="ms")
            s.text(x, 852, lbl, font("semi", 16), t["muted"], anchor="ms", tracking=4)
        self.footer(s, [(icon_updown, "CHOOSE FILM"), (icon_ok, "OPEN")], f"{total_label(ctx.total_seconds)} TOTAL")

        m = ctx.menu("films", s.image())
        pitch = min(66, 760 // self.n)
        rows = []
        for film in self.films:
            bid = f"row{film.number:02d}"
            rows.append(bid)
            self.btn(m, bid, L, 150 + (film.number - 1) * pitch, 820, pitch - 4,
                     self._row_draw(film), act.menu(f"film{film.number:02d}", "play"))
        self.btn(m, "back", R - 230, 52, 230, 52, self.link_button("MAIN MENU", "right"), act.menu("main", "select"))
        m.chain(rows)
        m.get(rows[0]).nav["up"] = "back"
        m.get(rows[-1]).nav["down"] = "back"
        for r in rows:
            m.get(r).nav["right"] = "back"
        m.get("back").nav.update({"down": rows[0], "up": rows[-1], "left": rows[0]})
        m.default = rows[0]

    def _row_draw(self, film):
        t = self.t

        def draw(s, ox, oy, w, h, c, state):
            on = state != "normal"
            if on:
                s.skew_box(ox, oy, w, h, fill=c["fill"])
            fg = c["fg"] if on else t["text"]
            sub = c["sub"] if on else t["muted"]
            s.text(ox + 24, oy + h / 2 + 14, f"{film.number:02d}", font("black_i", 40), c["num"] if on else t["dim"])
            year_w = 0
            if film.year:
                s.text(ox + w - 24, oy + h / 2 + 7, str(film.year), font("semi", 20), sub, anchor="rs", tracking=2)
                year_w = 90
            tx = ox + 110
            tf = font("bold", 30 if on else 32)
            title = film.title
            avail = ox + w - 24 - year_w - tx - (110 if film.spinoff else 0)
            while s.text_width(title, tf, 1) > avail and len(title) > 4:
                title = title.rstrip("…")[:-1].rstrip() + "…"
            if on:
                s.text(tx, oy + 32, title, tf, fg, tracking=1)
                details = " · ".join(x for x in [film.runtime, film.place.upper()] if x)
                s.text(tx, oy + h - 9, details, font("semi", 14), sub, tracking=2)
            else:
                s.text(tx, oy + h / 2 + 11, title, tf, fg, tracking=1)
            if film.spinoff:
                bx = tx + s.text_width(title, tf, 1) + 18
                by = oy + (14 if on else h / 2 - 13)
                tag = font("semi", 14)
                bw = s.text_width("SPIN-OFF", tag, 3) + 20
                s.rect(bx, by, bw, 26, outline=fg if on else sub, width=1.5)
                s.text(bx + 10, by + 18, "SPIN-OFF", tag, fg if on else sub, tracking=3)
        return draw

    # ------------------------------------------------------------ film pages
    def render_film(self, film):
        t, a, ctx = self.t, self.accent, self.ctx
        mid = f"film{film.number:02d}"
        s = self.new_bg()
        self.speed_lines(s, [(0, 300, 760, 1, .08), (80, 326, 1100, 2, .05), (0, 640, 520, 1, .10)])
        s.text(R, 82, f"FILM {film.number:02d} OF {self.n:02d}", font("semi", 20), t["muted"], anchor="rs", tracking=5)
        cx, cy, k = draw_dial(s, 1190, 130, 620, self.n, a, t, needle=film.number,
                              highlight=film.number, label_dim=t["dim"])
        s.text(cx, cy + 205 * k, f"{film.number:02d}", font("black_i", 150 * k), a, anchor="ms")
        s.text(cx, cy + 250 * k, f"OF {self.n}", font("semi", 20 * k), t["muted"], anchor="ms", tracking=6 * k)

        self.skew_mark(s, L, 168)
        kick = str(film.year or "")
        if film.spinoff:
            kick = (kick + "  ·  SPIN-OFF").strip(" ·")
        s.text(L + 30, 182, kick, font("semi", 22), a, tracking=5)

        title = film.title.upper()
        lines, size, base, meta_y = [title], 72, 260, 400
        for size in [236, 210, 190, 170, 150, 132, 116, 104, 96, 88, 80, 72]:
            _, lines = fit_lines(title, "black_i", 1060, 3, [size], tracking=-4 * size / 236)
            if any(s.text_width(l, font("black_i", size), -4 * size / 236) > 1060 for l in lines):
                continue
            base = 202 + 0.72 * size
            meta_y = base + (len(lines) - 1) * size * 0.86 + 60
            if meta_y <= 492:
                break
        for i, line in enumerate(lines):
            s.text(L - 8, base + i * size * 0.86, line, font("black_i", size), t["text"], tracking=-4 * size / 236)

        f = font("med", 22)
        x = L
        for i, part in enumerate([p for p in [film.runtime, film.place] if p]):
            if i:
                s.rect(x, meta_y - 22, 1, 30, fill=t["dark"])
                x += 22
            s.text(x, meta_y, part, f, t["soft"], tracking=2)
            x += s.text_width(part, f, 2) + 22

        s.text(L, 846, "WHERE THIS SITS IN THE SAGA", font("semi", 16), t["muted"], tracking=5)
        gap = 10
        cw = (R - L - gap * (self.n - 1)) / self.n
        nf = font("xbold_i", 26)
        for f2 in self.films:
            x = L + (f2.number - 1) * (cw + gap)
            cur, past = f2.number == film.number, f2.number < film.number
            s.poly(s.skew_pts(x + 3, 862, cw - 6, 10), fill=a if cur else (t["dim"] if past else hex_rgb("#23262D")))
            s.text(x, 908, f"{f2.number:02d}", nf, a if cur else (t["soft"] if past else t["dim"]))
            if f2.year:
                s.text(x + s.text_width(f"{f2.number:02d}", nf) + 10, 906, str(f2.year), font("semi", 15),
                       t["text"] if cur else t["muted"], tracking=1)
        self.footer(s, [(icon_updown, "NAVIGATE"), (icon_ok, "SELECT")], f"{self.title_small} {self.title_big}")

        m = ctx.menu(mid, s.image())
        col = [("play", "PLAY FILM", icon_play, None, act.title(film.number))]
        if self.has_scenes(film):
            col.append(("scenes", "SCENE SELECTION", icon_grid, None, act.menu(f"ch{film.number:02d}p1", "c01")))
        if film.number < self.n:
            nxt = self.films[film.number]
            col.append(("next", clip(nxt.title.upper(), 22), None, "NEXT FILM", act.menu(f"film{nxt.number:02d}", "next")))
        else:
            col.append(("next", "MAIN MENU", None, "BACK TO", act.menu("main", "play")))
        for i, (bid, title, icon, kicker, action) in enumerate(col):
            self.btn(m, bid, L, 520 + i * 88, 640, 76, self.big_button(title, None, icon, kicker), action)
        self.btn(m, "back", L, 52, 210, 52, self.link_button("ALL FILMS", "left"),
                 act.menu("films", f"row{film.number:02d}"))
        ids = [c[0] for c in col]
        m.chain(ids)
        m.get(ids[0]).nav["up"] = "back"
        m.get("back").nav.update({"down": ids[0], "up": ids[-1]})
        m.default = "play"

    # -------------------------------------------------------- scene pages
    def render_chapters(self, film):
        t, a, ctx = self.t, self.accent, self.ctx
        pages = ctx.pages(film.chapters, PER_PAGE)
        for p, chunk in enumerate(pages, 1):
            mid = f"ch{film.number:02d}p{p}"
            s = self.new_bg()
            hf = font("black_i", 64)
            s.text(L, 108, "SCENE SELECTION", hf, t["text"], tracking=1)
            s.text(L + s.text_width("SCENE SELECTION", hf, 1) + 24, 108,
                   f"{film.number:02d} · {clip(film.title.upper(), 40)}", font("semi", 20), a, tracking=5)
            for j, ch in enumerate(chunk):
                self._paste_thumb(s, ch.thumb, L + (j % 4) * 440, 176 + (j // 4) * 322, 408, 230)
            if len(pages) > 1:
                dots_w = len(pages) * 58 - 14
                for q in range(1, len(pages) + 1):
                    s.poly(s.skew_pts(960 - dots_w / 2 + (q - 1) * 58, 844, 44, 8), fill=a if q == p else t["line"])
                s.text(960, 884, f"{p} / {len(pages)}", font("semi", 18), t["muted"], anchor="ms", tracking=4)
            self.footer(s, [(icon_updown, "NAVIGATE"), (icon_ok, "PLAY FROM SCENE")],
                        f"CHAPTERS {chunk[0].number:02d}–{chunk[-1].number:02d} OF {len(film.chapters):02d}")

            m = ctx.menu(mid, s.image())
            for j, ch in enumerate(chunk):
                self.btn(m, f"c{j + 1:02d}", L + (j % 4) * 440, 176 + (j // 4) * 322, 408, 278,
                         self._chapter_draw(ch), act.chapter(film.number, ch.number))
            if p > 1:
                self.btn(m, "prev", 560, 820, 200, 56, self.small_button("PREV", "left"),
                         act.menu(f"ch{film.number:02d}p{p - 1}", "c01"))
            if p < len(pages):
                self.btn(m, "nextpage", 1160, 820, 200, 56, self.small_button("NEXT", "right"),
                         act.menu(f"ch{film.number:02d}p{p + 1}", "c01"))
            self.btn(m, "back", R - 260, 52, 260, 52, self.link_button("BACK TO FILM", "right"),
                     act.menu(f"film{film.number:02d}", "scenes"))
            m.default = "c01"

    def _paste_thumb(self, s, path, x, y, w, h):
        from PIL import Image
        import os
        if path and os.path.exists(path):
            im = Image.open(path).convert("RGB")
            scale = max(w / im.width, h / im.height)
            nw, nh = round(im.width * scale), round(im.height * scale)
            im = im.resize((nw, nh), Image.LANCZOS)
            im = im.crop(((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h))
            s.paste(im, x, y)
        else:
            s.rect(x, y, w, h, fill=self.t["button"])
            s.text(x + w / 2, y + h / 2 + 6, "NO PREVIEW", font("semi", 15), self.t["dim"], anchor="ms", tracking=4)

    def _chapter_draw(self, ch):
        t, a = self.t, self.accent

        def draw(s, ox, oy, w, h, c, state):
            th = 230
            if state == "normal":
                s.rect(ox - 1, oy - 1, w + 2, th + 2, outline=hex_rgb("#23262D"), width=2)
                badge_bg, badge_fg, lab = t["bg"], t["soft"], t["text"]
            else:
                ring = a if state == "selected" else t["text"]
                s.rect(ox - 6, oy - 6, w + 12, th + 12, outline=ring, width=6)
                badge_bg, badge_fg, lab = ring, t["bg"], ring
            bf = font("black_i", 30)
            bw = s.text_width(f"{ch.number:02d}", bf) + 28
            s.rect(ox, oy, bw, 42, fill=badge_bg)
            s.text(ox + 14, oy + 32, f"{ch.number:02d}", bf, badge_fg)
            s.text(ox, oy + th + 44, f"CHAPTER {ch.number:02d}", font("bold", 28), lab, tracking=2)
            s.text(ox + w, oy + th + 44, ch.timecode, font("med", 18), t["muted"], anchor="rs", tracking=2)
        return draw
