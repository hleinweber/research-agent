"""Small synchronous bridge to long-lived MCP sessions on one async thread."""
import asyncio
import concurrent.futures
import json
import os
import re
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from api import ROOT, load_settings

class Plugins:
    def __init__(self):
        self.ready = concurrent.futures.Future()
        self.tools = []
        self.skills = []
        self.routes = {}
        self.names = []
        self.thread = threading.Thread(target=self._thread, daemon=True)

    def __enter__(self):
        self.thread.start()
        self.ready.result(timeout=120)
        from subagents import Subagents
        try:
            self.subagents = Subagents(self)
        except Exception:
            self.loop.call_soon_threadsafe(self.stop.set)
            self.thread.join(timeout=20)
            raise
        return self

    def _thread(self):
        try:
            asyncio.run(self._serve())
        except BaseException as error:
            if not self.ready.done(): self.ready.set_exception(RuntimeError("Plugin startup failed: " + type(error).__name__))

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self.loop = asyncio.get_running_loop()
        self.stop = asyncio.Event()
        env = dict(os.environ)
        env.update({k:v for k,v in load_settings().items() if k not in os.environ})
        # Never pass model credentials to plugin processes.
        for key in ("API_KEY", "BASE_URL", "MODEL"): env.pop(key, None)
        async with AsyncExitStack() as stack:
            for manifest in sorted((ROOT / "plugins").glob("*/.claude-plugin/plugin.json")):
                folder = manifest.parent.parent.resolve()
                metadata = json.loads(manifest.read_text())
                self.names.append(metadata["name"])
                def expand(value):
                    def substitute(match):
                        name = match.group(1)
                        if name == "CLAUDE_PLUGIN_ROOT": return str(folder)
                        if name not in env: raise ValueError("Missing plugin environment variable: " + name)
                        return env[name]
                    return re.sub(r"\$\{([^}]+)\}", substitute, value)
                config = json.loads((folder / ".mcp.json").read_text())
                for server, spec in config.get("mcpServers", {}).items():
                    # Give each server only its declared secrets plus basic process settings.
                    child_env = {k:v for k,v in os.environ.items() if k.upper() in {"PATH","SYSTEMROOT","WINDIR","TEMP","TMP","USERPROFILE","HOME","LOCALAPPDATA","APPDATA","UV_CACHE_DIR","UV_SYSTEM_CERTS","SSL_CERT_FILE","SSL_CERT_DIR"}}
                    child_env["UV_SYSTEM_CERTS"] = "true"
                    child_env["PYTHONIOENCODING"] = "utf-8"
                    child_env.update({k:expand(v) for k,v in spec.get("env",{}).items()})
                    params = StdioServerParameters(command=expand(spec["command"]), args=[expand(v) for v in spec.get("args",[])], env=child_env)
                    read,write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read,write))
                    await asyncio.wait_for(session.initialize(), 80)
                    for tool in (await session.list_tools()).tools:
                        name = server + "__" + tool.name
                        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",name) or name in self.routes:
                            raise ValueError("Invalid or duplicate MCP tool name")
                        self.routes[name] = (session,tool.name)
                        self.tools.append({"type":"function","function":{"name":name,"description":tool.description or "", "parameters":tool.inputSchema}})
                for skill in sorted((folder/"skills").glob("*/SKILL.md")):
                    text = skill.read_text(encoding="utf-8")
                    front = text.split("---",2)[1] if text.startswith("---") else ""
                    fields = dict(line.split(":",1) for line in front.splitlines() if ":" in line)
                    self.skills.append(f"{fields.get('name',skill.parent.name).strip()}: {fields.get('description','').strip()} ({skill})")
            settings = ROOT / "settings.json"
            self.allow = set(json.loads(settings.read_text()).get("allow",[])) if settings.exists() else set()
            self.ready.set_result(True)
            await self.stop.wait()

    def skill_prompt(self):
        return "\nAvailable plugin skills (read the full SKILL.md using bash before using a skill):\n" + "\n".join(self.skills)

    def announce(self):
        print("Plugins: " + ", ".join(self.names), flush=True)
        print("MCP tools: " + ", ".join(self.routes), flush=True)
        print("Skills: " + "; ".join(self.skills), flush=True)

    async def _call(self, name, arguments):
        session,tool = self.routes[name]
        result = await session.call_tool(tool,arguments)
        if result.isError:
            return {"error":"MCP tool failed", "content":[c.text for c in result.content if hasattr(c,"text")]}
        if result.structuredContent is not None:
            value = result.structuredContent
            return value.get("result",value) if isinstance(value,dict) else value
        texts = [c.text for c in result.content if hasattr(c,"text")]
        if len(texts)==1:
            try: return json.loads(texts[0])
            except ValueError: return texts[0]
        return texts

    def call(self, name, arguments):
        return asyncio.run_coroutine_threadsafe(self._call(name,arguments),self.loop).result(timeout=90)

    def __exit__(self, *args):
        if hasattr(self, "subagents"):
            self.subagents.close()
        self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(timeout=20)
