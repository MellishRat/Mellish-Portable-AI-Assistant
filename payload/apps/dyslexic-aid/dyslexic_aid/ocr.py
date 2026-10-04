from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from .paths import assistant_root, ollama_url

OCR_MODEL = os.environ.get("MELLISH_DYSLEXIC_OCR_MODEL", "glm-ocr:latest")
VISION_MODEL = os.environ.get("MELLISH_DYSLEXIC_VISION_MODEL", "lukey03/qwen3.5-9b-abliterated-vision:latest")


def models() -> list[str]:
    with urllib.request.urlopen(ollama_url() + "/api/tags", timeout=4) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [str(item.get("name", "")) for item in data.get("models", []) if item.get("name")]


def ensure_ollama() -> None:
    try:
        models()
        return
    except Exception:
        pass
    executable = assistant_root() / "ollama" / "ollama.exe"
    if not executable.is_file():
        raise RuntimeError(f"Contained Ollama is missing: {executable}")
    bind = ollama_url().split("://", 1)[-1]
    environment = os.environ.copy()
    environment.update({"OLLAMA_MODELS": str(assistant_root() / "models"), "OLLAMA_HOST": bind,
                        "MELLISH_OLLAMA_HOST": bind, "OLLAMA_KEEP_ALIVE": "-1"})
    subprocess.Popen([str(executable), "serve"], cwd=str(assistant_root()), env=environment,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        try:
            models()
            return
        except Exception:
            continue
    raise RuntimeError(f"Contained Ollama did not start at {ollama_url()}.")


def extract_image_text(path: Path) -> str:
    ensure_ollama()
    installed = models()
    candidates = [model for model in (OCR_MODEL, VISION_MODEL) if model in installed]
    if not candidates:
        raise RuntimeError("No OCR-capable model is installed. Repair the installation and select Dyslexic Aid.")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    prompt = ("Transcribe every readable piece of text in this image in natural reading order. Preserve wording "
              "and useful line breaks. Do not describe the image. Return only JSON with one string field named text.")
    errors = []
    for model in candidates:
        payload = {"model": model, "messages": [{"role": "user", "content": prompt, "images": [encoded]}],
                   "stream": False, "format": "json", "options": {"temperature": 0.0, "num_ctx": 8192}}
        try:
            request = urllib.request.Request(ollama_url() + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                                             headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=1800) as response:
                content = json.loads(response.read().decode("utf-8")).get("message", {}).get("content", "")
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            result = json.loads(cleaned)
            text = str(result.get("text", "")).strip() if isinstance(result, dict) else ""
            if text:
                return text
            raise ValueError("The OCR model returned no text.")
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    raise RuntimeError("Image text extraction failed. " + " | ".join(errors))

