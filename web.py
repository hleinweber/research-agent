"""Local web chat. The agent loop stays in agent.py; this handles the interface."""
import argparse
import json
import secrets
import threading
import webbrowser
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from api import initial_messages, load_settings
from agent import agent_turn
from shell_tool import run_command

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
EVENTS = []
MESSAGES = initial_messages()
BUSY = False
PENDING = None

def emit(kind, **data):
    with LOCK:
        EVENTS.append({"kind": kind, **data})

def web_tool(command):
    global PENDING
    approval = {"id": secrets.token_hex(8), "command": command,
                "ready": threading.Event(), "approved": False}
    with LOCK:
        PENDING = approval
        emit("command", id=approval["id"], text=command)
    # No response is never interpreted as approval.
    answered = approval["ready"].wait(600)
    with LOCK:
        PENDING = None
    if answered and approval["approved"]:
        try:
            result = run_command(command)
        except OSError as error:
            result = {"output": f"Cannot start command: {error}", "exit_code": None}
    else:
        result = {"output": "The user declined to run this command." if answered
                  else "Approval expired; command was not run.", "exit_code": None}
    emit("result", id=approval["id"], **result)
    return result

def run_turn(text):
    global BUSY
    try:
        MESSAGES.append({"role": "user", "content": text})
        agent_turn(MESSAGES, run_tool=web_tool,
                   on_text=lambda reply: emit("assistant", text=reply),
                   on_usage=lambda counts: emit("usage", **counts))
    except Exception as error:
        # Avoid dumping request bodies, headers, or credentials into the browser.
        emit("error", text=f"Request failed ({type(error).__name__}). Check your connection, model access, and billing; retry or reset the conversation.")
    finally:
        with LOCK:
            BUSY = False
            emit("done")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, data, content_type="application/json"):
        body = json.dumps(data).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        if content_type == "text/html":
            self.send_header("Set-Cookie", f"research-agent-{self.server.server_port}={TOKEN}; HttpOnly; SameSite=Strict; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            self.respond(403, {"error": "Use the printed 127.0.0.1 address."})
            return False
        if self.headers.get("Origin") not in (None, "http://" + expected):
            self.respond(403, {"error": "Origin rejected."})
            return False
        return True

    def authenticated(self):
        if not self.allowed():
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        session = cookie.get(f"research-agent-{self.server.server_port}")
        cookie_token = session.value if session else ""
        if not (secrets.compare_digest(cookie_token, TOKEN) or
                secrets.compare_digest(self.headers.get("X-Session-Token", ""), TOKEN)):
            self.respond(403, {"error": "Reload this page to reconnect to the server."})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        parsed = urlparse(self.path)
        assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                  "/style.css": ("style.css", "text/css")}
        if parsed.path in assets:
            filename, content_type = assets[parsed.path]
            self.respond(200, (ROOT / filename).read_bytes(), content_type)
        elif parsed.path == "/health":
            self.respond(200, {"application": "research-agent"})
        elif parsed.path == "/events":
            if not self.authenticated():
                return
            try:
                start = int(parse_qs(parsed.query).get("after", ["0"])[0])
            except ValueError:
                self.respond(400, {"error": "Invalid event cursor."})
                return
            with LOCK:
                self.respond(200, {"events": EVENTS[max(0, start):], "cursor": len(EVENTS),
                                   "busy": BUSY, "folder": str(Path.cwd())})
        else:
            self.respond(404, {"error": "Not found."})

    def do_POST(self):
        global BUSY
        if not self.authenticated():
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 32768:
                raise ValueError()
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            self.respond(400, {"error": "Invalid request."})
            return
        with LOCK:
            if self.path == "/chat":
                text = data.get("text", "")
                if not isinstance(text, str) or not text.strip():
                    self.respond(400, {"error": "Enter a message."})
                elif BUSY:
                    self.respond(409, {"error": "Wait for the current reply."})
                else:
                    BUSY = True
                    emit("user", text=text.strip())
                    threading.Thread(target=run_turn, args=(text.strip(),), daemon=True).start()
                    self.respond(202, {"ok": True})
            elif self.path == "/approve":
                if not PENDING or data.get("id") != PENDING["id"] or PENDING["ready"].is_set():
                    self.respond(409, {"error": "This command is no longer pending."})
                elif type(data.get("approved")) is not bool:
                    self.respond(400, {"error": "Choose Approve or Deny."})
                else:
                    PENDING["approved"] = data["approved"]
                    PENDING["ready"].set()
                    emit("decision", id=PENDING["id"], approved=data["approved"])
                    self.respond(200, {"ok": True})
            elif self.path == "/reset":
                if BUSY:
                    self.respond(409, {"error": "Finish or deny the current command first."})
                else:
                    MESSAGES[:] = initial_messages()
                    emit("reset")
                    self.respond(200, {"ok": True})
            else:
                self.respond(404, {"error": "Not found."})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    load_settings()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        url = f"http://127.0.0.1:{args.port}/"
        try:
            with urllib.request.urlopen(url + "health", timeout=2) as response:
                existing = json.load(response).get("application") == "research-agent"
        except Exception:
            existing = False
        if existing:
            print("Research agent is already running. Open: " + url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return
        parser.exit(1, f"Cannot start on port {args.port}. Try --port 8766.\n")
    url = f"http://127.0.0.1:{server.server_port}/"
    print("Open this local chat link: " + url, flush=True)
    print("Working folder: " + str(Path.cwd()), flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
