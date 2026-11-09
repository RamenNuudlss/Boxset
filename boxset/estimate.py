"""How much space each film will really take on the disc.

The encoder aims for a fixed picture quality (x264 CRF) and only uses the full
bitrate the disc allows when a scene needs it, so a film's size depends on the
film itself. Two ways to tell:

* `guess`: instant, from the source file's own bitrate and codec. Rough.
* `measure`: encodes a few short samples spread through the film with the
  real disc settings and counts how many bits each needed. Takes a minute or
  so per film and comes within about 10% of the real result. Results are cached per file.

Both give a list of sample bitrates (kbps) measured without the disc's limit.
`video_kbps(rates, ceiling)` turns that into the average the film will use
under a given limit, because the limit only clips the scenes that need more.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading

from . import probe

from .encoders import CRF_STANDARD, x264_args

SAMPLES = 12          # how many samples per film (more, shorter samples cover a film better)
SAMPLE_SECONDS = 3    # length of each
VERSION = 1           # bump when the encoder settings change, to measure again
UNLIMITED_KBPS = 30_000

# Roughly how many Blu-ray H.264 bits each bit of the source turns into. The disc
# encoder works at a high quality setting and keeps the source's grain and noise, so
# compressed downloads grow. Erring high keeps the rough figure from promising space
# that measuring then takes back.
_CODEC_FACTOR = {"hevc": 2.4, "av1": 2.8, "vp9": 2.2, "h264": 1.5,
                 "mpeg2video": 0.8, "vc1": 0.9, "mpeg4": 1.5}


def rescale(rates: list[float], from_crf: int, to_crf: int) -> list[float]:
    """Rough conversion between quality settings: x264 needs about half the bits
    for every 6 steps of CRF."""
    f = 2 ** (-(to_crf - from_crf) / 6)
    return [r * f for r in rates]


def guess(media, crf: int = CRF_STANDARD) -> list[float]:
    """A rough figure from the source file alone, before measuring."""
    src = getattr(media, "video_kbps", None)
    if not src:
        return [UNLIMITED_KBPS * 0.5]
    k = src * _CODEC_FACTOR.get(getattr(media, "vcodec", ""), 1.5)
    pixels = (media.width or 1920) * (media.height or 1080)
    if pixels > 1920 * 1088:            # 4K and up is scaled down to 1080p
        k *= 0.45
    elif pixels < 1280 * 720:           # small sources are scaled up, which adds some
        k *= 1.3
    k = rescale([k], CRF_STANDARD, crf)[0]
    return [max(1500.0, min(UNLIMITED_KBPS, k))]


def video_kbps(rates: list[float], ceiling: float) -> float:
    """Average video bitrate under the disc's per-film limit."""
    if not rates:
        return ceiling
    return sum(min(r, ceiling) for r in rates) / len(rates)


def limited_share(rates: list[float], ceiling: float) -> float:
    """Share of the film whose scenes want more than the limit allows."""
    if not rates:
        return 1.0
    return sum(1 for r in rates if r > ceiling * 1.02) / len(rates)


def measure(media, cancel: threading.Event | None = None, crf: int = CRF_STANDARD,
            preset: str = "medium") -> list[float] | None:
    """Encode short samples with the disc's real settings; return their bitrates."""
    from bdmvkit.encode import fit_filter
    from .pipeline import DISC_FPS
    fps = DISC_FPS.get(media.fps)
    if fps is None or media.duration <= 0:
        return None
    ffmpeg = probe.need("ffmpeg")
    n = max(2, min(SAMPLES, int(media.duration // (SAMPLE_SECONDS * 4))))
    length = min(SAMPLE_SECONDS, max(1.0, media.duration / (n * 2)))
    # spread through the film, skipping the opening logos and end credits
    starts = [media.duration * (0.08 + 0.84 * (i + 0.5) / n) for i in range(n)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    rates = []
    for t in starts:
        if cancel is not None and cancel.is_set():
            return None
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", media.path,
               "-t", f"{length:.2f}", "-map", "0:v:0", "-vf", fit_filter(fps), "-an", "-sn"]
        cmd += x264_args(fps, UNLIMITED_KBPS * 1000, (), preset, crf)
        cmd += ["-f", "h264", "pipe:1"]
        proc = subprocess.run(cmd, capture_output=True, creationflags=flags)
        if proc.returncode != 0 or not proc.stdout:
            continue
        rates.append(len(proc.stdout) * 8 / length / 1000)
    return rates or None


# ------------------------------------------------------------------ cache
def default_cache_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "Boxset")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "sizes.json")


class Cache:
    """Measured sample rates by file (path, size and date), kept between sessions."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        try:
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    @staticmethod
    def key(path: str, crf: int = CRF_STANDARD, preset: str = "medium") -> str | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        base = f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{int(st.st_mtime)}|v{VERSION}"
        if crf != CRF_STANDARD:
            base += f"|crf{crf}"
        return base if preset == "medium" else f"{base}|{preset}"

    def get(self, path: str, crf: int = CRF_STANDARD, preset: str = "medium") -> list[float] | None:
        k = self.key(path, crf, preset)
        return self.data.get(k) if k else None

    def put(self, path: str, rates: list[float], crf: int = CRF_STANDARD, preset: str = "medium"):
        k = self.key(path, crf, preset)
        if not k:
            return
        with self._lock:
            self.data[k] = [round(r, 1) for r in rates]
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh)
                os.replace(tmp, self.path)
            except OSError:
                pass
