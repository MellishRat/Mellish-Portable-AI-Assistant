from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .paths import OCR_MODEL, TEXT_MODEL, VISION_MODEL, assistant_root, ollama_url
from .project import new_line


SYSTEM_PROMPT = """You convert prose, scripts, and comic OCR into an audiobook production script.
Return only a JSON object with a `lines` array. Every line object must contain:
speaker, type, text, direction, confidence. type is dialogue, narration, thought,
caption, or sound_effect. Use Narrator for prose/captions. Preserve wording and
punctuation; do not rewrite, censor, summarize, or invent text. Use dialogue tags
and context to identify speakers. Use Unknown when genuinely ambiguous. Confidence
is a number from 0 to 1. Split long narration at natural paragraph boundaries.
"""


def _json_from_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("The language model did not return JSON.")
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict) or not isinstance(value.get("lines"), list):
        raise ValueError("The language model JSON has no lines array.")
    return value


def ollama_chat(model: str, messages: list[dict[str, Any]], *, timeout: int = 1800) -> str:
    ensure_ollama()
    model = resolve_model(model)
    options: dict[str, Any] = {"temperature": 0.1, "num_ctx": 8192}
    configured_gpu = os.environ.get("MELLISH_NARRATION_NUM_GPU", "").strip()
    if configured_gpu:
        options["num_gpu"] = int(configured_gpu)
    payload = {"model": model, "messages": messages, "stream": False, "format": "json", "options": options}

    def send() -> dict[str, Any]:
        request = urllib.request.Request(
            ollama_url() + "/api/chat", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        result = send()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        # A busy 12 GB card can fail to allocate the model even though system RAM
        # has ample room. Retry once on CPU unless the user explicitly chose GPU layers.
        lower_detail = detail.lower()
        memory_failure = any(marker in lower_detail for marker in ("out of memory", "out-of-memory", "failed to allocate"))
        if exc.code == 500 and memory_failure and not configured_gpu:
            payload["options"]["num_gpu"] = 0
            try:
                result = send()
            except urllib.error.HTTPError as retry_exc:
                retry_detail = retry_exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Ollama GPU load ran out of memory and the CPU fallback also failed for {model}: {retry_detail}"
                ) from retry_exc
        else:
            raise RuntimeError(f"Ollama returned HTTP {exc.code} for model {model}: {detail}") from exc
    return result.get("message", {}).get("content", "")


def ollama_models() -> list[str]:
    with urllib.request.urlopen(ollama_url() + "/api/tags", timeout=4) as response:
        result = json.loads(response.read().decode("utf-8"))
    return [str(item.get("name", "")) for item in result.get("models", []) if item.get("name")]


def ensure_ollama() -> None:
    try:
        ollama_models()
        return
    except Exception:
        pass
    executable = assistant_root() / "ollama" / "ollama.exe"
    if not executable.is_file():
        raise RuntimeError(f"Ollama is not running and its contained executable is missing: {executable}")
    bind = ollama_url().split("://", 1)[-1]
    environment = os.environ.copy()
    environment.update({
        "OLLAMA_MODELS": str(assistant_root() / "models"),
        "OLLAMA_HOST": bind,
        "MELLISH_OLLAMA_HOST": bind,
        "OLLAMA_KEEP_ALIVE": "-1",
    })
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([str(executable), "serve"], cwd=str(assistant_root()), env=environment,
                     creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.5)
        try:
            ollama_models()
            return
        except Exception:
            continue
    raise RuntimeError(f"Contained Ollama did not become ready at {ollama_url()}.")


def resolve_model(preferred: str) -> str:
    names = ollama_models()
    if preferred in names:
        return preferred
    # Text-only installations may use the low-spec model. Vision/OCR requests
    # deliberately do not fall back to a text model.
    if preferred == TEXT_MODEL:
        candidates = [
            "huihui_ai/qwen3-abliterated:1.7b",
            "hf.co/prism-ml/Bonsai-1.7B-gguf:Q1_0",
            "hf.co/mradermacher/Mistral-Nemo-Inst-2407-12B-Thinking-Uncensored-HERETIC-HI-Claude-Opus-GGUF:Q4_K_M",
            "dagbs/qwen2.5-coder-14b-instruct-abliterated:latest",
        ]
        for candidate in candidates:
            if candidate in names:
                return candidate
    raise RuntimeError(f"Required Ollama model is not installed: {preferred}. Installed models: {', '.join(names) or 'none'}")


