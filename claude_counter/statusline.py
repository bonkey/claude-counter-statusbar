#!/usr/bin/env python3
"""Claude Counter — Claude Code statusline.

Reads JSON from stdin (provided by Claude Code) and outputs a formatted
status line with token usage, cache status, rate limit utilization, model, and cwd.

Usage:
  claude-counter [--style=STYLE] [--no-git] [--no-usage] [--no-cost] [--no-total]

Styles (from claude-powerline): text, bar, ball, capped, dots (default), filled,
plus off (no bars).
Segments form a powerline ribbon; with --no-powerline they are joined by a
separator that matches the bar style (override with --separator).
"""

import argparse
import calendar
import glob as globmod
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────
CLAUDE_SETTINGS_FILE = os.path.expanduser("~/.claude/settings.json")
COST_STATE_FILE = os.path.expanduser("~/.claude/.claude-counter-cost-state.json")
PRICING_CACHE_FILE = os.path.expanduser("~/.claude/.claude-counter-pricing-cache.json")
PRICING_CACHE_TTL = 86400  # 24 hours
PRICING_REFRESH_STAMP_FILE = os.path.expanduser("~/.claude/.claude-counter-pricing-refresh")
PRICING_REFRESH_BACKOFF = 3600  # cap background refresh attempts to once/hour

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
LIME = "\033[38;5;148m"
ORANGE = "\033[38;5;208m"
BRIGHT_MAGENTA = "\033[95m"

# ── Constants ─────────────────────────────────────────────────────────
BAR_WIDTH = 5
WARN_PCT = 80
CRIT_PCT = 95
CACHE_READ_FACTOR = 0.10
CACHE_WRITE_FACTOR = 2.0
BILLING_DAY = 1  # default, overridable via --billing-day

# ── Water footprint model ─────────────────────────────────────────────
# water = energy × (WUE_onsite / PUE + WUE_offsite)
# (Li et al. 2023 arXiv:2304.03271; "How Hungry is AI?" arXiv:2505.09598).
# Onsite = data-center cooling (~0.30 L/kWh hyperscaler avg, PUE ~1.12);
# offsite = water evaporated generating the electricity (~3.14 L/kWh US
# grid) — offsite dominates. Google's Gemini disclosure counts onsite
# only, which is why its per-prompt figure is ~10× lower.
WATER_L_PER_KWH = 0.30 / 1.12 + 3.142  # ≈ 3.41

# Inference energy per token, anchored on the measured Claude Sonnet
# figure from arXiv:2505.09598 (~5.5 Wh per 10k-input/1.5k-output query,
# assuming decode ≈ 10× prefill per token). Other Anthropic tiers are
# scaled by relative API input price as a rough compute-size proxy.
# Cache reads skip prefill compute → same discount as the cost model.
WATER_WH_PER_1K_INPUT = 0.22
WATER_WH_PER_1K_OUTPUT = 2.2
WATER_BASELINE_INPUT_PRICE = 3.0  # $/MTok of the Sonnet-class anchor
WATER_ICON = "💧"

BAR_STYLES = {
    "bar":    ("█", "░", None, None),
    "ball":   ("─", "─", None, "●"),
    "capped": ("━", "┄", "╸", None),
    "dots":   ("●", "○", None, None),
    "filled": ("■", "□", None, None),
}

# Reasoning effort tiers — the source of truth for count/order.
# Mirrors Claude Code's own ramp ["low","medium","high","xhigh","max"] plus
# "ultracode" (xhigh effort + standing dynamic-workflow orchestration), which
# Claude Code surfaces as a separate top state rendered in magenta.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max", "ultracode")
EFFORT_COLORS = (GREEN, LIME, YELLOW, ORANGE, RED, BRIGHT_MAGENTA)

# Glyph presets — one symbol per tier. Variable length: shorter presets clamp
# to their last glyph, so a future tier degrades gracefully instead of vanishing.
EFFORT_PRESETS = {
    "arrows":  ("↓", "→", "↑", "⇈", "⇑", "✦"),
    "circles": ("○", "◐", "●", "◉", "◈", "✦"),
    "bubbles": ("🫧", "💭", "🧠", "🔥", "🌋", "✨"),
}

# fastMode is orthogonal to the effort tier ("fast on top") — shown as a suffix.
FAST_ICON = "⚡"
FAST_COLOR = "\033[38;5;202m"  # ~rgb(255,106,0), matches Claude Code's fastMode color

STYLE_SEPARATORS = {
    "text":   "●",
    "bar":    "█",
    "ball":   "●",
    "capped": "━",
    "dots":   "●",
    "filled": "■",
    "off":    "●",
}

