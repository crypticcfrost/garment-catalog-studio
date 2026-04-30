"""
Garment Grouper — Pure visual, classification-free.

The main pipeline no longer runs a separate classification step.
group_images() does everything in a single visual pass:
  - Groups garment photos by physical garment
  - Identifies spec labels / bills within each group
  - Outputs a view_map  (image_id -> view_type) so downstream steps know
    which images are spec labels, fronts, backs, etc.

classify_image() is retained for the manual retry endpoint only.
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
CHUNK_SIZE        = 12   # images per chunk (anchor mode)
MAX_ANCHORS       = 6    # anchor images per chunk call
THUMB_PX          = 800  # thumbnail — enough detail for collar/sleeve/bill distinction
MAX_RETRIES       = 2


# ── Image helpers ─────────────────────────────────────────────────────────────

def _make_thumb(path: str, max_px: int = THUMB_PX) -> tuple[str, str]:
    img = PILImage.open(path).convert("RGB")
    img.thumbnail((max_px, max_px), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=87)
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


# ── 1. Per-image classification (kept for manual retry endpoint only) ─────────

_CLS_PROMPT = """You are classifying a single garment image for a fashion catalog.

Respond ONLY with valid JSON (no markdown, no explanation):
{
  "image_type": "<front | back | detail | spec_label | unknown>",
  "style_id": "<style/article/reference code visible on a tag, or null>",
  "garment_type": "<t-shirt | shirt | polo | hoodie | sweatshirt | jacket | jeans | pants | shorts | dress | skirt | coat | cardigan | vest | other>",
  "primary_color": "<dominant colour>",
  "secondary_color": "<second colour or null>",
  "key_features": "<2-3 most distinctive details>",
  "confidence": <0.0-1.0>
}

TYPE GUIDE:
  front       – front panel faces camera
  back        – rear panel faces camera (same garment as its matching front)
  detail      – extreme close-up of one feature only; whole garment not visible
  spec_label  – printed paper: hang-tag / care label / spec sheet / bill / receipt
  unknown     – completely unrecognisable"""


async def classify_image(image_path: str) -> dict:
    """Single-image classifier — used by the manual retry endpoint only."""
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


# ── 2. All-image visual grouper ───────────────────────────────────────────────
#
# Sends EVERY uploaded image (garments + bills) in one call.
# The model groups them AND identifies view types — no separate classify step.

_GROUP_PROMPT = """You are a garment catalog expert. You are looking at {n} photos from a single catalog session.

The photos are a mix of:
  - Garment shots: front views, back views, and detail close-ups of clothing items
  - Spec labels: printed bills, hang-tags, receipts, spec sheets, barcode labels

TASK:
  1. Group all photos so that every shot of the SAME physical garment AND its spec label are in one group.
  2. Identify the view type of each photo.

SAME GROUP (all belong together):
  • Front view + back view of the same garment → one group
  • Detail close-ups of the same garment → same group as the front/back
  • The spec label / bill that belongs to this garment → same group
  Typical group size: 2–5 photos (e.g. front + back + spec label, or front + spec label)

DIFFERENT GROUP (separate group when ANY of these differ):
  • Different garment design: different collar style, different color, different sleeve length, different print
  • Different spec label that belongs to a different garment

SPEC LABEL DETECTION — mark view="spec_label" for:
  • Printed paper, tags, receipts, bills, hang-tags, measurement/spec sheets, barcodes
  • Anything that is NOT a photograph of the garment itself
  • Usually uploaded immediately before or after the garment photos it belongs with

VIEW TYPES:
  front      – front panel of garment is the main subject
  back       – rear panel of garment is the main subject (same garment as its front)
  detail     – extreme close-up of ONE feature; whole garment not visible
  spec_label – printed paper / bill / receipt / spec sheet

OUTPUT — only valid JSON, no markdown:
{{
  "groups": [
    {{
      "style_id": "STYLE-001",
      "garment_type": "t-shirt",
      "images": [
        {{"num": 1, "view": "front"}},
        {{"num": 4, "view": "back"}},
        {{"num": 3, "view": "spec_label"}}
      ]
    }},
    {{
      "style_id": "STYLE-002",
      "garment_type": "polo",
      "images": [
        {{"num": 2, "view": "front"}},
        {{"num": 5, "view": "back"}},
        {{"num": 6, "view": "spec_label"}}
      ]
    }}
  ]
}}

