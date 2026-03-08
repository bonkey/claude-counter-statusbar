# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- **Always update README.md** when adding, removing, or changing CLI options/configuration. The README is the user-facing docs and must stay in sync with the actual `--flags` in `statusline.py`.

## Project Overview

Claude Counter is a Claude Code statusline script that displays:
- Current directory and model name
- Git branch (optional, `--git`)
- Token count with progress bar (6 styles) + cache status
- Daily cost bar (1d) with configurable budget
- Weekly cost bar (7d) with configurable budget

Single Python package, no external dependencies. Installable directly from git via `uvx` or `pipx`.

## Architecture

**`claude_counter/statusline.py`** — The statusline script. Reads JSON from stdin, outputs ANSI-colored text. Entry point: `main()`.

**`claude_counter/__init__.py`** — Package init with version.

**`pyproject.toml`** — Package metadata. Console script entry point: `claude-counter` → `claude_counter.statusline:main`.

**`install.sh`** — Convenience script to add statusline config to `~/.claude/settings.json`.

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--style` | `dots` | Bar style: text, bar, ball, capped, dots, filled |
| `--separator` | (matches style) | Separator character between segments |
| `--git` | off | Show current git branch |
| `--no-usage` | off | Disable rate limit usage bars (skip API call) |

## Rate limit usage

Session (5h) and weekly (7d) utilization is fetched from `https://api.anthropic.com/api/oauth/usage` using the OAuth token from Claude Code's credential store (macOS Keychain `Claude Code-credentials` or `~/.claude/.credentials.json` on Linux). Results are cached in `~/.claude/.claude-counter-usage-cache.json` for 15 seconds.

## Install pattern

```json
{
  "statusLine": {
    "type": "command",
    "command": "uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter --style=dots --git"
  }
}
```

## Bar styles (credit: Owloops/claude-powerline)

- `dots` (default): `●●●●○○○○○○` separator `●`
- `bar`: `████░░░░░░` separator `█`
- `ball`: `────●─────` separator `●`
- `capped`: `━━━╸┄┄┄┄┄┄` separator `━`
- `filled`: `■■■■□□□□□□` separator `■`
- `text`: `~19.0k 40%` separator `·`

## Version Bumping

Update both locations:
1. `pyproject.toml` — `version` field
2. `claude_counter/__init__.py` — `__version__`

## Testing

```bash
echo '{"session_id":"test","cwd":"/tmp/myapp","model":{"display_name":"Opus"},"context_window":{"total_input_tokens":15000,"total_output_tokens":4000,"context_window_size":200000,"used_percentage":8,"current_usage":{"cache_read_input_tokens":12000}}}' | python3 -m claude_counter.statusline --style=dots --git
```
