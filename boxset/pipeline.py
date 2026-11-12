"""The whole job, from rips to disc, as cancellable steps that report progress.

Every step sends events to `emit(dict)`:
  {"type": "stage", "stage": "menus", "status": "start"|"done"|"skipped", "label": "…"}
  {"type": "progress", "stage": "encode", "film": 3, "pct": 0.42, "eta": 1830, "speed": 1.4, "overall": 0.31}
  {"type": "log", "level": "info"|"warn"|"error", "message": "…"}
The app turns these into its progress views; the command line prints them.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time

from . import budget, chapters, config, core, encoders, estimate, popup, probe, subs as submod, thumbs, tracks, winfix

DISC_FPS = probe.DISC_FPS      # source frame rate -> the rate it has on the disc
PROBE_CACHE_VERSION = 1        # bump when probe.Media gains something a cached entry would lack

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
    # JSON, not pickle: a build folder can arrive with a project from someone else,
    # and reading a cache must never be able to run anything.
    cache_p = os.path.join(coll.build, "probe.json")
    cache = {}
    if os.path.exists(cache_p) and not refresh:
        try:
            with open(cache_p, encoding="utf-8") as fh:
                cache = json.load(fh)
        except (OSError, ValueError):
            cache = {}
        cache = cache.get("files", {}) if isinstance(cache, dict) and cache.get("v") == PROBE_CACHE_VERSION else {}
    try:
        os.remove(os.path.join(coll.build, "probe3.cache"))     # the cache earlier versions wrote
    except OSError:
        pass
    fresh = {}
    media, problems = {}, []
    for film in coll.films:
        if job:
            job.check()
        path = coll.resolve(film.file)
        if not os.path.exists(path):
            problems.append((film.number, f"File not found: {path}"))
            continue
        key = f"{path}|{os.path.getsize(path)}|{int(os.path.getmtime(path))}"
        m = None
        if key in cache:
            try:
                m = probe.from_dict(cache[key])
            except (TypeError, ValueError, KeyError, IndexError):
                m = None                 # written by another version: read the file again
        try:
            m = m or probe.probe(path)
        except RuntimeError as e:
            problems.append((film.number, str(e)))
            continue
        fresh[key] = probe.to_dict(m)
        minutes = coll.auto_chapters
        if minutes and chapters.needs_chapters(m):
            m = dataclasses.replace(m, chapters=list(m.chapters))
            chapters.add_to(m, minutes, chapters.Cache(os.path.join(coll.build, "chapters.json")),
                            log=job.log if job else None, check=job.check if job else None, title=film.title)
        media[film.number] = m
        for p in getattr(m, "fatal", []):
            problems.append((film.number, p[0].upper() + p[1:]))
        for p in m.problems:
            if job:
                job.log(f"{film.title}: {p}", "warn")
    tmp = cache_p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"v": PROBE_CACHE_VERSION, "files": fresh}, fh)
        os.replace(tmp, cache_p)
    except OSError:
        pass                             # the cache only saves time
    return media, problems


def probe_one(path: str) -> dict:
    """Quick facts about one file for the app's film table."""
    return describe(probe.probe(path))


