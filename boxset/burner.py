"""Finding Blu-ray burners and what's in them, and burning a disc image.

Detection uses IMAPI2, the disc-burning service built into Windows, through
PowerShell. Burning hands the image to Windows Disc Image Burner (isoburn.exe)
with the chosen drive already selected.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

# IMAPI_PROFILE_TYPE values a drive lists when it can write Blu-ray
BD_WRITE_PROFILES = {0x41, 0x42, 0x43}          # BD-R (SRM), BD-R (RRM), BD-RE

# IMAPI_MEDIA_PHYSICAL_TYPE
MEDIA_NAMES = {1: "CD-ROM", 2: "CD-R", 3: "CD-RW", 4: "DVD-ROM", 5: "DVD-RAM", 6: "DVD+R",
               7: "DVD+RW", 8: "DVD+R DL", 9: "DVD-R", 10: "DVD-RW", 11: "DVD-R DL",
               13: "DVD+RW DL", 17: "BD-ROM", 18: "BD-R", 19: "BD-RE"}
BD_WRITABLE_MEDIA = {18, 19}

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$out = @()
try { $dm = New-Object -ComObject IMAPI2.MsftDiscMaster2 } catch { '[]'; exit }
if (-not $dm.IsSupportedEnvironment) { '[]'; exit }
foreach ($id in $dm) {
  try {
    $r = New-Object -ComObject IMAPI2.MsftDiscRecorder2
    $r.InitializeDiscRecorder($id)
    $o = [ordered]@{ id = "$id"; vendor = "$($r.VendorId)".Trim(); product = "$($r.ProductId)".Trim();
                     drive = "$(@($r.VolumePathNames) | Select-Object -First 1)";
                     profiles = @($r.SupportedProfiles | ForEach-Object { [int]$_ });
                     media = 0; blank = $null; free = $null }
    try {
      $f = New-Object -ComObject IMAPI2.MsftDiscFormat2Data
      $f.Recorder = $r
      $f.ClientName = 'Boxset'
      $o.media = [int]$f.CurrentPhysicalMediaType
      $o.blank = [bool]$f.MediaHeuristicallyBlank
      $o.free = [int64]$f.FreeSectorsOnMedia * 2048
    } catch { }
    $out += [pscustomobject]$o
  } catch { }
}
ConvertTo-Json -InputObject @($out) -Depth 3 -Compress
"""


def _powershell() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                        "WindowsPowerShell", "v1.0", "powershell.exe")


def list_drives(timeout=40) -> list[dict]:
    """Every optical drive Windows knows, with what it can write and what's in it."""
    if sys.platform != "win32":
        return []
    try:
        r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", _SCRIPT], capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout.strip() or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    if isinstance(data, dict):
        data = [data]
    return [describe(d) for d in data if isinstance(d, dict)]


def describe(d: dict) -> dict:
    """Add what the app shows: a name, whether it writes Blu-ray, and the disc in it."""
    profiles = set(d.get("profiles") or [])
    drive = (d.get("drive") or "").rstrip("\\")
    media = int(d.get("media") or 0)
    d = dict(d, drive=drive, bd=bool(profiles & BD_WRITE_PROFILES),
             name=" ".join(x for x in (drive, d.get("vendor", ""), d.get("product", "")) if x).strip(),
             media_name=MEDIA_NAMES.get(media, "" if not media else "an unknown disc"))
    return d


def check_disc(drive: dict | None, needed_bytes: int | None) -> tuple[str, str]:
    """(level, message) about burning to `drive`: level is "ok", "warn" or "stop"."""
    if not drive:
        return "stop", "No Blu-ray burner found. Connect one and press Refresh."
    if not drive.get("bd"):
        return "stop", f"{drive['name']} can't write Blu-ray discs."
    media = int(drive.get("media") or 0)
    if not media:
        return "warn", "No disc in the drive. Put in a blank BD-R or a BD-RE, then press Refresh."
    if media not in BD_WRITABLE_MEDIA:
        return "stop", f"The drive has {drive['media_name']} in it. Put in a blank BD-R or a BD-RE."
    free = drive.get("free")
    if drive.get("blank") is False:
        if media == 19:
            return "stop", ("The BD-RE in the drive has data on it. Erase it first: in File Explorer, "
                            "select the drive and choose Erase this disc. Then press Refresh.")
        return "stop", "The BD-R in the drive has already been written to. Use a blank one."
    if needed_bytes and free and free < needed_bytes:
        return "stop", (f"The {drive['media_name']} in the drive holds {free / 1e9:.1f} GB, and this disc "
                        f"needs {needed_bytes / 1e9:.1f} GB.")
    room = f", {free / 1e9:.1f} GB" if free else ""
    return "ok", f"Blank {drive['media_name']} in the drive{room}. Ready to burn."


def burn(iso_path: str, drive_letter: str | None):
    """Open Windows Disc Image Burner on the image, with the drive chosen."""
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "isoburn.exe")
    args = [exe] + ([drive_letter.rstrip("\\")] if drive_letter else []) + [iso_path]
    subprocess.Popen(args)
