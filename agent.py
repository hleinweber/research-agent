"""Step 4: the agent loop, with one approved shell tool."""
import json
from api import complete, initial_messages
from shell_tool import TOOL, approve_and_run

MAX_TOOL_ROUNDS = 20

def agent_turn(messages, run_tool=approve_and_run, on_text=None, on_usage=None, plugins=None, approve_mcp=None, telegram_mode=False):
    tools = [TOOL] + ([t for t in plugins.tools if not telegram_mode or t["function"]["name"] != "telegram__wait_for_messages"] if plugins else [])
    for round_index in range(MAX_TOOL_ROUNDS + 1):
        # Send the entire history and the one available tool.
        reply = complete(messages, on_usage=on_usage, tools=tools,
                         tool_choice="none" if round_index == MAX_TOOL_ROUNDS else "auto")
        messages.append(reply)
        if reply.get("content"):
            (on_text or (lambda text: print("Assistant:", text)))(reply["content"])
        calls = reply.get("tool_calls") or []
        if not calls:
            return
        for call in calls:
            try:
                arguments = json.loads(call["function"]["arguments"])
                name = call["function"]["name"]
                if not isinstance(arguments, dict): raise ValueError("Tool arguments must be an object.")
                # Never log arguments or results: they can contain private content.
                print("Tool requested: " + name, flush=True)
                if round_index == MAX_TOOL_ROUNDS:
                    result = {"output": "Tool round limit reached.", "exit_code": None}
                elif name == "bash":
                    command = arguments.get("command")
                    if not isinstance(command,str) or not command.strip(): raise ValueError("Expected a nonempty command.")
                    result = run_tool(command)
                elif plugins and name in plugins.routes and (not telegram_mode or name != "telegram__wait_for_messages"):
                    if name in plugins.allow or (approve_mcp and approve_mcp(name,arguments)):
                        print("Tool running: " + name, flush=True)
                        result = plugins.call(name,arguments)
                    else:
                        result = {"declined":True,"output":"User declined this tool. Do not retry or bypass the denial."}
                else:
                    raise ValueError("Unknown tool.")
            except (ValueError, TypeError, KeyError, OSError, TimeoutError) as error:
                result = {"output": f"Tool error: {error}", "exit_code": None}
            failed = isinstance(result, dict) and (result.get("error") or result.get("declined") or result.get("exit_code") not in (None, 0))
            print("Tool result: " + call["function"]["name"] + (" (error or declined)" if failed else " (returned; inspect result for details)"), flush=True)
            # Match each result to the model's tool call, then call the model again.
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result)})
    print("Tool round limit reached. Send another message to continue.")

def terminal(plugins):
    messages = initial_messages()
    messages[0]["content"] += plugins.skill_prompt()
    def approve(name, arguments):
        return input("Run " + name + " " + json.dumps(arguments) + "? [y/N] ").strip().lower() in {"y","yes"}
    print("Research agent. Commands require approval. Type /quit to exit.")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text == "/quit":
            return
        if not text:
            continue
        messages.append({"role": "user", "content": text})
        try:
            agent_turn(messages, plugins=plugins, approve_mcp=approve)
        except (RuntimeError, OSError, ValueError) as error:
            print(f"Request failed: {error}. Type /quit to exit or try another message.")

def main():
    import argparse
    from plugins import Plugins
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true")
    args = parser.parse_args()
    with Plugins() as plugins:
        plugins.announce()
        if args.telegram:
            from telegram_mode import run
            run(plugins)
        else:
            terminal(plugins)

if __name__ == "__main__":
    main()
