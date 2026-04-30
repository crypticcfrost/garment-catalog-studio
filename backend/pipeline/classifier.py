"""
Garment Image Classifier — Anchor-based whole-context visual grouping

Core design principles:
  1. NO text-description-based grouping anywhere in the main path.
     Grouping is done purely by sending pixel data to the vision model.

  2. SINGLE CALL for small batches (≤ SINGLE_CALL_LIMIT):
     All garment images are sent together so the model has full context.

  3. ANCHOR-BASED CHUNKING for large batches (> SINGLE_CALL_LIMIT):
     - Process the first chunk → establish initial style groups.
     - Every subsequent chunk includes one ANCHOR thumbnail per existing group.
     - Anchors give the model a visual reference: "does this new image match ANCHOR-A?"
     - This eliminates the cross-batch context-loss problem.

  4. Spec labels are NEVER sent to the visual grouper.
     They are assigned deterministically: reference-number match → upload-order proximity.
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

MIME_MAP = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png",  ".webp": "image/webp"}

# ── Tuning constants ──────────────────────────────────────────────────────────
SINGLE_CALL_LIMIT  = 20   # ≤ this → one API call with all images
CHUNK_SIZE         = 12   # garment images per chunk (anchor-based mode)
MAX_ANCHORS        = 6    # anchor images included per chunk call
THUMB_GARMENT      = 640  # px – thumbnail size for garment images
THUMB_ANCHOR       = 384  # px – smaller thumbnail for anchor images
MAX_RETRIES        = 2    # retry attempts on vision API failure


# ── Image encoding ────────────────────────────────────────────────────────────

def _thumb(path: str, max_px: int) -> tuple[str, str]:
    """Open image, resize to fit max_px on longest side, return (base64, mime)."""
    img = PILImage.open(path).convert("RGB")
    img.thumbnail((max_px, max_px), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def _img_block(path: str, max_px: int) -> dict:
    b64, mime = _thumb(path, max_px)
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _clean_json(text: str) -> str:
    text = text.strip()
    if "```" in text:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s != -1 and e > s:
            return text[s:e]
    return text


async def _call_vision(content: list, max_tokens: int = 2000) -> dict:
    """Wrapper with retry logic around the OpenRouter vision endpoint."""
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
                        "temperature": 0.0,
                    },
                )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return json.loads(_clean_json(raw))
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"Vision API failed after {MAX_RETRIES} retries: {last_err}")


# ── 1. Per-image classification ───────────────────────────────────────────────

async def classify_image(image_path: str) -> dict:
    """
    Classify a single garment image.
    Returns: image_type, style_id, garment_type, primary_color, key_features, confidence.
    """
    try:
        b64, mime = _thumb(image_path, THUMB_GARMENT)
    except Exception as e:
        return _empty_cls(f"Read error: {e}")

    prompt = """You are a garment catalog specialist. Classify this image precisely.

Respond ONLY with valid JSON (no markdown fences, no explanation):
{
  "image_type": "front | back | detail | spec_label | unknown",
  "style_id": "<ref/style/article code visible in the image, or null>",
  "garment_type": "<t-shirt | shirt | polo | jeans | dress | jacket | hoodie | pants | shorts | skirt | coat | sweatshirt | cardigan | blazer | vest | etc.>",
  "primary_color": "<dominant colour: white | off-white | cream | black | navy | red | grey | beige | tan | khaki | blue | green | olive | brown | pink | purple | yellow | orange | teal | multicolor | striped | checked | printed>",
  "secondary_color": "<second colour if present, else null>",
  "key_features": "<5-7 precise visual identifiers, e.g. 'boxy crew-neck t-shirt, wide raglan sleeves in navy, front graphic print of golfer figure, white body, no buttons, ribbed cuffs'>",
  "confidence": <0.0–1.0>,
  "reasoning": "<one concise sentence>"
}

━━ TYPE DEFINITIONS — READ CAREFULLY ━━

front
  • The FRONT panel of a garment faces the camera.
  • Garment is on a hanger, flat-lay, mannequin, or worn — does not matter.
  • If you can see chest / collar / front buttons / front print → it is FRONT.

