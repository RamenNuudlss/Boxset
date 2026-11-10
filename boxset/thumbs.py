"""Grabs one frame per chapter to use as scene-selection thumbnails."""
from __future__ import annotations

import os
import subprocess

from .probe import need

OFFSET = 8.0  # seconds into the chapter, past fades and black frames


def grab(media, out_dir: str, width: int = 816, progress=None) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    starts = media.chapters
    vf = f"scale={width}:-2:flags=lanczos"
    if getattr(media, "hdr", "") in ("hdr10", "hlg"):
        from . import tracks
        if tracks.tonemap_available():      # HDR frames look grey unless converted
            vf += "," + tracks.tonemap_filter(media.hdr)
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else media.duration
        t = min(start + OFFSET, start + max(0.0, (end - start) / 2))
        p = os.path.join(out_dir, f"ch{i + 1:03d}.jpg")
        if not os.path.exists(p):
            subprocess.run(
                [need("ffmpeg"), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", media.path,
                 "-frames:v", "1", "-vf", vf, "-q:v", "3", p],
                check=False, capture_output=True)
        paths.append(p if os.path.exists(p) else None)
        if progress:
            progress(i + 1, len(starts))
    return paths
