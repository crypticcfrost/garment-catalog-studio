from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class ImageStatus(str, Enum):
    UPLOADED = "uploaded"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ASSIGNED = "assigned"
    COMPLETE = "complete"
    ERROR = "error"


class ImageType(str, Enum):
    FRONT = "front"
    BACK = "back"
    DETAIL = "detail"
    SPEC_LABEL = "spec_label"
    UNKNOWN = "unknown"


class GarmentData(BaseModel):
    reference_number: Optional[str] = None
    fabric_composition: Optional[str] = None
    gsm: Optional[str] = None
    date: Optional[str] = None
    garment_type: Optional[str] = None
    brand: Optional[str] = None
    size: Optional[str] = None
    origin: Optional[str] = None
    colors: Optional[List[str]] = Field(default_factory=list)


class ImageItem(BaseModel):
    id: str
    filename: str
    original_path: str
    # When set (e.g. Vercel Blob), browsers and other instances load bytes from this URL.
    original_public_url: Optional[str] = None
    processed_path: Optional[str] = None
    processed_public_url: Optional[str] = None
    status: ImageStatus = ImageStatus.UPLOADED
    image_type: Optional[ImageType] = None
    style_id: Optional[str] = None
    confidence: float = 0.0
    garment_data: Optional[GarmentData] = None
    error_message: Optional[str] = None
    description: Optional[str] = None
    colors: Optional[List[str]] = Field(default_factory=list)
    # Structured attributes extracted during classification (used as grouping constraints)
    collar_type: Optional[str] = None
    sleeve_length: Optional[str] = None
    body_length: Optional[str] = None
    fit: Optional[str] = None
    texture: Optional[str] = None
    distinctive_features: Optional[List[str]] = Field(default_factory=list)
    retry_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class StyleGroup(BaseModel):
    id: str
    style_id: str
    garment_type: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    garment_data: Optional[GarmentData] = None
    slide_number: Optional[int] = None
    version: int = 1


class PipelineStep(BaseModel):
    id: str
    label: str
    status: str = "pending"
    progress: int = 0
    message: Optional[str] = None


class Session(BaseModel):
    id: str
    status: str = "idle"
    images: Dict[str, Any] = Field(default_factory=dict)
    groups: Dict[str, Any] = Field(default_factory=dict)
    pipeline_steps: List[Any] = Field(default_factory=list)
    ppt_path: Optional[str] = None
    ppt_public_url: Optional[str] = None
    version: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    error: Optional[str] = None
