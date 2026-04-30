import base64
import json
import httpx
from pathlib import Path
from config import OPENROUTER_API_KEY, VISION_MODEL, OPENROUTER_BASE_URL

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
}


async def extract_spec_data(image_path: str) -> dict:
    """Extract structured specification data from a garment label/spec image."""
    ext = Path(image_path).suffix.lower()
    mime = MIME_MAP.get(ext, "image/jpeg")
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        return _empty_spec(str(e))

    prompt = """You are analyzing a garment specification label, care label, or product tag.

Extract ALL visible information. Respond ONLY with valid JSON (no markdown fences):
{
  "reference_number": "<style/article/ref code or null>",
  "fabric_composition": "<e.g. 100% Cotton or null>",
  "gsm": "<numeric value like 180 or null>",
  "date": "<production/season date or null>",
  "brand": "<brand name or null>",
  "size": "<size info or null>",
  "origin": "<country of origin or null>",
  "other_specs": {},
  "raw_text": "<all text visible in image>",
  "confidence": <0.0 to 1.0>
}

Use null for any field not clearly visible. Do not guess."""

    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=HEADERS,
                json={
                    "model": VISION_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime};base64,{b64}"
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                    "max_tokens": 600,
                    "temperature": 0.1,
                },
            )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            start = content.find("{")
            end = content.rfind("}") + 1
            content = content[start:end]
        return json.loads(content)
    except Exception as e:
        return _empty_spec(str(e))


def _empty_spec(reason: str = "") -> dict:
    return {
        "reference_number": None,
        "fabric_composition": None,
        "gsm": None,
        "date": None,
        "brand": None,
        "size": None,
        "origin": None,
        "other_specs": {},
        "raw_text": "",
        "confidence": 0.0,
        "error": reason,
    }
