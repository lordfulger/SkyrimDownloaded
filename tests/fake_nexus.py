"""A tiny stand-in for the Nexus API and CDN, for tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PAYLOADS = {
    101: b"A" * 300_000,      # SkyUI main
    201: b"B" * 50_000,       # textures 1K
    202: b"C" * 120_000,      # textures 2K
    203: b"D" * 7_000,        # optional patch
    204: b"E" * 1_000,        # old version
    301: b"F" * 1_100,        # SKSE: only size_kb given, like the real v1 API
    401: b"G" * 1_024, 402: b"H" * 1_024, 403: b"I" * 1_024, 404: b"J" * 1_024,
    501: b"K" * 1_024,
}

MODS = {
    12604: {"mod_id": 12604, "name": "SkyUI", "version": "5.2SE", "author": "schlangster",
            "summary": "Elegant, PC-friendly interface", "available": True, "status": "published",
            "category_id": 42},
    1000: {"mod_id": 1000, "name": "Pretty Textures", "version": "2.0", "author": "someone",
           "summary": "Textures", "available": True, "status": "published", "category_id": 29,
           "endorsement_count": 1234, "mod_downloads": 56789, "updated_timestamp": 1700000000,
           "description": "[b]Pretty textures[/b] for everything.<br />[size=4]Compatibility[/size]<br />"
                          "[list][*]Needs SkyUI for the menu.[*]Incompatible with "
                          "[url=https://www.nexusmods.com/skyrimspecialedition/mods/17230]Engine Fixes[/url] "
                          "(just for testing).[/list][img]https://example.com/a.png[/img]"},
    266: {"mod_id": 266, "name": "Unofficial Skyrim Special Edition Patch", "version": "4.3.2",
          "author": "Arthmoor", "available": True, "status": "published", "category_id": 84,
          "summary": "Fixes bugs.", "description": "Fixes lots of bugs."},
    30379: {"mod_id": 30379, "name": "SKSE64", "version": "2.2.6", "author": "ianpatt",
            "available": True, "status": "published", "category_id": 39},
    17230: {"mod_id": 17230, "name": "SSE Engine Fixes", "version": "7.0", "author": "aers",
            "available": True, "status": "published", "category_id": 39},
    999: {"mod_id": 999, "name": "Gone Mod", "version": "1", "available": False, "status": "removed"},
}

FILES = {
    12604: [
        {"file_id": 101, "name": "SkyUI_5_2_SE", "version": "5.2SE", "category_id": 1,
         "category_name": "MAIN", "is_primary": True, "size_in_bytes": len(PAYLOADS[101]),
         "file_name": "SkyUI_5_2_SE-12604-5-2SE.7z", "uploaded_timestamp": 1500000000,
         "description": "Main file"},
    ],
    1000: [
        {"file_id": 201, "name": "Pretty Textures 1K", "version": "2.0", "category_id": 1,
         "category_name": "MAIN", "is_primary": True, "size_in_bytes": len(PAYLOADS[201]),
         "file_name": "Pretty Textures 1K-1000-2-0.7z", "uploaded_timestamp": 1600000000,
         "description": "1K <b>performance</b> version<br>for low-end PCs"},
        {"file_id": 202, "name": "Pretty Textures 2K", "version": "2.0", "category_id": 1,
         "category_name": "MAIN", "is_primary": False, "size_in_bytes": len(PAYLOADS[202]),
         "file_name": "Pretty Textures 2K-1000-2-0.7z", "uploaded_timestamp": 1600000001,
         "description": "2K, looks better"},
        {"file_id": 203, "name": "USSEP Patch, for real", "version": "1.1", "category_id": 3,
         "category_name": "OPTIONAL", "is_primary": False, "size_in_bytes": len(PAYLOADS[203]),
         "file_name": "Patch-1000-1-1.zip", "uploaded_timestamp": 1600000002, "description": ""},
        {"file_id": 204, "name": "Pretty Textures 1K", "version": "1.0", "category_id": 4,
         "category_name": "OLD_VERSION", "is_primary": False, "size_in_bytes": len(PAYLOADS[204]),
         "file_name": "Pretty Textures 1K-1000-1-0.7z", "uploaded_timestamp": 1500000000,
         "description": "old"},
    ],
    266: [
        {"file_id": 501, "name": "USSEP", "version": "4.3.2", "category_id": 1, "is_primary": True,
         "size_kb": 1, "file_name": "USSEP-266-4-3-2.7z", "uploaded_timestamp": 1700000000,
         "description": ""},
    ],
    17230: [
        {"file_id": 401, "name": "SSE Engine Fixes for 1.5.97", "version": "6.2", "category_id": 1,
         "is_primary": False, "size_kb": 1, "file_name": "SSE Engine Fixes for 1.5.97-17230-6-2.7z",
         "uploaded_timestamp": 1690000000, "description": ""},
        {"file_id": 402, "name": "SSE Engine Fixes for 1.6.1170", "version": "7.0", "category_id": 1,
         "is_primary": True, "size_kb": 1, "file_name": "SSE Engine Fixes for 1.6.1170-17230-7-0.7z",
         "uploaded_timestamp": 1710000000, "description": ""},
        {"file_id": 403, "name": "Engine Fixes VR", "version": "6.1", "category_id": 1,
         "is_primary": False, "size_kb": 1, "file_name": "Engine Fixes VR-17230-6-1.7z",
         "uploaded_timestamp": 1680000000, "description": ""},
        {"file_id": 404, "name": "Part 2 - DLLs (all versions)", "version": "7.0", "category_id": 3,
         "is_primary": False, "size_kb": 1, "file_name": "Part 2-17230-7-0.7z",
         "uploaded_timestamp": 1710000001, "description": ""},
    ],
    30379: [
        {"file_id": 301, "name": "SKSE64 for AE", "version": "2.2.6", "category_id": 1,
         "is_primary": True, "size_kb": 1, "file_name": "skse64-30379-2-2-6.7z",
         "uploaded_timestamp": 1700000000, "description": ""},
    ],
}

GOOD_KEY = "test-key"
FREE_KEY = "free-key"


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeNexus/1"

    def log_message(self, *args):
        pass

    def _json(self, code, data, headers=None):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-RL-Daily-Remaining", "2400")
        self.send_header("X-RL-Hourly-Remaining", "99")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        state = self.server.state
        path = urlsplit(self.path).path
        state["requests"].append(self.path)
        if state.get("delay"):
            import time
            time.sleep(state["delay"])
        if path.startswith("/redirect/"):  # github.com/.../releases/latest -> the newest release page
            self.send_response(302)
            self.send_header("Location", state.get("redirect_to", "/"))
            self.end_headers()
            return
        if "/releases/tag/" in path:
            return self._json(200, {"page": path})
        if path.endswith("/releases/latest"):  # GitHub, for the update check
            tag = state.get("latest_tag", "v9.9.9")
            return self._json(200, {"tag_name": tag, "html_url": f"https://example.com/{tag}",
                                    "draft": False, "prerelease": False,
                                    "assets": [{"name": "SkyrimDownloadedSetup.exe", "size": 5678,
                                                "digest": "sha256:" + "cd" * 32,
                                                "browser_download_url": f"https://example.com/{tag}-setup.exe"},
                                               {"name": "SkyrimDownloaded.exe", "size": 1234,
                                                "digest": "sha256:" + "ab" * 32,
                                                "browser_download_url": f"https://example.com/{tag}.exe"}]})
        if path.startswith("/cdn/"):
            return self._cdn(int(path.split("/")[2]))
        if path.startswith("/pictures/"):
            body = _picture()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        key = self.headers.get("apikey")
        if key not in (GOOD_KEY, FREE_KEY):
            return self._json(401, {"message": "Please provide a valid API Key"})
        if state.get("fail_429", 0) > 0:
            state["fail_429"] -= 1
            return self._json(429, {"message": "slow down"}, {"Retry-After": "0"})
        parts = path.strip("/").split("/")
        if parts[1:] == ["games", "skyrimspecialedition", "mods", "updated.json"]:
            state.setdefault("updated_periods", []).append(self.path.split("period=")[-1])
            return self._json(200, state.get("updated", []))
        if parts[1:] == ["games", "skyrimspecialedition.json"]:
            return self._json(200, {"name": "Skyrim Special Edition", "categories": [
                {"category_id": 29, "name": "Environmental", "parent_category": 1},
                {"category_id": 42, "name": "User Interface", "parent_category": 1},
                {"category_id": 84, "name": "Patches", "parent_category": 1}]})
        # /v1/users/validate.json
        if parts[1:] == ["users", "validate.json"]:
            return self._json(200, {"user_id": 7, "name": "Dovahkiin", "is_premium": key == GOOD_KEY,
                                    "is_supporter": False, "profile_url": ""})
        # /v1/games/<g>/mods/<id>.json  | files.json | files/<fid>/download_link.json
        if len(parts) >= 5 and parts[1] == "games" and parts[3] == "mods":
            mod_id = int(parts[4].split(".")[0])
            if len(parts) == 5:
                if mod_id not in MODS:
                    return self._json(404, {"message": "No Mod Found"})
                return self._json(200, MODS[mod_id])
            if parts[5:] == ["files.json"]:
                files, updates = FILES.get(mod_id, []), []
                if state.get("new_upload") and mod_id == 1000:
                    # The author uploaded 2K v2.1: the old 2K moves to old versions and Nexus links
                    # old -> new; the patch file was deleted.
                    files = [dict(f) for f in files if f["file_id"] != 203]
                    for f in files:
                        if f["file_id"] == 202:
                            f.update(category_id=4, category_name="OLD_VERSION")
                    files.append({"file_id": 205, "name": "Pretty Textures 2K", "version": "2.1",
                                  "category_id": 1, "category_name": "MAIN", "is_primary": False,
                                  "size_in_bytes": 120_000, "file_name": "Pretty Textures 2K-1000-2-1.7z",
                                  "uploaded_timestamp": 1700000500, "description": "2K, looks better"})
                    updates = [{"old_file_id": 202, "new_file_id": 205, "old_file_name": "a",
                                "new_file_name": "b", "uploaded_timestamp": 1700000500}]
                return self._json(200, {"files": files, "file_updates": updates})
            if len(parts) == 8 and parts[7] == "download_link.json":
                if key != GOOD_KEY and "key=" not in self.path:
                    return self._json(403, {"message": "You don't have permission to get download "
                                                       "links from the API without visting nexusmods.com"})
                fid = int(parts[6])
                host = f"http://127.0.0.1:{self.server.server_port}"
                return self._json(200, [{"name": "Nexus CDN", "short_name": "Nexus CDN",
                                         "URI": f"{host}/cdn/{fid}/file name.7z"}])
        return self._json(404, {"message": "not found"})

    def _cdn(self, fid):
        state = self.server.state
        if state.get("cdn_fail", 0) > 0:  # the download server is down, this many times
            state["cdn_fail"] -= 1
            return self._json(503, {"message": "busy"})
        data = PAYLOADS[fid]
        start = 0
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
        chunk = data[start:]
        cut = state.get("cut_after")  # drop the connection part way, once
        self.send_response(206 if rng else 200)
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        if cut and not rng:
            state["cut_after"] = None
            self.wfile.write(chunk[:cut])
            self.wfile.flush()
            self.connection.shutdown(2)
            return
        self.wfile.write(chunk)


REQUIREMENTS = {
    1000: [
        {"id": "1", "gameId": "1704", "modId": "12604", "modName": "SkyUI", "notes": "",
         "url": "https://www.nexusmods.com/skyrimspecialedition/mods/12604", "externalRequirement": False},
        {"id": "2", "gameId": "1704", "modId": "30379", "modName": "SKSE64", "notes": "for the menus",
         "url": "https://www.nexusmods.com/skyrimspecialedition/mods/30379", "externalRequirement": False},
        {"id": "3", "gameId": "1704", "modId": None, "modName": "Some Outside Tool", "notes": "",
         "url": "https://example.com/tool", "externalRequirement": True},
    ],
}


def _cfile(mod_id, file_id, mod_name, file_name, optional=False):
    return {"fileId": file_id, "optional": optional,
            "file": {"fileId": file_id, "modId": mod_id, "name": file_name, "version": "1",
                     "mod": {"name": mod_name}, "game": {"domainName": "skyrimspecialedition"}}}


COLLECTION = {
    "revisionNumber": 7,
    "collection": {"name": "Pretty Skyrim | Lite", "slug": "abc123", "summary": "x",
                   "game": {"domainName": "skyrimspecialedition"}},
    "modFiles": [
        _cfile(12604, 101, "SkyUI", "SkyUI_5_2_SE"),
        _cfile(1000, 202, "Pretty Textures", "Pretty Textures 2K"),
        _cfile(1000, 203, "Pretty Textures", "USSEP Patch, for real"),
        _cfile(266, 501, "Unofficial Skyrim Special Edition Patch", "USSEP", optional=True),
    ],
    "externalResources": [{"name": "SKSE64 (#1)", "resourceUrl": "https://skse.silverlock.org", "optional": False}],
}


DLC_REQUIREMENTS = {
    1000: [{"gameExpansion": {"id": "1", "name": "Fishing"}, "notes": "for the fishing rods"}],
}


def _post(self):
    length = int(self.headers.get("Content-Length") or 0)
    raw = self.rfile.read(length) or b""
    self.server.state["requests"].append("POST " + self.path)
    if self.path.startswith("/v1/"):  # track / endorse (form posts)
        from urllib.parse import parse_qs
        self.server.state.setdefault("posted", []).append((urlsplit(self.path).path, parse_qs(raw.decode())))
        if self.headers.get("apikey") != GOOD_KEY:
            return self._json(401, {"message": "Please provide a valid API Key"})
        return self._json(200, {"message": "ok", "status": "Endorsed"})
    body = json.loads(raw or b"{}")
    if self.server.state.get("old_api") is None:  # the current API unless a test asks for the old one
        answered = _post_v2(self, body) if not self.server.state.get("graphql_down") else None
        if answered is not None:
            return answered
    if self.server.state.get("graphql_down"):
        return self._json(500, {"errors": [{"message": "down"}]})
    if "collectionRevision" in body.get("query", ""):
        slug = body.get("variables", {}).get("slug")
        if slug != "abc123":
            return self._json(200, {"errors": [{"message": "Collection not found"}], "data": None})
        return self._json(200, {"data": {"collectionRevision": COLLECTION}})
    mod_id = body.get("variables", {}).get("modId")
    nodes = REQUIREMENTS.get(mod_id, [])
    result = {"nexusRequirements": {"nodes": nodes}}
    if "dlcRequirements" in body.get("query", ""):
        if self.server.state.get("dlc_unsupported"):
            return self._json(200, {"errors": [{"message": "Cannot query field dlcRequirements"}], "data": None})
        result["dlcRequirements"] = DLC_REQUIREMENTS.get(mod_id, [])
    return self._json(200, {"data": {"modRequirements": result}})


def _discover_node(mid):
    if mid not in DISCOVER_MODS:  # a mod from the main fake data
        m = MODS[mid]
        return {"modId": mid, "uid": f"uid{mid}", "name": m["name"], "author": m.get("author", ""),
                "endorsements": 1, "downloads": 1, "createdAt": "", "updatedAt": "", "category": "",
                "adultContent": False, "status": "published", "summary": "", "thumbnailUrl": "", "version": "1",
                "modRequirements": {"nexusRequirements": {"nodes": []}}}
    m = DISCOVER_MODS[mid]
    return {"modId": mid, "uid": f"uid{mid}", "name": m["name"], "author": "someone", "endorsements": m["end"], "downloads": m["end"] * 10,
            "createdAt": "2026-10-01T00:00:00Z", "updatedAt": "2026-11-01T00:00:00Z", "category": "Patches",
            "adultContent": m.get("adult", False), "status": "published", "summary": "A mod.",
            "thumbnailUrl": "", "version": "1.0",
            "modRequirements": {"nexusRequirements": {"nodes": [
                {"modId": str(r), "modName": "x", "externalRequirement": False} for r in m["requires"]]}}}


def _post_v2(self, body):
    """Nexus's current API: requirements hang off mod(modId, gameId); mods() searches."""
    query, var = body.get("query", ""), body.get("variables", {})
    if "modsRequiringThisMod" in query:
        mid = int(var.get("modId"))
        nodes = [{"modId": str(k), "modName": v["name"], "gameId": "1704"}
                 for k, v in DISCOVER_MODS.items() if mid in v["requires"]]
        page = nodes[var.get("offset", 0):var.get("offset", 0) + var.get("count", 20)]
        return self._json(200, {"data": {"mod": {"modRequirements": {
            "modsRequiringThisMod": {"totalCount": len(nodes), "nodes": page}}}}})
    if "collectionsV2" in query:
        uid = next(f["modUid"][0]["value"] for f in var.get("f") or [] if "modUid" in f)
        mid = int(uid[3:])
        nodes = [{"slug": c["slug"], "name": c["name"], "endorsements": 10, "adultContent": False,
                  "latestPublishedRevision": {"modFiles": [
                      {"optional": False, "file": {"modId": m, "mod": {"name": f"Mod {m}"}}} for m in c["mods"]]}}
                 for c in COLLECTIONS if mid in c["mods"]]
        return self._json(200, {"data": {"collectionsV2": {"nodes": nodes}}})
    if "mods(filter" in query:
        filters = var.get("f") or []
        if "op: OR" in query:  # details of these mods
            ids = [int(f["modId"][0]["value"]) for f in filters if "modId" in f]
            nodes = [_discover_node(i) for i in ids if i in DISCOVER_MODS or i in MODS]
            return self._json(200, {"data": {"mods": {"totalCount": len(nodes), "nodes": nodes}}})
        self.server.state.setdefault("browse", []).append(var)
        adult = not any(f.get("adultContent") == {"value": False} for f in filters)
        nodes = [_discover_node(i) for i in DISCOVER_MODS if adult or not DISCOVER_MODS[i].get("adult")]
        nodes.sort(key=lambda n: -n["endorsements"])
        off, cnt = var.get("offset", 0), var.get("count", 20)
        return self._json(200, {"data": {"mods": {"totalCount": len(nodes), "nodes": nodes[off:off + cnt]}}})
    if "mod(modId" in query:  # requirements
        mid = int(var.get("modId"))
        result = {"nexusRequirements": {"nodes": REQUIREMENTS.get(mid, [])}}
        if "dlcRequirements" in query:
            if self.server.state.get("dlc_unsupported"):
                return self._json(200, {"errors": [{"message": "Cannot query field dlcRequirements"}], "data": None})
            result["dlcRequirements"] = DLC_REQUIREMENTS.get(mid, [])
        return self._json(200, {"data": {"mod": {"modRequirements": result}}})
    return None


