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

Week 4 in progress: email sending uses port 587 with verified STARTTLS; self-addressed delivery, user-confirmed arrival, read-back, and harness MCP/approval checks passed. The class hello was sent to lingtai2026@gmail.com on October 27, 2026; its reply dated October 27 at 20:40:28 America/Los_Angeles was retrieved and read back to the student on October 28, confirming receipt. The harness includes delegate and background lifecycle tools, four agent types, and fourteen passing deterministic checks. Five reviewed rerun transcripts are saved in [transcripts/](transcripts/README.md), with private inbox details removed. Persistent main/worker logs verify inbox delegation, context-preserving follow-up without new tools, approved process start and termination with PID evidence, and enforced three-turn failure. The corrected fan-out rerun used three background starts before waiting, with overlapping worker activity and a combined report. Scientific caveats distinguish search coverage, source types, missing evidence, and unsupported generalizations. The follow-up's lack of a retrieved magnetometer source is documented. Prepare the submission next.

Week 2 submitted: [pull request #11](https://github.com/huangzesen/ai-in-research-homework/pull/11).

Week 3: both plugins and the harness loader/Telegram mode are implemented. Student-confirmed checks passed for web-to-phone sending, command approval and denial, two separately approved commands, conversation context explanation, old-message skipping after restart, and research replies with observed search/DOI tool calls. Unauthorized-chat filtering passed a simulated local check; no live second-account test has been done. Research covers seismology and magnetometer calibration. Citation metadata is verified through tools, but summaries still require scientific review.

Submission files are prepared in the isolated `C:/Users/hleinweber/ai-in-research-week3` worktree, branch `week-3-hleinweber`. Codex host validation passed: Telegram sending returned status sent (message ID 59), incoming polling responded successfully, and literature search, source listing and DOI lookup returned successfully. A fresh-message receive test in Codex was inconclusive after the Telegram tool became unavailable; earlier phone-mode tests remain documented above. Final SDK checks passed for all literature tools and invalid inputs; harness integration passed for discovery, denial, polling ownership and a model call (872 input tokens). The updated harness and submission branch are published. Week 3 submitted: [pull request #19](https://github.com/huangzesen/ai-in-research-homework/pull/19).


Scientific accuracy follow-up: a phone test initially mixed findings from a shared Science editorial summary into individual papers. The tool now withholds suspected editorial text and marks findings unsupported; multi-region searches alternate crust/core results. Live checks returned the central 2021 crust and core papers first and withheld editorial text for all three Science DOIs. The student repeated the original question after restart: correct key citations and DOI links were returned, and unsupported findings for those papers were withheld. This verifies citation discovery and evidence handling, not a complete scientific synthesis: extra results still included indirect geological/modeling studies, and the blanket observation-method claim was too broad. Primary-source review remains necessary for findings, uncertainties and method attribution. No full-paper retrieval is implemented.

## Subagents

The main loop exposes `delegate(agent, task)` for a blocking hand-off and `subagent(action, ...)` for background work. Actions are `start` (agent/task), `list`, `send` (id/message), `wait` (ids/timeout), `read` (id/last), and `stop` (id). Types come from `agents/*.md`; the main model sees their descriptions. Tasks must provide all needed context because workers begin with only their own system prompt and task. Use `/agents` in terminal, web, or Telegram chat for status.

Each worker runs the same `agent_turn` loop in a daemon thread, sharing the model client, MCP sessions, and working folder while keeping a private conversation and a strict tool allow list. The supplied mail-reader can only list/read mail; research-reader can only use literature tools. Workers never get delegation tools. Missing `tools` grants bash and all plugin tools, while `tools: []` grants none. Optional `model` and `max_turns` fields customize the type. Unknown tool names fail startup.

At most four workers run concurrently. Default limits are 20 model calls and 10 minutes from creation, including follow-ups. A completed worker is idle; `send` resumes its existing conversation. Failed or stopped workers cannot resume. Completion notes reach the interface immediately and the main conversation before its next model call. Token usage reaches the existing usage callback and is also tracked per worker and in the manager total.

Approvals are serialized and labeled with the worker ID and type. Shell commands run only after user approval. `stop` sets a cancellation event and kills the shell process tree using Windows taskkill or a POSIX process group. In-flight model/MCP requests may finish at their normal network timeout; their results cannot trigger further tools after stop. An approval already on screen may still need dismissal, but approval after stop cannot execute a command. Session shutdown and web/Telegram resets stop workers.

Private JSONL logs live in ignored `logs/<session>/<id>.jsonl`; each includes messages, tool results, usage, and states. Review/redact logs before sharing. Run `.venv/Scripts/python.exe -B check_subagents.py` on Windows (or `uv run python check_subagents.py`) for deterministic checks without model API calls or email sends. The assignment's five live demonstrations are a separate next step.

The session also writes `logs/<session>/main.jsonl` as events occur: the main conversation, tool-call arguments/results (including list/read/stop), model usage, web approval requests/decisions, and worker events. Records include timestamps and a session-wide sequence number. Worker logs record approval decisions, process start with PID, exit code and cancellation, stop requests, and confirmed process termination. `list` exposes `pid` and `command_running`. A stopped worker's process-exit event can follow its stopped-state event; match the PID rather than assuming the stopped event is the final log line. Files survive restarts but do not restore live agent state. Logging starts after loading the updated code; it cannot recover missing historical events. Logs include private conversations and tool output, so export only reviewed/redacted evidence for submission. Credentials and browser session cookies are not supplied to the logger.

## Running the plugins

Session audit records also include an explicit session ID, UTC timestamp, schema version, session start/close markers, and correlated tool start/finish/error events. Unexpected tool exceptions record their type and call ID without copying exception text into the error event. Session-close marks shutdown of the manager; an already in-flight request can still append its final event afterward. An absent close marker can indicate an interrupted session.

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
