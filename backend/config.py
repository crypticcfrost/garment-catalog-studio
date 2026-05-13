import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()


def _ensure_upload_output_dirs() -> tuple[Path, Path]:
    """
    Return (UPLOAD_DIR, OUTPUT_DIR) that exist and are writable.

    On Vercel serverless the application directory is not writable; only TMPDIR
    (usually /tmp) works for uploads and generated outputs.

    Override with GARMENT_STORAGE_ROOT=/abs/path to force a root directory.
    """
    explicit = os.getenv("GARMENT_STORAGE_ROOT", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    # Vercel sets VERCEL=1 in build and runtime
    if os.getenv("VERCEL"):
        tmp_root = Path(os.getenv("TMPDIR") or tempfile.gettempdir())
        candidates.append(tmp_root / "garment_catalog_studio")
    candidates.append(BASE_DIR)

    seen: set[Path] = set()
    for root in candidates:
        key = root.resolve()
        if key in seen:
            continue
        seen.add(key)
        upload_dir = root / "uploads"
        output_dir = root / "outputs"
        try:
            upload_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            return upload_dir, output_dir
        except OSError:
            continue

    raise RuntimeError(
        "Could not create writable upload/output directories. "
        "Set GARMENT_STORAGE_ROOT to a writable path (e.g. /tmp/garment_catalog_studio on serverless)."
    )


UPLOAD_DIR, OUTPUT_DIR = _ensure_upload_output_dirs()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Primary vision model for classification + extraction
VISION_MODEL = "openai/gpt-4o"

# Text model for grouping logic (cheaper, no vision needed)
TEXT_MODEL = "google/gemini-2.0-flash-001"

MAX_IMAGE_SIZE_MB = 10
BATCH_SIZE = 4  # concurrent AI calls per batch
