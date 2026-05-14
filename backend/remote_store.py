"""
Optional shared storage for Vercel serverless:

- Upstash / Vercel Redis REST (UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN,
  or legacy KV_REST_API_URL + KV_REST_API_TOKEN): full session JSON so any instance
  can load the same session.
- Vercel Blob (BLOB_READ_WRITE_TOKEN): durable image/PPT bytes with public URLs.

If these env vars are unset, helpers no-op or return False and the app uses local disk only.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

BLOB_API_VERSION = "12"
BLOB_API_BASE = (os.getenv("VERCEL_BLOB_API_URL") or "https://vercel.com/api/blob").strip().rstrip("/")


def _redis_credentials() -> tuple[Optional[str], Optional[str]]:
    url = (
        os.getenv("UPSTASH_REDIS_REST_URL")
        or os.getenv("KV_REST_API_URL")
        or ""
    ).strip().rstrip("/")
    token = (
        os.getenv("UPSTASH_REDIS_REST_TOKEN")
        or os.getenv("KV_REST_API_TOKEN")
        or ""
    ).strip()
    if url and token:
        return url, token
    return None, None


def redis_enabled() -> bool:
    u, t = _redis_credentials()
    return bool(u and t)


def redis_command(cmd: list[Any]) -> dict[str, Any]:
    url, token = _redis_credentials()
    if not url or not token:
        raise RuntimeError("Redis REST not configured")
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=cmd,
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()


def redis_get(key: str) -> Optional[str]:
    try:
        data = redis_command(["GET", key])
        v = data.get("result")
        if v is None:
            return None
        return v if isinstance(v, str) else str(v)
    except Exception:
        log.exception("redis GET failed for %s", key)
        return None


def redis_set(key: str, value: str, ex_seconds: Optional[int] = None) -> None:
    try:
        cmd: list[Any] = ["SET", key, value]
        if ex_seconds is not None and ex_seconds > 0:
            cmd.extend(["EX", ex_seconds])
        redis_command(cmd)
    except Exception:
        log.exception("redis SET failed for %s", key)


def session_redis_key(session_id: str) -> str:
    return f"garment:session:{session_id.strip().upper()}"


def blob_enabled() -> bool:
    return bool(os.getenv("BLOB_READ_WRITE_TOKEN", "").strip())


def blob_put(pathname: str, data: bytes, content_type: str, access: str = "public") -> dict[str, Any]:
    token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN not set")
    q = urllib.parse.urlencode({"pathname": pathname})
    url = f"{BLOB_API_BASE}/?{q}"
    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-version": BLOB_API_VERSION,
        "x-content-length": str(len(data)),
        "x-vercel-blob-access": access,
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1",
        "x-content-type": content_type,
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.put(url, content=data, headers=headers)
    if not resp.is_success:
        log.error("blob put failed %s %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
    return resp.json()


def session_ttl_seconds() -> Optional[int]:
    raw = os.getenv("GARMENT_SESSION_REDIS_TTL_SECONDS", "").strip()
    if not raw:
        return 7 * 24 * 3600  # 7 days
    try:
        return max(60, int(raw))
    except ValueError:
        return 7 * 24 * 3600
