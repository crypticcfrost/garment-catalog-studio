import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Primary vision model for classification + extraction
VISION_MODEL = "openai/gpt-4o"

# Text model for grouping logic (cheaper, no vision needed)
TEXT_MODEL = "google/gemini-2.0-flash-001"

MAX_IMAGE_SIZE_MB = 10
BATCH_SIZE = 4  # concurrent AI calls per batch