# Percentage color stops (pct, rgb): green up to 50, orange by 80, red above.
# Colors in between are interpolated in truecolor.
PCT_COLOR_STOPS = (
    (0,   (80, 200, 80)),
    (50,  (150, 200, 60)),
    (65,  (220, 190, 50)),
    (80,  (240, 140, 40)),
    (95,  (220, 60, 60)),
)

# Powerline: badges first, then a band whose background steps evenly from
# "light" under the model to "dark" under the last segment.
POWERLINE_ARROW = "\ue0b0"
POWERLINE_SOFT_ARROW = "\ue0b1"  # between neighbours on the same background
# Badge background, and the same color as a foreground for the arrow after it.
DIR_BADGE = ("\033[106m", "\033[96m")
SESSION_BADGE = ("\033[105m", "\033[95m")
# One palette per terminal theme. The terminal's own colors are tuned for its
# background, so on the band they are replaced with "fg", and the percentages
# use "pct". Dim text and empty bar cells move toward "ink" until they reach
# their contrast; the partial bar cell blends from "frac".
POWERLINE_PALETTES = {
    "dark": {
        "light": (80, 87, 106), "dark": (8, 9, 12),
        "text": (225, 228, 235), "ink": (255, 255, 255), "frac": (120, 125, 140),
        "pct": ((0, (110, 220, 110)), (50, (170, 220, 90)), (65, (235, 205, 80)),
                (80, (255, 160, 70)), (95, (255, 130, 130))),
        "fg": {RED: (255, 140, 140), GREEN: (120, 225, 120), YELLOW: (240, 210, 90),
               BLUE: (135, 170, 255), MAGENTA: (245, 215, 252), BRIGHT_MAGENTA: (245, 185, 255),
               LIME: (195, 230, 100), ORANGE: (255, 175, 80), FAST_COLOR: (255, 150, 80)},
    },
    "light": {
        "light": (228, 231, 238), "dark": (166, 172, 187),
        "text": (30, 33, 42), "ink": (0, 0, 0), "frac": (150, 155, 165),
        "pct": ((0, (15, 115, 40)), (50, (80, 105, 0)), (65, (125, 85, 0)),
                (80, (160, 60, 0)), (95, (175, 25, 25))),
        "fg": {RED: (175, 25, 25), GREEN: (15, 115, 40), YELLOW: (125, 85, 0),
               BLUE: (25, 85, 195), MAGENTA: (125, 35, 145), BRIGHT_MAGENTA: (145, 35, 165),
               LIME: (80, 105, 0), ORANGE: (165, 70, 0), FAST_COLOR: (175, 60, 0)},
    },
}
BAND_MUTED_CONTRAST = 4.0  # reset times, cost, water
BAND_EMPTY_CONTRAST = 2.5  # empty bar cells
FRAC_BLEND_RGB = (0, 0, 0)  # the partial bar cell blends from this toward the fill

# Hardcoded fallback — only used if LiteLLM fetch has never succeeded
FALLBACK_PRICING = {
    "fable":  (10.0, 50.0),
    "opus":   (4.0, 20.0),
    "sonnet": (2.0, 10.0),
    "haiku":  (0.1, 0.5),
}


def _load_pricing():
    """Load pricing from cache file, falling back to hardcoded defaults."""
    # Start from the fallback so models added in a new release are priced even
    # when an older cache file (without them) is still present; cache overrides.
    pricing = dict(FALLBACK_PRICING)
    try:
        with open(PRICING_CACHE_FILE) as f:
            cache = json.load(f)
        for model, prices in cache.get("pricing", {}).items():
            if isinstance(prices, list) and len(prices) == 2:
                pricing[model] = (float(prices[0]), float(prices[1]))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return pricing


API_PRICING = _load_pricing()


# ── Terminal-safety helpers ───────────────────────────────────────────
# Output is captured by Claude Code and re-laid-out by its TUI renderer, so
# everything we emit must be a single line of printable text plus SGR color
# codes — no control characters, and a width we can keep within COLUMNS.

# C0 controls, DEL, and C1 controls. Any of these in externally-sourced text
# (git branch, directory, model name) would corrupt the rendered status line.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# Self-contained SGR colour sequence (the only escape we ever emit).
_SGR_RE = re.compile(r"\033\[[0-9;]*m")


def _sanitize(s):
    """Strip control characters from text that came from outside the script."""
    if not s:
        return s
    return _CONTROL_CHARS.sub("", s)


