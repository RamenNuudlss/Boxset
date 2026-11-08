"""The whole job, from rips to disc, as cancellable steps that report progress.

Every step sends events to `emit(dict)`:
  {"type": "stage", "stage": "menus", "status": "start"|"done"|"skipped", "label": "…"}
  {"type": "progress", "stage": "encode", "film": 3, "pct": 0.42, "eta": 1830, "speed": 1.4, "overall": 0.31}
  {"type": "log", "level": "info"|"warn"|"error", "message": "…"}
The app turns these into its progress views; the command line prints them.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import shutil
import subprocess
import threading
import time
from fractions import Fraction

from . import budget, config, core, probe, thumbs

DISC_FPS = {
    Fraction(24000, 1001): (24000, 1001),
    Fraction(24, 1): (24000, 1001),
    Fraction(25, 1): (25, 1),
    Fraction(30000, 1001): (30000, 1001),
}

STAGES = ["check", "menus", "encode", "assemble", "iso"]


class Cancelled(Exception):
    pass


class Job:
    """One run of the pipeline. `cancel()` stops it at the next safe point,
    killing any running encoder."""

    def __init__(self, emit=None):
        self.emit = emit or (lambda e: None)
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None

    def cancel(self):
        self._cancel.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def check(self):
        if self._cancel.is_set():
            raise Cancelled()

    def log(self, message, level="info"):
        self.emit({"type": "log", "level": level, "message": message})

    def stage(self, stage, status, label=""):
        self.emit({"type": "stage", "stage": stage, "status": status, "label": label})


# --------------------------------------------------------------------- reading

def load_media(coll, job: Job | None = None, refresh=False):
    """Probe every rip (cached by path, size and date). Returns (media, problems), where
    problems are the things that stop a build. Warnings are logged to the job."""
    os.makedirs(coll.build, exist_ok=True)
    cache_p = os.path.join(coll.build, "probe2.cache")
    cache = {}
    if os.path.exists(cache_p) and not refresh:
        try:
            with open(cache_p, "rb") as fh:
                cache = pickle.load(fh)
        except Exception:
            cache = {}
    media, problems = {}, []
    for film in coll.films:
        if job:
            job.check()
        path = coll.resolve(film.file)
        if not os.path.exists(path):
            problems.append((film.number, f"File not found: {path}"))
            continue
        key = (path, os.path.getsize(path), int(os.path.getmtime(path)))
        try:
            m = cache.get(key) or probe.probe(path)
        except RuntimeError as e:
            problems.append((film.number, str(e)))
            continue
        cache[key] = m
        media[film.number] = m
        for p in getattr(m, "fatal", []):
            problems.append((film.number, p[0].upper() + p[1:]))
        for p in m.problems:
            if job:
                job.log(f"{film.title}: {p}", "warn")
    with open(cache_p, "wb") as fh:
        pickle.dump(cache, fh)
    return media, problems


def probe_one(path: str) -> dict:
    """Quick facts about one file for the app's film table."""
    m = probe.probe(path)
    a = m.audio[0] if m.audio else None
    return {"duration": m.duration, "chapters": len(m.chapters), "fps": m.fps_label,
            "width": m.width, "height": m.height, "size": os.path.getsize(path),
            "audio": f"{a.codec.upper()} {a.channels}ch" if a else "No audio",
            "problems": m.problems, **({"error": m.fatal[0][0].upper() + m.fatal[0][1:]} if m.fatal else {})}


# --------------------------------------------------------------------- menus

def _menu_fingerprint(coll, media) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"theme": coll.theme, "opts": coll.theme_options,
                         "order": coll.timeline_order,
                         "films": [[f.title, f.year, f.place, f.spinoff, media[f.number].chapters,
                                    round(media[f.number].duration, 1)] for f in coll.films],
                         "extra": [{k: v for k, v in raw.items() if k != "file"}
                                   for raw in coll.extra.get("films", [])]},
                        sort_keys=True, default=str).encode())
    # changes to the theme's own files count too
    themes = core.list_themes(coll)
    tdir = themes.get(coll.theme)
    if tdir:
        for root, _, files in os.walk(tdir):
            for n in sorted(files):
                if n.endswith((".py", ".css", ".html", ".png", ".jpg", ".ttf", ".otf", ".mp3", ".mp4")):
                    p = os.path.join(root, n)
                    h.update(f"{os.path.relpath(p, tdir)}:{os.path.getsize(p)}:{int(os.path.getmtime(p))}".encode())
    return h.hexdigest()[:16]


