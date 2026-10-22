# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The MCP server: tool bodies (no SDK needed) and a stdio smoke test (needs ``mcp``)."""

import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from .. import mcp as server
from ..spec import dumps, example_path, load_example, to_data

HAS_MCP = importlib.util.find_spec("mcp") is not None
TOOL_NAMES = {
    "run_household",
    "validate_household",
    "compare_change",
    "explain_year",
    "reconcile_household",
    "get_schema",
    "list_examples",
}


class TestToolBodies(unittest.TestCase):
    def test_tool_set(self):
        self.assertEqual({tool.__name__ for tool in server.TOOLS}, TOOL_NAMES)

    def test_run_household_every_source(self):
        spec = load_example("married_homeowners")
        for kwargs in (
            {"example": "married_homeowners"},
            {"spec": to_data(spec)},
            {"spec": dumps(spec)},
            {"spec_path": str(example_path("married_homeowners"))},
        ):
            with self.subTest(source=next(iter(kwargs))):
                result = server.run_household(**kwargs, years=2, seed=1, yearly=False)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["summary"]["years"], [2026, 2027])
                self.assertNotIn("yearly", result["summary"])
                self.assertTrue(result["warnings"])  # events after the shortened end year

    def test_source_errors(self):
        for kwargs in ({}, {"example": "single_renter", "spec_path": "x.yaml"}, {"spec": "just-a-path.yaml"}):
            with self.subTest(kwargs=kwargs):
                result = server.run_household(**kwargs)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["kind"], "validation")
        missing = server.run_household(spec_path="does/not/exist.yaml")
        self.assertIn("No such spec file", missing["error"]["message"])

    def test_validation_and_runtime_errors(self):
        from .spec_helpers import not_yet_supported

        invalid = server.run_household(spec=not_yet_supported())
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["findings"][0]["code"], "not_yet_supported")
        with mock.patch("life_model.api.run", side_effect=RuntimeError("boom")):
            failed = server.run_household(example="single_renter")
        self.assertEqual(failed["error"]["kind"], "runtime")
        self.assertIn("boom", failed["error"]["message"])

    def test_validate_household(self):
        self.assertEqual(server.validate_household(example="married_homeowners")["valid"], True)
        from .spec_helpers import not_yet_supported

        result = server.validate_household(spec=not_yet_supported())
        self.assertTrue(result["ok"])
        self.assertFalse(result["valid"])
        self.assertEqual(server.validate_household(example="single_renter", scenario="x")["valid"], False)

    def test_compare_change(self):
        result = server.compare_change(
            example="married_homeowners",
            change={"people": {"jane": {"retirement_age": 50}}},
            sets=["meta.name=Changed"],
            years=10,
            seed=2,
        )
        self.assertTrue(result["ok"], result)
        self.assertLess(result["deltas"]["final_net_worth"], 0)
        self.assertEqual(result["changes"]["sets"], ["meta.name=Changed"])

    def test_explain_year(self):
        result = server.explain_year(2027, example="married_homeowners", seed=1)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["markdown"].startswith("# 2027"))
        self.assertFalse(server.explain_year(1990, example="married_homeowners")["ok"])

    def test_schema_and_examples(self):
        self.assertEqual(server.get_schema()["schema"]["title"], "HouseholdSpec")
        listing = server.list_examples(include_spec=True)
        self.assertIn("stochastic", listing["scenarios"])
        row = next(r for r in listing["examples"] if r["name"] == "single_renter")
        self.assertEqual(row["spec"], example_path("single_renter").read_text(encoding="utf-8"))
        self.assertNotIn("spec", server.list_examples()["examples"][0])

    def test_missing_sdk_is_reported(self):
        blocked = {"mcp": None, "mcp.server": None, "mcp.server.mcpserver": None, "mcp.server.fastmcp": None}
        with mock.patch.dict(sys.modules, blocked), self.assertRaises(ImportError) as caught:
            server.create_server()
        self.assertIn("life-model[mcp]", str(caught.exception))


class _StdioClient:
    """A minimal newline-delimited JSON-RPC client for an MCP stdio server (protocol level, so the
    test does not depend on the SDK's client API)."""

    def __init__(self, argv: list[str]):
        env = dict(os.environ)
        src = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [src, env.get("PYTHONPATH")]))
        self.process = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
        )
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message: dict) -> None:
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        self.process.stdin.flush()

    def request(self, request_id: int, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        self.send({"id": request_id, "method": method, **({"params": params} if params is not None else {})})
        while True:
            line = self.lines.get(timeout=timeout)
            if line is None:
                raise RuntimeError(f"server exited: {self.process.stderr.read()}")
            message = json.loads(line)
            if message.get("id") == request_id:
                return message

    def close(self) -> None:
        self.process.stdin.close()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a hung server
            self.process.kill()
        self.process.stdout.close()
        self.process.stderr.close()


@unittest.skipUnless(HAS_MCP, "the mcp extra is not installed (pip install 'life-model[mcp]')")
class TestStdioServer(unittest.TestCase):
    def test_initialize_list_and_call(self):
        client = _StdioClient([sys.executable, "-m", "life_model.mcp"])
        try:
            init = client.request(
                1,
                "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            )
            self.assertIn("tools", init["result"]["capabilities"])
            client.send({"method": "notifications/initialized"})
            tools = client.request(2, "tools/list")["result"]["tools"]
            self.assertEqual({tool["name"] for tool in tools}, TOOL_NAMES)
            call = client.request(
                3, "tools/call", {"name": "validate_household", "arguments": {"example": "married_homeowners"}}
            )
            self.assertFalse(call["result"].get("isError", False), call)
            payload = json.loads(call["result"]["content"][0]["text"])
            self.assertEqual(payload["valid"], True)
            call = client.request(
                4, "tools/call", {"name": "explain_year", "arguments": {"example": "married_homeowners", "year": 2027}}
            )
            payload = json.loads(call["result"]["content"][0]["text"])
            self.assertTrue(payload["markdown"].startswith("# 2027"))
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
