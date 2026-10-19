# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.28,<2"]
# ///
"""Exercise research tools through an actual MCP stdio session."""
import asyncio
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    server=Path(__file__).resolve().parent / "plugins/hleinweber-insight-literature/server.py"
    params=StdioServerParameters(command="uv",args=["run","--script",str(server)],env=dict(os.environ,UV_SYSTEM_CERTS="true"))
    async with asyncio.timeout(100):
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                names={t.name for t in (await session.list_tools()).tools}
                assert names == {"search_papers","get_paper","insight_reference_sources"}
                print("MCP discovery passed",flush=True)
                cases=[("search_papers",{"query":"InSight magnetic","limit":5}),
                       ("get_paper",{"doi":"https://doi.org/10.1029/2020JE006505"}),
                       ("insight_reference_sources",{})]
                for name,args in cases:
                    result=await session.call_tool(name,args)
                    assert not result.isError, name+" failed"
                    print(name+": PASSED",flush=True)
                    for item in result.content:
                        if hasattr(item,"text"): print(item.text,flush=True)
                for name,args in [("search_papers",{"query":"InSight","limit":50}),("get_paper",{"doi":"not-a-doi"})]:
                    result=await session.call_tool(name,args)
                    assert result.isError, "Invalid input should be rejected"
                print("Invalid-input checks passed",flush=True)

if __name__ == "__main__":
    asyncio.run(main())
