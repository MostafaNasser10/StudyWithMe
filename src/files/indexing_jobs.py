from __future__ import annotations

import os
import subprocess
import sys
from threading import Lock, Thread
from pathlib import Path

from src.chat.chat_store import ChatStore
from src.files.indexing_status import IndexingStatus


_ACTIVE_INDEXING_JOBS: set[str] = set()
_ACTIVE_INDEXING_LOCK = Lock()


def start_indexing_worker(chat_id: str) -> None:
    mode = os.getenv("INDEXING_WORKER_MODE", "thread").strip().lower()
    if mode != "process":
        with _ACTIVE_INDEXING_LOCK:
            if chat_id in _ACTIVE_INDEXING_JOBS:
                return
            _ACTIVE_INDEXING_JOBS.add(chat_id)

        def run_in_thread() -> None:
            try:
                from src.indexing_worker import run_indexing_job

                run_indexing_job(chat_id)
            finally:
                with _ACTIVE_INDEXING_LOCK:
                    _ACTIVE_INDEXING_JOBS.discard(chat_id)

        Thread(target=run_in_thread, daemon=True, name=f"indexing-{chat_id}").start()
        return

    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(
        [sys.executable, "-m", "src.indexing_worker", chat_id],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )


def start_indexing_job(
    chat_id: str,
    store: ChatStore | None = None,
    *,
    step: str = "Preparing index",
    force: bool = False,
) -> bool:
    store = store or ChatStore()
    chat = store.ensure_chat(chat_id)
    files = chat.get("files") or []
    if not files:
        return False
    with _ACTIVE_INDEXING_LOCK:
        if chat_id in _ACTIVE_INDEXING_JOBS and not force:
            return False
    if chat.get("indexing_status") == IndexingStatus.INDEXING and not force:
        return False

    for item in files:
        item["indexing_status"] = IndexingStatus.INDEXING
    store.update_chat(
        chat_id,
        files=files,
        indexing_status=IndexingStatus.INDEXING,
        indexing_step=step,
    )
    start_indexing_worker(chat_id)
    return True
