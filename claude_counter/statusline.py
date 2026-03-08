#!/usr/bin/env python3
"""Claude Counter — Claude Code statusline.

Reads JSON from stdin (provided by Claude Code) and outputs a formatted
status line showing token usage, cache status, and session cost.

Features (mapped from the browser extension):
  - Token count with progress bar (context usage against window size)
  - Cache status (read vs creation tokens from last API call)
  - Session cost (replaces browser's session/weekly usage bars)
"""

import json
import sys

# ── Config ────────────────────────────────────────────────────────────
BAR_WIDTH = 20
WARN_PCT = 80
CRIT_PCT = 95

# ANSI escape helpers
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
BLUE = "\033[34m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
GRAY = "\033[90m"


# ── Formatting ────────────────────────────────────────────────────────
def fmt_tokens(n):
    """Format token count for compact display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_cost(usd):
    """Format cost, hiding sub-cent amounts."""
    if usd >= 1.0:
        return f"${usd:.2f}"
    if usd >= 0.01:
        return f"${usd:.2f}"
    if usd > 0:
        return f"${usd:.3f}"
    return "$0.00"


def progress_bar(pct, width=BAR_WIDTH):
    """Render a Unicode progress bar with ANSI colors."""
    pct = max(0.0, min(100.0, pct))
    filled = int(pct / 100 * width)
    filled = min(filled, width)
    empty = width - filled

    if pct >= CRIT_PCT:
        color = RED + BOLD
    elif pct >= WARN_PCT:
        color = YELLOW
    else:
        color = BLUE

    bar = f"{color}{'█' * filled}{GRAY}{'░' * empty}{RESET}"
    return bar


# ── Main ──────────────────────────────────────────────────────────────
def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(f"{DIM}waiting for data…{RESET}")
        return

    ctx = data.get("context_window") or {}
    cost_data = data.get("cost") or {}
    model = data.get("model") or {}

    # ── Token count + progress bar ────────────────────────────────
    total_input = ctx.get("total_input_tokens") or 0
    total_output = ctx.get("total_output_tokens") or 0
    context_size = ctx.get("context_window_size") or 200_000
    used_pct = ctx.get("used_percentage")

    # Fallback: compute percentage if not provided
    if used_pct is None and context_size > 0:
        used_pct = (total_input / context_size) * 100
    used_pct = used_pct or 0

    total_tokens = total_input + total_output
    bar = progress_bar(used_pct)

    # Color the percentage based on severity
    if used_pct >= CRIT_PCT:
        pct_str = f"{RED}{BOLD}{used_pct:.0f}%{RESET}"
    elif used_pct >= WARN_PCT:
        pct_str = f"{YELLOW}{used_pct:.0f}%{RESET}"
    else:
        pct_str = f"{used_pct:.0f}%"

    parts = [f"~{fmt_tokens(total_tokens)} {bar} {pct_str}"]

    # ── Cache status (maps to browser's cache timer) ──────────────
    current = ctx.get("current_usage") or {}
    cache_read = current.get("cache_read_input_tokens") or 0
    cache_creation = current.get("cache_creation_input_tokens") or 0

    if cache_read > 0:
        parts.append(f"{GREEN}⚡{fmt_tokens(cache_read)} cached{RESET}")
    elif cache_creation > 0:
        parts.append(f"{DIM}📝{fmt_tokens(cache_creation)} written{RESET}")

    # ── Session cost (maps to browser's session/weekly bars) ──────
    total_cost = cost_data.get("total_cost_usd") or 0
    if total_cost > 0:
        parts.append(fmt_cost(total_cost))

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
