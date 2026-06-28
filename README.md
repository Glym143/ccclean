<div align="center">

# ccclean

**A surgical context cleaner for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions.**
Trim the oldest messages from a conversation to free up the context window — with a confirmation step and an optional summary of what gets removed.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
![Platform: macOS | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)

**English** · [Русский](README.ru.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [Deutsch](README.de.md)

</div>

---

It works directly on the `.jsonl` session files in `~/.claude/projects/`.

## Contents

- [Why ccclean](#why-ccclean)
- [Features](#features)
- [Installation](#installation)
  - [API keys](#api-keys)
- [Usage](#usage)
- [Automatic cleanup (the hook + `ccclaude`)](#automatic-cleanup-the-hook--ccclaude)
  - [Proactive mode (`clean_at`)](#proactive-mode-clean_at)
  - [Auto-continue (`resume_prompt`)](#auto-continue-resume_prompt)
  - [Hook safety](#hook-safety)
- [How it works](#how-it-works)
- [For AI agents](#for-ai-agents)
- [Caveats](#caveats)
- [License](#license)

---

## Why ccclean

Long Claude Code sessions fill up the context window, and work gets harder: the
model hits its limit, and auto-compact kicks in at the wrong moment and squashes
everything indiscriminately. `ccclean` gives you **precise control**: you decide
how many tokens to free and exactly which old chunk of the conversation to drop —
after seeing a short summary of it first. The current (recent) part of the
conversation stays untouched.

Unlike the built-in `/compact` (which compresses the *entire* dialog into a
summary), `ccclean` simply **cuts off the oldest beginning** of the active
branch, keeping the most recent messages verbatim.

---

## Features

- ✂️ **Precise trimming** — you specify an amount (`10k`, `50k`, `1.5m`) and the
  tool removes old messages from the start so that it frees **at least** the
  requested amount.
- 🔢 **Honest token counting** — by default through the official Anthropic
  `count_tokens` API (exact), or offline via `tiktoken` (`--fast`). It accounts
  for text, `thinking`, tool calls, and **images**.
- 📋 **Summary of what's removed (optional)** — with the `--summary` flag, before
  deleting anything it shows a short summary of the chunk (via DeepSeek) so you
  understand what you're losing. Off by default.
- 📊 **Real window usage** — shows the actual context size from the logs
  (`usage`), including the system prompt, tool schemas, MCP, and `CLAUDE.md`.
- 🗂 **Interactive session picker** — with no arguments it opens a list of
  conversations (via `fzf`, searchable by title), so you don't have to remember
  the id.
- 🔓 **Lifts the "context limit reached" block** — Claude Code determines the
  limit from the `usage` of the last response rather than recounting the trimmed
  messages. After a cut, ccclean lowers that counter by `usage_subtract`
  (default `200k`, a key in `config.json`) — noticeably below what was actually
  removed, so auto-compact doesn't fire before the first request after cleanup.
  The real context is still below the limit, so the server accepts the request,
  and Claude Code recounts the counter from the actual data.
- 💾 **Safety** — an automatic backup before every cut, an integrity check,
  protection against deleting the whole dialog, and correct re-stitching of the
  root.

---

## Installation

You need **Python 3.8+** and `pip`. Everything else (`tiktoken`, `anthropic`,
`fzf`) the tool installs itself on first run.

```bash
git clone https://github.com/Glym143/ccclean.git
cd ccclean
./install.sh
```

`install.sh`:

- makes `ccclean.py` executable;
- creates a `ccclean` symlink in the first writable directory on your `PATH`
  (`/opt/homebrew/bin`, `/usr/local/bin`, or `~/.local/bin`) — no sudo;
- creates the config `~/.config/ccclean/config.json` (mode `600`).

> If `~/.local/bin` is chosen but it isn't on your `PATH`, add this to
> `~/.zshrc` / `~/.bashrc`:
> `export PATH="$HOME/.local/bin:$PATH"`

### API keys

Put your keys in `~/.config/ccclean/config.json`:

```json
{
  "deepseek_api_key": "sk-...",
  "anthropic_api_key": "sk-ant-..."
}
```

- **`anthropic_api_key`** — exact token counting (the default mode).
  Get one at <https://console.anthropic.com/> → API Keys.
- **`deepseek_api_key`** — summaries of the removed chunk.
  Get one at <https://platform.deepseek.com/> → API Keys.

You can also set them via environment variables (which take priority):
`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`.

Without an Anthropic key it auto-falls back to offline `tiktoken` (approximate).
Without a DeepSeek key the summary is skipped.

---

## Usage

```bash
ccclean                       # pick a session from the list + free 50k (default)
ccclean 30k                   # pick a session + free 30k
ccclean <session-id>          # a specific session + free the default amount
ccclean <session-id> 30k      # a specific session + free 30k
ccclean <session-id> --keep 200k     # keep roughly the last 200k tokens
ccclean <session-id> 50k --dry-run   # show the plan, change nothing
ccclean <session-id> 100k --fast     # fast offline counting (tiktoken)
```

The amount is positional (`30k`, `50000`, `1.5m`) or a flag, `--free` / `--keep`
(the flag wins). Argument order doesn't matter. The `session-id` can be
abbreviated (as in the picker list). For the full list of flags: `ccclean -h`.

If no amount is given, it uses `default_free` from `~/.config/ccclean/config.json`
(installed as `50k`; the built-in fallback if there is no config is `10k`) —
change it there to set your default once and for all.

After cleanup, resume the session:

```bash
claude --resume <session-id>
```

---

## Automatic cleanup (the hook + `ccclaude`)

To avoid cleaning by hand, there's an automatic mode: when the context fills up
and Claude Code launches a compact, the hook intercepts it and, instead of lossy
compression, runs `ccclean`, after which the session restarts already unloaded.

`install.sh` sets this up for you:

- installs the wrapper command **`ccclaude`**;
- places the hook at `~/.claude/hooks/ccclean-hook.sh`;
- registers it in `~/.claude/settings.json` for the `PreCompact` event, but only
  for **auto**-compact (manual `/compact` is left alone — if you ran it
  yourself, then a compact is what you wanted);
- enables `autoCompactEnabled: true` (required for the hook to fire on its own);
- sets `autoCompactWindow: 1000000` — raising the auto-compact threshold close to
  the model's real ceiling (Claude Code computes the threshold as
  `window − ~33k`), so "context limit reached" doesn't fire prematurely.

> How it works inside Claude Code (from reversing the bundle): the block hits
> when the `usage` of the last response is ≥ `auto-compact-window −
> output_reserve(≤20k) − 13k`. So two levers help: raise the window
> (`autoCompactWindow`, done by install.sh) and lower the counter after cleanup
> (`usage_subtract`, done by ccclean).

**How to use it:** launch Claude Code through the wrapper (in a terminal):

```bash
ccclaude --resume <session-id>      # instead of `claude --resume <session-id>`
```

The cycle when it fills up:

1. Claude Code hits the limit → launches auto-compact.
2. The hook `ccclean-hook.sh` marks the session and ends `claude` (compact
   cancelled).
3. The `ccclaude` wrapper sees the mark → waits ~2s → `ccclean <id> --force` →
   restarts and immediately sends the prompt: `claude --resume <id> "continue"`.

The cut size per cycle is set (in priority order):

1. the `CCCLEAN_FREE` environment variable (one-off),
2. the `default_free` key in `~/.config/ccclean/config.json` (persistent),
3. the built-in fallback `10k`.

```bash
CCCLEAN_FREE=300k ccclaude --resume <id>   # one-off, unload an overflowing session
```

```json
// ~/.config/ccclean/config.json — change the default once and for all
{ "default_free": "30k" }
```

**Limitations:**

- Works **in a terminal**, not inside VS Code (the hook ends the `claude`
  process; VS Code has a different process model).
- If the session is right at the ceiling, a small cut (`10k`) may not get it out
  of the limit in a single cycle — increase `CCCLEAN_FREE` for a one-off unload.

### Proactive mode (`clean_at`)

So you never hit "context limit reached" at all, there's a second hook — on the
`Stop` event (after every response). It reads the current `usage` from the
transcript, and if it's above the **`clean_at`** threshold (a key in
`config.json`, e.g. `"940k"`), it runs the same cleanup cycle (kill → `ccclean` →
restart) ahead of time — while still under the limit. That way the block never
happens. The mode is enabled by the presence of `clean_at` in the config.

### Auto-continue (`resume_prompt`)

After the restart the wrapper doesn't just open the session — it **immediately
sends a prompt into it** so work continues without your involvement:

```bash
claude --resume <id> "continue"     # claude sends the prompt right at startup
```

The text is set by the **`resume_prompt`** key in `config.json` (default
`"continue"`):

```json
{ "resume_prompt": "continue from where you left off" }
```

An empty string (`""`) → just resume, with no auto-send.

### Hook safety

The `Stop` / `PreCompact` hooks **end the `claude` process**, so they only act in
sessions launched through the `ccclaude` wrapper (which sets `CCCLEAN_WRAPPED=1`).
In ordinary sessions (`claude`, VS Code) the hooks are a no-op and touch nothing.

---

## How it works

1. Finds the session file (by id or through the interactive picker).
2. Reconstructs the **active branch** of the dialog — the chain from the last
   message back along `parentUuid` to the root (this is exactly what gets loaded
   into context).
3. Counts tokens (Anthropic API — exact; `--fast` — tiktoken).
4. Finds the cut point for the requested amount, aligning it to a user-message
   boundary (it cuts no less than requested).
5. Asks for confirmation (and with `--summary`, a short summary of the removed
   chunk via DeepSeek).
6. Creates a backup `*.jsonl.bak-<date>`, deletes the old messages, re-stitches
   the root.
7. Verifies the integrity of the result.

---

## For AI agents

If an agent (rather than a human) runs this tool, keep in mind:

- **Non-interactive mode:** `-y` (no confirmations), `--fast` (no network,
  offline counting). The DeepSeek summary is OFF by default — enable it with
  `--summary`. You **must** specify the session with an explicit `session-id` —
  without it the interactive picker launches and hangs.
  ```bash
  ccclean <session-id> 50k --fast -y
  ```
- **Preview without changes:** `--dry-run` — prints the plan ("will free ≈ X",
  "will keep ≈ Y") and exits without touching anything. Handy for estimation.
- **Guarantee:** it actually trims **no less** than the requested amount; the
  "will free ≈" number in the output matches the real deletion exactly.
- **Active branch only:** the tool touches only the current linear chain of the
  dialog. The system prompt, tool schemas, MCP, and `CLAUDE.md` are part of the
  context but are **not** removed by trimming (they aren't in the `.jsonl`).
- **Safe by default:** a backup is always created (disable with `--no-backup`).
  To roll back, copy `*.jsonl.bak-*` over `*.jsonl`.
- ⚠️ **Run only when the target session is CLOSED:** an open Claude Code process
  will rewrite the file from memory and overwrite your changes. The tool checks
  this via `lsof` and will **refuse** to trim an open session (override with
  `--force`).

---

## Caveats

- **Run only when the session being cleaned is closed** (checked via `lsof`; the
  tool refuses to trim an open session, override with `--force`).
- A backup is created automatically next to the session file before every cut.
- Token counting via `tiktoken` (`--fast`) is approximate (it under-counts on
  Cyrillic); for exact numbers use the default mode (Anthropic API).

---

## License

[MIT](LICENSE) © [Glym143](https://github.com/Glym143)
