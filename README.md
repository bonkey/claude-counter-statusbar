# Claude Counter

A statusline for [Claude Code](https://claude.ai/code) showing token usage, cost, and real rate limit utilization.

## Features

- **Current directory + model + reasoning effort** — At-a-glance context (read from `~/.claude/settings.json`, configurable icon presets)
- **Git branch + worktree** — On by default (shows `[worktree-name]` when in a linked worktree; `--no-git` to disable)
- **Token progress bar** — Context usage with color-coded warnings (blue → yellow → red)
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
| `--git` / `--no-git` | on | Show current git branch |
| `--no-usage` | off | Disable rate limit usage bars |
| `--no-cost` | off | Disable estimated API cost display |
| `--no-total` | off | Disable billing period total cost display |
| `--billing-day` | `1` | Day of month billing resets |
| `--effort-icons` | `arrows` | Effort preset (`arrows`, `bubbles`, `style`) or 4 custom icons comma-separated |
| `--iterm-session` / `--no-iterm-session` | on | Set iTerm2 user variable `claude_session` to the session name |
| `--sync` | off | Scan historical transcripts to backfill cost data, then exit |

Example with all options:

```json
{
  "statusLine": {
    "type": "command",
    "command": "uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter --style=dots"
  }
}
```

### Bar styles

| Style | Bar | Separator |
|-------|-----|-----------|
| `dots` (default) | `●●●○○` | `●` |
| `bar` | `██░░░` | `█` |
| `ball` | `──●──` | `●` |
| `capped` | `━━╸┄┄` | `━` |
| `filled` | `■■□□□` | `■` |
| `text` | `~19.0k 40%` | `●` |

### Effort icon presets

| Preset | Low | Medium | High | Max |
|--------|-----|--------|------|-----|
| `arrows` (default) | ↓ | → | ↑ | ⇑ |
| `bubbles` | 🫧 | 💭 | 🧠 | 🔥 |
| `style` | `●○○○` | `●●○○` | `●●●○` | `●●●●` (matches `--style`) |

Custom: `--effort-icons='🐌,🐇,🐎,🚀'`

### iTerm2 session name

By default, the script sets the iTerm2 user variable `claude_session` to the current Claude Code session name (falls back to `"claude"` if unnamed). Disable with `--no-iterm-session`.

To display it in iTerm2, add `\(user.claude_session)` to your tab title or status bar:
- **Tab title:** Profiles → General → Title → use an interpolated string containing `\(user.claude_session)`
- **Status bar:** Profiles → Session → Status bar enabled → Configure Status Bar → add an Interpolated String component with value `\(user.claude_session)`

### Alternative: install globally

```bash
pip install git+https://github.com/bonkey/claude-counter-statusbar
```

Then use `"command": "claude-counter"` (with any flags).

## How it works

Claude Code sends JSON via stdin after each assistant message. The script reads `context_window`, `model`, `workspace`, `rate_limits`, and `session_id` fields and renders a compact status line with ANSI colors. Reasoning effort is read from `~/.claude/settings.json` (workaround until exposed in the statusline JSON).

Run `claude-counter --sync` to backfill historical costs from Claude Code transcripts (`~/.claude/projects/*/*.jsonl`). It also fetches the latest model pricing from [LiteLLM](https://github.com/BerriAI/litellm). Scans all sessions in the current billing period (deduplicated by request ID) and populates the cost state. After that, costs accumulate automatically on each statusline update. Run periodically to keep pricing current.

Estimated API cost shows what the current session's token usage would cost on the Anthropic API, with per-model pricing (Opus/Sonnet/Haiku) and cache discounts (reads at 10%, writes at 125% of input price). Costs are accumulated across sessions in `~/.claude/.claude-counter-cost-state.json` — daily totals shown on the 5h bar, weekly totals on the 7d bar (auto-prunes after 7 days). Pricing source: [she-llac.com/claude-limits](https://she-llac.com/claude-limits).

### Pricing

Model pricing is fetched automatically from [LiteLLM](https://github.com/BerriAI/litellm) and cached in `~/.claude/.claude-counter-pricing-cache.json` (refreshed every 24 hours).

Rate limit utilization (session 5h and weekly 7d) is read from the native `rate_limits` field provided by Claude Code ≥2.1.80. If the field is absent (older versions), usage bars are simply not shown.

## Credits

- Original browser extension by [shellac](https://github.com/she-llac)
- Bar styles and separator concept from [claude-powerline](https://github.com/Owloops/claude-powerline) by Owloops
- Rewritten as Claude Code statusline by [Claude](https://claude.ai) (Anthropic)
- Inspired by [Claude Usage Tracker](https://github.com/lugia19/Claude-Usage-Extension) by lugia19

## License

MIT
