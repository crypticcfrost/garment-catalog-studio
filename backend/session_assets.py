"""Download remote originals to local temp paths before vision / PIL steps."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from config import UPLOAD_DIR
from models import ImageItem, Session

log = logging.getLogger(__name__)


async def ensure_session_images_local(session: Session) -> None:
    """Ensure every image has a readable local file path (download from blob URL if needed)."""
    sid = session.id
    dest_dir = UPLOAD_DIR / sid
    dest_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=120.0) as client:
        for img in session.images.values():
            await _ensure_one_local(client, sid, img)


async def _ensure_one_local(client: httpx.AsyncClient, session_id: str, img: ImageItem) -> None:
    path = Path(img.original_path)
    if path.is_file():
        return

    url = getattr(img, "original_public_url", None) or None
    if not url and str(img.original_path).startswith(("http://", "https://")):
        url = img.original_path
    if not url:
        log.warning("image %s has no local file and no remote URL", img.id)
        return

    fname = path.name if path.name else Path(img.filename).name
    if not fname or fname == ".":
        fname = f"{img.id}.jpg"
    dest = (UPLOAD_DIR / session_id / fname).resolve()
    base = (UPLOAD_DIR / session_id).resolve()
    if not str(dest).startswith(str(base)):
        return

    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        dest.write_bytes(r.content)
        img.original_path = str(dest)
    except Exception:
        log.exception("failed to download original for image %s from %s", img.id, url)
