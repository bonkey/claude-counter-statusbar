# Claude Counter

A statusline for [Claude Code](https://claude.ai/code) showing token usage, cache status, and real rate limit utilization.

## Features

- **Current directory + model** — At-a-glance context
- **Git branch** — Optional, with `--git`
- **Token progress bar** — Context usage with color-coded warnings (blue → yellow → red)
- **Cache status** — Cached vs freshly written tokens from the last API call
- **Estimated API cost** — What this session would cost on the Anthropic API (per-model pricing with cache discounts)
- **Session usage bar (5h)** — Rolling 5-hour rate limit utilization with reset countdown + accumulated API cost
- **Weekly usage bar (7d)** — Rolling 7-day rate limit utilization with reset countdown + accumulated API cost
- **Billing period total** — Accumulated cost for the current billing cycle (resets on configurable billing day)
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
| `--no-cost` | off | Disable estimated API cost display |
| `--sync` | off | Scan historical transcripts to backfill cost data, then exit |

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

Run `claude-counter --sync` once to backfill historical costs from Claude Code transcripts (`~/.claude/projects/*/*.jsonl`). It scans all sessions in the current billing period and populates the cost state. After that, costs accumulate automatically on each statusline update.

Estimated API cost shows what the current session's token usage would cost on the Anthropic API, with per-model pricing (Opus/Sonnet/Haiku) and cache discounts (reads at 10%, writes at 125% of input price). Costs are accumulated across sessions in `~/.claude/.claude-counter-cost-state.json` — daily totals shown on the 5h bar, weekly totals on the 7d bar (auto-prunes after 7 days). Pricing source: [she-llac.com/claude-limits](https://she-llac.com/claude-limits).

### Configuration

`~/.claude/.claude-counter-config.json` is auto-created on first run with all defaults:

```json
{
  "bar_width": 10,
  "warn_pct": 80,
  "crit_pct": 95,
  "usage_cache_ttl": 15,
  "bar_styles": {
    "dots": ["●", "○", null, null],
    "bar": ["█", "░", null, null],
    "ball": ["─", "─", null, "●"],
    "capped": ["━", "┄", "╸", null],
    "filled": ["■", "□", null, null]
  },
  "separators": {
    "text": "·", "bar": "█", "ball": "●",
    "capped": "━", "dots": "●", "filled": "■"
  },
  "pricing": {
    "opus": [15.0, 75.0],
    "sonnet": [3.0, 15.0],
    "haiku": [0.80, 4.0]
  },
  "cache_read_factor": 0.10,
  "cache_write_factor": 1.25,
  "billing_day": 1
}
```

All fields are optional — missing keys fall back to built-in defaults. Pricing is `[input_per_M, output_per_M]` in USD ([source](https://she-llac.com/claude-limits)). Bar style chars are `[filled, empty, cap, marker]` (use `null` for unused).

Rate limit utilization (session 5h and weekly 7d) is fetched from the Anthropic OAuth API using Claude Code's stored credentials (macOS Keychain or `~/.claude/.credentials.json` on Linux). Results are cached for 15 seconds to avoid excessive API calls.

## Credits

- Original browser extension by [shellac](https://github.com/she-llac)
- Bar styles and separator concept from [claude-powerline](https://github.com/Owloops/claude-powerline) by Owloops
- Rewritten as Claude Code statusline by [Claude](https://claude.ai) (Anthropic)
- Inspired by [Claude Usage Tracker](https://github.com/lugia19/Claude-Usage-Extension) by lugia19

## License

MIT