def render_menus(coll, media, job: Job, force=False) -> dict:
    fp = _menu_fingerprint(coll, media)
    mpath = os.path.join(coll.build, "menus.json")
    if not force and os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as fh:
            old = json.load(fh)
        if old.get("fingerprint") == fp:
            job.stage("menus", "skipped", "Menus are up to date")
            return old
    job.stage("menus", "start", "Rendering menus")
    tmap = {}
    if coll.theme_options.get("thumbnails", True):
        for film in coll.films:
            job.check()
            m = media[film.number]

            def prog(i, n, film=film):
                job.emit({"type": "progress", "stage": "menus", "label": f"Chapter frames: {film.title}",
                          "pct": ((film.number - 1) + i / max(1, n)) / len(coll.films) * 0.5})
            tmap[film.number] = thumbs.grab(m, os.path.join(coll.build, "thumbs", f"film{film.number:02d}"),
                                            progress=prog)
    theme, theme_dir = core.load_theme(coll, coll.theme, coll.theme_options)
    films = core.film_infos(coll, media, tmap)
    done = {"n": 0}

    def tlog(msg):
        done["n"] += 1
        job.check()
        job.emit({"type": "progress", "stage": "menus", "label": msg.strip(),
                  "pct": 0.5 + min(0.49, done["n"] / (len(coll.films) * 2 + 4) * 0.5)})

    ctx = core.Context(coll, films, theme_dir, coll.build, coll.theme_options, log=tlog)
    try:
        theme.build(ctx)
    finally:
        ctx.close()
    errors, warnings = core.validate(ctx)
    for w in warnings:
        job.log(w, "warn")
    if errors:
        raise RuntimeError("The theme made menus a Blu-ray player can't handle:\n" + "\n".join(errors))
    manifest = core.write_manifest(ctx)
    manifest["fingerprint"] = fp
    manifest["theme"] = coll.theme
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    job.stage("menus", "done", f"{len(manifest['menus'])} screens")
    return manifest


# --------------------------------------------------------------------- encoding

def audio_for(coll, media):
    a = media.audio[0] if media.audio else None
    channels = 6 if a and a.channels >= 6 else 2
    bitrate = coll.audio_kbps * 1000 if channels > 2 else 192_000
    lang = (a.language if a else "und") or "und"
    if not (len(lang) == 3 and lang.isalpha()):
        lang = "und"
    return channels, bitrate, lang


def _clip_settings(coll, media, plan, fast):
    st = os.stat(media.path)
    return {"source": media.path, "size": st.st_size, "mtime": int(st.st_mtime),
            "video_kbps": plan.video_kbps, "audio": list(audio_for(coll, media)[:2]), "fast": fast,
            "chapters": media.chapters, "v": 2}


