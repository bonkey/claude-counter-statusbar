#!/usr/bin/env python3
"""Claude Counter — Claude Code statusline.

Reads JSON from stdin (provided by Claude Code) and outputs a formatted
status line with token usage, cache status, rate limit utilization, model, and cwd.

Usage:
  claude-counter [--style=STYLE] [--no-git] [--no-usage] [--no-cost] [--no-total]

Styles (from claude-powerline): text, bar, ball, capped, dots (default), filled
Separator auto-matches the bar style (override with --separator).
"""

import argparse
import calendar
import glob as globmod
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.expanduser("~/.claude/.claude-counter-config.json")
COST_STATE_FILE = os.path.expanduser("~/.claude/.claude-counter-cost-state.json")
PRICING_CACHE_FILE = os.path.expanduser("~/.claude/.claude-counter-pricing-cache.json")
PRICING_CACHE_TTL = 86400  # 24 hours

# ANSI escape helpers
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
BLUE = "\033[34m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
GRAY = "\033[90m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"

# ── Defaults (written to config on first run) ─────────────────────────
DEFAULT_CONFIG = {
    "bar_width": 5,
    "warn_pct": 80,
    "crit_pct": 95,
    "bar_styles": {
        "bar":    ["█", "░", None, None],
        "ball":   ["─", "─", None, "●"],
        "capped": ["━", "┄", "╸", None],
        "dots":   ["●", "○", None, None],
        "filled": ["■", "□", None, None],
    },
    "separators": {
        "text":   "●",
        "bar":    "█",
        "ball":   "●",
        "capped": "━",
        "dots":   "●",
        "filled": "■",
    },
    "cache_read_factor": 0.10,
    "cache_write_factor": 2.0,
    "billing_day": 1,
}

