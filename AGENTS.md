# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- **Always update README.md** when adding, removing, or changing CLI options/configuration. The README is the user-facing docs and must stay in sync with the actual `--flags` in `statusline.py`.

## Project Overview

Claude Counter is a Claude Code statusline script that displays:
- Current directory and model name
- Git branch + worktree name (on by default, `--no-git` to disable)
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
| `--git` / `--no-git` | on | Show current git branch |
| `--no-usage` | off | Disable rate limit usage bars (skip API call) |
| `--no-cost` | off | Disable estimated API cost display |
| `--sync` | off | Scan historical transcripts to backfill cost data, then exit |

## Rate limit usage

Session (5h) and weekly (7d) utilization is fetched from `https://api.anthropic.com/api/oauth/usage` using the OAuth token from Claude Code's credential store (macOS Keychain `Claude Code-credentials` or `~/.claude/.credentials.json` on Linux). Results are cached in `~/.claude/.claude-counter-usage-cache.json` for 15 seconds.

## Cost estimation

Estimated API cost is calculated per-model with cache discounts. Pricing is auto-fetched from LiteLLM and cached in `~/.claude/.claude-counter-pricing-cache.json` (24h TTL). Cache reads at 10%, writes at 200% of input price (1-hour caching used by Claude Code). Per-session costs are accumulated in `~/.claude/.claude-counter-cost-state.json` — 5h totals, 7d totals, and billing period total (resets on `billing_day` from config, default 1st).

## Historical sync

`claude-counter --sync` does two things:
1. **Updates pricing** from LiteLLM's model pricing database (base input/output prices; cache write factor kept at 2.0x for Claude Code's 1-hour caching)
2. **Scans transcripts** in `~/.claude/projects/*/*.jsonl` to backfill cost data from past sessions (deduplicated by `requestId` to avoid counting streaming updates)

Only processes files modified within the current billing period. Run periodically to update pricing and recalculate costs.

## Config file

`~/.claude/.claude-counter-config.json` — auto-created on first run with all defaults. Edit to customize pricing, bar styles, thresholds, etc.

All fields are optional — missing keys fall back to built-in defaults.

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

- `dots` (default): `●●●●○○○○○○` separator `●`
- `bar`: `████░░░░░░` separator `█`
- `ball`: `────●─────` separator `●`
- `capped`: `━━━╸┄┄┄┄┄┄` separator `━`
- `filled`: `■■■■□□□□□□` separator `■`
- `text`: `~19.0k 40%` separator `●`

## Version Bumping

Update both locations:
1. `pyproject.toml` — `version` field
2. `claude_counter/__init__.py` — `__version__`

## Testing

```bash
echo '{"session_id":"test","cwd":"/tmp/myapp","model":{"display_name":"Opus"},"context_window":{"total_input_tokens":15000,"total_output_tokens":4000,"context_window_size":200000,"used_percentage":8,"current_usage":{"cache_read_input_tokens":12000}}}' | python3 -m claude_counter.statusline --style=dots
```