def encode_film(job: Job, coll, film, media, plan, out, fast, on_progress):
    """Encode one film to a Blu-ray clip with ffmpeg + x264 (bdmvkit's settings),
    reporting progress from ffmpeg and stoppable mid-way."""
    from bdmvkit.encode import audio_args, fit_filter, video_args
    from bdmvkit.formats import AUDIO_PID, PMT_PID, VIDEO_PID
    fps = DISC_FPS.get(media.fps)
    if fps is None:
        raise RuntimeError(f"{film.title}: {float(media.fps):.3f} fps can't go on a Blu-ray")
    ffmpeg = probe.need("ffmpeg")
    channels, bitrate, _ = audio_for(coll, media)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y", "-progress", "pipe:1", "-nostats",
           "-i", media.path]
    graph = [f"[0:v:0]{fit_filter(fps)}[v]"]
    if media.audio:
        graph.append("[0:a:0]apad[a0]")
        amap = ["-map", "[a0]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        amap = ["-map", "1:a:0"]
    cmd += ["-filter_complex", ";".join(graph), "-map", "[v]"] + amap
    cmd += video_args(fps, plan.video_kbps * 1000, fast, [t for t in media.chapters if t > 0])
    cmd += audio_args("ac3", channels, 0, bitrate)
    cmd += ["-streamid", f"0:{VIDEO_PID}", "-streamid", f"1:{AUDIO_PID}",
            "-t", f"{media.duration:.3f}", "-f", "mpegts", "-mpegts_m2ts_mode", "1",
            "-mpegts_pmt_start_pid", str(PMT_PID), out]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=flags)
    job._proc = proc
    err_lines = []
    t_err = threading.Thread(target=lambda: err_lines.extend(proc.stderr.read().splitlines()[-20:]), daemon=True)
    t_err.start()
    started = time.time()
    try:
        for line in proc.stdout:
            if job.cancelled:
                break
            k, _, v = line.strip().partition("=")
            if k == "out_time_us" and v.isdigit():
                pos = int(v) / 1e6
                pct = min(0.999, pos / media.duration) if media.duration else 0
                el = time.time() - started
                speed = pos / el if el > 0 else 0
                eta = (media.duration - pos) / speed if speed > 0 else None
                on_progress(pct, eta, speed)
        proc.wait()
    finally:
        job._proc = None
        if proc.poll() is None:
            proc.kill()
    t_err.join(timeout=2)
    if job.cancelled or proc.returncode != 0:
        try:
            os.remove(out)          # never leave a half-written film behind
        except OSError:
            pass
    if job.cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        raise RuntimeError(f"Encoding {film.title} failed:\n" + "\n".join(err_lines[-8:]))


def clip_path(coll, media) -> str:
    """Encoded films are stored by source file, not disc position, so reordering
    films or editing their titles never re-encodes anything."""
    key = hashlib.sha1(os.path.normcase(os.path.abspath(media.path)).encode("utf-8")).hexdigest()[:16]
    return os.path.join(coll.build, "clips", f"{key}.m2ts")


def _tidy_clips(coll, media):
    """Remove encoded films that are no longer part of the project."""
    keep = {os.path.basename(clip_path(coll, media[f.number])) for f in coll.films}
    d = os.path.join(coll.build, "clips")
    for n in os.listdir(d) if os.path.isdir(d) else []:
        base = n[:-5] if n.endswith(".json") else n[:-5] if n.endswith(".part") else n
        if base not in keep:
            try:
                os.remove(os.path.join(d, n))
            except OSError:
                pass


def encode_all(coll, media, job: Job, plan, fast=False) -> dict[int, str]:
    clips_dir = os.path.join(coll.build, "clips")
    os.makedirs(clips_dir, exist_ok=True)
    total = sum(media[f.number].duration for f in coll.films)
    todo, clips = [], {}
    for film in coll.films:
        clip = clip_path(coll, media[film.number])
        clips[film.number] = clip
        want = _clip_settings(coll, media[film.number], plan, fast)
        meta = clip + ".json"
        have = None
        if os.path.exists(clip) and os.path.exists(meta):
            try:
                with open(meta, encoding="utf-8") as fh:
                    have = json.load(fh)
            except ValueError:
                have = None
        if have != want:
            todo.append((film, clip, meta, want))
    if not todo:
        job.stage("encode", "skipped", "All films already encoded")
        return clips
    job.stage("encode", "start", f"Encoding {len(todo)} film{'s' if len(todo) != 1 else ''}")
    done_secs = total - sum(media[f.number].duration for f, *_ in todo)
    for film, clip, meta, want in todo:
        job.check()
        m = media[film.number]
        part = clip + ".part"
        job.emit({"type": "film", "film": film.number, "status": "encoding", "title": film.title})
        base = done_secs

        def prog(pct, eta, speed, film=film, m=m, base=base):
            job.emit({"type": "progress", "stage": "encode", "film": film.number, "pct": pct,
                      "eta": eta, "speed": round(speed, 2), "overall": (base + pct * m.duration) / total})
        encode_film(job, coll, film, m, plan, part, fast, prog)
        os.replace(part, clip)
        with open(meta, "w", encoding="utf-8") as fh:
            json.dump(want, fh)
        done_secs += m.duration
        job.emit({"type": "film", "film": film.number, "status": "done", "title": film.title,
                  "bytes": os.path.getsize(clip)})
    job.stage("encode", "done", "All films encoded")
    return clips


