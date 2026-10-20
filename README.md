# Research agent

A small agent harness built by hleinweber for UCLA AI in Research, Week 2.
It talks to an OpenAI-compatible Chat Completions API, with a built-in tool named `bash` and tools discovered from MCP plugins.
The local web page shows the conversation, command approval buttons, command output and exit codes, and token usage for each API call.
The loop is written directly; the official MCP SDK supplies plugin transport.

## Install

Install Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Clone this repository and enter its folder. uv will obtain Python if needed.

```sh
git clone https://github.com/hleinweber/research-agent.git
cd research-agent
```

## Configure

On macOS or Linux:

```sh
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

Privately enter your API key in `.env`. Keep this file out of Git and chat.
The settings are `BASE_URL`, `API_KEY`, and `MODEL`:

```dotenv
BASE_URL=https://api.openai.com/v1
API_KEY=replace_with_your_key
MODEL=gpt-4.1-mini
```

Environment variables override `.env`. Other OpenAI-compatible providers work if the model supports tool calling.
API calls can incur charges from your provider.

## Run

```sh
uv run python web.py
```

Start the server in a separate terminal window so your original shell remains available. Keep the server running while using the page. Closing its terminal stops the server; the page then shows restart instructions and disables Send.

The browser opens automatically. Alternatively use `uv run python web.py --no-browser`
and open the printed link.
The server listens only on `127.0.0.1`, with a private browser session cookie separate from your API key. Reloading reconnects after a restart.
If research-agent is already running, launching it again reopens the existing page and returns your shell.
Use `--port 8766` if the default port, 8765, is occupied by another program.
On Windows you can launch from any folder with `& "$env:USERPROFILE\research-agent\start.ps1"`. Press Ctrl+C in the server terminal to stop.

Ask "What files are in this folder?" Review the command and choose Approve or Deny.
Every command needs approval; unanswered approval requests expire after ten minutes without running.
Commands run in the folder from which you launched the program, shown in the page.
On Windows the `bash` tool uses PowerShell; on macOS and Linux it uses bash.
Commands have a 60-second timeout, and only the last 10,000 output characters are returned.
Standard output and standard error are combined. Each result includes an exit code.

Input, cached input when reported, and output tokens appear in a numbered card for each API call. A latest-call summary stays visible above the message box.
Cached input is part of the input count. There is a limit of 20 tool rounds per question.
This is a single-user, single-conversation server: multiple tabs share the same conversation.
New conversation clears the model history. Conversations are kept in memory, not saved to disk.
Reset after an interrupted or failed API request if you want a fresh history.

A terminal interface is also available with `uv run python agent.py`; type `/quit` to exit.

## Understand the loop

1. `api.py` loads configuration and sends a Chat Completions request.
2. `agent.py` sends the full conversation and the built-in and discovered tool definitions.
3. When a model reply contains tool calls, each command waits for approval.
4. `shell_tool.py` runs an approved command and returns output plus its exit code.
5. The loop appends each result with its matching tool-call ID and calls the model again.
6. A reply without tool calls ends the turn and waits for the next user message.

`system_prompt.md` contains editable system instructions.
`web.py`, `index.html`, `app.js`, and `style.css` provide the local web interface.
`one_call.py` and `chat.py` preserve the earlier learning steps.

## Validation

Live OpenAI checks passed for plain text, tool calling, conversation history, and command denial.
Local checks passed for approval, denial without execution, matching tool-call IDs, reset,
failing commands, timeout, output truncation, and token-usage events.
Browser checks exercise the chat and approval interface with a predictable simulated model.

## Status

Week 2 submitted: [pull request #11](https://github.com/huangzesen/ai-in-research-homework/pull/11).

Week 3: both plugins and the harness loader/Telegram mode are implemented. Student-confirmed checks passed for web-to-phone sending, command approval and denial, two separately approved commands, conversation context explanation, old-message skipping after restart, and research replies with observed search/DOI tool calls. Unauthorized-chat filtering passed a simulated local check; no live second-account test has been done. Research covers seismology and magnetometer calibration. Citation metadata is verified through tools, but summaries still require scientific review.

Submission files are prepared in the isolated `C:/Users/hleinweber/ai-in-research-week3` worktree, branch `week-3-hleinweber`. Codex host validation passed: Telegram sending returned status sent (message ID 59), incoming polling responded successfully, and literature search, source listing and DOI lookup returned successfully. A fresh-message receive test in Codex was inconclusive after the Telegram tool became unavailable; earlier phone-mode tests remain documented above. Final SDK checks passed for all literature tools and invalid inputs; harness integration passed for discovery, denial, polling ownership and a model call (872 input tokens). The submission is prepared locally for publication; pushing the harness and submission branch and opening the Week 3 PR remain pending final approval.


Scientific accuracy follow-up: a phone test initially mixed findings from a shared Science editorial summary into individual papers. The tool now withholds suspected editorial text and marks findings unsupported; multi-region searches alternate crust/core results. Live checks returned the central 2021 crust and core papers first and withheld editorial text for all three Science DOIs. The student repeated the original question after restart: correct key citations and DOI links were returned, and unsupported findings for those papers were withheld. This verifies citation discovery and evidence handling, not a complete scientific synthesis: extra results still included indirect geological/modeling studies, and the blanket observation-method claim was too broad. Primary-source review remains necessary for findings, uncertainties and method attribution. No full-paper retrieval is implemented.

## Week 3 plugins and Telegram

Run `uv --system-certs run python agent.py` for terminal chat or `uv --system-certs run python web.py` for web chat. uv installs the official MCP SDK dependency. The loader starts each plugins/*/.mcp.json stdio server, adds its tools beside bash and adds skill names, descriptions and paths to the system prompt. Full skills are read through an approved bash call only when needed. Startup lists plugins, tools and skills; each API call reports token usage including the first input count.

The Telegram plugin requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in local .env. InSight literature needs no key. settings.json allow-lists Telegram send and the three read-only literature tools. Bash always requires approval; other MCP tools ask unless explicitly allowed.

Start phone mode in a separate terminal:

```powershell
cd C:\Users\hleinweber\research-agent
uv --system-certs run python agent.py --telegram
```

Keep the process running. Only one process may poll the bot at once; stop web/terminal/plugin tests before starting phone mode. For commands, use Telegram Reply on the approval message and send yes or no. Only yes on the matching prompt approves; anything else declines, and unanswered prompts expire after ten minutes. Replies to old prompts are ignored. /new clears history. The harness owns incoming messages; the model cannot call wait_for_messages in this mode.

Only your private chat ID is accepted. Startup skips old messages. Keep .env out of Git and chat; revoke leaked bot tokens with BotFather /revoke. Bot chats are not end-to-end encrypted. Review each command; do not send secrets.

Tool calls print names and return status in the terminal without arguments or result bodies. Literature instructions require search, DOI verification, exact metadata and checking the observation method. This is model guidance, not programmatic citation enforcement. Scientific summaries need review, especially shared editorial abstracts that describe several companion papers.
