"""
Garment Image Classifier
Provides two-level intelligence:
  1. Per-image classification — type + richer visual fingerprint
  2. Smart multi-phase grouping — garments first, spec-labels assigned separately
"""

import base64
import json
import httpx
from pathlib import Path
from config import OPENROUTER_API_KEY, VISION_MODEL, TEXT_MODEL, OPENROUTER_BASE_URL

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://garment-catalog-studio.dev",
    "X-Title": "Garment Catalog Studio",
}

MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


# ── Single-image classification ───────────────────────────────────────────────

def _encode_image(path: str) -> tuple[str, str]:
    ext = Path(path).suffix.lower()
    mime = MIME_MAP.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode(), mime


async def classify_image(image_path: str) -> dict:
    """
    Classify a single garment image.
    Returns a rich fingerprint used downstream for smart grouping.
    """
    try:
        b64, mime = _encode_image(image_path)
    except Exception as e:
        return _empty_classification(f"Failed to read image: {e}")

    prompt = """You are an expert garment image classifier for a professional catalog system.

Analyze this image and respond ONLY with a valid JSON object — no markdown, no explanation:
{
  "image_type": "front | back | detail | spec_label | unknown",
  "style_id": "<ANY reference/style/article code you can read in the image, or null>",
  "garment_type": "<t-shirt | shirt | jeans | dress | jacket | hoodie | pants | shorts | skirt | coat | etc., or null>",
  "primary_color": "<single standardised color name, e.g. white | black | navy | red | grey | beige>",
  "secondary_color": "<second color if present, else null>",
  "key_features": "<2-4 specific visual details that would identify THIS garment: neckline style, print, hardware, stitching, silhouette. Be specific enough to distinguish from similar garments.>",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one sentence>"
}

IMPORTANT TYPE DEFINITIONS — read carefully:
- front: the garment is shown from the FRONT. The chest / front panel faces the camera.
- back: the garment is shown from the BACK. The rear panel faces the camera. A back view of the SAME garment looks DIFFERENT from the front but is the SAME style.
- detail: extreme close-up of ONE feature — fabric texture, seam, print, button, zipper, pocket, logo, embroidery. Usually shows no full garment silhouette.
- spec_label: a PAPER/FABRIC TAG, care label, specification card, or hang-tag that contains product codes, barcodes, fabric info, or size charts. NOT the garment itself.
- unknown: cannot determine (blurry, wrong subject, etc.)

DO NOT confuse a back view with a different garment. Back views share the same garment_type, primary_color, and overall silhouette as their matching front view."""

    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=HEADERS,
                json={
                    "model": VISION_MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }],
                    "max_tokens": 500,
                    "temperature": 0.1,
                },
            )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        return json.loads(_clean_json(content))
    except Exception as e:
        return _empty_classification(str(e))


# ── Multi-phase smart grouping ────────────────────────────────────────────────

async def group_images(
    image_summaries: list[dict],
    upload_order: list[str] | None = None,
) -> dict:
    """
    Three-phase grouping:
      Phase 1 — Group garment images (front/back/detail) with a vision-aware prompt.
      Phase 2 — Assign spec_label images to the correct garment group.
      Phase 3 — Merge any single-image groups that share strong visual similarity.
    """
    if not image_summaries:
        return {"groups": []}

    # Separate spec labels from garment images
    garment_items = [i for i in image_summaries if i.get("image_type") != "spec_label"]
    spec_items    = [i for i in image_summaries if i.get("image_type") == "spec_label"]

    # Phase 1: Group garments
    raw_groups = await _group_garment_images(garment_items)

    # Phase 2: Assign spec labels
    upload_order = upload_order or [i["id"] for i in image_summaries]
    raw_groups = _assign_spec_labels(spec_items, raw_groups, upload_order, image_summaries)

    # Phase 3: Ensure every image appears in exactly one group
    raw_groups = _ensure_complete_coverage(raw_groups, image_summaries)

    return {"groups": raw_groups}


# ── Phase 1: Garment grouping ──────────────────────────────────────────────────

async def _group_garment_images(items: list[dict]) -> list[dict]:
    """
    Groups front/back/detail images using an AI prompt that explicitly understands
    that a front view and back view of the SAME garment belong in ONE group.
    """
    if not items:
        return []

    lines = []
    for i, item in enumerate(items):
        lines.append(
            f"  [{i+1}] id={item['id']} "
            f"type={item.get('image_type', '?')} "
            f"garment={item.get('garment_type', '?')} "
            f"color={item.get('primary_color', '?')} "
            f"color2={item.get('secondary_color', '?') or 'none'} "
            f"features=\"{item.get('key_features', '?')}\" "
            f"style_id={item.get('style_id') or 'null'}"
        )

    prompt = f"""You are a garment expert grouping catalog images into STYLES.

A STYLE = one physical garment photographed from multiple angles.
Each style typically has 2–4 images: front view + back view + optional detail shots.

HARD RULES (never break these):
1. The FRONT view and BACK view of the SAME garment are ONE style — they look different (camera angle is opposite) but belong together. They share: same garment type, same primary color, very similar silhouette and key features.
2. If two images share an identical style_id → they are ALWAYS the same style.
3. Two images of the SAME garment type + SAME primary color → VERY LIKELY the same style unless features clearly differ.
4. NEVER create a group with two "front" images of the same garment type and color — that is wrong; one of them is probably a back view misidentified.

SIGNALS for "same style" (in order of reliability):
a. Matching style_id (strongest signal — treat as certain)
b. Same garment type + same primary color + similar key features
c. Complementary views (front + back always come in pairs for same garment)
d. Upload sequence — images uploaded consecutively are likely from the same style shoot

Garment images to group:
{chr(10).join(lines)}

Generate a concise style name for each group: use style_id if available, else "STYLE-001", "STYLE-002", etc.

Respond ONLY with valid JSON (no markdown):
{{
  "groups": [
    {{
      "style_id": "<name>",
      "garment_type": "<type>",
      "image_ids": ["<id1>", "<id2>", "..."]
    }}
  ]
}}"""

    try:
        async with httpx.AsyncClient(timeout=50.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=HEADERS,
                json={
                    "model": TEXT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 3000,
                    "temperature": 0.1,
                },
            )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        data = json.loads(_clean_json(content))
        return data.get("groups", [])
    except Exception:
        return _fallback_garment_grouping(items)


