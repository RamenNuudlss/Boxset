"""The video encoders Boxset can use, all set up for Blu-ray.

Speeds the user picks from:

* "quality": x264 at its "medium" preset. Slowest, best picture per gigabyte.
* "fast": x264 at "veryfast". About 2.5x faster; in testing, files came out
  13-15% smaller with a little less fine detail (about 1.2-1.5 dB PSNR).
* "gpu": the graphics card's H.264 encoder (NVIDIA NVENC, Intel Quick Sync or
  AMD AMF). Much faster and leaves the processor free, but hardware encoders
  need more bits for the same picture, and they have no Blu-ray mode like
  x264's, so the Blu-ray rules are set by hand here.

The graphics card encodes at an average bitrate rather than a quality level:
the film's measured need (from x264 samples) times GPU_FACTOR, capped by the
disc's limit. That keeps its picture close to x264's and its size known in
advance. Films at 25 or 29.97 fps are stored as 1080i, which needs x264's
fake-interlaced mode, so on the "gpu" speed those films use "fast" instead.
"""
from __future__ import annotations

import subprocess
import threading

from . import probe

SPEEDS = ("quality", "fast", "gpu")
X264_PRESET = {"quality": "medium", "fast": "veryfast"}

# x264 quality settings (CRF: lower is better and bigger)
CRF_STANDARD = 19
CRF_SAVE_SPACE = 23
CRF_TEST_BUILD = 24          # the quick test build, with x264's "ultrafast" preset

# How many more bits a graphics card's encoder gets than x264 needed, for a
# similar picture. Hardware encoders are typically 20-30% less efficient.
GPU_FACTOR = 1.3

FILM_FPS = (24000, 1001)     # the only rate the graphics card path handles (progressive 1080p)

# Tried in this order; the first that works is used.
GPU_ENCODERS = (("h264_nvenc", "NVIDIA"), ("h264_qsv", "Intel"), ("h264_amf", "AMD"))


def crf_for(save_space: bool) -> int:
    return CRF_SAVE_SPACE if save_space else CRF_STANDARD


def x264_args(fps, max_bps, keys=(), preset="medium", crf=CRF_STANDARD) -> list[str]:
    """bdmvkit's Blu-ray x264 settings with Boxset's preset and quality."""
    from bdmvkit.encode import video_args
    args = video_args(fps, max_bps, False, keys)
    args[args.index("-preset") + 1] = preset
    args[args.index("-crf") + 1] = str(crf)
    return args


def gpu_args(encoder: str, fps, max_bps, target_bps, keys=()) -> list[str]:
    """A graphics card's H.264 encoder held to the Blu-ray rules x264's
    bluray-compat mode applies: High profile at level 4.1, four slices, access
    unit delimiters, a key frame at least every second (and at each chapter
    where the encoder allows), at most 3 B-frames, none used as references,
    and the disc's peak bitrate and buffer."""
    from bdmvkit.formats import VBV_BUFFER
    gop = round(fps[0] / fps[1])
    target = int(min(target_bps, max_bps))
    common = ["-b:v", str(target), "-maxrate", str(int(max_bps)), "-bufsize", str(VBV_BUFFER),
              "-g", str(gop), "-slices", "4", "-aud", "1", "-profile:v", "high",
              "-r", f"{fps[0]}/{fps[1]}", "-aspect", "16:9",
              "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if encoder == "h264_nvenc":
        args = ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr",
                "-multipass", "qres", "-rc-lookahead", "32", "-spatial-aq", "1",
                "-bf", "3", "-b_ref_mode", "0", "-level", "4.1", "-forced-idr", "1",
                "-pix_fmt", "yuv420p"] + common
    elif encoder == "h264_qsv":
        args = ["-c:v", "h264_qsv", "-preset", "slow", "-look_ahead", "0", "-bf", "3",
                "-level", "41", "-forced_idr", "1", "-pix_fmt", "nv12"] + common
    elif encoder == "h264_amf":
        # AMF ignores requested key frames; chapters snap to the nearest one (under a second away)
        args = ["-c:v", "h264_amf", "-usage", "transcoding", "-quality", "quality",
                "-rc", "vbr_peak", "-enforce_hrd", "1", "-level", "4.1", "-pix_fmt", "nv12"] + common
    else:
        raise ValueError(f"Unknown encoder {encoder}")
    if keys and encoder != "h264_amf":
        args += ["-force_key_frames", ",".join(f"{t:.6f}" for t in sorted(keys))]
    return args


def gpu_target_kbps(rates: list[float], ceiling_kbps: float) -> float:
    """The average bitrate a graphics card gets for a film whose x264 samples
    needed `rates`, under the disc's limit."""
    from .estimate import video_kbps
    return video_kbps([r * GPU_FACTOR for r in rates], ceiling_kbps)


def uses_gpu(speed: str, gpu: dict | None, fps) -> bool:
    return speed == "gpu" and bool(gpu) and tuple(fps) == FILM_FPS


def x264_preset(speed: str) -> str:
    """The x264 preset for a speed; "gpu" films that can't use the card use "fast"."""
    return X264_PRESET.get(speed, X264_PRESET["fast"])


# ------------------------------------------------------------------ finding a graphics card
_found = None
_lock = threading.Lock()


def _works(ffmpeg: str, encoder: str) -> bool:
    """Encode a few frames with the real settings: proves the card, its driver
    and the settings all work, not just that FFmpeg knows the encoder."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi",
           "-i", "color=black:s=1920x1080:r=24000/1001", "-frames:v", "12"]
    cmd += gpu_args(encoder, FILM_FPS, 30_000_000, 8_000_000, [0.2])
    cmd += ["-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _card_names() -> list[str]:
    """The graphics cards Windows reports, for showing the user."""
    import sys
    if sys.platform != "win32":
        return []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                           capture_output=True, text=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def detect_gpu(refresh=False) -> dict | None:
    """{"encoder": "h264_nvenc", "vendor": "NVIDIA", "name": "NVIDIA GeForce …"} for the
    first graphics card encoder that works here, or None. Checked once per run."""
    global _found
    with _lock:
        if _found is not None and not refresh:
            return _found or None
        try:
            ffmpeg = probe.need("ffmpeg")
        except RuntimeError:
            _found = {}
            return None
        names = None
        for encoder, vendor in GPU_ENCODERS:
            if _works(ffmpeg, encoder):
                if names is None:
                    names = _card_names()
                key = {"NVIDIA": ("nvidia", "geforce", "quadro", "rtx"), "Intel": ("intel",),
                       "AMD": ("amd", "radeon")}[vendor]
                name = next((n for n in names if any(k in n.lower() for k in key)), f"{vendor} graphics")
                _found = {"encoder": encoder, "vendor": vendor, "name": name}
                return _found
        _found = {}
        return None
