# Claude Counter

A statusline for [Claude Code](https://claude.ai/code) showing token usage, cache status, and session cost.

## Features

- **Token count + progress bar** — Context usage against window size with color-coded warnings
- **Cache status** — Shows cached vs freshly written tokens from the last API call
- **Session cost** — Running total for the current session
- **Lines changed** — Net additions/removals across the session

## Installation

Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter"
  }
}
```

Or with `pipx`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "pipx run --spec git+https://github.com/bonkey/claude-counter-statusbar claude-counter"
  }
}
```

Restart Claude Code to activate.

### Alternative: install globally

```bash
pip install git+https://github.com/bonkey/claude-counter-statusbar
```

Then use:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-counter"
  }
}
```

## How it works

Claude Code sends a JSON object to the statusline script via stdin after each assistant message. The script reads `context_window`, `cost`, and `current_usage` fields and renders a compact status line with ANSI colors.

**Display at different usage levels:**

| Usage | Appearance |
|-------|-----------|
| Normal (<80%) | Blue progress bar |
| Warning (80-95%) | Yellow bar + yellow percentage |
| Critical (>95%) | Red bold bar + red percentage |

**Cache indicators:**
- `⚡12.0k cached` — tokens served from cache (cheaper)
- `📝5.0k written` — tokens written to cache (first time)

## Credits

- Original browser extension by [shellac](https://github.com/she-llac)
- Rewritten as Claude Code statusline by [Claude](https://claude.ai) (Anthropic)
- Inspired by [Claude Usage Tracker](https://github.com/lugia19/Claude-Usage-Extension) by lugia19

## License

MIT