def describe(m) -> dict:
    a = m.audio[0] if m.audio else None
    return {"duration": m.duration, "chapters": len(m.chapters), "fps": m.fps_label,
            "channels": a.channels if a else 2,
            "audio_tracks": len(m.audio), "subtitles": len(submod.usable(m)), "hdr": m.hdr,
            "bd_video": m.bd_video,
            "width": m.width, "height": m.height, "size": os.path.getsize(m.path),
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
    # files picked in the theme's settings (logos, covers, music): a replaced file is a change
    for key, value in sorted((coll.theme_options or {}).items()):
        if isinstance(value, str) and value:
            path = value if os.path.isabs(value) else os.path.join(coll.base_dir, value)
            if os.path.isfile(path):
                st = os.stat(path)
                h.update(f"{key}:{st.st_size}:{int(st.st_mtime)}".encode())
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

    ctx = core.Context(coll, films, theme_dir, coll.build, coll.theme_options, log=tlog, check=job.check)
    ctx.hdr = {n: m.hdr for n, m in media.items() if m.hdr}
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


def _clip_settings(coll, media, plan, enc, recipe=None):
    """Everything an encoded film depends on. A film is encoded again only when
    this changes. What was added later (more tracks, subtitles, slowing, HDR
    conversion, copying) only appears when it applies, so films encoded by
    earlier versions still count as done."""
    st = os.stat(media.path)
    d = {"source": media.path, "size": st.st_size, "mtime": int(st.st_mtime),
         "video_kbps": plan.video_kbps, "audio": list(audio_for(coll, media)[:2]),
         "enc": enc, "chapters": media.chapters, "v": 2}
    if recipe is None:
        return d
    if recipe.copy_video:
        d["video_kbps"] = 0            # a copy doesn't depend on the disc's limit
    if len(recipe.audio) > 1 or any(a.codec != "ac3" for a in recipe.audio):
        d["tracks"] = [[a.stream, a.codec, 6 if a.channels > 2 else 2] for a in recipe.audio]
    if recipe.subs:
        d["subs"] = [[s.kind, s.index, s.language, os.path.basename(s.file),
                      int(os.path.getmtime(s.file)) if s.file and os.path.exists(s.file) else 0]
                     for s in recipe.subs]
    if recipe.tempo != 1.0:
        d["tempo"] = round(recipe.tempo, 6)
    if recipe.tonemap:
        d["tonemap"] = recipe.tonemap
    return d


def _legacy_settings(have: dict) -> dict:
    """Settings saved by earlier versions, in today's form, so their films aren't
    encoded again for nothing."""
    if "enc" in have:
        return have
    fast = have.pop("fast", False)
    crf = have.pop("crf", None)
    have["enc"] = {"encoder": "x264", "preset": "ultrafast" if fast else "medium",
                   "crf": encoders.CRF_TEST_BUILD if fast else (crf or encoders.CRF_STANDARD)}
    return have


def choose_encoder(coll, film, media, plan, fast, job: Job | None = None, gpu=None, sizes=None,
                   recipe=None) -> dict:
    """How one film's picture gets onto the disc: copied when the recipe says it
    can be, else encoded as the build's speed and quality settings say."""
    if recipe is not None and recipe.copy_video:
        return {"encoder": "copy"}
    if fast:
        return {"encoder": "x264", "preset": "ultrafast", "crf": encoders.CRF_TEST_BUILD}
    crf = encoders.crf_for(coll.save_space)
    speed = coll.speed
    if encoders.uses_gpu(speed, gpu, DISC_FPS[media.fps]):
        sizes = sizes or estimate.Cache(estimate.default_cache_path())
        rates = sizes.get(media.path, crf)
        if not rates:
            if job:
                job.log(f"Measuring {film.title} to set the graphics card's bitrate")
            rates = estimate.measure(media, job._cancel if job else None, crf)
            if rates:
                sizes.put(media.path, rates, crf)
            else:
                rates = estimate.guess(media, crf)
        kbps = encoders.gpu_target_kbps(rates, plan.video_kbps)
        return {"encoder": gpu["encoder"], "kbps": int(kbps // 10 * 10)}
    return {"encoder": "x264", "preset": encoders.x264_preset(speed), "crf": crf}


def prepare_subs(job: Job, film, media, recipe, workdir: str) -> list[tuple]:
    """The film's subtitle tracks ready for muxing: ("pgs", stream index, language)
    for picture subtitles copied from the file, ("sup", file, language) for text
    drawn here. Tracks that can't be made are left out, with a note."""
    out = []
    for n, sub in enumerate(recipe.subs):
        job.check()
        if sub.kind == "pgs":
            out.append(("pgs", sub.index, sub.language))
            continue
        name = sub.language if sub.language != "und" else f"track {n + 1}"
        try:
            cues = submod.read_cues(media.path, sub)
            if not cues:
                continue
            if not submod.drawable(cues):
                job.log(f"{film.title}: the {name} subtitles are in a script Boxset can't draw yet, "
                        "so they're left out.", "warn")
                continue
            os.makedirs(workdir, exist_ok=True)
            path = os.path.join(workdir, f"sub{n:02d}.sup")
            if submod.write_sup(cues, path, recipe.tempo, job.check):
                out.append(("sup", path, sub.language))
        except RuntimeError as e:
            job.log(f"{film.title}: couldn't read the {name} subtitles ({str(e).splitlines()[-1][:120]}), "
                    "so they're left out.", "warn")
    return out


def encode_command(ffmpeg: str, media, recipe, enc: dict, max_kbps: int, out: str, sub_inputs=()) -> list[str]:
    """The FFmpeg command that turns one film into its Blu-ray clip: picture
    (copied, or fitted and encoded as `enc` says), then the sound tracks, then the
    subtitle tracks, each with the stream number the disc's playlists expect."""
    from bdmvkit.encode import audio_args
    from bdmvkit.formats import AUDIO_PID, PG_PID, PMT_PID, VIDEO_PID
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y", "-progress", "pipe:1", "-nostats",
           "-i", media.path]
    inputs = 1
    graph, maps, codecs = [], [], []
    disc_seconds = media.duration * recipe.tempo
    if recipe.copy_video:
        maps += ["-map", "0:v:0"]
        codecs += ["-c:v", "copy"]
    else:
        graph.append(f"[0:v:0]{tracks.video_filter(recipe.fps, recipe.tempo, recipe.tonemap)}[v]")
        maps += ["-map", "[v]"]
        keys = [t * recipe.tempo for t in media.chapters if t > 0]
        if enc["encoder"] == "x264":
            codecs += encoders.x264_args(recipe.fps, max_kbps * 1000, keys, enc["preset"], enc["crf"])
        else:
            codecs += encoders.gpu_args(enc["encoder"], recipe.fps, max_kbps * 1000, enc["kbps"] * 1000, keys)
    if not recipe.audio:                  # a film without sound gets a silent track
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        maps += ["-map", f"{inputs}:a:0"]
        inputs += 1
        codecs += audio_args("ac3", 2, 0, tracks.STEREO_KBPS * 1000)
    for k, a in enumerate(recipe.audio):
        if a.copy:
            maps += ["-map", f"0:a:{a.stream}"]
            codecs += [f"-c:a:{k}", "copy"]
            if a.codec == "dts":          # the core every player decodes, without the HD extension
                codecs += [f"-bsf:a:{k}", "dca_core"]
        else:
            graph.append(f"[0:a:{a.stream}]{tracks.audio_filter(recipe.tempo)}[a{k}]")
            maps += ["-map", f"[a{k}]"]
            codecs += audio_args("ac3", a.channels, k, a.kbps * 1000)
    for kind, what, _ in sub_inputs:
        if kind == "pgs" and recipe.tempo == 1.0:
            maps += ["-map", f"0:s:{what}"]
            continue
        if kind == "pgs":                 # the same file again, its times stretched with the film
            cmd += ["-itsscale", f"{recipe.tempo:.6f}", "-i", media.path]
            maps += ["-map", f"{inputs}:s:{what}"]
        else:
            cmd += ["-f", "sup", "-i", what]
            maps += ["-map", f"{inputs}:s:0"]
        inputs += 1
    if graph:
        cmd += ["-filter_complex", ";".join(graph)]
    cmd += maps + codecs
    if sub_inputs:
        cmd += ["-c:s", "copy"]
    n_audio = max(1, len(recipe.audio))
    cmd += ["-streamid", f"0:{VIDEO_PID}"]
    for k in range(n_audio):
        cmd += ["-streamid", f"{1 + k}:{AUDIO_PID + k}"]
    for k in range(len(sub_inputs)):
        cmd += ["-streamid", f"{1 + n_audio + k}:{PG_PID + k}"]
    cmd += ["-t", f"{disc_seconds:.3f}", "-f", "mpegts", "-mpegts_m2ts_mode", "1",
            "-mpegts_pmt_start_pid", str(PMT_PID), out]
    return cmd


def made_tracks(recipe, sub_inputs=()) -> dict:
    """What a clip holds, as the disc's playlists need it told."""
    audio = [[a.codec, a.channels, a.language] for a in recipe.audio] or [["ac3", 2, "und"]]
    return {"audio": audio, "subs": [lang for _, _, lang in sub_inputs]}


def encode_film(job: Job, coll, film, media, plan, out, enc, on_progress, recipe=None, sub_inputs=()):
    """Make one film's Blu-ray clip with FFmpeg (see encode_command), reporting
    progress and stoppable mid-way."""
    if media.fps not in DISC_FPS:
        raise RuntimeError(f"{film.title}: {float(media.fps):.3f} fps can't go on a Blu-ray")
    if recipe is None:
        recipe = tracks.recipe(coll, media, plan.video_kbps)
    ffmpeg = probe.need("ffmpeg")
    cmd = encode_command(ffmpeg, media, recipe, enc, plan.video_kbps, out, sub_inputs)
    disc_seconds = media.duration * recipe.tempo
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
                pct = min(0.999, pos / disc_seconds) if disc_seconds else 0
                el = time.time() - started
                speed = pos / el if el > 0 else 0
                eta = (disc_seconds - pos) / speed if speed > 0 else None
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


def film_recipes(coll, media, plan) -> dict:
    return {f.number: tracks.recipe(coll, media[f.number], plan.video_kbps) for f in coll.films}


def encode_all(coll, media, job: Job, plan, fast=False, recipes=None) -> dict[int, str]:
    recipes = recipes or film_recipes(coll, media, plan)
    clips_dir = os.path.join(coll.build, "clips")
    os.makedirs(clips_dir, exist_ok=True)
    total = sum(media[f.number].duration for f in coll.films)
    gpu = None
    if not fast and coll.speed == "gpu":
        gpu = encoders.detect_gpu()
        if gpu:
            job.log(f"Encoding with the graphics card: {gpu['name']}")
        else:
            job.log("No graphics card encoder works on this PC, so films are encoded with Faster instead.", "warn")
        if gpu and any(DISC_FPS[media[f.number].fps] != encoders.FILM_FPS for f in coll.films):
            job.log("Films that go on the disc at 25 or 29.97 fps are encoded with Faster: the graphics "
                    "card can't make the 1080i video Blu-ray needs at those rates.", "warn")
    sizes = estimate.Cache(estimate.default_cache_path())
    todo, clips = [], {}
    for film in coll.films:
        clip = clip_path(coll, media[film.number])
        clips[film.number] = clip
        recipe = recipes[film.number]
        enc = choose_encoder(coll, film, media[film.number], plan, fast, job, gpu, sizes, recipe)
        want = _clip_settings(coll, media[film.number], plan, enc, recipe)
        meta = clip + ".json"
        have = None
        if os.path.exists(clip) and os.path.exists(meta):
            try:
                with open(meta, encoding="utf-8") as fh:
                    have = json.load(fh)
            except ValueError:
                have = None
        if have is not None:
            have.pop("made", None)           # what the clip holds, not what it depends on
            have = _legacy_settings(have)
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
        recipe = recipes[film.number]
        part = clip + ".part"
        job.emit({"type": "film", "film": film.number, "status": "encoding", "title": film.title})
        base = done_secs
        if recipe.copy_video:
            job.log(f"{film.title}: the picture is already Blu-ray video, so it's copied as it is.")
        if m.hdr in ("hdr10", "hlg") and not recipe.tonemap:
            job.log(f"{film.title} is HDR, and this FFmpeg can't convert it (it lacks the zscale filter), "
                    "so its colours will look washed out.", "warn")
        if coll.subtitles == "all":
            for note in submod.skipped(m):
                job.log(f"{film.title}: left out {note}.", "warn")
        subdir = clip + ".subs"
        sub_inputs = prepare_subs(job, film, m, recipe, subdir)

        def prog(pct, eta, speed, film=film, m=m, base=base):
            job.emit({"type": "progress", "stage": "encode", "film": film.number, "pct": pct,
                      "eta": eta, "speed": round(speed, 2), "overall": (base + pct * m.duration) / total})
        try:
            encode_film(job, coll, film, m, plan, part, want["enc"], prog, recipe, sub_inputs)
        except RuntimeError as e:
            if want["enc"]["encoder"] in ("x264", "copy"):
                raise
            # the card failed (driver, memory, an unusual source): do this film on the processor
            first = next((ln for ln in str(e).splitlines()[1:] if ln.strip()), str(e))[:160]
            job.log(f"The graphics card couldn't encode {film.title} ({first}). Encoding it with Faster instead.",
                    "warn")
            want = dict(want, enc={"encoder": "x264", "preset": encoders.x264_preset("fast"),
                                   "crf": encoders.crf_for(coll.save_space)})
            encode_film(job, coll, film, m, plan, part, want["enc"], prog, recipe, sub_inputs)
        finally:
            shutil.rmtree(subdir, ignore_errors=True)
        os.replace(part, clip)
        with open(meta, "w", encoding="utf-8") as fh:
            json.dump(dict(want, made=made_tracks(recipe, sub_inputs)), fh)
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


def _made(coll, media, clip: str) -> dict:
    """The sound and subtitle tracks in an encoded film, from the note saved
    beside it; films encoded by earlier versions hold one Dolby Digital track."""
    try:
        with open(clip + ".json", encoding="utf-8") as fh:
            made = json.load(fh).get("made")
        if made and made.get("audio"):
            return {"audio": made["audio"], "subs": made.get("subs") or []}
    except (OSError, ValueError):
        pass
    channels, _, lang = audio_for(coll, media)
    return {"audio": [["ac3", channels, lang]], "subs": []}


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
    popups = {int(n): popup.load(os.path.join(coll.build, rel))
              for n, rel in (manifest.get("popups") or {}).items()}

    class PopupDisc(Disc):
        """A Disc whose pop-ups are Boxset's: a frame for each moment of the film
        (popup.py), where bdmvkit's own show one picture throughout."""

        def _add_popup(self, t, buttons, default, pt, nav):
            from bdmvkit import hdmv
            from bdmvkit.formats import FORMATS
            from bdmvkit.m2ts import scan_m2ts
            number = self.titles.index(t) + 1
            data, m = popups[number], media[coll.films[number - 1].number]
            job.check()
            job.log(f"Adding the pop-up to {coll.films[number - 1].title}")
            commands = {}
            for b, pb in zip(data["frames"][0]["buttons"], pt.popup_buttons):
                if b["action"] == "close":
                    commands[b["id"]] = [hdmv.popup_off()]
                elif b["action"]:
                    commands[b["id"]] = nav.button(pb)
            sets = popup.schedule(data, commands, FORMATS[t.fps][1], m.tempo, m.duration * m.tempo)
            popup.insert(t.clip, pt.clip, sets, scan_m2ts(t.clip).first_pts, job.check)

    disc = PopupDisc(first_play=start, title_key=start)
    for film in coll.films:
        m = media[film.number]
        staged = os.path.join(stage, f"film{film.number:02d}.m2ts")
        _stage_link(clips[film.number], staged)
        made = _made(coll, m, clips[film.number])
        disc.add_title(staged, fps=DISC_FPS[m.fps], chapters=[round(t * m.tempo, 3) for t in m.chapters],
                       audio=[tuple(a) for a in made["audio"]], subtitles=list(made["subs"]),
                       end=manifest["title_ends"][str(film.number)])
    for number, data in sorted(popups.items()):
        disc.add_popup(number, [MenuButton(b["id"], b["x"], b["y"], selected="",
                                           action=b["action"] if b["action"] not in ("", "close") else None)
                                for b in data["frames"][0]["buttons"]])
    for pid, items in manifest["playlists"].items():
        disc.add_playlist(pid, items, end=manifest["playlist_ends"].get(pid, start))
    menu_fps = DISC_FPS[media[coll.films[0].number].fps]
    p = lambda rel: os.path.join(coll.build, rel) if rel else None
    for mn in manifest["menus"]:
        job.check()
        buttons = [MenuButton(b["id"], b["x"], b["y"], selected=p(b["selected"]), activated=p(b["activated"]),
                              normal=p(b["normal"]), action=b["action"], nav=b["nav"], auto=bool(b.get("auto")))
                   for b in mn["buttons"]]
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


# --------------------------------------------------------------------- disc space

def space_needed(coll, media, make_iso=False, sizes=None) -> int:
    """Roughly how many bytes of working space the build still needs in the build
    folder: the films not encoded yet, the menus, and the disc image if one is made.
    (The disc folder itself reuses the encoded films, so it adds almost nothing.)"""
    crf = encoders.crf_for(coll.save_space)
    sizes = sizes or estimate.Cache(estimate.default_cache_path())
    ms = [media[f.number] for f in coll.films]
    durations = [m.duration for m in ms]
    planned = [tracks.planned_audio_kbps(coll, m) for m in ms]
    limit = budget.video_limit(coll.disc_size, durations, coll.audio_kbps, planned)
    recipes = [tracks.recipe(coll, m, limit) for m in ms]
    needs = [[m.video_kbps] if r.copy_video else sizes.get(m.path, crf) or estimate.guess(m, crf)
             for m, r in zip(ms, recipes)]
    p = budget.plan(coll.disc_size, durations, coll.audio_kbps, needs,
                    [r.audio_kbps for r in recipes], planned)
    to_encode = sum(b for m, b in zip(ms, p.film_bytes) if not os.path.exists(clip_path(coll, m)))
    return to_encode + budget.MENU_RESERVE + (p.estimated_bytes if make_iso else 0)


def check_space(coll, media, job: Job, make_iso=False):
    """Say so before hours of encoding, not after, when the drive is too full. The
    figure is an estimate, so only a drive that is clearly too small stops the build."""
    try:
        free = shutil.disk_usage(coll.build).free
    except OSError:
        return
    need = space_needed(coll, media, make_iso)
    if free >= need:
        return
    msg = (f"This build needs about {need / 1e9:.0f} GB of free space in {coll.build}, "
           f"and the drive has {free / 1e9:.0f} GB.")
    if free < need * 0.5:
        raise RuntimeError(msg + " Free up some space, or move the project to a drive with more room.")
    job.log(msg + " It may run out before the disc is finished.", "warn")


# --------------------------------------------------------------------- everything

def run(collection_path: str, job: Job, menus_only=False, skip_encode=False, fast=False,
        make_iso=False, force_menus=False) -> dict:
    """Rips -> menus -> encoded films -> BDMV folder (-> ISO). Returns a summary."""
    with winfix.keep_awake():
        return _run(collection_path, job, menus_only, skip_encode, fast, make_iso, force_menus)


def _run(collection_path: str, job: Job, menus_only=False, skip_encode=False, fast=False,
        make_iso=False, force_menus=False) -> dict:
    coll = config.load(collection_path)
    job.stage("check", "start", "Reading your films")
    media, problems = load_media(coll, job)
    if problems:
        raise RuntimeError("\n".join(f"Film {n}: {msg}" for n, msg in problems))
    # the limit allows for each film's sound: more tracks leave a little less for the picture
    plan = budget.plan(coll.disc_size, [media[f.number].duration for f in coll.films], coll.audio_kbps,
                       film_audio=[tracks.planned_audio_kbps(coll, media[f.number]) for f in coll.films])
    recipes = film_recipes(coll, media, plan)
    job.emit({"type": "plan", "video_kbps": plan.video_kbps, "estimated_bytes": plan.estimated_bytes,
              "capacity": plan.capacity, "warning": plan.warning})
    if plan.warning:
        job.log(plan.warning.capitalize(), "warn")
    if not menus_only and not fast:        # test builds are a fraction of the size
        check_space(coll, media, job, make_iso)
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
        clips = encode_all(coll, media, job, plan, fast, recipes)
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