Every number from 1 to {n} must appear in exactly one group.
view must be one of: front | back | detail | spec_label"""


async def visual_group_batch(
    image_infos: list[dict],
) -> tuple[list[dict], dict[str, str]]:
    """
    Send ALL images (garments + spec labels) in one call.
    Returns (groups, view_map) where:
      groups   = [{"style_id": ..., "garment_type": ..., "image_ids": [...]}]
      view_map = {"img_id": "front" | "back" | "detail" | "spec_label", ...}
    """
    if not image_infos:
        return [], {}
    if len(image_infos) == 1:
        info = image_infos[0]
        return (
            [{"style_id": info.get("style_id") or "STYLE-001",
              "garment_type": info.get("garment_type"),
              "image_ids": [info["id"]]}],
            {info["id"]: "front"},
        )

    content: list[dict] = []
    valid: list[tuple[int, dict]] = []  # (number, info)

    for i, info in enumerate(image_infos, start=1):
        path = info.get("path", "")
        if not path or not Path(path).exists():
            continue
        try:
            content.append(_img_part(path))
        except Exception:
            continue
        content.append({"type": "text", "text": f"[Photo {i}]"})
        valid.append((i, info))

    if not valid:
        return _order_fallback(image_infos), {}

    content.append({"type": "text", "text": _GROUP_PROMPT.format(n=len(valid))})

    try:
        data = await _call(content, max_tokens=2500)
        num_map = {num: info for num, info in valid}
        groups: list[dict] = []
        view_map: dict[str, str] = {}
        used: set[int] = set()

        for g in data.get("groups", []):
            img_list = g.get("images", [])
            ids: list[str] = []
            for entry in img_list:
                num  = int(entry["num"]) if str(entry.get("num", "")).isdigit() else None
                view = entry.get("view", "front")
                if num is not None and num in num_map:
                    img_id = num_map[num]["id"]
                    ids.append(img_id)
                    view_map[img_id] = view
                    used.add(num)
            if ids:
                groups.append({
                    "style_id":    g.get("style_id") or f"STYLE-{len(groups)+1:03d}",
                    "garment_type": g.get("garment_type"),
                    "image_ids":   ids,
                })

        # Recover any image the model omitted
        ctr = len(groups) + 1
        for num, info in valid:
            if num not in used:
                groups.append({
                    "style_id":    info.get("style_id") or f"STYLE-{ctr:03d}",
                    "garment_type": info.get("garment_type"),
                    "image_ids":   [info["id"]],
                })
                view_map[info["id"]] = "front"
                ctr += 1

        return groups, view_map

    except Exception:
        fallback = _order_fallback(image_infos)
        fallback_view_map = {iid: "front" for g in fallback for iid in g["image_ids"]}
        return fallback, fallback_view_map


# ── 3. Anchor-based chunking for large batches ────────────────────────────────

_ANCHOR_PROMPT = """You are a garment catalog expert. Compare NEW photos against ANCHOR reference photos.

ANCHOR photos = one confirmed reference per known style group (already grouped).
NEW photos = need to be assigned to an existing group OR a new group.

ANCHORS (with their confirmed style groups):
{anchor_lines}

NEW photos to assign:
{new_lines}

TASK: For each NEW photo:
  • If it shows the SAME physical garment as an anchor → assign to that anchor's style group
  • If it is the SPEC LABEL / BILL belonging to an anchor's garment → assign to that anchor's style group
  • If it matches no anchor (new garment design or a spec label for a new garment) → new group

Also identify each NEW photo's view type.

OUTPUT — only valid JSON, no markdown:
{{
  "assignments": [
    {{"img_num": 3, "anchor_style_id": "STYLE-001", "view": "back"}},
    {{"img_num": 5, "anchor_style_id": "STYLE-001", "view": "spec_label"}},
    {{"img_num": 4, "anchor_style_id": null, "new_style_id": "STYLE-006", "garment_type": "polo", "view": "front"}}
  ]
}}

