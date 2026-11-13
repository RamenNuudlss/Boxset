"""In-film pop-ups: what the remote's Pop-up Menu button shows over a playing film.

A pop-up is drawn by the theme as a series of *frames*, each for a moment of the
film: the progress bar at 0:00, at 0:01, at 0:02 and so on. On the disc each
frame becomes a set of buttons carried inside the film's own stream at that
moment, so whenever the viewer opens the pop-up they see the frame for where
they are. That is how a Blu-ray menu, which can't draw anything by itself, shows
a progress bar that is right.

    pop = ctx.popup(film.number)
    for t in pop.moments(every=60):          # each minute, and each chapter's start
        fr = pop.frame(t)
        fr.label("time", 96, 900, image)                       # just a picture
        fr.button("resume", 1500, 900, {"normal": a, "selected": b}, act.close())
        fr.default = "resume"

Every frame has the same buttons (same ids, same actions); their pictures,
positions and the default button may differ from frame to frame.

Between frames the current one is repeated every few seconds, so the pop-up is
there again straight after a jump to another chapter.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import dataclass, field

from PIL import Image

FRAME_W, FRAME_H = 1920, 1080
MAX_BUTTONS = 255
DIRECTIONS = ("up", "down", "left", "right")
REPEAT_SECONDS = 8.0          # how often the current frame is carried again
REPEAT_KBPS = 64              # ... but never taking more of the film's bitrate than this
MIN_FRAME_GAP = 2.0           # frames closer together than this are too fast for a player
POPUP_ACTIONS = ("chapter", "title", "menu", "playall", "playlist", "close")


@dataclass
class PopupButton:
    id: str
    x: int
    y: int
    normal: Image.Image
    selected: Image.Image
    action: str                   # "" for a label: a picture that can't be selected
    nav: dict = field(default_factory=dict)

    @property
    def w(self):
        return self.normal.width

    @property
    def h(self):
        return self.normal.height


class PopupFrame:
    """The pop-up as it looks from `seconds` into the film until the next frame."""

    def __init__(self, seconds: float):
        self.seconds = float(seconds)
        self.buttons: list[PopupButton] = []
        self.default: str | None = None

    def button(self, bid, x, y, images: dict, action: str, nav: dict | None = None, default=False):
        """Add a button. images: {"normal": ..., "selected": ...}, the same size.
        nav: {"left": id, ...}; a direction left out stays on the button."""
        normal, selected = images.get("normal"), images.get("selected")
        if normal is None or selected is None:
            raise ValueError(f"Pop-up button '{bid}' needs a normal and a selected picture")
        normal, selected = normal.convert("RGBA"), selected.convert("RGBA")
        if normal.size != selected.size:
            raise ValueError(f"Pop-up button '{bid}': its two pictures must be the same size")
        b = PopupButton(bid, round(x), round(y), normal, selected, action, dict(nav or {}))
        self.buttons.append(b)
        if default or self.default is None:
            self.default = bid
        return b

    def label(self, bid, x, y, image):
        """Add a picture that is only shown: the remote can't move onto it."""
        image = image.convert("RGBA")
        self.buttons.append(PopupButton(bid, round(x), round(y), image, image, ""))

    def get(self, bid) -> PopupButton:
        return next(b for b in self.buttons if b.id == bid)

    def chain(self, ids, wrap=False, axis="horizontal"):
        """Link buttons for the arrow keys in the given order."""
        a, b = ("up", "down") if axis == "vertical" else ("left", "right")
        for i, bid in enumerate(ids):
            btn = self.get(bid)
            if i > 0 or wrap:
                btn.nav.setdefault(a, ids[i - 1])
            if i < len(ids) - 1 or wrap:
                btn.nav.setdefault(b, ids[(i + 1) % len(ids)])

    def compose(self, selected: str | None = None) -> Image.Image:
        """The frame as a picture (for previews): every button in its normal
        state, `selected` in its selected one."""
        im = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
        for b in self.buttons:
            im.paste(b.selected if b.id == selected else b.normal, (b.x, b.y))
        return im


