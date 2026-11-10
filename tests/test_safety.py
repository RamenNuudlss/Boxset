"""Checks for the safety and robustness fixes. Run with:  python -m pytest tests

None of these need FFmpeg, a browser or a disc drive.
"""
import http.client
import json
import os
import threading

import pytest

from boxset import core, pipeline, probe
from boxset.gui import server
from boxset.project import Project


from conftest import make_media as _media


class _Coll:
    def __init__(self, base):
        self.base_dir = str(base)


# ------------------------------------------------------------------ project themes
def _project_with_theme(tmp_path):
    marker = tmp_path / "ran.txt"
    tdir = tmp_path / "proj" / "themes" / "sneaky"
    tdir.mkdir(parents=True)
    (tdir / "theme.py").write_text(
        f"open({str(marker)!r}, 'w').close()\n"
        "from boxset.core import BaseTheme\n"
        "class Theme(BaseTheme):\n    name = 'Sneaky'\n", encoding="utf-8")
    return _Coll(tmp_path / "proj"), marker


def test_project_themes_do_not_run_until_allowed(tmp_path):
    coll, marker = _project_with_theme(tmp_path)
    core.restrict_project_themes([])
    assert "sneaky" not in core.list_themes(coll)
    assert all(t["id"] != "sneaky" for t in core.theme_catalog(coll))
    assert core.untrusted_project_themes(coll) == ["sneaky"]
    assert not marker.exists()
    with pytest.raises(RuntimeError, match="hasn't been allowed"):
        core.load_theme(coll, "sneaky", {})
    assert not marker.exists()


def test_project_themes_load_once_allowed(tmp_path):
    coll, marker = _project_with_theme(tmp_path)
    core.restrict_project_themes([coll.base_dir])
    assert core.untrusted_project_themes(coll) == []
    assert any(t["id"] == "sneaky" and t["source"] == "project" for t in core.theme_catalog(coll))
    assert marker.exists()


def test_command_line_is_not_restricted(tmp_path):
    coll, _ = _project_with_theme(tmp_path)
    core.restrict_project_themes(None)
    assert "sneaky" in core.list_themes(coll)


# ------------------------------------------------------------------ probe cache
def test_media_round_trips_through_json():
    m = _media("film.mkv", problems=["a warning"])
    again = probe.from_dict(json.loads(json.dumps(probe.to_dict(m))))
    from fractions import Fraction
    assert again == m and isinstance(again.fps, Fraction)


def test_probe_cache_is_json_and_reused(tmp_path, monkeypatch):
    film = tmp_path / "film.mkv"
    film.write_bytes(b"x" * 10)
    calls = []
    monkeypatch.setattr(probe, "probe", lambda p: calls.append(p) or _media(p))

    class Film:
        number, file, title = 1, str(film), "Film"

    class C:
        build = str(tmp_path / "build")
        films = [Film]
        auto_chapters = 0

        @staticmethod
        def resolve(p):
            return p

    os.makedirs(C.build)
    old = os.path.join(C.build, "probe3.cache")
    open(old, "wb").close()
    media, problems = pipeline.load_media(C)
    assert not problems and media[1].duration == 6000.0
    assert not os.path.exists(old)
    with open(os.path.join(C.build, "probe.json"), encoding="utf-8") as fh:
        assert len(json.load(fh)["files"]) == 1
    media, _ = pipeline.load_media(C)
    assert len(calls) == 1 and media[1] == _media(film)
    # a cache from some other version is ignored, not trusted
    cache_p = os.path.join(C.build, "probe.json")
    with open(cache_p, encoding="utf-8") as fh:
        saved = json.load(fh)
    saved["files"] = {k: {"nonsense": 1} for k in saved["files"]}
    with open(cache_p, "w", encoding="utf-8") as fh:
        json.dump(saved, fh)
    pipeline.load_media(C)
    assert len(calls) == 2


# ------------------------------------------------------------------ film fields
def test_theme_fields_cannot_replace_a_films_own():
    p = Project()
    p.films.append({"file": "a.mkv", "title": "A", "year": 2001, "place": ""})
    p.update_film(0, {"x_file": "b.mkv", "x_title": "B", "x_crew": "Dom", "title": "C"})
    assert p.films[0] == {"file": "a.mkv", "title": "C", "year": 2001, "place": "", "crew": "Dom"}


