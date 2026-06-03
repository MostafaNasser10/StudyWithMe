from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from time import perf_counter

from langchain_community.vectorstores import FAISS

from src.chat.chat_models import now_iso
from src.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_MODEL_NAME,
    FAISS_INDEX_DIR,
    INDEX_METADATA_PATH,
    RAW_DOCS_DIR,
    TOP_K,
)
from src.document_loader import load_documents
from src.embeddings import get_embedding_model
from src.files.file_manager import chat_faiss_index_dir, chat_manifest_path, chat_raw_docs_dir
from src.files.indexing_status import IndexingResult, IndexingStatus
from src.text_splitter import split_documents


_VECTOR_STORES: dict[str, FAISS] = {}
_VECTOR_STORE_SIGNATURES: dict[str, tuple] = {}


def _key(chat_id: str | None) -> str:
    return chat_id or "__global__"


def _index_dir(chat_id: str | None = None) -> Path:
    return chat_faiss_index_dir(chat_id) if chat_id else FAISS_INDEX_DIR


def _manifest_path(chat_id: str | None = None) -> Path:
    return chat_manifest_path(chat_id) if chat_id else INDEX_METADATA_PATH


def _docs_dir(chat_id: str | None = None) -> Path:
    return chat_raw_docs_dir(chat_id) if chat_id else RAW_DOCS_DIR


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_config() -> dict:
    return {
        "embedding_model_name": EMBEDDING_MODEL_NAME,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
    }


def _current_files(chat_id: str | None) -> list[dict]:
    docs_dir = _docs_dir(chat_id)
    if not docs_dir.exists():
        return []

    files = []
    for path in sorted(docs_dir.iterdir()):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_time": stat.st_mtime,
                "content_hash": _hash_file(path),
            }
        )
    return files


