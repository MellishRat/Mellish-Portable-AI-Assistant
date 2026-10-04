from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import soundfile as sf

from .paths import kokoro_files

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
                raise FileNotFoundError(f"Kokoro files are missing: {model} / {voices}")
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(str(model), str(voices))
        return self._kokoro

    def synthesize(self, text: str, destination: Path, *, voice: str, speed: float) -> Path:
        if not 0.5 <= float(speed) <= 2.0:
            raise ValueError("TTS speed must be between 0.5 and 2.0.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            samples, rate = self._load().create(text, voice=voice, speed=float(speed), lang="en-us")
        audio = np.asarray(samples, dtype=np.float32)
        if not audio.size:
            raise RuntimeError("Kokoro produced no audio.")
        temporary = destination.with_suffix(".wav.tmp")
        sf.write(str(temporary), audio, rate, format="WAV", subtype="PCM_16")
        temporary.replace(destination)
        return destination

