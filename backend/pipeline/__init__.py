import asyncio
import uuid
import shutil
from pathlib import Path

from models import (
    Session, ImageItem, ImageStatus, ImageType,
    StyleGroup, GarmentData, PipelineStep,
)
from ws_manager import ConnectionManager
from config import OUTPUT_DIR

from .classifier import group_images
from .extractor import extract_spec_data
from .processor import process_image
from .ppt_generator import generate_catalog_ppt


PIPELINE_STEPS = [
    ("grouping",       "Style Grouping"),
    ("extraction",     "Spec Extraction"),
    ("processing",     "Image Processing"),
    ("ppt_generation", "PPT Generation"),
    ("file_export",    "File Export"),
]


async def run_pipeline(session: Session, manager: ConnectionManager):
    """Orchestrate the full catalog pipeline with real-time WS events."""
    try:
        session.pipeline_steps = [
            {"id": sid, "label": label, "status": "pending", "progress": 0}
            for sid, label in PIPELINE_STEPS
        ]
        await _emit(manager, session.id, "pipeline_started", {
            "total": len(session.images),
            "steps": session.pipeline_steps,
        })

        await _step_group(session, manager)
        await _step_extract(session, manager)
        await _step_process(session, manager)
        await _step_ppt(session, manager)
        await _step_export(session, manager)

        session.status = "complete"
        await _emit(manager, session.id, "pipeline_complete", {
            "ppt_url": f"/api/sessions/{session.id}/download",
            "slides": len(session.groups) + 2,
        })
    except Exception as exc:
        session.status = "error"
        session.error = str(exc)
        await _emit(manager, session.id, "pipeline_error", {"error": str(exc)})


# ── Step 1: Grouping (classification-free) ───────────────────────────────────
#
# All uploaded images are sent directly to the visual grouper.
# The model groups garment photos by physical item AND identifies spec labels
# in a single pass — no separate classification step needed.

async def _step_group(session: Session, manager: ConnectionManager):
    await _step_start(session, manager, "grouping",
                      "Grouping garments and identifying spec labels…")

    # Build minimal summaries — just path and id; grouper works purely visually
    summaries = [
        {
            "id":   img_id,
            "path": img.original_path,
        }
        for img_id, img in session.images.items()
    ]

    grouping = await group_images(summaries)

    # ── Apply view_map: set image_type on every image from grouper output ──────
    view_map = grouping.get("view_map", {})
    type_map = {
        "front":      ImageType.FRONT,
        "back":       ImageType.BACK,
        "detail":     ImageType.DETAIL,
        "spec_label": ImageType.SPEC_LABEL,
    }
    for img_id, view in view_map.items():
        img = session.images.get(img_id)
        if img:
            img.image_type = type_map.get(view, ImageType.UNKNOWN)
            img.status = ImageStatus.CLASSIFIED
            await _emit(manager, session.id, "image_classified", {
                "image_id":   img_id,
                "image_type": img.image_type.value,
                "status":     "classified",
            })

    # ── Build style groups ────────────────────────────────────────────────────
    session.groups = {}
    for raw in grouping.get("groups", []):
        gid = str(uuid.uuid4())[:8]
        g = StyleGroup(
            id=gid,
            style_id=raw.get("style_id", f"STYLE-{len(session.groups)+1:03d}"),
            garment_type=raw.get("garment_type"),
            images=raw.get("image_ids", []),
        )
        session.groups[gid] = g
        for img_id in g.images:
            if img_id in session.images:
                session.images[img_id].style_id = g.style_id

    spec_count    = sum(1 for img in session.images.values() if img.image_type == ImageType.SPEC_LABEL)
    garment_count = len(session.images) - spec_count

    await _emit(manager, session.id, "images_grouped", {
        "groups": [
            {
                "group_id":    g.id,
                "style_id":    g.style_id,
                "garment_type": g.garment_type,
                "image_ids":   g.images,
            }
            for g in session.groups.values()
        ],
    })
    await _step_done(
        session, manager, "grouping",
        f"Formed {len(session.groups)} style groups "
        f"({garment_count} garment images + {spec_count} spec labels)"
    )


# ── Step 3: Extraction ────────────────────────────────────────────────────────

