"""Non-destructive diagnostics for an installed portable assistant."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL_MANIFEST = ROOT / "config" / "install-manifest.json"
PORT = os.environ.get("MELLISH_OLLAMA_HOST", "127.0.0.1:11437")
URL = f"http://{PORT}"
results: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        results.append((name, True, str(fn() or "OK")))
    except Exception as exc:
        results.append((name, False, str(exc)))


def installed_config():
    if not INSTALL_MANIFEST.exists():
        raise RuntimeError("config/install-manifest.json is missing; run Repair or Add Models.bat")
    return json.loads(INSTALL_MANIFEST.read_text(encoding="utf-8-sig"))


def ollama_models():
    config = installed_config()
    with urllib.request.urlopen(URL + "/api/tags", timeout=4) as response:
        data = json.loads(response.read().decode("utf-8"))
    names = {item["name"].lower().removesuffix(":latest") for item in data.get("models", [])}
    required = [item["ollama"] for item in config.get("models", [])]
    missing = [name for name in required if name.lower().removesuffix(":latest") not in names]
    if missing:
        raise RuntimeError("Missing: " + ", ".join(missing))
    return f"{len(required)} selected models installed"


def gpu():
    completed = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    if completed.returncode:
        return "NVIDIA GPU unavailable; Ollama will use another supported backend or CPU"
    return completed.stdout.strip()


check("Portable Python", lambda: sys.executable)
check("Tkinter", lambda: __import__("tkinter").TkVersion)
check("Pillow", lambda: __import__("PIL").__version__)
check("NumPy", lambda: __import__("numpy").__version__)
check("Install manifest", lambda: f"version {installed_config().get('appVersion', 'unknown')}")
check("Ollama models", ollama_models)
check("GPU", gpu)

config = installed_config() if INSTALL_MANIFEST.exists() else {}
if config.get("voiceInstalled"):
    check("faster-whisper", lambda: __import__("faster_whisper").__file__)
    check("Kokoro", lambda: __import__("kokoro_onnx").__file__)
    check("Kokoro model", lambda: f"{(ROOT / 'voice/kokoro/kokoro-v1.0.onnx').stat().st_size / 1e6:.0f} MB")
    check("Whisper model", lambda: next((ROOT / "voice/whisper-models").rglob("model.bin")))

print("\nPortable Assistant diagnostics")
print("=" * 72)
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL':4}  {name:20} {detail}")
failed = sum(not ok for _, ok, _ in results)
print("=" * 72)
print(f"{len(results) - failed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
