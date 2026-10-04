from __future__ import annotations

import json
import threading
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .core import output_root


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self) -> None:
        self.folder = output_root() / "jobs"
        self.folder.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mellish-mcp")
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()
        self._mark_interrupted()

    def _path(self, job_id: str) -> Path:
        return self.folder / f"{job_id}.json"

    def _write(self, data: dict[str, Any]) -> None:
        target = self._path(data["id"])
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(target)

    def _mark_interrupted(self) -> None:
        for path in self.folder.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if data.get("status") in {"queued", "running"}:
                    data.update(status="interrupted", finished_at=now(), error="MCP server stopped before completion.")
                    self._write(data)
            except Exception:
                continue

    def submit(self, kind: str, summary: str, function: Callable[[], Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        record = {"id": job_id, "kind": kind, "summary": summary[:300], "status": "queued",
                  "created_at": now(), "started_at": "", "finished_at": "", "result": None, "error": ""}
        self._write(record)

        def runner() -> None:
            current = self.get(job_id)
            current.update(status="running", started_at=now())
            self._write(current)
            try:
                current = self.get(job_id)
                current.update(status="completed", finished_at=now(), result=function())
            except Exception as exc:
                current = self.get(job_id)
                current.update(status="failed", finished_at=now(),
                               error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}")
            self._write(current)

        with self._lock:
            self._futures[job_id] = self._executor.submit(runner)
        return record

    def get(self, job_id: str) -> dict[str, Any]:
        path = self._path(job_id)
        if not path.is_file():
            raise KeyError(f"Unknown background job: {job_id}")
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        records = []
        for path in self.folder.glob("*.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8-sig")))
            except Exception:
                continue
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records[:max(1, min(int(limit), 200))]

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            future = self._futures.get(job_id)
        if future is None:
            return self.get(job_id)
        cancelled = future.cancel()
        data = self.get(job_id)
        if cancelled:
            data.update(status="cancelled", finished_at=now())
        elif data.get("status") == "running":
            data["cancel_note"] = "Already running; the backend cannot safely force-kill this operation."
        self._write(data)
        return data
