"""The pure parts: names, settings, the disc budget, track recipes, subtitles,
versions. Nothing here needs FFmpeg."""
import json
import os
import types
from fractions import Fraction

import pytest

from boxset import budget, config, pipeline, probe, settings, subs, tracks, updates
from boxset.project import Project, guess_title_year
from conftest import make_media

GB = 1e9


# ------------------------------------------------------------------ file names
@pytest.mark.parametrize("name,want", [
    ("The Fast and the Furious (2001).mkv", ("The Fast and the Furious", 2001)),
    ("2.Fast.2.Furious.2003.1080p.BluRay.x264.mkv", ("2 Fast 2 Furious", 2003)),
    ("Blade Runner 2049 (2017) [2160p].mkv", ("Blade Runner 2049", 2017)),
    ("home movie.mp4", ("home movie", None)),
])
def test_guess_title_year(name, want):
    title, year = guess_title_year(os.path.join("rips", name))
    assert (title.lower(), year) == (want[0].lower(), want[1])


# ------------------------------------------------------------------ settings
def test_new_projects_get_the_new_defaults_and_old_ones_keep_their_behaviour():
    new = settings.fill(None)
    assert (new["audio_tracks"], new["subtitles"], new["keep_streams"]) == ("all", "all", True)
    old = settings.fill({"films": [], "disc_size": "BD-25"})
    assert (old["audio_tracks"], old["subtitles"], old["keep_streams"]) == ("first", "off", False)
    assert old["disc_size"] == "BD-25" and old["audio_kbps"] == 448
    assert settings.fill(None) is not settings.DEFAULT and new["films"] is not settings.DEFAULT["films"]


def test_settings_are_checked():
    assert settings.check("disc_size", "bd-50") == "BD-50"
    assert settings.check("disc_label", "fast & furious!") == "FAST__FURIOUS"
    assert settings.check("auto_chapters", "") == 0
    for key, bad in [("disc_size", "BD-9"), ("speed", "warp"), ("audio_tracks", "some"),
                     ("subtitles", "maybe"), ("films", [])]:
        with pytest.raises(ValueError):
            settings.check(key, bad)


def test_app_and_build_read_a_project_the_same_way(tmp_path):
    p = Project()
    p.films.append({"file": "a.mkv", "title": "A", "year": 2001, "place": ""})
    p.set("disc_size", "bd-25")
    p.set("speed", "fast")
    p.set("subtitles", "off")
    p.set_option("accent", "#00FF00")
    p.save(str(tmp_path / "p.boxset"))
    coll = config.load(str(tmp_path / "p.boxset"))
    for key in ("disc_size", "audio_kbps", "save_space", "speed", "auto_chapters", "audio_tracks",
                "subtitles", "keep_streams", "theme"):
        assert getattr(coll, key) == p.data[key], key
    assert coll.accent == "#00FF00" and coll.label == p.data["disc_label"]


def test_an_older_project_file_still_loads(tmp_path):
    path = tmp_path / "old.boxset"
    path.write_text(json.dumps({"theme": "tachometer", "disc_size": "BD-50",
                                "films": [{"file": "a.mkv", "title": "A"}]}), encoding="utf-8")
    coll = config.load(str(path))
    assert (coll.audio_tracks, coll.subtitles, coll.keep_streams, coll.speed) == ("first", "off", False, "quality")
    with pytest.raises(config.ConfigError):
        path.write_text(json.dumps({"disc_size": "BD-9", "films": [{"file": "a", "title": "A"}]}))
        config.load(str(path))


# ------------------------------------------------------------------ the disc budget
def test_video_limit_fills_the_disc_and_never_exceeds_blu_rays():
    eleven = [6600.0] * 11
    limit = budget.video_limit("BD-50", eleven, 448)
    p = budget.plan("BD-50", eleven, 448)
    assert p.video_kbps == limit and 4000 < limit < 6000
    assert p.estimated_bytes <= p.capacity
    assert budget.video_limit("BD-50", [6000.0], 448) == budget.MAX_VIDEO_KBPS
    assert budget.plan("BD-25", [6600.0] * 30, 448).warning


def test_more_sound_leaves_less_for_the_picture_and_is_counted():
    films = [6600.0] * 11
    one = budget.plan("BD-50", films, 448)
    three = budget.plan("BD-50", films, 448, film_audio=[448 + 192 + 448] * 11)
    assert three.video_kbps < one.video_kbps
    assert three.estimated_bytes <= three.capacity
    # a film known to need little is counted at what it needs, plus all its sound
    small = budget.plan("BD-50", [6000.0], 448, needs=[[2000.0]], film_audio=[448])
    more = budget.plan("BD-50", [6000.0], 448, needs=[[2000.0]], film_audio=[448 + 1509])
    assert more.film_bytes[0] - small.film_bytes[0] == pytest.approx(1509e3 / 8 * 6000 * (1 + budget.MUX_OVERHEAD), rel=.02)