async def _step_extract(session: Session, manager: ConnectionManager):
    await _step_start(session, manager, "extraction", "Extracting spec data from labels…")

    spec_images = [
        (img_id, img)
        for img_id, img in session.images.items()
        if img.image_type == ImageType.SPEC_LABEL
    ]
    if not spec_images:
        await _step_done(session, manager, "extraction", "No spec labels found")
        return

    for i, (img_id, img) in enumerate(spec_images):
        img.status = ImageStatus.EXTRACTING
        await _emit(manager, session.id, "image_status", {
            "image_id": img_id, "status": "extracting",
        })
        try:
            result = await extract_spec_data(img.original_path)
            img.garment_data = GarmentData(
                reference_number=result.get("reference_number"),
                fabric_composition=result.get("fabric_composition"),
                gsm=result.get("gsm"),
                date=result.get("date"),
                brand=result.get("brand"),
                origin=result.get("origin"),
                garment_type=img.garment_data.garment_type if img.garment_data else None,
            )
            img.status = ImageStatus.EXTRACTED
            extracted_ref = result.get("reference_number")

            # ── Re-assign this spec label to the correct group now that we have
            # the real reference number from OCR.  This is more reliable than
            # the pre-extraction classification guess. ────────────────────────
            current_group = _find_group_for_image(session, img_id)

            if extracted_ref:
                # Try to find a garment group that has a matching style_id or
                # a garment image that was classified with the same style_id.
                target_group = _find_group_by_ref(session, extracted_ref, img_id)
                if target_group and target_group is not current_group:
                    # Move spec label to the correct group
                    if current_group:
                        current_group.images = [
                            i for i in current_group.images if i != img_id
                        ]
                    target_group.images.append(img_id)
                    current_group = target_group
                    await _emit(manager, session.id, "spec_label_reassigned", {
                        "image_id":  img_id,
                        "group_id":  target_group.id,
                        "style_id":  extracted_ref,
                        "reason":    "reference_number_match",
                    })

            # Push spec data into the (possibly updated) owning group
            if current_group:
                current_group.garment_data = img.garment_data
                if extracted_ref:
                    current_group.style_id = extracted_ref

            await _emit(manager, session.id, "data_extracted", {
                "image_id": img_id,
                "data":     result,
                "status":   "extracted",
            })
        except Exception as e:
            img.status = ImageStatus.ERROR
            await _emit(manager, session.id, "image_error", {
                "image_id": img_id, "error": str(e),
            })

        await _step_progress(session, manager, "extraction",
                             int((i + 1) / len(spec_images) * 100))

    await _step_done(session, manager, "extraction", "Spec extraction complete")


# ── Step 4: Processing ────────────────────────────────────────────────────────

async def _step_process(session: Session, manager: ConnectionManager):
    await _step_start(session, manager, "processing", "Processing & enhancing images…")
    out_dir = OUTPUT_DIR / session.id / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    items = [
        (iid, img) for iid, img in session.images.items()
        if img.status != ImageStatus.ERROR
    ]
    for i, (img_id, img) in enumerate(items):
        img.status = ImageStatus.PROCESSING
        await _emit(manager, session.id, "image_status", {
            "image_id": img_id, "status": "processing",
        })
        try:
            out_file = str(out_dir / f"{img_id}_processed.jpg")
            res = process_image(
                img.original_path, out_file,
                image_type=img.image_type.value if img.image_type else "front",
            )
            img.processed_path = res.get("output_path") or img.original_path
            img.status = ImageStatus.PROCESSED
            await _emit(manager, session.id, "image_processed", {
                "image_id":    img_id,
                "processed_url": f"/outputs/{session.id}/processed/{img_id}_processed.jpg",
                "status":      "processed",
            })
        except Exception as e:
            img.processed_path = img.original_path
            img.status = ImageStatus.ERROR
            await _emit(manager, session.id, "image_error", {
                "image_id": img_id, "error": str(e),
            })

        await _step_progress(session, manager, "processing",
                             int((i + 1) / len(items) * 100))
        await asyncio.sleep(0.05)

    await _step_done(session, manager, "processing", "Image processing complete")


# ── Step 5: PPT Generation ────────────────────────────────────────────────────

async def _step_ppt(session: Session, manager: ConnectionManager):
    await _step_start(session, manager, "ppt_generation", "Generating PowerPoint catalog…")

    ppt_groups = []
    for slide_num, (gid, grp) in enumerate(session.groups.items(), start=1):
        grp.slide_number = slide_num
        imgs = []
        for img_id in grp.images:
            img = session.images.get(img_id)
            if img:
                imgs.append({
                    "image_type":     img.image_type.value if img.image_type else "unknown",
                    "original_path":  img.original_path,
                    "processed_path": img.processed_path,
                })
                img.status = ImageStatus.ASSIGNED
                await _emit(manager, session.id, "image_status", {
                    "image_id": img_id, "status": "assigned",
                    "slide_number": slide_num,
                })
        ppt_groups.append({
            "style_id":     grp.style_id,
            "garment_type": grp.garment_type,
            "images":       imgs,
            "garment_data": grp.garment_data.model_dump() if grp.garment_data else {},
        })

    ppt_path = str(OUTPUT_DIR / session.id / f"catalog_{session.id}.pptx")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, generate_catalog_ppt, ppt_groups, ppt_path, "GARMENT COLLECTION"
    )
    session.ppt_path = ppt_path
    session.version += 1

    await _emit(manager, session.id, "ppt_generated", {
        "ppt_url":   f"/api/sessions/{session.id}/download",
        "slides":    len(ppt_groups) + 2,
        "version":   session.version,
    })
    await _step_done(session, manager, "ppt_generation", "PowerPoint ready")


