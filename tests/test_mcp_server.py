import sys
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "tkrs_mcp.py"


class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_and_search(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER)],
        )
        async with Client(params) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            self.assertIn("search_assets", names)
            self.assertIn("get_asset", names)
            self.assertIn("list_asset_categories", names)

            result = await client.call_tool(
                "search_assets",
                {"query": "industrial wall", "limit": 3},
            )
            self.assertFalse(result.is_error)
            payload = result.structured_content
            self.assertIsNotNone(payload)
            self.assertEqual(payload["catalog_asset_count"], 410)
            self.assertGreater(payload["result_count"], 0)

            asset_id = payload["results"][0]["id"]
            selected = await client.call_tool("get_asset", {"asset_id": asset_id})
            self.assertFalse(selected.is_error)
            self.assertTrue(selected.structured_content["found"])


if __name__ == "__main__":
    unittest.main()