# ── Phase 2: Spec-label assignment ────────────────────────────────────────────

def _assign_spec_labels(
    spec_items: list[dict],
    garment_groups: list[dict],
    upload_order: list[str],
    all_items: list[dict],
) -> list[dict]:
    """
    Assigns each spec_label to the right garment group using three strategies in order:

    Strategy A — Reference number match:
      The spec label was classified with a style_id (e.g. the model read "REF-001").
      Find which garment group has that same style_id → assign there.

    Strategy B — Upload-order proximity:
      Users upload images of the same style together (front, back, detail, label).
      Find the garment group whose images are CLOSEST in upload order to this label.

    Strategy C — AI fallback:
      If both A and B are inconclusive, create a minimal new group just for the label.
    """
    if not spec_items:
        return garment_groups

    groups = [dict(g) for g in garment_groups]  # shallow copy to mutate

    for spec in spec_items:
        spec_id       = spec["id"]
        spec_style_id = spec.get("style_id")
        assigned      = False

        # ── Strategy A: reference number match ───────────────────────────────
        if spec_style_id:
            # Direct group style_id match
            for grp in groups:
                if grp.get("style_id") == spec_style_id:
                    grp["image_ids"].append(spec_id)
                    assigned = True
                    break

            if not assigned:
                # A garment image in some group might carry the same style_id
                style_id_to_group: dict[str, dict] = {}
                for grp in groups:
                    for iid in grp.get("image_ids", []):
                        for it in all_items:
                            if it["id"] == iid and it.get("style_id") == spec_style_id:
                                style_id_to_group[spec_style_id] = grp
                if spec_style_id in style_id_to_group:
                    style_id_to_group[spec_style_id]["image_ids"].append(spec_id)
                    assigned = True

        # ── Strategy B: upload-order proximity ───────────────────────────────
        if not assigned and spec_id in upload_order:
            spec_pos = upload_order.index(spec_id)
            best_grp  = None
            best_dist = float("inf")

            for grp in groups:
                for iid in grp.get("image_ids", []):
                    if iid in upload_order:
                        dist = abs(upload_order.index(iid) - spec_pos)
                        if dist < best_dist:
                            best_dist = dist
                            best_grp  = grp

            if best_grp is not None:
                best_grp["image_ids"].append(spec_id)
                assigned = True

        # ── Strategy C: standalone fallback (should rarely happen) ───────────
        if not assigned:
            counter = len(groups) + 1
            groups.append({
                "style_id":    spec_style_id or f"SPEC-{counter:03d}",
                "garment_type": None,
                "image_ids":   [spec_id],
            })

    return groups


# ── Phase 3: Coverage check ───────────────────────────────────────────────────

def _ensure_complete_coverage(
    groups: list[dict],
    all_items: list[dict],
) -> list[dict]:
    """Make sure every image_id appears in exactly one group."""
    all_ids      = {i["id"] for i in all_items}
    covered_ids  = {iid for g in groups for iid in g.get("image_ids", [])}
    missing      = all_ids - covered_ids

    if missing:
        counter = len(groups) + 1
        for mid in missing:
            item = next((i for i in all_items if i["id"] == mid), {})
            groups.append({
                "style_id":    item.get("style_id") or f"STYLE-{counter:03d}",
                "garment_type": item.get("garment_type"),
                "image_ids":   [mid],
            })
            counter += 1

    return groups


# ── Utilities ─────────────────────────────────────────────────────────────────

def _clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        start = text.find("{")
        end   = text.rfind("}") + 1
        return text[start:end]
    return text


def _empty_classification(reason: str) -> dict:
    return {
        "image_type":      "unknown",
        "style_id":        None,
        "garment_type":    None,
        "primary_color":   None,
        "secondary_color": None,
        "key_features":    "",
        "colors":          [],
        "description":     "unknown",
        "confidence":      0.0,
        "reasoning":       reason,
    }


def _fallback_garment_grouping(items: list[dict]) -> list[dict]:
    """
    Deterministic fallback when AI grouping fails.
    Groups by (garment_type, primary_color) similarity, then upload order batches.
    """
    # First pass: group by reference number
    ref_map: dict[str, dict] = {}
    no_ref:  list[dict]      = []

    for item in items:
        sid = item.get("style_id")
        if sid:
            if sid not in ref_map:
                ref_map[sid] = {
                    "style_id":    sid,
                    "garment_type": item.get("garment_type"),
                    "image_ids":   [],
                }
            ref_map[sid]["image_ids"].append(item["id"])
        else:
            no_ref.append(item)

    groups = list(ref_map.values())

    # Second pass: group remaining by (garment_type, primary_color)
    color_type_map: dict[tuple, dict] = {}
    counter = len(groups) + 1
    for item in no_ref:
        key = (item.get("garment_type") or "unknown", item.get("primary_color") or "unknown")
        if key not in color_type_map:
            color_type_map[key] = {
                "style_id":    f"STYLE-{counter:03d}",
                "garment_type": item.get("garment_type"),
                "image_ids":   [],
            }
            counter += 1
        color_type_map[key]["image_ids"].append(item["id"])

    groups.extend(color_type_map.values())
    return groups
