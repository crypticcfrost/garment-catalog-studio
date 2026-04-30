from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
import numpy as np


def process_image(
    input_path: str,
    output_path: str,
    image_type: str = "front",
) -> dict:
    """
    Process a garment image:
    - Fix EXIF orientation
    - Auto-crop whitespace
    - Auto-enhance brightness/contrast/sharpness
    - Standardise portrait orientation for front/back
    - Resize to max 1400px on longest side
    - Preserve aspect ratio at every step
    """
    try:
        img = Image.open(input_path)

        # Normalise colour mode
        if img.mode == "RGBA":
            canvas = Image.new("RGB", img.size, (255, 255, 255))
            canvas.paste(img, mask=img.split()[3])
            img = canvas
        elif img.mode == "P":
            img = img.convert("RGBA").convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Respect EXIF orientation
        img = ImageOps.exif_transpose(img)

        # Auto-crop surrounding whitespace / near-white border
        img = _auto_crop(img, threshold=240, padding=18)

        # Auto-enhance without blowing out colours
        img = _enhance(img)

        # Force portrait for front / back views (no content loss)
        if image_type in ("front", "back"):
            img = _ensure_portrait(img)

        # Resize (maintain aspect ratio)
        img = _resize(img, max_side=1400)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "JPEG", quality=93, optimize=True)

        return {
            "success": True,
            "width": img.width,
            "height": img.height,
            "output_path": output_path,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "output_path": input_path}


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _auto_crop(img: Image.Image, threshold: int = 240, padding: int = 18) -> Image.Image:
    arr = np.array(img)
    # Mask: pixels that are NOT near-white
    mask = np.any(arr < threshold, axis=2)
    if not np.any(mask):
        return img
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    rmin = max(0, rmin - padding)
    rmax = min(img.height - 1, rmax + padding)
    cmin = max(0, cmin - padding)
    cmax = min(img.width - 1, cmax + padding)
    return img.crop((cmin, rmin, cmax + 1, rmax + 1))


def _enhance(img: Image.Image) -> Image.Image:
    # Auto-contrast with a small cutoff to avoid blown highlights
    img = ImageOps.autocontrast(img, cutoff=0.3)

    # Sharpness — subtle boost
    img = ImageEnhance.Sharpness(img).enhance(1.15)

    # Brightness — only brighten if genuinely dark
    mean_lum = float(np.array(img.convert("L")).mean())
    if mean_lum < 90:
        img = ImageEnhance.Brightness(img).enhance(1.12)
    elif mean_lum > 210:
        img = ImageEnhance.Brightness(img).enhance(0.97)

    # Subtle colour saturation boost
    img = ImageEnhance.Color(img).enhance(1.08)

    return img


def _ensure_portrait(img: Image.Image) -> Image.Image:
    """Rotate landscape images to portrait — no content loss."""
    if img.width > img.height:
        img = img.transpose(Image.ROTATE_90)
    return img


def _resize(img: Image.Image, max_side: int = 1400) -> Image.Image:
    w, h = img.size
    scale = min(max_side / w, max_side / h)
    if scale >= 1:
        return img
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
