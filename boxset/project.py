"""A disc project: the films, the theme and its options, disc settings.

Saved as JSON (*.boxset). The command line
(boxset-cli) and the app read and write the same files.
"""
from __future__ import annotations

import json
import os
import re

from .config import DISC_SIZES

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".m2ts", ".ts", ".wmv", ".webm", ".vob", ".mpg", ".mpeg"}

_TAGS = re.compile(
    r"\b(2160p|1080p|1080i|720p|480p|4k|uhd|hdr10\+?|hdr|dv|dolby ?vision|sdr|blu-?ray|bdrip|brrip|bdremux|"
    r"remux|web-?dl|webrip|web|hdtv|dvdrip|x26[45]|h\.?26[45]|hevc|avc|aac|ac3|dts(-hd)?|truehd|atmos|"
    r"ddp?5\.1|5\.1|7\.1|10bit|8bit|proper|repack|extended|unrated|imax|criterion|theatrical|directors cut)\b.*",
    re.I)


def guess_title_year(path: str) -> tuple[str, int | None]:
    """'The.Fast.and.the.Furious.2001.1080p.BluRay.mkv' -> ('The Fast and the Furious', 2001)."""
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"[._]+", " ", name).strip()
    year = None
    m = re.search(r"[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]", name)
    if not m:
        # last year-like number that isn't the first word ("1917", "Blade Runner 2049 2017")
        cands = [c for c in re.finditer(r"(?<!\d)((?:19|20)\d{2})(?!\d)", name) if c.start() > 0]
        m = cands[-1] if cands else None
    if m:
        year = int(m.group(1))
        name = name[:m.start()]
    name = _TAGS.sub("", name)
    name = re.sub(r"[\[\(\{].*?[\]\)\}]", "", name)
    name = re.sub(r"\s+-\s*$|\s{2,}", " ", name).strip(" -")
    if name.islower() or name.isupper():
        small = {"a", "an", "and", "the", "of", "in", "on", "at", "to", "for", "or", "vs"}
        words = name.lower().split()
        name = " ".join(w if i and w in small else w.capitalize() for i, w in enumerate(words))
    return name or os.path.basename(path), year


DEFAULT = {
    "theme": "tachometer",
    "theme_options": {},
    "disc_label": "MY_COLLECTION",
    "disc_size": "BD-50",
    "audio_kbps": 448,
    "timeline_order": None,
    "build_dir": "build",
    "films": [],
}


class Project:
    def __init__(self, path: str | None = None, data: dict | None = None):
        self.path = path
        self.data = json.loads(json.dumps(data or DEFAULT))
        for k, v in DEFAULT.items():
            self.data.setdefault(k, json.loads(json.dumps(v)))

    # -- files ------------------------------------------------------------------
    @classmethod
    def open(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as fh:
            return cls(path, json.load(fh))

    def save(self, path: str | None = None):
        self.path = path or self.path
        if not self.path:
            raise ValueError("No file name for this project yet")
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    @property
    def films(self) -> list[dict]:
        return self.data["films"]

    # -- editing ----------------------------------------------------------------
    def add_files(self, paths) -> list[dict]:
        added = []
        have = {os.path.normcase(os.path.abspath(f["file"])) for f in self.films}
        for p in paths:
            if os.path.isdir(p):
                inner = sorted(os.path.join(p, n) for n in os.listdir(p)
                               if os.path.splitext(n)[1].lower() in VIDEO_EXTS)
                added += self.add_files(inner)
                continue
            if os.path.splitext(p)[1].lower() not in VIDEO_EXTS:
                continue
            key = os.path.normcase(os.path.abspath(p))
            if key in have:
                continue
            title, year = guess_title_year(p)
            film = {"file": os.path.abspath(p), "title": title, "year": year, "place": ""}
            self.films.append(film)
            have.add(key)
            added.append(film)
        # keep films in release order when years are known and the user hasn't reordered
        if added and self.data.get("_auto_order", True):
            self.films.sort(key=lambda f: (f.get("year") or 9999))
        return added

    def update_film(self, index: int, fields: dict):
        allowed = {"title", "year", "place", "spinoff"}
        f = self.films[index]
        for k, v in fields.items():
            if k in allowed:
                if k == "year":
                    v = int(v) if str(v).strip().isdigit() else None
                f[k] = v
            elif k.startswith("x_"):          # theme-specific extra fields
                f[k[2:]] = v

    def move_film(self, src: int, dst: int):
        f = self.films.pop(src)
        self.films.insert(dst, f)
        self.data["_auto_order"] = False
        self.data["timeline_order"] = None

    def remove_film(self, index: int):
        self.films.pop(index)
        self.data["timeline_order"] = None

    def set(self, key: str, value):
        if key == "disc_size" and value not in DISC_SIZES:
            raise ValueError(f"Unknown disc size {value}")
        if key not in {"theme", "disc_label", "disc_size", "audio_kbps", "timeline_order", "build_dir"}:
            raise ValueError(f"Can't set {key}")
        if key == "disc_label":
            value = re.sub(r"[^A-Za-z0-9_ ]", "", str(value)).strip().replace(" ", "_").upper()[:32] or "COLLECTION"
        self.data[key] = value

    def set_option(self, key: str, value):
        self.data.setdefault("theme_options", {})[key] = value

    @property
    def build_dir(self) -> str:
        base = os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()
        return os.path.join(base, self.data.get("build_dir") or "build")
