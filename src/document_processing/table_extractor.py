from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.config import TABLE_EXTRACTION_ENABLED


@dataclass
class TableExtractionResult:
    status: str
    tables: list[dict] = field(default_factory=list)
    message: str = ""


def extract_tables(path: str | Path) -> TableExtractionResult:
    if not TABLE_EXTRACTION_ENABLED:
        return TableExtractionResult(
            status="skipped",
            message="Table extraction is disabled. Set TABLE_EXTRACTION_ENABLED=true to enable it.",
        )
    return TableExtractionResult(status="skipped", message="Table extraction adapter is not implemented yet.")