# Hardcoded fallback — only used if LiteLLM fetch has never succeeded
FALLBACK_PRICING = {
    "opus":   (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku":  (1.0, 5.0),
}


def _load_config():
    """Load config from file, creating it with defaults if missing."""
    config = None
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    except FileNotFoundError:
        # Auto-create with defaults
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
    except (json.JSONDecodeError, OSError):
        pass

    if not config:
        config = {}

    def get(key):
        return config.get(key, DEFAULT_CONFIG[key])

    # Scalars
    cfg = {
        "bar_width": int(get("bar_width")),
        "warn_pct": int(get("warn_pct")),
        "crit_pct": int(get("crit_pct")),
        "cache_read_factor": float(get("cache_read_factor")),
        "cache_write_factor": float(get("cache_write_factor")),
        "billing_day": int(get("billing_day")),
    }

    # Bar styles: convert lists to tuples
    raw_styles = get("bar_styles")
    cfg["bar_styles"] = {}
    for name, chars in raw_styles.items():
        if isinstance(chars, list) and len(chars) >= 4:
            cfg["bar_styles"][name] = tuple(chars[:4])

    # Separators
    cfg["separators"] = dict(get("separators"))

    return cfg


CFG = _load_config()
BAR_WIDTH = CFG["bar_width"]
WARN_PCT = CFG["warn_pct"]
CRIT_PCT = CFG["crit_pct"]
BAR_STYLES = CFG["bar_styles"]
STYLE_SEPARATORS = CFG["separators"]
CACHE_READ_FACTOR = CFG["cache_read_factor"]
CACHE_WRITE_FACTOR = CFG["cache_write_factor"]
BILLING_DAY = CFG["billing_day"]


def _load_pricing():
    """Load pricing from cache file, falling back to hardcoded defaults."""
    try:
        with open(PRICING_CACHE_FILE) as f:
            cache = json.load(f)
        pricing = {}
        for model, prices in cache.get("pricing", {}).items():
            if isinstance(prices, list) and len(prices) == 2:
                pricing[model] = (float(prices[0]), float(prices[1]))
        if pricing:
            return pricing
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return dict(FALLBACK_PRICING)


API_PRICING = _load_pricing()


# ── Formatting ────────────────────────────────────────────────────────
def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_cost(usd):
    if usd >= 1.0:
        return f"${usd:.2f}"
    if usd >= 0.01:
        return f"${usd:.2f}"
    if usd > 0:
        return f"${usd:.3f}"
    return "$0.00"


def fmt_pct(pct):
    if pct >= CRIT_PCT:
        return f"{RED}{BOLD}{pct:.0f}%{RESET}"
    if pct >= WARN_PCT:
        return f"{YELLOW}{pct:.0f}%{RESET}"
    return f"{pct:.0f}%"


def fmt_dir(cwd):
    home = os.environ.get("HOME", "")
    if home and cwd.startswith(home):
        cwd = "~" + cwd[len(home):]
    return os.path.basename(cwd) or cwd


def fmt_reset(resets_at):
    """Format resets_at (ISO timestamp or Unix epoch) as a compact relative string."""
    try:
        # Handle Unix epoch (number or numeric string)
        if isinstance(resets_at, (int, float)):
            dt = datetime.fromtimestamp(resets_at, tz=timezone.utc)
        elif isinstance(resets_at, str) and resets_at.replace(".", "", 1).isdigit():
            dt = datetime.fromtimestamp(float(resets_at), tz=timezone.utc)
        else:
            # Parse ISO 8601 with timezone
            ts = resets_at.replace("+00:00", "Z").replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
        now = datetime.now(timezone.utc)
        delta = (dt - now).total_seconds()
        if delta <= 0:
            return "now"
        if delta < 3600:
            return f"{int(delta / 60)}m"
        if delta < 86400:
            h = int(delta / 3600)
            m = int((delta % 3600) / 60)
            return f"{h}h{m:02d}m" if m else f"{h}h"
        d = int(delta / 86400)
        h = int((delta % 86400) / 3600)
        return f"{d}d{h}h" if h else f"{d}d"
    except Exception:
        return ""


def get_git_branch(cwd):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def get_git_worktree(cwd):
    """Return (worktree_name, repo_name) if cwd is inside a linked worktree, else (None, None)."""
    try:
        # Get the common .git dir (bare repo or main worktree's .git)
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
        # Get the current worktree's .git dir
        current = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
        if common.returncode != 0 or current.returncode != 0:
            return None, None
        common_dir = os.path.realpath(common.stdout.strip())
        current_dir = os.path.realpath(current.stdout.strip())
        # If they differ, we're in a linked worktree
        if common_dir != current_dir:
            worktree_name = os.path.basename(current_dir)
            # Repo name: common_dir is <repo>/.git or <repo>/.git/worktrees/..
            # For a regular repo, common_dir ends with .git
            repo_dir = common_dir
            if os.path.basename(repo_dir) == ".git":
                repo_dir = os.path.dirname(repo_dir)
            repo_name = os.path.basename(repo_dir)
            return worktree_name, repo_name
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None, None


# RGB values for bar colors, used for truecolor gradient shading
_COLOR_RGB = {
    "blue":   (80, 120, 220),
    "yellow": (200, 180, 50),
    "red":    (220, 60, 60),
}
_EMPTY_RGB = (90, 90, 90)  # matches GRAY


def _truecolor_fg(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


def _lerp_rgb(rgb_a, rgb_b, t):
    """Linear interpolate between two RGB tuples. t=0 → a, t=1 → b."""
    return tuple(int(a + (b - a) * t) for a, b in zip(rgb_a, rgb_b))


def progress_bar(pct, style_name, width=BAR_WIDTH):
    pct = max(0.0, min(100.0, pct))
    frac = pct / 100 * width

    if pct >= CRIT_PCT:
        color = RED + BOLD
        color_key = "red"
    elif pct >= WARN_PCT:
        color = YELLOW
        color_key = "yellow"
    else:
        color = BLUE
        color_key = "blue"

    style = BAR_STYLES[style_name]
    filled_ch, empty_ch = style[0], style[1]
    cap_ch = style[2] if len(style) > 2 else None
    marker_ch = style[3] if len(style) > 3 else None

    filled_count = min(int(frac), width)

    if marker_ch:
        pos = min(filled_count, width - 1)
        bar = filled_ch * pos + marker_ch + empty_ch * (width - pos - 1)
        return f"{color}{bar}{RESET}"

    if cap_ch:
        if filled_count == 0:
            bar = cap_ch + empty_ch * (width - 1)
        elif filled_count >= width:
            bar = filled_ch * width
        else:
            bar = filled_ch * (filled_count - 1) + cap_ch + empty_ch * (width - filled_count)
        return f"{color}{bar}{RESET}"

    # Solid fill + one dimmed fractional cell + gray empty
    frac_part = frac - filled_count
    empty_count = width - filled_count
    if frac_part > 0.05 and filled_count < width:
        # Fractional cell: same filled glyph at a weaker shade of the fill color
        # Blend from 40% to 85% of fill color based on fraction
        alpha = 0.4 + 0.45 * frac_part
        dimmed = tuple(int(c * alpha) for c in _COLOR_RGB[color_key])
        frac_cell = f"{_truecolor_fg(*dimmed)}{filled_ch}"
        empty_count -= 1
    else:
        frac_cell = ""
    return f"{color}{filled_ch * filled_count}{frac_cell}{GRAY}{empty_ch * empty_count}{RESET}"


def estimate_api_cost(model_name, total_input, total_output, cache_read, cache_creation):
    """Estimate what this session would cost on the Anthropic API."""
    model_key = None
    name_lower = (model_name or "").lower()
    for key in API_PRICING:
        if key in name_lower:
            model_key = key
            break
    if not model_key:
        model_key = "sonnet"  # fallback

    input_per_m, output_per_m = API_PRICING[model_key]

    # Non-cached input = total_input - cache_read - cache_creation
    plain_input = max(0, total_input - cache_read - cache_creation)

    cost = (
        (plain_input / 1_000_000) * input_per_m
        + (cache_read / 1_000_000) * input_per_m * CACHE_READ_FACTOR
        + (cache_creation / 1_000_000) * input_per_m * CACHE_WRITE_FACTOR
        + (total_output / 1_000_000) * output_per_m
    )
    return cost


def usage_segment(label, pct, resets_at, style_name, cost=None):
    pct_s = fmt_pct(pct)
    reset_s = fmt_reset(resets_at)
    reset_part = f" {DIM}{reset_s}{RESET}" if reset_s else ""
    cost_part = f" {DIM}~{fmt_cost(cost)}{RESET}" if cost and cost > 0 else ""
    if style_name == "text":
        return f"{label} {pct_s}{reset_part}{cost_part}"
    bar = progress_bar(pct, style_name)
    return f"{label} {bar} {pct_s}{reset_part}{cost_part}"


# ── Billing period helpers ────────────────────────────────────────────


def _effective_billing_day(year, month, billing_day):
    """Clamp billing_day to the last day of the given month.

    e.g. billing_day=29 in February → 28 (or 29 in leap year).
    """
    last_day = calendar.monthrange(year, month)[1]
    return min(billing_day, last_day)


def _billing_period_start(dt_obj=None, billing_day=None):
    """Return the start datetime of the current billing period."""
    if dt_obj is None:
        dt_obj = datetime.now(timezone.utc)
    if billing_day is None:
        billing_day = BILLING_DAY

    effective = _effective_billing_day(dt_obj.year, dt_obj.month, billing_day)

    if dt_obj.day >= effective:
        # Current period started this month
        return datetime(dt_obj.year, dt_obj.month, effective, tzinfo=timezone.utc)
    else:
        # Current period started last month
        if dt_obj.month == 1:
            prev_year, prev_month = dt_obj.year - 1, 12
        else:
            prev_year, prev_month = dt_obj.year, dt_obj.month - 1
        prev_effective = _effective_billing_day(prev_year, prev_month, billing_day)
        return datetime(prev_year, prev_month, prev_effective, tzinfo=timezone.utc)


def _billing_period_key(dt_obj=None, billing_day=None):
    """Return a string key like '2026-03' for the current billing period."""
    start = _billing_period_start(dt_obj, billing_day)
    return f"{start.year}-{start.month:02d}"


# ── Cost accumulation (aligned with rate limit windows) ───────────────
def _load_cost_state():
    try:
        with open(COST_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_cost_state(state):
    try:
        os.makedirs(os.path.dirname(COST_STATE_FILE), exist_ok=True)
        with open(COST_STATE_FILE, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def update_accumulated_costs(session_id, session_cost):
    """Track per-session costs for the billing period. Returns billing_cost."""
    state = _load_cost_state()

    # Check if billing period rolled over → re-sync from transcripts
    current_period = _billing_period_key()
    if state.get("billing_period") != current_period:
        try:
            sync_historical_costs()
            state = _load_cost_state()
        except Exception:
            state["billing_sessions"] = {}
            state["billing_period"] = current_period

    billing_sessions = state.get("billing_sessions", {})
    billing_sessions[session_id] = session_cost
    state["billing_sessions"] = billing_sessions

    _save_cost_state(state)

    return sum(billing_sessions.values())


# ── Historical transcript sync ───────────────────────────────────────
TRANSCRIPT_DIR = os.path.expanduser("~/.claude/projects")
LITELLM_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"


def fetch_and_update_pricing(force=False):
    """Fetch latest pricing from LiteLLM and cache locally.

    Cached for 24h. Pass force=True to skip TTL check (used by --sync).
    Uses LiteLLM for base input/output prices. Cache write factor is kept
    from config (default 2.0x for 1-hour caching used by Claude Code).
    """
    global API_PRICING

    # Check cache TTL
    if not force:
        try:
            with open(PRICING_CACHE_FILE) as f:
                cache = json.load(f)
            if time.time() - cache.get("_cached_at", 0) < PRICING_CACHE_TTL:
                return False  # still fresh
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    try:
        req = urllib.request.Request(LITELLM_PRICING_URL, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError, TimeoutError):
        return False

    # Map model patterns to LiteLLM keys
    model_map = {
        "opus": "claude-opus-4-6",
        "sonnet": "claude-sonnet-4-6",
        "haiku": "claude-haiku-4-5-20251001",
    }

    updated = {}
    for our_key, litellm_key in model_map.items():
        model_data = data.get(litellm_key)
        if not model_data:
            continue
        inp = model_data.get("input_cost_per_token", 0)
        out = model_data.get("output_cost_per_token", 0)
        if inp > 0 and out > 0:
            # Convert per-token to per-M
            updated[our_key] = [round(inp * 1_000_000, 2), round(out * 1_000_000, 2)]

    if not updated:
        return False

    # Save to pricing cache file
    cache = {"pricing": updated, "_cached_at": time.time()}
    try:
        os.makedirs(os.path.dirname(PRICING_CACHE_FILE), exist_ok=True)
        with open(PRICING_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        return False

    # Update in-memory pricing
    for key, prices in updated.items():
        API_PRICING[key] = (prices[0], prices[1])

    return True


def _estimate_cost_from_usage(usage, model_str):
    """Calculate cost from a single assistant message's usage dict."""
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    return estimate_api_cost(model_str, input_tokens, output_tokens, cache_read, cache_creation)


def sync_historical_costs():
    """Scan transcript files and backfill cost state.

    Returns (sessions_found, total_cost).
    """
    billing_period = _billing_period_key()
    now = datetime.now(timezone.utc)
    period_start = _billing_period_start(now)

    # Cutoffs for each window
    five_hour_cutoff = now.timestamp() - 5 * 3600
    seven_day_cutoff = now.timestamp() - 7 * 86400
    billing_cutoff = period_start.timestamp()

    # Find all transcript files — only check files modified since billing start
    pattern = os.path.join(TRANSCRIPT_DIR, "*", "*.jsonl")
    files = globmod.glob(pattern)

    # Deduplicate by requestId — Claude Code logs streaming updates,
    # so the same API call appears multiple times. Keep the last (largest) entry.
    # Structure: {requestId: {usage, model, sessionId, timestamp}}
    requests = {}
    session_timestamps = {}  # session_id -> latest timestamp

    for fpath in files:
        try:
            mtime = os.path.getmtime(fpath)
            if mtime < billing_cutoff:
                continue  # older than billing period
        except OSError:
            continue

        try:
            with open(fpath) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if entry.get("type") != "assistant":
                        continue
                    msg = entry.get("message") or {}
                    usage = msg.get("usage")
                    if not usage:
                        continue

                    req_id = entry.get("requestId", "")
                    if not req_id:
                        continue

                    # Keep entry with highest output_tokens (final streaming update)
                    out = usage.get("output_tokens", 0)
                    prev = requests.get(req_id)
                    if prev is None or out > prev["usage"].get("output_tokens", 0):
                        requests[req_id] = {
                            "usage": usage,
                            "model": msg.get("model", ""),
                            "sessionId": entry.get("sessionId", ""),
                            "timestamp": entry.get("timestamp", ""),
                        }

                    # Track latest timestamp per session
                    ts_str = entry.get("timestamp", "")
                    session_id = entry.get("sessionId", "")
                    if ts_str and session_id:
                        if session_id not in session_timestamps or ts_str > session_timestamps[session_id]:
                            session_timestamps[session_id] = ts_str
        except OSError:
            continue

    # Sum costs per session from deduplicated requests
    session_costs = {}
    for req in requests.values():
        sid = req["sessionId"]
        cost = _estimate_cost_from_usage(req["usage"], req["model"])
        session_costs[sid] = session_costs.get(sid, 0.0) + cost

    # Now bucket sessions into windows based on their latest timestamp
    state = _load_cost_state()

    five_hour_sessions = {}
    seven_day_sessions = {}
    billing_sessions = {}

    for sid, cost in session_costs.items():
        ts_str = session_timestamps.get(sid, "")
        if not ts_str:
            continue
        try:
            ts_parsed = ts_str.replace("+00:00", "Z").replace("Z", "+00:00")
            ts_dt = datetime.fromisoformat(ts_parsed)
            ts_epoch = ts_dt.timestamp()
        except (ValueError, OSError):
            continue

        if ts_epoch >= billing_cutoff:
            billing_sessions[sid] = cost
        if ts_epoch >= seven_day_cutoff:
            seven_day_sessions[sid] = cost
        if ts_epoch >= five_hour_cutoff:
            five_hour_sessions[sid] = cost

    # Preserve resets_at from existing state (sync doesn't know these)
    state["five_hour_sessions"] = five_hour_sessions
    state["seven_day_sessions"] = seven_day_sessions
    state["billing_sessions"] = billing_sessions
    state["billing_period"] = billing_period
    state["synced_at"] = time.time()

    _save_cost_state(state)

    total = sum(billing_sessions.values())
    return len(session_costs), total



# ── Main ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Claude Counter statusline")
    parser.add_argument(
        "--style",
        choices=["text", "bar", "ball", "capped", "dots", "filled"],
        default="dots",
        help="Progress bar style (default: dots)",
    )
    parser.add_argument(
        "--separator", type=str, default=None,
        help="Separator character (default: matches bar style)",
    )
    parser.add_argument(
        "--git", action=argparse.BooleanOptionalAction, default=True,
        help="Show current git branch (default: on)",
    )
    parser.add_argument(
        "--no-usage", action="store_true",
        help="Disable rate limit usage bars",
    )
    parser.add_argument(
        "--no-cost", action="store_true",
        help="Disable estimated API cost display",
    )
    parser.add_argument(
        "--no-total", action="store_true",
        help="Disable billing period total cost display",
    )
    parser.add_argument(
        "--sync", action="store_true",
        help="Scan historical transcripts to backfill cost data, then exit",
    )
    args = parser.parse_args()

    # ── Sync mode (standalone) ────────────────────────────────────
    if args.sync:
        print("Updating pricing from LiteLLM…", file=sys.stderr)
        if fetch_and_update_pricing(force=True):
            print(f"  Pricing updated: {dict(API_PRICING)}", file=sys.stderr)
        else:
            print("  Using cached pricing (fetch failed or unchanged)", file=sys.stderr)
        print(f"Scanning transcripts in {TRANSCRIPT_DIR}…", file=sys.stderr)
        sessions, total = sync_historical_costs()
        print(f"Done: {sessions} sessions, ~{fmt_cost(total)} billing period total", file=sys.stderr)
        return

    # Auto-refresh pricing if cache is stale (24h TTL, non-blocking)
    if not args.no_cost:
        fetch_and_update_pricing()

    sep_char = args.separator or STYLE_SEPARATORS.get(args.style, "·")
    sep = f" {GRAY}{sep_char}{RESET} "

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(f"{DIM}waiting for data…{RESET}")
        return

    ctx = data.get("context_window") or {}
    model_data = data.get("model") or {}

    parts = []

    # ── Current directory + Git branch/worktree ───────────────────
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or ""
    dir_name = fmt_dir(cwd) if cwd else ""
    git_part = ""
    if args.git and cwd:
        branch = get_git_branch(cwd)
        if branch:
            worktree_name, repo_name = get_git_worktree(cwd)
            if worktree_name:
                # In a worktree: show repo name as dir, ⎇ worktree name
                if repo_name:
                    dir_name = repo_name
                git_part = f"{DIM}⎇ {worktree_name}{RESET}"
            else:
                git_part = f"{DIM} {branch}{RESET}"
    if dir_name:
        parts.append(f"{CYAN}{dir_name}{RESET}")
    if git_part:
        parts.append(git_part)

    # ── Model ─────────────────────────────────────────────────────
    model_name = model_data.get("display_name") or ""
    if model_name:
        parts.append(f"{MAGENTA}{model_name}{RESET}")

    # ── Token count + progress bar + cache (grouped) ──────────────
    total_input = ctx.get("total_input_tokens") or 0
    total_output = ctx.get("total_output_tokens") or 0
    context_size = ctx.get("context_window_size") or 200_000
    used_pct = ctx.get("used_percentage")

    if used_pct is None and context_size > 0:
        used_pct = (total_input / context_size) * 100
    used_pct = used_pct or 0

    total_tokens = total_input + total_output
    pct_str = fmt_pct(used_pct)

    # Cache info (appended to token segment, no separator)
    current = ctx.get("current_usage") or {}
    cache_read = current.get("cache_read_input_tokens") or 0
    cache_creation = current.get("cache_creation_input_tokens") or 0

    cache_str = ""

    # Estimated API cost (grouped with token bar, no separator)
    cost_str = ""
    session_api_cost = 0.0
    if not args.no_cost:
        session_api_cost = estimate_api_cost(
            model_name, total_input, total_output, cache_read, cache_creation,
        )
        if session_api_cost > 0:
            cost_str = f" {DIM}~{fmt_cost(session_api_cost)}{RESET}"

    if context_size >= 1_000_000:
        ctx_size_label = f"{context_size // 1_000_000}M"
    elif context_size >= 1_000:
        ctx_size_label = f"{context_size // 1_000}k"
    else:
        ctx_size_label = str(context_size)
    ctx_size_str = f"/{ctx_size_label}"
    if args.style == "text":
        parts.append(f"ctx ~{fmt_tokens(total_tokens)} {pct_str}{ctx_size_str}{cache_str}{cost_str}")
    else:
        bar = progress_bar(used_pct, args.style)
        parts.append(f"ctx {bar} {pct_str}{ctx_size_str}{cache_str}{cost_str}")

    # ── Rate limit usage (session + weekly) ─────────────────────
    # Read from native rate_limits field (Claude Code ≥2.1.80)
    billing_cost = 0.0

    rate_limits = data.get("rate_limits") or {}
    five_hour = rate_limits.get("five_hour") or {}
    seven_day = rate_limits.get("seven_day") or {}

    # Accumulate billing cost (independent of rate_limits presence)
    session_id = data.get("session_id") or ""
    if not args.no_cost and session_id and session_api_cost > 0:
        billing_cost = update_accumulated_costs(session_id, session_api_cost)

    if five_hour or seven_day:
        session_pct = five_hour.get("used_percentage", 0)
        session_reset = five_hour.get("resets_at", "")
        weekly_pct = seven_day.get("used_percentage", 0)
        weekly_reset = seven_day.get("resets_at", "")

        # Usage bars
        if not args.no_usage:
            if session_pct is not None:
                parts.append(usage_segment(
                    "5h", session_pct, session_reset, args.style,
                ))
            if weekly_pct is not None:
                parts.append(usage_segment(
                    "7d", weekly_pct, weekly_reset, args.style,
                ))

    # ── Billing period total cost ────────────────────────────
    if not args.no_cost and not args.no_total and billing_cost > 0:
        parts.append(f"{DIM}~{fmt_cost(billing_cost)}/mo{RESET}")

    print(sep.join(parts))


if __name__ == "__main__":
    main()
