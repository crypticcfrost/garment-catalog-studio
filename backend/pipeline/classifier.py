"""
Garment Image Classifier — Clean, visual-first grouping.

Design principles:
  1. classify_image()        – lightweight per-image type detection only.
                               Returns image_type, garment_type, primary_color, key_features.
                               NO complex structured attributes – they introduce more errors than
                               they prevent when used as hard constraints.

  2. visual_group_batch()    – sends ALL garment thumbnails in ONE call so the model can compare
                               every pair simultaneously (the key to avoiding context-loss).
                               Prompt is direct and simple: no attribute labels, no "hard rules"
                               that override visual evidence.

  3. _anchor_chunked_group() – for > SINGLE_CALL_LIMIT images, keeps anchor thumbnails from
                               confirmed groups to maintain cross-batch continuity.

  4. group_images()          – orchestrates: A) visual group garments, B) assign spec labels,
                               C) coverage check.

  Spec labels are NEVER sent to the visual grouper; they are assigned deterministically.
"""

import asyncio
import base64
import io
import json
import httpx
from pathlib import Path
from PIL import Image as PILImage

from config import OPENROUTER_API_KEY, VISION_MODEL, OPENROUTER_BASE_URL

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://garment-catalog-studio.dev",
    "X-Title": "Garment Catalog Studio",
}

# ── Tuning ────────────────────────────────────────────────────────────────────
SINGLE_CALL_LIMIT = 20   # ≤ this → one API call with all images
CHUNK_SIZE        = 14   # garment images per chunk (anchor mode)
MAX_ANCHORS       = 5    # anchor images per chunk call
THUMB_PX          = 768  # thumbnail size – enough detail, not too heavy
MAX_RETRIES       = 2


# ── Image helpers ─────────────────────────────────────────────────────────────

def _make_thumb(path: str, max_px: int = THUMB_PX) -> tuple[str, str]:
    img = PILImage.open(path).convert("RGB")
    img.thumbnail((max_px, max_px), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def _img_part(path: str, max_px: int = THUMB_PX) -> dict:
    b64, mime = _make_thumb(path, max_px)
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _strip_json(text: str) -> str:
    text = text.strip()
    if "```" in text:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s != -1 and e > s:
            return text[s:e]
    return text


async def _call(content: list, max_tokens: int = 2000, temp: float = 0.0) -> dict:
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers=HEADERS,
                    json={
                        "model": VISION_MODEL,
                        "messages": [{"role": "user", "content": content}],
                        "max_tokens": max_tokens,
                        "temperature": temp,
                    },
                )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return json.loads(_strip_json(raw))
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"Vision API failed: {last_err}")


# ── 1. Per-image classification ───────────────────────────────────────────────

_CLS_PROMPT = """You are classifying a single garment image for a catalog system.

Respond ONLY with valid JSON (no markdown, no explanation):
{
  "image_type": "<one of: front | back | detail | spec_label | unknown>",
  "style_id": "<reference/article code visible in the image, or null>",
  "garment_type": "<t-shirt | shirt | polo | hoodie | sweatshirt | jacket | jeans | pants | shorts | dress | skirt | coat | cardigan | vest | other>",
  "primary_color": "<dominant colour name>",
  "secondary_color": "<second colour or null>",
  "key_features": "<2-3 most visually distinctive details, e.g. navy raglan sleeves, golf graphic print, crew neck>",
  "confidence": <0.0 to 1.0>
}

TYPE GUIDE:
  front       – front panel of garment faces camera (chest, buttons, front print visible)
  back        – rear panel faces camera; this is the SAME garment as its matching front
  detail      – extreme close-up of one feature only (fabric, seam, button) — whole garment not visible
  spec_label  – paper/card hang tag, spec sheet, or barcode label; NOT the garment itself
  unknown     – completely unrecognisable or totally blurry image; use sparingly

RULE: If you can see any garment at all, classify it as front/back/detail — not unknown.
RULE: Back views are the same physical garment as their front. They share garment_type and color."""


async def classify_image(image_path: str) -> dict:
    try:
        b64, mime = _make_thumb(image_path, THUMB_PX)
    except Exception as e:
        return _empty_cls(str(e))

    try:
        content = [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": _CLS_PROMPT},
        ]
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=HEADERS,
                json={
                    "model": VISION_MODEL,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 300,
                    "temperature": 0.0,
                },
            )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        return json.loads(_strip_json(raw))
    except Exception as e:
        return _empty_cls(str(e))


