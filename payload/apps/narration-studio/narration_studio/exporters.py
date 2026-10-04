from __future__ import annotations

import csv
import json
from pathlib import Path

import soundfile as sf

from .project import NarrationProject


def export_dialogue(project: NarrationProject, destination: Path) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    for line in project.lines:
        duration = 0.0
        if line.get("audio"):
            audio_path = project.folder / line["audio"]
            if audio_path.is_file():
                duration = float(sf.info(str(audio_path)).duration)
        rows.append({
            "id": line["id"], "part": line.get("part", 1), "order": line.get("order", 0),
            "speaker": line.get("speaker", "Unknown"), "type": line.get("type", "dialogue"),
            "text": line.get("text", ""), "direction": line.get("direction", ""),
            "audio": line.get("audio", ""), "duration_seconds": round(duration, 3),
        })
    json_path = destination / "dialogue.json"
    csv_path = destination / "dialogue.csv"
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["id", "text"])
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def export_srt(project: NarrationProject, destination: Path) -> Path:
    def stamp(seconds: float) -> str:
        milliseconds = int(round(seconds * 1000))
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        secs, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    cursor, blocks = 0.0, []
    gap = int(project.data["settings"].get("gap_ms", 250)) / 1000
    for line in project.lines:
        if not line.get("audio"):
            continue
        info = sf.info(str(project.folder / line["audio"]))
        end = cursor + info.duration
        blocks.append(f"{len(blocks) + 1}\n{stamp(cursor)} --> {stamp(end)}\n{line.get('speaker', 'Unknown')}: {line.get('text', '')}\n")
        cursor = end + gap
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(blocks), encoding="utf-8")
    return destination
