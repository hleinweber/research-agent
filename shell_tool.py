"""The single tool: shell commands with approval, timeout, and output limits."""
import os
import subprocess
import tempfile
import time
from contextvars import ContextVar
from pathlib import Path

WINDOWS = os.name == "nt"
TIMEOUT = 60
OUTPUT_LIMIT = 10000
COMMAND_EVENTS = ContextVar("command_events", default=None)
TOOL = {"type": "function", "function": {
    "name": "bash",
    "description": "Run a shell command in the current working folder. " +
        ("This computer uses Windows PowerShell; write PowerShell commands." if WINDOWS else "Commands run through bash.") +
        " The user must approve each command. Commands time out after 60 seconds; long output is truncated.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                   "required": ["command"], "additionalProperties": False},
}}

def kill_process(process):
    if process.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


def run_command(command, cwd=None, timeout=TIMEOUT, stop_event=None, on_process=None, on_event=None):
    on_event = on_event or COMMAND_EVENTS.get()
    argv = (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
            if WINDOWS else ["bash", "-c", command])
    # Capture to disk so a verbose command cannot fill RAM.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(argv, cwd=cwd or Path.cwd(), stdout=output,
                                   stderr=subprocess.STDOUT,
                                   start_new_session=not WINDOWS,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0)
        timed_out = False
        cancelled = False
        deadline = time.monotonic() + timeout
        try:
            if on_process:
                on_process(process)
            if on_event:
                on_event({"event": "process_started", "pid": process.pid, "command": command})
            while process.poll() is None:
                cancelled = bool(stop_event and stop_event.is_set())
                timed_out = time.monotonic() >= deadline
                if cancelled or timed_out:
                    kill_process(process)
                    process.wait()
                    break
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                kill_process(process)
                process.wait()
            cancelled = cancelled or bool(stop_event and stop_event.is_set())
            if on_process:
                on_process(None)
            if on_event:
                on_event({"event": "process_exited", "pid": process.pid,
                          "exit_code": process.returncode, "timed_out": timed_out,
                          "cancelled": cancelled})
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size - OUTPUT_LIMIT * 4))
        text = output.read().decode("utf-8", errors="replace")
        truncated = size > OUTPUT_LIMIT * 4 or len(text) > OUTPUT_LIMIT
        text = text[-OUTPUT_LIMIT:]
    return {"output": text, "exit_code": process.returncode,
            "timed_out": timed_out, "cancelled": cancelled, "truncated": truncated}


def approve_command(command):
    print("\nRequested command:\n" + command)
    try:
        return input("Run this command? [y/N] ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False

def approve_and_run(command):
    audit = COMMAND_EVENTS.get()
    if audit:
        audit({"event": "approval_requested", "command": command})
    print("\nRequested command:\n" + command)
    try:
        approved = input("Run this command? [y/N] ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        approved = False
    if audit:
        audit({"event": "approval_decision", "approved": approved})
    if not approved:
        return {"output": "The user declined to run this command.", "exit_code": None}
    result = run_command(command)
    print(result["output"])
    print(f"Exit code: {result['exit_code']}; timed out: {result['timed_out']}; truncated: {result['truncated']}")
    return result
