from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "payload"))

from tools.chat_store import ChatStore
from tools.mcp_client import MCPClientAdapter


class ChatStoreTests(unittest.TestCase):
    def test_save_reload_rename_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ChatStore(Path(folder))
            record = store.new_record({"model": "test"})
            record["messages"] = [{"role": "user", "content": "Remember this conversation"}]
            store.save(record)
            self.assertEqual(store.list()[0]["title"], "Remember this conversation")
            self.assertEqual(store.load(record["id"])["messages"], record["messages"])
            store.rename(record["id"], "Renamed")
            self.assertEqual(store.list()[0]["title"], "Renamed")
            store.delete(record["id"])
            self.assertEqual(store.list(), [])

    def test_incomplete_index_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ChatStore(Path(folder))
            store.index_path.write_text("not-json", encoding="utf-8")
            self.assertEqual(store.list(), [])


class MCPAdapterTests(unittest.TestCase):
    def test_stdio_discovery_and_call(self):
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest("MCP SDK is not installed in this test interpreter")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            server = root / "server.py"
            server.write_text(
                "from mcp.server import MCPServer\n"
                "server = MCPServer('portable-test')\n"
                "@server.tool()\n"
                "def echo(text: str) -> str:\n"
                "    return 'echo:' + text\n"
                "server.run()\n",
                encoding="utf-8",
            )
            config = {
                "version": 1,
                "servers": {
                    "test": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": [str(server)],
                        "env": {"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
                    }
                },
            }
            path = root / "mcp_servers.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            adapter = MCPClientAdapter(root, path)
            tools = adapter.discover_tools()
            self.assertEqual(tools[0]["function"]["name"], "test__echo")
            self.assertIn("echo:hello", adapter.call_tool("test__echo", {"text": "hello"}))


if __name__ == "__main__":
    unittest.main()