def _empty_cls(reason: str) -> dict:
    return {
        "image_type": "unknown", "style_id": None, "garment_type": None,
        "primary_color": None, "secondary_color": None,
        "key_features": "", "confidence": 0.0,
    }


# ── 2. Visual grouping (single call) ─────────────────────────────────────────

_GROUP_PROMPT = """You are a garment catalog expert. You are looking at {n} garment photos, numbered [1] through [{n}].

TASK: Group the photos so that every photo of the SAME physical garment is in the same group.

WHAT IS ONE GROUP:
  • Front view + back view of the same garment → ONE group (same item, different angle)
  • 2 or 3 front shots of the same garment (different angles or lighting) → ONE group
  • Detail close-ups of the same garment → same group as its front/back
  • Typical group size: 2–4 images. A group of 1 is fine if only one shot exists.

WHAT IS A DIFFERENT GROUP:
  Look carefully at the physical garment construction and design:
  • Different collar style (e.g. polo collar vs crew neck vs button-down) → separate groups
  • Different colour (even similar shades like off-white vs cream → separate if clearly different)
  • Different sleeve length (short vs long) → separate groups
  • Different print or pattern → separate groups
  • Different overall garment design → separate groups
  Garments that are the same TYPE and COLOR but have different construction = different groups.

SPECIAL CASE — white/light solid garments:
  These are visually similar. Compare collar and sleeve carefully.
  A plain crew-neck tee and a polo-collar tee are DIFFERENT garments even if both white.

OUTPUT — only valid JSON, no markdown:
{{
  "groups": [
    {{"style_id": "STYLE-001", "garment_type": "t-shirt", "image_numbers": [1, 4, 7]}},
    {{"style_id": "STYLE-002", "garment_type": "polo",    "image_numbers": [2, 5, 8]}}
  ]
}}

Every number from 1 to {n} must appear in exactly one group."""


async def visual_group_batch(image_infos: list[dict]) -> list[dict]:
    """
    Send all garment images in one call. No attribute labels — pure visual comparison.
    """
    if not image_infos:
        return []
    if len(image_infos) == 1:
        info = image_infos[0]
        return [{"style_id": info.get("style_id") or "STYLE-001",
                 "garment_type": info.get("garment_type"),
                 "image_ids": [info["id"]]}]

    content: list[dict] = []
    valid: list[tuple[int, dict]] = []

    for i, info in enumerate(image_infos, start=1):
        path = info.get("path", "")
        if not path or not Path(path).exists():
            continue
        try:
            content.append(_img_part(path))
        except Exception:
            continue
        # Minimal label — just the number and view type (no attributes that could mislead)
        view = info.get("image_type", "?")
        content.append({"type": "text", "text": f"[Photo {i} — view: {view}]"})
        valid.append((i, info))

    if not valid:
        return _order_fallback(image_infos)

    content.append({"type": "text", "text": _GROUP_PROMPT.format(n=len(valid))})

    try:
        data = await _call(content, max_tokens=2000)
        num_map = {num: info for num, info in valid}
        groups: list[dict] = []
        used: set[int] = set()

        for g in data.get("groups", []):
            nums = [int(x) for x in g.get("image_numbers", []) if str(x).isdigit()]
            ids  = [num_map[n]["id"] for n in nums if n in num_map]
            if ids:
                groups.append({
                    "style_id":    g.get("style_id") or f"STYLE-{len(groups)+1:03d}",
                    "garment_type": g.get("garment_type"),
                    "image_ids":   ids,
                })
                used.update(nums)

        # Recover any image the model omitted
        ctr = len(groups) + 1
        for num, info in valid:
            if num not in used:
                groups.append({
                    "style_id":    info.get("style_id") or f"STYLE-{ctr:03d}",
                    "garment_type": info.get("garment_type"),
                    "image_ids":   [info["id"]],
                })
                ctr += 1

        return groups

    except Exception:
        return _order_fallback(image_infos)


# ── 3. Anchor-based chunking for large batches ────────────────────────────────

