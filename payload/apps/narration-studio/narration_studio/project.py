from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_FILE = "project.json"
VALID_TYPES = {"dialogue", "narration", "thought", "caption", "sound_effect"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_slug(value: str, fallback: str = "project") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug[:80] or fallback


def new_line(text: str, *, speaker: str = "Narrator", kind: str = "narration", part: int = 1,
             direction: str = "", confidence: float = 1.0, source: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "part": max(1, int(part)),
        "order": 0,
        "speaker": speaker.strip() or "Unknown",
        "type": kind if kind in VALID_TYPES else "dialogue",
        "text": text.strip(),
        "direction": direction.strip(),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "voice": "",
        "speed": None,
        "status": "draft",
        "audio": "",
        "source": source or {},
    }


class NarrationProject:
    def __init__(self, folder: Path, data: dict[str, Any]):
        self.folder = folder.resolve()
        self.data = data
        self.normalize()

    @classmethod
    def create(cls, folder: Path, title: str) -> "NarrationProject":
        folder = folder.resolve()
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("sources", "audio", "exports"):
            (folder / name).mkdir(exist_ok=True)
        now = utc_now()
        data = {
            "version": 1,
            "title": title.strip() or folder.name,
            "created_at": now,
            "updated_at": now,
            "settings": {
                "default_voice": "af_sarah",
                "narrator_voice": "bm_george",
                "default_speed": 1.0,
                "language": "en-us",
                "gap_ms": 250,
            },
            "cast": {
                "Narrator": {"voice": "bm_george", "speed": 1.0, "aliases": [], "notes": ""}
            },
            "pronunciations": {},
            "sources": [],
            "lines": [],
        }
        project = cls(folder, data)
        project.save()
        return project

    @classmethod
    def load(cls, path: Path) -> "NarrationProject":
        path = path.resolve()
        project_file = path / PROJECT_FILE if path.is_dir() else path
        data = json.loads(project_file.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Project JSON root must be an object.")
        return cls(project_file.parent, data)

    def normalize(self) -> None:
        self.data.setdefault("version", 1)
        self.data.setdefault("title", self.folder.name)
        self.data.setdefault("settings", {})
        settings = self.data["settings"]
        settings.setdefault("default_voice", "af_sarah")
        settings.setdefault("narrator_voice", "bm_george")
        settings.setdefault("default_speed", 1.0)
        settings.setdefault("language", "en-us")
        settings.setdefault("gap_ms", 250)
        self.data.setdefault("cast", {})
        self.data["cast"].setdefault("Narrator", {"voice": settings["narrator_voice"], "speed": 1.0, "aliases": [], "notes": ""})
        self.data.setdefault("pronunciations", {})
        self.data.setdefault("sources", [])
        self.data.setdefault("lines", [])
        for index, line in enumerate(self.data["lines"]):
            line.setdefault("id", uuid.uuid4().hex[:12])
            line.setdefault("part", 1)
            line["order"] = index
            line.setdefault("speaker", "Unknown")
            line.setdefault("type", "dialogue")
            line.setdefault("text", "")
            line.setdefault("direction", "")
            line.setdefault("confidence", 0.5)
            line.setdefault("voice", "")
            line.setdefault("speed", None)
            line.setdefault("status", "draft")
            line.setdefault("audio", "")
            line.setdefault("source", {})

    @property
    def lines(self) -> list[dict[str, Any]]:
        return self.data["lines"]

    def save(self) -> Path:
        self.normalize()
        self.data["updated_at"] = utc_now()
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / PROJECT_FILE
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(target)
        return target

    def add_lines(self, lines: list[dict[str, Any]]) -> None:
        self.lines.extend(lines)
        self.normalize()
        self.rebuild_cast()

    def rebuild_cast(self) -> None:
        default_voice = self.data["settings"]["default_voice"]
        for line in self.lines:
            speaker = line.get("speaker", "Unknown").strip() or "Unknown"
            self.data["cast"].setdefault(speaker, {
                "voice": self.data["settings"]["narrator_voice"] if speaker == "Narrator" else default_voice,
                "speed": 1.0,
                "aliases": [],
                "notes": "",
            })

    def line_by_id(self, line_id: str) -> dict[str, Any]:
        for line in self.lines:
            if line["id"] == line_id:
                return line
        raise KeyError(f"No line with id {line_id!r}.")

    def effective_voice(self, line: dict[str, Any]) -> tuple[str, float]:
        cast = self.data["cast"].get(line.get("speaker"), {})
        voice = line.get("voice") or cast.get("voice") or self.data["settings"]["default_voice"]
        speed = line.get("speed")
        if speed is None:
            speed = cast.get("speed", self.data["settings"]["default_speed"])
        return str(voice), float(speed)

    def apply_pronunciations(self, text: str) -> str:
        for source, replacement in sorted(self.data["pronunciations"].items(), key=lambda item: len(item[0]), reverse=True):
            text = re.sub(rf"\b{re.escape(source)}\b", str(replacement), text, flags=re.IGNORECASE)
        return text