def _display_width(ch):
    """Columns a character occupies, matching Claude Code's width counter.

    Mirrors the `string-width` semantics Claude Code (Ink) uses: East-Asian
    Wide/Fullwidth → 2, combining/zero-width → 0, everything else (including
    Ambiguous) → 1. Matching its count is what keeps our line and its redraw
    in sync.
    """
    if ch in ("‍", "️") or unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _iter_cells(s):
    """Yield (chunk, is_escape): whole SGR sequences as escapes, else one char."""
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\033":
            m = _SGR_RE.match(s, i)
            if m:
                yield s[i:m.end()], True
                i = m.end()
            else:
                # Bare ESC should never occur; drop it rather than emit it raw.
                yield "", True
                i += 1
            continue
        yield s[i], False
        i += 1


def _visible_width(s):
    return sum(_display_width(ch) for ch, esc in _iter_cells(s) if not esc)


def _truncate_to_width(s, max_width):
    """Cut to at most max_width visible columns without splitting an escape."""
    out, width = [], 0
    for chunk, esc in _iter_cells(s):
        if esc:
            out.append(chunk)
            continue
        w = _display_width(chunk)
        if width + w > max_width:
            return "".join(out), True
        out.append(chunk)
        width += w
    return "".join(out), False


def _columns():
    """The width Claude Code reports via COLUMNS, or None when unset or not positive."""
    cols = os.environ.get("COLUMNS", "")
    return int(cols) if cols.isdigit() and int(cols) > 0 else None


def _bound_to_columns(line):
    """Truncate the rendered line to the width Claude Code reports via COLUMNS.

    Recent Claude Code sets COLUMNS for the statusline subprocess. Bounding the
    line here makes an over-long status truncate predictably (with an ellipsis)
    instead of wrapping onto a second row — wrapping is what aggravates known
    redraw/scrollback-bleed bugs on wide panes. No-op when COLUMNS is unset or
    not a positive integer, so behaviour is unchanged on older versions.
    """
    max_width = _columns()
    if max_width is None or _visible_width(line) <= max_width:
        return line
    text, _ = _truncate_to_width(line, max(0, max_width - 1))
    return f"{text}{RESET}…"


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


def fmt_water(liters):
    ml = liters * 1000
    if ml <= 0:
        return "0mL"
    if ml < 1000:
        return f"{max(1, round(ml))}mL"
    if liters < 100:
        return f"{liters:.1f}L"
    if liters < 1000:
        return f"{liters:.0f}L"
    return f"{liters / 1000:.1f}kL"


def pct_color(pct):
    """Truecolor escape for pct, interpolated between PCT_COLOR_STOPS."""
    lo_pct, lo_rgb = PCT_COLOR_STOPS[0]
    for hi_pct, hi_rgb in PCT_COLOR_STOPS:
        if pct <= hi_pct:
            t = (pct - lo_pct) / (hi_pct - lo_pct) if hi_pct > lo_pct else 0.0
            return _truecolor_fg(*_lerp_rgb(lo_rgb, hi_rgb, t))
        lo_pct, lo_rgb = hi_pct, hi_rgb
    return _truecolor_fg(*lo_rgb)


def fmt_pct(pct, color=True):
    if not color:
        return f"{pct:.0f}%"
    bold = BOLD if pct >= CRIT_PCT else ""
    return f"{pct_color(pct)}{bold}{pct:.0f}%{RESET}"


