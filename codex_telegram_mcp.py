"""Launch the Telegram MCP server for Codex without copying secrets into config."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    env = dict(os.environ)
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            name = name.strip()
            if name in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}:
                env.setdefault(name, value.strip().strip(chr(34)).strip(chr(39)))
    env["UV_SYSTEM_CERTS"] = "true"
    return subprocess.call(["uv", "run", "--script", str(ROOT / "plugins/hleinweber-telegram/server.py")], env=env)

if __name__ == "__main__":
    raise SystemExit(main())
