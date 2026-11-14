"""Grabs one frame per chapter to use as scene-selection thumbnails."""
from __future__ import annotations

import os
import subprocess

from .probe import need

OFFSET = 8.0  # seconds into the chapter, past fades and black frames


def _source_stamp(media, vf: str) -> str:
    """Identifies the film file the frames came from. Folders are named by disc position
    (film01, film02...), so without this a different film in the same slot reused the old frames."""
    try:
        st = os.stat(media.path)
        ident = f"{os.path.abspath(media.path)}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        ident = os.path.abspath(media.path)
    return f"{ident}|{vf}|{OFFSET}\n"


def grab(media, out_dir: str, width: int = 816, progress=None) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    starts = media.chapters
    vf = f"scale={width}:-2:flags=lanczos"
    if getattr(media, "hdr", "") in ("hdr10", "hlg"):
        from . import tracks
        if tracks.tonemap_available():      # HDR frames look grey unless converted
            vf += "," + tracks.tonemap_filter(media.hdr)
    stamp_path = os.path.join(out_dir, "source.txt")
    stamp = _source_stamp(media, vf)
    try:
        with open(stamp_path, encoding="utf-8") as fh:
            same = fh.read() == stamp
    except OSError:
        same = False
    if not same:                            # another film (or the file changed): start over
        for n in os.listdir(out_dir):
            if n.startswith("ch") and n.endswith(".jpg"):
                os.remove(os.path.join(out_dir, n))
        with open(stamp_path, "w", encoding="utf-8") as fh:
            fh.write(stamp)
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else media.duration
        t = min(start + OFFSET, start + max(0.0, (end - start) / 2))
        # the time is in the name so moved or added chapters get fresh frames
        p = os.path.join(out_dir, f"ch{i + 1:03d}_{round(t * 1000)}.jpg")
        if not os.path.exists(p):
            subprocess.run(
                [need("ffmpeg"), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", media.path,
                 "-frames:v", "1", "-vf", vf, "-q:v", "3", p],
                check=False, capture_output=True)
        paths.append(p if os.path.exists(p) else None)
        if progress:
            progress(i + 1, len(starts))
    keep = {os.path.basename(p) for p in paths if p}
    for n in os.listdir(out_dir):           # frames for chapters that no longer exist
        if n.startswith("ch") and n.endswith(".jpg") and n not in keep:
            os.remove(os.path.join(out_dir, n))
    return paths
