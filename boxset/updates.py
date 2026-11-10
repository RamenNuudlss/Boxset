"""Is there a newer Boxset?

Asks GitHub for the latest release once when the app starts and compares it with
this copy's version. Nothing is downloaded or installed: the app only shows a
note with a link to the release page. Set "check_updates": false in settings.json
(or the environment variable BOXSET_NO_UPDATE_CHECK) to switch it off.
"""
from __future__ import annotations

import json
import re
import urllib.request

from . import __version__

REPO = "RamenNuudlss/Boxset"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"


def parse(version: str):
    """"v1.2.3" -> (1, 2, 3); None for anything that isn't a plain release number
    (a development build, a pre-release)."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", (version or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def newer(latest: str, current: str = __version__) -> bool:
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


def check(current: str = __version__, timeout: float = 8.0, fetch=None) -> dict | None:
    """{"version", "url"} when a newer release is out, else None. Never raises:
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
        return {"version": tag.lstrip("v"), "url": url}
    except Exception:                    # noqa: BLE001 - see the docstring
        return None