Every NEW img_num must appear exactly once.
view must be: front | back | detail | spec_label"""


async def _anchor_chunked_group(
    items: list[dict],
) -> tuple[list[dict], dict[str, str]]:
    """Process > SINGLE_CALL_LIMIT images with anchor-based continuity."""
    first  = items[:CHUNK_SIZE]
    groups, view_map = await visual_group_batch(first)
    processed = {iid for g in groups for iid in g["image_ids"]}
    remaining = [i for i in items if i["id"] not in processed]

    while remaining:
        chunk     = remaining[:CHUNK_SIZE]
        remaining = remaining[CHUNK_SIZE:]

        # One anchor image per existing group (prefer front views)
        anchors: list[dict] = []
        for g in groups:
            for aid in g["image_ids"]:
                anchor_item = next((x for x in items if x["id"] == aid), None)
                if anchor_item and Path(anchor_item.get("path", "")).exists():
                    anchors.append({**anchor_item,
                                    "_style": g["style_id"],
                                    "_gtype": g.get("garment_type")})
                    break
            if len(anchors) >= MAX_ANCHORS:
                break

        assignments, chunk_view_map = await _run_anchor_call(anchors, chunk)
        view_map.update(chunk_view_map)
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
            ns = asgn.get("new_style_id") or f"STYLE-{ctr:03d}"
            groups.append({
                "style_id":    ns,
                "garment_type": asgn.get("garment_type") or item.get("garment_type"),
                "image_ids":   [item["id"]],
            })
            ctr += 1

        # Safety net
        assigned = {iid for g in groups for iid in g["image_ids"]}
        for item in chunk:
            if item["id"] not in assigned:
                groups.append({
                    "style_id":    item.get("style_id") or f"STYLE-{ctr:03d}",
                    "garment_type": item.get("garment_type"),
                    "image_ids":   [item["id"]],
                })
                view_map.setdefault(item["id"], "front")
                ctr += 1

        await asyncio.sleep(0.4)

    return groups, view_map


async def _run_anchor_call(
    anchors: list[dict],
    new_items: list[dict],
) -> tuple[list[dict], dict[str, str]]:
    content: list[dict] = []
    anchor_lines: list[str] = []
    new_lines: list[str] = []

    for a in anchors:
        try:
            content.append(_img_part(a["path"], 512))
        except Exception:
            continue
        anchor_lines.append(f"  [ANCHOR style={a['_style']!r} garment={a.get('_gtype','?')!r}]")
        content.append({"type": "text",
                        "text": f"[ANCHOR style={a['_style']!r} garment={a.get('_gtype','?')!r}]"})

    new_map: dict[int, dict] = {}
    for j, item in enumerate(new_items, start=1):
        path = item.get("path", "")
        if not path or not Path(path).exists():
            continue
        try:
            content.append(_img_part(path))
        except Exception:
            continue
        new_lines.append(f"  [NEW img_num={j}]")
        content.append({"type": "text", "text": f"[NEW img_num={j}]"})
        new_map[j] = item

    if not new_lines:
        return [], {}

    content.append({"type": "text", "text": _ANCHOR_PROMPT.format(
        anchor_lines="\n".join(anchor_lines) or "  (none)",
        new_lines="\n".join(new_lines),
    )})

    chunk_view_map: dict[str, str] = {}
    try:
        data = await _call(content, max_tokens=1400)
        assignments = data.get("assignments", [])
        for asgn in assignments:
            num = asgn.get("img_num")
            if num in new_map:
                chunk_view_map[new_map[num]["id"]] = asgn.get("view", "front")
        return assignments, chunk_view_map
    except Exception:
        fallback = [
            {"img_num": j, "anchor_style_id": None, "new_style_id": None,
             "garment_type": item.get("garment_type"), "view": "front"}
            for j, item in new_map.items()
        ]
        for j, item in new_map.items():
            chunk_view_map[item["id"]] = "front"
        return fallback, chunk_view_map


# ── 4. Top-level orchestrator ─────────────────────────────────────────────────

async def group_images(
    image_summaries: list[dict],
    upload_order: list[str] | None = None,
    spec_ref_map: dict[str, str] | None = None,
) -> dict:
    """
    Two-phase pipeline (no separate classification step):
      A: Visual grouping of ALL images — garments + spec labels together.
         The model identifies spec labels and view types in the same pass.
      B: Coverage check.

    Returns:
      {
        "groups":   [{"style_id": ..., "garment_type": ..., "image_ids": [...]}],
        "view_map": {"img_id": "front" | "back" | "detail" | "spec_label", ...}
      }
    """
    if not image_summaries:
        return {"groups": [], "view_map": {}}

    if len(image_summaries) <= SINGLE_CALL_LIMIT:
        raw_groups, view_map = await visual_group_batch(image_summaries)
    else:
        raw_groups, view_map = await _anchor_chunked_group(image_summaries)

    raw_groups = _ensure_coverage(raw_groups, image_summaries, view_map)

    return {"groups": raw_groups, "view_map": view_map}


# ── 5. Coverage check ─────────────────────────────────────────────────────────

def _ensure_coverage(
    groups: list[dict],
    all_items: list[dict],
    view_map: dict[str, str],
) -> list[dict]:
    covered = {iid for g in groups for iid in g.get("image_ids", [])}
    ctr = len(groups) + 1
    for item in all_items:
        if item["id"] not in covered:
            groups.append({
                "style_id":    item.get("style_id") or f"STYLE-{ctr:03d}",
                "garment_type": item.get("garment_type"),
                "image_ids":   [item["id"]],
            })
            view_map.setdefault(item["id"], "front")
            ctr += 1
    return groups


# ── 6. Last-resort fallback ───────────────────────────────────────────────────

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
