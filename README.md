# Claude Counter

A statusline for [Claude Code](https://claude.ai/code) showing token usage, cache status, and session cost.

## Features

- **Current directory + model** — At-a-glance context
- **Token progress bar** — Context usage with color-coded warnings (blue → yellow → red)
- **Cache status** — Cached vs freshly written tokens from the last API call
- **Session cost** — Running total for the current session
- **Weekly cost** — Aggregated across all sessions over 7 days
- **Lines changed** — Net additions/removals
- **Bar styles** — `dots` (default), `text`, `bar`, `ball`, `capped`, `filled`

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

### Choosing a style

Append `--style=STYLE` to the command:

```json
{
  "statusLine": {
    "type": "command",
    "command": "uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter --style=bar"
  }
}
```

| Style | Example |
|-------|---------|
| `dots` (default) | `●●●●○○○○○○ 40%` |
| `bar` | `████░░░░░░ 40%` |
| `ball` | `────●───── 40%` |
| `capped` | `━━━╸┄┄┄┄┄┄ 40%` |
| `filled` | `■■■■□□□□□□ 40%` |
| `text` | `~19.0k 40%` |

### Alternative: install globally

```bash
pip install git+https://github.com/bonkey/claude-counter-statusbar
```

Then use `"command": "claude-counter"` (or `"command": "claude-counter --style=bar"`).

## How it works

Claude Code sends JSON via stdin after each assistant message. The script reads `context_window`, `cost`, `model`, and `workspace` fields and renders a compact status line with ANSI colors.

Weekly cost is tracked in `~/.claude/.claude-counter-state.json`, aggregating per-session costs by date with a 7-day rolling window.

## Credits

- Original browser extension by [shellac](https://github.com/she-llac)
- Bar styles from [claude-powerline](https://github.com/Owloops/claude-powerline) by Owloops
- Rewritten as Claude Code statusline by [Claude](https://claude.ai) (Anthropic)
- Inspired by [Claude Usage Tracker](https://github.com/lugia19/Claude-Usage-Extension) by lugia19

## License

MIT
