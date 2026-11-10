"""Shared pieces for the tests. Run them with:  python -m pytest tests"""
import os
import shutil
import subprocess
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from boxset import core, probe  # noqa: E402

collect_ignore = ["libbluray_nav.py"]          # a manual script, not a test


@pytest.fixture(autouse=True)
def _own_settings(tmp_path, monkeypatch):
    """Keep settings, caches and installed themes away from the real user folder,
    and never call GitHub from a test."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("BOXSET_NO_UPDATE_CHECK", "1")
    yield
    core.restrict_project_themes(None)


def make_media(path="film.mkv", **kw):
    """A probe.Media as a 100-minute 1080p film with 5.1 Dolby Digital sound."""
    base = dict(path=str(path), duration=6000.0, fps=Fraction(24000, 1001), width=1920, height=1080,
                chapters=[0.0, 600.0], audio=[probe.AudioStream(1, "ac3", 6, "eng", 448.0)],
                vcodec="h264", video_kbps=8000.0)
    base.update(kw)
    return probe.Media(**base)


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


needs_ffmpeg = pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg isn't installed")


def ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", *map(str, args)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]


def has_encoder(name: str) -> bool:
    if not have_ffmpeg():
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return any(len(ln.split()) > 1 and ln.split()[1] == name for ln in out.splitlines())


def streams(path) -> list[dict]:
    """A file's streams as ffprobe sees them."""
    import json
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-500:]
    return json.loads(out.stdout)["streams"]
