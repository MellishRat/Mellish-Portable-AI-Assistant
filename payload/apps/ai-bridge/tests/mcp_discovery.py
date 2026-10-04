from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        parameters = StdioServerParameters(command=sys.executable, args=[str(ROOT / "run_mcp.py")], cwd=str(ROOT),
                                           env={**os.environ, "MELLISH_ASSISTANT_ROOT": temporary})
        async with Client(parameters) as client:
            listing = await client.list_tools()
            names = {tool.name for tool in listing.tools}
            required = {"get_local_ai_status", "list_local_models", "ask_local_model", "review_code_text",
                        "audit_local_files", "submit_model_job", "list_background_jobs", "get_background_job",
                        "cancel_background_job", "list_local_voices", "generate_voice_line",
                        "submit_dialogue_pack", "unload_local_model"}
            assert names == required, (required - names, names - required)
            print(f"MELLISH_AI_BRIDGE_DISCOVERY_OK tools={len(names)}")


if __name__ == "__main__":
    asyncio.run(main())
