"""The single tool: shell commands with approval, timeout, and output limits."""
import os
import subprocess
import tempfile
from pathlib import Path

WINDOWS = os.name == "nt"
TIMEOUT = 60
OUTPUT_LIMIT = 10000
TOOL = {"type": "function", "function": {
    "name": "bash",
    "description": "Run a shell command in the current working folder. " +
        ("This computer uses Windows PowerShell; write PowerShell commands." if WINDOWS else "Commands run through bash.") +
        " The user must approve each command. Commands time out after 60 seconds; long output is truncated.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                   "required": ["command"], "additionalProperties": False},
}}

def run_command(command, cwd=None, timeout=TIMEOUT):
    argv = (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
            if WINDOWS else ["bash", "-c", command])
    # Capture to disk so a verbose command cannot fill RAM.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(argv, cwd=cwd or Path.cwd(), stdout=output,
                                   stderr=subprocess.STDOUT,
                                   start_new_session=not WINDOWS)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if WINDOWS:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            if process.poll() is None:
                process.kill()
            process.wait()
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size - OUTPUT_LIMIT * 4))
        text = output.read().decode("utf-8", errors="replace")
        truncated = size > OUTPUT_LIMIT * 4 or len(text) > OUTPUT_LIMIT
        text = text[-OUTPUT_LIMIT:]
    return {"output": text, "exit_code": process.returncode,
            "timed_out": timed_out, "truncated": truncated}

def approve_and_run(command):
    print("\nRequested command:\n" + command)
    try:
        approved = input("Run this command? [y/N] ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        approved = False
    if not approved:
        return {"output": "The user declined to run this command.", "exit_code": None}
    result = run_command(command)
    print(result["output"])
    print(f"Exit code: {result['exit_code']}; timed out: {result['timed_out']}; truncated: {result['truncated']}")
    return result
