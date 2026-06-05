"""Long-term user preference storage.

Preferences are intentionally manual: users add or delete them through the UI,
and the prompt builder injects them into every answer request.
"""

import json

from src.config import DATA_DIR


PREFERENCES_PATH = DATA_DIR / "memory" / "preferences.json"


def load_preferences() -> list[str]:
    """Load saved long-term user preferences.

    Returns:
        Clean preference strings in saved order. Missing or invalid storage
        returns an empty list.

    Example:
        >>> prefs = load_preferences()
        >>> isinstance(prefs, list)
        True
    """

    if not PREFERENCES_PATH.exists():
        return []
    try:
        data = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    preferences = data.get("preferences") if isinstance(data, dict) else []
    return [str(item).strip() for item in preferences if str(item).strip()]


def save_preferences(preferences: list[str]) -> None:
    """Persist de-duplicated long-term preferences.

    Args:
        preferences:
            Preference strings to clean, de-duplicate, and save.

    Side effects:
        Writes ``data/memory/preferences.json``.

    Example:
        >>> save_preferences(["Explain in Arabic"])
    """

    clean_preferences = []
    seen = set()
    for item in preferences:
        text = str(item).strip()
        if not text or text in seen:
            continue
        clean_preferences.append(text)
        seen.add(text)
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_PATH.write_text(
        json.dumps({"preferences": clean_preferences}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_preference(preference: str) -> list[str]:
    """Add one preference if it is non-empty and not already saved.

    Args:
        preference:
            User-provided preference text.

    Returns:
        Updated preference list.

    Example:
        >>> add_preference("Use simple examples")
        ['Use simple examples']
    """

    preferences = load_preferences()
    text = str(preference or "").strip()
    if text and text not in preferences:
        preferences.append(text)
        save_preferences(preferences)
    return preferences


def delete_preference(index: int) -> list[str]:
    """Delete a preference by index when the index is valid.

    Args:
        index:
            Zero-based preference index from the UI list.

    Returns:
        Updated preference list.

    Example:
        >>> delete_preference(0)
        []
    """

    preferences = load_preferences()
    if 0 <= index < len(preferences):
        preferences.pop(index)
        save_preferences(preferences)
    return preferences


def build_preferences_context() -> str:
    """Render saved preferences for prompt injection.

    Returns:
        A bullet-list context block, or an explicit empty-state sentence.

    Example:
        >>> isinstance(build_preferences_context(), str)
        True
    """

    preferences = load_preferences()
    if not preferences:
        return "No saved long-term user preferences."
    return "\n".join(f"- {item}" for item in preferences)