def split_text(text: str, limit: int = 9000) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > limit:
            chunks.append(current)
            current = ""
        if len(paragraph) > limit:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            for sentence in sentences:
                if current and len(current) + len(sentence) + 1 > limit:
                    chunks.append(current)
                    current = ""
                current = (current + " " + sentence).strip()
        else:
            current = (current + "\n\n" + paragraph).strip()
    if current:
        chunks.append(current)
    return chunks


def heuristic_lines(text: str, part: int = 1) -> list[dict[str, Any]]:
    lines = []
    quote_pattern = re.compile(r"[“\"](.+?)[”\"]")
    for paragraph in [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]:
        position = 0
        for match in quote_pattern.finditer(paragraph):
            before = paragraph[position:match.start()].strip()
            if before:
                lines.append(new_line(before, part=part, kind="narration", confidence=0.6))
            nearby = paragraph[max(0, match.start() - 80):min(len(paragraph), match.end() + 100)]
            speaker_match = re.search(r"\b([A-Z][A-Za-z0-9_-]+)\s+(?:said|asked|replied|whispered|shouted|cried|murmured)", nearby)
            speaker = speaker_match.group(1) if speaker_match else "Unknown"
            lines.append(new_line(match.group(1), speaker=speaker, kind="dialogue", part=part,
                                  confidence=0.55 if speaker_match else 0.25))
            position = match.end()
        tail = paragraph[position:].strip()
        if tail:
            lines.append(new_line(tail, part=part, kind="narration", confidence=0.6))
    return lines


def analyze_text(text: str, *, part: int = 1, use_llm: bool = True, cast_context: list[str] | None = None) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    if not use_llm:
        return heuristic_lines(text, part)
    output: list[dict[str, Any]] = []
    context = ", ".join(cast_context or []) or "No established cast yet"
    for chunk_index, chunk in enumerate(split_text(text), 1):
        prompt = f"Established character names: {context}\nPart: {part}\nChunk: {chunk_index}\n\nSOURCE TEXT:\n{chunk}"
        parsed = _json_from_response(ollama_chat(TEXT_MODEL, [
            {"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}
        ]))
        for item in parsed["lines"]:
            if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                continue
            output.append(new_line(
                str(item["text"]), speaker=str(item.get("speaker", "Unknown")),
                kind=str(item.get("type", "dialogue")), part=part,
                direction=str(item.get("direction", "")), confidence=float(item.get("confidence", 0.5)),
                source={"chunk": chunk_index},
            ))
    return output


def analyze_comic_image(path: Path, *, page: int, use_ocr: bool = False) -> list[dict[str, Any]]:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    model = OCR_MODEL if use_ocr else VISION_MODEL
    prompt = SYSTEM_PROMPT + "\nAnalyse this comic page in likely panel/reading order. Put panel and bubble order in direction."
    content = ollama_chat(model, [{"role": "user", "content": prompt, "images": [encoded]}])
    parsed = _json_from_response(content)
    output = []
    for item in parsed["lines"]:
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            output.append(new_line(
                str(item["text"]), speaker=str(item.get("speaker", "Unknown")),
                kind=str(item.get("type", "dialogue")), part=page,
                direction=str(item.get("direction", "")), confidence=float(item.get("confidence", 0.5)),
                source={"image": path.name, "page": page},
            ))
    return output


def extract_image_text(path: Path) -> str:
    """Transcribe readable text from a screenshot or document image in reading order."""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    prompt = (
        "Transcribe every readable piece of text in this image in natural reading order. "
        "Preserve wording and line breaks where useful. Do not describe the image and do not "
        "invent missing text. Return only a JSON object with one string field named text."
    )
    errors = []
    for model in (OCR_MODEL, VISION_MODEL):
        try:
            content = ollama_chat(model, [{"role": "user", "content": prompt, "images": [encoded]}])
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)
            text = str(data.get("text", "")).strip() if isinstance(data, dict) else ""
            if text:
                return text
            raise ValueError("The OCR model returned no text.")
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    raise RuntimeError("Image text extraction failed. " + " | ".join(errors))
