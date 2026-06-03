from __future__ import annotations

import re
import shutil
import hashlib
from dataclasses import asdict
from pathlib import Path

from src.chat.chat_models import FileMeta, new_id, now_iso
from src.chat.chat_store import ChatStore
from src.config import RAW_DOCS_DIR, SUPPORTED_EXTENSIONS, VECTOR_STORE_DIR
from src.files.indexing_status import IndexingStatus


def chat_raw_docs_dir(chat_id: str) -> Path:
    path = RAW_DOCS_DIR / f"chat_{chat_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def chat_vector_dir(chat_id: str) -> Path:
    path = VECTOR_STORE_DIR / f"chat_{chat_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def chat_faiss_index_dir(chat_id: str) -> Path:
    path = chat_vector_dir(chat_id) / "faiss_index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def chat_manifest_path(chat_id: str) -> Path:
    return chat_vector_dir(chat_id) / "manifest.json"


def safe_filename(name: str) -> str:
    path_name = Path(name).name
    stem = re.sub(r"[^A-Za-z0-9_.\-\u0600-\u06FF ]+", "_", Path(path_name).stem).strip()
    suffix = Path(path_name).suffix.lower()
    return f"{stem[:80] or 'file'}{suffix}"


def save_uploaded_files(chat_id: str, uploaded_files, store: ChatStore | None = None) -> list[dict]:
    if not uploaded_files:
        return []

    store = store or ChatStore()
    chat = store.ensure_chat(chat_id)
    docs_dir = chat_raw_docs_dir(chat_id)
    saved_files = []
    existing_hashes = {
        item.get("content_hash")
        for item in chat.get("files", [])
        if item.get("content_hash")
    }
    existing_name_sizes = {
        (item.get("original_name"), int(item.get("size_bytes") or 0))
        for item in chat.get("files", [])
    }

    for uploaded_file in uploaded_files:
        extension = Path(uploaded_file.name).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            continue
        data = uploaded_file.getbuffer()
        content_hash = hashlib.sha256(data).hexdigest()
        size_bytes = len(data)
        if content_hash in existing_hashes or (uploaded_file.name, size_bytes) in existing_name_sizes:
            continue

        file_id = new_id("file")
        saved_name = f"{file_id}_{safe_filename(uploaded_file.name)}"
        target = docs_dir / saved_name
        target.write_bytes(data)

        meta = asdict(
            FileMeta(
                file_id=file_id,
                original_name=uploaded_file.name,
                saved_name=saved_name,
                path=str(target),
                size_bytes=size_bytes,
                extension=extension,
                upload_time=now_iso(),
                indexing_status=IndexingStatus.FILES_UPLOADED,
            )
        )
        meta["content_hash"] = content_hash
        chat.setdefault("files", []).append(meta)
        saved_files.append(meta)
        existing_hashes.add(content_hash)
        existing_name_sizes.add((uploaded_file.name, size_bytes))

    if saved_files:
        chat["indexing_status"] = IndexingStatus.FILES_UPLOADED
        chat["indexing_step"] = "Files uploaded"
        store.save_chat(chat)

    return saved_files


def delete_file(chat_id: str, file_id: str, store: ChatStore | None = None) -> bool:
    store = store or ChatStore()
    chat = store.ensure_chat(chat_id)
    files = chat.get("files", [])
    kept_files = []
    deleted = False

    for file_meta in files:
        if file_meta.get("file_id") == file_id:
            path = Path(file_meta.get("path", ""))
            if path.exists():
                path.unlink()
            deleted = True
        else:
            kept_files.append(file_meta)

    if deleted:
        chat["files"] = kept_files
        chat["indexing_status"] = IndexingStatus.DIRTY if kept_files else IndexingStatus.EMPTY
        chat["indexing_step"] = "File deleted; index needs refresh" if kept_files else ""
        store.save_chat(chat)

    return deleted


def delete_chat_assets(chat_id: str) -> None:
    for path in (RAW_DOCS_DIR / f"chat_{chat_id}", VECTOR_STORE_DIR / f"chat_{chat_id}"):
        if path.exists():
            shutil.rmtree(path)


def mark_file_status(chat_id: str, status: str, store: ChatStore | None = None) -> None:
    store = store or ChatStore()
    chat = store.ensure_chat(chat_id)
    for file_meta in chat.get("files", []):
        file_meta["indexing_status"] = status
    chat["indexing_status"] = status
    store.save_chat(chat)
