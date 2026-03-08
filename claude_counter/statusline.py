#!/usr/bin/env python3
"""Claude Counter — Claude Code statusline.

Reads JSON from stdin (provided by Claude Code) and outputs a formatted
status line with token usage, cache status, rate limit utilization, model, and cwd.

Usage:
  claude-counter [--style=STYLE] [--git] [--no-usage]

Styles (from claude-powerline): text, bar, ball, capped, dots (default), filled
Separator auto-matches the bar style (override with --separator).
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ── Config ────────────────────────────────────────────────────────────
BAR_WIDTH = 10
WARN_PCT = 80
CRIT_PCT = 95
USAGE_CACHE_FILE = os.path.expanduser("~/.claude/.claude-counter-usage-cache.json")
USAGE_CACHE_TTL = 15  # seconds — avoid hammering the API on every statusline update
COST_STATE_FILE = os.path.expanduser("~/.claude/.claude-counter-cost-state.json")

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

# ── Bar styles (credit: Owloops/claude-powerline) ─────────────────────
# (filled_char, empty_char, cap_char, marker_char)
BAR_STYLES = {
    "bar":    ("█", "░", None, None),
    "ball":   ("─", "─", None, "●"),
    "capped": ("━", "┄", "╸", None),
    "dots":   ("●", "○", None, None),
    "filled": ("■", "□", None, None),
}

# Default separator per style — uses the filled char, colored
STYLE_SEPARATORS = {
    "text":   "·",
    "bar":    "█",
    "ball":   "●",
    "capped": "━",
    "dots":   "●",
    "filled": "■",
}

# ── API pricing per million tokens (USD) ──────────────────────────────
# Cache reads = 10% of input price, cache writes (5min) = 125% of input price
# Source: https://she-llac.com/claude-limits
API_PRICING = {
    # model_pattern: (input_per_M, output_per_M)
    "opus":   (15.0, 75.0),
    "sonnet": (3.0, 15.0),
    "haiku":  (0.80, 4.0),
}
CACHE_READ_FACTOR = 0.10    # 10% of input price
CACHE_WRITE_FACTOR = 1.25   # 125% of input price

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_API_HEADERS = {
    "anthropic-beta": "oauth-2025-04-20",
    "Content-Type": "application/json",
}


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
    """Format resets_at ISO timestamp as a compact relative string."""
    try:
        # Parse ISO 8601 with timezone
        ts = resets_at.replace("+00:00", "Z").replace("Z", "+00:00")
        from datetime import datetime, timezone
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


def progress_bar(pct, style_name, width=BAR_WIDTH):
    pct = max(0.0, min(100.0, pct))
    filled_count = int(pct / 100 * width)
    filled_count = min(filled_count, width)
    empty_count = width - filled_count

    if pct >= CRIT_PCT:
        color = RED + BOLD
    elif pct >= WARN_PCT:
        color = YELLOW
    else:
        color = BLUE

    filled_ch, empty_ch, cap_ch, marker_ch = BAR_STYLES[style_name]

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
            bar = filled_ch * (filled_count - 1) + cap_ch + empty_ch * empty_count
        return f"{color}{bar}{RESET}"

    return f"{color}{filled_ch * filled_count}{GRAY}{empty_ch * empty_count}{RESET}"


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
        return f"{label} {pct_s}{cost_part}{reset_part}"
    bar = progress_bar(pct, style_name)
    return f"{label} {bar} {pct_s}{cost_part}{reset_part}"


# ── Cost accumulation ─────────────────────────────────────────────────
def update_accumulated_costs(session_id, session_cost):
    """Track per-session estimated API costs, return daily + weekly totals."""
    try:
        with open(COST_STATE_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state = {}

    daily = state.get("daily", {})
    today = time.strftime("%Y-%m-%d")

    today_sessions = daily.get(today, {})
    today_sessions[session_id] = session_cost
    daily[today] = today_sessions

    # Prune entries older than 7 days
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
    daily = {d: s for d, s in daily.items() if d >= cutoff}

    state["daily"] = daily
    try:
        os.makedirs(os.path.dirname(COST_STATE_FILE), exist_ok=True)
        with open(COST_STATE_FILE, "w") as f:
            json.dump(state, f)
    except OSError:
        pass

    daily_total = sum(daily.get(today, {}).values())
    weekly_total = sum(
        cost for day_sessions in daily.values()
        for cost in day_sessions.values()
    )
    return daily_total, weekly_total


# ── OAuth token retrieval ─────────────────────────────────────────────
def get_oauth_token():
    """Retrieve Claude Code OAuth access token from OS credential store."""
    system = platform.system()

    if system == "Darwin":
        # macOS: read from Keychain
        # Multiple entries may exist — find accounts with claudeAiOauth tokens
        try:
            result = subprocess.run(
                ["security", "dump-keychain"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                accounts = []
                lines = result.stdout.splitlines()
                in_creds_entry = False
                for line in lines:
                    if '"Claude Code-credentials"' in line and "0x00000007" in line:
                        in_creds_entry = True
                    elif in_creds_entry and '"acct"<blob>=' in line:
                        acct = line.split('"acct"<blob>="', 1)[-1].rstrip('"') if '"acct"<blob>="' in line else ""
                        if acct:
                            accounts.append(acct)
                        in_creds_entry = False

                for acct in accounts:
                    try:
                        r = subprocess.run(
                            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-a", acct, "-w"],
                            capture_output=True, text=True, timeout=5,
                        )
                        if r.returncode == 0:
                            creds = json.loads(r.stdout.strip())
                            token = creds.get("claudeAiOauth", {}).get("accessToken")
                            if token:
                                return token
                    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                        continue
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        # Linux/WSL: read from credentials file
        creds_file = os.path.expanduser("~/.claude/.credentials.json")
        try:
            with open(creds_file) as f:
                creds = json.load(f)
                return creds.get("claudeAiOauth", {}).get("accessToken")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    return None


# ── Usage data fetching with cache ────────────────────────────────────
def load_usage_cache():
    try:
        with open(USAGE_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_usage_cache(data):
    try:
        os.makedirs(os.path.dirname(USAGE_CACHE_FILE), exist_ok=True)
        with open(USAGE_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def fetch_usage():
    """Fetch rate limit usage from Anthropic OAuth API, with caching."""
    cache = load_usage_cache()
    cached_at = cache.get("_cached_at", 0)

    if time.time() - cached_at < USAGE_CACHE_TTL:
        return cache

    token = get_oauth_token()
    if not token:
        return cache if cache else None

    try:
        headers = dict(USAGE_API_HEADERS)
        headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(USAGE_API_URL, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            data["_cached_at"] = time.time()
            save_usage_cache(data)
            return data
    except (urllib.error.URLError, json.JSONDecodeError, OSError, TimeoutError):
        return cache if cache else None


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
        "--git", action="store_true",
        help="Show current git branch",
    )
    parser.add_argument(
        "--no-usage", action="store_true",
        help="Disable rate limit usage bars (skip API call)",
    )
    parser.add_argument(
        "--no-cost", action="store_true",
        help="Disable estimated API cost display",
    )
    args = parser.parse_args()

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

    # ── Current directory ─────────────────────────────────────────
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or ""
    if cwd:
        parts.append(f"{CYAN}{fmt_dir(cwd)}{RESET}")

    # ── Git branch ────────────────────────────────────────────────
    if args.git and cwd:
        branch = get_git_branch(cwd)
        if branch:
            parts.append(f"{DIM}⎇ {branch}{RESET}")

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
    if cache_read > 0:
        cache_str = f" {GREEN}⚡{fmt_tokens(cache_read)}{RESET}"
    elif cache_creation > 0:
        cache_str = f" {DIM}📝{fmt_tokens(cache_creation)}{RESET}"

    # Estimated API cost (grouped with token bar, no separator)
    cost_str = ""
    session_api_cost = 0.0
    if not args.no_cost:
        session_api_cost = estimate_api_cost(
            model_name, total_input, total_output, cache_read, cache_creation,
        )
        if session_api_cost > 0:
            cost_str = f" {DIM}~{fmt_cost(session_api_cost)}{RESET}"

    if args.style == "text":
        parts.append(f"~{fmt_tokens(total_tokens)} {pct_str}{cache_str}{cost_str}")
    else:
        bar = progress_bar(used_pct, args.style)
        parts.append(f"{bar} {pct_str}{cache_str}{cost_str}")

    # ── Accumulate costs across sessions ───────────────────────────
    daily_cost = 0.0
    weekly_cost = 0.0
    session_id = data.get("session_id") or ""
    if not args.no_cost and session_id and session_api_cost > 0:
        daily_cost, weekly_cost = update_accumulated_costs(session_id, session_api_cost)

    # ── Rate limit usage (session + weekly) ────────────────────────
    if not args.no_usage:
        usage = fetch_usage()
        if usage:
            five_hour = usage.get("five_hour") or {}
            seven_day = usage.get("seven_day") or {}

            session_pct = five_hour.get("utilization", 0)
            session_reset = five_hour.get("resets_at", "")
            if session_pct is not None:
                parts.append(usage_segment(
                    "5h", session_pct, session_reset, args.style,
                    cost=daily_cost if not args.no_cost else None,
                ))

            weekly_pct = seven_day.get("utilization", 0)
            weekly_reset = seven_day.get("resets_at", "")
            if weekly_pct is not None:
                parts.append(usage_segment(
                    "7d", weekly_pct, weekly_reset, args.style,
                    cost=weekly_cost if not args.no_cost else None,
                ))

    print(sep.join(parts))


if __name__ == "__main__":
    main()
