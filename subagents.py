"""Threaded subagents sharing the harness loop and MCP sessions, not conversations."""
import json
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from api import ROOT
from shell_tool import approve_command, kill_process, run_command


def tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}}


TOOLS = [
    tool("delegate", "Hand one task to a fresh subagent and wait for its report. It sees none of this conversation: provide all context and the required report.",
         {"agent": {"type": "string"}, "task": {"type": "string"}}, ["agent", "task"]),
    tool("subagent", "Control background subagents. start needs agent/task; send needs id/message; wait needs ids (timeout defaults to 60s, max 600); read needs id (last defaults to 5). stop kills its command permanently. Use start/wait for independent parallel work; include all context in tasks.",
         {"action": {"type": "string", "enum": ["start", "list", "send", "wait", "read", "stop"]},
          "agent": {"type": "string"}, "task": {"type": "string"}, "id": {"type": "string"},
          "message": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}},
          "timeout": {"type": "number", "minimum": 0, "maximum": 600},
          "last": {"type": "integer", "minimum": 1, "maximum": 100}}, ["action"]),
]


def load_types(folder, available):
    types = {}
    for path in sorted(Path(folder).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---") or len(text.split("---", 2)) != 3:
            raise ValueError(f"{path}: expected frontmatter")
        _, front, prompt = text.split("---", 2)
        fields = {}
        current = None
        for line in front.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.strip().startswith("- ") and current == "tools":
                fields["tools"] += "," + line.strip()[2:]
            elif ":" in line:
                current, value = line.split(":", 1)
                current = current.strip()
                fields[current] = value.strip().strip('"').strip("'")
            else:
                raise ValueError(f"{path}: unsupported frontmatter line")
        name = fields.get("name", path.stem)
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or name in types:
            raise ValueError(f"{path}: invalid or duplicate agent name")
        allowed = set(available) if "tools" not in fields else {
            x.strip().strip('"').strip("'") for x in fields["tools"].strip("[]").split(",") if x.strip()}
        for unknown in allowed - set(available) - {"delegate", "subagent"}:
            raise ValueError(f"{path}: unknown tool {unknown}")
        allowed -= {"delegate", "subagent"}
        turns = int(fields.get("max_turns", 20))
        if not 1 <= turns <= 1000 or not prompt.strip():
            raise ValueError(f"{path}: invalid max_turns or empty prompt")
        types[name] = {"description": fields.get("description", name), "tools": allowed,
                       "prompt": prompt.strip(), "max_turns": turns, "model": fields.get("model")}
    return types


@dataclass
class Worker:
    id: str
    agent: str
    task: str
    definition: dict
    path: Path
    messages: list
    state: str = "running"
    report: str = ""
    reason: str = ""
    turns: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.monotonic)
    inbox: deque = field(default_factory=deque)
    stop_event: threading.Event = field(default_factory=threading.Event)
    process: object = None
    thread: object = None
    events: list = field(default_factory=list)
    logged: int = 0


