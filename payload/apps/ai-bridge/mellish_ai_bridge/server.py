from __future__ import annotations

import json
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from .core import (allowed_roots, ask_model, assistant_root, bridge_config, code_model, collect_files,
                   ensure_ollama, model_catalog, output_root, request_json, safe_name)
from .jobs import JobManager

mcp = MCPServer(name="mellish-ai-bridge", title="Mellish Local AI Bridge",
                description="Use contained local models, bounded audits, background jobs and offline voices.",
                version=__version__)
jobs = JobManager()


def _voice_engine():
    candidates = ((assistant_root() / "apps" / "narration-studio", "narration_studio.tts"),
                  (assistant_root() / "apps" / "dyslexic-aid", "dyslexic_aid.tts"))
    for folder, module in candidates:
        if folder.is_dir():
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            imported = __import__(module, fromlist=["TTSEngine", "KOKORO_VOICES"])
            return imported.TTSEngine(), list(imported.KOKORO_VOICES)
    raise RuntimeError("Install Narration Studio or Dyslexic Aid to enable Kokoro voice tools.")


def _make_voice_line(text: str, output_name: str, voice: str, speed: float) -> dict[str, Any]:
    engine, voices = _voice_engine()
    if voice not in voices:
        raise ValueError(f"Unknown voice {voice!r}. Available: {', '.join(voices)}")
    destination = output_root() / "audio" / f"{safe_name(output_name, 'voice-line')}.wav"
    path = engine.synthesize(text, destination, voice=voice, speed=float(speed))
    return {"output": str(path), "bytes": path.stat().st_size, "voice": voice, "speed": float(speed)}


def _make_dialogue_pack(pack_name: str, lines: list[dict[str, Any]], default_voice: str) -> dict[str, Any]:
    if not lines or len(lines) > 500:
        raise ValueError("Supply between 1 and 500 dialogue lines.")
    engine, voices = _voice_engine()
    pack = output_root() / "dialogue" / safe_name(pack_name, "dialogue-pack")
    audio = pack / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    manifest_lines = []
    for index, line in enumerate(lines, 1):
        text = str(line.get("text", "")).strip()
        if not text:
            continue
        voice = str(line.get("voice", default_voice))
        if voice not in voices:
            raise ValueError(f"Unknown voice {voice!r} on line {index}.")
        line_id = safe_name(str(line.get("id", f"line-{index:04d}")), f"line-{index:04d}")
        speaker, speed = str(line.get("speaker", "Narrator")), float(line.get("speed", 1.0))
        destination = audio / f"{index:04d}_{safe_name(speaker, 'speaker')}_{line_id}.wav"
        engine.synthesize(text, destination, voice=voice, speed=speed)
        manifest_lines.append({"id": line_id, "speaker": speaker, "text": text, "voice": voice, "speed": speed,
                               "event": str(line.get("event", "")),
                               "audio": str(destination.relative_to(pack)).replace("\\", "/")})
    manifest = {"version": 1, "name": pack_name, "line_count": len(manifest_lines), "lines": manifest_lines}
    manifest_path = pack / "dialogue.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"folder": str(pack), "manifest": str(manifest_path), "generated": len(manifest_lines)}


@mcp.tool()
def get_local_ai_status() -> dict[str, Any]:
    """Report installation, Ollama/models, allowed roots, outputs and persistent background-job counts."""
    try:
        models, ollama = model_catalog(), "ready"
    except Exception as exc:
        models, ollama = [], f"error: {exc}"
    recent = jobs.list(200)
    return {"version": __version__, "assistant_root": str(assistant_root()), "ollama": ollama,
            "installed_models": [item.get("name", "") for item in models],
            "allowed_roots": [str(path) for path in allowed_roots()], "output_root": str(output_root()),
            "jobs": {status: sum(1 for job in recent if job.get("status") == status)
                     for status in ("queued", "running", "completed", "failed", "interrupted")}}


@mcp.tool()
def list_local_models() -> list[dict[str, Any]]:
    """List locally installed Ollama models and sizes without loading or downloading them."""
    return [{"name": item.get("name", ""), "size": item.get("size", 0),
             "modified_at": item.get("modified_at", ""), "details": item.get("details", {})}
            for item in model_catalog()]


