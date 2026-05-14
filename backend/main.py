import asyncio
import logging
import mimetypes
import os
import re
import uuid
import json
from pathlib import Path
from typing import Callable, List
from urllib.parse import quote, unquote

import aiofiles
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

import persistence
from models import Session, ImageItem, ImageStatus
from ws_manager import ConnectionManager
from pipeline import run_pipeline
from config import UPLOAD_DIR, OUTPUT_DIR, MAX_IMAGE_SIZE_MB
from remote_store import blob_enabled, blob_put, redis_enabled


class StripBackendPrefixMiddleware:
    """
    Vercel experimentalServices mounts this app under routePrefix (e.g. /_/backend).
    Incoming ASGI paths are often the full URL path, so strip the prefix before routing.
    """

    def __init__(self, app: Callable, prefix: str):
        self.app = app
        self.prefix = (prefix or "").rstrip("/")

    async def __call__(self, scope, receive, send):
        if self.prefix and scope["type"] in ("http", "websocket"):
            path = scope.get("path") or ""
            new_path = None
            if path.startswith(self.prefix + "/"):
                new_path = path[len(self.prefix) :] or "/"
            elif path == self.prefix:
                new_path = "/"
            if new_path is not None:
                scope = dict(scope)
                scope["path"] = new_path
        await self.app(scope, receive, send)


app = FastAPI(title="Garment Catalog Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

log = logging.getLogger(__name__)

manager = ConnectionManager()
sessions: dict[str, Session] = {}


def _canon_session_id(session_id: str) -> str:
    """Session ids are always stored uppercase to match create_session and disk folders."""
    return session_id.strip().upper()


# ── Session persistence ───────────────────────────────────────────────────────


def _restore_sessions() -> None:
    """On startup, rebuild in-memory sessions from any manifests on disk."""
    try:
        if not UPLOAD_DIR.is_dir():
            return
    except OSError:
        return
    for session_dir in UPLOAD_DIR.iterdir():
        if not session_dir.is_dir():
            continue
        sid = _canon_session_id(session_dir.name)
        if sid in sessions:
            continue
        s = persistence.load_session_from_disk_manifest(sid)
        if s:
            sessions[sid] = s


@app.on_event("startup")
async def _on_startup():
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        if not redis_enabled():
            log.warning(
                "Vercel runtime without Redis REST (UPSTASH_REDIS_REST_URL + "
                "UPSTASH_REDIS_REST_TOKEN or KV_REST_*): sessions may not survive "
                "routing to a different serverless instance.",
            )
        if not blob_enabled():
            log.warning(
                "Vercel runtime without BLOB_READ_WRITE_TOKEN: uploaded image bytes "
                "live only on the instance that received the upload unless files are on shared disk.",
            )
    try:
        _restore_sessions()
    except Exception:
        log.exception("session restore on startup failed (non-fatal)")

ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


# ── Session management ────────────────────────────────────────────────────────

@app.post("/api/sessions")
async def create_session():
    sid = str(uuid.uuid4())[:8].upper()
    session = Session(id=sid)
    sessions[sid] = session
    try:
        (UPLOAD_DIR / sid).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / sid).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.exception("create_session: could not mkdir for %s", sid)
        sessions.pop(sid, None)
        raise HTTPException(
            503,
            detail="Storage is not writable on this host. For Vercel, ensure VERCEL is set and "
            "TMPDIR is writable, or set GARMENT_STORAGE_ROOT to a writable directory.",
        ) from e
    persistence.save_session(session)
    return {"session_id": sid}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    s = _get_session(session_id)
    return JSONResponse(json.loads(s.model_dump_json()))


@app.get("/api/sessions")
async def list_sessions():
    """Return all active sessions so the frontend can reconnect after a page reload."""
    return {
        "sessions": [
            {
                "session_id": sid,
                "status":     s.status,
                "images":     len(s.images),
                "groups":     len(s.groups),
            }
            for sid, s in sessions.items()
        ]
    }


@app.get("/api/sessions/{session_id}/status")
async def get_status(session_id: str):
    s = _get_session(session_id)
    return {
        "status": s.status,
        "images": len(s.images),
        "groups": len(s.groups),
        "pipeline_steps": s.pipeline_steps,
        "ppt_ready": s.ppt_path is not None or bool(getattr(s, "ppt_public_url", None)),
        "version": s.version,
    }


