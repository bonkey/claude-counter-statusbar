#!/usr/bin/env python3
"""Claude Counter — Claude Code statusline.

Reads JSON from stdin (provided by Claude Code) and outputs a formatted
status line with token usage, cache status, daily/weekly cost, model, and cwd.

Usage:
  claude-counter [--style=STYLE] [--daily-budget=USD] [--weekly-budget=USD] [--git]

Styles (from claude-powerline): text, bar, ball, capped, dots (default), filled
"""

import argparse
import json
import os
import subprocess
import sys
import time

# ── Config ────────────────────────────────────────────────────────────
BAR_WIDTH = 10
WARN_PCT = 80
CRIT_PCT = 95
STATE_FILE = os.path.expanduser("~/.claude/.claude-counter-state.json")

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
# Each style defines (filled_char, empty_char, cap_char, marker_char)
BAR_STYLES = {
    "bar":    ("█", "░", None, None),
    "ball":   ("─", "─", None, "●"),
    "capped": ("━", "┄", "╸", None),
    "dots":   ("●", "○", None, None),
    "filled": ("■", "□", None, None),
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


def cost_segment(label, pct, cost, style_name):
    """Render a cost segment: `label BAR PCT $COST` or `label PCT $COST` for text."""
    pct_s = fmt_pct(pct)
    cost_s = fmt_cost(cost)
    if style_name == "text":
        return f"{label} {pct_s} {cost_s}"
    bar = progress_bar(pct, style_name)
    return f"{label} {bar} {pct_s} {cost_s}"


# ── Cost tracking ────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def update_costs(session_id, session_cost):
    """Track per-session costs by date. Returns (daily_total, weekly_total)."""
    state = load_state()
    daily = state.get("daily", {})

    today = time.strftime("%Y-%m-%d")

    today_sessions = daily.get(today, {})
    today_sessions[session_id] = session_cost
    daily[today] = today_sessions

    # Prune entries older than 7 days
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
    daily = {d: s for d, s in daily.items() if d >= cutoff}

    state["daily"] = daily
    save_state(state)

    daily_total = sum(daily.get(today, {}).values())
    weekly_total = sum(
        cost for day_sessions in daily.values()
        for cost in day_sessions.values()
    )
    return daily_total, weekly_total


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
        "--daily-budget", type=float, default=10.0,
        help="Daily cost budget in USD (default: $10)",
    )
    parser.add_argument(
        "--weekly-budget", type=float, default=50.0,
        help="Weekly cost budget in USD (default: $50)",
    )
    parser.add_argument(
        "--git", action="store_true",
        help="Show current git branch",
    )
    args = parser.parse_args()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(f"{DIM}waiting for data…{RESET}")
        return

    ctx = data.get("context_window") or {}
    cost_data = data.get("cost") or {}
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

    # ── Token count + progress bar ────────────────────────────────
    total_input = ctx.get("total_input_tokens") or 0
    total_output = ctx.get("total_output_tokens") or 0
    context_size = ctx.get("context_window_size") or 200_000
    used_pct = ctx.get("used_percentage")

    if used_pct is None and context_size > 0:
        used_pct = (total_input / context_size) * 100
    used_pct = used_pct or 0

    total_tokens = total_input + total_output
    pct_str = fmt_pct(used_pct)

    if args.style == "text":
        parts.append(f"🔤 ~{fmt_tokens(total_tokens)} {pct_str}")
    else:
        bar = progress_bar(used_pct, args.style)
        parts.append(f"🔤 {bar} {pct_str}")

    # ── Cache status ──────────────────────────────────────────────
    current = ctx.get("current_usage") or {}
    cache_read = current.get("cache_read_input_tokens") or 0
    cache_creation = current.get("cache_creation_input_tokens") or 0

    if cache_read > 0:
        parts.append(f"{GREEN}⚡{fmt_tokens(cache_read)}{RESET}")
    elif cache_creation > 0:
        parts.append(f"{DIM}📝{fmt_tokens(cache_creation)}{RESET}")

    # ── Daily + weekly cost ───────────────────────────────────────
    session_id = data.get("session_id") or ""
    session_cost = cost_data.get("total_cost_usd") or 0
    daily_total = 0.0
    weekly_total = 0.0

    if session_id:
        daily_total, weekly_total = update_costs(session_id, session_cost)

    if daily_total > 0:
        daily_pct = min(100.0, (daily_total / args.daily_budget) * 100) if args.daily_budget > 0 else 0
        parts.append(cost_segment("dy", daily_pct, daily_total, args.style))

    if weekly_total > 0:
        weekly_pct = min(100.0, (weekly_total / args.weekly_budget) * 100) if args.weekly_budget > 0 else 0
        parts.append(cost_segment("wk", weekly_pct, weekly_total, args.style))

    # ── Lines changed ─────────────────────────────────────────────
    lines_added = cost_data.get("total_lines_added") or 0
    lines_removed = cost_data.get("total_lines_removed") or 0
    if lines_added > 0 or lines_removed > 0:
        line_parts = []
        if lines_added > 0:
            line_parts.append(f"{GREEN}+{lines_added}{RESET}")
        if lines_removed > 0:
            line_parts.append(f"{RED}-{lines_removed}{RESET}")
        parts.append(f"✏️ {'/'.join(line_parts)}")

    print(" │ ".join(parts))


if __name__ == "__main__":
    main()
