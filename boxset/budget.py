"""Works out how much video bitrate every film gets so the whole set fits the disc."""
from __future__ import annotations

from dataclasses import dataclass

from .config import DISC_SIZES
from .estimate import limited_share, video_kbps

MENU_RESERVE = 1_500_000_000      # bytes held back for menus, thumbnails and filesystem
MUX_OVERHEAD = 0.05               # M2TS packet and header overhead (~4-5%)
MAX_VIDEO_KBPS = 30_000           # no point going higher for re-encoded rips
MIN_SANE_KBPS = 3_000             # below this, warn loudly


@dataclass
class Plan:
    disc_size: str
    total_seconds: float
    video_kbps: int
    audio_kbps: int
    capacity: int
    estimated_bytes: int          # what the disc will really hold, from each film's needs
    warning: str | None
    film_bytes: list[int]         # per film, in the order given
    limited: float = 0.0          # share of the running time held back by the limit (0 to 1)

    def describe(self) -> str:
        h, m = divmod(round(self.total_seconds / 60), 60)
        lines = [
            f"Disc:        {self.disc_size} ({self.capacity / 1e9:.1f} GB)",
            f"Running time {h} hr {m} min of film",
            f"Video:       up to {self.video_kbps / 1000:.1f} Mbps per film",
            f"Audio:       {self.audio_kbps} kbps Dolby Digital",
            f"Estimate:    about {self.estimated_bytes / 1e9:.1f} GB used, "
            f"{max(0, self.capacity - self.estimated_bytes) / 1e9:.1f} GB free",
        ]
        if self.warning:
            lines.append(f"Warning:     {self.warning}")
        return "\n".join(lines)


def film_size(duration: float, video: float, audio_kbps: int) -> int:
    return int((video + audio_kbps) * 1000 * duration / 8 * (1 + MUX_OVERHEAD))


def plan(disc_size: str, durations: list[float], audio_kbps: int,
         needs: list[list[float] | None] | None = None,
         film_audio: list[int] | None = None) -> Plan:
    """`needs`: per film, the sample bitrates from estimate.guess/measure. Films
    without one are counted at the full limit, the most they could take."""
    cap = DISC_SIZES[disc_size]
    total = sum(durations)
    usable_bits = (cap - MENU_RESERVE) * 8 / (1 + MUX_OVERHEAD)
    total_kbps = usable_bits / total / 1000
    video = int(min(MAX_VIDEO_KBPS, total_kbps - audio_kbps) // 100 * 100)
    warning = None
    if video < MIN_SANE_KBPS:
        bigger = [s for s in DISC_SIZES if DISC_SIZES[s] > cap]
        warning = (f"only {video / 1000:.1f} Mbps per film; picture quality will suffer"
                   + (f" (a {bigger[0]} would help)" if bigger else ""))
    needs = needs or [None] * len(durations)
    film_audio = film_audio or [audio_kbps] * len(durations)
    sizes, held = [], 0.0
    for d, rates, a in zip(durations, needs, film_audio):
        v = video_kbps(rates, video) if rates else video
        sizes.append(film_size(d, v, a))
        held += d * (limited_share(rates, video) if rates else 1.0)
    est = sum(sizes) + MENU_RESERVE
    return Plan(disc_size, total, video, audio_kbps, cap, est, warning, sizes,
                held / total if total else 0.0)
