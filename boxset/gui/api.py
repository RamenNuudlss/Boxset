"""Everything the app's interface can ask for. One instance per window.

Methods are called from the interface through the local server (server.py).
Long jobs (rendering menus, building) run on a worker thread and stream
progress events to the interface.
"""
from __future__ import annotations

import functools
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

from .. import __version__, updates
from .. import budget, burner, core, encoders, estimate, pipeline, probe, project as projmod, tracks, winfix
from ..config import DISC_SIZES
from ..project import Project

AUDIO_EXTS = ("*.mp3", "*.wav", "*.flac", "*.m4a", "*.ogg", "*.aac")
VIDEO_PATTERNS = ";".join("*" + e for e in sorted(projmod.VIDEO_EXTS))


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "Boxset")
    os.makedirs(d, exist_ok=True)
    return d


def documents_dir() -> str:
    home = os.path.expanduser("~")
    for name in ("Documents", "documents"):
        if os.path.isdir(os.path.join(home, name)):
            return os.path.join(home, name)
    return home


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s).strip()
    return re.sub(r"\s+", " ", s) or "Untitled collection"


def _locked(fn):
    """Run a method while holding the state lock. Requests arrive on a thread each,
    and the probing, measuring and job threads report in too, so everything that
    reads or changes the project, the film facts or the job status takes turns."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._state_lock:
            return fn(self, *args, **kwargs)
    return wrapper


class Api:
    def __init__(self):
        self.window = None                    # set by app.py in desktop mode
        self.project = Project()
        self.project.data.setdefault("name", "Untitled collection")
        self.meta: dict[str, dict] = {}        # file path -> facts from probing
        self._probing: set[str] = set()
        self._subs: list[queue.Queue] = []
        self._lock = threading.RLock()                # event subscribers
        self._state_lock = threading.RLock()          # project, film facts, job status, settings
        self._pool = ThreadPoolExecutor(max_workers=3)
        self._measure_pool = ThreadPoolExecutor(max_workers=1)   # test encodes, one at a time
        self._measuring: set[tuple[str, int]] = set()
        self._media: dict = {}                                    # file path -> probe.Media
        self._stop_measuring = threading.Event()
        self.job: pipeline.Job | None = None
        self.status = self._idle_status()
        self.settings_path = os.path.join(config_dir(), "settings.json")
        self.settings = self._load_settings()
        core.restrict_project_themes(self.settings.get("trusted_theme_folders", []))
        self.update = None                            # {"version", "url"} once a newer release is found
        if self.settings.get("check_updates", True) and not os.environ.get("BOXSET_NO_UPDATE_CHECK"):
            threading.Thread(target=self._check_update, daemon=True).start()
        self.estimates = estimate.Cache(estimate.default_cache_path())
        self.gpu, self.gpu_checked = None, False
        threading.Thread(target=self._detect_gpu, daemon=True).start()
        self.burners: list[dict] | None = None      # None until the first look
        self._burner_lock = threading.Lock()
        threading.Thread(target=self._detect_burners, daemon=True).start()

    # ------------------------------------------------------------------ events
    def subscribe(self) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def push(self, event: dict):
        with self._lock:
            for q in list(self._subs):
                q.put(event)

    # ------------------------------------------------------------------ settings
    def _load_settings(self):
        try:
            with open(self.settings_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {"recent": []}

    @_locked
    def _save_settings(self):
        tmp = self.settings_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.settings, fh, indent=1)
            os.replace(tmp, self.settings_path)
        except OSError:
            pass

    @_locked
    def _remember(self, path):
        rec = [p for p in self.settings.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
        self.settings["recent"] = [path] + rec[:7]
        self.settings["last"] = path
        self._save_settings()

    # ------------------------------------------------------------------ project
    @_locked
    def _ensure_path(self):
        if self.project.path:
            return
        name = _slug(self.project.data.get("name", ""))
        base = os.path.join(documents_dir(), "Boxset")
        folder, n = os.path.join(base, name), 2
        while os.path.exists(folder):
            folder, n = os.path.join(base, f"{name} {n}"), n + 1
        self.project.save(os.path.join(folder, f"{name}.boxset"))
        self._trust_folder(folder)      # a folder the app just made holds nothing but this project
        self._remember(self.project.path)

    @_locked
    def _changed(self):
        """Autosave after every edit, once there's something worth saving."""
        if self.project.films or self.project.path:
            self._ensure_path()
            self.project.save()

    def load_initial(self, path: str | None):
        target = path or self.settings.get("last")
        if target and os.path.exists(target):
            try:
                self._open(target)
                return
            except (OSError, ValueError):
                pass

    @_locked
    def _open(self, path):
        self.project = Project.open(path)
        self.project.data.setdefault("name", os.path.splitext(os.path.basename(path))[0])
        self.meta = {}
        self._remember(path)
        self._probe_missing()

    @_locked
    def new_project(self):
        self._busy_guard()
        self.project = Project()
        self.project.data["name"] = "Untitled collection"
        self.meta = {}
        return self.state()

    def open_project(self, path: str | None = None):
        self._busy_guard()
        if not path:
            res = self._dialog("open", "Open a Boxset project", ("Boxset project (*.boxset;*.json)",))
            if not res:
                return None
            path = res[0]
        self._open(path)
        return self.state()

    def save_project_as(self, path: str | None = None):
        if not path:
            res = self._dialog("save", "Save project as", ("Boxset project (*.boxset)",),
                               save_name=_slug(self.project.data.get("name", "")) + ".boxset")
            if not res:
                return None
            path = res if isinstance(res, str) else res[0]
        if not path.lower().endswith(".boxset"):
            path += ".boxset"
        with self._state_lock:
            self.project.save(path)
            self._remember(path)
            return self.state()

    def recent(self):
        return [{"path": p, "name": os.path.splitext(os.path.basename(p))[0], "exists": os.path.exists(p)}
                for p in self.settings.get("recent", [])]

    # ------------------------------------------------------------------ films
    def pick_files(self):
        res = self._dialog("open", "Add movies", (f"Video files ({VIDEO_PATTERNS})", "All files (*.*)"), multiple=True)
        return self.add_paths(res) if res else self.state()

    def pick_folder(self):
        res = self._dialog("folder", "Add a folder of movies")
        return self.add_paths(res) if res else self.state()

    @_locked
    def add_paths(self, paths):
        self._busy_guard()
        paths = [p for p in (paths or []) if p]
        added = self.project.add_files(paths)
        if added:
            self._clear_order_option()
            self.project.data["timeline_order"] = None
            self._changed()
            self._probe_missing()
        self.push({"type": "films", "added": len(added)})
        return self.state()

    @_locked
    def update_film(self, index: int, fields: dict):
        self.project.update_film(int(index), fields or {})
        self._changed()
        return self.state()

    @_locked
    def move_film(self, src: int, dst: int):
        self._busy_guard()
        self.project.move_film(int(src), int(dst))
        self._clear_order_option()
        self._changed()
        return self.state()

    @_locked
    def remove_film(self, index: int):
        self._busy_guard()
        self.project.remove_film(int(index))
        self._clear_order_option()
        self._changed()
        return self.state()

    def _clear_order_option(self):
        self.project.data.get("theme_options", {}).pop("timeline_order", None)

    @_locked
    def _probe_missing(self):
        for f in self.project.films:
            p = f["file"]
            if p not in self.meta and p not in self._probing:
                self._probing.add(p)
                self._pool.submit(self._probe, p)

    # Sizes depend on the encoder settings, so films are measured per "profile":
    # the x264 quality (CRF) and preset a speed uses. The graphics card is sized
    # from the x264 "medium" measurement (see encoders.gpu_target_kbps).
    PRESET_FACTOR = {"medium": 1.0, "veryfast": 0.86}   # veryfast came out ~14% smaller in testing

    def _profile(self, m: dict, speed: str | None = None) -> tuple[int, str, bool]:
        """(crf, preset to measure with, sized as the graphics card) for a film."""
        crf = encoders.crf_for(bool(self.project.data.get("save_space")))
        speed = speed or self.project.data.get("speed", "quality")
        progressive = m.get("fps") in ("23.976", "24")
        if speed == "gpu" and self.gpu and progressive:
            return crf, "medium", True
        return crf, encoders.x264_preset(speed), False

    def _probe(self, path):
        media = None
        try:
            if os.path.exists(path):
                media = probe.probe(path)
                info = pipeline.describe(media)
            else:
                info = {"error": "File not found"}
        except Exception as e:
            info = {"error": str(e).splitlines()[0][:200]}
        if media is not None and "error" not in info:
            self._media[path] = media
            # sample bitrates per profile, as far as they've been measured
            info["rates"] = {f"{c}/{p}": r for c in (encoders.CRF_STANDARD, encoders.CRF_SAVE_SPACE)
                             for p in ("medium", "veryfast") if (r := self.estimates.get(path, c, p))}
            info["guess"] = estimate.guess(media)
        with self._state_lock:
            self.meta[path] = info
            self._probing.discard(path)
        self.push({"type": "meta", "file": path, "meta": info})
        self._measure_missing()

    def _need(self, m: dict, speed: str | None = None):
        """(sample rates, state) for the current settings (or another speed). state is
        True once measured, False while not measured yet, None if measuring failed."""
        crf, preset, gpu = self._profile(m, speed)
        key = f"{crf}/{preset}"
        rates = m.get("rates") or {}
        if key in rates:
            est, state = rates[key], True
        else:
            if rates:              # another profile is measured: convert it
                k, r = next(iter(rates.items()))
                c, p = k.split("/")
                est = estimate.rescale(r, int(c), crf)
                f = self.PRESET_FACTOR.get(preset, 1) / self.PRESET_FACTOR.get(p, 1)
                est = [x * f for x in est]
            else:
                est = estimate.rescale(m.get("guess") or [], encoders.CRF_STANDARD, crf)
                est = [x * self.PRESET_FACTOR.get(preset, 1) for x in est]
            est, state = est or None, (None if key in m.get("failed", []) else False)
        if gpu and est:
            est = [x * encoders.GPU_FACTOR for x in est]
        return est, state

    @_locked
    def _measure_missing(self):
        copied = {path for path, r in self._recipes().items() if r.copy_video}
        for f in self.project.films:
            path, m = f["file"], self.meta.get(f["file"]) or {}
            if path not in self._media or "error" in m or path in copied:
                continue                     # a copied film's size is already known exactly
            crf, preset, _ = self._profile(m)
            key = f"{crf}/{preset}"
            if key in (m.get("rates") or {}) or key in m.get("failed", []):
                continue
            if (path, key) not in self._measuring:
                self._measuring.add((path, key))
                self._measure_pool.submit(self._measure, path, crf, preset)

    def _measure(self, path, crf, preset):
        """Test-encode samples of the film to learn its real size on the disc."""
        key, rates = f"{crf}/{preset}", None
        try:
            with self._state_lock:
                m = self.meta.get(path) or {}
                wanted = (any(f["file"] == path for f in self.project.films)
                          and self._profile(m)[:2] == (crf, preset))
            if not wanted:
                return                      # removed, or the settings changed, before its turn came
            while self.status.get("running"):
                if self._stop_measuring.wait(5):   # don't compete with a build
                    return
            rates = estimate.measure(self._media[path], self._stop_measuring, crf, preset)
            if self._stop_measuring.is_set():
                return
        except Exception:
            rates = None
        finally:
            self._measuring.discard((path, key))
        if rates:
            self.estimates.put(path, rates, crf, preset)
        with self._state_lock:
            info = self.meta.get(path)
            if info is None:
                return
            info = dict(info)
            if rates:
                info["rates"] = dict(info.get("rates") or {}, **{key: rates})
            else:
                info["failed"] = list(info.get("failed", [])) + [key]   # keep the rough figure
            self.meta[path] = info
        self.push({"type": "meta", "file": path, "meta": info})

    def _detect_gpu(self):
        try:
            self.gpu = encoders.detect_gpu()
        except Exception:
            self.gpu = None
        self.gpu_checked = True
        self.push({"type": "gpu"})
        self._measure_missing()        # sizes on the graphics card use other measurements

    # ------------------------------------------------------------------ settings on the project
    @_locked
    def set(self, key: str, value):
        if key == "name":
            self.project.data["name"] = str(value).strip()[:80] or "Untitled collection"
            if not self.project.data.get("_custom_label"):
                self.project.set("disc_label", self.project.data["name"])
        elif key == "disc_label":
            self.project.data["_custom_label"] = True
            self.project.set("disc_label", value)
        else:
            self.project.set(key, value)
        self._changed()
        if key in ("save_space", "speed", "keep_streams", "disc_size", "audio_tracks"):
            self._measure_missing()
        return self.state()

    @_locked
    def set_option(self, key: str, value):
        self.project.set_option(key, value)
        self._changed()
        return self.state()

    def pick_option_file(self, key: str, kind: str = "audio"):
        types = ((f"Audio ({';'.join(AUDIO_EXTS)})",) if kind == "audio" else
                 ("Pictures (*.jpg;*.jpeg;*.png;*.webp)",) if kind == "image" else ("All files (*.*)",))
        res = self._dialog("open", "Choose a file", types)
        if res:
            return self.set_option(key, res[0])
        return self.state()

    @_locked
    def remove_theme(self, tid: str):
        """Remove an installed theme pack. A project using it switches to the first
        built-in theme, and its menus show as changed."""
        self._busy_guard()
        name = next((t["name"] for t in core.theme_catalog(self._coll_stub()) if t["id"] == tid), tid)
        core.remove_theme(tid)
        if self.project.data.get("theme") == tid:
            fallback = next((t["id"] for t in core.theme_catalog(self._coll_stub()) if t["builtin"]), "tachometer")
            self.project.set("theme", fallback)
            self._changed()
        self.push({"type": "themes"})
        self.push({"type": "toast", "message": f"Removed {name}"})
        return self.state()

    def _check_update(self):
        found = updates.check()
        if found:
            self.update = found
            self.push({"type": "update"})

    def open_update(self):
        """Open the newer release's page in the browser."""
        import webbrowser
        if self.update:
            webbrowser.open(self.update["url"])
        return {"ok": True}

    def _trust_folder(self, folder):
        folders = self.settings.setdefault("trusted_theme_folders", [])
        if not any(os.path.normcase(f) == os.path.normcase(folder) for f in folders):
            folders.append(folder)
            self._save_settings()
        core.restrict_project_themes(folders)

    @_locked
    def trust_project_themes(self):
        """The user's go-ahead to load the themes in this project's own folder.
        Themes are programs, so nothing in that folder runs before this."""
        if not self.project.path:
            return self.state()
        self._trust_folder(os.path.dirname(os.path.abspath(self.project.path)))
        self.push({"type": "themes"})
        return self.state()

    def _untrusted_themes(self):
        return core.untrusted_project_themes(self._coll_stub()) if self.project.path else []

    def install_theme(self, path: str | None = None):
        if not path:
            res = self._dialog("open", "Install a theme pack", ("Boxset theme (*.boxtheme;*.zip)",))
            if not res:
                return None
            path = res[0]
        tid = core.install_theme(path)
        self.push({"type": "themes"})
        st = self.state()
        st["installed"] = tid
        return st

    # ------------------------------------------------------------------ state
    def _track_settings(self):
        """The project's settings as the track recipes read them."""
        d = self.project.data
        return types.SimpleNamespace(audio_kbps=int(d.get("audio_kbps", 448)), audio_tracks=d.get("audio_tracks"),
                                     subtitles=d.get("subtitles"), keep_streams=bool(d.get("keep_streams")))

    def _known(self):
        """(path, facts, Media) for every film that has been read."""
        return [(f["file"], self.meta[f["file"]], self._media[f["file"]]) for f in self.project.films
                if (self.meta.get(f["file"]) or {}).get("duration") and f["file"] in self._media]

    @_locked
    def _recipes(self) -> dict:
        """How each film that has been read will go on the disc (tracks.Recipe), by path."""
        known = self._known()
        if not known:
            return {}
        st = self._track_settings()
        planned = [tracks.planned_audio_kbps(st, md) for _, _, md in known]
        limit = budget.video_limit(self.project.data["disc_size"], [m["duration"] for _, m, _ in known],
                                   st.audio_kbps, planned)
        return {path: tracks.recipe(st, md, limit) for path, _, md in known}

    def _plan(self, speed: str | None = None):
        known = self._known()
        if not known:
            return None
        st = self._track_settings()
        recipes = self._recipes()
        needs = [([md.video_kbps], True) if recipes[path].copy_video else self._need(m, speed)
                 for path, m, md in known]
        p = budget.plan(self.project.data["disc_size"], [m["duration"] for _, m, _ in known], st.audio_kbps,
                        [r for r, _ in needs],
                        [recipes[path].audio_kbps for path, _, _ in known],
                        [tracks.planned_audio_kbps(st, md) for _, _, md in known])
        return {"video_kbps": p.video_kbps, "estimated_bytes": p.estimated_bytes, "capacity": p.capacity,
                "warning": p.warning, "complete": len(known) == len(self.project.films),
                "total_seconds": p.total_seconds,
                "reserve": budget.MENU_RESERVE, "overhead": budget.MUX_OVERHEAD,
                "audio_kbps": p.audio_kbps, "limited": p.limited,
                "films": {path: {"bytes": b, "measured": state, "copy": recipes[path].copy_video,
                                 "audio": len(recipes[path].audio) or 1, "subs": len(recipes[path].subs)}
                          for (path, _, _), b, (_, state) in zip(known, p.film_bytes, needs)},
                "measuring": sum(1 for _, state in needs if state is False),
                "exact": all(state for _, state in needs),
                "save_space": bool(self.project.data.get("save_space")),
                "speed": speed or self.project.data.get("speed", "quality")}

    def _speed_sizes(self):
        """What the disc would hold at each speed, for the Speed control."""
        out = {}
        for sp in encoders.SPEEDS:
            if sp == "gpu" and not self.gpu:
                continue
            p = self._plan(sp)
            if p:
                out[sp] = {"bytes": p["estimated_bytes"], "exact": p["exact"]}
        return out

    @_locked
    def state(self):
        d = self.project.data
        themes = []
        for t in core.theme_catalog(self._coll_stub()):
            t = dict(t)
            t["preview_url"] = self.file_url(t["preview"]) if t.get("preview") else None
            t.pop("dir", None)
            t.pop("preview", None)
            themes.append(t)
        return {
            "project": {k: v for k, v in d.items() if not k.startswith("_")},
            "path": self.project.path,
            "folder": os.path.dirname(self.project.path) if self.project.path else None,
            "folder_display": self._short(os.path.dirname(self.project.path)) if self.project.path else None,
            "meta": {f["file"]: self.meta.get(f["file"]) for f in self.project.films},
            "themes": themes,
            "untrusted_themes": self._untrusted_themes(),
            "plan": self._plan(),
            "sizes": {k: v for k, v in DISC_SIZES.items()},
            "job": self.status,
            "menus": self._menus_status(),
            "native": self.window is not None,
            "windows": sys.platform == "win32",
            "recent": self.recent(),
            "gpu": self.gpu,
            "gpu_checked": self.gpu_checked,
            "speed_sizes": self._speed_sizes(),
            "burners": self._burner_state(),
            "version": __version__,
            "update": self.update,
        }

    @staticmethod
    def _short(path):
        """A folder as people think of it: relative to their user folder when inside it."""
        home = os.path.expanduser("~")
        try:
            rel = os.path.relpath(path, home)
        except ValueError:          # another drive on Windows
            return path
        return path if rel.startswith("..") else rel

    def _coll_stub(self):
        class _C:
            base_dir = os.path.dirname(self.project.path) if self.project.path else os.getcwd()
        return _C()

    def _menus_status(self):
        if not self.project.path:
            return None
        mpath = os.path.join(self.project.build_dir, "menus.json")
        if not os.path.exists(mpath):
            return None
        return {"rendered_at": os.path.getmtime(mpath)}

    def manifest(self):
        mpath = os.path.join(self.project.build_dir, "menus.json")
        if not os.path.exists(mpath):
            return None
        with open(mpath, encoding="utf-8") as fh:
            m = json.load(fh)
        root = self.project.build_dir
        for mn in m["menus"]:
            bg = os.path.join(root, mn["background"])
            mn["background_url"] = self.file_url(bg)
            mn["video"] = bg.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".m2ts"))
            mn["music_url"] = self.file_url(os.path.join(root, mn["music"])) if mn.get("music") else None
            for b in mn["buttons"]:
                for st in ("normal", "selected", "activated"):
                    b[st + "_url"] = self.file_url(os.path.join(root, b[st]))
        m["film_titles"] = {str(f["number"]): f["title"] for f in m["films"]}
        return m

    # filled in by the server: turns a file path into a URL the interface can load
    def file_url(self, path):  # pragma: no cover - replaced at runtime
        return path

    def allowed_roots(self):
        roots = core.theme_dirs(self._coll_stub())
        if self.project.path:
            roots.append(self.project.build_dir)
        return [os.path.abspath(r) for r in roots]

    # ------------------------------------------------------------------ jobs
    def _idle_status(self):
        return {"running": False, "kind": None, "stages": {}, "films": {}, "overall": 0.0,
                "log": [], "result": None, "error": None, "started": None}

    def _busy_guard(self):
        if self.status["running"]:
            raise RuntimeError("Wait for the current job to finish, or cancel it first.")

    def render_menus(self, force: bool = False):
        return self._start("menus", menus_only=True, force_menus=bool(force))

    def cancel_render(self):
        """Stop a menu render (the Stop button next to Render menus)."""
        if self.status.get("running") and self.status.get("kind") == "menus" and self.job:
            self.job.cancel()
        return self.state()

    @_locked
    def clear_menus(self):
        """Delete the rendered menus so the next render starts from nothing. Chapter
        frames are kept; they only depend on the films."""
        self._busy_guard()
        if not self.project.path:
            return self.state()
        build = self.project.build_dir
        removed = 0
        for rel in ("menus.json", "menus_preview.jpg"):
            p = os.path.join(build, rel)
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        for rel in ("menus", "html"):
            p = os.path.join(build, rel)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        self.push({"type": "toast", "message": "Rendered menus cleared" if removed else "No rendered menus to clear"})
        return self.state()

    def build(self, opts: dict | None = None):
        opts = opts or {}
        return self._start("build", fast=bool(opts.get("fast")),
                           make_iso=bool(opts.get("iso")) and sys.platform == "win32")

    def make_iso(self):
        return self._start("iso")

    @_locked
    def _start(self, kind, **kw):
        self._busy_guard()
        if not self.project.films:
            raise RuntimeError("Add some movies first.")
        missing = [f["title"] for f in self.project.films if not os.path.exists(f["file"])]
        if missing:
            raise RuntimeError("These files can't be found: " + ", ".join(missing))
        self._ensure_path()
        self.project.save()
        self.status = self._idle_status()
        self.status.update(running=True, kind=kind, started=time.time())
        self.job = pipeline.Job(self._on_event)
        path = self.project.path
        threading.Thread(target=self._run_job, args=(kind, path, kw), daemon=True).start()
        self.push({"type": "job", "status": "start", "kind": kind})
        return self.state()

    def _set_status(self, **kw):
        with self._state_lock:
            self.status.update(**kw)

    def _run_job(self, kind, path, kw):
        try:
            if kind == "iso":
                from .. import config, iso
                coll = config.load(path)
                folder = os.path.join(coll.build, "disc")
                if not os.path.isdir(os.path.join(folder, "BDMV")):
                    raise RuntimeError("Build the disc first.")
                with winfix.keep_awake():
                    out = iso.make_iso(folder, os.path.join(coll.build, f"{coll.label}.iso"), coll.label,
                                       coll.disc_size, self.job)
                result = {"iso": out, "folder": folder}
            else:
                result = pipeline.run(path, self.job, **kw)
                if kind == "menus":
                    result = {"screens": len(result["manifest"]["menus"])}
            self._set_status(running=False, result=result)
            self.push({"type": "job", "status": "done", "kind": kind, "result": result})
        except pipeline.Cancelled:
            self._set_status(running=False, error="Cancelled")
            self.push({"type": "job", "status": "cancelled", "kind": kind})
        except Exception as e:  # report every failure to the interface
            msg = str(e) or e.__class__.__name__
            self._set_status(running=False, error=msg)
            self.push({"type": "job", "status": "error", "kind": kind, "message": msg})
        finally:
            self.job = None

    def _on_event(self, e):
        with self._state_lock:
            self._note_event(e)
        self.push(e)

    def _note_event(self, e):
        st = self.status
        t = e.get("type")
        if t == "stage":
            st["stages"][e["stage"]] = {"status": e["status"], "label": e.get("label", "")}
        elif t == "progress":
            if e.get("stage") == "encode":
                st["films"][str(e["film"])] = {"pct": e["pct"], "eta": e.get("eta"), "speed": e.get("speed")}
                st["overall"] = e.get("overall", st["overall"])
            st["current"] = e
        elif t == "film":
            cur = st["films"].setdefault(str(e["film"]), {})
            cur["status"] = e["status"]
            if e["status"] == "done":
                cur["pct"] = 1.0
        elif t == "log":
            st["log"] = (st["log"] + [e])[-200:]
        elif t == "plan":
            st["plan"] = e

    def cancel(self):
        if self.job:
            self.job.cancel()
        return {"ok": True}

    # ------------------------------------------------------------------ OS helpers
    def open_folder(self, which: str = "project"):
        target = {"project": os.path.dirname(self.project.path or ""),
                  "build": self.project.build_dir,
                  "disc": os.path.join(self.project.build_dir, "disc")}.get(which, "")
        if not target or not os.path.isdir(target):
            raise RuntimeError("That folder doesn't exist yet.")
        if sys.platform == "win32":
            os.startfile(target)  # noqa: S606 - opening Explorer on the user's own folder
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return {"ok": True}

    # ------------------------------------------------------------------ burners
    def _detect_burners(self):
        if not self._burner_lock.acquire(blocking=False):
            return                                   # a look is already under way
        try:
            self.push({"type": "burners", "checking": True})
            self.burners = burner.list_drives()
        finally:
            self._burner_lock.release()
        self.push({"type": "burners"})

    def refresh_burners(self):
        threading.Thread(target=self._detect_burners, daemon=True).start()
        return self.state()

    @_locked
    def set_burner(self, drive_id: str):
        self.settings["burner"] = drive_id
        self._save_settings()
        return self.state()

    def _chosen_burner(self):
        drives = self.burners or []
        want = self.settings.get("burner")
        return (next((d for d in drives if d.get("id") == want and d.get("bd")), None)
                or next((d for d in drives if d.get("bd")), None))

    def _iso_path(self):
        res = (self.status.get("result") or {})
        iso_path = res.get("iso")
        if not iso_path and self.project.path:
            label = re.sub(r"[^A-Za-z0-9_]", "", self.project.data.get("disc_label", "")) or "COLLECTION"
            cand = os.path.join(self.project.build_dir, f"{label}.iso")
            iso_path = cand if os.path.exists(cand) else None
        return iso_path

    def _burner_state(self):
        chosen = self._chosen_burner()
        iso_path = self._iso_path()
        need = os.path.getsize(iso_path) if iso_path and os.path.exists(iso_path) else None
        if need is None:
            p = self._plan()
            need = p["estimated_bytes"] if p else None
        level, message = burner.check_disc(chosen, need) if self.burners is not None else ("wait", "Looking for burners…")
        return {"drives": self.burners, "chosen": chosen["id"] if chosen else None,
                "checking": self._burner_lock.locked(), "level": level, "message": message}

    def burn(self):
        """Hand the disc image to Windows' own disc burner, with the chosen drive."""
        iso_path = self._iso_path()
        if not iso_path:
            raise RuntimeError("Make the disc image first.")
        if sys.platform != "win32":
            raise RuntimeError("Burning uses Windows' built-in disc burner.")
        chosen = self._chosen_burner()
        burner.burn(iso_path, chosen.get("drive") if chosen else None)
        return {"ok": True}

    # ------------------------------------------------------------------ dialogs
    def _dialog(self, kind, title, file_types=(), multiple=False, save_name=""):
        if self.window is None:
            raise RuntimeError("NO_DIALOG")
        import webview
        fd = getattr(webview, "FileDialog", None)
        mode = {"open": getattr(fd, "OPEN", None) if fd else webview.OPEN_DIALOG,
                "save": getattr(fd, "SAVE", None) if fd else webview.SAVE_DIALOG,
                "folder": getattr(fd, "FOLDER", None) if fd else webview.FOLDER_DIALOG}[kind]
        kw = {"allow_multiple": multiple}
        if file_types and kind != "folder":
            kw["file_types"] = tuple(file_types)
        if kind == "save":
            kw = {"save_filename": save_name, "file_types": tuple(file_types)}
        res = self.window.create_file_dialog(mode, **kw)
        if not res:
            return None
        return [res] if isinstance(res, str) else list(res)
