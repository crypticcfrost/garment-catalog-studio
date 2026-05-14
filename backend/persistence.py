"""
Session persistence: minimal on-disk manifest + optional full JSON in Redis.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from config import UPLOAD_DIR
from models import ImageItem, Session, StyleGroup
from remote_store import redis_enabled, redis_get, redis_set, session_redis_key, session_ttl_seconds

log = logging.getLogger(__name__)


def manifest_path(session_id: str) -> Path:
    return UPLOAD_DIR / session_id / "_session.json"


def save_minimal_manifest(session: Session) -> None:
    """Lightweight manifest for disk-only recovery (images + paths, no groups)."""
    try:
        data: dict[str, Any] = {
            "id": session.id,
            "status": session.status if session.status != "processing" else "idle",
            "images": {
                img_id: {
                    "id": img.id,
                    "filename": img.filename,
                    "original_path": img.original_path,
                    "original_public_url": getattr(img, "original_public_url", None),
                }
                for img_id, img in session.images.items()
            },
        }
        manifest_path(session.id).parent.mkdir(parents=True, exist_ok=True)
        manifest_path(session.id).write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        log.exception("save_minimal_manifest failed for %s", session.id)


def serialize_session(session: Session) -> str:
    d: dict[str, Any] = {
        "id": session.id,
        "status": session.status,
        "images": {k: json.loads(v.model_dump_json()) for k, v in session.images.items()},
        "groups": {k: json.loads(v.model_dump_json()) for k, v in session.groups.items()},
        "pipeline_steps": session.pipeline_steps,
        "ppt_path": session.ppt_path,
        "ppt_public_url": session.ppt_public_url,
        "version": session.version,
        "created_at": session.created_at,
        "error": session.error,
    }
    return json.dumps(d)


def deserialize_session(data: dict[str, Any]) -> Session:
    s = Session(
        id=str(data["id"]).strip().upper(),
        status=data.get("status", "idle"),
        pipeline_steps=data.get("pipeline_steps", []),
        ppt_path=data.get("ppt_path"),
        ppt_public_url=data.get("ppt_public_url"),
        version=int(data.get("version", 1)),
        created_at=data.get("created_at", ""),
        error=data.get("error"),
    )
    for kid, raw in data.get("images", {}).items():
        s.images[kid] = ImageItem.model_validate(raw)
    for gid, raw in data.get("groups", {}).items():
        s.groups[gid] = StyleGroup.model_validate(raw)
    return s


def save_session(session: Session) -> None:
    """Persist manifest to disk and full snapshot to Redis when configured."""
    save_minimal_manifest(session)
    if not redis_enabled():
        return
    try:
        redis_set(
            session_redis_key(session.id),
            serialize_session(session),
            ex_seconds=session_ttl_seconds(),
        )
    except Exception:
        log.exception("save_session redis failed for %s", session.id)


def load_session_from_redis(session_id: str) -> Optional[Session]:
    if not redis_enabled():
        return None
    raw = redis_get(session_redis_key(session_id))
    if not raw:
        return None
    try:
        return deserialize_session(json.loads(raw))
    except Exception:
        log.exception("load_session_from_redis failed for %s", session_id)
        return None


def load_session_from_disk_manifest(session_id: str) -> Optional[Session]:
    """Legacy hydrate: images only if local files exist."""
    manifest = manifest_path(session_id)
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if str(data.get("id", "")).upper() != str(session_id).upper():
            return None
        session = Session(id=session_id)
        session.status = data.get("status", "idle")
        for img_id, img_data in data.get("images", {}).items():
            path = img_data.get("original_path", "")
            pub = img_data.get("original_public_url")
            if path and Path(path).is_file():
                session.images[img_id] = ImageItem(
                    id=img_data["id"],
                    filename=img_data["filename"],
                    original_path=path,
                    original_public_url=pub,
                )
            elif pub:
                session.images[img_id] = ImageItem(
                    id=img_data["id"],
                    filename=img_data["filename"],
                    original_path=path or pub,
                    original_public_url=pub,
                )
        if session.images:
            return session
    except Exception:
        log.exception("load_session_from_disk_manifest failed for %s", session_id)
    return None


def load_session_any(session_id: str) -> Optional[Session]:
    """Prefer Redis full snapshot, then disk manifest."""
    s = load_session_from_redis(session_id)
    if s is not None:
        return s
    return load_session_from_disk_manifest(session_id)


def lookup_original_public_url(session_id: str, filename: str) -> Optional[str]:
    """Resolve a public blob URL for an upload filename without holding the session in memory."""
    s = load_session_from_redis(session_id)
    if not s:
        return None
    for img in s.images.values():
        if Path(img.original_path).name == filename or img.filename == filename:
            u = getattr(img, "original_public_url", None)
            if u:
                return u
    return None


def lookup_processed_public_url(session_id: str, image_id: str) -> Optional[str]:
    s = load_session_from_redis(session_id)
    if not s:
        return None
    img = s.images.get(image_id)
    if not img:
        return None
    u = getattr(img, "processed_public_url", None)
    return u or None
