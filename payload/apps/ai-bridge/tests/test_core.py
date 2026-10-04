from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mellish_ai_bridge.core import bridge_config, collect_files
from mellish_ai_bridge.jobs import JobManager
from mellish_ai_bridge.merge_mcp import merge


class BridgeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous = os.environ.get("MELLISH_ASSISTANT_ROOT")
        os.environ["MELLISH_ASSISTANT_ROOT"] = str(self.root)
        (self.root / "config").mkdir()

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("MELLISH_ASSISTANT_ROOT", None)
        else:
            os.environ["MELLISH_ASSISTANT_ROOT"] = self.previous
        self.temporary.cleanup()

    def test_file_audit_stays_inside_allowed_root(self):
        allowed = self.root / "project"
        allowed.mkdir()
        source = allowed / "sample.py"
        source.write_text("print('safe')\n", encoding="utf-8")
        (self.root / "config" / "ai-bridge.json").write_text(
            json.dumps({"allowed_roots": [str(allowed)]}), encoding="utf-8"
        )
        content, included = collect_files([str(source)])
        self.assertIn("print('safe')", content)
        self.assertEqual(included, [str(source)])
        outside = self.root / "outside.py"
        outside.write_text("pass\n", encoding="utf-8")
        with self.assertRaises(PermissionError):
            collect_files([str(outside)])

    def test_mcp_merge_preserves_unrelated_servers(self):
        path = self.root / "config" / "mcp_servers.json"
        path.write_text(json.dumps({"version": 1, "servers": {"unity": {"enabled": False}}}), encoding="utf-8")
        merge(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("unity", data["servers"])
        self.assertIn("mellish-ai-bridge", data["servers"])

    def test_background_job_persists_result(self):
        manager = JobManager()
        record = manager.submit("test", "small test", lambda: {"answer": 42})
        for _ in range(50):
            current = manager.get(record["id"])
            if current["status"] == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(current["result"], {"answer": 42})


if __name__ == "__main__":
    unittest.main()