back
  • The BACK panel faces the camera. Rear seam, back yoke, or back print visible.
  • A back view is the SAME physical garment as its matching front. They are ONE style.

detail
  • Extreme close-up of ONE feature: fabric weave, seam, embroidery, zipper, button, tag sewn INTO the garment.
  • The whole garment is NOT visible — only a small section.

spec_label
  • A paper hang-tag, printed spec sheet, barcode sticker, or care label CARD.
  • The garment itself is NOT the main subject.
  • Key indicator: printed text with reference numbers, barcodes, fabric composition %.

unknown
  • Use ONLY when the image is completely blurry, corrupt, or contains NO garment at all.
  • If ANY garment is visible — even partially — classify it as front/back/detail, NOT unknown.
  • DO NOT use unknown just because you are uncertain between front and back.

━━ DECISION RULES ━━
1. Can you see the full garment front? → front
2. Can you see the full garment back? → back
3. Can you see only a small section of fabric/seam? → detail
4. Is it a paper/card label with barcodes or spec text? → spec_label
5. Is the image completely unusable? → unknown (last resort only)

IMPORTANT: "unknown" should be extremely rare — less than 5% of images in a real catalog."""

    try:
        content = [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=HEADERS,
                json={
                    "model": VISION_MODEL,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 500,
                    "temperature": 0.0,
                },
            )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        return json.loads(_clean_json(raw))
    except Exception as e:
        return _empty_cls(str(e))


def _empty_cls(reason: str) -> dict:
    return {
        "image_type": "unknown", "style_id": None, "garment_type": None,
        "primary_color": None, "secondary_color": None,
        "key_features": "", "colors": [], "confidence": 0.0, "reasoning": reason,
    }


# ── 2. Visual grouping — single call ─────────────────────────────────────────

_PROMPT_FULL = """You are a garment catalog specialist. You are looking at {n} garment images labeled [Img 1] … [Img {n}].

━━ YOUR TASK ━━
Group the images so that all images of the **same physical garment** are in one group.
Every image must appear in exactly one group — no image may be left out.

━━ WHAT COUNTS AS "SAME GARMENT" ━━
All of these belong in ONE group for the SAME garment:
  • Front view on hanger
  • Back view on hanger           ← SAME garment, different angle
  • Second front view (flat-lay, different angle, or duplicate shot)  ← STILL same garment
  • Close-up detail of the fabric or seam
  • Any additional angle of the same item
Typical group size: 2–5 images. Groups of 1 are allowed (only one shot exists).

━━ RULES FOR "DIFFERENT GARMENTS" ━━
These MUST be in SEPARATE groups even if they look similar:

  SOLID / NEAR-SOLID GARMENTS (white, cream, black, grey, etc.) — this is the hardest case:
  ① Collar/neckline: crew-neck ≠ v-neck ≠ polo-collar ≠ band-collar ≠ open-collar shirt
  ② Sleeve length: sleeveless ≠ short-sleeve ≠ 3/4-sleeve ≠ long-sleeve
  ③ Body length: crop ≠ regular ≠ longline — even a few centimetres difference = different style
  ④ Fit silhouette: boxy/oversized ≠ slim-fit ≠ relaxed — if the shoulder drop or body taper differs
  ⑤ Construction details: ribbed cuffs ≠ plain cuffs; side slits ≠ no slits; chest pocket ≠ no pocket
  ⑥ Fabric surface: waffle/textured knit ≠ smooth jersey ≠ structured woven
  ⑦ Colour shade: pure white ≠ off-white/cream ≠ light grey — if the shade is visibly different

  PATTERNED GARMENTS:
  ⑧ Stripe spacing or rhythm: narrow stripes ≠ wide stripes even if same colours
  ⑨ Pattern scale: small check ≠ large check
  ⑩ Print content: any difference in print motif = different garment

NEVER merge two garments just because they share garment type and general colour.
When in doubt about solid garments, CHECK the collar and sleeve details — those are the most reliable differentiators.

━━ RESPOND ━━
ONLY valid JSON — no markdown, no explanation outside the JSON:
{{
  "groups": [
    {{"style_id": "STYLE-001", "garment_type": "t-shirt", "image_numbers": [1, 3, 5]}},
    {{"style_id": "STYLE-002", "garment_type": "shirt",   "image_numbers": [2, 4, 6, 8]}}
  ]
}}

