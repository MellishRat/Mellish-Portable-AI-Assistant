from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .analyzer import analyze_comic_image, analyze_text
from .exporters import export_dialogue, export_srt
from .project import NarrationProject
from .tts import KOKORO_VOICES, TTSEngine, combine_part


mcp = MCPServer(
    name="mellish-narration-studio",
    title="Mellish Narration Studio",
    description="Create, review, voice and export local narration projects.",
    version="0.4.0",
)
tts = TTSEngine()


def project_at(project_path: str) -> NarrationProject:
    path = Path(project_path).expanduser().resolve()
    if not path.is_absolute():
        raise ValueError("project_path must be absolute.")
    return NarrationProject.load(path)


@mcp.tool()
def create_narration_project(project_path: str, title: str) -> dict[str, Any]:
    """Create a narration project at an absolute folder path. Refuses a folder that already has project.json."""
    path = Path(project_path).expanduser().resolve()
    if (path / "project.json").exists():
        raise FileExistsError(f"A narration project already exists at {path}")
    project = NarrationProject.create(path, title)
    return {"project_path": str(project.folder), "title": project.data["title"]}


@mcp.tool()
def get_narration_project(project_path: str) -> dict[str, Any]:
    """Inspect project title, cast, line counts, parts and generation status without changing it."""
    project = project_at(project_path)
    parts = sorted({int(line.get("part", 1)) for line in project.lines})
    return {"title": project.data["title"], "project_path": str(project.folder), "line_count": len(project.lines),
            "parts": parts, "cast": project.data["cast"],
            "status_counts": {status: sum(1 for line in project.lines if line.get("status") == status)
                              for status in sorted({line.get("status", "draft") for line in project.lines})}}


@mcp.tool()
def analyze_narration_text(project_path: str, text: str, part: int = 1, use_local_llm: bool = True) -> dict[str, Any]:
    """Identify narration/dialogue speakers in supplied text and append editable lines to a project."""
    if not text.strip():
        raise ValueError("text must not be empty.")
    project = project_at(project_path)
    lines = analyze_text(text, part=part, use_llm=use_local_llm, cast_context=list(project.data["cast"]))
    project.add_lines(lines)
    project.save()
    return {"added": len(lines), "line_ids": [line["id"] for line in lines], "cast": sorted(project.data["cast"])}


@mcp.tool()
def analyze_comic_page(project_path: str, image_path: str, page: int = 1) -> dict[str, Any]:
    """Analyse one absolute comic image using local vision, appending panel/bubble lines for review."""
    project = project_at(project_path)
    image = Path(image_path).expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(image)
    lines = analyze_comic_image(image, page=page)
    project.add_lines(lines)
    project.save()
    return {"added": len(lines), "line_ids": [line["id"] for line in lines]}


@mcp.tool()
def list_narration_lines(project_path: str, part: int | None = None, only_uncertain: bool = False) -> list[dict[str, Any]]:
    """List editable script lines, optionally by part or only confidence below 0.7/Unknown speaker."""
    project = project_at(project_path)
    lines = project.lines
    if part is not None:
        lines = [line for line in lines if int(line.get("part", 1)) == part]
    if only_uncertain:
        lines = [line for line in lines if float(line.get("confidence", 0)) < 0.7 or line.get("speaker") == "Unknown"]
    return lines[:2000]


@mcp.tool()
def update_narration_line(project_path: str, line_id: str, speaker: str | None = None,
                          text: str | None = None, line_type: str | None = None,
                          direction: str | None = None, part: int | None = None) -> dict[str, Any]:
    """Update selected fields of one line. Existing generated audio is marked changed for regeneration."""
    project = project_at(project_path)
    line = project.line_by_id(line_id)
    updates = {"speaker": speaker, "text": text, "type": line_type, "direction": direction, "part": part}
    for key, value in updates.items():
        if value is not None:
            line[key] = value
    line["status"] = "changed" if line.get("audio") else "draft"
    project.rebuild_cast()
    project.save()
    return line


@mcp.tool()
def assign_character_voice(project_path: str, character: str, voice: str, speed: float = 1.0,
                           aliases: list[str] | None = None, notes: str = "") -> dict[str, Any]:
    """Assign a bundled Kokoro voice and speed to a character. Voice must be in the advertised list."""
    if voice not in KOKORO_VOICES:
        raise ValueError(f"Unknown voice {voice!r}. Available: {', '.join(KOKORO_VOICES)}")
    if not 0.5 <= float(speed) <= 2.0:
        raise ValueError("speed must be between 0.5 and 2.0.")
    project = project_at(project_path)
    project.data["cast"][character] = {"voice": voice, "speed": float(speed), "aliases": aliases or [], "notes": notes}
    project.save()
    return {"character": character, **project.data["cast"][character]}


@mcp.tool()
def list_narration_voices() -> list[str]:
    """List Kokoro voice identifiers supported by the app."""
    return KOKORO_VOICES


@mcp.tool()
def generate_voice_lines(project_path: str, line_ids: list[str] | None = None, overwrite: bool = False) -> dict[str, Any]:
    """Generate WAV files locally for selected IDs or all lines. Existing audio is reused unless overwrite is true."""
    project = project_at(project_path)
    paths = tts.generate_lines(project, line_ids, overwrite=overwrite)
    return {"generated": len(paths), "files": [str(path) for path in paths]}


@mcp.tool()
def combine_narration_part(project_path: str, part: int) -> dict[str, Any]:
    """Combine generated line WAV files for one part into a single WAV with configured gaps."""
    project = project_at(project_path)
    path = combine_part(project, part)
    return {"part": part, "output": str(path), "bytes": path.stat().st_size}


@mcp.tool()
def export_narration_project(project_path: str) -> dict[str, Any]:
    """Export dialogue JSON/CSV for Unity/VRChat and SRT subtitles."""
    project = project_at(project_path)
    folder = project.folder / "exports" / "Unity"
    json_path, csv_path = export_dialogue(project, folder)
    srt_path = export_srt(project, project.folder / "exports" / "subtitles.srt")
    return {"json": str(json_path), "csv": str(csv_path), "srt": str(srt_path)}


def self_test():
    assert "af_sarah" in KOKORO_VOICES
    assert mcp is not None
    print(f"NARRATION_MCP_SELF_TEST_OK python={sys.executable} tools=11")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        mcp.run(transport="stdio")
