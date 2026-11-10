"""Reads what's inside each rip with ffprobe: length, frame rate, chapters, audio."""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction

# Frame rates Boxset takes, as exact fractions, with their names. A 1080p Blu-ray
# title carries 23.976, 25 or 29.97; the others are converted (see DISC_FPS).
BLURAY_FPS = {
    Fraction(24000, 1001): "23.976",
    Fraction(24, 1): "24",
    Fraction(25, 1): "25",
    Fraction(30000, 1001): "29.97",
    Fraction(30, 1): "30",
    Fraction(50, 1): "50",
    Fraction(60000, 1001): "59.94",
    Fraction(60, 1): "60",
}

# source rate -> the rate it has on the disc
DISC_FPS = {
    Fraction(24000, 1001): (24000, 1001),
    Fraction(24, 1): (24000, 1001),
    Fraction(25, 1): (25, 1),
    Fraction(30000, 1001): (30000, 1001),
    Fraction(30, 1): (30000, 1001),
    Fraction(50, 1): (25, 1),
    Fraction(60000, 1001): (30000, 1001),
    Fraction(60, 1): (30000, 1001),
}

# Whole-number rates (24, 30, 60) are played 0.1% slower to reach the disc's rate,
# picture and sound together, the way films are put on disc. Nothing is dropped.
SLOWED_FPS = {Fraction(24, 1), Fraction(30, 1), Fraction(60, 1)}
SLOWDOWN = 1001 / 1000
# 50 and 59.94/60 frames a second keep every other frame.
HALVED_FPS = {Fraction(50, 1), Fraction(60000, 1001), Fraction(60, 1)}

TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
PGS_SUBS = {"hdmv_pgs_subtitle"}
HDR_TRANSFERS = {"smpte2084": "hdr10", "arib-std-b67": "hlg"}


@dataclass
class AudioStream:
    index: int
    codec: str
    channels: int
    language: str
    kbps: float | None = None      # from the file, when it says
    profile: str = ""              # e.g. "DTS-HD MA"
    sample_rate: int = 48000


@dataclass
class SubStream:
    index: int                     # which subtitle stream of the file (0-based); -1 for a file beside it
    codec: str
    language: str
    width: int = 0                 # picture subtitles: the frame they were made for
    height: int = 0
    forced: bool = False
    file: str = ""                 # a subtitle file beside the film (e.g. Film.en.srt)

    @property
    def kind(self) -> str:
        """"text", "pgs", or "" for a kind Boxset can't put on a disc."""
        if self.codec in TEXT_SUBS:
            return "text"
        if self.codec in PGS_SUBS:
            return "pgs" if (self.width, self.height) == (1920, 1080) else ""
        return ""


@dataclass
class Media:
    path: str
    duration: float
    fps: Fraction
    width: int
    height: int
    chapters: list[float] = field(default_factory=list)  # start times in seconds
    audio: list[AudioStream] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)   # warnings: handled, but worth knowing
    fatal: list[str] = field(default_factory=list)      # can't go on a Blu-ray as it is
    vcodec: str = ""
    auto_chapters: bool = False                         # chapters added by Boxset, not in the file
    video_kbps: float | None = None                     # the source's video bitrate, when known
    subs: list[SubStream] = field(default_factory=list)
    hdr: str = ""                                       # "", "hdr10", "hlg" or "dv" (Dolby Vision only)
    bd_video: bool = False                              # the picture is already what a Blu-ray holds

    @property
    def fps_label(self) -> str:
        return BLURAY_FPS.get(self.fps, f"{float(self.fps):.3f}")

    @property
    def tempo(self) -> float:
        """How much longer the film runs on the disc (1.001 for 24, 30 and 60 fps)."""
        return SLOWDOWN if self.fps in SLOWED_FPS else 1.0


def to_dict(m: Media) -> dict:
    """A Media as plain JSON data (for the probe cache)."""
    d = dataclasses.asdict(m)
    d["fps"] = [m.fps.numerator, m.fps.denominator]
    return d


def from_dict(d: dict) -> Media:
    """The reverse of to_dict. Raises (TypeError, ValueError, KeyError) on data
    written by a different version, which callers treat as "not cached"."""
    d = dict(d)
    d["fps"] = Fraction(int(d["fps"][0]), int(d["fps"][1]))
    d["audio"] = [AudioStream(**a) for a in d.get("audio", [])]
    d["subs"] = [SubStream(**x) for x in d.get("subs", [])]
    return Media(**d)


def need(tool: str) -> str:
    p = shutil.which(tool)
    if not p:
        raise RuntimeError(f"{tool} isn't installed or isn't on PATH. Install FFmpeg and try again.")
    return p


