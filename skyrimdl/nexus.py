"""A small client for the Nexus Mods public API (v1), using your personal API key.

Get the key from https://www.nexusmods.com/settings/api-keys (bottom of the page,
"Personal API Key"). Premium accounts can ask the API for download links
directly; free accounts can't, which is why this tool needs Premium for the
"download it here" mode.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import __version__

API_BASE = "https://api.nexusmods.com/v1"
# The v1 API doesn't list a mod's requirements; the v2 GraphQL API does.
REQUIREMENTS_QUERY = """
query modRequirements($modId: Int!, $gameDomainName: String!) {
  modRequirements(modId: $modId, gameDomainName: $gameDomainName) {
    nexusRequirements(count: 50) {
      nodes { id gameId modId modName notes url externalRequirement }
    }
  }
}
"""
APP_NAME = "SkyrimDownloaded"
USER_AGENT = f"{APP_NAME}/{__version__} (Python; mod list downloader)"


class NexusError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class NotPremiumError(NexusError):
    pass


class AuthError(NexusError):
    pass


@dataclass
class Account:
    user_id: int
    name: str
    is_premium: bool
    is_supporter: bool
    profile_url: str = ""

    @property
    def kind(self) -> str:
        if self.is_premium:
            return "Premium"
        if self.is_supporter:
            return "Supporter"
        return "Free"


@dataclass
class RateLimit:
    daily_remaining: int | None = None
    hourly_remaining: int | None = None
    daily_limit: int | None = None
    hourly_limit: int | None = None

    def update(self, headers) -> None:
        def num(name):
            value = headers.get(name)
            try:
                return int(value) if value is not None else None
            except ValueError:
                return None
        for attr, name in (
            ("daily_remaining", "X-RL-Daily-Remaining"),
            ("hourly_remaining", "X-RL-Hourly-Remaining"),
            ("daily_limit", "X-RL-Daily-Limit"),
            ("hourly_limit", "X-RL-Hourly-Limit"),
        ):
            value = num(name)
            if value is not None:
                setattr(self, attr, value)

    def describe(self) -> str:
        if self.daily_remaining is None and self.hourly_remaining is None:
            return "unknown"
        return f"{self.daily_remaining} left today, {self.hourly_remaining} left this hour"


@dataclass
class Requirement:
    mod_id: int | None
    name: str
    url: str
    notes: str = ""
    external: bool = False   # not on Nexus (e.g. a download from another site)


@dataclass
class ModInfo:
    game: str
    mod_id: int
    name: str
    version: str = ""
    author: str = ""
    summary: str = ""
    available: bool = True
    status: str = "published"
    adult: bool = False
    picture_url: str = ""
    category_id: int | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, game: str, data: dict) -> "ModInfo":
        return cls(
            game=game,
            mod_id=int(data.get("mod_id") or 0),
            name=data.get("name") or f"Mod {data.get('mod_id')}",
            version=str(data.get("version") or ""),
            author=data.get("author") or data.get("uploaded_by") or "",
            summary=data.get("summary") or "",
            available=bool(data.get("available", True)),
            status=data.get("status") or "published",
            adult=bool(data.get("contains_adult_content", False)),
            picture_url=data.get("picture_url") or "",
            category_id=data.get("category_id"),
            raw=data,
        )


class NexusClient:
    def __init__(self, api_key: str, *, base_url: str = API_BASE, timeout: float = 30.0,
                 max_retries: int = 4):
        if not api_key or not api_key.strip():
            raise AuthError("No Nexus API key. Paste your personal API key first.")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.graphql_url = re.sub(r"/v1$", "", self.base_url) + "/v2/graphql"
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate = RateLimit()
        self._cache: dict[str, object] = {}
        self._lock = threading.Lock()
        self._account: Account | None = None

    # -- plumbing ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.api_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Application-Name": APP_NAME,
            "Application-Version": __version__,
            "Protocol-Version": "1.0.0",
        }

    def _get(self, path: str, params: dict | None = None, *, cache: bool = True):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if cache:
            with self._lock:
                if url in self._cache:
                    return self._cache[url]
        attempt = 0
        while True:
            attempt += 1
            req = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.rate.update(resp.headers)
                    body = resp.read()
                data = json.loads(body.decode("utf-8") or "null")
                if cache:
                    with self._lock:
                        self._cache[url] = data
                return data
            except urllib.error.HTTPError as err:
                self.rate.update(err.headers or {})
                message = _error_message(err)
                if err.code == 401:
                    raise AuthError("Nexus says the API key isn't valid. " + message, 401) from None
                if err.code == 429:
                    if attempt > self.max_retries:
                        raise NexusError(
                            "Out of Nexus API requests for now (" + self.rate.describe()
                            + "). Try again in an hour.", 429) from None
                    time.sleep(_retry_after(err, attempt))
                    continue
                if err.code >= 500 and attempt <= self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise NexusError(f"Nexus API {err.code}: {message}", err.code) from None
            except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError,
                    http.client.HTTPException, json.JSONDecodeError) as err:
                if attempt <= self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                reason = getattr(err, "reason", err)
                raise NexusError(f"Can't reach Nexus Mods: {reason}") from None

    # -- endpoints --------------------------------------------------------

    def validate(self) -> Account:
        data = self._get("/users/validate.json", cache=False)
        self._account = Account(
            user_id=int(data.get("user_id") or 0),
            name=data.get("name") or "?",
            is_premium=bool(data.get("is_premium")),
            is_supporter=bool(data.get("is_supporter")),
            profile_url=data.get("profile_url") or "",
        )
        return self._account

    @property
    def account(self) -> Account:
        return self._account or self.validate()

    def mod(self, game: str, mod_id: int) -> ModInfo:
        data = self._get(f"/games/{game}/mods/{int(mod_id)}.json")
        return ModInfo.from_api(game, data)

    def files(self, game: str, mod_id: int) -> list[dict]:
        data = self._get(f"/games/{game}/mods/{int(mod_id)}/files.json")
        return list((data or {}).get("files") or [])

    def download_links(self, game: str, mod_id: int, file_id: int, *,
                       key: str | None = None, expires: int | None = None) -> list[str]:
        """Return CDN URLs for a file, best first.

        Premium accounts need no ``key``/``expires``. Those come from an
        ``nxm://`` link made by clicking "Mod manager download" on the site.
        """
        try:
            data = self._get(
                f"/games/{game}/mods/{int(mod_id)}/files/{int(file_id)}/download_link.json",
                {"key": key, "expires": expires} if key else None, cache=False)
        except NexusError as err:
            if err.status == 403:
                raise NotPremiumError(
                    "Nexus only gives download links to Premium accounts (or to links "
                    "you click on the site). Check your key belongs to your Premium account.",
                    403) from None
            if err.status == 404:
                raise NexusError("That file is gone from Nexus (deleted or hidden).", 404) from None
            raise
        urls = []
        for item in data or []:
            uri = item.get("URI") if isinstance(item, dict) else None
            if uri:
                urls.append(_safe_url(uri))
        if not urls:
            raise NexusError("Nexus returned no download link for that file.")
        return urls


    def requirements(self, game: str, mod_id: int) -> list[Requirement] | None:
        """The mod's "Requirements" list, or None if Nexus couldn't say."""
        cache_key = f"req:{game}/{mod_id}"
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
        body = json.dumps({"query": REQUIREMENTS_QUERY,
                           "variables": {"modId": int(mod_id), "gameDomainName": game}}).encode()
        headers = dict(self._headers(), **{"Content-Type": "application/json"})
        req = urllib.request.Request(self.graphql_url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            nodes = data["data"]["modRequirements"]["nexusRequirements"]["nodes"]
        except Exception:
            return None
        out = []
        for node in nodes or []:
            try:
                mid = node.get("modId")
                out.append(Requirement(
                    mod_id=int(mid) if mid not in (None, "", 0, "0") else None,
                    name=node.get("modName") or "?",
                    url=node.get("url") or "",
                    notes=node.get("notes") or "",
                    external=bool(node.get("externalRequirement")),
                ))
            except (TypeError, ValueError, AttributeError):
                continue
        with self._lock:
            self._cache[cache_key] = out
        return out


def _error_message(err: urllib.error.HTTPError) -> str:
    try:
        body = err.read().decode("utf-8", "replace")
        data = json.loads(body)
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error") or body)[:300]
        return body[:300]
    except Exception:
        return err.reason if isinstance(err.reason, str) else str(err.code)


def _retry_after(err: urllib.error.HTTPError, attempt: int) -> float:
    value = (err.headers or {}).get("Retry-After")
    try:
        return min(float(value), 120.0)
    except (TypeError, ValueError):
        return min(5.0 * attempt, 60.0)


def _safe_url(uri: str) -> str:
    """CDN links sometimes contain spaces or non-ASCII file names."""
    parts = urllib.parse.urlsplit(uri)
    path = urllib.parse.quote(parts.path, safe="/%~!$&'()*+,;=:@")
    query = urllib.parse.quote(parts.query, safe="=&%~!$'()*+,;:@/?")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))
