from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.chat.chat_models import Chat, ChatMessage, new_id, now_iso
from src.config import CHAT_DIR, DATA_DIR


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    return str(value)


class ChatStore:
    def __init__(self, chat_dir: Path = CHAT_DIR):
        self.chat_dir = chat_dir
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_conversations()

    def chat_path(self, chat_id: str) -> Path:
        return self.chat_dir / f"chat_{chat_id}.json"

    def list_chats(self) -> list[dict[str, Any]]:
        chats = []
        for path in self.chat_dir.glob("chat_*.json"):
            try:
                with path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
            except Exception:
                continue
            chat_id = str(data.get("chat_id") or path.stem.removeprefix("chat_"))
            chats.append(
                {
                    "chat_id": chat_id,
                    "title": data.get("title") or "New Conversation",
                    "updated_at": data.get("updated_at", ""),
                    "created_at": data.get("created_at", ""),
                }
            )
        return sorted(chats, key=lambda chat: chat.get("updated_at", ""), reverse=True)

    def load_chat(self, chat_id: str) -> dict[str, Any] | None:
        path = self.chat_path(chat_id)
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError:
            backup = path.with_suffix(".corrupt.json")
            shutil.copy2(path, backup)
            return None

        return self._normalize_chat(data)

    def save_chat(self, chat: dict[str, Any]) -> None:
        chat = self._normalize_chat(chat)
        path = self.chat_path(chat["chat_id"])
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(_json_safe(chat), file, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def create_chat(self, title: str = "New Conversation") -> dict[str, Any]:
        chat_id = new_id("chat").removeprefix("chat_")
        chat = asdict(
            Chat(
                chat_id=chat_id,
                title=title,
                created_at=now_iso(),
                updated_at=now_iso(),
            )
        )
        self.save_chat(chat)
        return chat

    def ensure_chat(self, chat_id: str | None = None) -> dict[str, Any]:
        if chat_id:
            chat = self.load_chat(chat_id)
            if chat:
                return chat

        chats = self.list_chats()
        if chats:
            chat = self.load_chat(chats[0]["chat_id"])
            if chat:
                return chat
        return self.create_chat()

    def delete_chat(self, chat_id: str) -> None:
        path = self.chat_path(chat_id)
        if path.exists():
            path.unlink()

    def rename_chat(self, chat_id: str, title: str) -> None:
        chat = self.load_chat(chat_id)
        if not chat:
            return
        clean_title = title.strip()
        if not clean_title:
            return
        chat["title"] = clean_title[:80]
        chat["updated_at"] = now_iso()
        self.save_chat(chat)

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        agent: str | None = None,
        docs: list[dict[str, Any]] | None = None,
        trace_id: str | None = None,
        evaluation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chat = self.ensure_chat(chat_id)
        message = asdict(
            ChatMessage(
                message_id=new_id("msg"),
                role=role,
                content=content,
                created_at=now_iso(),
                agent=agent,
                docs=docs or [],
                trace_id=trace_id,
                evaluation_id=evaluation_id,
            )
        )
        if metadata:
            message["metadata"] = metadata
        chat["messages"].append(message)
        chat["updated_at"] = now_iso()
        if role == "user":
            stats = chat.setdefault("stats", {})
            stats["prompts_count"] = int(stats.get("prompts_count", 0)) + 1
            if chat["title"] == "New Conversation":
                chat["title"] = content.strip().replace("\n", " ")[:60] or chat["title"]
        self.save_chat(chat)
        return message

    def update_chat(self, chat_id: str, **fields: Any) -> dict[str, Any]:
        chat = self.ensure_chat(chat_id)
        chat.update(fields)
        chat["updated_at"] = now_iso()
        self.save_chat(chat)
        return chat

    def append_trace(self, chat_id: str, trace: dict[str, Any]) -> None:
        chat = self.ensure_chat(chat_id)
        chat.setdefault("traces", []).append(trace)
        chat["updated_at"] = now_iso()
        self.save_chat(chat)

    def append_evaluation(self, chat_id: str, evaluation: dict[str, Any]) -> None:
        chat = self.ensure_chat(chat_id)
        chat.setdefault("evaluations", []).append(evaluation)
        chat["updated_at"] = now_iso()
        self.save_chat(chat)

    def record_assistant_result(
        self,
        chat_id: str,
        content: str,
        agent: str | None = None,
        docs: list[dict[str, Any]] | None = None,
        trace: dict[str, Any] | None = None,
        evaluation: dict[str, Any] | None = None,
        response_time_ms: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chat = self.ensure_chat(chat_id)
        if evaluation and evaluation.get("evaluation_id"):
            chat.setdefault("evaluations", []).append(evaluation)
        if trace:
            trace.setdefault("timings_ms", {})
            trace["timings_ms"]["total_response_ms"] = response_time_ms
            chat.setdefault("traces", []).append(trace)

        message = asdict(
            ChatMessage(
                message_id=new_id("msg"),
                role="assistant",
                content=content,
                created_at=now_iso(),
                agent=agent,
                docs=docs or [],
                trace_id=(trace or {}).get("prompt_id"),
                evaluation_id=evaluation.get("evaluation_id") if isinstance(evaluation, dict) else None,
            )
        )
        if metadata:
            message["metadata"] = metadata
        chat["messages"].append(message)
        stats = chat.setdefault("stats", {})
        stats["total_response_time_ms"] = int(stats.get("total_response_time_ms", 0) or 0) + int(response_time_ms)
        chat["updated_at"] = now_iso()
        self.save_chat(chat)
        return message

    def _normalize_chat(self, data: dict[str, Any]) -> dict[str, Any]:
        now = now_iso()
        chat_id = str(data.get("chat_id") or data.get("id") or new_id("chat").removeprefix("chat_"))
        return {
            "chat_id": chat_id,
            "title": data.get("title") or "New Conversation",
            "created_at": data.get("created_at") or now,
            "updated_at": data.get("updated_at") or now,
            "files": data.get("files") or [],
            "messages": data.get("messages") or [],
            "traces": data.get("traces") or [],
            "evaluations": data.get("evaluations") or [],
            "active_quiz": data.get("active_quiz"),
            "quiz_history": data.get("quiz_history") or [],
            "stats": data.get("stats") or {},
            "indexing_status": data.get("indexing_status") or "EMPTY",
            "indexing_step": data.get("indexing_step") or "",
        }

    def _migrate_legacy_conversations(self) -> None:
        legacy_path = DATA_DIR / "conversations.json"
        if not legacy_path.exists() or any(self.chat_dir.glob("chat_*.json")):
            return

        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception:
            return

        if not isinstance(data, dict):
            return

        for legacy_id, item in data.items():
            chat = asdict(
                Chat(
                    chat_id=str(legacy_id),
                    title=item.get("title") or "Imported Conversation",
                    created_at=item.get("created_at") or now_iso(),
                    updated_at=item.get("updated_at") or now_iso(),
                    messages=item.get("messages") or [],
                    traces=[],
                    evaluations=[],
                    indexing_status="EMPTY",
                )
            )
            self.save_chat(chat)
