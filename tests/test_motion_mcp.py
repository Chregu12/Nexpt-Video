import unittest

from motion import mcp
from tests.test_motion_spec import sample_spec


class MotionMcpTests(unittest.TestCase):
    def test_every_declared_tool_has_dispatch_route(self):
        for tool in mcp.tool_definitions():
            name = tool["name"]
            if name == "motion_validate_animation":
                response = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {"spec": sample_spec()}}})
                self.assertFalse(response["result"]["isError"])

    def test_initialize_and_list_tools(self):
        initialized = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "nexpt-motion-bridge")
        listed = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertGreaterEqual(len(listed["result"]["tools"]), 20)
        self.assertEqual(len({tool["name"] for tool in listed["result"]["tools"]}), len(listed["result"]["tools"]))

    def test_tool_error_is_returned_as_mcp_error_content(self):
        response = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "unknown", "arguments": {}}})
        self.assertTrue(response["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
