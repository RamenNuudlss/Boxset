"""The theme API.

A theme is a folder containing theme.py with a `Theme` class:

    from boxset.core import BaseTheme, act

    class Theme(BaseTheme):
        name = "My theme"

        def build(self, ctx):
            m = ctx.menu("main", background=some_image)      # PIL image, file, or video
            m.button("play", x, y, images, act.playall())     # images: normal/selected/activated
            ctx.start("main")

The theme decides every screen, every button and how menus link together.
The core supplies the data (films, chapters, thumbnails, any extra fields you
set on a film), rendering helpers, and then checks the result
against what a Blu-ray player can actually do before building the disc.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from dataclasses import dataclass, field

from PIL import Image

from .probe import timecode

FRAME_W, FRAME_H = 1920, 1080
MAX_BUTTONS_PER_MENU = 255
STATES = ("normal", "selected", "activated")


# ----------------------------------------------------------------- data for themes

@dataclass
class Chapter:
    number: int          # 1-based
    start: float         # seconds
    timecode: str        # "0:12:34"
    thumb: str | None    # path to a frame grab, if one was made


@dataclass
class FilmInfo:
    number: int
    title: str
    year: int | None
    place: str
    spinoff: bool
    file: str
    duration: float
    chapters: list[Chapter]
    extra: dict          # every other field set on this film

    @property
    def runtime(self) -> str:
        m = round(self.duration / 60)
        return f"{m // 60} HR {m % 60} MIN"

    @property
    def minutes(self) -> int:
        return round(self.duration / 60)


class act:
    """Button actions. Every button runs exactly one."""

    @staticmethod
    def title(n: int) -> str:
        return f"title:{n}"

    @staticmethod
    def chapter(n: int, c: int) -> str:
        return f"chapter:{n}:{c}"

    @staticmethod
    def menu(menu_id: str, button: str | None = None) -> str:
        return f"menu:{menu_id}" + (f":{button}" if button else "")

    @staticmethod
    def playall() -> str:
        return "playall"

    @staticmethod
    def playlist(pid: str) -> str:
        return f"playlist:{pid}"

    @staticmethod
    def back() -> str:
        return "lastmenu"

    @staticmethod
    def close() -> str:
        """In a film's pop-up: close it and carry on watching."""
        return "close"


# ----------------------------------------------------------------- menu building

@dataclass
class Button:
    id: str
    x: int
    y: int
    images: dict          # state -> PIL.Image (RGBA)
    action: str
    nav: dict = field(default_factory=dict)
    auto: bool = False    # runs its action as soon as it's selected (no OK needed)

    @property
    def w(self):
        return self.images["normal"].width

    @property
    def h(self):
        return self.images["normal"].height


class Menu:
    def __init__(self, ctx, menu_id, background, music=None, loop_seconds=None):
        self.ctx = ctx
        self.id = menu_id
        self.background = background   # PIL.Image or path to image/video
        self.music = music
        self.loop_seconds = loop_seconds
        self.buttons: list[Button] = []
        self.default: str | None = None

    def button(self, bid, x, y, images: dict, action: str, nav: dict | None = None, default=False, auto=False):
        """Add a button. images needs 'normal' and 'selected'; 'activated' falls back to selected.
        All states are padded to one shared size so they line up exactly. An `auto` button
        runs its action the moment it's selected, e.g. to flip to another page."""
        imgs = {}
        for st in STATES:
            im = images.get(st) or images.get("selected")
            if im is None:
                raise ValueError(f"Button {self.id}/{bid} needs at least normal and selected images")
            imgs[st] = im.convert("RGBA") if not isinstance(im, str) else Image.open(im).convert("RGBA")
        w = max(i.width for i in imgs.values())
        h = max(i.height for i in imgs.values())
        for st, im in imgs.items():
            if im.size != (w, h):
                canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                canvas.alpha_composite(im)
                imgs[st] = canvas
        # drop near-invisible halo pixels (resampling ringing) so they can't cause overlaps
        for st, im in imgs.items():
            a = im.getchannel("A").point(lambda v: 0 if v < 12 else v)
            im.putalpha(a)
        # trim transparent margins: the button's on-disc rectangle is exactly what it paints
        boxes = [im.getchannel("A").getbbox() for im in imgs.values()]
        boxes = [bx for bx in boxes if bx]
        if boxes:
            l, t = min(bx[0] for bx in boxes), min(bx[1] for bx in boxes)
            r, btm = max(bx[2] for bx in boxes), max(bx[3] for bx in boxes)
            imgs = {st: im.crop((l, t, r, btm)) for st, im in imgs.items()}
            x, y = x + l, y + t
        b = Button(bid, round(x), round(y), imgs, action, dict(nav or {}), bool(auto))
        self.buttons.append(b)
        if default or (self.default is None and not auto):
            self.default = bid
        return b

    def get(self, bid) -> Button:
        return next(b for b in self.buttons if b.id == bid)

    def chain(self, ids, wrap=True, axis="vertical"):
        """Link buttons for d-pad movement in the given order."""
        a, b = ("up", "down") if axis == "vertical" else ("left", "right")
        for i, bid in enumerate(ids):
            btn = self.get(bid)
            if i > 0 or wrap:
                btn.nav.setdefault(a, ids[i - 1])
            if i < len(ids) - 1 or wrap:
                btn.nav.setdefault(b, ids[(i + 1) % len(ids)])