Every image number from 1 to {n} must appear in exactly one group."""


async def visual_group_batch(image_infos: list[dict]) -> list[dict]:
    """
    Sends all garment images in one API call for visual grouping.
    image_infos: list of {id, path, image_type, style_id, garment_type, ...}
    """
    if not image_infos:
        return []
    if len(image_infos) == 1:
        info = image_infos[0]
        return [{"style_id": info.get("style_id") or "STYLE-001",
                 "garment_type": info.get("garment_type"),
                 "image_ids": [info["id"]]}]

    content: list[dict] = []
    valid: list[tuple[int, dict]] = []  # (image_number, info)

    for i, info in enumerate(image_infos, start=1):
        path = info.get("path", "")
        if not path or not Path(path).exists():
            continue
        try:
            content.append(_img_block(path, THUMB_GARMENT))
        except Exception:
            continue
        hint = f" ref={info['style_id']!r}" if info.get("style_id") else ""
        content.append({"type": "text",
                         "text": f"[Img {i}: id={info['id']} type={info.get('image_type','?')}{hint}]"})
        valid.append((i, info))

    if not valid:
        return _upload_order_fallback(image_infos)

    content.append({"type": "text", "text": _PROMPT_FULL.format(n=len(valid))})

    try:
        data = await _call_vision(content, max_tokens=2000)
        num_to_info = {num: info for num, info in valid}
        groups: list[dict] = []
        used: set[int] = set()

        for grp in data.get("groups", []):
            nums = [int(n) for n in grp.get("image_numbers", []) if str(n).isdigit()]
            ids  = [num_to_info[n]["id"] for n in nums if n in num_to_info]
            if ids:
                groups.append({
                    "style_id":    grp.get("style_id") or f"STYLE-{len(groups)+1:03d}",
                    "garment_type": grp.get("garment_type"),
                    "image_ids":   ids,
                })
                used.update(nums)

        # Recover any image the model missed
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
        return _upload_order_fallback(image_infos)


# ── 3. Anchor-based chunking for large batches ────────────────────────────────

_PROMPT_ANCHOR = """You are a garment catalog specialist comparing NEW images against ANCHOR reference images.

ANCHOR images = already confirmed styles. Each anchor thumbnail represents one known style.
NEW images = must be assigned to an existing anchor style OR declared a brand-new style.

━━ IMAGES ━━
ANCHORS (already classified):
{anchor_descriptions}

NEW images to classify:
{new_descriptions}

━━ HOW TO MATCH ━━
A NEW image MATCHES an anchor when it shows the SAME physical garment:
  • Same exact collar/neckline type
  • Same sleeve length
  • Same colour shade (pure white ≠ cream ≠ off-white)
  • Same fabric texture
  • Same construction (pocket, slit, cuff, silhouette)
  • A front view CAN match a back-view anchor — they are the same garment
  • A SECOND front view CAN match a front-view anchor — same garment, extra shot

A NEW image does NOT match when even ONE of these differs:
  • Different collar (crew ≠ polo ≠ v-neck ≠ band collar)
  • Different sleeve length
  • Different body length or silhouette
  • Visibly different colour shade

━━ RESPOND ━━
ONLY valid JSON (no markdown, no extra text):
{{
  "assignments": [
    {{"img_num": 5, "anchor_style_id": "STYLE-001"}},
    {{"img_num": 6, "anchor_style_id": null, "new_style_id": "STYLE-005", "garment_type": "polo"}}
  ]
}}