class Popup:
    def __init__(self, film):
        self.film = film
        self.frames: list[PopupFrame] = []

    def frame(self, seconds: float) -> PopupFrame:
        fr = PopupFrame(seconds)
        self.frames.append(fr)
        return fr

    def moments(self, every: float = 60.0) -> list[float]:
        """Times to draw a frame for: every `every` seconds and at each chapter's
        start (so the current chapter is always right), none too close together."""
        times = {0.0}
        t = every
        while t < self.film.duration - MIN_FRAME_GAP:
            times.add(float(t))
            t += every
        chapters = [c.start for c in self.film.chapters if 0 < c.start < self.film.duration - MIN_FRAME_GAP]
        out = sorted(set(chapters))
        for t in sorted(times):                      # chapter starts win over nearby minute marks
            if all(abs(t - c) >= MIN_FRAME_GAP for c in chapters):
                out.append(t)
        out = sorted(set(out) | {0.0})
        kept = []
        for t in out:
            if not kept or t - kept[-1] >= MIN_FRAME_GAP:
                kept.append(t)
        return kept

    def chapter_at(self, seconds: float):
        """The chapter playing at `seconds`."""
        now = self.film.chapters[0]
        for c in self.film.chapters:
            if c.start <= seconds + 0.001:
                now = c
        return now


# ----------------------------------------------------------------- checking
def validate(ctx, check_action) -> list[str]:
    """What's wrong with the theme's pop-ups, in words. `check_action(action)`
    returns an error for an action that points at nothing."""
    errors = []
    for n, pop in sorted(ctx.popups.items()):
        where = f"film {n}'s pop-up"
        if not pop.frames:
            errors.append(f"{where} has no frames")
            continue
        times = [fr.seconds for fr in pop.frames]
        if times != sorted(times) or times[0] != 0:
            errors.append(f"{where}: frames must be in time order, the first at 0 seconds")
        if any(b - a < MIN_FRAME_GAP for a, b in zip(times, times[1:])):
            errors.append(f"{where}: frames must be at least {MIN_FRAME_GAP:g} seconds apart")
        if times[-1] >= pop.film.duration:
            errors.append(f"{where}: a frame is timed after the film ends")
        first = [(b.id, b.action) for b in pop.frames[0].buttons]
        for fr in pop.frames:
            at = f"{where} at {fr.seconds:g}s"
            ids = [b.id for b in fr.buttons]
            if [(b.id, b.action) for b in fr.buttons] != first:
                errors.append(f"{at}: every frame must have the same buttons with the same actions")
                break
            if len(set(ids)) != len(ids):
                errors.append(f"{at}: duplicate button ids")
                break
            if len(ids) > MAX_BUTTONS:
                errors.append(f"{at} has {len(ids)} buttons; the limit is {MAX_BUTTONS}")
            selectable = [b.id for b in fr.buttons if b.action]
            if not selectable:
                errors.append(f"{at} has no button to select")
            elif fr.default not in selectable:
                errors.append(f"{at}: default button '{fr.default}' isn't a selectable button")
            for b in fr.buttons:
                if b.x < 0 or b.y < 0 or b.x + b.w > FRAME_W or b.y + b.h > FRAME_H:
                    errors.append(f"{at}, button '{b.id}' runs off the 1920x1080 screen")
                for d, target in b.nav.items():
                    if d not in DIRECTIONS:
                        errors.append(f"{at}, button '{b.id}': unknown direction '{d}'")
                    elif target not in selectable:
                        errors.append(f"{at}, button '{b.id}': {d} goes to '{target}', "
                                      "which isn't a selectable button here")
            rects = [(b.id, b.x, b.y, b.x + b.w, b.y + b.h) for b in fr.buttons]
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    a, b = rects[i], rects[j]
                    if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                        errors.append(f"{at}: buttons '{a[0]}' and '{b[0]}' overlap")
            if len(errors) > 12:
                return errors
        for bid, action in first:
            if not action:
                continue
            kind = action.split(":")[0]
            if kind not in POPUP_ACTIONS:
                errors.append(f"{where}, button '{bid}': a pop-up button can't do '{action}'")
            elif kind != "close":
                err = check_action(action)
                if err:
                    errors.append(f"{where}, button '{bid}': {err}")
    return errors