class Context:
    def __init__(self, coll, films: list[FilmInfo], theme_dir: str, out_dir: str, options: dict, log=print,
                 check=None):
        self.collection = coll
        self.check = check or (lambda: None)     # raises when the user stops the job
        self.films = films
        self.theme_dir = theme_dir
        self.out = out_dir
        self.options = options
        self.log = log
        self.menus: dict[str, Menu] = {}
        self.popups: dict = {}                   # film number -> popup.Popup
        self.hdr: dict = {}                      # film number -> "hdr10" / "hlg" for HDR films
        self.playlists: dict[str, list[int]] = {}
        self.first: str | None = None
        self.title_ends: dict[int, str] = {}
        self.playlist_ends: dict[str, str] = {}
        self._html = None

    # -- data helpers -----------------------------------------------------------
    @property
    def total_seconds(self) -> float:
        return sum(f.duration for f in self.films)

    def film(self, n: int) -> FilmInfo:
        return self.films[n - 1]

    def frame(self, film_number: int, seconds: float, width: int = 1920) -> str | None:
        """A picture from film `film_number` at `seconds`, as a JPEG `width` wide
        (for backdrops; chapter thumbnails are in film.chapters). HDR films are
        converted like everything else. None if the frame couldn't be read."""
        import subprocess
        from .probe import need
        film = self.film(film_number)
        seconds = max(0.0, min(float(seconds), max(0.0, film.duration - 1)))
        folder = os.path.join(self.out, "frames")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"film{film_number:02d}_{round(seconds * 10):07d}_{width}.jpg")
        if not os.path.exists(path):
            vf = f"scale={width}:-2:flags=lanczos"
            if self.hdr.get(film_number) in ("hdr10", "hlg"):
                from . import tracks
                if tracks.tonemap_available():
                    vf += "," + tracks.tonemap_filter(self.hdr[film_number])
            subprocess.run([need("ffmpeg"), "-v", "error", "-y", "-ss", f"{seconds:.3f}", "-i", film.file,
                            "-frames:v", "1", "-vf", vf, "-q:v", "2", path], check=False, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return path if os.path.exists(path) else None

    def asset(self, *parts) -> str:
        """Path to a file inside the theme folder."""
        return os.path.join(self.theme_dir, *parts)

    def user_file(self, p: str) -> str:
        """Path to a file chosen in the settings (relative to the project file)."""
        return self.collection.resolve(p)

    @staticmethod
    def uri(path: str) -> str:
        """file:// URL for use inside HTML screens (thumbnails, posters, your own images)."""
        import pathlib
        return pathlib.Path(os.path.abspath(path)).as_uri()

    @staticmethod
    def esc(s) -> str:
        """Escape text for HTML."""
        import html as _h
        return _h.escape(str(s if s is not None else ""))

    def story_order(self, order) -> list[int] | None:
        """An 'order' setting as a list of film numbers, or None when it's unset, just
        release order, or out of date (films were added or removed since it was set)."""
        n = len(self.films)
        if not isinstance(order, (list, tuple)) or sorted(order) != list(range(1, n + 1)):
            return None
        order = [int(x) for x in order]
        return None if order == list(range(1, n + 1)) else order

    @staticmethod
    def pages(items, per_page):
        return [items[i:i + per_page] for i in range(0, len(items), per_page)]

    # -- building -----------------------------------------------------------------
    def menu(self, menu_id: str, background, music=None, loop_seconds=None) -> Menu:
        if menu_id in self.menus:
            raise ValueError(f"Menu id '{menu_id}' used twice")
        m = Menu(self, menu_id, background, music, loop_seconds)
        self.menus[menu_id] = m
        if self.first is None:
            self.first = menu_id
        return m

    def popup(self, film_number: int):
        """Film `film_number`'s pop-up: what the remote's Pop-up Menu button shows
        over the film while it plays (see boxset/popup.py)."""
        from .popup import Popup
        if film_number not in self.popups:
            self.popups[film_number] = Popup(self.film(film_number))
        return self.popups[film_number]

    def playlist(self, pid: str, film_numbers: list[int]):
        self.playlists[pid] = list(film_numbers)

    def start(self, menu_id: str):
        """Menu shown when the disc is inserted (and on Top Menu)."""
        self.first = menu_id

    def after_film(self, n: int, action: str):
        """Where the player goes when film n finishes (default: the start menu)."""
        self.title_ends[n] = action

    def after_playlist(self, pid: str, action: str):
        """Where the player goes when a playlist finishes (default: the start menu)."""
        self.playlist_ends[pid] = action

    @property
    def html(self):
        """HTML/CSS renderer (headless browser), started on first use."""
        if self._html is None:
            from .html import HtmlRenderer
            self._html = HtmlRenderer(self)
        return self._html

    def close(self):
        if self._html is not None:
            self._html.close()


class BaseTheme:
    """Subclass this in theme.py.

    `options` declares the settings the app shows for this theme, e.g.
        options = [
            {"key": "title_big", "label": "Title", "type": "text", "default": "SAGA"},
            {"key": "accent", "label": "Accent colour", "type": "color", "default": "#FF6B1A"},
            {"key": "scene_selection", "label": "Scene selection", "type": "bool", "default": True},
            {"key": "style", "label": "Style", "type": "choice", "choices": ["Day", "Night"], "default": "Night"},
            {"key": "timeline_order", "label": "Story order", "type": "order"},
            {"key": "main_music", "label": "Main menu music", "type": "file", "filter": "audio"},
        ]
    `film_fields` declares extra per-film fields the theme uses (shown in the film editor):
        film_fields = [{"key": "tagline", "label": "Tagline", "type": "text"}]
    """
    name = "Untitled theme"
    description = ""
    author = ""
    version = "1.0"
    options: list = []
    film_fields: list = []
    limits = {"min_films": 1, "max_films": 99}

    def __init__(self, options: dict):
        merged = {o["key"]: o.get("default") for o in self.options if "key" in o}
        merged.update({k: v for k, v in (options or {}).items() if v is not None})
        self.options = merged

    @classmethod
    def info(cls) -> dict:
        return {"name": cls.name, "description": cls.description, "author": cls.author,
                "version": cls.version, "options": cls.options, "film_fields": cls.film_fields,
                "limits": cls.limits}

    def build(self, ctx: Context):  # pragma: no cover - themes override
        raise NotImplementedError


# ----------------------------------------------------------------- loading themes

def user_theme_dir() -> str:
    """Where installed theme packs live (per user)."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "Boxset", "themes")
    os.makedirs(d, exist_ok=True)
    return d


# Themes are code, so a project's own "themes" folder is only loaded from folders the
# user has allowed: opening a project someone sent you must not run what came with it.
# None means no restriction, which is what the command line uses (running it on a
# project is itself the go-ahead). The app narrows this to the folders in its settings.
_TRUSTED_PROJECT_DIRS: set[str] | None = None


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def restrict_project_themes(trusted_folders) -> None:
    """Only load project themes from these project folders (None lifts the limit)."""
    global _TRUSTED_PROJECT_DIRS
    _TRUSTED_PROJECT_DIRS = None if trusted_folders is None else {_norm(d) for d in trusted_folders}


def project_themes_trusted(coll) -> bool:
    return _TRUSTED_PROJECT_DIRS is None or _norm(coll.base_dir) in _TRUSTED_PROJECT_DIRS


def untrusted_project_themes(coll) -> list[str]:
    """Themes in the project's own folder that are waiting for the user's go-ahead.
    Found by name only: nothing in them is loaded."""
    if coll is None or project_themes_trusted(coll):
        return []
    root = os.path.join(coll.base_dir, "themes")
    if not os.path.isdir(root):
        return []
    return [n for n in sorted(os.listdir(root)) if os.path.exists(os.path.join(root, n, "theme.py"))]


def theme_dirs(coll=None) -> list[str]:
    dirs = []
    if coll is not None and project_themes_trusted(coll):
        dirs.append(os.path.join(coll.base_dir, "themes"))
    dirs += [user_theme_dir(), os.path.join(os.path.dirname(__file__), "themes")]
    return dirs


def install_theme(src: str) -> str:
    """Install a theme pack (a folder or a .zip / .boxtheme containing theme.py).
    Returns the installed theme's id. Themes are code: only install packs you trust."""
    import tempfile
    import zipfile
    work = None
    if os.path.isfile(src):
        work = tempfile.mkdtemp(prefix="boxset-theme-")
        with zipfile.ZipFile(src) as z:
            for n in z.namelist():
                target = os.path.abspath(os.path.join(work, n))
                if not target.startswith(os.path.abspath(work) + os.sep):
                    raise RuntimeError("That theme pack contains unsafe file paths.")
            z.extractall(work)
        src = work
    found = [root for root, _, files in os.walk(src) if "theme.py" in files]
    if not found:
        raise RuntimeError("No theme.py found in that theme pack.")
    root = min(found, key=len)
    tid = "".join(c if c.isalnum() or c in "-_" else "-" for c in os.path.basename(root.rstrip("/\\")).lower()) or "theme"
    if root == src and work:
        tid = "".join(c if c.isalnum() or c in "-_" else "-" for c in os.path.splitext(os.path.basename(src))[0].lower())
    dest = os.path.join(user_theme_dir(), tid)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(root, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if work:
        shutil.rmtree(work, ignore_errors=True)
    return tid


def list_themes(coll=None) -> dict[str, str]:
    found = {}
    for root in theme_dirs(coll):
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                if name not in found and os.path.exists(os.path.join(root, name, "theme.py")):
                    found[name] = os.path.join(root, name)
    return found


def load_theme(coll, name: str, options: dict):
    themes = list_themes(coll)
    if name in themes:
        cls = _theme_class(name, themes[name])
        return cls(options), themes[name]
    if name in untrusted_project_themes(coll):
        raise RuntimeError(f"The theme '{name}' is in this project's themes folder, which hasn't been allowed "
                           "to run yet. Allow it on the Menu page, or pick another theme.")
    raise RuntimeError(f"No theme called '{name}'. Available: {', '.join(themes) or 'none'}")


_THEME_CACHE: dict = {}


def _theme_class(name, d):
    key = (d, os.path.getmtime(os.path.join(d, "theme.py")))
    if key not in _THEME_CACHE:
        spec = importlib.util.spec_from_file_location(f"boxset_theme_{name}", os.path.join(d, "theme.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "Theme"):
            raise RuntimeError(f"Theme '{name}' has no Theme class in theme.py")
        _THEME_CACHE[key] = mod.Theme
    return _THEME_CACHE[key]


def theme_catalog(coll=None) -> list[dict]:
    """Every available theme with its settings schema and preview image path."""
    out = []
    for tid, d in list_themes(coll).items():
        try:
            info = _theme_class(tid, d).info()
        except Exception as e:  # a broken theme pack shouldn't break the app
            info = {"name": tid, "description": f"Couldn't load: {e}", "options": [], "film_fields": [],
                    "broken": True}
        prev = next((os.path.join(d, n) for n in ("preview.jpg", "preview.png") if os.path.exists(os.path.join(d, n))), None)
        parent = os.path.normcase(os.path.abspath(os.path.dirname(d)))
        builtin = parent == os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(__file__), "themes")))
        installed = parent == os.path.normcase(os.path.abspath(user_theme_dir()))
        out.append({"id": tid, "dir": d, "preview": prev, "builtin": builtin,
                    "source": "builtin" if builtin else "installed" if installed else "project", **info})
    return out


def remove_theme(tid: str) -> None:
    """Delete an installed theme pack. Built-in themes and themes in a project's
    own folder are never touched."""
    root = os.path.abspath(user_theme_dir())
    d = os.path.abspath(os.path.join(root, tid))
    if os.path.dirname(d) != root or not os.path.exists(os.path.join(d, "theme.py")):
        raise RuntimeError("Only installed theme packs can be removed.")
    shutil.rmtree(d)


# ----------------------------------------------------------------- checking

def validate(ctx: Context) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    n = len(ctx.films)
    if not ctx.menus:
        errors.append("The theme made no menus.")
        return errors, warnings
    if ctx.first not in ctx.menus:
        errors.append(f"Start menu '{ctx.first}' doesn't exist.")

    reachable_films = set()
    for pid, films in ctx.playlists.items():
        bad = [f for f in films if not 1 <= f <= n]
        if bad:
            errors.append(f"Playlist '{pid}' lists films that don't exist: {bad}")

    for m in ctx.menus.values():
        where = f"menu '{m.id}'"
        if isinstance(m.background, str) and not os.path.exists(m.background):
            errors.append(f"{where}: background file not found: {m.background}")
        if m.music and not os.path.exists(m.music):
            errors.append(f"{where}: music file not found: {m.music}")
        if not m.buttons:
            warnings.append(f"{where} has no buttons")
            continue
        if len(m.buttons) > MAX_BUTTONS_PER_MENU:
            errors.append(f"{where} has {len(m.buttons)} buttons; the limit is {MAX_BUTTONS_PER_MENU}")
        ids = [b.id for b in m.buttons]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errors.append(f"{where}: duplicate button ids {sorted(dup)}")
        if m.default not in ids:
            errors.append(f"{where}: default button '{m.default}' doesn't exist")
        elif next(b for b in m.buttons if b.id == m.default).auto:
            errors.append(f"{where}: the default button '{m.default}' acts on its own as soon as it's selected, "
                          f"so the menu would leave the moment it opens")
        for b in m.buttons:
            bw = f"{where}, button '{b.id}'"
            if b.x < 0 or b.y < 0 or b.x + b.w > FRAME_W or b.y + b.h > FRAME_H:
                errors.append(f"{bw} runs off the 1920x1080 screen ({b.x},{b.y} {b.w}x{b.h})")
            for d, target in b.nav.items():
                if d not in ("up", "down", "left", "right"):
                    errors.append(f"{bw}: unknown direction '{d}'")
                elif target not in ids:
                    errors.append(f"{bw}: {d} goes to '{target}', which isn't on this menu")
            err = _check_action(ctx, b.action, n)
            if err:
                errors.append(f"{bw}: {err}")
            kind = b.action.split(":")[0]
            if kind in ("title", "chapter"):
                reachable_films.add(int(b.action.split(":")[1]))
            elif kind == "playlist" and b.action[9:] in ctx.playlists:
                reachable_films.update(ctx.playlists[b.action[9:]])
            elif kind == "playall":
                reachable_films.update(range(1, n + 1))
        # overlapping buttons are not allowed on a Blu-ray menu
        rects = [(b.id, _visible_box(b)) for b in m.buttons]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i][1], rects[j][1]
                if a and b and a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    errors.append(f"{where}: buttons '{rects[i][0]}' and '{rects[j][0]}' overlap")
    for k, a in list(ctx.title_ends.items()) + list(ctx.playlist_ends.items()):
        err = _check_action(ctx, a, n)
        if err:
            errors.append(f"end of {'film' if isinstance(k, int) else 'playlist'} {k}: {err}")
    if ctx.popups:
        from . import popup
        errors += popup.validate(ctx, lambda a: _check_action(ctx, a, n))
    missing = sorted(set(range(1, n + 1)) - reachable_films)
    if missing:
        warnings.append(f"No button plays film(s) {missing}")
    return errors, warnings