def _session_poll_snapshot(session_id: str, s: Session) -> dict:
    """
    Full session view for HTTP polling (Vercel has no long-lived WebSocket to Python).
    Shape matches what the SPA needs to replace images / groups / pipeline / export state.
    """
    images: dict = {}
    for iid, img in s.images.items():
        fname = Path(img.original_path).name
        gd = img.garment_data
        pub_orig = getattr(img, "original_public_url", None)
        preview = pub_orig or _public_upload_url(session_id, fname)
        pub_proc = getattr(img, "processed_public_url", None)
        proc_url = None
        if pub_proc:
            proc_url = pub_proc
        elif img.processed_path:
            proc_url = _public_processed_url(session_id, iid)
        images[iid] = {
            "id": img.id,
            "filename": img.filename,
            "status": img.status.value if hasattr(img.status, "value") else str(img.status),
            "image_type": img.image_type.value if img.image_type else None,
            "style_id": img.style_id,
            "confidence": img.confidence,
            "garment_data": json.loads(gd.model_dump_json()) if gd else None,
            "error_message": img.error_message,
            "description": img.description,
            "colors": img.colors or [],
            "preview_url": preview,
            "processed_url": proc_url,
        }

    groups: dict = {}
    for gid, grp in s.groups.items():
        gdata = grp.garment_data
        groups[gid] = {
            "id": gid,
            "style_id": grp.style_id,
            "garment_type": grp.garment_type,
            "images": list(grp.images),
            "garment_data": json.loads(gdata.model_dump_json()) if gdata else None,
            "slide_number": grp.slide_number,
        }

    ppt_pub = getattr(s, "ppt_public_url", None)
    if ppt_pub:
        ppt_url = ppt_pub
    elif s.ppt_path:
        ppt_url = f"/api/sessions/{session_id}/download"
    else:
        ppt_url = None

    return {
        "status": s.status,
        "images": images,
        "groups": groups,
        "pipeline_steps": s.pipeline_steps or [],
        "ppt_url": ppt_url,
        "version": s.version,
    }


@app.get("/api/sessions/{session_id}/state")
async def get_session_state(session_id: str):
    """
    Full session snapshot for HTTP polling.
    Never returns 404 for a missing in-memory session: serverless may hit a different
    instance than the one that created the session (reply with session_lost instead).
    """
    sid = _canon_session_id(session_id)
    if sid not in sessions:
        _hydrate_session_from_manifest(sid)
    if sid not in sessions:
        return {
            "status": "idle",
            "session_lost": True,
            "images": {},
            "groups": {},
            "pipeline_steps": [],
            "ppt_url": None,
            "version": 0,
        }
    s = sessions[sid]
    return _session_poll_snapshot(sid, s)


def _public_upload_url(session_id: str, disk_fname: str) -> str:
    """Browser URL for an uploaded file (served via API so Vercel routes hit Python)."""
    return f"/api/sessions/{session_id}/file/upload/{quote(disk_fname, safe='')}"


def _public_processed_url(session_id: str, image_id: str) -> str:
    return f"/api/sessions/{session_id}/file/processed/{image_id}"


@app.get("/api/sessions/{session_id}/file/upload/{filename}")
async def serve_session_upload(session_id: str, filename: str):
    """Serve original upload bytes (no in-memory session required; path must exist on this host)."""
    sid = _canon_session_id(session_id)
    _assert_valid_session_dir_name(sid)
    raw = unquote(filename)
    if "/" in raw or "\\" in raw or raw.startswith(".."):
        raise HTTPException(400, "Invalid filename")
    name = Path(raw).name
    path = (UPLOAD_DIR / sid / name).resolve()
    base = (UPLOAD_DIR / sid).resolve()
    if str(path).startswith(str(base)) and path.is_file():
        return FileResponse(path, filename=name)
    remote = persistence.lookup_original_public_url(sid, name)
    if remote:
        return RedirectResponse(remote, status_code=302)
    raise HTTPException(404)


