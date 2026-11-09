"""Everything the app's interface can ask for. One instance per window.

Methods are called from the interface through the local server (server.py).
Long jobs (rendering menus, building) run on a worker thread and stream
progress events to the interface.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .. import budget, core, estimate, pipeline, probe, project as projmod
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


class Api:
    def __init__(self):
        self.window = None                    # set by app.py in desktop mode
        self.project = Project()
        self.project.data.setdefault("name", "Untitled collection")
        self.meta: dict[str, dict] = {}        # file path -> facts from probing
        self._probing: set[str] = set()
        self._subs: list[queue.Queue] = []
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=3)
        self._measure_pool = ThreadPoolExecutor(max_workers=1)   # test encodes, one at a time
        self._measuring: set[tuple[str, int]] = set()
        self._media: dict = {}                                    # file path -> probe.Media
        self._stop_measuring = threading.Event()
        self.job: pipeline.Job | None = None
        self.status = self._idle_status()
        self.settings_path = os.path.join(config_dir(), "settings.json")
        self.settings = self._load_settings()
        self.estimates = estimate.Cache(estimate.default_cache_path())

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

    def _save_settings(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as fh:
                json.dump(self.settings, fh, indent=1)
        except OSError:
            pass

    def _remember(self, path):
        rec = [p for p in self.settings.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
        self.settings["recent"] = [path] + rec[:7]
        self.settings["last"] = path
        self._save_settings()

    # ------------------------------------------------------------------ project
    def _ensure_path(self):
        if self.project.path:
            return
        name = _slug(self.project.data.get("name", ""))
        base = os.path.join(documents_dir(), "Boxset")
        folder, n = os.path.join(base, name), 2
        while os.path.exists(folder):
            folder, n = os.path.join(base, f"{name} {n}"), n + 1
        self.project.save(os.path.join(folder, f"{name}.boxset"))
        self._remember(self.project.path)

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

    def _open(self, path):
        self.project = Project.open(path)
        self.project.data.setdefault("name", os.path.splitext(os.path.basename(path))[0])
        self.meta = {}
        self._remember(path)
        self._probe_missing()

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

    def update_film(self, index: int, fields: dict):
        self.project.update_film(int(index), fields or {})
        self._changed()
        return self.state()

    def move_film(self, src: int, dst: int):
        self._busy_guard()
        self.project.move_film(int(src), int(dst))
        self._clear_order_option()
        self._changed()
        return self.state()

    def remove_film(self, index: int):
        self._busy_guard()
        self.project.remove_film(int(index))
        self._clear_order_option()
        self._changed()
        return self.state()

    def _clear_order_option(self):
        self.project.data.get("theme_options", {}).pop("timeline_order", None)

    def _probe_missing(self):
        for f in self.project.films:
            p = f["file"]
            if p not in self.meta and p not in self._probing:
                self._probing.add(p)
                self._pool.submit(self._probe, p)

    def _crf(self) -> int:
        return estimate.crf_for(bool(self.project.data.get("save_space")))

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
            # sample bitrates by quality setting, as far as they've been measured
            info["rates"] = {str(c): r for c in (estimate.CRF_STANDARD, estimate.CRF_SAVE_SPACE)
                             if (r := self.estimates.get(path, c))}
            info["guess"] = estimate.guess(media)
        self.meta[path] = info
        self._probing.discard(path)
        self.push({"type": "meta", "file": path, "meta": info})
        self._measure_missing()

    def _need(self, m: dict):
        """(sample rates, state) for the current quality setting. state is True once
        measured, False while waiting to be measured, None if measuring failed."""
        crf = self._crf()
        rates = (m.get("rates") or {})
        if str(crf) in rates:
            return rates[str(crf)], True
        others = [(int(c), r) for c, r in rates.items()]
        if others:
            c, r = others[0]
            est = estimate.rescale(r, c, crf)
        else:
            est = estimate.rescale(m.get("guess") or [], estimate.CRF_STANDARD, crf) or None
        return est, (None if crf in m.get("failed", []) else False)

    def _measure_missing(self):
        crf = self._crf()
        for f in self.project.films:
            path, m = f["file"], self.meta.get(f["file"]) or {}
            if path not in self._media or "error" in m:
                continue
            if str(crf) in (m.get("rates") or {}) or crf in m.get("failed", []):
                continue
            if (path, crf) not in self._measuring:
                self._measuring.add((path, crf))
                self._measure_pool.submit(self._measure, path, crf)

    def _measure(self, path, crf):
        """Test-encode samples of the film to learn its real size on the disc."""
        rates = None
        try:
            if not any(f["file"] == path for f in self.project.films) or crf != self._crf():
                return                      # removed, or the setting changed, before its turn came
            while self.status.get("running"):
                if self._stop_measuring.wait(5):   # don't compete with a build
                    return
            rates = estimate.measure(self._media[path], self._stop_measuring, crf)
            if self._stop_measuring.is_set():
                return
        except Exception:
            rates = None
        finally:
            self._measuring.discard((path, crf))
        info = self.meta.get(path)
        if info is None:
            return
        info = dict(info)
        if rates:
            self.estimates.put(path, rates, crf)
            info["rates"] = dict(info.get("rates") or {}, **{str(crf): rates})
        else:
            info["failed"] = list(info.get("failed", [])) + [crf]   # keep the rough figure
        self.meta[path] = info
        self.push({"type": "meta", "file": path, "meta": info})

    # ------------------------------------------------------------------ settings on the project
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
        if key == "save_space":
            self._measure_missing()
        return self.state()

    def set_option(self, key: str, value):
        self.project.set_option(key, value)
        self._changed()
        return self.state()

    def pick_option_file(self, key: str, kind: str = "audio"):
        types = (f"Audio ({';'.join(AUDIO_EXTS)})",) if kind == "audio" else ("All files (*.*)",)
        res = self._dialog("open", "Choose a file", types)
        if res:
            return self.set_option(key, res[0])
        return self.state()

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
    def _plan(self):
        films = [(f["file"], self.meta.get(f["file"]) or {}) for f in self.project.films]
        known = [(path, m) for path, m in films if m.get("duration")]
        if not known:
            return None
        needs = [self._need(m) for _, m in known]
        p = budget.plan(self.project.data["disc_size"], [m["duration"] for _, m in known],
                        int(self.project.data.get("audio_kbps", 448)), [r for r, _ in needs])
        return {"video_kbps": p.video_kbps, "estimated_bytes": p.estimated_bytes, "capacity": p.capacity,
                "warning": p.warning, "complete": len(known) == len(films), "total_seconds": p.total_seconds,
                "reserve": budget.MENU_RESERVE, "overhead": budget.MUX_OVERHEAD,
                "audio_kbps": p.audio_kbps, "limited": p.limited,
                "films": {path: {"bytes": b, "measured": st} for (path, _), b, (_, st) in zip(known, p.film_bytes, needs)},
                "measuring": sum(1 for _, st in needs if st is False),
                "save_space": bool(self.project.data.get("save_space"))}

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
            "plan": self._plan(),
            "sizes": {k: v for k, v in DISC_SIZES.items()},
            "job": self.status,
            "menus": self._menus_status(),
            "native": self.window is not None,
            "windows": sys.platform == "win32",
            "recent": self.recent(),
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

    def build(self, opts: dict | None = None):
        opts = opts or {}
        return self._start("build", fast=bool(opts.get("fast")),
                           make_iso=bool(opts.get("iso")) and sys.platform == "win32")

    def make_iso(self):
        return self._start("iso")

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

    def _run_job(self, kind, path, kw):
        try:
            if kind == "iso":
                from .. import config, iso
                coll = config.load(path)
                folder = os.path.join(coll.build, "disc")
                if not os.path.isdir(os.path.join(folder, "BDMV")):
                    raise RuntimeError("Build the disc first.")
                out = iso.make_iso(folder, os.path.join(coll.build, f"{coll.label}.iso"), coll.label,
                                   coll.disc_size, self.job)
                result = {"iso": out, "folder": folder}
            else:
                result = pipeline.run(path, self.job, **kw)
                if kind == "menus":
                    result = {"screens": len(result["manifest"]["menus"])}
            self.status.update(running=False, result=result)
            self.push({"type": "job", "status": "done", "kind": kind, "result": result})
        except pipeline.Cancelled:
            self.status.update(running=False, error="Cancelled")
            self.push({"type": "job", "status": "cancelled", "kind": kind})
        except Exception as e:  # report every failure to the interface
            msg = str(e) or e.__class__.__name__
            self.status.update(running=False, error=msg)
            self.push({"type": "job", "status": "error", "kind": kind, "message": msg})
        finally:
            self.job = None

    def _on_event(self, e):
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
        self.push(e)

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

    def burn(self):
        """Hand the disc image to Windows' own disc burner."""
        res = (self.status.get("result") or {})
        iso_path = res.get("iso")
        if not iso_path:
            label = re.sub(r"[^A-Za-z0-9_]", "", self.project.data.get("disc_label", "")) or "COLLECTION"
            cand = os.path.join(self.project.build_dir, f"{label}.iso")
            iso_path = cand if os.path.exists(cand) else None
        if not iso_path:
            raise RuntimeError("Make the disc image first.")
        if sys.platform != "win32":
            raise RuntimeError("Burning uses Windows' built-in disc burner.")
        burner = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "isoburn.exe")
        subprocess.Popen([burner, iso_path])
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
