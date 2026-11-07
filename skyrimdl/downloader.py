"""Download one file with resume, retries and progress."""

from __future__ import annotations

import http.client
import os
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .nexus import USER_AGENT

CHUNK = 1024 * 1024
ProgressFn = Callable[[int, int | None], None]  # (bytes done, total or None)


class Cancelled(Exception):
    pass


class DownloadError(RuntimeError):
    pass


def safe_file_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad or ord(c) < 32 else c for c in name).strip(" .")
    return cleaned or "download"


def download(urls: list[str] | str, dest: Path, *, partial_dir: Path,
             expected_size: int | None = None, progress: ProgressFn | None = None,
             cancel: threading.Event | None = None, retries: int = 5,
             timeout: float = 60.0) -> Path:
    """Fetch ``urls`` (tried in order) to ``dest``.

    The file is written to ``partial_dir`` first and moved into place only when
    complete, so a mod manager watching the folder never sees half a file.
    Stopping and starting again picks up where it left off.
    """
    if isinstance(urls, str):
        urls = [urls]
    partial_dir.mkdir(parents=True, exist_ok=True)
    part = partial_dir / (dest.name + ".part")
    last_error: Exception | None = None
    attempt = 0
    url_index = 0

    while attempt <= retries:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        url = urls[url_index % len(urls)]
        have = part.stat().st_size if part.exists() else 0
        if expected_size and have > expected_size:
            part.unlink()
            have = 0
        if expected_size and have == expected_size:
            break
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                if have and status != 206:
                    have = 0  # server ignored the range: start over
                length = resp.headers.get("Content-Length")
                total = expected_size
                if total is None and length is not None:
                    total = int(length) + (have if status == 206 else 0)
                mode = "ab" if have else "wb"
                done = have
                if progress:
                    progress(done, total)
                with open(part, mode) as out:
                    while True:
                        if cancel is not None and cancel.is_set():
                            raise Cancelled()
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            size = part.stat().st_size
            if expected_size and size != expected_size:
                if size < expected_size:
                    raise DownloadError(f"connection dropped at {size} of {expected_size} bytes")
                part.unlink()
                raise DownloadError(f"got {size} bytes, Nexus says the file is {expected_size}")
            if not expected_size and length is not None and status == 200 and size != int(length):
                raise DownloadError(f"connection dropped at {size} of {length} bytes")
            break
        except Cancelled:
            raise
        except urllib.error.HTTPError as err:
            last_error = err
            if err.code == 416 and part.exists():  # range past the end: start over
                part.unlink()
            elif err.code in (401, 403, 404, 410):
                url_index += 1  # link expired or mirror refused: try the next one
                if url_index >= len(urls):
                    raise DownloadError(f"the download server refused the file ({err.code})") from None
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError,
                http.client.HTTPException, DownloadError, OSError) as err:
            last_error = err
        attempt += 1
        if attempt <= retries:
            _sleep(min(2 ** attempt, 30), cancel)
    else:
        raise DownloadError(f"download failed after {retries} retries: {last_error}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    try:
        os.replace(part, dest)
    except OSError:
        shutil.move(str(part), str(dest))  # different drive
    return dest


def _sleep(seconds: float, cancel: threading.Event | None) -> None:
    if cancel is None:
        time.sleep(seconds)
    elif cancel.wait(seconds):
        raise Cancelled()
