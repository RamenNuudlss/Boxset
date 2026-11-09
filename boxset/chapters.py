"""Chapters for films whose files have none.

Downloads often carry no chapter marks, which leaves a disc with no scene
selection. Boxset adds one every few minutes, like a retail disc, and moves
each to the nearest cut within a few seconds so a chapter starts on a fresh
shot rather than mid-scene. Finding the cuts decodes a short low-resolution
window around each point, about a minute per film, and the result is cached.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import probe

INTERVALS = (3, 4, 5, 6, 8, 10)     # minutes, as offered in the app
DEFAULT_MINUTES = 5
WINDOW = 12.0        # seconds either side of each point to look for a cut
SCENE = 0.28         # ffmpeg scene-change score that counts as a cut
VERSION = 1


def needs_chapters(media) -> bool:
    return len(media.chapters) <= 1


def evenly(duration: float, minutes: int) -> list[float]:
    """Chapter points every `minutes`, starting at 0, none in the last two minutes."""
    step = minutes * 60
    pts, t = [0.0], float(step)
    while t < duration - 120:
        pts.append(t)
        t += step
    return pts


def _cuts(path: str, start: float, length: float) -> list[tuple[float, float]]:
    """(time, score) of the cuts in a stretch of the film."""
    cmd = [probe.need("ffmpeg"), "-hide_banner", "-nostdin", "-ss", f"{start:.2f}", "-t", f"{length:.2f}",
           "-i", path, "-map", "0:v:0", "-an", "-sn",
           "-vf", f"scale=320:-2,select='gt(scene\\,{SCENE})',metadata=print", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out, t = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and t is not None:
            out.append((start + t, float(m.group(1))))
            t = None
    return out


def snapped(path: str, points: list[float], check=None) -> list[float]:
    """Move each point (except 0) to the strongest nearby cut, keeping order and
    at least a minute between chapters."""
    result = [0.0]
    for p in points[1:]:
        if check:
            check()
        best = p
        cuts = [(t, s) for t, s in _cuts(path, max(0.0, p - WINDOW), WINDOW * 2) if abs(t - p) <= WINDOW]
        if cuts:
            # prefer strong cuts, then the nearest one
            best = max(cuts, key=lambda c: c[1] - abs(c[0] - p) / (WINDOW * 4))[0]
        if best - result[-1] >= 60:
            result.append(round(best, 3))
    return result


class Cache:
    """Auto chapters per file and interval, kept in the project's build folder."""

    def __init__(self, path: str):
        self.path = path
        try:
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    @staticmethod
    def key(path: str, minutes: int) -> str | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        return f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{int(st.st_mtime)}|{minutes}|v{VERSION}"

    def get(self, path, minutes):
        k = self.key(path, minutes)
        return self.data.get(k) if k else None

    def put(self, path, minutes, points):
        k = self.key(path, minutes)
        if not k:
            return
        self.data[k] = points
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
        except OSError:
            pass


def add_to(media, minutes: int, cache: Cache, log=None, check=None, title="") -> bool:
    """Give `media` automatic chapters if its file has none. Returns True if it did."""
    if not minutes or not needs_chapters(media) or media.duration < 8 * 60:
        return False
    pts = cache.get(media.path, minutes)
    if pts is None:
        if log:
            log(f"Adding chapters to {title or os.path.basename(media.path)} (its file has none)")
        pts = snapped(media.path, evenly(media.duration, minutes), check)
        cache.put(media.path, minutes, pts)
    media.chapters = list(pts)
    media.auto_chapters = True
    return True
