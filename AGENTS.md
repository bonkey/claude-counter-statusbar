# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- **Always update README.md** when adding, removing, or changing CLI options/configuration. The README is the user-facing docs and must stay in sync with the actual `--flags` in `statusline.py`.
- **Always bump version before push.** Increment the patch version in both `pyproject.toml` and `claude_counter/__init__.py` when making any functional change.
- **Verify hardcoded pricing before release.** Before each version bump, fetch current prices from LiteLLM (`LITELLM_PRICING_URL`) and update `FALLBACK_PRICING` in `statusline.py` if they've changed. Also update `model_map` keys if new model IDs have replaced old ones.

## Project Overview

Claude Counter is a Claude Code statusline script that displays:
- A powerline ribbon by default (`--no-powerline` for separators): directory and session badges in cyan and pink, then segments whose background steps evenly from light under the model to dark under the last segment, with a dark and a light palette (`--powerline-theme`)
- Current directory and model name
- Session name next to the directory, when Claude Code reports one
- Git branch when the line does not already imply it: main checkout, a worktree whose folder names another branch (orange), detached HEAD (orange hash), or no session name (on by default, `--no-git` to disable)
- Token count with progress bar (6 styles, or `off`) + cache status
- Percentages shaded green → orange → red (`--no-pct-color` to disable)
- Bold segment labels (`ctx`, `5h`, `7d`)
- Daily cost bar (1d) with configurable budget
- Weekly cost bar (7d) with configurable budget
- Estimated water footprint (billing period, from `--sync`)

Single Python package, no external dependencies. Installable directly from git via `uv tool install` or `pipx install`.

## Architecture

**`claude_counter/statusline.py`** — The statusline script. Reads JSON from stdin, outputs ANSI-colored text. Entry point: `main()`.

**`claude_counter/__init__.py`** — Package init with version.

**`pyproject.toml`** — Package metadata. Console script entry point: `claude-counter` → `claude_counter.statusline:main`.