Every NEW img_num must appear exactly once in the assignments list."""


async def _anchor_chunked_group(items: list[dict]) -> list[dict]:
    """
    Groups > SINGLE_CALL_LIMIT garment images using anchor-based chunking.

    Algorithm:
      1. Form initial groups from the first CHUNK_SIZE images.
      2. For each subsequent chunk:
           a. Pick one representative (anchor) image from each existing group.
           b. Send anchors + chunk to vision model.
           c. Model assigns each new image to an existing group OR declares a new group.
      3. Accumulate all groups.
    """
    # Step 1: initial groups from first chunk
    first_chunk = items[:CHUNK_SIZE]
    groups = await visual_group_batch(first_chunk)
    processed = {iid for g in groups for iid in g["image_ids"]}

    # Step 2: anchor-based processing of remaining items
    remaining = [i for i in items if i["id"] not in processed]

    while remaining:
        chunk      = remaining[:CHUNK_SIZE]
        remaining  = remaining[CHUNK_SIZE:]

        # Build anchor list: one image per existing group (use first image in group)
        anchors: list[dict] = []
        for g in groups:
            for aid in g["image_ids"]:
                anchor_item = next((x for x in items if x["id"] == aid), None)
                if anchor_item and Path(anchor_item.get("path", "")).exists():
                    anchors.append({**anchor_item,
                                    "_anchor_style": g["style_id"],
                                    "_anchor_gtype":  g.get("garment_type")})
                    break
            if len(anchors) >= MAX_ANCHORS:
                break

        assignments = await _call_with_anchors(anchors, chunk)

        # Merge assignments into existing groups
        ctr = len(groups) + 1
        for asgn in assignments:
            img_num = asgn.get("img_num")
            if img_num is None or img_num > len(chunk):
                continue
            new_item = chunk[img_num - 1]
            matched_style = asgn.get("anchor_style_id")

            if matched_style:
                target = next((g for g in groups if g["style_id"] == matched_style), None)
                if target:
                    target["image_ids"].append(new_item["id"])
                    continue

            # New style
            ns = asgn.get("new_style_id") or f"STYLE-{ctr:03d}"
            groups.append({
                "style_id":    ns,
                "garment_type": asgn.get("garment_type") or new_item.get("garment_type"),
                "image_ids":   [new_item["id"]],
            })
            ctr += 1

        # Safety: ensure nothing from the chunk is lost
        assigned_ids = {iid for g in groups for iid in g["image_ids"]}
        for item in chunk:
            if item["id"] not in assigned_ids:
                groups.append({
                    "style_id":    item.get("style_id") or f"STYLE-{ctr:03d}",
                    "garment_type": item.get("garment_type"),
                    "image_ids":   [item["id"]],
                })
                ctr += 1

        await asyncio.sleep(0.5)  # brief pause between anchor calls

    return groups


async def _call_with_anchors(anchors: list[dict], new_items: list[dict]) -> list[dict]:
    """
    Sends anchor images + new images to the vision model.
    Returns per-image assignment list.
    """
    content: list[dict] = []
    anchor_descs: list[str] = []
    new_descs:    list[str] = []

    # Add anchor images
    for i, a in enumerate(anchors, start=1):
        try:
            content.append(_img_block(a["path"], THUMB_ANCHOR))
        except Exception:
            continue
        anchor_descs.append(
            f"  [ANCHOR {i}: style={a['_anchor_style']!r} garment={a.get('_anchor_gtype','?')}]"
        )
        content.append({"type": "text", "text": f"[ANCHOR {i}: style_id={a['_anchor_style']!r}]"})

    # Add new images
    for j, item in enumerate(new_items, start=1):
        path = item.get("path", "")
        if not path or not Path(path).exists():
            new_descs.append(f"  [NEW img_num={j} id={item['id']} — IMAGE UNAVAILABLE]")
            continue
        try:
            content.append(_img_block(path, THUMB_GARMENT))
        except Exception:
            continue
        hint = f" ref={item['style_id']!r}" if item.get("style_id") else ""
        new_descs.append(f"  [NEW img_num={j} id={item['id']} type={item.get('image_type','?')}{hint}]")
        content.append({"type": "text", "text": f"[NEW img_num={j} id={item['id']}]"})

    if not new_descs:
        return []

    content.append({
        "type": "text",
        "text": _PROMPT_ANCHOR.format(
            anchor_descriptions="\n".join(anchor_descs) or "  (none)",
            new_descriptions="\n".join(new_descs),
        ),
    })

    try:
        data = await _call_vision(content, max_tokens=1500)
        return data.get("assignments", [])
    except Exception:
        # If anchor call fails, treat all new items as new styles
        return [{"img_num": j + 1, "anchor_style_id": None,
                 "new_style_id": None, "garment_type": item.get("garment_type")}
                for j, item in enumerate(new_items)]


# ── 4. Top-level orchestrator ─────────────────────────────────────────────────

async def group_images(
    image_summaries: list[dict],
    upload_order: list[str] | None = None,
) -> dict:
    """
    Three-phase grouping (purely visual — no text descriptions used for grouping):
      A: Visual grouping of garment images (single call or anchor-chunked)
      B: Deterministic spec-label assignment
      C: Coverage check
    """
    if not image_summaries:
        return {"groups": []}

    garment_items = [i for i in image_summaries if i.get("image_type") != "spec_label"]
    spec_items    = [i for i in image_summaries if i.get("image_type") == "spec_label"]

    # Phase A — visual grouping
    if len(garment_items) == 0:
        raw_groups: list[dict] = []
    elif len(garment_items) <= SINGLE_CALL_LIMIT:
        raw_groups = await visual_group_batch(garment_items)
    else:
        raw_groups = await _anchor_chunked_group(garment_items)

    # Phase B — spec label assignment
    upload_order = upload_order or [i["id"] for i in image_summaries]
    raw_groups = _assign_spec_labels(spec_items, raw_groups, upload_order, image_summaries)

    # Phase C — coverage
    raw_groups = _ensure_complete_coverage(raw_groups, image_summaries)

    return {"groups": raw_groups}


# ── 5. Spec-label assignment ──────────────────────────────────────────────────

def _assign_spec_labels(
    spec_items: list[dict],
    garment_groups: list[dict],
    upload_order: list[str],
    all_items: list[dict],
) -> list[dict]:
    """
    Assigns each spec_label image to a garment group.
    Priority:
      1. Reference-number match (spec style_id == group style_id)
      2. Upload-order proximity (label was uploaded near the garment)
      3. Standalone fallback
    """
    if not spec_items:
        return garment_groups

    groups = [dict(g, image_ids=list(g["image_ids"])) for g in garment_groups]

    for spec in spec_items:
        spec_id  = spec["id"]
        spec_ref = (spec.get("style_id") or "").strip().lower()
        assigned = False

        # 1. Reference number match
        if spec_ref:
            for grp in groups:
                if grp.get("style_id", "").strip().lower() == spec_ref:
                    grp["image_ids"].append(spec_id)
                    assigned = True
                    break
            if not assigned:
                for grp in groups:
                    for iid in grp.get("image_ids", []):
                        item = next((x for x in all_items if x["id"] == iid), None)
                        if item and (item.get("style_id") or "").strip().lower() == spec_ref:
                            grp["image_ids"].append(spec_id)
                            assigned = True
                            break
                    if assigned:
                        break

        # 2. Upload-order proximity
        if not assigned and spec_id in upload_order:
            spec_pos = upload_order.index(spec_id)
            best, dist = None, float("inf")
            for grp in groups:
                for iid in grp.get("image_ids", []):
                    if iid in upload_order:
                        d = abs(upload_order.index(iid) - spec_pos)
                        if d < dist:
                            dist, best = d, grp
            if best:
                best["image_ids"].append(spec_id)
                assigned = True

        # 3. Standalone
        if not assigned:
            groups.append({
                "style_id":    spec.get("style_id") or f"SPEC-{len(groups)+1:03d}",
                "garment_type": None,
                "image_ids":   [spec_id],
            })

    return groups


# ── 6. Coverage check ─────────────────────────────────────────────────────────

def _ensure_complete_coverage(groups: list[dict], all_items: list[dict]) -> list[dict]:
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


# ── 7. Pure upload-order fallback (last resort only) ─────────────────────────

def _upload_order_fallback(items: list[dict]) -> list[dict]:
    """
    Used ONLY when ALL vision API calls fail.
    Groups by upload order in batches of 4 (typical: front+back+detail+spec).
    """
    groups = []
    for i in range(0, len(items), 4):
        batch = items[i:i + 4]
        groups.append({
            "style_id":    batch[0].get("style_id") or f"STYLE-{len(groups)+1:03d}",
            "garment_type": batch[0].get("garment_type"),
            "image_ids":   [x["id"] for x in batch],
        })
    return groups