def probe(path: str) -> Media:
    out = subprocess.run(
        [need("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", "-show_chapters", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe couldn't read {path}:\n{out.stderr.strip()}")
    info = json.loads(out.stdout)

    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise RuntimeError(f"No video stream found in {path}.")

    num, den = (video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1").split("/")
    fps = Fraction(int(num), int(den) or 1)
    # snap near-misses (e.g. 23.9760239) to the exact Blu-ray rate
    for exact in BLURAY_FPS:
        if abs(float(fps) - float(exact)) < 0.01:
            fps = exact
            break

    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    chapters = sorted({round(float(c["start_time"]), 3) for c in info.get("chapters", [])})
    if not chapters or chapters[0] > 1:
        chapters = [0.0] + chapters
    # drop chapters closer than 5 s together or in the last 5 s (they're usually junk marks)
    clean = []
    for t in chapters:
        if t < duration - 5 and (not clean or t - clean[-1] >= 5):
            clean.append(t)

    audio = []
    for s in info.get("streams", []):
        if s.get("codec_type") == "audio":
            audio.append(AudioStream(index=s["index"], codec=s.get("codec_name", "?"),
                                     channels=int(s.get("channels", 2)),
                                     language=language((s.get("tags", {}) or {}).get("language")),
                                     kbps=_stream_kbps(s), profile=s.get("profile") or "",
                                     sample_rate=_int(s.get("sample_rate"), 48000)))
    subs, n = [], 0
    for s in info.get("streams", []):
        if s.get("codec_type") == "subtitle":
            subs.append(SubStream(index=n, codec=s.get("codec_name", "?"),
                                  language=language((s.get("tags", {}) or {}).get("language")),
                                  width=_int(s.get("width")), height=_int(s.get("height")),
                                  forced=bool((s.get("disposition") or {}).get("forced"))))
            n += 1
    subs += subtitle_files(path)

    m = Media(path=path, duration=duration, fps=fps, width=int(video.get("width", 0)),
              height=int(video.get("height", 0)), chapters=clean, audio=audio,
              vcodec=video.get("codec_name", ""),
              video_kbps=_video_kbps(info, video, audio, duration, path),
              subs=subs, hdr=_hdr(video))
    if fps not in BLURAY_FPS:
        m.fatal.append(f"{float(fps):.3f} fps can't go on a Blu-ray "
                       "(Boxset takes 23.976, 24, 25, 29.97, 30, 50, 59.94 and 60)")
    elif fps in SLOWED_FPS and fps in HALVED_FPS:
        m.problems.append(f"{m.fps_label} fps becomes 29.97 on the disc: every other frame is kept, "
                          "and it plays 0.1% slower")
    elif fps in SLOWED_FPS:
        m.problems.append(f"{m.fps_label} fps plays 0.1% slower on the disc, at "
                          f"{BLURAY_FPS[Fraction(*DISC_FPS[fps])]} (no frames are dropped)")
    elif fps in HALVED_FPS:
        m.problems.append(f"{m.fps_label} fps becomes {BLURAY_FPS[Fraction(*DISC_FPS[fps])]} on the disc: "
                          "every other frame is kept, so fast motion is a little less smooth")
    if m.hdr == "dv":
        m.problems.append("Dolby Vision without an HDR10 layer can't be converted, so its colours will "
                          "look wrong. Use an HDR10 or SDR version of this film")
    elif m.hdr:
        m.problems.append("HDR colour is converted to standard (SDR) for the disc")
    if not audio:
        m.problems.append("no audio track, so the disc will play silence")
    if duration <= 0:
        m.fatal.append("couldn't read the running time")
    if not m.fatal and _bd_shaped(video, m):
        m.bd_video = _short_gops(path, duration, m.video_kbps) and _disc_layout(path, duration)
    return m


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ISO 639-2 has two codes for some languages; discs use the "B" ones.
_LANG_T_TO_B = {"fra": "fre", "deu": "ger", "nld": "dut", "zho": "chi", "ces": "cze", "ell": "gre",
                "fas": "per", "isl": "ice", "msa": "may", "ron": "rum", "slk": "slo", "sqi": "alb",
                "hye": "arm", "eus": "baq", "mya": "bur", "kat": "geo", "mkd": "mac", "mri": "mao",
                "bod": "tib", "cym": "wel"}


def language(tag) -> str:
    """A file's language tag as the three-letter code a disc uses, or "und"."""
    from bdmvkit.formats import lang3
    tag = (tag or "").strip().lower().split("-")[0].split("_")[0]
    if len(tag) == 2:
        return lang3(tag)
    if len(tag) == 3 and tag.isalpha():
        return _LANG_T_TO_B.get(tag, tag)
    return "und"


def subtitle_files(path: str) -> list[SubStream]:
    """Subtitle files that sit beside a film and share its name: Film.srt,
    Film.en.srt, Film.eng.forced.srt and so on."""
    folder, name = os.path.split(os.path.abspath(path))
    stem = os.path.splitext(name)[0]
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for n in names:
        base, ext = os.path.splitext(n)
        if ext.lower() not in (".srt", ".ass", ".ssa", ".vtt") or not base.lower().startswith(stem.lower()):
            continue
        rest = base[len(stem):]
        if rest and not rest.startswith("."):
            continue                         # "Film 2.srt" belongs to another film
        tags = [t.lower() for t in rest.split(".") if t]
        lang = next((language(t) for t in tags if language(t) != "und"), "und")
        codec = {".srt": "subrip", ".ass": "ass", ".ssa": "ass", ".vtt": "webvtt"}[ext.lower()]
        out.append(SubStream(index=-1, codec=codec, language=lang, forced="forced" in tags,
                             file=os.path.join(folder, n)))
    return out


def _hdr(video) -> str:
    kind = HDR_TRANSFERS.get(video.get("color_transfer") or "", "")
    if kind:
        return kind
    for side in video.get("side_data_list") or []:
        if "DOVI" in (side.get("side_data_type") or ""):
            return "dv"                      # Dolby Vision with no HDR10 or HLG picture under it
    return ""


def _bd_shaped(video, m: Media) -> bool:
    """The cheap half of "is this picture already Blu-ray video?": H.264 High (or
    Main) up to level 4.1, 1920x1080, 8-bit 4:2:0, progressive, 23.976 fps, SDR,
    and no more than a Blu-ray's bitrate."""
    return (m.vcodec == "h264" and (video.get("profile") or "") in ("High", "Main")
            and 0 < _int(video.get("level")) <= 41
            and (m.width, m.height) == (1920, 1080)
            and video.get("pix_fmt") in ("yuv420p", "yuvj420p")
            and (video.get("field_order") or "progressive") == "progressive"
            and m.fps == Fraction(24000, 1001) and not m.hdr
            and _int(video.get("refs"), 1) <= 4
            and bool(m.video_kbps) and m.video_kbps <= 40_000)


def _short_gops(path: str, duration: float, video_kbps: float) -> bool:
    """The other half: a Blu-ray's video has a key frame at least every second
    (every two below 15 Mbps), which downloads and phone videos almost never do.
    Looks at three short stretches of the file; reads no pictures, so it's quick."""
    if duration < 60:
        return False
    limit = 1.1 if video_kbps > 15_000 else 2.1
    for part in (0.2, 0.5, 0.8):
        try:
            out = subprocess.run(
                [need("ffprobe"), "-v", "error", "-select_streams", "v:0",
                 "-read_intervals", f"{duration * part:.0f}%+12",
                 "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", path],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            return False
        if out.returncode != 0:
            return False
        keys = []
        for line in out.stdout.splitlines():
            t, _, flags = line.partition(",")
            try:
                if "K" in flags:
                    keys.append(float(t))
            except ValueError:
                pass
        keys.sort()
        gaps = [b - a for a, b in zip(keys, keys[1:])]
        if len(gaps) < 4 or max(gaps) > limit:
            return False
    return True


def _disc_layout(path: str, duration: float) -> bool:
    """Whether the picture, copied as it is, starts each key frame the way a disc's
    video must: its settings (SPS, PPS) ahead of everything but the delimiter.
    Video taken straight from a Blu-ray does; most other H.264 keeps the settings
    apart, and a copy would put them too late for strict players."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for start in (0.0, duration / 2):
        try:
            out = subprocess.run(
                [need("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.2f}", "-i", path,
                 "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "h264_mp4toannexb", "-frames:v", "1",
                 "-f", "h264", "pipe:1"],
                capture_output=True, timeout=60, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            return False
        if out.returncode != 0 or not _settings_first(out.stdout):
            return False
    return True


def _settings_first(frame: bytes) -> bool:
    """True if this H.264 frame carries its SPS and PPS before any other unit
    than the access unit delimiter."""
    seen, i = [], 0
    while len(seen) < 16:
        i = frame.find(b"\x00\x00\x01", i)
        if i < 0 or i + 3 >= len(frame):
            break
        kind = frame[i + 3] & 0x1F
        i += 3
        if kind in (1, 5):
            break
        seen.append(kind)
    rest = [k for k in seen if k != 9]
    return rest[:2] == [7, 8]


def _stream_kbps(s) -> float | None:
    """A stream's bitrate: ffprobe's figure, or the BPS tag MKV muxers write."""
    tags = s.get("tags", {}) or {}
    for v in (s.get("bit_rate"), tags.get("BPS"), tags.get("BPS-eng")):
        try:
            if v and float(v) > 0:
                return float(v) / 1000
        except ValueError:
            pass
    return None


# typical bitrates (kbps) for audio that doesn't state its own
_AUDIO_GUESS = {"truehd": 3500, "mlp": 3500, "dts": 1509, "flac": 2000, "pcm_s16le": 1536,
                "pcm_s24le": 2304, "pcm_bluray": 2304, "eac3": 768, "ac3": 448, "aac": 256,
                "opus": 192, "mp3": 192, "vorbis": 192}


def _video_kbps(info, video, audio, duration, path) -> float | None:
    v = _stream_kbps(video)
    if v:
        return v
    total = None
    try:
        total = float(info.get("format", {}).get("bit_rate") or 0) / 1000 or None
    except ValueError:
        pass
    if not total and duration > 0:
        try:
            total = os.path.getsize(path) * 8 / duration / 1000
        except OSError:
            return None
    if not total:
        return None
    a = sum(x.kbps or _AUDIO_GUESS.get(x.codec, 640) for x in audio)
    return max(total - a, total * 0.3)


def timecode(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"
