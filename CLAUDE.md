# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Counter is a Claude Code statusline script that displays:
- Token count with progress bar (against context window size)
- Cache status (read vs creation tokens from last API call)
- Session cost
- Lines added/removed

Single Python package, no external dependencies. Installable directly from git via `uvx` or `pipx`.

## Architecture

**`claude_counter/statusline.py`** — The statusline script. Reads JSON from stdin (provided by Claude Code), outputs ANSI-colored text to stdout. Entry point: `main()`.

**`claude_counter/__init__.py`** — Package init with version.

**`pyproject.toml`** — Package metadata. Console script entry point: `claude-counter` → `claude_counter.statusline:main`.

**`install.sh`** — Convenience script to add statusline config to `~/.claude/settings.json`.

## Install pattern

```json
{
  "statusLine": {
    "type": "command",
    "command": "uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter"
  }
}
```

## Version Bumping

Update both locations:
1. `pyproject.toml` — `version` field
2. `claude_counter/__init__.py` — `__version__`

## Testing

```bash
echo '{"context_window":{"total_input_tokens":15000,"total_output_tokens":4000,"context_window_size":200000,"used_percentage":8,"current_usage":{"cache_read_input_tokens":12000}},"cost":{"total_cost_usd":0.12,"total_lines_added":50,"total_lines_removed":10}}' | python3 -m claude_counter.statusline
```
