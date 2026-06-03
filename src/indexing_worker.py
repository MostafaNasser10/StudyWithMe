from __future__ import annotations

import sys
import traceback

from src.chat.chat_store import ChatStore
from src.files.indexing_status import IndexingStatus


def run_indexing_job(chat_id: str) -> int:
    """Build one chat index outside the Streamlit render process."""

    store = ChatStore()
    try:
        chat = store.load_chat(chat_id)
        if not chat:
            print(f"Chat not found: {chat_id}")
            return 2
        def update_step(step: str) -> None:
            store.update_chat(chat_id, indexing_status=IndexingStatus.INDEXING, indexing_step=step)

        update_step("Checking index changes")
        from src.vector_store import analyze_index_changes, rebuild_all

        changes = analyze_index_changes(chat_id)
        if not changes.get("changed"):
            chat = store.ensure_chat(chat_id)
            files = chat.get("files", [])
            status = IndexingStatus.EMPTY if not files else IndexingStatus.READY
            for item in files:
                item["indexing_status"] = status
            store.update_chat(
                chat_id,
                files=files,
                indexing_status=status,
                indexing_step="Ready" if files else "No files to index",
            )
            return 0

        result = rebuild_all(chat_id, tracer=update_step)
        chat = store.ensure_chat(chat_id)
        files = chat.get("files", [])
        for item in files:
            item["indexing_status"] = result.status
        store.update_chat(
            chat_id,
            files=files,
            indexing_status=result.status,
            indexing_step=result.step,
        )
        return 0 if result.status == IndexingStatus.READY else 1
    except Exception as exc:
        chat = store.ensure_chat(chat_id)
        files = chat.get("files", [])
        for item in files:
            item["indexing_status"] = IndexingStatus.FAILED
        store.update_chat(
            chat_id,
            files=files,
            indexing_status=IndexingStatus.FAILED,
            indexing_step=f"Indexing failed: {exc}"[:500],
        )
        traceback.print_exc()
        return 1


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m src.indexing_worker <chat_id>")
        return 2
    return run_indexing_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
