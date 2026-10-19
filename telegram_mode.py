"""The harness owns polling and command approval in Telegram mode."""
import json
import time
from collections import deque
from api import initial_messages
from agent import agent_turn
from shell_tool import run_command


def run(plugins):
    pending = deque()
    def send(text):
        result = plugins.call("telegram__send_message", {"text":text})
        if not isinstance(result,dict) or result.get("error"): raise RuntimeError("Telegram send failed")
        return result.get("message_ids",[])
    def poll(seconds=30):
        result=plugins.call("telegram__wait_for_messages",{"seconds":seconds})
        if isinstance(result,dict) and result.get("error"): raise RuntimeError("Telegram polling failed")
        return result if isinstance(result,list) else []
    def approve(label):
        # Drain messages already received before the approval prompt exists.
        pending.extend(poll(0))
        if len(label)>3000:
            send("Request is too long to review safely on the phone; denied.")
            return False
        ids=send("Run this command or tool?\n"+label+"\nUse Telegram Reply on THIS message and answer yes or no. Expires in 10 minutes.")
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            batch = poll()
            for index, message in enumerate(batch):
                if message.get("reply_to_message_id") in ids:
                    pending.extend(batch[index+1:])
                    decision=message["text"].strip().lower()=="yes"
                    send("Approved." if decision else "Declined.")
                    return decision
                pending.append(message)
        send("Approval expired; request was not run.")
        return False
    def shell(command):
        if not approve(command):
            return {"output":"User declined. Do not retry or bypass this denial.","exit_code":None}
        return run_command(command)
    def fresh():
        messages=initial_messages()
        messages[0]["content"] += plugins.skill_prompt()+"\nYou are talking through Telegram. Never read .env or send secrets. Do not bypass denied actions. The harness owns polling."
        return messages
    messages=fresh()
    send("Research agent ready. Ask a question. Commands require approval by replying to their prompt. /new resets the conversation.")
    try:
        while True:
            if not pending: pending.extend(poll())
            if not pending: continue
            message=pending.popleft()
            # Replies to old prompts cannot become fresh orders.
            if message.get("reply_to_message_id"): continue
            text=message["text"].strip()
            if text=="/new":
                messages=fresh()
                send("Started a new conversation.")
                continue
            messages.append({"role":"user","content":text})
            try:
                agent_turn(messages,run_tool=shell,on_text=send,plugins=plugins,
                           approve_mcp=lambda name,args:approve(name+"\n"+json.dumps(args)),telegram_mode=True)
            except Exception as error:
                send("Request failed ("+type(error).__name__+"). Retry or use /new.")
    except KeyboardInterrupt:
        print("Telegram mode stopped.")