@app.get("/api/sessions/{session_id}/file/processed/{image_id}")
async def serve_session_processed(session_id: str, image_id: str):
    """Serve processed JPEG for an image id (no in-memory session required)."""
    sid = _canon_session_id(session_id)
    _assert_valid_session_dir_name(sid)
    if not re.match(r"^[0-9a-fA-F]{8}$", image_id):
        raise HTTPException(400, "Invalid image id")
    path = (OUTPUT_DIR / sid / "processed" / f"{image_id}_processed.jpg").resolve()
    base = (OUTPUT_DIR / sid / "processed").resolve()
    if str(path).startswith(str(base)) and path.is_file():
        return FileResponse(path, media_type="image/jpeg", filename=f"{image_id}_processed.jpg")
    remote = persistence.lookup_processed_public_url(sid, image_id)
    if remote:
        return RedirectResponse(remote, status_code=302)
    raise HTTPException(404)


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/upload")
async def upload_images(session_id: str, files: List[UploadFile] = File(...)):
    s = _require_session(session_id)
    sid = s.id
    uploaded = []

    for file in files:
        # Basic validation
        if file.content_type not in ALLOWED_TYPES:
            continue
        content = await file.read()
        if len(content) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
            continue

        img_id = str(uuid.uuid4())[:8]
        ext = Path(file.filename).suffix or ".jpg"
        fname = f"{img_id}{ext}"
        fpath = UPLOAD_DIR / sid / fname

        async with aiofiles.open(fpath, "wb") as f:
            await f.write(content)

        item = ImageItem(
            id=img_id,
            filename=file.filename,
            original_path=str(fpath),
        )
        if blob_enabled():
            try:
                ctype = file.content_type or mimetypes.guess_type(fname)[0] or "image/jpeg"
                pathname = f"garment-catalog/{sid}/original/{fname}"
                meta = await asyncio.to_thread(blob_put, pathname, content, ctype)
                item.original_public_url = meta.get("url")
            except Exception:
                log.exception("blob upload failed session=%s fname=%s", sid, fname)

        s.images[img_id] = item
        uploaded.append(img_id)

        thumb = item.original_public_url or _public_upload_url(sid, fname)
        await manager.send_event(sid, "image_uploaded", {
            "image_id":  img_id,
            "filename":  file.filename,
            "status":    "uploaded",
            "thumbnail": thumb,
        })

    persistence.save_session(s)
    return {"uploaded": uploaded, "total": len(s.images)}


# ── Pipeline ──────────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/process")
async def start_processing(session_id: str, background_tasks: BackgroundTasks):
    s = _require_session(session_id)
    if not s.images:
        raise HTTPException(400, "No images uploaded")
    if s.status == "processing":
        raise HTTPException(400, "Already processing")
    s.status = "processing"
    persistence.save_session(s)
    background_tasks.add_task(run_pipeline, s, manager)
    return {"status": "started", "images": len(s.images)}


# ── Manual reclassification (drag-and-drop) ───────────────────────────────────

@app.patch("/api/sessions/{session_id}/images/{image_id}/reclassify")
async def reclassify_image(session_id: str, image_id: str, body: dict):
    s = _require_session(session_id)
    img = s.images.get(image_id)
    if not img:
        raise HTTPException(404, "Image not found")

    from models import ImageType
    new_type = body.get("image_type")
    new_group = body.get("group_id")

    if new_type:
        try:
            img.image_type = ImageType(new_type)
        except ValueError:
            pass

    if new_group and new_group in s.groups:
        # Remove from current group
        for g in s.groups.values():
            if image_id in g.images:
                g.images.remove(image_id)
        s.groups[new_group].images.append(image_id)

    await manager.send_event(session_id, "image_reclassified", {
        "image_id":   image_id,
        "image_type": img.image_type.value if img.image_type else "unknown",
        "group_id":   new_group,
    })
    persistence.save_session(s)
    return {"ok": True}


# ── Retry failed image ────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/images/{image_id}/retry")
async def retry_image(session_id: str, image_id: str, background_tasks: BackgroundTasks):
    s = _require_session(session_id)
    img = s.images.get(image_id)
    if not img:
        raise HTTPException(404, "Image not found")

    from pipeline.classifier import classify_image
    img.status = ImageStatus.CLASSIFYING
    img.retry_count += 1

    async def _retry():
        from models import ImageType, GarmentData
        result = await classify_image(img.original_path)
        type_map = {
            "front": ImageType.FRONT, "back": ImageType.BACK,
            "detail": ImageType.DETAIL, "spec_label": ImageType.SPEC_LABEL,
        }
        img.image_type = type_map.get(result.get("image_type", ""), ImageType.UNKNOWN)
        img.style_id   = result.get("style_id")
        img.confidence = result.get("confidence", 0.0)
        img.status     = ImageStatus.CLASSIFIED
        await manager.send_event(session_id, "image_classified", {
            "image_id":   image_id,
            "image_type": img.image_type.value,
            "confidence": img.confidence,
            "status":     "classified",
            "retry":      True,
        })

    background_tasks.add_task(_retry)
    return {"status": "retrying"}


