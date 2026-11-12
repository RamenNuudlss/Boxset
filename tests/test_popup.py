"""In-film pop-ups: the theme API, the checks, and the stream that carries them."""
import subprocess
import types

import pytest
from PIL import Image

from boxset import popup
from boxset.core import Chapter, FilmInfo, act
from boxset.probe import timecode
from conftest import ffmpeg, needs_ffmpeg, streams


def _film(duration=600.0, chapters=(0, 150, 300, 450)):
    return FilmInfo(1, "Film", 2001, "", False, "film.mkv", duration,
                    [Chapter(i + 1, float(t), timecode(t), None) for i, t in enumerate(chapters)], {})


def _tile(w, h, colour):
    return Image.new("RGBA", (w, h), colour)


def _popup(film=None, every=60, moments=None):
    film = film or _film()
    pop = popup.Popup(film)
    for t in (moments or pop.moments(every)):
        fr = pop.frame(t)
        done = int(800 * t / film.duration)
        bar = _tile(800, 30, (20, 20, 20, 255))
        bar.paste((0, 200, 255, 255), (0, 0, max(1, done), 30))
        fr.label("bar", 100, 900, bar)
        for c in film.chapters:
            fr.button(f"c{c.number}", 100 + (c.number - 1) * 120, 950,
                      {"normal": _tile(100, 40, (60, 60, 60, 255)), "selected": _tile(100, 40, (255, 120, 0, 255))},
                      act.chapter(1, c.number))
        fr.button("resume", 1500, 950, {"normal": _tile(100, 40, (60, 60, 60, 255)),
                                        "selected": _tile(100, 40, (255, 120, 0, 255))}, act.close())
        fr.chain([f"c{c.number}" for c in film.chapters] + ["resume"])
        fr.default = "resume"
    return pop


def _ctx(pop):
    return types.SimpleNamespace(popups={pop.film.number: pop})


# ------------------------------------------------------------------ the theme's side
def test_moments_cover_every_minute_and_every_chapter():
    pop = popup.Popup(_film(600, (0, 150, 301, 450)))
    times = pop.moments(60)
    assert times[0] == 0 and times == sorted(times)
    assert {150.0, 301.0, 450.0} <= set(times)
    assert 300.0 not in times                       # too close to the chapter at 301: the chapter wins
    assert all(b - a >= popup.MIN_FRAME_GAP for a, b in zip(times, times[1:]))
    assert pop.chapter_at(0).number == 1 and pop.chapter_at(299).number == 2 and pop.chapter_at(301).number == 3


def test_a_sound_popup_passes_the_checks():
    assert popup.validate(_ctx(_popup()), lambda a: None) == []


def test_checks_catch_what_a_player_would_choke_on():
    def errors(change):
        pop = _popup()
        change(pop)
        return " | ".join(popup.validate(_ctx(pop), lambda a: "nowhere" if a == "menu:gone" else None))

    def overlap(pop):
        pop.frames[2].get("c2").x = 150
    assert "overlap" in errors(overlap)

    def off_screen(pop):
        pop.frames[0].get("resume").x = 1900
    assert "runs off" in errors(off_screen)

    def different(pop):
        pop.frames[3].buttons.pop()
    assert "same buttons" in errors(different)

    def label_default(pop):
        pop.frames[0].default = "bar"
    assert "isn't a selectable button" in errors(label_default)

    def bad_nav(pop):
        pop.frames[0].get("c1").nav["left"] = "bar"
    assert "isn't a selectable button here" in errors(bad_nav)

    def bad_action(pop):
        for fr in pop.frames:
            fr.get("resume").action = "menu:gone"
    assert "nowhere" in errors(bad_action)

    def not_for_popups(pop):
        for fr in pop.frames:
            fr.get("resume").action = "lastmenu"
    assert "can't do" in errors(not_for_popups)

    def out_of_order(pop):
        pop.frames.reverse()
    assert "time order" in errors(out_of_order)


