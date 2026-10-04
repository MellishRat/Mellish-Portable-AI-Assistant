from __future__ import annotations

import json
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
APP_DIR = PACKAGE_DIR.parent


def assistant_root() -> Path:
    configured = os.environ.get("MELLISH_ASSISTANT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if APP_DIR.parent.name.lower() == "apps":
        return APP_DIR.parent.parent
    legacy = Path(r"W:\Qwen3.5-9B-abliterated")
    if legacy.is_dir():
        return legacy
    return APP_DIR


def kokoro_files() -> tuple[Path, Path]:
    root = assistant_root() / "voice" / "kokoro"
    return root / "kokoro-v1.0.onnx", root / "voices-v1.0.bin"


def cache_folder(name: str) -> Path:
    folder = assistant_root() / "cache" / "dyslexic-aid" / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def settings_file() -> Path:
    folder = assistant_root() / "config"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "dyslexic-aid.json"


def ollama_url() -> str:
    explicit = os.environ.get("MELLISH_OLLAMA_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    bind = os.environ.get("MELLISH_OLLAMA_HOST", "").strip() or os.environ.get("OLLAMA_HOST", "").strip()
    if bind:
        return (bind if "://" in bind else "http://" + bind).rstrip("/")
    manifest = assistant_root() / "config" / "install-manifest.json"
    if manifest.is_file():
        try:
            port = int(json.loads(manifest.read_text(encoding="utf-8-sig")).get("portablePort", 11437))
            return f"http://127.0.0.1:{port}"
        except Exception:
            pass
    return "http://127.0.0.1:11434"