# ------------------------------------------------------------------ recipes
def _st(**kw):
    base = dict(audio_kbps=448, audio_tracks="all", subtitles="all", keep_streams=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _three_tracks(**kw):
    return make_media(audio=[probe.AudioStream(1, "ac3", 6, "eng", 640.0),
                             probe.AudioStream(2, "aac", 2, "fre"),
                             probe.AudioStream(3, "dts", 6, "eng", 4200.0, "DTS-HD MA")],
                      subs=[probe.SubStream(0, "subrip", "eng"),
                            probe.SubStream(1, "hdmv_pgs_subtitle", "ger", 1920, 1080),
                            probe.SubStream(2, "dvd_subtitle", "spa"),
                            probe.SubStream(3, "hdmv_pgs_subtitle", "ita", 3840, 2160)], **kw)


def test_recipe_for_an_ordinary_film():
    r = tracks.recipe(_st(), _three_tracks(), 30000)
    assert not r.copy_video and r.tempo == 1.0 and r.fps == (24000, 1001)
    assert [(a.codec, a.channels, a.kbps, a.copy) for a in r.audio] == [
        ("ac3", 6, 640, True), ("ac3", 2, 192, False), ("ac3", 6, 448, False)]
    assert [s.language for s in r.subs] == ["eng", "ger"]


def test_recipe_respects_the_switches():
    r = tracks.recipe(_st(audio_tracks="first", subtitles="off", keep_streams=False), _three_tracks(), 30000)
    assert [(a.stream, a.codec, a.kbps, a.copy) for a in r.audio] == [(0, "ac3", 448, False)]
    assert r.subs == [] and not r.copy_video


def test_blu_ray_video_is_copied_only_when_it_fits():
    film = _three_tracks(bd_video=True, video_kbps=24000.0)
    r = tracks.recipe(_st(), film, 30000)
    assert r.copy_video and [(a.codec, a.kbps, a.copy) for a in r.audio][2] == ("dts", 1509, True)
    assert not tracks.recipe(_st(), film, 12000).copy_video           # the disc is too full for a copy
    assert not tracks.recipe(_st(keep_streams=False), film, 30000).copy_video
    slowed = _three_tracks(bd_video=True, video_kbps=24000.0, fps=Fraction(24, 1))
    assert not tracks.recipe(_st(), slowed, 30000).copy_video


def test_frame_rates_and_hdr(monkeypatch):
    monkeypatch.setattr(tracks, "tonemap_available", lambda: True)
    r = tracks.recipe(_st(), make_media(fps=Fraction(24, 1)), 30000)
    assert r.fps == (24000, 1001) and r.tempo == pytest.approx(1.001) and not r.audio[0].copy
    assert tracks.recipe(_st(), make_media(fps=Fraction(50, 1)), 30000).fps == (25, 1)
    assert tracks.recipe(_st(), make_media(fps=Fraction(60, 1)), 30000).fps == (30000, 1001)
    assert tracks.recipe(_st(), make_media(hdr="hdr10"), 30000).tonemap == "hdr10"
    assert tracks.recipe(_st(), make_media(hdr="dv"), 30000).tonemap == ""
    assert "setpts" in tracks.video_filter((24000, 1001), 1.001) and "tonemap" in tracks.video_filter((25, 1), 1.0, "hlg")
    monkeypatch.setattr(tracks, "tonemap_available", lambda: False)
    assert tracks.recipe(_st(), make_media(hdr="hdr10"), 30000).tonemap == ""


def test_films_from_earlier_versions_are_not_encoded_again(tmp_path):
    film = tmp_path / "a.mkv"
    film.write_bytes(b"x")
    m = make_media(film)
    coll = types.SimpleNamespace(audio_kbps=448, audio_tracks="first", subtitles="off", keep_streams=False)
    plan = types.SimpleNamespace(video_kbps=20000)
    enc = {"encoder": "x264", "preset": "medium", "crf": 19}
    before = pipeline._clip_settings(coll, m, plan, enc)
    assert pipeline._clip_settings(coll, m, plan, enc, tracks.recipe(coll, m, 20000)) == before
    coll.audio_tracks, coll.subtitles = "all", "all"
    m.audio.append(probe.AudioStream(2, "aac", 2, "fre"))
    after = pipeline._clip_settings(coll, m, plan, enc, tracks.recipe(coll, m, 20000))
    assert after != before and after["tracks"] == [[0, "ac3", 6], [1, "ac3", 2]]


# ------------------------------------------------------------------ subtitles
SRT = """1
00:00:01,000 --> 00:00:03,500
<i>Hello</i> there
General Kenobi

2
00:00:04,000 --> 00:00:05,000
{\\an8}Up top

3
00:00:06,000 --> 00:00:07,000
1999
"""


def test_parse_srt():
    cues = subs.parse_srt(SRT.replace("\n", "\r\n"))
    assert [(c.start, c.end, c.text, c.top) for c in cues] == [
        (1.0, 3.5, "Hello there\nGeneral Kenobi", False), (4.0, 5.0, "Up top", True), (6.0, 7.0, "1999", False)]
    assert subs.parse_srt("") == [] and subs.parse_srt("not subtitles") == []


def test_subtitles_are_drawn_into_pgs(tmp_path):
    from bdmvkit import pgs
    out = tmp_path / "a.sup"
    cues = subs.parse_srt(SRT)
    assert subs.write_sup(cues, str(out), tempo=1.001) == 3
    shown = [(pts / 90000, objs) for pts, objs, _ in pgs.decode(out.read_bytes()) if objs]
    assert [round(t, 3) for t, _ in shown] == [1.001, 4.004, 6.006]
    (x, y, w, h, _), = shown[0][1]
    assert y > 700 and x + w <= 1920 and y + h <= 1080 and abs((x + w / 2) - 960) < 12   # bottom, centred
    assert shown[1][1][0][1] < 200                                                     # {\an8}: top


def test_scripts_that_need_shaping_are_left_out():
    assert subs.drawable([subs.Cue(0, 1, "Привет, мир")])
    assert not subs.drawable([subs.Cue(0, 1, "مرحبا")])
    m = _three_tracks()
    assert [s.language for s in subs.usable(m)] == ["eng", "ger"]
    assert len(subs.skipped(m)) == 2


def test_language_codes_and_subtitle_files_beside_a_film(tmp_path):
    assert [probe.language(t) for t in ("en", "fra", "deu", "ENG", "pt-BR", "", None, "xx1")] == [
        "eng", "fre", "ger", "eng", "por", "und", "und", "und"]
    film = tmp_path / "Heat (1995).mkv"
    for name in ("Heat (1995).srt", "Heat (1995).es.srt", "Heat (1995).en.forced.srt",
                 "Heat (1995) 2.srt", "Other.srt", "Heat (1995).txt"):
        (tmp_path / name).write_text("x")
    found = probe.subtitle_files(str(film))
    assert sorted((s.language, s.forced) for s in found) == [("eng", True), ("spa", False), ("und", False)]


def test_h264_settings_first():
    start = b"\x00\x00\x01"
    def frame(*kinds):
        return b"".join(start + bytes([k]) + b"\xff" for k in kinds)
    assert probe._settings_first(frame(9, 7, 8, 6, 5))
    assert probe._settings_first(frame(7, 8, 5))
    assert not probe._settings_first(frame(9, 6, 7, 8, 5))
    assert not probe._settings_first(frame(9, 6, 5))


# ------------------------------------------------------------------ updates
def test_version_comparison():
    assert updates.newer("v0.2.0", "0.1.9") and updates.newer("1.0", "0.9.9")
    assert not updates.newer("v0.1.7", "0.1.7") and not updates.newer("v0.1.6", "0.1.7")
    assert not updates.newer("v2.0.0-beta", "0.1.0") and not updates.newer("v9.9.9", "0.0.0-dev")


def test_update_check_never_raises_and_only_links_to_the_project():
    rel = {"tag_name": "v0.3.0", "html_url": "https://github.com/RamenNuudlss/Boxset/releases/tag/v0.3.0"}
    assert updates.check("0.2.0", fetch=lambda: rel) == {"version": "0.3.0", "url": rel["html_url"]}
    assert updates.check("0.3.0", fetch=lambda: rel) is None
    assert updates.check("0.0.0", fetch=lambda: rel) is None                 # running from source
    assert updates.check("0.2.0", fetch=lambda: dict(rel, prerelease=True)) is None
    assert updates.check("0.2.0", fetch=lambda: dict(rel, html_url="https://evil.example/x"))["url"] == updates.RELEASES_PAGE

    def broken():
        raise OSError("no network")
    assert updates.check("0.2.0", fetch=broken) is None
    assert updates.check("0.2.0", fetch=lambda: ["nonsense"]) is None
