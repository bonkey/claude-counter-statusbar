#!/usr/bin/env python3
"""Claude Counter — Claude Code statusline.

Reads JSON from stdin (provided by Claude Code) and outputs a formatted
status line with token usage, cache status, session/weekly cost, model, and cwd.

Usage:
  claude-counter [--style=STYLE] [--weekly-budget=USD]

Styles (from claude-powerline): text, bar, ball, capped, dots (default), filled
"""

import argparse
import json
import os
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


def fmt_dir(cwd):
    home = os.environ.get("HOME", "")
    if home and cwd.startswith(home):
        cwd = "~" + cwd[len(home):]
    return os.path.basename(cwd) or cwd


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
        # Ball style: line with a marker dot at the position
        pos = min(filled_count, width - 1)
        bar = filled_ch * pos + marker_ch + empty_ch * (width - pos - 1)
        return f"{color}{bar}{RESET}"

    if cap_ch:
        # Capped style: filled with a cap at the end
        if filled_count == 0:
            bar = cap_ch + empty_ch * (width - 1)
        elif filled_count >= width:
            bar = filled_ch * width
        else:
            bar = filled_ch * (filled_count - 1) + cap_ch + empty_ch * empty_count
        return f"{color}{bar}{RESET}"

    # Standard: filled + empty
    return f"{color}{filled_ch * filled_count}{GRAY}{empty_ch * empty_count}{RESET}"


# ── Weekly cost tracking ──────────────────────────────────────────────
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


def update_weekly(session_id, session_cost):
    """Track per-session costs by date for weekly aggregation."""
    state = load_state()
    daily = state.get("daily", {})

    today = time.strftime("%Y-%m-%d")

    # Record this session's cost for today
    today_sessions = daily.get(today, {})
    today_sessions[session_id] = session_cost
    daily[today] = today_sessions

    # Prune entries older than 7 days
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
    daily = {d: s for d, s in daily.items() if d >= cutoff}

    state["daily"] = daily
    save_state(state)

    # Sum all sessions across the week
    weekly_total = sum(
        cost for day_sessions in daily.values()
        for cost in day_sessions.values()
    )
    return weekly_total


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
        "--weekly-budget",
        type=float,
        default=50.0,
        help="Weekly cost budget in USD for the progress bar (default: $50)",
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

    if used_pct >= CRIT_PCT:
        pct_str = f"{RED}{BOLD}{used_pct:.0f}%{RESET}"
    elif used_pct >= WARN_PCT:
        pct_str = f"{YELLOW}{used_pct:.0f}%{RESET}"
    else:
        pct_str = f"{used_pct:.0f}%"

    if args.style == "text":
        parts.append(f"~{fmt_tokens(total_tokens)} {pct_str}")
    else:
        bar = progress_bar(used_pct, args.style)
        parts.append(f"{bar} {pct_str}")

    # ── Cache status ──────────────────────────────────────────────
    current = ctx.get("current_usage") or {}
    cache_read = current.get("cache_read_input_tokens") or 0
    cache_creation = current.get("cache_creation_input_tokens") or 0

    if cache_read > 0:
        parts.append(f"{GREEN}⚡{fmt_tokens(cache_read)}{RESET}")
    elif cache_creation > 0:
        parts.append(f"{DIM}📝{fmt_tokens(cache_creation)}{RESET}")

    # ── Session cost ──────────────────────────────────────────────
    session_cost = cost_data.get("total_cost_usd") or 0
    if session_cost > 0:
        parts.append(fmt_cost(session_cost))

    # ── Weekly cost ───────────────────────────────────────────────
    session_id = data.get("session_id") or ""
    weekly_total = 0.0
    if session_id:
        weekly_total = update_weekly(session_id, session_cost)
    if weekly_total > 0:
        weekly_pct = min(100.0, (weekly_total / args.weekly_budget) * 100) if args.weekly_budget > 0 else 0
        if args.style == "text":
            wk_label = fmt_cost(weekly_total)
            if weekly_pct >= CRIT_PCT:
                parts.append(f"wk {RED}{BOLD}{wk_label}{RESET}")
            elif weekly_pct >= WARN_PCT:
                parts.append(f"wk {YELLOW}{wk_label}{RESET}")
            else:
                parts.append(f"wk {wk_label}")
        else:
            wk_bar = progress_bar(weekly_pct, args.style)
            parts.append(f"wk {wk_bar} {fmt_cost(weekly_total)}")

    # ── Lines changed ─────────────────────────────────────────────
    lines_added = cost_data.get("total_lines_added") or 0
    lines_removed = cost_data.get("total_lines_removed") or 0
    if lines_added > 0 or lines_removed > 0:
        line_parts = []
        if lines_added > 0:
            line_parts.append(f"{GREEN}+{lines_added}{RESET}")
        if lines_removed > 0:
            line_parts.append(f"{RED}-{lines_removed}{RESET}")
        parts.append("/".join(line_parts))

    print(" │ ".join(parts))


if __name__ == "__main__":
    main()