# ------------------------------------------------------------------ saving
def test_pictures_are_stored_once_and_come_back(tmp_path):
    pop = _popup()
    saved = popup.save(pop, str(tmp_path), "film01")
    data = popup.load(str(tmp_path / "film01.json"))
    assert saved["frames"] == len(pop.frames) == len(data["frames"])
    # two button looks, and one bar per frame: nothing is stored twice
    assert len(data["tiles"]) == 2 + len(pop.frames)
    assert len(data["palette"]) <= 255 and all(len(c) == 4 for c in data["palette"])
    assert [b["id"] for b in data["frames"][0]["buttons"]] == ["bar", "c1", "c2", "c3", "c4", "resume"]


def test_display_sets_are_well_formed(tmp_path):
    pop = _popup()
    popup.save(pop, str(tmp_path), "film01")
    data = popup.load(str(tmp_path / "film01.json"))
    sets = list(popup.schedule(data, {"resume": [bytes(12)]}, 1, 1.0, 600.0))
    times = [t for t, _ in sets]
    assert times == sorted(times) and times[0] == 0
    assert len(sets) > len(pop.frames)                           # frames are repeated in between
    kinds = [seg[0] for seg in sets[0][1]]
    assert kinds[0] == popup.ICS and kinds[1] == popup.PDS and kinds[-1] == popup.END
    assert set(kinds[2:-1]) == {popup.ODS}
    for _, segs in sets:
        for seg in segs:
            assert int.from_bytes(seg[1:3], "big") == len(seg) - 3 and len(seg) <= popup.MAX_SEGMENT + 3
    states = [segs[0][10] for _, segs in sets]                   # composition state of each
    assert states[0] == popup.EPOCH_START and popup.ACQUISITION_POINT in states
    assert states.count(popup.EPOCH_START) == len(pop.frames)


def test_segments_become_whole_packets():
    p = popup._Packets(0x1400)
    for size in (0, 1, 150, 170, 171, 172, 173, 181, 182, 183, 184, 185, 366, 5000):
        seg = bytes([popup.ODS]) + size.to_bytes(2, "big") + bytes(size)
        out = p.pes(seg, 90000 * 5, b"\x00\x00\x00\x01")
        assert len(out) % 192 == 0, size
        payload = b""
        for i in range(0, len(out), 192):
            pkt = out[i + 4:i + 192]
            assert pkt[0] == 0x47 and (pkt[1] & 0x1F) << 8 | pkt[2] == 0x1400
            assert bool(pkt[1] & 0x40) == (i == 0)
            q = 4
            if pkt[3] & 0x20:
                q += 1 + pkt[4]
            payload += pkt[q:]
        assert payload[:4] == b"\x00\x00\x01\xbd" and int.from_bytes(payload[4:6], "big") == len(payload) - 6
        assert payload[14:] == seg and popup._read_pts(payload, 9) == 450000
    # the packets count up without a gap
    out = p.pes(bytes([popup.END, 0, 0]), 0, bytes(4)) + p.pes(bytes([popup.END, 0, 0]), 0, bytes(4))
    assert (out[7] & 0x0F, out[192 + 7] & 0x0F) == ((out[7] & 0x0F), ((out[7] & 0x0F) + 1) & 0x0F)


