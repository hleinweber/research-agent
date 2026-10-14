"""Step 4: the agent loop, with one approved shell tool."""
import json
from api import complete, initial_messages
from shell_tool import TOOL, approve_and_run

MAX_TOOL_ROUNDS = 20

def agent_turn(messages, run_tool=approve_and_run, on_text=None, on_usage=None):
    for round_index in range(MAX_TOOL_ROUNDS + 1):
        # Send the entire history and the one available tool.
        reply = complete(messages, on_usage=on_usage, tools=[TOOL],
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
                command = arguments.get("command")
                if call["function"]["name"] != "bash" or not isinstance(command, str) or not command.strip():
                    raise ValueError("Expected a bash tool call with a nonempty command string.")
                if round_index == MAX_TOOL_ROUNDS:
                    result = {"output": "Tool round limit reached.", "exit_code": None}
                else:
                    result = run_tool(command)
            except (ValueError, TypeError, KeyError, OSError) as error:
                result = {"output": f"Tool error: {error}", "exit_code": None}
            # Match each result to the model's tool call, then call the model again.
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result)})
    print("Tool round limit reached. Send another message to continue.")

def main():
    messages = initial_messages()
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
            agent_turn(messages)
        except (RuntimeError, OSError, ValueError) as error:
            print(f"Request failed: {error}. Type /quit to exit or try another message.")

if __name__ == "__main__":
    main()