_ANCHOR_PROMPT = """You are a garment catalog expert. Compare NEW garment photos against ANCHOR reference photos.

ANCHOR photos = confirmed reference images, each from a known style group.
NEW photos = need to be assigned to an existing style OR identified as a new style.

ANCHOR images:
{anchor_lines}

NEW images to assign:
{new_lines}

TASK: For each NEW photo, decide:
  • Does it show the SAME physical garment as one of the ANCHORS?
    → Same means: same collar, same colour, same sleeve, same design. Front/back of same garment = match.
  • If it matches an ANCHOR → assign to that anchor's style_id
  • If it matches NO anchor → it is a new style

OUTPUT — only valid JSON, no markdown:
{{
  "assignments": [
    {{"img_num": 3, "anchor_style_id": "STYLE-001"}},
    {{"img_num": 4, "anchor_style_id": null, "new_style_id": "STYLE-006", "garment_type": "polo"}}
  ]
}}

Every NEW img_num must appear exactly once."""


async def _anchor_chunked_group(items: list[dict]) -> list[dict]:
    """Process > SINGLE_CALL_LIMIT garment images with anchor-based continuity."""
    # Initial groups from first chunk
    first = items[:CHUNK_SIZE]
    groups = await visual_group_batch(first)
    processed = {iid for g in groups for iid in g["image_ids"]}
    remaining = [i for i in items if i["id"] not in processed]

    while remaining:
        chunk     = remaining[:CHUNK_SIZE]
        remaining = remaining[CHUNK_SIZE:]

        # Build anchors: one confirmed image per existing group
        anchors: list[dict] = []
        for g in groups:
            for aid in g["image_ids"]:
                anchor = next((x for x in items if x["id"] == aid), None)
                if anchor and Path(anchor.get("path", "")).exists():
                    anchors.append({**anchor,
                                    "_style": g["style_id"],
                                    "_gtype": g.get("garment_type")})
                    break
            if len(anchors) >= MAX_ANCHORS:
                break

        assignments = await _run_anchor_call(anchors, chunk)
        ctr = len(groups) + 1

        for asgn in assignments:
            num = asgn.get("img_num")
            if num is None or num < 1 or num > len(chunk):
                continue
            item = chunk[num - 1]
            sid  = asgn.get("anchor_style_id")
            if sid:
                target = next((g for g in groups if g["style_id"] == sid), None)
                if target:
                    target["image_ids"].append(item["id"])
                    continue
            # New style
            ns = asgn.get("new_style_id") or f"STYLE-{ctr:03d}"
            groups.append({
                "style_id":    ns,
                "garment_type": asgn.get("garment_type") or item.get("garment_type"),
                "image_ids":   [item["id"]],
            })
            ctr += 1

        # Safety net — ensure nothing from chunk is lost
        assigned = {iid for g in groups for iid in g["image_ids"]}
        for item in chunk:
            if item["id"] not in assigned:
                groups.append({
                    "style_id":    item.get("style_id") or f"STYLE-{ctr:03d}",
                    "garment_type": item.get("garment_type"),
                    "image_ids":   [item["id"]],
                })
                ctr += 1

        await asyncio.sleep(0.4)

    return groups


async def _run_anchor_call(anchors: list[dict], new_items: list[dict]) -> list[dict]:
    content: list[dict] = []
    anchor_lines: list[str] = []
    new_lines:    list[str] = []

    for a in anchors:
        try:
            content.append(_img_part(a["path"], 512))
        except Exception:
            continue
        anchor_lines.append(f"  ANCHOR style={a['_style']!r} garment={a.get('_gtype','?')!r}")
        content.append({"type": "text", "text": f"[ANCHOR: style={a['_style']!r}]"})

    for j, item in enumerate(new_items, start=1):
        path = item.get("path", "")
        if not path or not Path(path).exists():
            continue
        try:
            content.append(_img_part(path))
        except Exception:
            continue
        new_lines.append(f"  NEW img_num={j}")
        content.append({"type": "text", "text": f"[NEW img_num={j}]"})

    if not new_lines:
        return []

    content.append({"type": "text", "text": _ANCHOR_PROMPT.format(
        anchor_lines="\n".join(anchor_lines) or "  (none)",
        new_lines="\n".join(new_lines),
    )})

    try:
        data = await _call(content, max_tokens=1200)
        return data.get("assignments", [])
    except Exception:
        return [{"img_num": j + 1, "anchor_style_id": None, "new_style_id": None,
                 "garment_type": item.get("garment_type")}
                for j, item in enumerate(new_items)]