# ------------------------------------------------------------------ into a real clip
@needs_ffmpeg
def test_popup_goes_into_a_clip_at_the_right_moments(tmp_path):
    from bdmvkit.m2ts import scan_m2ts, stream_pids
    clip = tmp_path / "clip.m2ts"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=24000/1001", "-f", "lavfi", "-i", "sine=f=440:r=48000",
           "-t", "40", "-c:v", "libx264", "-preset", "ultrafast", "-g", "24", "-keyint_min", "24", "-sc_threshold", "0",
           "-c:a", "ac3", "-streamid", "0:4113", "-streamid", "1:4352",
           "-f", "mpegts", "-mpegts_m2ts_mode", "1", "-mpegts_pmt_start_pid", "256", clip)
    pop = _popup(_film(40.0, (0, 10, 20, 30)), moments=[0, 5, 10, 15, 20, 25, 30, 35])
    popup.save(pop, str(tmp_path), "film01")
    data = popup.load(str(tmp_path / "film01.json"))
    out = tmp_path / "out.m2ts"
    scan = scan_m2ts(str(clip))
    n = popup.insert(str(clip), str(out), popup.schedule(data, {}, 1, 1.0, 40.0), scan.first_pts, chunk=192 * 700)
    assert n == 8 + 0 and out.stat().st_size % 192 == 0          # 5 s apart: no room for repeats
    assert stream_pids(str(out)) == {**stream_pids(str(clip)), 0x1400: 0x91}

    # nothing else changed: the picture and sound are packet for packet what they were
    def md5(path):
        return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v", "-map", "0:a", "-c", "copy",
                               "-f", "md5", "-"], capture_output=True, text=True).stdout
    assert md5(out) == md5(clip) and md5(out).startswith("MD5=")
    again = scan_m2ts(str(out))
    assert (again.first_pts, again.end_pts, len(again.entries)) == (scan.first_pts, scan.end_pts, len(scan.entries))

    # each set sits in the file where its moment is, complete
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "2", "-show_entries", "packet=pts_time,pos",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    rows = [(float(a), int(b)) for a, b in (r.split(",")[:2] for r in probe)]
    first = scan.first_pts / 90000
    starts = sorted({round(t - first, 2) for t, _ in rows})
    assert starts == [0, 5, 10, 15, 20, 25, 30, 35]
    assert [p for _, p in rows] == sorted(p for _, p in rows)
    size = out.stat().st_size
    for t, pos in rows:
        assert abs(pos / size - (t - first) / 40) < 0.08         # (constant-ish bitrate test film)
    assert streams(out)[2]["id"] == "0x1400"


# ------------------------------------------------------------------ the Ironclad theme's progress bar
def _ironclad():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "boxset", "themes", "ironclad",
                        "theme.py")
    spec = importlib.util.spec_from_file_location("ironclad_theme", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("duration,chapters", [
    (8634.0, [0, 312, 598, 900, 1247, 1520, 1890, 2200, 2460, 2811, 3120, 3400, 3777, 4100, 4390, 4700, 5010, 5333,
              5600, 5920, 6240, 6555, 6800, 7150, 7480, 7800, 8100, 8400]),
    (5400.0, [0]),                                           # a film with no chapters of its own
    (7200.0, [0, 20, 40, 60, 3600, 3610, 7100]),             # chapters too short to be their own segment
    (95.0, [0, 30, 60]),                                     # a short
])
def test_ironclad_progress_bar_is_valid_for_any_film(duration, chapters, tmp_path):
    mod = _ironclad()
    film = _film(duration, chapters)
    pop = popup.Popup(film)
    hud = mod.Hud(film, 3, "#3FD9FF", "#FF8A1F")
    hud.build(pop)
    assert popup.validate(_ctx(pop), lambda a: None) == []
    assert sum(w for _, _, w in hud.columns) == hud.bar_w and all(w >= 14 for _, _, w in hud.columns)
    first, last = pop.frames[0], pop.frames[-1]
    assert first.default == "resume" and first.get("resume").action == "close"
    # the bar fills: the last frame has more of the energy colour than the first
    def lit(fr):
        im = fr.compose().convert("RGB")
        return sum(1 for x in range(hud.bar_x, hud.bar_x + hud.bar_w, 4)
                   if im.getpixel((x, hud.Y0 + hud.TRACK_Y + 16))[2] > 180)
    assert lit(last) > lit(first) and lit(first) <= 3
    # the tiles sit edge to edge: one slab with no holes along the track
    row = pop.frames[0].compose().getchannel("A").crop((hud.X0 + 40, hud.Y0 + 90, hud.X0 + hud.W - 40, hud.Y0 + 91))
    assert min(row.tobytes()) > 0
    saved = popup.save(pop, str(tmp_path), "film01")
    assert saved["frames"] == len(pop.frames)


def test_split_title():
    mod = _ironclad()
    assert mod.split_title("Transformers: Dark of the Moon") == ("Transformers", "Dark of the Moon")
    assert mod.split_title("Heat") == ("", "Heat")
    assert mod.split_title("Mission - Impossible") == ("Mission", "Impossible")