COLLECTIONS = [
    {"slug": "c1", "name": "Pretty Setup", "mods": [12604, 266, 1000, 6001, 6002]},
    {"slug": "c2", "name": "Lite Setup", "mods": [12604, 266, 6001, 6003]},
    {"slug": "c3", "name": "Unrelated", "mods": [17230, 6002]},  # shares one mod: doesn't count
]

DISCOVER_MODS = {
    6001: {"name": "Goes Well Mod", "requires": [424242], "end": 300},
    6002: {"name": "Only Once Mod", "requires": [], "end": 200},
    6003: {"name": "Another Once Mod", "requires": [], "end": 100},
    5001: {"name": "SkyUI - USSEP Patch", "requires": [12604, 266], "end": 900},
    5002: {"name": "Cool SkyUI Addon", "requires": [12604], "end": 500},
    5003: {"name": "Needs Something Else", "requires": [12604, 424242], "end": 800},
    5004: {"name": "SkyUI Russian Translation", "requires": [12604], "end": 50},
    5005: {"name": "Spicy USSEP Addon", "requires": [266], "end": 700, "adult": True},
}


Handler.do_POST = _post


def _picture() -> bytes:
    """A small JPEG (with Pillow) or PNG picture for the info panel."""
    try:
        import io
        from PIL import Image
        img = Image.new("RGB", (640, 360), (70, 110, 160))
        for x in range(0, 640, 40):
            for y in range(0, 360, 40):
                img.putpixel((x, y), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        return buf.getvalue()
    except ImportError:
        import struct
        import zlib
        raw = b"".join(b"\x00" + bytes((70, 110, 160)) * 64 for _ in range(36))
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 36, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class FakeNexus:
    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.state = {"requests": []}
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def state(self):
        return self.httpd.state

    @property
    def base(self):
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