class Subagents:
    def __init__(self, plugins, folder=None, logs=None, time_limit=600):
        self.plugins = plugins
        self.types = load_types(folder or ROOT / "agents", {"bash", *plugins.routes})
        self.logs = Path(logs or ROOT / "logs" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]))
        self.time_limit = time_limit
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.approval_lock = threading.Lock()
        self.workers = {}
        self.notes = deque()
        self.closed = False
        self.approve_shell = approve_command
        self.approve_mcp = None
        self.on_usage = None
        self.on_notice = None
        self.total_tokens = 0
        self.disabled_tools = set()
        self.main_conversations = []
        self.audit_sequence = 0
        self.audit_lock = threading.RLock()
        self.session_id = uuid.uuid4().hex
        self.audit({"event": "session_started", "agent_types": sorted(self.types),
                    "time_limit": self.time_limit})

    def audit(self, event):
        """Append private session evidence, with a shared ordering across threads."""
        with self.audit_lock:
            self.audit_sequence += 1
            self.logs.mkdir(parents=True, exist_ok=True)
            now = time.time()
            record = {**event, "time": now, "sequence": self.audit_sequence,
                      "timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                      "session_id": self.session_id, "schema_version": 1}
            with (self.logs / "main.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def sync_main(self, messages):
        with self.lock:
            entry = next((e for e in self.main_conversations if e[0] is messages), None)
            if entry is None:
                entry = [messages, 0, f"main-{len(self.main_conversations)+1}"]
                self.main_conversations.append(entry)
            for index in range(entry[1], len(messages)):
                self.audit({"event": "message", "conversation": entry[2],
                            "message_index": index, "message": messages[index]})
                entry[1] = index + 1

    def prompt(self):
        return "\nAvailable subagent types (fresh conversations; provide complete tasks):\n" + "\n".join(
            f"{name}: {d['description']}" for name, d in self.types.items())

    def log(self, worker, event):
        record = {"time": time.time(), **event}
        with self.lock:
            worker.events.append(record)
            worker.path.parent.mkdir(parents=True, exist_ok=True)
            with worker.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.audit({"event": "worker_event", "worker_id": worker.id,
                        "agent": worker.agent, "record": record})

    def sync_log(self, worker):
        with self.lock:
            for message in worker.messages[worker.logged:]:
                self.log(worker, {"message": message})
                worker.logged += 1

    def check(self, worker):
        if worker.stop_event.is_set() or worker.state != "running":
            raise RuntimeError(worker.reason or "stopped")
        if time.monotonic() - worker.started >= self.time_limit:
            raise RuntimeError("time limit exceeded")

    def before_model(self, worker):
        with self.lock:
            self.check(worker)
            if worker.turns >= worker.definition["max_turns"]:
                raise RuntimeError("max_turns exceeded")
            if worker.inbox:
                worker.messages.append({"role": "user", "content": "\n".join(worker.inbox)})
                worker.inbox.clear()
            worker.turns += 1
            self.sync_log(worker)

    def usage(self, worker, counts):
        with self.lock:
            tokens = (counts.get("input") or 0) + (counts.get("output") or 0)
            worker.tokens += tokens
            self.total_tokens += tokens
            self.log(worker, {"usage": counts})
        if self.on_usage:
            self.on_usage(counts)
        else:
            print(f"[{worker.id}] Tokens: input={counts.get('input')}, output={counts.get('output')}", flush=True)

    def status(self, worker):
        return {"id": worker.id, "agent": worker.agent, "state": worker.state,
                "pid": worker.process.pid if worker.process else None,
                "command_running": bool(worker.process and worker.process.poll() is None),
                "turns": worker.turns, "tokens": worker.tokens,
                "seconds": round(time.monotonic() - worker.started, 2),
                "task": worker.task[:120], "report": worker.report[:4000] + ("\n[Truncated; full report is in the log.]" if len(worker.report) > 4000 else ""), "reason": worker.reason,
                "log": str(worker.path)}

    def finish(self, worker, state, reason=""):
        with self.changed:
            if worker.state != "running":
                return
            worker.state, worker.reason = state, reason
            self.sync_log(worker)
            self.log(worker, {"state": state, "reason": reason, "report": worker.report})
            note = f"{worker.id} ({worker.agent}) {state}: {reason or worker.report[:4000]}"
            self.notes.append(note)
            self.changed.notify_all()
        if self.on_notice:
            self.on_notice(note)

    def drain_notes(self):
        with self.lock:
            notes = list(self.notes)
            self.notes.clear()
            return notes

    def approve(self, worker, label, callback):
        while not self.approval_lock.acquire(timeout=0.1):
            self.check(worker)
        try:
            self.check(worker)
            self.log(worker, {"event": "approval_requested", "label": label})
            result = callback(label) if callback else False
            self.log(worker, {"event": "approval_decision", "approved": bool(result), "label": label})
            self.check(worker)
            return result
        finally:
            self.approval_lock.release()

    def shell(self, worker, command):
        label = f"[{worker.id} · {worker.agent}] {command}"
        if not self.approve(worker, label, self.approve_shell):
            return {"declined": True, "output": "User declined. Do not retry.", "exit_code": None}
        self.check(worker)
        def process_changed(process):
            with self.lock:
                worker.process = process
                if process and worker.stop_event.is_set():
                    kill_process(process)
        result = run_command(command, timeout=max(0.1, self.time_limit - (time.monotonic()-worker.started)),
                             stop_event=worker.stop_event, on_process=process_changed,
                             on_event=lambda event: self.log(worker, event))
        self.log(worker, {"event": "command_result", "result": result})
        self.check(worker)
        return result

    def run(self, worker):
        from agent import agent_turn
        manager = self
        class View:
            tools = [t for t in manager.plugins.tools if t["function"]["name"] in worker.definition["tools"] and t["function"]["name"] not in manager.disabled_tools]
            routes = {k: v for k, v in manager.plugins.routes.items() if k in worker.definition["tools"] and k not in manager.disabled_tools}
            allow = manager.plugins.allow & worker.definition["tools"]
            def call(self, name, args):
                manager.check(worker)
                result = manager.plugins.call(name, args)
                manager.check(worker)
                return result
        try:
            while True:
                agent_turn(worker.messages, run_tool=lambda command: self.shell(worker, command),
                           on_text=lambda text: None, on_usage=lambda counts: self.usage(worker, counts),
                           plugins=View(),
                           approve_mcp=lambda name, args: self.approve(worker, name, lambda label:
                               self.approve_mcp(f"[{worker.id} · {worker.agent}] {label}", args) if self.approve_mcp else False),
                           worker=worker, worker_manager=self)
                with self.lock:
                    self.check(worker)
                    self.sync_log(worker)
                    if worker.inbox:
                        continue
                    worker.report = str(worker.messages[-1].get("content") or "")
                    self.finish(worker, "idle")
                    break
        except Exception as error:
            self.finish(worker, "failed", str(error) if isinstance(error, RuntimeError) else type(error).__name__)

    def launch(self, worker):
        worker.thread = threading.Thread(target=self.run, args=(worker,), daemon=True)
        worker.thread.start()

    def capacity(self):
        if self.closed:
            raise ValueError("Subagent session is closed")
        if sum(w.state == "running" for w in self.workers.values()) >= 4:
            raise ValueError("4 subagents are running: wait for one or stop one")

    def start(self, agent, task):
        with self.lock:
            self.capacity()
            if agent not in self.types or not isinstance(task, str) or not task.strip():
                raise ValueError("Provide a known agent type and a nonempty task")
            key = f"sa-{len(self.workers)+1}"
            definition = self.types[agent]
            worker = Worker(key, agent, task, definition, self.logs / f"{key}.jsonl",
                            [{"role": "system", "content": definition["prompt"]}, {"role": "user", "content": task}])
            self.workers[key] = worker
            self.sync_log(worker)
            self.launch(worker)
            threading.Thread(target=self.watch, args=(worker,), daemon=True).start()
            return {"id": key}

    def watch(self, worker):
        if not worker.stop_event.wait(self.time_limit):
            with self.lock:
                if worker.state == "running":
                    self.finish(worker, "failed", "time limit exceeded")
                    worker.stop_event.set()
                    if worker.process:
                        kill_process(worker.process)

    def get(self, id):
        if id not in self.workers:
            raise ValueError("Unknown subagent id")
        return self.workers[id]

    def wait(self, ids, timeout=60):
        if not isinstance(ids, list) or not ids or not 0 <= timeout <= 600:
            raise ValueError("Provide ids and timeout between 0 and 600")
        deadline = time.monotonic() + timeout
        with self.changed:
            workers = [self.get(key) for key in ids]
            while any(w.state == "running" for w in workers):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.changed.wait(remaining)
            return [self.status(w) for w in workers]

    def call(self, name, args):
        if name == "delegate":
            key = self.start(args["agent"], args["task"])["id"]
            while True:
                result = self.wait([key], 60)[0]
                if result["state"] != "running":
                    return result
        action = args.get("action")
        if action == "start":
            return self.start(args["agent"], args["task"])
        if action == "wait":
            return self.wait(args["ids"], args.get("timeout", 60))
        with self.lock:
            if action == "list":
                return [self.status(w) for w in self.workers.values()]
            worker = self.get(args.get("id"))
            if action == "read":
                last = args.get("last", 5)
                if type(last) is not int or not 1 <= last <= 100:
                    raise ValueError("last must be 1-100")
                return {"id": worker.id, "steps": [json.dumps(e, ensure_ascii=False)[:500] for e in worker.events[-last:]]}
            if action == "send":
                if worker.state not in ("running", "idle"):
                    raise ValueError(f"Subagent is {worker.state}; start a new one")
                message = args.get("message")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("Provide a nonempty message")
                if worker.state == "idle":
                    self.capacity()
                    if time.monotonic()-worker.started >= self.time_limit:
                        raise ValueError("Subagent time limit expired; start a new one")
                    worker.state = "running"
                    worker.inbox.append(message)
                    self.launch(worker)
                else:
                    worker.inbox.append(message)
                return {"id": worker.id, "queued": True}
            if action == "stop":
                self.log(worker, {"event": "stop_requested", "pid": worker.process.pid if worker.process else None})
                worker.stop_event.set()
                if worker.process:
                    process = worker.process
                    kill_process(process)
                    process.wait()
                    self.log(worker, {"event": "process_termination_confirmed", "pid": process.pid,
                                      "exit_code": process.returncode})
                if worker.state == "running":
                    self.finish(worker, "stopped", "Stopped by user or main agent")
                elif worker.state == "idle":
                    worker.state = "running"
                    self.finish(worker, "stopped", "Stopped by user or main agent")
                return self.status(worker)
            raise ValueError("Unknown subagent action")

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for key in self.workers:
                self.call("subagent", {"action": "stop", "id": key})
            self.audit({"event": "session_closed", "worker_count": len(self.workers),
                        "worker_tokens": self.total_tokens})
