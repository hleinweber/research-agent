# Research agent

A small agent harness built by hleinweber for UCLA AI in Research, Week 2.
It talks to an OpenAI-compatible Chat Completions API, with exactly one tool named `bash`.
The local web page shows the conversation, command approval buttons, command output and exit codes, and token usage for each API call.
No agent frameworks or external Python packages are needed.

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

The browser opens automatically. Alternatively use `uv run python web.py --no-browser`
and open the full printed link, including the fragment after `#`.
The server listens only on `127.0.0.1`, with a browser session token separate from your API key.
Use `--port 8766` if the default port, 8765, is occupied. Press Ctrl+C in the server terminal to stop.

Ask "What files are in this folder?" Review the command and choose Approve or Deny.
Every command needs approval; unanswered approval requests expire after ten minutes without running.
Commands run in the folder from which you launched the program, shown in the page.
On Windows the `bash` tool uses PowerShell; on macOS and Linux it uses bash.
Commands have a 60-second timeout, and only the last 10,000 output characters are returned.
Standard output and standard error are combined. Each result includes an exit code.

Input, cached input when reported, and output tokens appear for each API call.
Cached input is part of the input count. There is a limit of 20 tool rounds per question.
This is a single-user, single-conversation server: multiple tabs share the same conversation.
New conversation clears the model history. Conversations are kept in memory, not saved to disk.
Reset after an interrupted or failed API request if you want a fresh history.

A terminal interface is also available with `uv run python agent.py`; type `/quit` to exit.

## Understand the loop

1. `api.py` loads configuration and sends a Chat Completions request.
2. `agent.py` sends the full conversation and the one tool definition.
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

The student explained the agent loop correctly and selected a local web page.
The web interface is implemented; awaiting the student's interface review.
Next: finish live interactive examples, review public files, get publishing approval,
publish the harness, test its install skill from a fresh clone, and submit the class pull request.
