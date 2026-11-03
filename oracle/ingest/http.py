"""Polite HTTP layer with on-disk caching, retries and bounded concurrency."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

import httpx

from ..config import settings

_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _cache_path(key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return settings.cache_dir / "http" / f"{digest}.json"


def read_cache(key: str, ttl_seconds: int | None) -> Any | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    if ttl_seconds is not None and time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cache(key: str, payload: Any) -> None:
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    cache_key: str | None = None,
    ttl: int = 900,
    retries: int = 3,
    headers: dict | None = None,
) -> Any:
    key = cache_key or url
    cached = read_cache(key, ttl)
    if cached is not None:
        return cached
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            r = await client.get(url, headers={**_HEADERS, **(headers or {})})
            r.raise_for_status()
            payload = r.json()
            write_cache(key, payload)
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_error}")


async def fetch_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    cache_key: str | None = None,
    ttl: int = 1800,
    retries: int = 2,
) -> str:
    key = (cache_key or url) + "#text"
    cached = read_cache(key, ttl)
    if cached is not None:
        return cached.get("text", "")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            r = await client.get(url, headers=_HEADERS)
            r.raise_for_status()
            text = r.text
            write_cache(key, {"text": text})
            return text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_error}")


async def gather_limited(
    factories: Iterable[Callable[[], Awaitable[Any]]],
    limit: int = 6,
    on_error: Callable[[Exception], None] | None = None,
) -> list[Any]:
    semaphore = asyncio.Semaphore(limit)

    async def run(factory):
        async with semaphore:
            try:
                return await factory()
            except Exception as exc:  # noqa: BLE001
                if on_error:
                    on_error(exc)
                return None

    return await asyncio.gather(*(run(f) for f in factories))


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.request_timeout,
        follow_redirects=True,
        headers=_HEADERS,
        limits=httpx.Limits(max_connections=12, max_keepalive_connections=8),
    )
