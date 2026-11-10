"""Real encodes of a few seconds of generated video, to check that what FFmpeg
writes is what the disc's playlists will claim. Skipped where FFmpeg is missing."""
import types

import pytest

from boxset import pipeline, probe, tracks
from conftest import ffmpeg, has_encoder, needs_ffmpeg, streams

pytestmark = needs_ffmpeg

SRT = "1\n00:00:01,000 --> 00:00:03,000\nHello there\n\n2\n00:00:04,000 --> 00:00:05,000\nSecond\n"
FAST = {"encoder": "x264", "preset": "ultrafast", "crf": 30}


def _settings(**kw):
    base = dict(audio_kbps=448, audio_tracks="all", subtitles="all", keep_streams=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _encode(tmp_path, media, coll, limit=30000, enc=FAST):
    logs = []
    job = pipeline.Job(logs.append)
    film = types.SimpleNamespace(number=1, title="Test")
    recipe = tracks.recipe(coll, media, limit)
    if recipe.copy_video:
        enc = {"encoder": "copy"}
    sub_inputs = pipeline.prepare_subs(job, film, media, recipe, str(tmp_path / "subs"))
    out = tmp_path / "out.m2ts"
    pipeline.encode_film(job, coll, film, media, types.SimpleNamespace(video_kbps=limit), str(out), enc,
                         lambda *a: None, recipe, sub_inputs)
    return out, recipe, pipeline.made_tracks(recipe, sub_inputs), logs


def _by_id(path):
    return {int(s["id"], 16): s for s in streams(path)}


def test_every_track_lands_where_the_disc_expects_it(tmp_path):
    (tmp_path / "a.srt").write_text(SRT, encoding="utf-8")
    src = tmp_path / "Film (2001).mkv"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=24000/1001", "-f", "lavfi", "-i", "sine=f=440:r=48000",
           "-f", "lavfi", "-i", "sine=f=660:r=44100", "-i", tmp_path / "a.srt", "-t", "6",
           "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a:0", "ac3", "-ac:a:0", "6", "-b:a:0", "448k",
           "-c:a:1", "aac", "-c:s", "srt", "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=fra",
           "-metadata:s:s:0", "language=eng", src)
    (tmp_path / "Film (2001).es.srt").write_text(SRT, encoding="utf-8")

    m = probe.probe(str(src))
    assert [(a.codec, a.language) for a in m.audio] == [("ac3", "eng"), ("aac", "fre")]
    assert [(s.kind, s.language) for s in m.subs] == [("text", "eng"), ("text", "spa")]
    assert not m.bd_video and not m.fatal

    out, recipe, made, _ = _encode(tmp_path, m, _settings())
    assert [a.copy for a in recipe.audio] == [True, False]
    assert made == {"audio": [["ac3", 6, "eng"], ["ac3", 2, "fre"]], "subs": ["eng", "spa"]}
    got = _by_id(out)
    assert sorted(got) == [0x1011, 0x1100, 0x1101, 0x1200, 0x1201]
    v = got[0x1011]
    assert (v["codec_name"], v["width"], v["height"], v["r_frame_rate"]) == ("h264", 1920, 1080, "24000/1001")
    assert [(got[i]["codec_name"], got[i]["channels"]) for i in (0x1100, 0x1101)] == [("ac3", 6), ("ac3", 2)]
    assert all(got[i]["codec_name"] == "hdmv_pgs_subtitle" for i in (0x1200, 0x1201))
    # the clip is what bdmvkit will accept for a title with these tracks
    from bdmvkit.m2ts import stream_pids
    assert stream_pids(str(out)) == {0x1011: 0x1B, 0x1100: 0x81, 0x1101: 0x81, 0x1200: 0x90, 0x1201: 0x90}

    # the old behaviour, for projects made before these settings existed
    out, recipe, made, _ = _encode(tmp_path, m, _settings(audio_tracks="first", subtitles="off", keep_streams=False))
    assert sorted(_by_id(out)) == [0x1011, 0x1100] and made == {"audio": [["ac3", 6, "eng"]], "subs": []}


