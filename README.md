# Claude Counter

A statusline for [Claude Code](https://claude.ai/code) showing token usage, cache status, and real rate limit utilization.

## Features

- **Current directory + model** — At-a-glance context
- **Git branch** — Optional, with `--git`
- **Token progress bar** — Context usage with color-coded warnings (blue → yellow → red)
- **Cache status** — Cached vs freshly written tokens from the last API call
- **Session usage bar (5h)** — Rolling 5-hour rate limit utilization with reset countdown
- **Weekly usage bar (7d)** — Rolling 7-day rate limit utilization with reset countdown
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
| `--git` | off | Show current git branch |
| `--no-usage` | off | Disable rate limit usage bars (skip API call) |

Example with all options:

```json
{
  "statusLine": {
    "type": "command",
    "command": "uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter --style=dots --git"
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

Claude Code sends JSON via stdin after each assistant message. The script reads `context_window`, `model`, and `workspace` fields and renders a compact status line with ANSI colors.

Rate limit utilization (session 5h and weekly 7d) is fetched from the Anthropic OAuth API using Claude Code's stored credentials (macOS Keychain or `~/.claude/.credentials.json` on Linux). Results are cached for 15 seconds to avoid excessive API calls.

## Credits

- Original browser extension by [shellac](https://github.com/she-llac)
- Bar styles and separator concept from [claude-powerline](https://github.com/Owloops/claude-powerline) by Owloops
- Rewritten as Claude Code statusline by [Claude](https://claude.ai) (Anthropic)
- Inspired by [Claude Usage Tracker](https://github.com/lugia19/Claude-Usage-Extension) by lugia19

## License

MIT