def load_manifest(chat_id: str | None = None) -> dict | None:
    path = _manifest_path(chat_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_manifest(chat_id: str | None, files: list[dict]) -> dict:
    manifest = {
        **_current_config(),
        "files": files,
    }
    path = _manifest_path(chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def index_exists(chat_id: str | None = None) -> bool:
    index_dir = _index_dir(chat_id)
    return (index_dir / "index.faiss").exists() and (index_dir / "index.pkl").exists()


def _index_signature(chat_id: str | None = None) -> tuple | None:
    paths = [_manifest_path(chat_id), _index_dir(chat_id) / "index.faiss", _index_dir(chat_id) / "index.pkl"]
    signature = []
    for path in paths:
        if not path.exists():
            return None
        stat = path.stat()
        signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def create_vector_store(chunks):
    if not chunks:
        return None
    return FAISS.from_documents(documents=chunks, embedding=get_embedding_model())


def save_vector_store(vector_store, chat_id: str | None = None) -> None:
    if vector_store is None:
        return
    index_dir = _index_dir(chat_id)
    index_dir.mkdir(parents=True, exist_ok=True)
    vector_store.save_local(str(index_dir))


def load_vector_store(chat_id: str | None = None):
    if not index_exists(chat_id):
        return None
    return FAISS.load_local(
        str(_index_dir(chat_id)),
        get_embedding_model(),
        allow_dangerous_deserialization=True,
    )


def delete_vector_store(chat_id: str | None = None) -> None:
    index_dir = _index_dir(chat_id)
    if index_dir.exists():
        shutil.rmtree(index_dir)
    manifest_path = _manifest_path(chat_id)
    if manifest_path.exists():
        manifest_path.unlink()
    _VECTOR_STORES.pop(_key(chat_id), None)
    _VECTOR_STORE_SIGNATURES.pop(_key(chat_id), None)


def analyze_index_changes(chat_id: str | None = None) -> dict:
    manifest = load_manifest(chat_id)
    current_files = _current_files(chat_id)

    if not current_files:
        return {"needs_full_rebuild": False, "reason": "empty", "changed": False}

    if manifest is None or not index_exists(chat_id):
        return {"needs_full_rebuild": True, "reason": "missing index", "changed": True}

    for key, value in _current_config().items():
        if manifest.get(key) != value:
            return {"needs_full_rebuild": True, "reason": "config changed", "changed": True}

    old_files = {item["path"]: item for item in manifest.get("files", [])}
    new_files = {item["path"]: item for item in current_files}

    if set(old_files) != set(new_files):
        return {"needs_full_rebuild": True, "reason": "files added or deleted", "changed": True}

    for path, info in new_files.items():
        old = old_files[path]
        if (
            info["size_bytes"] != old.get("size_bytes")
            or info["modified_time"] != old.get("modified_time")
            or info["content_hash"] != old.get("content_hash")
        ):
            return {"needs_full_rebuild": True, "reason": "file modified", "changed": True}

    return {"needs_full_rebuild": False, "reason": "up to date", "changed": False}


def rebuild_all(chat_id: str | None = None, tracer=None) -> IndexingResult:
    result = IndexingResult(status=IndexingStatus.INDEXING, full_rebuild=True)

    try:
        if tracer:
            tracer("Preparing index rebuild")
        delete_vector_store(chat_id)

        if tracer:
            tracer("Loading documents")
        started = perf_counter()
        documents = load_documents(chat_id=chat_id)
        result.steps.append(
            {"name": "Loading documents", "status": "ok", "duration_ms": round((perf_counter() - started) * 1000)}
        )

        if not documents:
            result.status = IndexingStatus.EMPTY
            result.step = "No files to index"
            return result

        if tracer:
            tracer("Splitting documents")
        started = perf_counter()
        chunks = split_documents(documents)
        result.steps.append(
            {"name": "Splitting documents", "status": "ok", "duration_ms": round((perf_counter() - started) * 1000)}
        )

        if tracer:
            tracer(f"Creating embeddings for {len(chunks)} chunks")
        started = perf_counter()
        vector_store = create_vector_store(chunks)
        result.steps.append(
            {"name": "Creating embeddings", "status": "ok", "duration_ms": round((perf_counter() - started) * 1000)}
        )

        if tracer:
            tracer("Saving vector store")
        started = perf_counter()
        save_vector_store(vector_store, chat_id=chat_id)
        result.steps.append(
            {"name": "Saving vector store", "status": "ok", "duration_ms": round((perf_counter() - started) * 1000)}
        )

        indexed_files = []
        for item in _current_files(chat_id):
            item["indexed_at"] = now_iso()
            indexed_files.append(item)
        save_manifest(chat_id, indexed_files)

        _VECTOR_STORES[_key(chat_id)] = vector_store
        signature = _index_signature(chat_id)
        if signature is not None:
            _VECTOR_STORE_SIGNATURES[_key(chat_id)] = signature
        result.status = IndexingStatus.READY
        result.step = "Ready"
        result.files_indexed = len(indexed_files)
        result.chunks_indexed = len(chunks)
        result.manifest_changed = True
        result.steps.append({"name": "Ready", "status": "ok", "duration_ms": 0})
        if tracer:
            tracer("Ready")
        return result
    except Exception as exc:
        result.status = IndexingStatus.FAILED
        result.step = "Indexing failed"
        result.errors.append(str(exc))
        return result


def get_vector_store(chat_id: str | None = None, *, auto_rebuild: bool = False):
    store_key = _key(chat_id)
    signature = _index_signature(chat_id)
    if (
        signature is not None
        and store_key in _VECTOR_STORES
        and _VECTOR_STORE_SIGNATURES.get(store_key) == signature
    ):
        return _VECTOR_STORES[store_key]

    changes = analyze_index_changes(chat_id)

    if changes["reason"] == "empty":
        _VECTOR_STORES.pop(store_key, None)
        _VECTOR_STORE_SIGNATURES.pop(store_key, None)
        return None

    if changes["needs_full_rebuild"]:
        if not auto_rebuild:
            _VECTOR_STORES.pop(store_key, None)
            _VECTOR_STORE_SIGNATURES.pop(store_key, None)
            return None
        result = rebuild_all(chat_id)
        if result.status != IndexingStatus.READY:
            return None

    if store_key not in _VECTOR_STORES:
        _VECTOR_STORES[store_key] = load_vector_store(chat_id)
    signature = _index_signature(chat_id)
    if signature is not None:
        _VECTOR_STORE_SIGNATURES[store_key] = signature

    return _VECTOR_STORES.get(store_key)


def retrieve_chunks(query: str, k: int = TOP_K, chat_id: str | None = None):
    vector_store = get_vector_store(chat_id)
    if vector_store is None:
        return []
    return vector_store.similarity_search(query=query, k=k)


def retrieve_chunks_with_scores(query: str, k: int = TOP_K, chat_id: str | None = None):
    vector_store = get_vector_store(chat_id)
    if vector_store is None:
        return []
    try:
        return vector_store.similarity_search_with_score(query=query, k=k)
    except Exception:
        return [(chunk, None) for chunk in vector_store.similarity_search(query=query, k=k)]


def load_index_metadata():
    return load_manifest(None)


def save_index_metadata(metadata: dict):
    INDEX_METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
