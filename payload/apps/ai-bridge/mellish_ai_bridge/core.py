from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]


def assistant_root() -> Path:
    configured = os.environ.get("MELLISH_ASSISTANT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if APP_DIR.parent.name.lower() == "apps":
        return APP_DIR.parent.parent.resolve()
    return APP_DIR.resolve()


def bridge_config() -> dict[str, Any]:
    root = assistant_root()
    path = root / "config" / "ai-bridge.json"
    defaults: dict[str, Any] = {"allowed_roots": [str(root)], "max_files_per_audit": 20,
                                "max_audit_bytes": 300_000, "default_model": ""}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            defaults.update(loaded)
    return defaults


def ollama_url() -> str:
    explicit = os.environ.get("MELLISH_OLLAMA_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    manifest = assistant_root() / "config" / "install-manifest.json"
    port = 11437
    if manifest.is_file():
        try:
            port = int(json.loads(manifest.read_text(encoding="utf-8-sig")).get("portablePort", port))
        except Exception:
            pass
    return f"http://127.0.0.1:{port}"


def request_json(path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(ollama_url() + path, data=data,
                                     headers={"Content-Type": "application/json"} if data else {},
                                     method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_ollama() -> None:
    try:
        request_json("/api/tags", timeout=3)
        return
    except Exception:
        pass
    root = assistant_root()
    executable = root / "ollama" / "ollama.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Contained Ollama is missing: {executable}")
    bind = ollama_url().split("://", 1)[-1]
    environment = os.environ.copy()
    environment.update({"OLLAMA_MODELS": str(root / "models"), "OLLAMA_HOST": bind,
                        "MELLISH_OLLAMA_HOST": bind, "OLLAMA_KEEP_ALIVE": "-1"})
    subprocess.Popen([str(executable), "serve"], cwd=str(root), env=environment,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        try:
            request_json("/api/tags", timeout=3)
            return
        except Exception:
            continue
    raise RuntimeError(f"Contained Ollama did not start at {ollama_url()}.")


def model_catalog() -> list[dict[str, Any]]:
    ensure_ollama()
    return list(request_json("/api/tags", timeout=10).get("models", []))


def default_model() -> str:
    configured = str(bridge_config().get("default_model", "")).strip()
    names = [str(item.get("name", "")) for item in model_catalog()]
    if configured and configured in names:
        return configured
    for fragment in ("lukey03/qwen3.5-9b-abliterated:latest", "mistral-nemo", "qwen3.5"):
        match = next((name for name in names if fragment.lower() in name.lower()), None)
        if match:
            return match
    if not names:
        raise RuntimeError("No local Ollama models are installed.")
    return names[0]


def code_model() -> str:
    names = [str(item.get("name", "")) for item in model_catalog()]
    for fragment in ("qwen2.5-coder", "coder"):
        match = next((name for name in names if fragment in name.lower()), None)
        if match:
            return match
    return default_model()


def ask_model(prompt: str, *, model: str = "", system_prompt: str = "", temperature: float = 0.2,
              context: int = 16_384, unload_after: bool = False) -> dict[str, Any]:
    if not prompt.strip():
        raise ValueError("prompt must not be empty.")
    if not 0 <= float(temperature) <= 2:
        raise ValueError("temperature must be between 0 and 2.")
    ensure_ollama()
    chosen = model.strip() or default_model()
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt})
    response = request_json("/api/chat", {"model": chosen, "messages": messages, "stream": False,
                            "keep_alive": 0 if unload_after else -1,
                            "options": {"temperature": float(temperature), "num_ctx": int(context)}}, timeout=1800)
    message = response.get("message", {})
    content = str(message.get("content", "") or "").strip()
    thinking = str(message.get("thinking", "") or "").strip()
    return {"model": chosen, "response": content or thinking, "used_reasoning_fallback": bool(not content and thinking),
            "prompt_tokens": int(response.get("prompt_eval_count", 0) or 0),
            "output_tokens": int(response.get("eval_count", 0) or 0),
            "duration_seconds": round(float(response.get("total_duration", 0) or 0) / 1_000_000_000, 3)}


def allowed_roots() -> list[Path]:
    roots = []
    for value in bridge_config().get("allowed_roots", []):
        try:
            roots.append(Path(str(value)).expanduser().resolve())
        except Exception:
            continue
    return roots or [assistant_root()]


def safe_input_file(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if not any(path == root or root in path.parents for root in allowed_roots()):
        raise PermissionError(f"Path is outside configured allowed_roots: {path}")
    return path


def collect_files(paths: list[str]) -> tuple[str, list[str]]:
    config = bridge_config()
    maximum_files = int(config.get("max_files_per_audit", 20))
    maximum_bytes = int(config.get("max_audit_bytes", 300_000))
    if not paths or len(paths) > maximum_files:
        raise ValueError(f"Supply between 1 and {maximum_files} files.")
    chunks, included, used = [], [], 0
    for value in paths:
        path = safe_input_file(value)
        raw = path.read_bytes()
        if b"\x00" in raw[:4096]:
            raise ValueError(f"Binary files are not accepted: {path}")
        text = raw.decode("utf-8-sig", errors="replace")
        used += len(text.encode("utf-8"))
        if used > maximum_bytes:
            raise ValueError(f"Audit input exceeds {maximum_bytes} bytes.")
        included.append(str(path))
        chunks.append(f"\n--- FILE: {path} ---\n{text}")
    return "".join(chunks), included


def safe_name(value: str, fallback: str = "output") -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")[:100] or fallback


def output_root() -> Path:
    path = assistant_root() / "mcp-output"
    path.mkdir(parents=True, exist_ok=True)
    return path
