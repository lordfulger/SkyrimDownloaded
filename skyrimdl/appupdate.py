"""Is there a newer SkyrimDownloaded? Asks GitHub for the latest release."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from . import __version__

LATEST_URL = "https://api.github.com/repos/lordfulger/SkyrimDownloaded/releases/latest"
RELEASES_PAGE = "https://github.com/lordfulger/SkyrimDownloaded/releases/latest"


@dataclass
class NewVersion:
    version: str
    page: str
    exe_url: str = ""


def parse(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version or "")[:3]) or (0,)


def check(url: str = LATEST_URL, current: str = __version__, timeout: float = 10.0) -> NewVersion | None:
    """The newer release, or None if this is the latest (or GitHub can't be reached)."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"SkyrimDownloaded/{current}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    tag = str(data.get("tag_name") or "")
    if not tag or data.get("draft") or data.get("prerelease") or parse(tag) <= parse(current):
        return None
    exe = next((a.get("browser_download_url") for a in data.get("assets") or []
                if str(a.get("name", "")).lower().endswith(".exe")), "")
    return NewVersion(tag.lstrip("v"), data.get("html_url") or RELEASES_PAGE, exe or "")
