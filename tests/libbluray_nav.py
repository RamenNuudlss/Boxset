"""Drive a built disc through libbluray (the engine inside VLC, Kodi and mpv):
press remote keys, record what plays, and capture the menu graphics the
player actually draws.

    python tests/libbluray_nav.py <disc folder> <out folder> KEY KEY ...

Keys: up down left right enter menu popup. `wait` plays to the end of the title,
`play:N` plays on for N seconds. Prints events; saves one PNG of the
interactive-graphics plane after each key.
"""
import ctypes as C
import os
import sys

from PIL import Image

lib = C.CDLL("libbluray.so.2")

# --- structs -------------------------------------------------------------
class BD_EVENT(C.Structure):
    _fields_ = [("event", C.c_uint32), ("param", C.c_uint32)]

class PAL(C.Structure):
    _fields_ = [("Y", C.c_uint8), ("Cr", C.c_uint8), ("Cb", C.c_uint8), ("T", C.c_uint8)]

class RLE(C.Structure):
    _fields_ = [("len", C.c_uint16), ("color", C.c_uint16)]

class BD_OVERLAY(C.Structure):
    _fields_ = [("pts", C.c_int64), ("plane", C.c_uint8), ("cmd", C.c_uint8),
                ("palette_update_flag", C.c_uint8), ("x", C.c_uint16), ("y", C.c_uint16),
                ("w", C.c_uint16), ("h", C.c_uint16), ("palette", C.POINTER(PAL)),
                ("img", C.POINTER(RLE))]

OVERLAY_CB = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(BD_OVERLAY))

lib.bd_open.restype = C.c_void_p
lib.bd_open.argtypes = [C.c_char_p, C.c_char_p]
lib.bd_play.argtypes = [C.c_void_p]
lib.bd_read_ext.argtypes = [C.c_void_p, C.c_char_p, C.c_int, C.POINTER(BD_EVENT)]
lib.bd_get_event.argtypes = [C.c_void_p, C.POINTER(BD_EVENT)]
lib.bd_user_input.argtypes = [C.c_void_p, C.c_int64, C.c_uint32]
lib.bd_register_overlay_proc.argtypes = [C.c_void_p, C.c_void_p, OVERLAY_CB]
lib.bd_get_titles.argtypes = [C.c_void_p, C.c_uint8, C.c_uint32]
lib.bd_close.argtypes = [C.c_void_p]
lib.bd_tell_time.restype = C.c_uint64
lib.bd_tell_time.argtypes = [C.c_void_p]

EVENTS = {1: "ERROR", 2: "READ_ERROR", 5: "TITLE", 6: "PLAYLIST", 7: "PLAYITEM", 8: "CHAPTER",
          10: "END_OF_TITLE", 11: "AUDIO_STREAM", 12: "IG_STREAM", 22: "PLAYLIST_STOP",
          25: "STILL", 26: "STILL_TIME", 29: "POPUP", 30: "MENU"}
KEYS = {"up": 12, "down": 13, "left": 14, "right": 15, "enter": 16, "menu": 10, "popup": 11}
# how much of the stream is read after each key (400 suits menus; inside a film
# that is about a minute, so set NAV_PUMP=2 to stay where you are)
AFTER_KEY = int(os.environ.get("NAV_PUMP", "400"))
OV = {0: "INIT", 1: "CLOSE", 2: "CLEAR", 3: "DRAW", 4: "WIPE", 5: "HIDE", 6: "FLUSH"}


class Plane:
    def __init__(self):
        self.img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        self.draws = 0

    def handle(self, _, ov_p):
        if not ov_p:
            return
        ov = ov_p.contents
        if ov.plane != 1:          # 1 = interactive graphics plane
            return
        cmd = OV.get(ov.cmd, ov.cmd)
        if cmd in ("INIT", "CLEAR", "CLOSE", "HIDE"):
            self.img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        elif cmd == "WIPE":
            self.img.paste((0, 0, 0, 0), (ov.x, ov.y, ov.x + ov.w, ov.y + ov.h))
        elif cmd == "DRAW" and ov.img:
            pal = [(p.Y, p.Cr, p.Cb, p.T) for p in ov.palette[:256]]
            rgba = [ycc(*p) for p in pal]
            px = Image.new("RGBA", (ov.w, ov.h), (0, 0, 0, 0))
            data = px.load()
            i, x, y = 0, 0, 0
            while y < ov.h:
                e = ov.img[i]
                i += 1
                if e.len == 0:     # end of line
                    x, y = 0, y + 1
                    continue
                c = rgba[e.color]
                for k in range(e.len):
                    if x + k < ov.w:
                        data[x + k, y] = c
                x += e.len
            # a graphics plane overwrites the area it draws (no blending with what was there)
            self.img.paste(px, (ov.x, ov.y))
            self.draws += 1


def ycc(Y, Cr, Cb, T):
    # BT.709 limited range -> RGB
    y, cb, cr = (Y - 16) * 1.164, Cb - 128, Cr - 128
    r = y + 1.793 * cr
    g = y - 0.213 * cb - 0.533 * cr
    b = y + 2.112 * cb
    cl = lambda v: max(0, min(255, round(v)))
    return (cl(r), cl(g), cl(b), T)


def pump(bd, n, log):
    buf = C.create_string_buffer(6144 * 20)
    ev = BD_EVENT()
    seen = []
    for _ in range(n):
        r = lib.bd_read_ext(bd, buf, len(buf), C.byref(ev))
        while ev.event:
            name = EVENTS.get(ev.event)
            if name and name not in ("STILL", "IG_STREAM", "AUDIO_STREAM", "PLAYITEM"):
                seen.append(f"{name}={ev.param}")
            if not lib.bd_get_event(bd, C.byref(ev)):
                break
        if r < 0:
            seen.append("read error")
            break
    log(" ".join(dict.fromkeys(seen)) or "(no events)")


def main():
    disc, out, keys = sys.argv[1], sys.argv[2], sys.argv[3:]
    os.makedirs(out, exist_ok=True)
    bd = lib.bd_open(disc.encode(), None)
    if not bd:
        sys.exit("libbluray could not open the disc")
    plane = Plane()
    cb = OVERLAY_CB(plane.handle)
    lib.bd_register_overlay_proc(bd, None, cb)
    lib.bd_get_titles(bd, 0, 0)
    if not lib.bd_play(bd):
        sys.exit("bd_play failed (first play)")
    print("start:", end=" ")
    pump(bd, 400, print)
    plane.img.save(os.path.join(out, "00_start.png"))
    for k, key in enumerate(keys, 1):
        if key == "wait":           # keep playing (reads the stream to the end of a title)
            print("wait:", end=" ")
            pump(bd, 6000, print)
        elif key.startswith("play:"):       # keep playing for this many seconds of the film
            target = lib.bd_tell_time(bd) + int(float(key[5:]) * 90000)
            for _ in range(20000):
                if lib.bd_tell_time(bd) >= target:
                    break
                pump(bd, 5, lambda _: None)
            print(f"{key}: now at {lib.bd_tell_time(bd) / 90000:.1f}s")
        else:
            lib.bd_user_input(bd, -1, KEYS[key])
            print(f"{key}:", end=" ")
            pump(bd, AFTER_KEY, print)
        plane.img.save(os.path.join(out, f"{k:02d}_{key.replace(':', '')}.png"))
    lib.bd_close(bd)


if __name__ == "__main__":
    main()
