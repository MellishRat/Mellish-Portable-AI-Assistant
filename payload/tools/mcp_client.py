"""Small portable MCP client adapter for stdio and Streamable HTTP servers."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "version": 1,
    "servers": {
        "unity": {
            "enabled": False,
            "transport": "stdio",
            "command": "${ROOT}/runtime/python/Scripts/unity-mcp-server.exe",
            "args": [],
            "env": {"UNITY_MCP_HOST": "127.0.0.1", "UNITY_MCP_PORT": "51279"},
            "notes": "The Python bridge is bundled. Install the Unity package and enable its server in the Editor."
        },
        "blender": {
            "enabled": False,
            "transport": "stdio",
            "command": "${BLENDER_MCP_COMMAND}",
            "args": [],
            "env": {},
            "notes": "Install a compatible Blender MCP add-on/server, then replace the command placeholder."
        },
        "gimp": {
            "enabled": False,
            "transport": "stdio",
            "command": "${PYTHON}",
            "args": ["${ROOT}/integrations/gimp-mcp/gimp_mcp_server.py"],
            "env": {},
            "notes": "Requires GIMP 3.2+, the GIMP plug-in, and a local checkout under integrations/gimp-mcp."
        }
    }
}


def _safe_public_name(server: str, tool: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{server}__{tool}")[:64]


class MCPClientAdapter:
    """Discovers and invokes MCP tools without depending on system PATH state."""

    def __init__(self, root: Path, config_path: Path):
        self.root = Path(root)
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        self.tool_map: dict[str, tuple[str, str]] = {}
        self.last_errors: dict[str, str] = {}

    def load_config(self) -> dict:
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        if not isinstance(data.get("servers", {}), dict):
            raise ValueError("mcp_servers.json must contain a 'servers' object")
        return data

    def enabled_servers(self) -> list[str]:
        return [
            name for name, config in self.load_config().get("servers", {}).items()
            if isinstance(config, dict) and config.get("enabled") is True
        ]

    def discover_tools(self) -> list[dict]:
        return asyncio.run(self._discover_tools())

    def call_tool(self, public_name: str, arguments: dict | None = None) -> str:
        return asyncio.run(self._call_tool(public_name, arguments or {}))

    def _expand(self, value: str) -> str:
        replacements = {
            "${ROOT}": str(self.root),
            "${PYTHON}": sys.executable,
        }
        result = str(value)
        for token, replacement in replacements.items():
            result = result.replace(token, replacement)
        result = os.path.expandvars(result)
        return result.replace("/", os.sep)

    def _source(self, config: dict):
        try:
            from mcp import Client, StdioServerParameters
        except ImportError as exc:
            raise RuntimeError(
                "The MCP client package is not installed. Run Repair or Add Models.bat to install core requirements."
            ) from exc
        transport = str(config.get("transport", "stdio")).lower()
        if transport in ("http", "streamable-http", "streamable_http"):
            url = str(config.get("url", "")).strip()
            if not url:
                raise ValueError("HTTP MCP server is missing its URL")
            return Client(url)
        command = self._expand(str(config.get("command", ""))).strip()
        if not command or command.startswith("${"):
            raise ValueError("MCP server command has not been configured")
        args = [self._expand(item) for item in config.get("args", [])]
        env = {str(key): self._expand(str(value)) for key, value in config.get("env", {}).items()}
        cwd = self._expand(str(config.get("cwd", ""))).strip() or None
        params = StdioServerParameters(command=command, args=args, env=env or None, cwd=cwd)
        return Client(params)

    async def _discover_tools(self) -> list[dict]:
        self.tool_map = {}
        self.last_errors = {}
        exposed = []
        for server_name, config in self.load_config().get("servers", {}).items():
            if not isinstance(config, dict) or not config.get("enabled"):
                continue
            try:
                client = self._source(config)
                async with client:
                    cursor = None
                    while True:
                        result = await client.list_tools(cursor=cursor)
                        for tool in result.tools:
                            public_name = _safe_public_name(server_name, tool.name)
                            self.tool_map[public_name] = (server_name, tool.name)
                            exposed.append({
                                "type": "function",
                                "function": {
                                    "name": public_name,
                                    "description": f"[{server_name}] {tool.description or tool.title or tool.name}",
                                    "parameters": tool.input_schema or {"type": "object", "properties": {}},
                                },
                            })
                        cursor = getattr(result, "next_cursor", None)
                        if not cursor:
                            break
            except Exception as exc:
                self.last_errors[server_name] = f"{type(exc).__name__}: {exc}"
        return exposed

    async def _call_tool(self, public_name: str, arguments: dict) -> str:
        if public_name not in self.tool_map:
            await self._discover_tools()
        if public_name not in self.tool_map:
            raise KeyError(f"Unknown MCP tool: {public_name}")
        server_name, tool_name = self.tool_map[public_name]
        config = self.load_config()["servers"][server_name]
        client = self._source(config)
        async with client:
            result = await client.call_tool(tool_name, arguments)
        pieces = []
        if getattr(result, "structured_content", None) is not None:
            pieces.append(json.dumps(result.structured_content, ensure_ascii=False, default=str))
        for block in getattr(result, "content", []) or []:
            if getattr(block, "type", "") == "text":
                pieces.append(str(getattr(block, "text", "")))
            elif getattr(block, "type", "") in ("image", "audio"):
                pieces.append(f"[{block.type} returned by {server_name}; binary data omitted from text context]")
            else:
                try:
                    pieces.append(json.dumps(block.model_dump(exclude_none=True), ensure_ascii=False, default=str))
                except Exception:
                    pieces.append(str(block))
        output = "\n".join(piece for piece in pieces if piece).strip() or "Tool completed without text output."
        if getattr(result, "is_error", False):
            output = "MCP tool reported an error:\n" + output
        return output[:100_000]