# ── Step 6: File export ───────────────────────────────────────────────────────

async def _step_export(session: Session, manager: ConnectionManager):
    await _step_start(session, manager, "file_export", "Organising output files…")
    out_dir = OUTPUT_DIR / session.id / "catalog_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    for grp in session.groups.values():
        safe_name = grp.style_id.replace("/", "_").replace(" ", "_")
        for img_id in grp.images:
            img = session.images.get(img_id)
            if not img:
                continue
            src = img.processed_path or img.original_path
            if not src or not Path(src).exists():
                continue
            type_name = img.image_type.value if img.image_type else "unknown"
            dest = out_dir / f"{safe_name}_{type_name}.jpg"
            try:
                shutil.copy2(src, dest)
                img.status = ImageStatus.COMPLETE
                await _emit(manager, session.id, "image_status", {
                    "image_id": img_id, "status": "complete",
                })
            except Exception:
                pass

    await _step_done(session, manager, "file_export", "Files organised")


# ── Utilities ─────────────────────────────────────────────────────────────────

async def _emit(manager: ConnectionManager, sid: str, event: str, data: dict):
    await manager.send_event(sid, event, data)


def _update_img(session: Session, img_id: str, **kwargs):
    img = session.images.get(img_id)
    if img:
        for k, v in kwargs.items():
            setattr(img, k, v)


async def _step_start(session: Session, manager: ConnectionManager, step_id: str, msg: str):
    _set_step(session, step_id, "running", 0, msg)
    await _emit(manager, session.id, "step_update", {
        "step_id": step_id, "status": "running", "progress": 0, "message": msg,
    })


async def _step_progress(session: Session, manager: ConnectionManager, step_id: str, pct: int):
    _set_step(session, step_id, "running", pct)
    await _emit(manager, session.id, "step_update", {
        "step_id": step_id, "status": "running", "progress": pct,
    })


async def _step_done(session: Session, manager: ConnectionManager, step_id: str, msg: str):
    _set_step(session, step_id, "complete", 100, msg)
    await _emit(manager, session.id, "step_update", {
        "step_id": step_id, "status": "complete", "progress": 100, "message": msg,
    })


def _set_step(session: Session, step_id: str, status: str, progress: int, message: str = ""):
    for s in session.pipeline_steps:
        if s["id"] == step_id:
            s["status"]   = status
            s["progress"] = progress
            if message:
                s["message"] = message
            break


def _find_group_for_image(session: Session, img_id: str):
    """Return the StyleGroup that currently contains img_id, or None."""
    for grp in session.groups.values():
        if img_id in grp.images:
            return grp
    return None


def _find_group_by_ref(session: Session, ref: str, exclude_img_id: str):
    """
    Find the garment group whose style_id or member image style_ids match `ref`.
    Excludes the group that contains only `exclude_img_id` (the spec label itself).
    Returns the best matching group, or None.
    """
    ref_lower = ref.strip().lower()

    # 1. Direct group style_id match
    for grp in session.groups.values():
        if grp.style_id.strip().lower() == ref_lower:
            # Make sure this is a garment group (has non-spec-label images)
            garment_members = [
                i for i in grp.images
                if i != exclude_img_id
                and session.images.get(i) is not None
                and session.images[i].image_type != ImageType.SPEC_LABEL
            ]
            if garment_members:
                return grp

    # 2. A garment image in any group carries the same style_id
    for grp in session.groups.values():
        for iid in grp.images:
            if iid == exclude_img_id:
                continue
            img = session.images.get(iid)
            if img and img.style_id and img.style_id.strip().lower() == ref_lower:
                return grp

    # 3. Partial / prefix match (e.g. "AND-1787" matches "and-1787-detail")
    for grp in session.groups.values():
        if ref_lower in grp.style_id.strip().lower() or grp.style_id.strip().lower() in ref_lower:
            garment_members = [
                i for i in grp.images
                if i != exclude_img_id
                and session.images.get(i) is not None
                and session.images[i].image_type != ImageType.SPEC_LABEL
            ]
            if garment_members:
                return grp

    return None
