"""Download optional voice models into the selected portable installation."""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
WHISPER = ROOT / "voice" / "whisper-models"
KOKORO = ROOT / "voice" / "kokoro"

os.environ["HF_HOME"] = str(CACHE / "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = str(CACHE / "huggingface" / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(CACHE / "huggingface" / "transformers")
os.environ["XDG_CACHE_HOME"] = str(CACHE)

DOWNLOADS = {
    KOKORO / "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    KOKORO / "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def download(target: Path, url: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 10_000_000:
        print(f"Already present: {target.name}")
        return
    partial = target.with_suffix(target.suffix + ".partial")
    print(f"Downloading {target.name}...")
    urllib.request.urlretrieve(url, partial)
    partial.replace(target)


def main() -> None:
    for target, url in DOWNLOADS.items():
        download(target, url)
    print("Preparing faster-whisper small.en for CPU/int8...")
    WHISPER.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel
    WhisperModel("small.en", device="cpu", compute_type="int8", download_root=str(WHISPER))
    print("Voice models are ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
