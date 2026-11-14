"""Is there a newer Boxset, and installing it.

Asks GitHub for the latest release once when the app starts and compares it with
this copy's version. Nothing is downloaded until you press Update: then the
release's installer is downloaded from this project's own release, checked
against the size and SHA-256 that GitHub lists for it, and run in place of the
old version (settings, projects and installed themes are kept). Set
"check_updates": false in settings.json (or the environment variable
BOXSET_NO_UPDATE_CHECK) to switch the check off.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

from . import __version__

REPO = "RamenNuudlss/Boxset"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/".lower()


def parse(version: str):
    """"v1.2.3" -> (1, 2, 3); None for anything that isn't a plain release number
    (a development build, a pre-release)."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", (version or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def newer(latest: str, current: str = __version__) -> bool:
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


def _installer(data: dict, tag: str) -> dict | None:
    """The release's Windows installer, if it's attached the way the release build
    attaches it and GitHub lists its checksum."""
    want = f"boxsetsetup-{tag.lstrip('v')}.exe"
    for a in data.get("assets") or []:
        name, url = str(a.get("name") or ""), str(a.get("browser_download_url") or "")
        digest, size = str(a.get("digest") or ""), a.get("size")
        if name.lower() != want or not url.lower().startswith(DOWNLOADS):
            continue
        m = re.fullmatch(r"sha256:([0-9a-f]{64})", digest.lower())
        if m and isinstance(size, int) and size > 0:
            return {"name": name, "url": url, "size": size, "sha256": m.group(1)}
    return None


def check(current: str = __version__, timeout: float = 8.0, fetch=None) -> dict | None:
    """{"version", "url", "installer"} when a newer release is out, else None.
    "installer" is None when the release has no installer this copy can use. Never raises:
    no network, a rate limit or an odd answer all mean "nothing to say"."""
    if parse(current) is None or current == "0.0.0":
        return None                      # a development build has nothing to compare
    try:
        if fetch is None:
            req = urllib.request.Request(LATEST, headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": f"Boxset/{current}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 - fixed https URL
                data = json.loads(r.read().decode("utf-8"))
        else:
            data = fetch()
        tag = str(data.get("tag_name") or "")
        if data.get("draft") or data.get("prerelease") or not newer(tag, current):
            return None
        url = str(data.get("html_url") or "")
        if not url.startswith(f"https://github.com/{REPO}/"):
            url = RELEASES_PAGE          # only ever send people to this project's own page
        return {"version": tag.lstrip("v"), "url": url, "installer": _installer(data, tag)}
    except Exception:                    # noqa: BLE001 - see the docstring
        return None


# ---------------------------------------------------------------------- installing

def can_install() -> bool:
    """Only the installed Windows app updates itself; from source, use git."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def download(installer: dict, folder: str, progress=None, cancelled=None, opener=None) -> str:
    """Download the installer into folder and check it. Returns its path; raises
    RuntimeError if it doesn't match what GitHub listed."""
    os.makedirs(folder, exist_ok=True)
    final = os.path.join(folder, os.path.basename(installer["name"]))
    for n in os.listdir(folder):              # installers from earlier updates aren't needed
        if n.lower().startswith("boxsetsetup-") and os.path.join(folder, n) != final:
            try:
                os.remove(os.path.join(folder, n))
            except OSError:
                pass
    part = final + ".part"
    h, got = hashlib.sha256(), 0
    if opener is None:
        req = urllib.request.Request(installer["url"], headers={"User-Agent": f"Boxset/{__version__}"})
        opener = lambda: urllib.request.urlopen(req, timeout=30)   # noqa: E731,S310 - checked URL
    try:
        with opener() as r, open(part, "wb") as out:
            while True:
                if cancelled and cancelled():
                    raise RuntimeError("Update cancelled")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                got += len(chunk)
                if got > installer["size"]:
                    raise RuntimeError("The download is bigger than GitHub said it would be")
                h.update(chunk)
                out.write(chunk)
                if progress:
                    progress(got / installer["size"])
        if got != installer["size"]:
            raise RuntimeError("The download stopped before it finished. Try again.")
        if h.hexdigest() != installer["sha256"]:
            raise RuntimeError("The download doesn't match the checksum GitHub lists for it")
        os.replace(part, final)
        return final
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def install_command(setup: str) -> list[str]:
    """Run the installer quietly over this copy, then reopen Boxset. The installer
    reuses the previous install's folder and mode (just for you, or for everyone)."""
    return [setup, "/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL",
            "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS", "/RELAUNCH=1"]


def launch(setup: str) -> None:
    """Start the installer on its own; the app then closes so its files can be replaced."""
    cmd = install_command(setup)
    # through the shell, so Windows can ask for permission when Boxset is installed for everyone
    os.startfile(setup, "open", subprocess.list2cmdline(cmd[1:]), os.path.dirname(setup))  # noqa: S606