def test_24_fps_is_slowed_not_thinned(tmp_path):
    src = tmp_path / "f.mkv"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=24", "-f", "lavfi", "-i", "sine=f=440:r=48000",
           "-t", "10", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", src)
    m = probe.probe(str(src))
    assert m.tempo == pytest.approx(1.001) and any("0.1% slower" in p for p in m.problems)
    out, recipe, _, _ = _encode(tmp_path, m, _settings())
    got = _by_id(out)
    v = got[0x1011]
    assert v["r_frame_rate"] == "24000/1001"
    frames = int(streams_count(out))
    assert abs(frames - 240) <= 2                      # every source frame kept
    assert float(v["duration"]) == pytest.approx(10.01, abs=0.1)
    assert float(got[0x1100]["duration"]) == pytest.approx(10.01, abs=0.15)


def streams_count(path):
    import subprocess
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout
    return out.split()[0].split(",")[0]      # an .m2ts lists its one programme twice


def test_50_fps_becomes_25(tmp_path):
    src = tmp_path / "f.mkv"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=50", "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", src)
    m = probe.probe(str(src))
    assert not m.fatal and not m.audio
    out, recipe, made, _ = _encode(tmp_path, m, _settings())
    got = _by_id(out)
    assert recipe.fps == (25, 1) and got[0x1011]["r_frame_rate"] in ("25/1", "50/1")
    assert got[0x1100]["codec_name"] == "ac3" and made["audio"] == [["ac3", 2, "und"]]   # silence


@pytest.mark.skipif(not has_encoder("libx265"), reason="this FFmpeg can't make an HDR test film")
def test_hdr_is_converted_to_sdr(tmp_path):
    if not tracks.tonemap_available():
        pytest.skip("this FFmpeg has no zscale filter")
    src = tmp_path / "hdr.mkv"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=24000/1001", "-t", "3", "-c:v", "libx265", "-preset",
           "ultrafast", "-pix_fmt", "yuv420p10le", "-x265-params",
           "log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
           "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc", src)
    m = probe.probe(str(src))
    assert m.hdr == "hdr10" and any("HDR" in p for p in m.problems)
    out, recipe, _, _ = _encode(tmp_path, m, _settings())
    v = _by_id(out)[0x1011]
    assert recipe.tonemap == "hdr10" and v["pix_fmt"] == "yuv420p" and v.get("color_transfer") == "bt709"


def test_blu_ray_video_is_copied_bit_for_bit(tmp_path):
    """A film laid out like a Blu-ray rip (H.264 High 4.1, a key frame a second,
    its settings ahead of each key frame) is copied; a re-encode of it isn't."""
    import hashlib
    import subprocess
    ts = tmp_path / "v.ts"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=24000/1001", "-t", "62", "-c:v", "libx264",
           "-preset", "veryfast", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
           "-b:v", "3M", "-maxrate", "6M", "-bufsize", "6M",
           "-x264-params", "bluray-compat=1:keyint=24:min-keyint=1:slices=4:aud=1:nal-hrd=vbr", "-f", "mpegts", ts)
    src = tmp_path / "rip.mkv"
    ffmpeg("-i", ts, "-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", "62", "-map", "0:v", "-map", "1:a",
           "-c:v", "copy", "-c:a", "dca", "-strict", "-2", "-ac", "6", "-b:a", "1509k", src)
    m = probe.probe(str(src))
    assert m.bd_video
    out, recipe, made, _ = _encode(tmp_path, m, _settings())
    assert recipe.copy_video and made["audio"] == [["dts", 6, "und"]]
    got = _by_id(out)
    assert got[0x1100]["codec_name"] == "dts"

    def video_md5(path):
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy",
                            "-bsf:v", "h264_mp4toannexb", "-f", "md5", "-"], capture_output=True, text=True)
        return hashlib.md5(r.stdout.encode()).hexdigest(), r.stdout
    assert video_md5(out)[1] == video_md5(ts)[1]

    # the same picture from an ordinary encoder keeps its key frames far apart: not copied
    web = tmp_path / "web.mkv"
    ffmpeg("-i", ts, "-t", "62", "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "-g", "250", web)
    assert not probe.probe(str(web)).bd_video