def _visible_box(b: Button):
    """Union of the non-transparent area across all states, in screen coordinates."""
    boxes = [im.getchannel("A").getbbox() for im in b.images.values()]
    boxes = [x for x in boxes if x]
    if not boxes:
        return None
    l, t = min(x[0] for x in boxes), min(x[1] for x in boxes)
    r, btm = max(x[2] for x in boxes), max(x[3] for x in boxes)
    return (b.x + l, b.y + t, b.x + r, b.y + btm)


def _check_action(ctx, action: str, n: int) -> str | None:
    parts = action.split(":")
    kind = parts[0]
    try:
        if kind == "title":
            if not 1 <= int(parts[1]) <= n:
                return f"plays film {parts[1]}, which doesn't exist"
        elif kind == "chapter":
            f, c = int(parts[1]), int(parts[2])
            if not 1 <= f <= n:
                return f"plays film {f}, which doesn't exist"
            if not 1 <= c <= len(ctx.film(f).chapters):
                return f"jumps to chapter {c} of film {f}, which has {len(ctx.film(f).chapters)}"
        elif kind == "menu":
            mid = parts[1]
            btn = parts[2] if len(parts) > 2 else None
            if mid not in ctx.menus:
                return f"opens menu '{mid}', which doesn't exist"
            if btn and btn not in [b.id for b in ctx.menus[mid].buttons]:
                return f"opens menu '{mid}' on button '{btn}', which isn't there"
        elif kind == "playlist":
            if parts[1] not in ctx.playlists:
                return f"plays playlist '{parts[1]}', which the theme never defined"
        elif kind not in ("playall", "lastmenu"):
            return f"unknown action '{action}'"
    except (IndexError, ValueError):
        return f"malformed action '{action}'"
    return None