def fmt_dir(cwd):
    home = os.environ.get("HOME", "")
    if home and cwd.startswith(home):
        cwd = "~" + cwd[len(home):]
    return _sanitize(os.path.basename(cwd) or cwd)


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
            return _sanitize(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def get_git_short_sha(cwd):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return _sanitize(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def get_git_worktree(cwd):
    """Return (worktree folder name, repo_name) if cwd is inside a linked worktree, else (None, None)."""
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
            # The gitdir file points at <worktree>/.git and follows `git worktree move`.
            # The admin dir keeps the name the worktree was created with.
            try:
                with open(os.path.join(current_dir, "gitdir")) as f:
                    worktree_name = os.path.basename(os.path.dirname(f.read().strip()))
            except OSError:
                worktree_name = os.path.basename(current_dir)
            # Repo name: common_dir is <repo>/.git or <repo>/.git/worktrees/..
            # For a regular repo, common_dir ends with .git
            repo_dir = common_dir
            if os.path.basename(repo_dir) == ".git":
                repo_dir = os.path.dirname(repo_dir)
            repo_name = os.path.basename(repo_dir)
            return _sanitize(worktree_name), _sanitize(repo_name)
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


def _truecolor_bg(r, g, b):
    return f"\033[48;2;{r};{g};{b}m"


def _lerp_rgb(rgb_a, rgb_b, t):
    """Linear interpolate between two RGB tuples. t=0 → a, t=1 → b."""
    return tuple(int(a + (b - a) * t) for a, b in zip(rgb_a, rgb_b))


def _luminance(rgb):
    """WCAG relative luminance of an sRGB color."""
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _lift(bg, ratio, ink):
    """bg moved toward ink just far enough to reach ratio against bg."""
    for i in range(101):
        rgb = _lerp_rgb(bg, ink, i / 100)
        if _contrast(rgb, bg) >= ratio:
            return rgb
    return ink


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
        dimmed = _lerp_rgb(FRAC_BLEND_RGB, _COLOR_RGB[color_key], alpha)
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


def estimate_water_liters(model_name, total_input, total_output, cache_read, cache_creation):
    """Estimate liters of water consumed by this session's inference.

    Per-token energy (Sonnet-class anchor, price-scaled per tier) times
    data-center water intensity (onsite cooling + offsite electricity
    generation). An order-of-magnitude estimate — see README for sources.
    """
    name_lower = (model_name or "").lower()
    input_price = None
    for key, (inp, _out) in API_PRICING.items():
        if key in name_lower:
            input_price = inp
            break
    scale = (input_price / WATER_BASELINE_INPUT_PRICE) if input_price else 1.0

    plain_input = max(0, total_input - cache_read - cache_creation)
    energy_wh = scale * (
        ((plain_input + cache_creation) / 1000) * WATER_WH_PER_1K_INPUT
        + (cache_read / 1000) * WATER_WH_PER_1K_INPUT * CACHE_READ_FACTOR
        + (total_output / 1000) * WATER_WH_PER_1K_OUTPUT
    )
    return (energy_wh / 1000) * WATER_L_PER_KWH


def usage_segment(label, pct, resets_at, style_name, cost=None, show_pct=True, color=True):
    pct_part = f" {fmt_pct(pct, color)}" if show_pct else ""
    reset_s = fmt_reset(resets_at)
    reset_part = f" {DIM}{reset_s}{RESET}" if reset_s else ""
    cost_part = f" {DIM}~{fmt_cost(cost)}{RESET}" if cost and cost > 0 else ""
    bar_part = "" if style_name in ("text", "off") else f" {progress_bar(pct, style_name)}"
    return f"{fmt_label(label)}{bar_part}{pct_part}{reset_part}{cost_part}"


def fmt_label(label):
    return f"{BOLD}{label}\033[22m"


def powerline_join(parts, badges, start, palette):
    """Join parts as powerline segments that touch, each padded by one space.

    The first len(badges) parts are badges with their own background. The
    rest form a band whose background steps evenly from palette["light"] at
    parts[start] to palette["dark"] at the last part; band parts before start
    share the lightest step, and a lone part at start takes the darkest. Each
    arrow takes the current background as its foreground and the next
    background as its own, and the last one ends on the terminal's default
    background. A RESET inside a part also clears the background, so the
    segment's colors are re-applied after each one.

    A line wider than COLUMNS is cut inside a segment, which then ends with
    "…" and a closing arrow.
    """
    if not parts:
        return ""
    last = len(parts) - 1
    segs = []  # (background, same color as foreground, text color, body, soft arrow color)
    for i, part in enumerate(parts):
        if i < len(badges):
            bg, fg = badges[i]
            segs.append((bg, fg, "\033[30m", f"{BOLD} {part} ", ""))
            continue
        t = 0.0 if i < start else (i - start) / (last - start) if last > start else 1.0
        rgb = _lerp_rgb(palette["light"], palette["dark"], t)
        bg, fg, text = _truecolor_bg(*rgb), _truecolor_fg(*rgb), _truecolor_fg(*palette["text"])
        muted = _truecolor_fg(*_lift(rgb, BAND_MUTED_CONTRAST, palette["ink"]))
        empty = _truecolor_fg(*_lift(rgb, BAND_EMPTY_CONTRAST, palette["ink"]))
        part = part.replace(RESET, RESET + bg + text).replace(GRAY, empty).replace(DIM, muted)
        for code, color in palette["fg"].items():
            part = part.replace(code, _truecolor_fg(*color))
        segs.append((bg, fg, text, f" {part} ", muted))
    pieces = []  # (text, segment whose background its last cell is on)
    for i, (bg, fg, text, body, muted) in enumerate(segs):
        pieces.append((f"{bg}{text}{body}", i))
        nxt = segs[i + 1][0] if i < last else ""
        if nxt == bg:
            pieces.append((f"{RESET}{bg}{muted}{POWERLINE_SOFT_ARROW}", i))
        else:
            pieces.append((f"{RESET}{fg}{nxt}{POWERLINE_ARROW}", i + 1))
    line = "".join(piece for piece, _ in pieces) + RESET
    cols = _columns()
    if cols is None or _visible_width(line) <= cols:
        return line
    # Keep room for "…" and the closing arrow.
    out, room, seg = [], max(0, cols - 2), 0
    for piece, i in pieces:
        cut, over = _truncate_to_width(piece, room)
        if _visible_width(cut):
            out.append(cut)
            room -= _visible_width(cut)
            seg = i
        if over:
            break
    bg, fg, text = segs[seg][:3]
    return f"{''.join(out)}{bg}{text}…{RESET}{fg}{POWERLINE_ARROW}{RESET}"


def powerline_palette(choice):
    """Palette for --powerline-theme.

    auto follows Claude Code's theme setting when it names one (dark, light,
    or their -daltonized and -ansi forms). Claude Code's own "auto" follows
    the terminal, which this script cannot query, so it falls back to dark.
    """
    if choice == "auto":
        try:
            with open(CLAUDE_SETTINGS_FILE) as f:
                theme = str(json.load(f).get("theme") or "")
        except (OSError, json.JSONDecodeError, AttributeError):
            theme = ""
        choice = "light" if theme.startswith("light") else "dark"
    return POWERLINE_PALETTES[choice]


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


def update_accumulated_costs(session_id, session_cost=None, session_water=None):
    """Track per-session cost/water for the billing period.

    A None value leaves that metric's stored entry untouched (so e.g.
    --no-cost doesn't overwrite a synced cost with 0).
    Returns (billing_cost, billing_water).
    """
    state = _load_cost_state()

    # Check if billing period rolled over → re-sync from transcripts
    current_period = _billing_period_key()
    if state.get("billing_period") != current_period:
        try:
            sync_historical_costs()
            state = _load_cost_state()
        except Exception:
            state["billing_sessions"] = {}
            state["billing_water"] = {}
            state["billing_period"] = current_period

    billing_sessions = state.get("billing_sessions", {})
    billing_water = state.get("billing_water", {})
    if session_cost is not None:
        billing_sessions[session_id] = session_cost
    if session_water is not None:
        billing_water[session_id] = session_water
    state["billing_sessions"] = billing_sessions
    state["billing_water"] = billing_water

    _save_cost_state(state)

    return sum(billing_sessions.values()), sum(billing_water.values())


# ── Historical transcript sync ───────────────────────────────────────
TRANSCRIPT_DIR = os.path.expanduser("~/.claude/projects")
LITELLM_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"


def _pricing_cache_fresh():
    """True if the pricing cache exists and is within its 24h TTL (no network)."""
    try:
        with open(PRICING_CACHE_FILE) as f:
            cache = json.load(f)
        return (time.time() - cache.get("_cached_at", 0)) < PRICING_CACHE_TTL
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False


def _maybe_spawn_pricing_refresh():
    """Refresh pricing off the render path — never block on the network.

    The status line runs on every assistant turn, so it must not make a
    synchronous network call: the previous inline urllib fetch could stall a
    render for the socket timeout, and if the cache write ever failed it would
    retry on *every* render. Here we only stat local files, throttle attempts
    to once per hour, and hand the actual fetch to a detached child process
    that updates the cache for subsequent renders.
    """
    if _pricing_cache_fresh():
        return
    now = time.time()
    try:
        if now - os.path.getmtime(PRICING_REFRESH_STAMP_FILE) < PRICING_REFRESH_BACKOFF:
            return  # attempted recently — back off whether or not it succeeded
    except OSError:
        pass  # no stamp yet → proceed
    try:
        os.makedirs(os.path.dirname(PRICING_REFRESH_STAMP_FILE), exist_ok=True)
        with open(PRICING_REFRESH_STAMP_FILE, "w") as f:
            f.write(str(now))
    except OSError:
        pass
    try:
        subprocess.Popen(
            [sys.executable, "-m", "claude_counter.statusline", "--refresh-pricing"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        pass


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
        "fable": "claude-fable-5-1",
        "opus": "claude-opus-5-5",
        "sonnet": "claude-sonnet-5-5",
        "haiku": "claude-haiku-5-5",
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


def _estimate_water_from_usage(usage, model_str):
    """Calculate water from a single assistant message's usage dict."""
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    # Transcript usage reports plain input separately from cache tokens,
    # unlike the statusline's total_input which includes them.
    total_input = input_tokens + cache_read + cache_creation
    return estimate_water_liters(model_str, total_input, output_tokens, cache_read, cache_creation)


def sync_historical_costs():
    """Scan transcript files and backfill cost state.

    Returns (sessions_found, total_cost, total_water).
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

    # Sum costs/water per session from deduplicated requests
    session_costs = {}
    session_water = {}
    for req in requests.values():
        sid = req["sessionId"]
        cost = _estimate_cost_from_usage(req["usage"], req["model"])
        session_costs[sid] = session_costs.get(sid, 0.0) + cost
        water = _estimate_water_from_usage(req["usage"], req["model"])
        session_water[sid] = session_water.get(sid, 0.0) + water

    # Now bucket sessions into windows based on their latest timestamp
    state = _load_cost_state()

    five_hour_sessions = {}
    seven_day_sessions = {}
    billing_sessions = {}
    billing_water = {}

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
            billing_water[sid] = session_water.get(sid, 0.0)
        if ts_epoch >= seven_day_cutoff:
            seven_day_sessions[sid] = cost
        if ts_epoch >= five_hour_cutoff:
            five_hour_sessions[sid] = cost

    # Preserve resets_at from existing state (sync doesn't know these)
    state["five_hour_sessions"] = five_hour_sessions
    state["seven_day_sessions"] = seven_day_sessions
    state["billing_sessions"] = billing_sessions
    state["billing_water"] = billing_water
    state["billing_period"] = billing_period
    state["synced_at"] = time.time()

    _save_cost_state(state)

    total = sum(billing_sessions.values())
    return len(session_costs), total, sum(billing_water.values())



def read_effort_state():
    """Resolve the active reasoning effort for display.

    Returns (level_index, fast):
      level_index — 0..len(EFFORT_LEVELS)-1, or None when effort is default/off.
      fast        — True when fastMode is enabled.

    Precedence mirrors Claude Code's own resolver (q87): ultracode wins, then
    the applied per-turn effort (CLAUDE_EFFORT env, which can be "max" and
    reflects session overrides), then the persisted `effortLevel` default.
    """
    settings = {}
    try:
        with open(CLAUDE_SETTINGS_FILE, "r") as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        settings = {}

    fast = settings.get("fastMode") is True

    if settings.get("ultracode") is True:
        return EFFORT_LEVELS.index("ultracode"), fast

    raw = os.environ.get("CLAUDE_EFFORT") or settings.get("effortLevel") or ""
    raw = str(raw).strip().lower()
    raw = {"med": "medium"}.get(raw, raw)  # Claude Code's alias (H87)
    if raw in EFFORT_LEVELS and raw != "ultracode":
        return EFFORT_LEVELS.index(raw), fast
    return None, fast


# ── Main ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Claude Counter statusline")
    parser.add_argument(
        "--style",
        choices=["text", "bar", "ball", "capped", "dots", "filled", "off"],
        default="dots",
        help="Progress bar style, 'off' hides bars (default: dots)",
    )
    parser.add_argument(
        "--powerline", action=argparse.BooleanOptionalAction, default=True,
        help="Join segments as a powerline ribbon, which needs a Nerd Font "
             "or a terminal that draws U+E0B0 (default: on)",
    )
    parser.add_argument(
        "--powerline-theme", choices=["auto", "dark", "light"], default="auto",
        help="Ribbon colors for a dark or light terminal; auto follows Claude "
             "Code's theme setting when it names one, else dark (default: auto)",
    )
    parser.add_argument(
        "--separator", type=str, default=None,
        help="Separator character with --no-powerline (default: matches bar style)",
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
        "--no-5h", action="store_true",
        help="Disable 5-hour session limit segment",
    )
    parser.add_argument(
        "--hide-absent-5h", action=argparse.BooleanOptionalAction, default=True,
        help="Hide the 5-hour segment when Claude Code reports no 5-hour "
             "window, as for Ultra accounts; --no-hide-absent-5h shows 5h ∞ "
             "(default: on)",
    )
    parser.add_argument(
        "--no-7d", action="store_true",
        help="Disable 7-day weekly limit segment",
    )
    parser.add_argument(
        "--percent", action=argparse.BooleanOptionalAction, default=True,
        help="Show usage percentages (default: on)",
    )
    parser.add_argument(
        "--pct-color", action=argparse.BooleanOptionalAction, default=True,
        help="Color percentages green → orange → red (default: on)",
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
        "--no-water", action="store_true",
        help="Disable estimated water footprint display",
    )
    parser.add_argument(
        "--sync", action="store_true",
        help="Scan historical transcripts to backfill cost data, then exit",
    )
    parser.add_argument(
        # Internal: invoked as a detached child to refresh pricing off the
        # render path. Not meant to be called by users.
        "--refresh-pricing", action="store_true", help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--billing-day", type=int, default=None,
        help="Day of month billing resets (default: 1)",
    )
    parser.add_argument(
        "--effort-icons", default="arrows",
        help="Effort indicator preset (arrows, circles, bubbles, style) or custom "
             "icons comma-separated, one per tier low→ultracode "
             "(e.g. '○,◐,●,◉,◈,✦'); fewer icons clamp to the last",
    )
    args = parser.parse_args()

    # Override global BILLING_DAY if specified
    if args.billing_day is not None:
        global BILLING_DAY
        BILLING_DAY = args.billing_day

    # ── Sync mode (standalone) ────────────────────────────────────
    if args.sync:
        print("Updating pricing from LiteLLM…", file=sys.stderr)
        if fetch_and_update_pricing(force=True):
            print(f"  Pricing updated: {dict(API_PRICING)}", file=sys.stderr)
        else:
            print("  Using cached pricing (fetch failed or unchanged)", file=sys.stderr)
        print(f"Scanning transcripts in {TRANSCRIPT_DIR}…", file=sys.stderr)
        sessions, total, water = sync_historical_costs()
        print(
            f"Done: {sessions} sessions, ~{fmt_cost(total)} / {WATER_ICON}{fmt_water(water)} billing period total",
            file=sys.stderr,
        )
        return

    # ── Pricing refresh worker (detached child, no statusline output) ──
    if args.refresh_pricing:
        fetch_and_update_pricing(force=True)
        return

    # Auto-refresh pricing if cache is stale (24h TTL) — off the render path,
    # so a slow or failing network never blocks/garbles the status line.
    if not args.no_cost:
        _maybe_spawn_pricing_refresh()

    sep_char = args.separator or STYLE_SEPARATORS.get(args.style, "·")
    sep = f" {GRAY}{sep_char}{RESET} "
    if args.powerline:
        global PCT_COLOR_STOPS, FRAC_BLEND_RGB
        palette = powerline_palette(args.powerline_theme)
        PCT_COLOR_STOPS, FRAC_BLEND_RGB = palette["pct"], palette["frac"]
        # Bars and their partial cell use the palette's colors on the band.
        _COLOR_RGB.update(blue=palette["fg"][BLUE], yellow=palette["fg"][YELLOW], red=palette["fg"][RED])

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
    # Session name from /rename or --name, else the AI-generated title
    session_name = _sanitize(data.get("session_name"))
    git_part = ""
    if args.git and cwd:
        branch = get_git_branch(cwd)
        if branch:
            worktree_name, repo_name = get_git_worktree(cwd)
            # In a worktree: show repo name as dir
            if worktree_name and repo_name:
                dir_name = repo_name
            # A worktree folder is named <repo>.<branch> with "/" as "-" (worktrunk),
            # so its branch shows only when it differs or no session name names the task.
            if branch == "HEAD":
                git_part = f"{ORANGE} {get_git_short_sha(cwd) or branch}{RESET}"
            elif not worktree_name:
                git_part = f"{DIM} {branch}{RESET}"
            elif not worktree_name.endswith(branch.replace("/", "-")):
                git_part = f"{ORANGE} {branch}{RESET}"
            elif not session_name:
                git_part = f"{DIM} {branch}{RESET}"
    badges = []
    if dir_name and args.powerline:
        parts.append(dir_name)
        badges.append(DIR_BADGE)
        if session_name:
            parts.append(session_name)
            badges.append(SESSION_BADGE)
    elif dir_name:
        badge = f"\033[1;7;96m {dir_name} {RESET}"
        if session_name:
            badge += f" \033[1;7;95m {session_name} {RESET}"
        parts.append(badge)
    if git_part:
        # The space after git_part's color pads it next to a separator; a
        # powerline segment brings its own padding.
        parts.append(git_part.replace(" ", "", 1) if args.powerline else git_part)
    band_start = len(parts)  # lightest step: the model, or what follows if it is missing

    # ── Model + reasoning effort ────────────────────────────────
    model_name = _sanitize(model_data.get("display_name") or "")
    if model_name:
        effort_indicator = ""
        idx, fast = read_effort_state()
        if idx is not None:
            color = EFFORT_COLORS[idx]
            preset = args.effort_icons
            n_levels = len(EFFORT_LEVELS)
            if preset == "style":
                filled, empty = BAR_STYLES.get(args.style, ("●", "○"))[:2]
                n = idx + 1
                glyph = f"{filled * n}{DIM}{empty * (n_levels - n)}"
            else:
                glyphs = EFFORT_PRESETS.get(preset)
                if glyphs is None:
                    custom = [g for g in preset.split(",") if g]
                    glyphs = tuple(custom) if custom else EFFORT_PRESETS["arrows"]
                glyph = glyphs[min(idx, len(glyphs) - 1)]  # clamp: never blank
            fast_suffix = f"{FAST_COLOR}{FAST_ICON}{RESET}" if fast else ""
            effort_indicator = f"{color}{glyph}{RESET}{fast_suffix} "
        parts.append(f"{effort_indicator}{MAGENTA}{model_name}{RESET}")

    # ── Token count + progress bar + cache (grouped) ──────────────
    total_input = ctx.get("total_input_tokens") or 0
    total_output = ctx.get("total_output_tokens") or 0
    context_size = ctx.get("context_window_size") or 200_000
    used_pct = ctx.get("used_percentage")

    if used_pct is None and context_size > 0:
        used_pct = (total_input / context_size) * 100
    used_pct = used_pct or 0

    total_tokens = total_input + total_output
    pct_str = fmt_pct(used_pct, args.pct_color)

    # Cache info (appended to token segment, no separator)
    current = ctx.get("current_usage") or {}
    cache_read = current.get("cache_read_input_tokens") or 0
    cache_creation = current.get("cache_creation_input_tokens") or 0

    # Estimated API cost (grouped with token bar, no separator)
    cost_str = ""
    session_api_cost = 0.0
    if not args.no_cost:
        session_api_cost = estimate_api_cost(
            model_name, total_input, total_output, cache_read, cache_creation,
        )
        if session_api_cost > 0:
            cost_str = f" {DIM}~{fmt_cost(session_api_cost)}{RESET}"

    # Estimated water footprint (grouped with token bar, no separator)
    water_str = ""
    session_water = 0.0
    if not args.no_water:
        session_water = estimate_water_liters(
            model_name, total_input, total_output, cache_read, cache_creation,
        )
        if session_water > 0:
            water_str = f" {DIM}{WATER_ICON}{fmt_water(session_water)}{RESET}"

    if context_size >= 1_000_000:
        ctx_size_label = f"{context_size // 1_000_000}M"
    elif context_size >= 1_000:
        ctx_size_label = f"{context_size // 1_000}k"
    else:
        ctx_size_label = str(context_size)
    pct_part = f" {pct_str}/{ctx_size_label}" if args.percent else ""
    if args.style == "text":
        parts.append(f"{fmt_label('ctx')} ~{fmt_tokens(total_tokens)}{pct_part}{cost_str}{water_str}")
    elif args.style == "off":
        parts.append(f"{fmt_label('ctx')}{pct_part}{cost_str}{water_str}")
    else:
        bar = progress_bar(used_pct, args.style)
        parts.append(f"{fmt_label('ctx')} {bar}{pct_part}{cost_str}{water_str}")

    # ── Rate limit usage (session + weekly) ─────────────────────
    # Read from native rate_limits field (Claude Code ≥2.1.80)
    billing_cost = 0.0
    billing_water = 0.0

    rate_limits = data.get("rate_limits") or {}
    five_hour = rate_limits.get("five_hour") or {}
    seven_day = rate_limits.get("seven_day") or {}

    # Accumulate billing cost/water (independent of rate_limits presence)
    session_id = data.get("session_id") or ""
    cost_upd = session_api_cost if not args.no_cost and session_api_cost > 0 else None
    water_upd = session_water if not args.no_water and session_water > 0 else None
    if session_id and (cost_upd is not None or water_upd is not None):
        billing_cost, billing_water = update_accumulated_costs(session_id, cost_upd, water_upd)

    if five_hour or seven_day:
        session_pct = five_hour.get("used_percentage", 0)
        session_reset = five_hour.get("resets_at", "")
        weekly_pct = seven_day.get("used_percentage", 0)
        weekly_reset = seven_day.get("resets_at", "")

        # Usage bars
        if not args.no_usage:
            # Ultra accounts have no 5-hour limit, so Claude Code sends no
            # five_hour window. It also drops the window between its reset
            # and the next API response.
            if not five_hour:
                if not args.no_5h and not args.hide_absent_5h:
                    parts.append(f"{fmt_label('5h')} ∞")
            elif session_pct is not None and not args.no_5h:
                parts.append(usage_segment(
                    "5h", session_pct, session_reset, args.style,
                    show_pct=args.percent, color=args.pct_color,
                ))
            if seven_day and weekly_pct is not None and not args.no_7d:
                parts.append(usage_segment(
                    "7d", weekly_pct, weekly_reset, args.style,
                    show_pct=args.percent, color=args.pct_color,
                ))

    # ── Billing period totals (cost + water) ──────────────────
    if not args.no_total:
        totals = []
        if not args.no_cost and billing_cost > 0:
            totals.append(f"~{fmt_cost(billing_cost)}/mo")
        if not args.no_water and billing_water > 0:
            totals.append(f"{WATER_ICON}{fmt_water(billing_water)}/mo")
        if totals:
            parts.append(f"{DIM}{' '.join(totals)}{RESET}")

    if args.powerline:
        line = powerline_join(parts, badges, band_start, palette)
    else:
        line = sep.join(parts)
    print(_bound_to_columns(line))


if __name__ == "__main__":
    main()
