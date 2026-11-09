"""Talks to the MCP server over stdio like Claude Code does: lists tools, submits a tiny job, waits, reads the result.
Uses the RUNNING broker (default port) unless AIBROKER_PORT/AIBROKER_HOME are set.   .venv\\Scripts\\python.exe tests\\test_mcp.py"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "aibroker.mcp_server"], cwd=ROOT, env=dict(os.environ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("TOOLS:", ", ".join(t.name for t in tools.tools))
            res = await s.call_tool("submit_job", {"job_type": "custom", "name": "mcp test", "command": [sys.executable, "-c", "print('hello from mcp job')"], "est_ram_gb": 0.2})
            data = res.structured_content or json.loads(res.content[0].text)
            print("SUBMIT:", data)
            jid = data["job_id"]
            res = await s.call_tool("wait_for_job", {"job_id": jid, "timeout_s": 60})
            print("WAIT:", res.structured_content or res.content[0].text)
            res = await s.call_tool("job_output", {"job_id": jid})
            print("OUTPUT:", (res.structured_content or {}).get("text"))


asyncio.run(main())
