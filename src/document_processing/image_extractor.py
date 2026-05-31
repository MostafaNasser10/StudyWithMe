from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.config import IMAGE_EXTRACTION_ENABLED


@dataclass
class ImageExtractionResult:
    status: str
    images: list[dict] = field(default_factory=list)
    message: str = ""


def extract_images(path: str | Path) -> ImageExtractionResult:
    if not IMAGE_EXTRACTION_ENABLED:
        return ImageExtractionResult(
            status="skipped",
            message="Image extraction is disabled. Set IMAGE_EXTRACTION_ENABLED=true to enable it.",
        )
    return ImageExtractionResult(status="skipped", message="Image extraction adapter is not implemented yet.")
