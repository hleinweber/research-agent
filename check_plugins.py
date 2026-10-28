"""Loader integration and deterministic approval checks; no shell commands run."""
import json
import sys
from unittest.mock import patch
from pathlib import Path
from plugins import Plugins
from api import initial_messages, complete
from agent import agent_turn
sys.stdout.reconfigure(encoding="utf-8")

def reply(name,args):
    return {"role":"assistant","content":None,"tool_calls":[{"id":"test-call","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}

def verify_loop(plugins):
    for name,args in [("bash",{"command":"SHOULD NEVER RUN"}),("telegram__wait_for_messages",{"seconds":0})]:
        called=[]
        messages=initial_messages()
        with patch("agent.complete",side_effect=[reply(name,args),{"role":"assistant","content":"Declined."}]):
            agent_turn(messages,run_tool=lambda cmd:{"output":"User declined","exit_code":None},plugins=plugins,approve_mcp=lambda *args:False,on_text=lambda text:None)
        result=json.loads(messages[2]["content"])
        assert "declined" in str(result).lower()
    with patch("agent.complete",side_effect=[reply("telegram__wait_for_messages",{}),{"role":"assistant","content":"Done"}]) as model:
        messages=initial_messages()
        agent_turn(messages,plugins=plugins,telegram_mode=True,on_text=lambda text:None)
        assert "telegram__wait_for_messages" not in [t["function"]["name"] for t in model.call_args_list[0].kwargs["tools"]]
        assert "Unknown tool" in messages[2]["content"]
    print("Denied tool and Telegram polling ownership checks passed",flush=True)

with Plugins() as plugins:
    plugins.announce()
    assert {"email__check_inbox", "email__read_message", "email__send_message"} <= set(plugins.routes)
    assert len(plugins.skills) >= 3
    verify_loop(plugins)
    paper=plugins.call("insight_literature__get_paper",{"doi":"10.1029/2020JE006505"})
    assert "Magnetic Variability" in paper["title"]
    print("Live loader DOI call passed",flush=True)
    messages=initial_messages()
    messages[0]["content"]+=plugins.skill_prompt()
    messages.append({"role":"user","content":"Say ready in one word. Do not call tools."})
    result=complete(messages,tools=plugins.tools,tool_choice="none")
    assert result.get("content")
    print("Model API with plugin context passed:",result["content"],flush=True)
print("Plugin sessions closed",flush=True)