# ── 4. Top-level orchestrator ─────────────────────────────────────────────────

async def group_images(
    image_summaries: list[dict],
    upload_order: list[str] | None = None,
) -> dict:
    """
    Three-phase pipeline:
      A: Visual grouping of garment images
      B: Deterministic spec-label assignment
      C: Coverage check
    """
    if not image_summaries:
        return {"groups": []}

    garment_items = [i for i in image_summaries if i.get("image_type") != "spec_label"]
    spec_items    = [i for i in image_summaries if i.get("image_type") == "spec_label"]

    # Phase A
    if not garment_items:
        raw_groups: list[dict] = []
    elif len(garment_items) <= SINGLE_CALL_LIMIT:
        raw_groups = await visual_group_batch(garment_items)
    else:
        raw_groups = await _anchor_chunked_group(garment_items)

    # Phase B
    upload_order = upload_order or [i["id"] for i in image_summaries]
    raw_groups = _assign_spec_labels(spec_items, raw_groups, upload_order, image_summaries)

    # Phase C
    raw_groups = _ensure_coverage(raw_groups, image_summaries)

    return {"groups": raw_groups}


# ── 5. Spec-label assignment ──────────────────────────────────────────────────

def _assign_spec_labels(
    spec_items: list[dict],
    garment_groups: list[dict],
    upload_order: list[str],
    all_items: list[dict],
) -> list[dict]:
    if not spec_items:
        return garment_groups

    groups = [dict(g, image_ids=list(g["image_ids"])) for g in garment_groups]

    for spec in spec_items:
        sid      = spec["id"]
        spec_ref = (spec.get("style_id") or "").strip().lower()
        placed   = False

        # 1. Reference-number match
        if spec_ref:
            for grp in groups:
                if grp.get("style_id", "").strip().lower() == spec_ref:
                    grp["image_ids"].append(sid)
                    placed = True
                    break
            if not placed:
                for grp in groups:
                    for iid in grp.get("image_ids", []):
                        item = next((x for x in all_items if x["id"] == iid), None)
                        if item and (item.get("style_id") or "").strip().lower() == spec_ref:
                            grp["image_ids"].append(sid)
                            placed = True
                            break
                    if placed:
                        break

        # 2. Upload-order proximity
        if not placed and sid in upload_order:
            pos  = upload_order.index(sid)
            best, dist = None, float("inf")
            for grp in groups:
                for iid in grp.get("image_ids", []):
                    if iid in upload_order:
                        d = abs(upload_order.index(iid) - pos)
                        if d < dist:
                            dist, best = d, grp
            if best:
                best["image_ids"].append(sid)
                placed = True

        # 3. Standalone fallback
        if not placed:
            groups.append({
                "style_id":    spec.get("style_id") or f"SPEC-{len(groups)+1:03d}",
                "garment_type": None,
                "image_ids":   [sid],
            })

    return groups


# ── 6. Coverage check ─────────────────────────────────────────────────────────

def _ensure_coverage(groups: list[dict], all_items: list[dict]) -> list[dict]:
    covered = {iid for g in groups for iid in g.get("image_ids", [])}
    ctr = len(groups) + 1
    for item in all_items:
        if item["id"] not in covered:
            groups.append({
                "style_id":    item.get("style_id") or f"STYLE-{ctr:03d}",
                "garment_type": item.get("garment_type"),
                "image_ids":   [item["id"]],
            })
            ctr += 1
    return groups


# ── 7. Last-resort fallback ───────────────────────────────────────────────────

def _order_fallback(items: list[dict]) -> list[dict]:
    """Only used when ALL API calls fail. Groups by upload order in batches of 4."""
    groups = []
    for i in range(0, len(items), 4):
        batch = items[i:i + 4]
        groups.append({
            "style_id":    batch[0].get("style_id") or f"STYLE-{len(groups)+1:03d}",
            "garment_type": batch[0].get("garment_type"),
            "image_ids":   [x["id"] for x in batch],
        })
    return groups
