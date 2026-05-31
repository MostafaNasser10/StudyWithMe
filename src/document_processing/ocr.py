from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config import OCR_ENABLED


@dataclass
class OCRResult:
    status: str
    text: str = ""
    message: str = ""


def run_ocr(path: str | Path) -> OCRResult:
    if not OCR_ENABLED:
        return OCRResult(status="skipped", message="OCR is disabled. Set OCR_ENABLED=true to enable it.")
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return OCRResult(status="skipped", message="pytesseract and Pillow are not installed.")

    try:
        text = pytesseract.image_to_string(Image.open(path), lang="ara+eng")
    except Exception as exc:
        return OCRResult(status="error", message=str(exc))
    return OCRResult(status="ok", text=text)