# ----------------------------------------------------------------- saving
def save(pop: Popup, folder: str, name: str) -> dict:
    """Write a pop-up to `folder` as name.json + name.bin, ready for the disc:
    its pictures reduced to one palette of 255 colours and run-length coded,
    each distinct picture stored once. Returns {"file", "frames", "bytes"}."""
    from bdmvkit import pgs
    os.makedirs(folder, exist_ok=True)
    tiles, order = {}, []                          # picture -> tile number

    def tile(im: Image.Image) -> int:
        key = (im.size, hashlib.blake2b(im.tobytes(), digest_size=16).digest())
        if key not in tiles:
            tiles[key] = len(order)
            order.append(im)
        return tiles[key]

    frames = []
    for fr in pop.frames:
        frames.append({"t": round(fr.seconds, 3), "default": fr.default, "buttons": [
            {"id": b.id, "x": b.x, "y": b.y, "w": b.w, "h": b.h, "normal": tile(b.normal),
             "selected": tile(b.selected), "action": b.action, "nav": b.nav} for b in fr.buttons]})

    # every distinct picture on one sheet, reduced to one palette
    width = max(2048, max(im.width for im in order))
    places, x, y, row = [], 0, 0, 0
    for im in order:
        if x + im.width > width:
            x, y, row = 0, y + row, 0
        places.append((x, y))
        x, row = x + im.width, max(row, im.height)
    sheet = Image.new("RGBA", (width, y + row), (0, 0, 0, 0))
    for im, at in zip(order, places):
        sheet.paste(im, at)
    q = sheet.quantize(colors=255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    flat = q.getpalette("RGBA")
    palette = [flat[i:i + 4] for i in range(0, len(flat), 4)][:255]

    index, blob = [], bytearray()
    for im, (px, py) in zip(order, places):
        idx = q.crop((px, py, px + im.width, py + im.height)).tobytes()
        coded = pgs.rle(idx, im.width, im.height)
        index.append([im.width, im.height, len(blob), len(coded)])
        blob += coded
    with open(os.path.join(folder, name + ".bin"), "wb") as fh:
        fh.write(blob)
    with open(os.path.join(folder, name + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"film": pop.film.number, "duration": pop.film.duration, "palette": palette,
                   "tiles": index, "frames": frames}, fh)
    return {"file": name + ".json", "frames": len(frames), "bytes": len(blob)}


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    with open(os.path.splitext(path)[0] + ".bin", "rb") as fh:
        blob = fh.read()
    data["coded"] = [blob[off:off + n] for _, _, off, n in data["tiles"]]
    return data


# ----------------------------------------------------------------- the disc's graphics stream
ICS, PDS, ODS, END = 0x18, 0x14, 0x15, 0x80
EPOCH_START, ACQUISITION_POINT = 0x80, 0x40
NO_OBJECT = 0xFFFF
MAX_SEGMENT = 65000          # with its packet header, a segment must stay under 65536 bytes


def _segment(kind: int, data: bytes) -> bytes:
    return bytes([kind]) + len(data).to_bytes(2, "big") + data


def _object(oid: int, w: int, h: int, coded: bytes) -> list[bytes]:
    data = (len(coded) + 4).to_bytes(3, "big") + struct.pack(">HH", w, h) + coded
    size = MAX_SEGMENT - 4
    chunks = [data[i:i + size] for i in range(0, len(data), size)]
    out = []
    for k, chunk in enumerate(chunks):
        flags = (0x80 if k == 0 else 0) | (0x40 if k == len(chunks) - 1 else 0)
        out.append(_segment(ODS, struct.pack(">HBB", oid, 0, flags) + chunk))
    return out


def display_set(data: dict, frame: dict, commands: dict, rate_code: int, number: int, state: int) -> list[bytes]:
    """One frame of a pop-up as the segments a player reads: the composition (its
    buttons, where the arrow keys go, what OK does), the palette, the pictures."""
    from bdmvkit import pgs
    buttons = frame["buttons"]
    ids = {b["id"]: k for k, b in enumerate(buttons)}
    used = []                                         # tile numbers, in object-id order
    for b in buttons:
        for t in (b["normal"], b["selected"]):
            if t not in used:
                used.append(t)
    oid = {t: k for k, t in enumerate(used)}
    body = b""
    number_key = 0
    for k, b in enumerate(buttons):
        moves = [ids.get(b["nav"].get(d), k) if b["action"] else k for d in DIRECTIONS]
        cmds = commands.get(b["id"], []) if b["action"] else []
        if b["action"]:
            number_key += 1
        n, s = oid[b["normal"]], oid[b["selected"]]
        button = struct.pack(">HHBHH", k, number_key if b["action"] else 0xFFFF, 0, b["x"], b["y"])
        button += struct.pack(">HHHH", *moves)
        button += struct.pack(">HHB", n, n, 0)                 # normal
        button += struct.pack(">BHHB", 0xFF, s, s, 0)          # selected (no sound)
        button += struct.pack(">BHH", 0xFF, s, s)              # activated: the same picture
        button += struct.pack(">H", len(cmds)) + b"".join(cmds)
        body += struct.pack(">HB", k, 1) + button              # each button its own group
    page = struct.pack(">BB", 0, 0) + bytes(8)                 # page 0; nothing prohibited
    page += bytes(4)                                           # no in or out effects
    page += struct.pack(">BHHBB", 0, ids[frame["default"]], NO_OBJECT, 0, len(buttons)) + body
    comp = bytes([0x40]) + bytes(10)                           # in the film's stream; a pop-up; no time-outs
    comp += (0).to_bytes(3, "big") + bytes([1]) + page
    ics = struct.pack(">HHB", FRAME_W, FRAME_H, rate_code << 4)
    ics += struct.pack(">HB", number & 0xFFFF, state)
    ics += bytes([0xC0]) + len(comp).to_bytes(3, "big") + comp
    if len(ics) > MAX_SEGMENT:
        raise RuntimeError("The pop-up has too many buttons for a player to hold.")
    entries = b""
    for k, (r, g, b_, a) in enumerate(data["palette"]):
        y, cb, cr = pgs.ycbcr((r, g, b_))
        entries += bytes([k, y, cr, cb, a])
    out = [_segment(ICS, ics), _segment(PDS, bytes([0, 0]) + entries)]
    for t in used:
        w, h = data["tiles"][t][:2]
        out += _object(oid[t], w, h, data["coded"][t])
    return out + [_segment(END, b"")]


def schedule(data: dict, commands: dict, rate_code: int, tempo: float = 1.0,
             clip_seconds: float | None = None):
    """When each display set goes into the film, in order: (seconds into the
    clip, its segments). Each frame at its moment, and again every few seconds
    until the next, so a player that has just jumped here picks it up."""
    end = clip_seconds if clip_seconds is not None else data["duration"] * tempo
    frames = data["frames"]
    number = 0
    for i, frame in enumerate(frames):
        start = frame["t"] * tempo
        stop = frames[i + 1]["t"] * tempo if i + 1 < len(frames) else end
        first = display_set(data, frame, commands, rate_code, number, EPOCH_START)
        yield start, first
        number += 1
        size = sum(len(seg) for seg in first)
        every = max(REPEAT_SECONDS, size * 8 / (REPEAT_KBPS * 1000))
        t = start + every
        while t < stop - MIN_FRAME_GAP:
            # the same again, marked as a repeat: a player already showing it carries on
            again = [first[0][:8] + struct.pack(">HB", number & 0xFFFF, ACQUISITION_POINT) + first[0][11:]]
            yield t, again + first[1:]
            number += 1
            t += every


# ----------------------------------------------------------------- into the film's clip
PACKET = 192                    # a BDAV source packet: 4 bytes of arrival time, then 188 of transport stream


def _pts_bytes(pts: int) -> bytes:
    pts &= (1 << 33) - 1
    return bytes([0x21 | (pts >> 30 & 7) << 1, pts >> 22 & 0xFF, (pts >> 15 & 0x7F) << 1 | 1,
                  pts >> 7 & 0xFF, (pts & 0x7F) << 1 | 1])


def _read_pts(b, i) -> int:
    return ((b[i] >> 1) & 7) << 30 | b[i + 1] << 22 | (b[i + 2] >> 1) << 15 | b[i + 3] << 7 | b[i + 4] >> 1


class _Packets:
    """Turns segments into source packets on the pop-up's stream."""

    def __init__(self, pid: int):
        self.pid = pid
        self.counter = 0

    def pes(self, segment: bytes, pts: int, arrival: bytes) -> bytes:
        """One segment as one PES packet, cut into source packets."""
        body = bytes([0x84, 0x80, 5]) + _pts_bytes(pts) + segment
        pes = b"\x00\x00\x01\xBD" + len(body).to_bytes(2, "big") + body
        out = bytearray()
        pos, first = 0, True
        while pos < len(pes):
            left = len(pes) - pos
            head = bytes([0x47, (0x40 if first else 0) | self.pid >> 8, self.pid & 0xFF])
            room = 184
            field = b""
            if first:                                   # the first packet says a unit starts here
                field = bytes([1, 0x40])
                room -= 2
            if left < room:                             # the last packet is padded in front
                pad = room - left
                if field:
                    field = bytes([1 + pad, 0x40]) + b"\xFF" * pad
                elif pad == 1:
                    field = bytes([0])
                else:
                    field = bytes([pad - 1, 0x00]) + b"\xFF" * (pad - 2)
                room = left
            flags = (0x30 if field else 0x10) | self.counter
            self.counter = (self.counter + 1) & 0x0F
            out += arrival + head + bytes([flags]) + field + pes[pos:pos + room]
            pos += room
            first = False
        return bytes(out)

    def display_set(self, segments: list[bytes], pts: int, arrival: bytes) -> bytes:
        return b"".join(self.pes(seg, pts, arrival) for seg in segments)


def _add_to_pmt(pkt: bytearray, pid: int, stream_type: int, crc32) -> bool:
    """List the pop-up's stream in one programme-map packet; whether it's there now."""
    q = 8
    if pkt[7] & 0x20:
        q += 1 + pkt[q]
    q += 1 + pkt[q]                                     # pointer field
    if pkt[q] != 2:
        return False
    length = (pkt[q + 1] & 0x0F) << 8 | pkt[q + 2]
    end = q + 3 + length - 4                            # where the CRC starts
    if end + 4 > len(pkt):
        raise RuntimeError("This film has too many audio and subtitle tracks to add a pop-up to.")
    e = q + 12 + ((pkt[q + 10] & 0x0F) << 8 | pkt[q + 11])
    while e < end:
        if (pkt[e + 1] & 0x1F) << 8 | pkt[e + 2] == pid:
            return True                                 # already listed
        e += 5 + ((pkt[e + 3] & 0x0F) << 8 | pkt[e + 4])
    if end + 4 + 5 > len(pkt):
        raise RuntimeError("This film has too many audio and subtitle tracks to add a pop-up to.")
    entry = bytes([stream_type, 0xE0 | pid >> 8, pid & 0xFF, 0xF0, 0x00])
    length += 5
    pkt[q + 1] = (pkt[q + 1] & 0xF0) | length >> 8
    pkt[q + 2] = length & 0xFF
    pkt[end:end] = entry                                # (before the CRC, which moves along)
    del pkt[len(pkt) - 5:]                              # five bytes less padding
    crc = crc32(bytes(pkt[q:end + 5]))
    pkt[end + 5:end + 9] = crc.to_bytes(4, "big")
    return True


def insert(clip: str, out: str, sets, first_pts: int, check=None, chunk: int = 8 << 20) -> int:
    """Copy `clip` to `out` with the pop-up's display sets (`sets`: (seconds,
    segments) in time order, as schedule() gives) put into the stream, each just
    before the last key frame at or before its moment, which is where a player
    jumping to that moment starts reading. Returns how many sets went in.

    Written here, not left to FFmpeg, which only places the first few packets of
    a stream this sparse where they belong and leaves the rest for the end of
    the file."""
    from bdmvkit.formats import CODING_IG, IG_PID, PMT_PID, VIDEO_PID
    from bdmvkit.igs import crc32
    video = bytes([0x47, 0x40 | VIDEO_PID >> 8, VIDEO_PID & 0xFF])
    pmt = bytes([0x47, 0x40 | PMT_PID >> 8, PMT_PID & 0xFF])
    chunk -= chunk % PACKET
    packets = _Packets(IG_PID)
    sets = iter(sets)
    pending = next(sets, None)
    count = 0
    buf = bytearray()
    held = None                 # offset in buf of the last key frame seen: everything before it is final
    listed = False

    def emit(dst, upto_pts):
        """Write the sets due before `upto_pts` (all of them when None)."""
        nonlocal pending, count
        data = b""
        while pending is not None and (upto_pts is None or first_pts + round(pending[0] * 90000) < upto_pts):
            arrival = bytes(buf[held:held + 4]) if held is not None else bytes(4)
            data += packets.display_set(pending[1], first_pts + round(pending[0] * 90000), arrival)
            count += 1
            pending = next(sets, None)
        if data:
            dst.write(data)

    with open(clip, "rb") as src, open(out, "wb") as dst:
        while True:
            if check:
                check()
            data = src.read(chunk)
            if not data:
                break
            start = len(buf)
            buf += data
            # the programme map: say the stream is there
            i = buf.find(pmt, start)
            while i >= 0:
                at = i - 4
                if at >= 0 and at % PACKET == 0 and at + PACKET <= len(buf):
                    pkt = bytearray(buf[at:at + PACKET])
                    if _add_to_pmt(pkt, IG_PID, CODING_IG, crc32):
                        buf[at:at + PACKET] = pkt
                        listed = True
                i = buf.find(pmt, i + 1)
            # the key frames
            i = buf.find(video, start)
            while i >= 0:
                at = i - 4
                if at >= 0 and at % PACKET == 0 and at + PACKET <= len(buf):
                    q = i + 4
                    afc = buf[i + 3] >> 4 & 3
                    key = False
                    if afc & 2:
                        if buf[q]:
                            key = bool(buf[q + 1] & 0x40)
                        q += 1 + buf[q]
                    if key and afc & 1 and q + 14 <= at + PACKET and buf[q:q + 3] == b"\0\0\1" \
                            and buf[q + 7] & 0x80:
                        pts = _read_pts(buf, q + 9)
                        shift = at if held is None else held
                        dst.write(buf[:shift])                  # all before the last key frame
                        if held is not None:
                            emit(dst, pts)                      # the sets due before this one
                        del buf[:shift]
                        i -= shift
                        held = at - shift                       # what's left starts at the last key frame
                i = buf.find(video, i + 1)
        if held is not None:
            dst.write(buf[:held])
            emit(dst, None)
            dst.write(buf[held:])
        else:
            dst.write(buf)
    if not listed:
        raise RuntimeError(f"Couldn't find the programme map of {clip}")
    return count
