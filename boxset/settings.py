"""The settings of a project file (*.boxset), in one place.

The app (project.py) and the build (config.py) both read project files; they get
their defaults and their checks from here, so the two can't drift apart.
"""
from __future__ import annotations

import copy
import re

DISC_SIZES = {  # usable bytes per disc type
    "BD-25": 25_025_314_816,
    "BD-50": 50_050_629_632,
    "BD-100": 100_103_356_416,
}

SPEEDS = ("quality", "fast", "gpu")
AUDIO_TRACKS = ("all", "first")
SUBTITLES = ("all", "off")

# A new project starts with these.
DEFAULT = {
    "theme": "tachometer",
    "theme_options": {},
    "disc_label": "MY_COLLECTION",
    "disc_size": "BD-50",
    "audio_kbps": 448,
    "save_space": False,
    "speed": "quality",
    "auto_chapters": 5,          # minutes between added chapters for films with none (0 = off)
    "audio_tracks": "all",       # every sound track of a film, or only its first
    "subtitles": "all",          # every subtitle track Boxset can carry, or none
    "keep_streams": True,        # copy picture and sound that are already Blu-ray's, don't re-encode
    "timeline_order": None,
    "build_dir": "build",
    "films": [],
}

# What a project file saved before a setting existed gets for it: the way Boxset
# behaved then, so opening an old project never re-encodes its films by surprise.
LEGACY = {
    "disc_label": "COLLECTION",
    "audio_tracks": "first",
    "subtitles": "off",
    "keep_streams": False,
}

SETTABLE = {"theme", "disc_label", "disc_size", "audio_kbps", "timeline_order", "build_dir", "save_space",
            "speed", "auto_chapters", "audio_tracks", "subtitles", "keep_streams"}


def label(value) -> str:
    """A disc label: capitals, digits and underscores, 32 at most."""
    return re.sub(r"[^A-Za-z0-9_ ]", "", str(value)).strip().replace(" ", "_").upper()[:32] or "COLLECTION"


def check(key: str, value):
    """`value` as setting `key` holds it. Raises ValueError for a value it can't hold."""
    if key not in SETTABLE:
        raise ValueError(f"Can't set {key}")
    if key == "disc_size":
        value = str(value).upper()
        if value not in DISC_SIZES:
            raise ValueError(f"Unknown disc size {value}")
    elif key in ("save_space", "keep_streams"):
        value = bool(value)
    elif key == "auto_chapters":
        value = int(value or 0)
    elif key == "audio_kbps":
        value = int(value)
    elif key == "speed" and value not in SPEEDS:
        raise ValueError(f"Unknown speed {value}")
    elif key == "audio_tracks" and value not in AUDIO_TRACKS:
        raise ValueError(f"audio_tracks is \"all\" or \"first\", not {value}")
    elif key == "subtitles" and value not in SUBTITLES:
        raise ValueError(f"subtitles is \"all\" or \"off\", not {value}")
    elif key == "disc_label":
        value = label(value)
    return value


def fill(data: dict | None) -> dict:
    """A project's data with every setting present: a copy of `data` with the
    missing ones filled in (None: a brand-new project)."""
    if data is None:
        return copy.deepcopy(DEFAULT)
    out = copy.deepcopy(data)
    for key, value in DEFAULT.items():
        if key not in out:
            out[key] = copy.deepcopy(LEGACY.get(key, value))
    return out
