from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def merge(config_path: Path) -> None:
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("MCP configuration root must be an object.")
    else:
        data = {"version": 1, "servers": {}}
    servers = data.setdefault("servers", {})
    if not isinstance(servers, dict):
        raise ValueError("MCP configuration servers value must be an object.")
    existing = servers.get("narration-studio", {})
    entry = dict(existing) if isinstance(existing, dict) else {}
    entry.update({
        "enabled": True,
        "transport": "stdio",
        "command": "${ROOT}/runtime/python/python.exe",
        "args": ["${ROOT}/apps/narration-studio/run_mcp.py"],
        "env": {**(entry.get("env", {}) if isinstance(entry.get("env"), dict) else {}),
                "MELLISH_ASSISTANT_ROOT": "${ROOT}"},
    })
    servers["narration-studio"] = entry
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".narration.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, config_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    merge(args.config.resolve())
    print(f"NARRATION_MCP_CONFIG_MERGED={args.config.resolve()}")