# ------------------------------------------------------------------ file serving
@pytest.mark.parametrize("header,want", [
    ("bytes=0-99", (0, 99)), ("bytes=10-", (10, 999)), ("bytes=-100", (900, 999)),
    ("bytes=990-5000", (990, 999)), ("bytes=-5000", (0, 999)),
    ("bytes=1000-", False), ("bytes=50-10", False), ("bytes=-0", False),
    ("bytes=abc-", None), ("bytes=-", None), ("bytes=0-1,5-9", None), ("items=0-1", None),
])
def test_byte_range(header, want):
    assert server._byte_range(header, 1000) == want


def test_file_requests_survive_bad_ranges(tmp_path):
    root = tmp_path / "build"
    root.mkdir()
    (root / "a.bin").write_bytes(bytes(range(200)))

    class Api:
        @staticmethod
        def allowed_roots():
            return [str(root)]

    api = Api()
    httpd, port, token = server.make_server(api)
    try:
        def get(rng=None, name="a.bin"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", api.file_url(str(root / name)), headers={"Range": rng} if rng else {})
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status, body
        assert get() == (200, bytes(range(200)))
        assert get("bytes=10-19") == (206, bytes(range(10, 20)))
        assert get("bytes=-5") == (206, bytes(range(195, 200)))
        assert get("bytes=nope-")[0] == 200
        assert get("bytes=500-")[0] == 416
        assert get(name="../secret.txt")[0] == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


# ------------------------------------------------------------------ disc space
def _space_case(tmp_path, monkeypatch, free_gb):
    class Film:
        number, title = 1, "Film"

    class C:
        build = str(tmp_path)
        films = [Film]
        disc_size, audio_kbps, save_space = "BD-25", 448, False
        audio_tracks, subtitles, keep_streams = "first", "off", False

    class Usage:
        free = int(free_gb * 1e9)

    monkeypatch.setattr(pipeline.shutil, "disk_usage", lambda p: Usage)
    logs = []
    job = pipeline.Job(logs.append)
    media = {1: _media(tmp_path / "film.mkv")}
    need = pipeline.space_needed(C, media, make_iso=True)
    return C, media, job, logs, need


def test_space_check_stops_a_build_that_cannot_fit(tmp_path, monkeypatch):
    C, media, job, logs, need = _space_case(tmp_path, monkeypatch, 1)
    assert need > 5e9
    with pytest.raises(RuntimeError, match="free space"):
        pipeline.check_space(C, media, job, make_iso=True)


def test_space_check_warns_when_tight_and_is_quiet_when_roomy(tmp_path, monkeypatch):
    C, media, job, logs, need = _space_case(tmp_path, monkeypatch, 0)
    monkeypatch.setattr(pipeline.shutil, "disk_usage", lambda p: type("U", (), {"free": int(need * 0.8)}))
    pipeline.check_space(C, media, job, make_iso=True)
    assert [e["level"] for e in logs] == ["warn"]
    monkeypatch.setattr(pipeline.shutil, "disk_usage", lambda p: type("U", (), {"free": int(need * 2)}))
    pipeline.check_space(C, media, job, make_iso=True)
    assert len(logs) == 1


# ------------------------------------------------------------------ the app's state
def test_edits_from_many_threads_keep_the_project_intact(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from boxset.gui.api import Api
    api = Api()
    api.file_url = lambda p: p
    films = []
    for i in range(6):
        f = tmp_path / f"Film {i} (200{i}).mkv"
        f.write_bytes(b"")
        films.append(str(f))
    api.add_paths(films)
    errors = []

    def edit(n):
        try:
            for i in range(40):
                api.update_film(i % 6, {"title": f"T{n}-{i}"})
                api.set_option(f"opt{n}", i)
                api.state()
        except Exception as e:      # any failure here is the bug
            errors.append(e)

    threads = [threading.Thread(target=edit, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    api._stop_measuring.set()
    assert not errors
    with open(api.project.path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved == api.project.data and len(saved["films"]) == 6
    # a project the app made itself is trusted with its own themes folder
    assert api.state()["untrusted_themes"] == []
