# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.28,<2"]
# ///
"""Send a live MCP test message without printing credentials."""
import asyncio
import os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    root = Path(__file__).resolve().parent
    env = dict(os.environ, UV_SYSTEM_CERTS="true")
    for line in (root / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip(chr(34)).strip(chr(39))
    params = StdioServerParameters(command="uv", args=["run", "--script", str(root / "plugins/hleinweber-telegram/server.py")], env=env)
    async with asyncio.timeout(40):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("MCP tools:", ", ".join(t.name for t in (await session.list_tools()).tools), flush=True)
                result = await session.call_tool("send_message", {"text":"Hello from your research-agent Telegram plugin! The MCP connection works."})
                print("Send test:", "FAILED" if result.isError else "PASSED", flush=True)
                for item in result.content:
                    if hasattr(item, "text"):
                        print(item.text, flush=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print("MCP connection test failed:", type(error).__name__)
        raise SystemExit(1)
