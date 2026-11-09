"""Reads what's inside each rip with ffprobe: length, frame rate, chapters, audio."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction

# Frame rates a 1080p Blu-ray title can carry, as exact fractions.
BLURAY_FPS = {
    Fraction(24000, 1001): "23.976",
    Fraction(24, 1): "24",
    Fraction(25, 1): "25",
    Fraction(30000, 1001): "29.97",
}


@dataclass
class AudioStream:
    index: int
    codec: str
    channels: int
    language: str
    kbps: float | None = None      # from the file, when it says


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

    @property
    def fps_label(self) -> str:
        return BLURAY_FPS.get(self.fps, f"{float(self.fps):.3f}")


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
                                     language=(s.get("tags", {}) or {}).get("language", "und"),
                                     kbps=_stream_kbps(s)))

    m = Media(path=path, duration=duration, fps=fps, width=int(video.get("width", 0)),
              height=int(video.get("height", 0)), chapters=clean, audio=audio,
              vcodec=video.get("codec_name", ""),
              video_kbps=_video_kbps(info, video, audio, duration, path))
    if fps not in BLURAY_FPS:
        m.fatal.append(f"{float(fps):.3f} fps can't go on a Blu-ray (it takes 23.976, 24, 25 or 29.97)")
    elif m.fps_label == "24":
        m.problems.append("24 fps will be converted to 23.976 for the disc (an occasional frame is dropped)")
    if not audio:
        m.problems.append("no audio track, so the disc will play silence")
    if duration <= 0:
        m.fatal.append("couldn't read the running time")
    return m


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