# ── Download ──────────────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/download")
async def download_ppt(session_id: str):
    s = _require_session(session_id)
    pub = getattr(s, "ppt_public_url", None)
    if pub:
        return RedirectResponse(pub, status_code=302)
    if not s.ppt_path or not Path(s.ppt_path).exists():
        raise HTTPException(400, "PPT not yet generated")
    return FileResponse(
        s.ppt_path,
        filename=f"garment_catalog_{_canon_session_id(session_id)}_v{s.version}.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.get("/api/sessions/{session_id}/slides")
async def get_slide_list(session_id: str):
    s = _require_session(session_id)
    groups_data = []
    for g in s.groups.values():
        groups_data.append({
            "group_id":     g.id,
            "style_id":     g.style_id,
            "garment_type": g.garment_type,
            "slide_number": g.slide_number,
            "garment_data": g.garment_data.model_dump() if g.garment_data else {},
            "image_count":  len(g.images),
        })
    return {"groups": groups_data, "ppt_ready": s.ppt_path is not None or bool(getattr(s, "ppt_public_url", None))}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str):
    sid = _canon_session_id(session_id)
    await manager.connect(websocket, sid)
    try:
        # Send current session state on connect
        if sid in sessions:
            s = sessions[sid]
            await manager.send_event(sid, "session_state", {
                "status":         s.status,
                "images":         {k: json.loads(v.model_dump_json()) for k, v in s.images.items()},
                "groups":         {k: json.loads(v.model_dump_json()) for k, v in s.groups.items()},
                "pipeline_steps": s.pipeline_steps,
                "ppt_ready":      s.ppt_path is not None,
            }, specific_ws=websocket)

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket, sid)


# ── Static files ──────────────────────────────────────────────────────────────

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")


# ── Helpers ───────────────────────────────────────────────────────────────────

_SESSION_ID_DIR_RE = re.compile(r"^[0-9a-fA-F]{8}$", re.I)


def _assert_valid_session_dir_name(session_id: str) -> None:
    """Session ids are 8-char hex folder names under uploads/outputs."""
    if not _SESSION_ID_DIR_RE.match(session_id):
        raise HTTPException(400, "Invalid session id")


def _require_session(session_id: str) -> Session:
    """
    Load session for a mutating request. Uses 503 (not 404) when the session is missing
    after hydrate — on serverless, another instance may hold the in-memory session.
    """
    sid = _canon_session_id(session_id)
    if sid not in sessions:
        _hydrate_session_from_manifest(sid)
    if sid not in sessions:
        raise HTTPException(
            503,
            detail="Session not available on this server instance. Retry shortly or refresh the page.",
        )
    return sessions[sid]


def _get_session(session_id: str) -> Session:
    sid = _canon_session_id(session_id)
    if sid not in sessions:
        _hydrate_session_from_manifest(sid)
    if sid not in sessions:
        raise HTTPException(404, f"Session '{session_id}' not found")
    return sessions[sid]


def _hydrate_session_from_manifest(session_id: str) -> None:
    """Re-load a session from Redis (full) or disk manifest when missing from memory."""
    sid = _canon_session_id(session_id)
    if sid in sessions:
        return
    s = persistence.load_session_any(sid)
    if s:
        if s.id != sid:
            s.id = sid
        sessions[sid] = s


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


# Strip /_/backend (or VERCEL_BACKEND_PREFIX) from incoming paths so routes match /api/...
# Do not gate on VERCEL — that env is not guaranteed on all Python runtimes.
_prefix = os.getenv("VERCEL_BACKEND_PREFIX", "/_/backend").strip()
if _prefix:
    app = StripBackendPrefixMiddleware(app, _prefix)
