"""Small Chat Completions client; secrets stay in .env."""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_settings():
    settings = {}
    for line in ((ROOT / ".env").read_text(encoding="utf-8-sig") if (ROOT / ".env").exists() else "").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            settings[name.strip()] = value.strip().strip(chr(34)).strip(chr(39))
    for name in ("BASE_URL", "API_KEY", "MODEL"):
        settings[name] = os.environ.get(name, settings.get(name, ""))
        if not settings[name] or settings[name] == "replace_with_your_key":
            raise ValueError(f"Set {name} in .env or your environment.")
    return settings

def complete(messages, on_usage=None, **options):
    settings = load_settings()
    payload = {"model": settings["MODEL"], "messages": messages, **options}
    request = urllib.request.Request(
        settings["BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + settings["API_KEY"],
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"API returned HTTP {error.code}; check credentials, model access, and billing.") from None
    usage = result.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", "not reported")
    counts = {"input": usage.get("prompt_tokens"), "cached": cached,
              "output": usage.get("completion_tokens")}
    if on_usage:
        on_usage(counts)
    else:
        print(f"Tokens: input={counts['input']}, cached={cached}, output={counts['output']}")
    return result["choices"][0]["message"]

def initial_messages():
    return [{"role": "system", "content": (ROOT / "system_prompt.md").read_text()}]
