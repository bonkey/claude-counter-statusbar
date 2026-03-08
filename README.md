# Claude Counter

A statusline for [Claude Code](https://claude.ai/code) showing token usage, cache status, and cost tracking.

## Features

- **Current directory + model** — At-a-glance context
- **Git branch** — Optional, with `--git`
- **Token progress bar** — Context usage with color-coded warnings (blue → yellow → red)
- **Cache status** — Cached vs freshly written tokens from the last API call
- **Daily cost bar** — Today's spend across all sessions, with configurable budget
- **Weekly cost bar** — Rolling 7-day spend, with configurable budget
- **6 bar styles** — `dots` (default), `text`, `bar`, `ball`, `capped`, `filled`
- **Style-matched separators** — Separator character matches the bar style (overridable)

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

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--style` | `dots` | Bar style: `text`, `bar`, `ball`, `capped`, `dots`, `filled` |
| `--separator` | *(matches style)* | Separator character between segments |
| `--daily-budget` | `10.0` | Daily cost budget in USD for the 1d progress bar |
| `--weekly-budget` | `50.0` | Weekly cost budget in USD for the 7d progress bar |
| `--git` | off | Show current git branch |

Example with all options:

```json
{
  "statusLine": {
    "type": "command",
    "command": "uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter --style=dots --git --daily-budget=15 --weekly-budget=75"
  }
}
```

### Bar styles

| Style | Bar | Separator |
|-------|-----|-----------|
| `dots` (default) | `●●●●○○○○○○` | `●` |
| `bar` | `████░░░░░░` | `█` |
| `ball` | `────●─────` | `●` |
| `capped` | `━━━╸┄┄┄┄┄┄` | `━` |
| `filled` | `■■■■□□□□□□` | `■` |
| `text` | `~19.0k 40%` | `·` |

### Alternative: install globally

```bash
pip install git+https://github.com/bonkey/claude-counter-statusbar
```

Then use `"command": "claude-counter"` (with any flags).

## How it works

Claude Code sends JSON via stdin after each assistant message. The script reads `context_window`, `cost`, `model`, and `workspace` fields and renders a compact status line with ANSI colors.

Daily and weekly costs are tracked in `~/.claude/.claude-counter-state.json`, aggregating per-session costs by date with a 7-day rolling window.

## Credits

- Original browser extension by [shellac](https://github.com/she-llac)
- Bar styles and separator concept from [claude-powerline](https://github.com/Owloops/claude-powerline) by Owloops
- Rewritten as Claude Code statusline by [Claude](https://claude.ai) (Anthropic)
- Inspired by [Claude Usage Tracker](https://github.com/lugia19/Claude-Usage-Extension) by lugia19

## License

MIT
