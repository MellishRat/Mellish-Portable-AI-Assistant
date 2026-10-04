from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import soundfile as sf

from .paths import kokoro_files
from .project import NarrationProject, safe_slug


KOKORO_VOICES = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore", "af_nicole", "af_nova",
    "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]


class TTSEngine:
    def __init__(self):
        self._kokoro = None
        self._lock = threading.Lock()

    def _load(self):
        if self._kokoro is None:
            model, voices = kokoro_files()
            if not model.is_file() or not voices.is_file():
                raise FileNotFoundError(f"Kokoro model files are missing: {model} / {voices}")
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(str(model), str(voices))
        return self._kokoro

    @staticmethod
    def chunks(text: str, limit: int = 450) -> list[str]:
        sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
        result, current = [], ""
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > limit:
                result.append(current)
                current = ""
            if len(sentence) > limit:
                pieces = [sentence[index:index + limit] for index in range(0, len(sentence), limit)]
                if current:
                    result.append(current)
                    current = ""
                result.extend(pieces[:-1])
                current = pieces[-1]
            else:
                current = (current + " " + sentence).strip()
        if current:
            result.append(current)
        return result

    def synthesize(self, text: str, destination: Path, *, voice: str, speed: float, language: str = "en-us") -> Path:
        if not 0.5 <= float(speed) <= 2.0:
            raise ValueError("TTS speed must be between 0.5 and 2.0.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        arrays, sample_rate = [], None
        with self._lock:
            kokoro = self._load()
            for chunk in self.chunks(text):
                samples, rate = kokoro.create(chunk, voice=voice, speed=float(speed), lang=language)
                sample_rate = rate
                arrays.append(np.asarray(samples, dtype=np.float32))
        if not arrays or sample_rate is None:
            raise RuntimeError("Kokoro produced no audio.")
        combined = np.concatenate(arrays)
        temporary = destination.with_suffix(".wav.tmp")
        sf.write(str(temporary), combined, sample_rate, format="WAV", subtype="PCM_16")
        temporary.replace(destination)
        return destination

    def generate_lines(self, project: NarrationProject, line_ids: Iterable[str] | None = None, *, overwrite: bool = False,
                       progress: Callable[[int, int, dict], None] | None = None,
                       cancelled: Callable[[], bool] | None = None) -> list[Path]:
        selected = set(line_ids) if line_ids is not None else None
        lines = [line for line in project.lines if selected is None or line["id"] in selected]
        generated = []
        for index, line in enumerate(lines, 1):
            if cancelled and cancelled():
                break
            if line.get("type") == "sound_effect" or not line.get("text", "").strip():
                line["status"] = "skipped"
                continue
            part_folder = project.folder / "audio" / f"Part_{int(line.get('part', 1)):03d}"
            filename = f"{int(line.get('order', 0)) + 1:05d}_{safe_slug(line.get('speaker', 'unknown'), 'unknown')}_{line['id']}.wav"
            destination = part_folder / filename
            if destination.exists() and not overwrite:
                line["status"], line["audio"] = "generated", str(destination.relative_to(project.folder))
            else:
                voice, speed = project.effective_voice(line)
                text = project.apply_pronunciations(line["text"])
                self.synthesize(text, destination, voice=voice, speed=speed,
                                language=project.data["settings"].get("language", "en-us"))
                line["status"], line["audio"] = "generated", str(destination.relative_to(project.folder))
            generated.append(destination)
            if progress:
                progress(index, len(lines), line)
            project.save()
        return generated


def combine_part(project: NarrationProject, part: int, destination: Path | None = None) -> Path:
    matching = [line for line in project.lines if int(line.get("part", 1)) == int(part) and line.get("audio")]
    if not matching:
        raise ValueError(f"Part {part} has no generated lines.")
    arrays, rate = [], None
    gap_ms = int(project.data["settings"].get("gap_ms", 250))
    for line in matching:
        samples, current_rate = sf.read(str(project.folder / line["audio"]), dtype="float32", always_2d=False)
        if rate is None:
            rate = current_rate
        if current_rate != rate:
            raise ValueError("Generated lines have different sample rates and cannot be combined safely.")
        arrays.append(samples)
        arrays.append(np.zeros(int(rate * gap_ms / 1000), dtype=np.float32))
    destination = destination or project.folder / "exports" / f"Part_{int(part):03d}.wav"
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destination), np.concatenate(arrays), rate, format="WAV", subtype="PCM_16")
    return destination
