"""Loads and checks a project file (*.boxset)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

DISC_SIZES = {  # usable bytes per disc type
    "BD-25": 25_025_314_816,
    "BD-50": 50_050_629_632,
    "BD-100": 100_103_356_416,
}


@dataclass
class Film:
    number: int
    file: str
    title: str
    year: int | None = None
    place: str = ""
    spinoff: bool = False


@dataclass
class Collection:
    path: str
    title_small: str
    title_big: str
    label: str
    accent: str
    disc_size: str
    audio_kbps: int
    audio_channels: int
    films: list[Film]
    timeline_order: list[int] | None
    chapters_per_page: int = 8
    scene_selection: bool = True
    build_dir: str = "build"
    extra: dict = field(default_factory=dict)

    @property
    def base_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.path))

    def resolve(self, p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(self.base_dir, p)

    @property
    def build(self) -> str:
        return self.resolve(self.build_dir)

    @property
    def years(self) -> tuple[int, int] | None:
        ys = [f.year for f in self.films if f.year]
        return (min(ys), max(ys)) if ys else None


class ConfigError(Exception):
    pass


def load(path: str) -> Collection:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"Can't find {path}. Make a project in the Boxset app, then pass its .boxset file.")
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} isn't valid JSON (line {e.lineno}): {e.msg}")

    films_raw = raw.get("films") or []
    if not films_raw:
        raise ConfigError("The project has no films yet.")
    films = []
    for i, f in enumerate(films_raw, 1):
        if "file" not in f or "title" not in f:
            raise ConfigError(f"Film #{i} needs both a \"file\" and a \"title\".")
        films.append(Film(number=i, file=f["file"], title=f["title"], year=f.get("year"),
                          place=f.get("place", ""), spinoff=bool(f.get("spinoff", False))))

    size = raw.get("disc_size", "BD-50").upper()
    if size not in DISC_SIZES:
        raise ConfigError(f"disc_size must be one of {', '.join(DISC_SIZES)} (got {size}).")

    order = raw.get("timeline_order")
    if order is not None:
        if sorted(order) != list(range(1, len(films) + 1)):
            raise ConfigError(f"timeline_order must list each film number 1-{len(films)} exactly once.")

    opts = raw.get("theme_options") or {}
    if not isinstance(opts, dict):
        raise ConfigError("theme_options must be an object, e.g. {\"accent\": \"#FF6B1A\"}.")
    # older top-level settings still work as theme options
    for k in ("title_small", "title_big", "accent", "scene_selection"):
        if k in raw and k not in opts:
            opts[k] = raw[k]

    c = Collection(
        path=path,
        title_small=opts.get("title_small", "THE COMPLETE"),
        title_big=opts.get("title_big", "COLLECTION"),
        label=raw.get("disc_label", "COLLECTION")[:32],
        accent=opts.get("accent", "#FF6B1A"),
        disc_size=size,
        audio_kbps=int(raw.get("audio_kbps", 448)),
        audio_channels=int(raw.get("audio_channels", 6)),
        films=films,
        timeline_order=order,
        scene_selection=bool(opts.get("scene_selection", True)),
        build_dir=raw.get("build_dir", "build"),
        extra=raw,
    )
    c.theme = raw.get("theme", "tachometer")
    c.theme_options = opts
    return c