**`install.sh`** — Convenience script to install the tool with `uv tool install` and add statusline config to `~/.claude/settings.json`.

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--style` | `dots` | Bar style: text, bar, ball, capped, dots, filled, off |
| `--powerline` / `--no-powerline` | on | Powerline ribbon (U+E0B0 arrows, needs a Nerd Font or a terminal that draws them) or separators |
| `--powerline-theme` | `auto` | Ribbon palette: dark, light, or auto (Claude Code's `theme` setting when it names one, else dark) |
| `--separator` | (matches style) | Separator character between segments with `--no-powerline` |
| `--git` / `--no-git` | on | Show current git branch |
| `--no-usage` | off | Disable rate limit usage bars |
| `--no-5h` | off | Disable 5-hour session limit segment |
| `--hide-absent-5h` / `--no-hide-absent-5h` | on | Hide the 5-hour segment when no 5-hour window is reported (Ultra); `--no-hide-absent-5h` shows `5h ∞` |
| `--no-7d` | off | Disable 7-day weekly limit segment |
| `--percent` / `--no-percent` | on | Show usage percentages |
| `--pct-color` / `--no-pct-color` | on | Color percentages green (≤50%) → orange (≤80%) → red |
| `--no-cost` | off | Disable estimated API cost display |
| `--no-total` | off | Disable billing period total cost display |
| `--no-water` | off | Disable estimated water footprint display |
| `--effort-icons` | `arrows` | Effort preset (arrows, bubbles, style) or 4 custom icons comma-separated |
| `--billing-day` | `1` | Day of month billing resets |
| `--sync` | off | Scan historical transcripts to backfill cost data, then exit |

## Rate limit usage

Session (5h) and weekly (7d) utilization is read from the native `rate_limits` field in Claude Code's stdin JSON (≥2.1.80). If absent, usage bars are not shown. A 7-day window without a 5-hour window hides the 5h segment, or shows `5h ∞` with `--no-hide-absent-5h`: Ultra accounts have no 5-hour limit, and Claude Code also drops the 5-hour window between its reset and the next API response. A missing 7-day window hides the 7d segment.

## Cost estimation

The session cost (`💰` segment) is `cost.total_cost_usd` from Claude Code's stdin JSON. `context_window` token counts describe only the most recent API response, so they cannot price a session. Each session's latest cost is stored in `~/.claude/.claude-counter-cost-state.json` under `billing_sessions`, and their sum is the billing period total (resets on `--billing-day`, default 1st).

`--sync` takes each session's total from the last `cost-state` entry in its main transcript (`totalCostUSD`, written by Claude Code ≥2.1.280 when a session ends). It is the same figure as `cost.total_cost_usd` and includes calls missing from the transcript, such as away summaries and compaction. A session with a `continued-in` entry is skipped when its continuation (`continuedInSessionId`) has a `cost-state`, because the continuation's total includes it.

Sessions without a `cost-state` are priced per request. Pricing is auto-fetched from LiteLLM and cached in `~/.claude/.claude-counter-pricing-cache.json` (24h TTL) as five USD-per-MTok rates per model: input, output, cache read, 5-minute cache write, 1-hour cache write. Cache read rates differ by model (0.025× input on Fable, 0.05× on Opus and Sonnet, 0.1× on Haiku). A request's cache writes are split by `cache_creation.ephemeral_5m_input_tokens`; the rest are priced as 1-hour. Advisor calls appear only in `usage.iterations` (type `advisor_message`, with their own `model`) and are priced at that model.

## Water footprint

Estimated liters of water per billing period (`💧` segment, `--no-water` to disable). Equation: `water = energy × (WUE_onsite/PUE + WUE_offsite) ≈ energy × 3.4 L/kWh`. Energy per token is anchored on the measured Claude Sonnet figure from arXiv:2505.09598 (0.22 Wh/1k input, 2.2 Wh/1k output), scaled per Anthropic tier by relative API input price; cache reads at 10% of input energy. Per-session water is stored in `billing_water` in the cost state. Only `--sync` writes it, because the status line gets no per-session token totals. It uses the `cost-state` entry's per-model token counts (`modelUsage`) when present, else the transcript's requests.

## Historical sync

`claude-counter --sync` does two things:
1. **Updates pricing** from LiteLLM's model pricing database (input, output, cache read, 5-minute and 1-hour cache write rates)
2. **Scans transcripts** in `~/.claude/projects/*/*.jsonl` and `~/.claude/projects/*/*/subagents/*.jsonl` (subagent transcripts carry the parent `sessionId`) to backfill cost and water from past sessions, from `cost-state` entries when present, else from requests (deduplicated by `requestId` to avoid counting streaming updates)

Only processes files modified within the current billing period. Run periodically to update pricing and recalculate costs.

## Install pattern

```bash
uv tool install git+https://github.com/bonkey/claude-counter-statusbar
```

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-counter --style=dots"
  }
}
```

Update with `uv tool upgrade claude-counter`. Do not use `uvx --from git+…` as the status line command: uv then runs a `git fetch` against GitHub on every refresh.

## Bar styles (credit: Owloops/claude-powerline)

Separators apply only with `--no-powerline`.

- `dots` (default): `●●●○○` separator `●`
- `bar`: `██░░░` separator `█`
- `ball`: `──●──` separator `●`
- `capped`: `━━╸┄┄` separator `━`
- `filled`: `■■□□□` separator `■`
- `text`: `~19.0k 40%` separator `●`
- `off`: `40%` (no bar) separator `●`

## Version Bumping

Update both locations:
1. `pyproject.toml` — `version` field
2. `claude_counter/__init__.py` — `__version__`

On each push to `main`, `.github/workflows/release.yml` creates the GitHub release `v<version>` if it does not exist yet. mise installs from these releases. The workflow fails when `claude_counter/` changed without a version bump.

## Testing

```bash
python3 -m unittest discover -s tests
```

The tests point every state, pricing and transcript path at a temporary folder. A manual render writes to `~/.claude/.claude-counter-cost-state.json`, so run it with a throwaway `HOME`:

```bash
echo '{"session_id":"test","cwd":"/tmp/myapp","model":{"display_name":"Opus"},"cost":{"total_cost_usd":1.23},"context_window":{"total_input_tokens":15000,"total_output_tokens":4000,"context_window_size":200000,"used_percentage":8,"current_usage":{"cache_read_input_tokens":12000}}}' | HOME=$(mktemp -d) python3 -m claude_counter.statusline --style=dots
```
