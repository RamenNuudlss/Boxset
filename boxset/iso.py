"""Disc images (.iso) made with Windows' own disc-writing engine (IMAPI2),
in UDF 2.50, the file system Blu-ray players read. No extra software needed.
The image can then be burned with Windows' built-in Disc Image Burner."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from .config import DISC_SIZES

PS_SCRIPT = r"""
param([Parameter(Mandatory=$true)][string]$Source,
      [Parameter(Mandatory=$true)][string]$Out,
      [string]$Label = "BLURAY",
      [long]$Blocks = 0)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
public static class BoxsetIso {
    public static void Write(object comStream, string path, int blockSize, long totalBlocks) {
        IStream s = (IStream)comStream;
        int chunk = 512;
        byte[] buf = new byte[blockSize * chunk];
        IntPtr read = Marshal.AllocHGlobal(sizeof(int));
        try {
            using (FileStream o = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20)) {
                long done = 0; long last = -1;
                while (done < totalBlocks) {
                    int want = (int)Math.Min((long)chunk, totalBlocks - done) * blockSize;
                    s.Read(buf, want, read);
                    int got = Marshal.ReadInt32(read);
                    if (got <= 0) break;
                    o.Write(buf, 0, got);
                    done += got / blockSize;
                    long permille = done * 1000 / totalBlocks;
                    if (permille != last) { Console.Out.WriteLine("PROGRESS " + permille); Console.Out.Flush(); last = permille; }
                }
            }
        } finally { Marshal.FreeHGlobal(read); }
    }
}
'@
$img = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
$img.ChooseImageDefaultsForMediaType(18)      # BD-R
$img.FileSystemsToCreate = 4                  # UDF only
$img.UDFRevision = 0x250                      # UDF 2.50 for Blu-ray players
$img.VolumeName = $Label
if ($Blocks -gt 0) { $img.FreeMediaBlocks = [int]$Blocks }
Get-ChildItem -LiteralPath $Source | ForEach-Object { $img.Root.AddTree($_.FullName, $true) }
$res = $img.CreateResultImage()
[BoxsetIso]::Write($res.ImageStream, $Out, $res.BlockSize, $res.TotalBlocks)
Write-Output "DONE"
"""


def make_iso(disc_folder: str, out_path: str, label: str, disc_size: str, job) -> str:
    if sys.platform != "win32":
        raise RuntimeError("Disc images are made with Windows' built-in disc writer, so this step needs Windows.")
    job.stage("iso", "start", "Making the disc image")
    blocks = DISC_SIZES.get(disc_size, DISC_SIZES["BD-50"]) // 2048
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as fh:
        fh.write(PS_SCRIPT)
        script = fh.name
    part = out_path + ".part"
    ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script,
           "-Source", disc_folder, "-Out", part, "-Label", label[:32], "-Blocks", str(blocks)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    job._proc = proc
    ok = False
    try:
        for line in proc.stdout:
            if job.cancelled:
                break
            line = line.strip()
            if line.startswith("PROGRESS "):
                job.emit({"type": "progress", "stage": "iso", "pct": int(line[9:]) / 1000,
                          "label": "Making the disc image"})
            elif line == "DONE":
                ok = True
        proc.wait()
        err = proc.stderr.read()
    finally:
        job._proc = None
        if proc.poll() is None:
            proc.kill()
        try:
            os.remove(script)
        except OSError:
            pass
    if job.cancelled or not ok:
        try:
            os.remove(part)
        except OSError:
            pass
    if job.cancelled:
        from .pipeline import Cancelled
        raise Cancelled()
    if not ok:
        detail = " ".join(err.split())[-400:]
        raise RuntimeError("Windows couldn't make the disc image. The disc folder is still ready to burn with "
                           f"an app like ImgBurn.\n{detail}")
    os.replace(part, out_path)
    job.stage("iso", "done", "Disc image saved")
    return out_path
