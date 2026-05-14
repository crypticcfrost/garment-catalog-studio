import logging
import os
import uuid
import json
from pathlib import Path
from typing import Callable, List

import aiofiles
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from models import Session, ImageItem, ImageStatus
from ws_manager import ConnectionManager
from pipeline import run_pipeline
from config import UPLOAD_DIR, OUTPUT_DIR, MAX_IMAGE_SIZE_MB


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


# ── Session persistence helpers ───────────────────────────────────────────────

def _manifest_path(session_id: str) -> Path:
    return UPLOAD_DIR / session_id / "_session.json"


def _save_session_manifest(session: Session) -> None:
    """Write a lightweight manifest so sessions survive hot-reloads / restarts."""
    try:
        data = {
            "id": session.id,
            "status": session.status if session.status != "processing" else "idle",
            "images": {
                img_id: {
                    "id": img.id,
                    "filename": img.filename,
                    "original_path": img.original_path,
                }
                for img_id, img in session.images.items()
            },
        }
        _manifest_path(session.id).write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass  # non-fatal


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
        manifest = session_dir / "_session.json"
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            sid = data["id"]
            if sid in sessions:
                continue  # already loaded
            session = Session(id=sid)
            session.status = data.get("status", "idle")
            for img_id, img_data in data.get("images", {}).items():
                path = img_data.get("original_path", "")
                if path and Path(path).exists():
                    session.images[img_id] = ImageItem(
                        id=img_data["id"],
                        filename=img_data["filename"],
                        original_path=path,
                    )
            if session.images:          # only restore if images are still on disk
                sessions[sid] = session
        except Exception:
            pass


@app.on_event("startup")
async def _on_startup():
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
    _save_session_manifest(session)
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
        "ppt_ready": s.ppt_path is not None,
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
            "preview_url": f"/uploads/{session_id}/{fname}",
            "processed_url": (
                f"/outputs/{session_id}/processed/{iid}_processed.jpg"
                if img.processed_path
                else None
            ),
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

    ppt_url = f"/api/sessions/{session_id}/download" if s.ppt_path else None

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
    """Full session snapshot for clients that cannot use WebSockets (e.g. Vercel serverless)."""
    s = _get_session(session_id)
    return _session_poll_snapshot(session_id, s)


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/upload")
async def upload_images(session_id: str, files: List[UploadFile] = File(...)):
    s = _get_session(session_id)
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
        fpath = UPLOAD_DIR / session_id / fname

        async with aiofiles.open(fpath, "wb") as f:
            await f.write(content)

        item = ImageItem(
            id=img_id,
            filename=file.filename,
            original_path=str(fpath),
        )
        s.images[img_id] = item
        uploaded.append(img_id)

        await manager.send_event(session_id, "image_uploaded", {
            "image_id":  img_id,
            "filename":  file.filename,
            "status":    "uploaded",
            "thumbnail": f"/uploads/{session_id}/{fname}",
        })

    _save_session_manifest(s)   # persist so a hot-reload doesn't lose the upload
    return {"uploaded": uploaded, "total": len(s.images)}


# ── Pipeline ──────────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/process")
async def start_processing(session_id: str, background_tasks: BackgroundTasks):
    s = _get_session(session_id)
    if not s.images:
        raise HTTPException(400, "No images uploaded")
    if s.status == "processing":
        raise HTTPException(400, "Already processing")
    s.status = "processing"
    background_tasks.add_task(run_pipeline, s, manager)
    return {"status": "started", "images": len(s.images)}


# ── Manual reclassification (drag-and-drop) ───────────────────────────────────

@app.patch("/api/sessions/{session_id}/images/{image_id}/reclassify")
async def reclassify_image(session_id: str, image_id: str, body: dict):
    s = _get_session(session_id)
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
    return {"ok": True}


# ── Retry failed image ────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/images/{image_id}/retry")
async def retry_image(session_id: str, image_id: str, background_tasks: BackgroundTasks):
    s = _get_session(session_id)
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
    s = _get_session(session_id)
    if not s.ppt_path or not Path(s.ppt_path).exists():
        raise HTTPException(400, "PPT not yet generated")
    return FileResponse(
        s.ppt_path,
        filename=f"garment_catalog_{session_id}_v{s.version}.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.get("/api/sessions/{session_id}/slides")
async def get_slide_list(session_id: str):
    s = _get_session(session_id)
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
    return {"groups": groups_data, "ppt_ready": s.ppt_path is not None}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)
    try:
        # Send current session state on connect
        if session_id in sessions:
            s = sessions[session_id]
            await manager.send_event(session_id, "session_state", {
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
        manager.disconnect(websocket, session_id)


# ── Static files ──────────────────────────────────────────────────────────────

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_session(session_id: str) -> Session:
    if session_id not in sessions:
        _hydrate_session_from_manifest(session_id)
    if session_id not in sessions:
        raise HTTPException(404, f"Session '{session_id}' not found")
    return sessions[session_id]


def _hydrate_session_from_manifest(session_id: str) -> None:
    """Re-load a session from disk when it is missing from memory (warm container / recovery)."""
    if session_id in sessions:
        return
    manifest = _manifest_path(session_id)
    if not manifest.exists():
        return
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("id") != session_id:
            return
        session = Session(id=session_id)
        session.status = data.get("status", "idle")
        for img_id, img_data in data.get("images", {}).items():
            path = img_data.get("original_path", "")
            if path and Path(path).exists():
                session.images[img_id] = ImageItem(
                    id=img_data["id"],
                    filename=img_data["filename"],
                    original_path=path,
                )
        sessions[session_id] = session
    except Exception:
        log.exception("hydrate session %s from manifest failed", session_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


# When deployed behind Vercel's backend routePrefix, strip it so routes match /api/...
if os.getenv("VERCEL"):
    _prefix = os.getenv("VERCEL_BACKEND_PREFIX", "/_/backend").strip()
    if _prefix:
        app = StripBackendPrefixMiddleware(app, _prefix)