# ----------------------------------------------------------------- output

def palettize(images: list[Image.Image], colors: int = 255) -> list[Image.Image]:
    """Reduce a menu's button art to one shared palette (Blu-ray button graphics are
    256-colour indexed; one entry is kept for full transparency)."""
    if not images:
        return images
    w = max(i.width for i in images)
    atlas = Image.new("RGBA", (w, sum(i.height for i in images)), (0, 0, 0, 0))
    y = 0
    for im in images:
        atlas.alpha_composite(im, (0, y))
        y += im.height
    q = atlas.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).convert("RGBA")
    out, y = [], 0
    for im in images:
        out.append(q.crop((0, y, im.width, y + im.height)))
        y += im.height
    return out


def write_manifest(ctx: Context) -> dict:
    root = os.path.join(ctx.out, "menus")
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(root)
    rel = lambda p: os.path.relpath(p, ctx.out).replace(os.sep, "/")
    menus = []
    for m in ctx.menus.values():
        d = os.path.join(root, m.id)
        os.makedirs(d)
        if isinstance(m.background, Image.Image):
            bg = os.path.join(d, "background.png")
            m.background.convert("RGB").resize((FRAME_W, FRAME_H)).save(bg, optimize=True)
        else:
            ext = os.path.splitext(m.background)[1].lower()
            bg = os.path.join(d, "background" + ext)
            shutil.copyfile(m.background, bg)
        music = None
        if m.music:
            music = os.path.join(d, "music" + os.path.splitext(m.music)[1].lower())
            shutil.copyfile(m.music, music)
        flat = [b.images[st] for b in m.buttons for st in STATES]
        flat = palettize(flat)
        buttons = []
        for i, b in enumerate(m.buttons):
            files = {}
            for k, st in enumerate(STATES):
                p = os.path.join(d, f"{b.id}_{st}.png")
                flat[i * 3 + k].save(p, optimize=True)
                files[st] = rel(p)
            buttons.append({"id": b.id, "x": b.x, "y": b.y, "w": b.w, "h": b.h, **files,
                            "action": b.action, "nav": b.nav, "auto": b.auto})
        menus.append({"id": m.id, "background": rel(bg), "music": rel(music) if music else None,
                      "loop_seconds": m.loop_seconds, "default_button": m.default, "buttons": buttons})
    popups = {}
    if ctx.popups:
        from . import popup
        for number, pop in sorted(ctx.popups.items()):
            ctx.check()
            saved = popup.save(pop, os.path.join(root, "popups"), f"film{number:02d}")
            popups[str(number)] = "menus/popups/" + saved["file"]
            middle = pop.frames[len(pop.frames) // 2]
            middle.compose(middle.default).save(os.path.join(root, "popups", f"film{number:02d}.png"))
    home = f"menu:{ctx.first}"
    manifest = {"start": ctx.first, "playlists": ctx.playlists, "menus": menus, "popups": popups,
                "title_ends": {str(f.number): ctx.title_ends.get(f.number, home) for f in ctx.films},
                "playlist_ends": {p: ctx.playlist_ends.get(p, home) for p in ctx.playlists},
                "films": [{"number": f.number, "title": f.title, "chapters": [c.start for c in f.chapters]}
                          for f in ctx.films]}
    with open(os.path.join(ctx.out, "menus.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest


def film_infos(coll, media, thumbs) -> list[FilmInfo]:
    out = []
    base_keys = {"file", "title", "year", "place", "spinoff"}
    raw_films = coll.extra.get("films", [])
    for f in coll.films:
        m = media[f.number]
        th = thumbs.get(f.number, [])
        chapters = [Chapter(i + 1, t, timecode(t), th[i] if i < len(th) else None)
                    for i, t in enumerate(m.chapters)]
        raw = raw_films[f.number - 1] if f.number - 1 < len(raw_films) else {}
        out.append(FilmInfo(f.number, f.title, f.year, f.place, f.spinoff, coll.resolve(f.file),
                            m.duration, chapters, {k: v for k, v in raw.items() if k not in base_keys}))
    return out
