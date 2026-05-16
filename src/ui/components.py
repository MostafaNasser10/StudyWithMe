from __future__ import annotations

import html


def safe_text(value) -> str:
    return html.escape(str(value if value is not None else ""))


def short_name(name: str, max_len: int = 34) -> str:
    if len(name) <= max_len:
        return name
    return f"{name[: max_len - 10]}...{name[-7:]}"


def format_bytes(size: int | float | None) -> str:
    if size is None:
        return "N/A"
    size = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"

