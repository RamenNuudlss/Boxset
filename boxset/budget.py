"""Works out how much video bitrate every film gets so the whole set fits the disc."""
from __future__ import annotations

from dataclasses import dataclass

from .config import DISC_SIZES

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
    estimated_bytes: int
    warning: str | None

    def describe(self) -> str:
        h, m = divmod(round(self.total_seconds / 60), 60)
        lines = [
            f"Disc:        {self.disc_size} ({self.capacity / 1e9:.1f} GB)",
            f"Running time {h} hr {m} min of film",
            f"Video:       {self.video_kbps / 1000:.1f} Mbps per film",
            f"Audio:       {self.audio_kbps} kbps Dolby Digital",
            f"Estimate:    {self.estimated_bytes / 1e9:.1f} GB used",
        ]
        if self.warning:
            lines.append(f"Warning:     {self.warning}")
        return "\n".join(lines)


def plan(disc_size: str, durations: list[float], audio_kbps: int) -> Plan:
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
    est = int((video + audio_kbps) * 1000 * total / 8 * (1 + MUX_OVERHEAD) + MENU_RESERVE)
    return Plan(disc_size, total, video, audio_kbps, cap, est, warning)
