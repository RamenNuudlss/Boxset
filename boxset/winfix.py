"""Windows housekeeping for the packaged app.

* Every child process (ffmpeg, ffprobe, PowerShell) starts without a console
  window, including the ones bdmvkit starts itself, so nothing flashes on screen.
* The FFmpeg bundled next to Boxset.exe is found before any other copy.
* The PC stays awake while a build runs (keep_awake).
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys


def apply():
    if sys.platform != "win32":
        return
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None
    if base:
        for d in (os.path.join(base, "bin"), os.path.join(getattr(sys, "_MEIPASS", base), "bin")):
            if os.path.isdir(d):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                break
    if getattr(subprocess.Popen, "_boxset_quiet", False):
        return
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    class QuietPopen(subprocess.Popen):
        _boxset_quiet = True

        def __init__(self, *args, **kwargs):
            if not kwargs.get("creationflags"):
                kwargs["creationflags"] = no_window
            super().__init__(*args, **kwargs)

    subprocess.Popen = QuietPopen


@contextlib.contextmanager
def keep_awake():
    """Stop Windows going to sleep while a long job runs on this thread. The screen
    may still turn off; only the sleep that would stall an encode is held back.
    Does nothing on other systems."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    kernel32 = None
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception:      # never let this stop a build
            kernel32 = None
    try:
        yield
    finally:
        if kernel32 is not None:
            try:
                kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:
                pass
