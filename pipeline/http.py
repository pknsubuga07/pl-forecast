"""Small HTTP helper: retries, polite delays, and a raw-file cache."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from .config import HTTP_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """A data source was unreachable or returned something we could not parse."""


_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})
_last_request: dict[str, float] = {}


def get(url: str, *, params: dict | None = None, retries: int = 3, min_interval: float = 1.0) -> requests.Response:
    """GET with retries and a per-host minimum interval between requests."""
    host = url.split("/")[2]
    wait = min_interval - (time.monotonic() - _last_request.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            _last_request[host] = time.monotonic()
            resp = _session.get(url, params=params, timeout=HTTP_TIMEOUT, allow_redirects=True)
            if resp.status_code == 404:
                return resp
            if resp.status_code >= 500 or resp.status_code == 429:
                raise SourceError(f"{url} returned HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp
        except (requests.RequestException, SourceError) as exc:
            err = exc
            log.warning("GET %s failed (attempt %d/%d): %s", url, attempt, retries, exc)
            time.sleep(2 * attempt)
    raise SourceError(f"GET {url} failed after {retries} attempts: {err}")


def fetch_cached(url: str, dest: Path, *, refresh: bool, params: dict | None = None, min_interval: float = 1.0) -> Path | None:
    """Download url to dest unless dest exists and refresh is False. Returns None on 404."""
    if dest.exists() and not refresh:
        return dest
    resp = get(url, params=params, min_interval=min_interval)
    if resp.status_code == 404:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(resp.content)
    tmp.replace(dest)
    return dest
