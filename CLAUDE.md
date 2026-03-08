# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Counter is a Claude Code statusline script that displays:
- Current directory and model name
- Token count with progress bar (6 styles: text, bar, ball, capped, dots, filled)
- Cache status (read vs creation tokens)
- Session cost and 7-day rolling weekly cost
- Lines added/removed

Single Python package, no external dependencies. Installable directly from git via `uvx` or `pipx`.

## Architecture

**`claude_counter/statusline.py`** — The statusline script. Reads JSON from stdin, outputs ANSI-colored text. Entry point: `main()`. Accepts `--style` argument.

**`claude_counter/__init__.py`** — Package init with version.

**`pyproject.toml`** — Package metadata. Console script entry point: `claude-counter` → `claude_counter.statusline:main`.

**`install.sh`** — Convenience script to add statusline config to `~/.claude/settings.json`.

## State file

`~/.claude/.claude-counter-state.json` stores per-session costs grouped by date for weekly aggregation. Auto-prunes entries older than 7 days.

## Install pattern

```json
{
  "statusLine": {
    "type": "command",
    "command": "uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter --style=dots"
  }
}
```

## Bar styles (credit: Owloops/claude-powerline)

- `dots` (default): `●●●●○○○○○○`
- `bar`: `████░░░░░░`
- `ball`: `────●─────`
- `capped`: `━━━╸┄┄┄┄┄┄`
- `filled`: `■■■■□□□□□□`
- `text`: `~19.0k 40%` (no bar)

## Version Bumping

Update both locations:
1. `pyproject.toml` — `version` field
2. `claude_counter/__init__.py` — `__version__`

## Testing

```bash
echo '{"session_id":"test","cwd":"/tmp/myapp","model":{"display_name":"Opus"},"context_window":{"total_input_tokens":15000,"total_output_tokens":4000,"context_window_size":200000,"used_percentage":8,"current_usage":{"cache_read_input_tokens":12000}},"cost":{"total_cost_usd":0.12,"total_lines_added":50,"total_lines_removed":10}}' | python3 -m claude_counter.statusline --style=dots
```