@mcp.tool()
def ask_local_model(prompt: str, model: str = "", system_prompt: str = "", temperature: float = 0.2,
                    context: int = 16384, unload_after: bool = False) -> dict[str, Any]:
    """Ask an installed local model for a second opinion, analysis or draft with token statistics."""
    return ask_model(prompt, model=model, system_prompt=system_prompt, temperature=temperature,
                     context=context, unload_after=unload_after)


@mcp.tool()
def review_code_text(code: str, filename: str = "snippet", focus: str = "correctness, risks and maintainability",
                     model: str = "") -> dict[str, Any]:
    """Review supplied code text locally. Use this when a file is outside configured allowed roots."""
    if len(code.encode("utf-8")) > int(bridge_config().get("max_audit_bytes", 300_000)):
        raise ValueError("Code input exceeds the configured audit byte limit.")
    prompt = (f"Act as an independent code reviewer. Review {filename!r}, focusing on {focus}. Identify concrete "
              f"bugs and risks first, cite relevant symbols/lines, then give concise fixes.\n\n--- {filename} ---\n{code}")
    return ask_model(prompt, model=model or code_model(),
                     system_prompt="You are a precise senior software reviewer.", temperature=0.15)


@mcp.tool()
def audit_local_files(paths: list[str], focus: str = "correctness, security and maintainability",
                      model: str = "") -> dict[str, Any]:
    """Audit bounded text files; every path must be under an allowed root in config/ai-bridge.json."""
    content, included = collect_files(paths)
    result = ask_model(f"Audit these files, focusing on {focus}. Report actionable findings in severity order, cite "
                       f"paths and lines, and state when no material issue exists.\n{content}", model=model or code_model(),
                       system_prompt="You are a precise senior code and security auditor.", temperature=0.1)
    result["files"] = included
    return result


@mcp.tool()
def submit_model_job(prompt: str, model: str = "", system_prompt: str = "", temperature: float = 0.2,
                     unload_after: bool = True) -> dict[str, Any]:
    """Run a slow local-model request in the background. Poll with get_background_job."""
    return jobs.submit("model", prompt, lambda: ask_model(prompt, model=model, system_prompt=system_prompt,
                                                           temperature=temperature, unload_after=unload_after))


@mcp.tool()
def list_background_jobs(limit: int = 50) -> list[dict[str, Any]]:
    """List persistent background-job records newest first."""
    return jobs.list(limit)


@mcp.tool()
def get_background_job(job_id: str) -> dict[str, Any]:
    """Return status, result or error for one background job."""
    return jobs.get(job_id)


@mcp.tool()
def cancel_background_job(job_id: str) -> dict[str, Any]:
    """Cancel a queued job. An operation already executing cannot be force-killed safely."""
    return jobs.cancel(job_id)


@mcp.tool()
def list_local_voices() -> list[str]:
    """List Kokoro voice identifiers for voice lines and dialogue packs."""
    return _voice_engine()[1]


@mcp.tool()
def generate_voice_line(text: str, output_name: str, voice: str = "af_sarah", speed: float = 1.0) -> dict[str, Any]:
    """Generate one offline WAV under mcp-output/audio and return its absolute path."""
    if not text.strip():
        raise ValueError("text must not be empty.")
    return _make_voice_line(text, output_name, voice, speed)


@mcp.tool()
def submit_dialogue_pack(pack_name: str, lines: list[dict[str, Any]], default_voice: str = "af_sarah") -> dict[str, Any]:
    """Generate a Unity-friendly folder of WAV files plus dialogue.json in a background job."""
    return jobs.submit("dialogue_pack", pack_name, lambda: _make_dialogue_pack(pack_name, lines, default_voice))


@mcp.tool()
def unload_local_model(model: str = "") -> dict[str, Any]:
    """Unload one local model from VRAM, or every loaded model when model is blank."""
    ensure_ollama()
    names = [str(item.get("name", "")) for item in request_json("/api/ps", timeout=10).get("models", [])]
    targets = [model] if model.strip() else names
    for name in targets:
        if name:
            request_json("/api/generate", {"model": name, "keep_alive": 0}, timeout=60)
    return {"unloaded": targets, "previously_loaded": names}


def self_test() -> None:
    assert assistant_root().is_absolute() and output_root().is_dir()
    print(f"MELLISH_AI_BRIDGE_SELF_TEST_OK tools=13 root={assistant_root()}")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        mcp.run(transport="stdio")
