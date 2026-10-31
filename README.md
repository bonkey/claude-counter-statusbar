# Claude Counter

A statusline for [Claude Code](https://claude.ai/code) showing token usage, cost, and real rate limit utilization.

![Claude Counter statusline demo](docs/statusbar-demo.png)

## Features

- **Powerline ribbon** — Segments joined into one band, on by default: the directory and session name in cyan and pink, then a background that steps from light under the model to dark under the last segment. Dark and light palettes (`--powerline-theme`). Needs a Nerd Font or a terminal that draws powerline glyphs, see [Terminal rendering](#terminal-rendering); `--no-powerline` separates segments with a character instead
- **Current directory + model + reasoning effort** — At-a-glance context (read from `~/.claude/settings.json`, configurable icon presets)
- **Session name** — Shown next to the directory when the session has a name (`/rename`, `--name`) or an AI-generated title
- **Git branch** — On by default, shown only when the line does not already imply it (`--no-git` to disable):
  - Main checkout: always, dimmed
  - Linked worktree whose folder ends with the branch (`<repo>.<branch>`, `/` as `-`, as worktrunk names it): only while the session has no name
  - Linked worktree on another branch: in orange
  - Detached HEAD: the short commit hash, in orange
- **Token progress bar** — Context usage with color-coded warnings (blue → yellow → red)
- **Colored percentages** — Shaded green → orange → red as usage grows (`--no-pct-color` to disable)
- **Estimated API cost** — What this session would cost on the Anthropic API, as Claude Code estimates it, shown as `💵0.10`
- **Water footprint** — Estimated liters of water your tokens consume (data-center cooling + electricity generation) per billing period, computed by `--sync`
- **Session usage bar (5h)** — Rolling 5-hour rate limit utilization with reset countdown + accumulated API cost. Hidden on Ultra accounts, which have no 5-hour limit, or shown as `5h ∞` with `--no-hide-absent-5h`
- **Weekly usage bar (7d)** — Rolling 7-day rate limit utilization with reset countdown + accumulated API cost
- **Billing period total** — Accumulated cost for the current billing cycle (resets on configurable billing day)
- **6 bar styles** — `dots` (default), `text`, `bar`, `ball`, `capped`, `filled`, or `off` for no bars
- **Style-matched separators** — With `--no-powerline`, the separator character matches the bar style (overridable)
- **Bold labels** — `ctx`, `5h` and `7d` stand out from the colored bars and percentages

## Installation

Install the tool once with `uv`:

```bash
uv tool install git+https://github.com/bonkey/claude-counter-statusbar
```

Or with `pipx`:

```bash
pipx install git+https://github.com/bonkey/claude-counter-statusbar
```

Or with `mise`, which installs from GitHub releases:

```toml
[tools]
"pipx:bonkey/claude-counter-statusbar" = "latest"
```

Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-counter"
  }
}
```

If Claude Code cannot find `claude-counter`, use its full path. `uv tool dir --bin` prints the directory, usually `~/.local/bin`.

To update, run `uv tool upgrade claude-counter`, `pipx upgrade claude-counter` or `mise upgrade`.

Do not put `uvx --from git+…` in the status line command. uv then fetches the repository from GitHub on every status line refresh, in every open session.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--style` | `dots` | Bar style: `text`, `bar`, `ball`, `capped`, `dots`, `filled`, `off` |
| `--powerline` / `--no-powerline` | on | Join segments as a powerline ribbon. Needs a Nerd Font or a terminal that draws U+E0B0, see [Terminal rendering](#terminal-rendering). `--no-powerline` separates segments with `--separator` |
| `--powerline-theme` | `auto` | Ribbon palette: `dark`, `light`, or `auto`, which follows Claude Code's `theme` setting when it names a light or dark theme and uses `dark` otherwise |
| `--separator` | *(matches style)* | Separator character between segments with `--no-powerline` |
| `--git` / `--no-git` | on | Show current git branch |
| `--no-usage` | off | Disable rate limit usage bars |
| `--no-5h` | off | Disable the 5-hour session limit segment |
| `--hide-absent-5h` / `--no-hide-absent-5h` | on | Hide the 5-hour segment when Claude Code reports no 5-hour window, as for Ultra accounts. `--no-hide-absent-5h` shows `5h ∞` instead |
| `--no-7d` | off | Disable the 7-day weekly limit segment |
| `--percent` / `--no-percent` | on | Show usage percentages |
| `--pct-color` / `--no-pct-color` | on | Color percentages green (≤50%) → orange (≤80%) → red |
| `--no-cost` | off | Disable estimated API cost display |
| `--no-total` | off | Disable billing period total cost display |
| `--no-water` | off | Disable estimated water footprint display |
| `--billing-day` | `1` | Day of month billing resets |
| `--effort-icons` | `arrows` | Effort preset (`arrows`, `circles`, `bubbles`, `style`) or custom icons comma-separated (one per tier, low→ultracode) |
| `--sync` | off | Scan historical transcripts to backfill cost data, then exit |

Example with all options:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-counter --style=dots"
  }
}
```

### Bar styles

| Style | Bar | Separator (`--no-powerline`) |
|-------|-----|------------------------------|
| `dots` (default) | `●●●○○` | `●` |
| `bar` | `██░░░` | `█` |
| `ball` | `──●──` | `●` |
| `capped` | `━━╸┄┄` | `━` |
| `filled` | `■■□□□` | `■` |
| `text` | `~19.0k 40%` | `●` |
| `off` | `40%` (no bar) | `●` |

### Effort icon presets

Mirrors Claude Code's effort ramp `low · medium · high · xhigh · max`, plus
`ultracode` (shown in magenta) as the top state. `fastMode` is layered on top as
an orange ⚡ suffix when enabled.

| Preset | Low | Medium | High | xHigh | Max | Ultracode |
|--------|-----|--------|------|-------|-----|-----------|
| `arrows` (default) | ↓ | → | ↑ | ⇈ | ⇑ | ✦ |
| `circles` | ○ | ◐ | ● | ◉ | ◈ | ✦ |
| `bubbles` | 🫧 | 💭 | 🧠 | 🔥 | 🌋 | ✨ |
| `style` | `●○○○○○` | `●●○○○○` | … | … | … | `●●●●●●` (matches `--style`) |

Colors ramp green → red across the tiers, with ultracode in magenta.

Custom: `--effort-icons='○,◐,●,◉,◈,✦'` — one icon per tier (low→ultracode).
Fewer icons clamp to the last, so a future tier never renders blank.

### Alternative: install globally

```bash
pip install git+https://github.com/bonkey/claude-counter-statusbar
```

Then use `"command": "claude-counter"` (with any flags).

## How it works

Claude Code sends JSON via stdin after each assistant message. The script reads `context_window`, `cost`, `model`, `workspace`, `rate_limits`, and `session_id` fields and renders a compact status line with ANSI colors. Reasoning effort is resolved like Claude Code's own logic: `ultracode` (from `~/.claude/settings.json`) wins, then the active per-turn effort (the `CLAUDE_EFFORT` env var, which reflects session overrides and can reach `max`), then the persisted `effortLevel` default in settings. `fastMode` from settings is shown as a ⚡ suffix.

Run `claude-counter --sync` to backfill historical costs from Claude Code transcripts (`~/.claude/projects/*/*.jsonl` and their subagent transcripts). It also fetches the latest model pricing from [LiteLLM](https://github.com/BerriAI/litellm). Scans all sessions in the current billing period (deduplicated by request ID) and populates the cost state, including the accumulated water footprint. After that, each status line update records the current session's cost. Water changes only when `--sync` runs. Run it periodically to keep pricing and water current.

The session cost is `cost.total_cost_usd` from Claude Code, its own estimate at list price. Each session's latest cost is stored in `~/.claude/.claude-counter-cost-state.json`, and their sum is the billing period total (`/mo`). `--sync` prices each transcript request at LiteLLM's rates for the model: input, output, cache reads, and 5-minute or 1-hour cache writes, plus any advisor calls at the advisor's model. Transcripts leave out some requests Claude Code counts, so a synced session usually comes out a few percent below Claude Code's figure.

### Water footprint

The `💧` segment estimates how many liters of water your token usage consumes, accumulated per billing period (`💧1.4kL/mo`) by `--sync`. The calculation has two steps: tokens → energy, then energy → water.

**Step 1 — tokens → energy.** The energy rates are anchored on the only published *measured* Claude figure: ["How Hungry is AI?" (2025)](https://arxiv.org/html/2505.09598v1) benchmarked Claude Sonnet at ~5.5 Wh for a 10k-input/1.5k-output query. Splitting that between prefill and decode (a decoded token costs roughly 10× a prefilled one — generation is sequential, prompt reading is parallel) gives:

| Token type | Energy | Why |
|------------|--------|-----|
| Input (plain or cache write) | 0.22 Wh / 1k | prefill compute |
| Cache read | 0.022 Wh / 1k | skips prefill — 10% of plain input |
| Output | 2.2 Wh / 1k | sequential decode, ~10× prefill per token |

Those are Sonnet-class rates. Each model is scaled by its API input price relative to the measured Sonnet's $3/MTok, as a rough proxy for model compute: Haiku ⅓×, Sonnet 5 ⅔×, Opus 5.5 1.33×, Fable 3.33×.

**Step 2 — energy → water.** Data centers consume water in two places, added up per the standard academic model ([Li et al. 2023](https://arxiv.org/pdf/2304.03271)):

```
water = energy × (WUE_onsite / PUE + WUE_offsite)
      = energy × (0.30 / 1.12  +  3.14)  ≈  energy × 3.4 L/kWh
```

- `WUE_onsite` = 0.30 L/kWh — water evaporated by the data center's own cooling towers, per unit of *total facility* energy. Dividing by `PUE` = 1.12 (power usage effectiveness, facility energy ÷ server energy) converts it to per-server-energy terms.
- `WUE_offsite` = 3.14 L/kWh — water evaporated generating the electricity itself (hydro reservoirs, thermal plant cooling; US grid average). This term dominates ~12:1.

**Worked example** — a Fable 5.1 session with 10k plain input, 20k cache-write, 120k cache-read, and 20k output tokens:

```
energy = 3.33 × (10 × 0.22  +  20 × 0.22  +  120 × 0.022  +  20 × 2.2)   [Fable scale × Wh]
       = 3.33 × (2.2 + 4.4 + 2.64 + 44) = 3.33 × 53.2 Wh ≈ 177 Wh
water  = 0.177 kWh × 3.4 L/kWh ≈ 0.6 L   →   💧605mL
```

Note that output tokens dominate the footprint even though input tokens dominate the count — and cache reads, the bulk of a Claude Code session, are nearly free.

Treat it as an order-of-magnitude estimate: published figures span ~1000× depending on scope — [Google reports 0.26 mL per median Gemini prompt](https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference) (onsite cooling only), while [Mistral's full lifecycle analysis](https://mistral.ai/news/our-contribution-to-a-global-environmental-standard-for-ai/) reports 45 mL per 400-token response (includes amortized training and hardware). This estimate sits in between, counting cooling + electricity generation but not hardware manufacturing or training. Disable with `--no-water`.

### Pricing

Model pricing (input, output, cache read, 5-minute and 1-hour cache write) is fetched automatically from [LiteLLM](https://github.com/BerriAI/litellm) and cached in `~/.claude/.claude-counter-pricing-cache.json` (refreshed every 24 hours). The refresh runs in a **detached background process** — the status line itself never makes a blocking network call, so a slow or failing network can't stall or garble rendering. (Attempts are throttled to once per hour and tracked in `~/.claude/.claude-counter-pricing-refresh`.)

Rate limit utilization (session 5h and weekly 7d) is read from the native `rate_limits` field provided by Claude Code ≥2.1.80. If the field is absent (older versions), usage bars are simply not shown. When `rate_limits` has a 7-day window but no 5-hour window, the 5h segment is hidden, or shows `5h ∞` with `--no-hide-absent-5h`. Ultra accounts have no 5-hour limit, so Claude Code sends no 5-hour window for them. Claude Code also drops the 5-hour window between its reset and the next API response, so a Pro or Max account can briefly lose its 5h segment, or show `5h ∞`, after a long idle period. When the 7-day window is missing, the 7d segment is hidden.

### Terminal rendering

The status line is built to be safe for Claude Code's TUI renderer: it emits a **single line** of plain text plus SGR colour codes only — no cursor-movement, screen-clear, OSC, or other escape sequences. Externally-sourced text (git branch, directory, session name, model name) is stripped of control characters before display, and the whole line is truncated to the terminal width Claude Code reports via `COLUMNS` (with an `…` ellipsis) so it never wraps onto a second row. The default `arrows` effort preset and the geometric bar glyphs are width-safe; the `bubbles` preset, the `⚡` fastMode suffix, the `💵` cost indicator and the `💧` water indicator use full-width emoji, whose rendered width some terminals measure differently.

The default powerline ribbon draws its arrows with the Private Use Area glyphs U+E0B0 and U+E0B1 (one column each). They need a [Nerd Font](https://www.nerdfonts.com/) or a powerline-patched font, or a terminal that draws them itself, such as Ghostty. Other fonts show missing-glyph boxes instead; `--no-powerline` uses plain separator characters. The ribbon sets its own background and text colors, so pick the palette that suits the terminal with `--powerline-theme`. The script runs without access to the terminal and cannot ask it for its background color.

> If you still see garbled/duplicated status lines, it's most likely a Claude Code renderer issue rather than this script — try updating Claude Code, setting `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, or `/clear`.

## Credits

- Original browser extension by [shellac](https://github.com/she-llac)
- Bar styles and separator concept from [claude-powerline](https://github.com/Owloops/claude-powerline) by Owloops
- Rewritten as Claude Code statusline by [Claude](https://claude.ai) (Anthropic)
- Inspired by [Claude Usage Tracker](https://github.com/lugia19/Claude-Usage-Extension) by lugia19

## License

MIT
