"""Windows housekeeping for the packaged app.

* Every child process (ffmpeg, ffprobe, PowerShell) starts without a console
  window, including the ones bdmvkit starts itself, so nothing flashes on screen.
* The FFmpeg bundled next to Boxset.exe is found before any other copy.
"""
from __future__ import annotations

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
