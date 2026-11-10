"""What goes into each film's clip on the disc, and how it gets there.

For one film this works out a `Recipe`: the disc's frame rate, whether the
picture is copied or encoded (and tone-mapped from HDR), which sound tracks are
copied or encoded, and which subtitle tracks are carried. The build (pipeline.py)
turns a recipe into one FFmpeg command; the app uses the same recipes to size
the disc, so the two always agree.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from . import probe, subs as submod

MAX_AUDIO_TRACKS = 8
STEREO_KBPS = 192
DTS_FULL_KBPS, DTS_HALF_KBPS = 1509, 768


@dataclass
class AudioOut:
    stream: int            # which audio stream of the file (0-based)
    codec: str             # what it is on the disc: "ac3" or "dts"
    channels: int
    language: str
    kbps: int              # what it takes on the disc
    copy: bool = False     # carried as it is (for "dts": its core, without the HD extension)


@dataclass
class Recipe:
    fps: tuple                                   # the film's rate on the disc
    tempo: float = 1.0                           # how much longer it runs there (1.001 when slowed)
    tonemap: str = ""                            # "hdr10" or "hlg": convert to SDR while encoding
    copy_video: bool = False
    audio: list[AudioOut] = field(default_factory=list)    # empty: a silent stereo track
    subs: list = field(default_factory=list)               # probe.SubStream

    @property
    def audio_kbps(self) -> int:
        return sum(a.kbps for a in self.audio) or STEREO_KBPS


# ------------------------------------------------------------------ sound
def _encoded(settings, k: int, a) -> AudioOut:
    channels = 6 if a.channels >= 6 else 2
    return AudioOut(k, "ac3", channels, a.language, int(settings.audio_kbps) if channels > 2 else STEREO_KBPS)


def _chosen(settings, media) -> list:
    n = MAX_AUDIO_TRACKS if settings.audio_tracks == "all" else 1
    return list(enumerate(media.audio))[:n]


def planned_audio(settings, media) -> list[AudioOut]:
    """The film's sound tracks when its picture is encoded: Dolby Digital, copied
    when the file already holds it that way and copying is on, else encoded."""
    out = []
    for k, a in _chosen(settings, media):
        enc = _encoded(settings, k, a)
        if (settings.keep_streams and a.codec == "ac3" and a.sample_rate == 48000 and a.channels >= 2
                and media.tempo == 1.0):
            kbps = round(a.kbps) if a.kbps else enc.kbps
            out.append(AudioOut(k, "ac3", a.channels, a.language, kbps, copy=True))
        else:
            out.append(enc)
    return out


def _copied_audio(settings, media) -> list[AudioOut]:
    """The film's sound tracks when its picture is copied too: DTS keeps its core
    (the part every player decodes) instead of becoming Dolby Digital."""
    out = []
    for track, (k, a) in zip(planned_audio(settings, media), _chosen(settings, media)):
        if a.codec == "dts" and a.sample_rate == 48000 and a.channels >= 2:
            kbps = DTS_HALF_KBPS if a.kbps and a.kbps <= 900 and "HD" not in a.profile else DTS_FULL_KBPS
            track = AudioOut(k, "dts", a.channels, a.language, kbps, copy=True)
        out.append(track)
    return out


def planned_audio_kbps(settings, media) -> int:
    return sum(a.kbps for a in planned_audio(settings, media)) or STEREO_KBPS


# ------------------------------------------------------------------ the recipe
def recipe(settings, media, video_limit_kbps: float) -> Recipe:
    """How one film goes on the disc. `video_limit_kbps` is the disc's per-film
    video limit (budget.plan), which decides whether a copy fits."""
    fps = probe.DISC_FPS[media.fps]
    audio = planned_audio(settings, media)
    r = Recipe(fps=fps, tempo=media.tempo, audio=audio,
               tonemap=media.hdr if media.hdr in ("hdr10", "hlg") and tonemap_available() else "",
               subs=submod.usable(media) if settings.subtitles == "all" else [])
    if settings.keep_streams and media.bd_video and media.tempo == 1.0 and media.video_kbps:
        copied = _copied_audio(settings, media)
        room = video_limit_kbps + sum(a.kbps for a in audio)
        if media.video_kbps + sum(a.kbps for a in copied) <= room:
            r.copy_video, r.audio = True, copied
    return r


# ------------------------------------------------------------------ picture filters
_TONEMAP = ("zscale=tin={tin}:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
_TRANSFER = {"hdr10": "smpte2084", "hlg": "arib-std-b67"}
_tonemap_ok: bool | None = None


def tonemap_available() -> bool:
    """Whether this FFmpeg has the two filters HDR conversion needs."""
    global _tonemap_ok
    if _tonemap_ok is None:
        try:
            out = subprocess.run([probe.need("ffmpeg"), "-hide_banner", "-filters"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=30,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            names = {ln.split()[1] for ln in out.splitlines() if len(ln.split()) > 2}
            _tonemap_ok = {"zscale", "tonemap"} <= names
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            _tonemap_ok = False
    return _tonemap_ok


def tonemap_filter(kind: str) -> str:
    return _TONEMAP.format(tin=_TRANSFER[kind])


def video_filter(fps, tempo: float = 1.0, tonemap: str = "") -> str:
    """The picture fitted into the 1080p frame at the disc's rate: slowed first
    when the film is (so no frame is dropped), tone-mapped last (at 1080p, which
    is far quicker than at 4K)."""
    from bdmvkit.encode import fit_filter
    parts = []
    if tempo != 1.0:
        parts.append("setpts=PTS*1001/1000")
    parts.append(fit_filter(fps))
    if tonemap:
        parts.append(tonemap_filter(tonemap))
    return ",".join(parts)


def audio_filter(tempo: float = 1.0) -> str:
    """Sound padded with silence to the picture's length, slowed with it when the
    film is (by resampling: a pitch change of 0.1%, far below what anyone hears)."""
    slow = "aresample=48000,asetrate=48000*1000/1001,aresample=48000," if tempo != 1.0 else ""
    return slow + "apad"
