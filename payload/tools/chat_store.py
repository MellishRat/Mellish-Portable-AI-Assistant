"""Portable, atomic storage for named assistant conversations."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def title_from_messages(messages: list[dict], fallback: str = "New chat") -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        text = re.sub(r"\s+", " ", str(message.get("content", ""))).strip()
        text = re.sub(r"\s*/no_think\s*$", "", text, flags=re.IGNORECASE).strip()
        if text:
            return text[:57] + ("..." if len(text) > 57 else "")
    return fallback


class ChatStore:
    """Stores each chat in its own JSON file and maintains a small index."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path = self.directory / "index.json"

    def new_record(self, settings: dict | None = None) -> dict:
        now = utc_now()
        return {
            "version": 3,
            "id": str(uuid.uuid4()),
            "title": "New chat",
            "created_at": now,
            "updated_at": now,
            "settings": dict(settings or {}),
            "messages": [],
        }

    def path_for(self, chat_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9-]", "", chat_id)
        if not safe_id:
            raise ValueError("Invalid chat identifier")
        return self.directory / f"{safe_id}.json"

    @staticmethod
    def _write_atomic(path: Path, data: dict) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)

    def save(self, record: dict) -> dict:
        chat_id = str(record.get("id") or uuid.uuid4())
        record["id"] = chat_id
        record.setdefault("version", 3)
        record.setdefault("created_at", utc_now())
        record["updated_at"] = utc_now()
        if not str(record.get("title", "")).strip() or record.get("title") == "New chat":
            record["title"] = title_from_messages(record.get("messages", []))
        self._write_atomic(self.path_for(chat_id), record)
        self.rebuild_index()
        return record

    def load(self, chat_id: str) -> dict:
        data = json.loads(self.path_for(chat_id).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("messages", []), list):
            raise ValueError("Chat file has an invalid format")
        data.setdefault("id", chat_id)
        data.setdefault("title", title_from_messages(data.get("messages", [])))
        return data

    def import_file(self, path: Path) -> dict:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("messages", []), list):
            raise ValueError("Chat file has an invalid format")
        record = self.new_record(data.get("settings", {}))
        record["messages"] = data.get("messages", [])
        record["title"] = str(data.get("title") or title_from_messages(record["messages"]))
        return self.save(record)

    def list(self) -> list[dict]:
        if not self.index_path.exists():
            return self.rebuild_index()
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            items = data.get("chats", [])
            if isinstance(items, list):
                return items
        except (OSError, ValueError, TypeError):
            pass
        return self.rebuild_index()

    def rebuild_index(self) -> list[dict]:
        items = []
        for path in self.directory.glob("*.json"):
            if path.name == self.index_path.name or path.name.endswith(".tmp"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "messages" not in data:
                    continue
                items.append({
                    "id": str(data.get("id") or path.stem),
                    "title": str(data.get("title") or title_from_messages(data.get("messages", []))),
                    "created_at": str(data.get("created_at", "")),
                    "updated_at": str(data.get("updated_at", "")),
                    "message_count": len(data.get("messages", [])),
                })
            except (OSError, ValueError, TypeError):
                continue
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        self._write_atomic(self.index_path, {"version": 1, "chats": items})
        return items

    def rename(self, chat_id: str, title: str) -> dict:
        record = self.load(chat_id)
        record["title"] = re.sub(r"\s+", " ", title).strip()[:100] or "New chat"
        return self.save(record)

    def delete(self, chat_id: str) -> None:
        path = self.path_for(chat_id)
        if path.exists():
            path.unlink()
        self.rebuild_index()