# --------------------------------------------------------------------- assembly

def _stage_link(src, dst):
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def assemble(coll, media, manifest, clips, job: Job, fast=False) -> dict:
    from bdmvkit import Disc, MenuButton
    from bdmvkit.errors import BdmvError
    job.stage("assemble", "start", "Writing the disc structure")
    out = os.path.join(coll.build, "disc")
    stage = os.path.join(coll.build, "stage")
    for d in (out, stage):
        if os.path.isdir(d):
            shutil.rmtree(d)
    os.makedirs(stage)
    start = f"menu:{manifest['start']}"
    disc = Disc(first_play=start, title_key=start)
    for film in coll.films:
        m = media[film.number]
        staged = os.path.join(stage, f"film{film.number:02d}.m2ts")
        _stage_link(clips[film.number], staged)
        channels, _, lang = audio_for(coll, m)
        disc.add_title(staged, fps=DISC_FPS[m.fps], chapters=m.chapters,
                       audio=[("ac3", channels, lang)], end=manifest["title_ends"][str(film.number)])
    for pid, items in manifest["playlists"].items():
        disc.add_playlist(pid, items, end=manifest["playlist_ends"].get(pid, start))
    menu_fps = DISC_FPS[media[coll.films[0].number].fps]
    p = lambda rel: os.path.join(coll.build, rel) if rel else None
    for mn in manifest["menus"]:
        job.check()
        buttons = [MenuButton(b["id"], b["x"], b["y"], selected=p(b["selected"]), activated=p(b["activated"]),
                              normal=p(b["normal"]), action=b["action"], nav=b["nav"]) for b in mn["buttons"]]
        disc.add_menu(mn["id"], p(mn["background"]), buttons, fps=menu_fps,
                      default=mn["default_button"], music=p(mn.get("music")))
    try:
        result = disc.write(out, move=True, play_all=False, fast=fast)
    except BdmvError as e:
        raise RuntimeError(f"Writing the disc failed: {e}")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(out) for f in fs)
    job.stage("assemble", "done", "Disc structure written")
    return {"folder": out, "bytes": size, "titles": result["titles"], "menus": result["menus"],
            "chapters": sum(result["chapters"])}


# --------------------------------------------------------------------- everything

def run(collection_path: str, job: Job, menus_only=False, skip_encode=False, fast=False,
        make_iso=False, force_menus=False) -> dict:
    """Rips -> menus -> encoded films -> BDMV folder (-> ISO). Returns a summary."""
    coll = config.load(collection_path)
    job.stage("check", "start", "Reading your films")
    media, problems = load_media(coll, job)
    if problems:
        raise RuntimeError("\n".join(f"Film {n}: {msg}" for n, msg in problems))
    plan = budget.plan(coll.disc_size, [media[f.number].duration for f in coll.films], coll.audio_kbps)
    job.emit({"type": "plan", "video_kbps": plan.video_kbps, "estimated_bytes": plan.estimated_bytes,
              "capacity": plan.capacity, "warning": plan.warning})
    if plan.warning:
        job.log(plan.warning.capitalize(), "warn")
    job.stage("check", "done", f"{len(coll.films)} films ready")

    manifest = render_menus(coll, media, job, force=force_menus)
    if menus_only:
        return {"manifest": manifest}
    job.check()
    if skip_encode:
        clips = {f.number: clip_path(coll, media[f.number]) for f in coll.films}
        missing = [f.title for f in coll.films if not os.path.exists(clips[f.number])]
        if missing:
            raise RuntimeError("Not encoded yet: " + ", ".join(missing))
    else:
        clips = encode_all(coll, media, job, plan, fast)
    job.check()
    result = assemble(coll, media, manifest, clips, job, fast)
    _tidy_clips(coll, media)
    if result["bytes"] > plan.capacity:
        job.log(f"The disc is {result['bytes'] / 1e9:.1f} GB, more than a {coll.disc_size} holds.", "warn")
    if make_iso:
        from . import iso
        job.check()
        result["iso"] = iso.make_iso(result["folder"], os.path.join(coll.build, f"{coll.label}.iso"),
                                     coll.label, coll.disc_size, job)
    return result
