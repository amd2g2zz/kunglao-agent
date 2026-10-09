#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_rl_visuals.py — regenerate the README learning-loop visuals.

Renders the four animated GIFs plus the static approach-comparison SVG that
the README embeds, matching the terminal palette of the showcase SVGs.
Committed assets are reproducible: re-run this script and commit the diff.

Usage:
  uv run python scripts/render_rl_visuals.py --out docs/assets
  uv run python scripts/render_rl_visuals.py --out docs/assets --only rl-loop
  uv run python scripts/render_rl_visuals.py --only comparison

Outputs (960x540 GIFs, 960x720 SVG):
  rl-loop.gif             the act-level learning loop, three cycles
  rl-features.gif         feature-keyed states, one vocabulary two rankings
  rl-death-discovery.gif  arm death, park, and the discovery layer
  rl-pricing.gif          the oracle pricing an honest vs a fabricated act
  approach-comparison.svg fixed-logic approaches vs a learned control law

Determinism: every draw uses one seeded RNG, so a run is repeatable on the
same machine; byte-identical output across Pillow versions is not required.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as _pil_exc:  # degrade: explicit refusal, never silent
    sys.stderr.write(
        "render_rl_visuals: Pillow is required (declared dependency "
        f"'pillow'); import failed: {_pil_exc}\n")
    raise SystemExit(2) from _pil_exc

# ---------------------------------------------------------------------------
# palette — mirrors the showcase SVG pair (terminal dark, Tokyo-Night accents)
# ---------------------------------------------------------------------------
BG = "#11131a"
PANEL = "#181b26"
PANEL_EDGE = "#2a2f45"
PANEL_HEAD = "#222739"
TITLE_BAR = "#232839"
BAR_GRAD_TOP = "#2a2f3e"
BAR_GRAD_BOT = "#1f2330"
ACTIVE_BOX = "#1f2337"
TRACK = "#10131f"
DOT_RED = "#ff5f57"
DOT_YELLOW = "#febc2e"
DOT_GREEN = "#28c840"
TEXT = "#c0caf5"
TEXT_DIM = "#a9b1d6"
TEXT_MUTED = "#8b93a7"
TEXT_FAINT = "#565f89"
BLUE = "#7aa2f7"
GREEN = "#9ece6a"
CYAN = "#73daca"
AMBER = "#ff9e64"
PURPLE = "#bb9af7"
RED = "#f7768e"
GLOW = "#e0af68"

W, H = 960, 540
FRAME_MS = 100
SEED = 1971
MAX_GIF_BYTES = 2_500_000

FONT_CANDIDATES = (
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Menlo.ttf",
    "/System/Library/Fonts/Monaco.ttf",
    "/System/Library/Fonts/SFNSMono.ttf",
)
_FONTS: dict = {}
_FONT_FALLBACK_NOTED = False


# ---------------------------------------------------------------------------
# small drawing helpers
# ---------------------------------------------------------------------------
def load_font(size: int):
    """Menlo/SF Mono via the truetype loader; bitmap default as fallback."""
    global _FONT_FALLBACK_NOTED
    if size in _FONTS:
        return _FONTS[size]
    font = None
    for path in FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
        if not _FONT_FALLBACK_NOTED:
            sys.stderr.write(
                "render_rl_visuals: no monospace ttf found, "
                "using the PIL default bitmap font\n"
            )
            _FONT_FALLBACK_NOTED = True
    _FONTS[size] = font
    return font


def text(d, xy, s, fill, size=13, anchor=None):
    """Draw monospace text; manual anchoring for bitmap-font fallback."""
    font = load_font(size)
    if anchor is not None and hasattr(font, "getbbox"):
        d.text(xy, s, font=font, fill=fill, anchor=anchor)
        return
    if anchor in (None, "la"):
        d.text(xy, s, font=font, fill=fill)
        return
    box = d.textbbox((0, 0), s, font=font)
    tx, ty = xy
    if anchor[0] == "m":
        tx -= (box[2] - box[0]) // 2
    elif anchor[0] == "r":
        tx -= box[2] - box[0]
    if anchor[1] == "m":
        ty -= (box[3] - box[1]) // 2
    d.text((tx, ty), s, font=font, fill=fill)


def new_canvas(title):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 17], fill=BAR_GRAD_TOP)
    d.rectangle([0, 17, W, 35], fill=BAR_GRAD_BOT)
    for cx, color in ((22, DOT_RED), (42, DOT_YELLOW), (62, DOT_GREEN)):
        d.ellipse([cx - 6, 12, cx + 6, 24], fill=color)
    text(d, (W // 2, 24), title, TEXT_MUTED, 13, anchor="mm")
    return img, d


def panel(d, box, title, title_color=BLUE):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=8, fill=PANEL, outline=PANEL_EDGE, width=1)
    d.rounded_rectangle([x0, y0, x1, y0 + 26], radius=8, fill=PANEL_HEAD)
    d.rectangle([x0, y0 + 14, x1, y0 + 26], fill=PANEL_HEAD)
    text(d, (x0 + 16, y0 + 13), title, title_color, 13, anchor="lm")


def chip(d, center, label, color, size=12, fill=None):
    font = load_font(size)
    tw = d.textlength(label, font=font)
    x, y = center
    box = [x - tw / 2 - 8, y - 11, x + tw / 2 + 8, y + 11]
    d.rounded_rectangle(box, radius=6, fill=fill or PANEL, outline=color,
                        width=1)
    text(d, (x, y), label, color, size, anchor="mm")


def arrow_down(d, x, y0, y1, color=TEXT_FAINT):
    d.line([x, y0, x, y1 - 5], fill=color, width=2)
    d.polygon([(x - 4, y1 - 6), (x + 4, y1 - 6), (x, y1)], fill=color)


def lerp(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, t))


def stamp(d, center, label, color, size=16):
    """Rubber-stamp box: double border around a short verdict label."""
    font = load_font(size)
    tw = d.textlength(label, font=font)
    x, y = center
    box = [x - tw / 2 - 14, y - 16, x + tw / 2 + 14, y + 16]
    d.rounded_rectangle(box, radius=4, outline=color, width=2)
    d.rounded_rectangle([box[0] + 3, box[1] + 3, box[2] - 3, box[3] - 3],
                        radius=3, outline=color, width=1)
    text(d, (x, y), label, color, size, anchor="mm")


# ---------------------------------------------------------------------------
# gif assembly
# ---------------------------------------------------------------------------
def shared_palette(frames):
    """One adaptive 256-color palette across every frame (no flicker)."""
    strip = Image.new("RGB", (W, H * len(frames)))
    for i, frame in enumerate(frames):
        strip.paste(frame, (0, i * H))
    return strip.quantize(colors=256, method=Image.MEDIANCUT,
                          dither=Image.Dither.NONE)


def save_gif(frames, path):
    palette = shared_palette(frames)
    quanted = [f.quantize(palette=palette, dither=Image.Dither.NONE)
               for f in frames]
    quanted[0].save(
        path, save_all=True, append_images=quanted[1:],
        duration=FRAME_MS, loop=0, optimize=True, disposal=2,
    )
    return path.stat().st_size


# ---------------------------------------------------------------------------
# rl-loop — the act-level learning loop, three cycles
# ---------------------------------------------------------------------------
ARMS = (
    ("static-decompile", 6.0, 2.5),
    ("kdf-chain", 3.0, 3.5),
    ("dynamic-trace", 2.0, 4.0),
    ("obfuscation-peeling", 1.5, 3.5),
)
CYCLES = (
    {"winner": 0, "verdict": "PASS", "dphi": 0.34, "loser": 2},
    {"winner": 2, "verdict": "PASS", "dphi": 0.34, "loser": 3},
    {"winner": 0, "verdict": "FAIL", "dphi": 0.00, "loser": 1},
)
ALPHA_W = 2.0
LAM = 0.25
COST = 0.28
SPINE_STEPS = ("STATE", "THOMPSON DRAW", "DISPATCH ACT", "ORACLE VERDICT",
               "LEDGER ROW")
SPINE_COLORS = (BLUE, PURPLE, AMBER, CYAN, GREEN)


def beta_stats(a, b):
    total = a + b
    mean = a / total
    sd = (a * b / (total * total * (total + 1.0))) ** 0.5
    return mean, sd


def cycle_post(counts, cyc):
    """Posterior counts after cycle `cyc` settles (winner +1, loser decays)."""
    post = [tuple(row) for row in counts]
    spec = CYCLES[cyc]
    name, wa, wb = post[spec["winner"]]
    if spec["verdict"] == "PASS":
        post[spec["winner"]] = (name, wa + 1.0, wb)
        lname, la, lb = post[spec["loser"]]
        post[spec["loser"]] = (lname, la, lb + 0.5)
    else:
        post[spec["winner"]] = (name, wa, wb + 1.0)
    return post


def draw_samples(cyc):
    """Seeded Thompson draws; the designated winner always shows the max."""
    rng = random.Random(SEED + cyc * 31)
    samples = [rng.betavariate(a, b) for _, a, b in ARMS]
    samples[CYCLES[cyc]["winner"]] = max(samples)
    return samples


def loop_arms(d, counts, pre, post, t_blend, winner, show_draw, samples):
    for i, (name, a, b) in enumerate(counts):
        a = lerp(pre[i][1], post[i][1], t_blend)
        b = lerp(pre[i][2], post[i][2], t_blend)
        mean, sd = beta_stats(a, b)
        y = 104 + i * 100
        glow = show_draw and i == winner
        text(d, (40, y), name, GLOW if glow else CYAN, 13)
        text(d, (340, y), f"mean {mean:.2f}", TEXT_FAINT, 12, anchor="ra")
        d.rounded_rectangle([40, y + 12, 340, y + 30], radius=4, fill=TRACK,
                            outline=PANEL_EDGE)
        bw = mean * 292
        if bw >= 6:
            d.rounded_rectangle([40, y + 12, 40 + bw, y + 30], radius=4,
                                fill=GLOW if glow else BLUE)
        x_lo = 40 + max(0.0, mean - 2 * sd) * 292
        x_hi = 40 + min(1.0, mean + 2 * sd) * 292
        d.line([x_lo, y + 21, x_hi, y + 21], fill=GLOW if glow else TEXT_FAINT,
               width=2)
        for cap_x in (x_lo, x_hi):
            d.line([cap_x, y + 16, cap_x, y + 26], fill=TEXT_FAINT, width=2)
        text(d, (40, y + 42), f"α {a:.1f}   β {b:.1f}",
             TEXT_FAINT, 11)
        if show_draw:
            text(d, (40, y + 62), f"draw {samples[i]:.2f}",
                 AMBER if glow else TEXT_FAINT, 12)


def loop_spine(d, phase):
    for i, label in enumerate(SPINE_STEPS):
        y = 100 + i * 74
        box = [396, y, 604, y + 46]
        active = i == phase
        edge = SPINE_COLORS[i] if active else PANEL_EDGE
        d.rounded_rectangle(box, radius=6, fill=ACTIVE_BOX if active else PANEL,
                            outline=edge, width=2)
        text(d, (500, y + 23), label, TEXT if active else TEXT_FAINT, 13,
             anchor="mm")
        if i < 4:
            arrow_down(d, 500, y + 46, y + 68,
                       SPINE_COLORS[i] if active else TEXT_FAINT)


def loop_center_card(d, f, act_name, verdict, rows):
    v_color = GREEN if verdict == "PASS" else RED
    if 4 <= f <= 7:
        d.rounded_rectangle([396, 464, 604, 514], radius=6, fill=ACTIVE_BOX,
                            outline=SPINE_COLORS[2], width=2)
        text(d, (500, 478), f"act → {act_name}", TEXT, 12, anchor="mm")
        text(d, (500, 498), "probe replay-pair · budget bucket B",
             TEXT_FAINT, 11, anchor="mm")
    elif 8 <= f <= 12:
        stamp(d, (500, 489), f"ORACLE: {verdict}", v_color, 14)
    elif 13 <= f <= 16:
        d.rounded_rectangle([396, 464, 604, 514], radius=6, fill=ACTIVE_BOX,
                            outline=SPINE_COLORS[4], width=2)
        text(d, (500, 478), f"ledger row {rows}", SPINE_COLORS[4], 12,
             anchor="mm")
        text(d, (500, 498), f"settle {act_name} → posterior", TEXT_FAINT,
             11, anchor="mm")


def loop_reward(d, spec, reveal_t):
    panel(d, (628, 56, 936, 516), "reward")
    text(d, (644, 118), "r = ΔΦ·α − λ·cost",
         TEXT, 16)
    dphi = spec["dphi"] * reveal_t
    r = dphi * ALPHA_W - LAM * COST
    text(d, (644, 156), f"ΔΦ  {dphi:.2f}", GREEN, 13)
    text(d, (644, 180), f"α  {ALPHA_W:.2f}", TEXT_FAINT, 13)
    text(d, (644, 204),
         f"λ  {LAM:.2f} × cost {COST:.2f} = {LAM * COST:.2f}",
         TEXT_FAINT, 13)
    r_color = GREEN if r >= 0 else RED
    text(d, (644, 254), f"r = {r:+.2f}", r_color, 24)
    mid = 782
    d.line([644, 306, 920, 306], fill=PANEL_EDGE, width=2)
    bar_len = min(abs(r), 0.8) * 150
    if reveal_t > 0.05 and bar_len > 1:
        bx1 = mid + bar_len if r >= 0 else mid
        bx0 = mid if r >= 0 else mid - bar_len
        d.rounded_rectangle([bx0, 296, bx1, 316], radius=3, fill=r_color)
    text(d, (644, 356), "oracle verdict is the only currency", TEXT_FAINT, 11)
    text(d, (644, 380), "every row lands append-only", TEXT_FAINT, 11)
    text(d, (644, 404), "discount γ 0.90 per tick", TEXT_FAINT, 11)
    text(d, (644, 452), "posterior sharpens as", TEXT_FAINT, 11)
    text(d, (644, 472), "whiskers narrow (±2σ)", TEXT_FAINT, 11)



# ---------------------------------------------------------------------------
# The four GIF scenes: story-first, jargon-free. A viewer who has never
# heard of reinforcement learning should get each point from one frame.
# ---------------------------------------------------------------------------



def _card(d, box, title, lines_, edge=PANEL_EDGE, title_color=TEXT):
    d.rounded_rectangle(box, radius=10, fill=PANEL, outline=edge, width=2)
    text(d, (box[0] + 20, box[1] + 30), title, title_color, 18, anchor="lm")
    yy = box[1] + 66
    for ln in lines_:
        text(d, (box[0] + 20, yy), ln, TEXT_FAINT, 14, anchor="lm")
        yy += 26


def _method_chip(d, cx, cy, label, state, sub=None):
    state_styles = {
        "idle": (PANEL_EDGE, TEXT), "pick": (GREEN, GREEN),
        "done": (GREEN, GREEN), "dead": (TEXT_FAINT, TEXT_FAINT), "new": (PURPLE, PURPLE),
    }
    edge, fg = state_styles[state]
    font = load_font(17)
    tw = d.textlength(label, font=font)
    box = [cx - tw / 2 - 14, cy - 17, cx + tw / 2 + 14, cy + 17]
    d.rounded_rectangle(box, radius=8, fill=PANEL, outline=edge, width=2)
    text(d, (cx, cy), label, fg, 17, anchor="mm")
    if sub:
        text(d, (cx, cy + 28), sub, AMBER if state == "pick" else TEXT_FAINT, 14,
             anchor="mm")


def _cost_meter(d, x, y, units, label):
    text(d, (x, y), label, TEXT_FAINT, 15, anchor="lm")
    for i in range(4):
        on = i < units
        d.rounded_rectangle([x + 160 + i * 36, y - 10, x + 186 + i * 36,
                             y + 10], radius=4,
                            fill=(AMBER if on else PANEL),
                            outline=PANEL_EDGE)
    text(d, (x + 330, y), f"{units} steps", TEXT, 15, anchor="lm")


def render_rl_loop():
    """Story: task 1 pays full price; the loop remembers; task 2 of the
    same kind runs cheaper."""
    frames = []
    for i in range(14):                    # beat 1: first task, has to explore
        img, d = new_canvas("the loop learns - one task at a time")
        _card(d, [40, 60, 420, 190], "TASK 1: hidden sign algorithm",
              ["obfuscated js bundle", "no notes yet - has to explore"])
        text(d, (230, 226), "which method first? the loop picks:",
             TEXT_FAINT, 14, anchor="mm")
        _method_chip(d, 230, 280, "read the code",
                     "pick" if i >= 7 else "idle")
        _method_chip(d, 230, 350, "run it and watch", "idle")
        _method_chip(d, 230, 420, "guess constants", "idle")
        _card(d, [560, 60, 920, 190], "THE CHECKER", ["re-runs everything,",
              "accepts only proof"])
        if i >= 11:
            text(d, (740, 240), "working...", AMBER, 16, anchor="mm")
        frames.append(img)
    for i in range(14):                    # beat 2: verified, note taken
        img, d = new_canvas("the loop learns - one task at a time")
        _card(d, [40, 60, 420, 190], "TASK 1: hidden sign algorithm",
              ["solved"], edge=GREEN, title_color=GREEN)
        _method_chip(d, 230, 280, "read the code", "done")
        _method_chip(d, 230, 350, "run it and watch", "idle")
        _method_chip(d, 230, 420, "guess constants", "idle")
        d.rounded_rectangle([560, 60, 920, 190], radius=10, fill=PANEL,
                            outline=GREEN, width=2)
        stamp(d, (740, 118), "VERIFIED", GREEN)
        text(d, (740, 158), "the answer replays byte-exact", TEXT_FAINT, 13,
             anchor="mm")
        mem_y = 300 + min(i * 8, 60)
        d.rounded_rectangle([560, mem_y, 920, mem_y + 96], radius=10,
                            fill=PANEL, outline=BLUE, width=2)
        text(d, (580, mem_y + 30), "NOTES for targets like this", BLUE, 14,
             anchor="lm")
        text(d, (580, mem_y + 62), "reading the code worked", TEXT, 16,
             anchor="lm")
        frames.append(img)
    for i in range(14):                    # beat 3: same kind, cheaper
        img, d = new_canvas("the loop learns - one task at a time")
        _card(d, [40, 60, 420, 190], "TASK 2: the same kind of target",
              ["a new sample, same family",
               "the loop opens from its notes"], edge=BLUE)
        _method_chip(d, 230, 280, "read the code", "pick",
                     sub="notes: start here")
        _method_chip(d, 230, 350, "run it and watch", "idle")
        _method_chip(d, 230, 420, "guess constants", "idle")
        d.rounded_rectangle([560, 60, 920, 190], radius=10, fill=PANEL,
                            outline=GREEN, width=2)
        stamp(d, (740, 118), "VERIFIED", GREEN)
        _cost_meter(d, 560, 240, 3, "task 1")
        _cost_meter(d, 560, 285, 1, "task 2")
        text(d, (740, 350), "the second one ran cheaper -", GREEN, 15,
             anchor="mm")
        text(d, (740, 376), "the loop remembered.", GREEN, 15, anchor="mm")
        frames.append(img)
    return frames


def render_rl_features():
    """Story: two targets that look alike open differently - the notes
    are kept per kind of target."""
    frames = []
    for i in range(30):
        img, d = new_canvas("different targets - different first moves")
        rev = min(1.0, i / 12.0)
        _card(d, [40, 60, 460, 200], "TARGET A: plain script",
              ["code reads normally", "no packing", "no traps"])
        _card(d, [500, 60, 920, 200], "TARGET B: hardened app",
              ["code is scrambled", "packed", "full of traps"])
        ay = lerp(216, 296, rev)
        by = lerp(216, 296, rev)
        d.line([250, 206, 250, ay], fill=BLUE, width=2)
        d.line([710, 206, 710, by], fill=PURPLE, width=2)
        text(d, (250, ay + 18), "what it looks like", TEXT_FAINT, 12, anchor="mm")
        text(d, (710, by + 18), "what it looks like", TEXT_FAINT, 12, anchor="mm")
        if rev >= 1.0:
            d.rounded_rectangle([60, 336, 440, 446], radius=10, fill=PANEL,
                                outline=BLUE, width=2)
            text(d, (80, 362), "NOTES for kind A", BLUE, 15, anchor="lm")
            text(d, (80, 394), "first move: read the code", TEXT, 16,
                 anchor="lm")
            text(d, (80, 422), "one cheap pass, done", TEXT_FAINT, 13, anchor="lm")
            d.rounded_rectangle([520, 336, 900, 446], radius=10, fill=PANEL,
                                outline=PURPLE, width=2)
            text(d, (540, 362), "NOTES for kind B", PURPLE, 15, anchor="lm")
            text(d, (540, 394), "first move: unpack, then watch it run",
                 TEXT, 16, anchor="lm")
            text(d, (540, 422), "reading it raw misleads", TEXT_FAINT, 13,
                 anchor="lm")
            text(d, (480, 486), "what works on one kind would mislead on "
                 "the other.", GREEN, 15, anchor="mm")
        frames.append(img)
    return frames


def render_rl_death_discovery():
    """Story: a method keeps failing, gets benched; when nothing works,
    a genuinely new idea gets a chance."""
    frames = []
    for i in range(40):
        img, d = new_canvas("dead ends get benched - new ideas get a chance")
        n_fail = 0
        for k, at in enumerate((5, 10, 15)):
            if i >= at:
                n_fail = k + 1
        state = "pick" if i < 5 else "dead"
        _method_chip(d, 250, 120, "guess the keys", state,
                     sub="benched - can come back" if i >= 5 else None)
        for k in range(n_fail):
            text(d, (370 + k * 44, 120), "X", RED, 24, anchor="mm")
        if 5 <= i < 22:
            text(d, (250, 192), "the loop stops spending on it", TEXT_FAINT, 14,
                 anchor="mm")
        if i >= 22:
            d.rounded_rectangle([40, 236, 920, 286], radius=10, fill=PANEL,
                                outline=AMBER, width=2)
            text(d, (60, 261), "nothing works - the loop tries to invent "
                 "a way in", AMBER, 15, anchor="lm")
            ny = lerp(336, 406, min(1.0, (i - 22) / 8.0))
            _method_chip(d, 250, ny, "follow the key setup", "new")
            if i >= 26:
                text(d, (520, ny), "really different from the failed "
                     "tries? YES", GREEN, 15, anchor="lm")
            if i >= 31:
                text(d, (520, ny + 28), "gets a chance", PURPLE, 15,
                     anchor="lm")
            if i >= 35:
                text(d, (520, ny + 56), "same thing renamed? refused.",
                     TEXT_FAINT, 13, anchor="lm")
        frames.append(img)
    return frames


def render_rl_pricing():
    """Story: two workers - one honest, one bluffing. The checker pays
    only for proof. Lying earns nothing."""
    frames = []
    for i in range(34):
        img, d = new_canvas("honesty is enforced - not asked for")
        ph = i / 33.0
        d.rounded_rectangle([40, 60, 460, 440], radius=10, fill=PANEL,
                            outline=PANEL_EDGE, width=2)
        text(d, (60, 92), "WORKER A", TEXT, 16, anchor="lm")
        text(d, (60, 126), "does the work, shows the receipts", TEXT_FAINT, 13,
             anchor="lm")
        text(d, (60, 174), "the checker re-runs everything", TEXT_FAINT, 13,
             anchor="lm")
        if ph > 0.35:
            stamp(d, (250, 226), "PASS", GREEN)
        if ph > 0.6:
            text(d, (60, 288), "real progress", TEXT, 15, anchor="lm")
            bw = int(200 * min(1.0, (ph - 0.6) / 0.4))
            d.rounded_rectangle([60, 308, 260, 330], radius=4, fill=PANEL,
                                outline=PANEL_EDGE)
            d.rounded_rectangle([60, 308, 60 + bw, 330], radius=4, fill=GREEN)
            text(d, (60, 360), "+ earns credit", GREEN, 15, anchor="lm")
        d.rounded_rectangle([500, 60, 920, 440], radius=10, fill=PANEL,
                            outline=PANEL_EDGE, width=2)
        text(d, (520, 92), "WORKER B", TEXT, 16, anchor="lm")
        text(d, (520, 126), "claims done - nothing to re-run", TEXT_FAINT, 13,
             anchor="lm")
        text(d, (520, 174), "the checker re-runs everything", TEXT_FAINT, 13,
             anchor="lm")
        if ph > 0.35:
            stamp(d, (710, 226), "FAIL", RED)
        if ph > 0.6:
            text(d, (520, 288), "no progress", TEXT_FAINT, 15, anchor="lm")
            text(d, (520, 360), "- gets nothing, pays the cost", RED, 15,
                 anchor="lm")
            text(d, (520, 386), "(its own words never count as proof)", TEXT_FAINT,
                 13, anchor="lm")
        if ph >= 1.0:
            text(d, (480, 486), "credit is paid only for results the "
                 "checker can verify.", GREEN, 15, anchor="mm")
        frames.append(img)
    return frames


SVG_FONT = ("font-family=\"'SF Mono','Menlo','Cascadia Code',monospace\"")


def svg_box(x, y, w, h, label, edge="#2a2f45", lab_fill="#c0caf5"):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
        f'fill="#181b26" stroke="{edge}"/>'
        f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" font-size="12" '
        f'fill="{lab_fill}" text-anchor="middle">{label}</text>'
    )


def svg_arrow(x0, x1, y, color="#565f89", width=2):
    head = (f'<polygon points="{x1},{y - 4} {x1},{y + 4} {x1 + 7},{y}" '
            f'fill="{color}"/>')
    return (f'<line x1="{x0}" y1="{y}" x2="{x1 - 1}" y2="{y}" '
            f'stroke="{color}" stroke-width="{width}"/>{head}')


def svg_lane(y, label, label_color, note, note_color):
    return (
        f'<rect x="24" y="{y}" width="912" height="140" rx="8" '
        f'fill="#181b26" stroke="#2a2f45"/>'
        f'<text x="40" y="{y + 26}" font-size="13" fill="{label_color}">'
        f'{label}</text>'
        f'<text x="920" y="{y + 26}" font-size="11" fill="{note_color}" '
        f'text-anchor="end">{note}</text>'
    )


def svg_loop_back(x0, x1, y, color, label, width=2, label_fill=None):
    mid = (x0 + x1) / 2
    return (
        f'<path d="M {x1} {y + 16} L {x1} {y + 34} L {x0} {y + 34} '
        f'L {x0} {y + 22}" fill="none" stroke="{color}" '
        f'stroke-width="{width}"/>'
        f'<polygon points="{x0 - 4},{y + 23} {x0 + 4},{y + 23} {x0},{y + 15}" '
        f'fill="{color}"/>'
        f'<text x="{mid}" y="{y + 48}" font-size="11" '
        f'fill="{label_fill or color}" text-anchor="middle">{label}</text>'
    )


def render_comparison_svg():
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="720" '
        f'viewBox="0 0 960 720" {SVG_FONT}>',
        f'<rect width="960" height="720" rx="12" fill="{BG}"/>',
        f'<rect width="960" height="36" rx="12" fill="{TITLE_BAR}"/>',
        f'<circle cx="22" cy="18" r="6" fill="{DOT_RED}"/>',
        f'<circle cx="42" cy="18" r="6" fill="{DOT_YELLOW}"/>',
        f'<circle cx="62" cy="18" r="6" fill="{DOT_GREEN}"/>',
        f'<text x="480" y="23" font-size="13" fill="{TEXT_MUTED}" '
        f'text-anchor="middle">how four approaches decide</text>',
    ]
    y = 52
    parts.append(svg_lane(y, "Static knowledge routing", TEXT_FAINT,
                          "open chain, no feedback", TEXT_FAINT))
    parts.append(svg_box(48, y + 48, 170, 40, "methodology manual"))
    parts.append(svg_arrow(222, 264, y + 68))
    parts.append(svg_box(268, y + 48, 170, 40, "LLM improvises"))
    parts.append(svg_arrow(442, 484, y + 68))
    parts.append(svg_box(488, y + 48, 130, 40, "output"))
    y2 = y + 148
    parts.append(svg_lane(y2, "Bounded pipeline", TEXT_FAINT,
                          "rounds capped by design", TEXT_FAINT))
    parts.append(svg_box(48, y2 + 48, 140, 40, "fixed stages"))
    parts.append(svg_arrow(192, 230, y2 + 68))
    parts.append(svg_box(234, y2 + 48, 140, 40, "fixed gates"))
    parts.append(svg_arrow(378, 416, y2 + 68))
    parts.append(svg_box(420, y2 + 48, 160, 40, "bounded rounds"))
    parts.append(svg_arrow(584, 622, y2 + 68))
    parts.append(svg_box(626, y2 + 48, 120, 40, "output"))
    parts.append(svg_loop_back(490, 686, y2 + 68, TEXT_FAINT,
                               "loop is fixed, learns nothing"))
    y3 = y2 + 148
    parts.append(svg_lane(y3, "Single-verdict triage", TEXT_FAINT,
                          "narrow domain, one pass", TEXT_FAINT))
    parts.append(svg_box(48, y3 + 48, 130, 40, "target"))
    parts.append(svg_arrow(182, 216, y3 + 68))
    parts.append(svg_box(220, y3 + 48, 150, 40, "agent loop"))
    parts.append(svg_arrow(374, 408, y3 + 68))
    parts.append(svg_box(412, y3 + 48, 130, 40, "verdict"))
    parts.append(
        f'<text x="580" y="{y3 + 73}" font-size="11" fill="{TEXT_FAINT}">'
        f'nothing banks between runs</text>')
    y4 = y3 + 148
    parts.append(svg_lane(y4, "kunglao-agent (act-level RL controller)", GREEN,
                          "the loop measures itself", GREEN))
    parts.append(svg_box(48, y4 + 44, 90, 36, "task"))
    parts.append(svg_arrow(142, 176, y4 + 62))
    parts.append(svg_box(180, y4 + 44, 170, 36, "oracle derivation"))
    parts.append(svg_arrow(354, 388, y4 + 62))
    parts.append(svg_box(392, y4 + 44, 120, 36, "act loop", edge=BLUE))
    parts.append(svg_arrow(516, 550, y4 + 62))
    parts.append(svg_box(554, y4 + 44, 110, 36, "ledger"))
    parts.append(svg_arrow(668, 702, y4 + 62))
    parts.append(svg_box(706, y4 + 44, 180, 36, "posterior update", edge=BLUE))
    parts.append(svg_loop_back(452, 796, y4 + 62, GREEN,
                               "policy updates from its own measured history",
                               width=3, label_fill=GLOW))
    parts.append(
        f'<text x="480" y="706" font-size="13" fill="{TEXT}" '
        f'text-anchor="middle">The first three decide with fixed logic; '
        f'the fourth learns its control law.</text>')
    parts.append('</svg>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------
RENDERERS = {
    "rl-loop": ("rl-loop.gif", render_rl_loop),
    "rl-features": ("rl-features.gif", render_rl_features),
    "rl-death-discovery": ("rl-death-discovery.gif",
                           render_rl_death_discovery),
    "rl-pricing": ("rl-pricing.gif", render_rl_pricing),
    "comparison": ("approach-comparison.svg", None),
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="render the README learning-loop visuals")
    parser.add_argument("--out", default="docs/assets",
                        help="output directory (default: docs/assets)")
    parser.add_argument("--only", choices=sorted(RENDERERS), default=None,
                        help="render a single visual instead of all five")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = [args.only] if args.only else sorted(RENDERERS)
    for key in wanted:
        filename, renderer = RENDERERS[key]
        path = out_dir / filename
        if renderer is None:
            path.write_text(render_comparison_svg(), encoding="utf-8")
            print(f"{path}  svg  {path.stat().st_size} bytes")
            continue
        frames = renderer()
        size = save_gif(frames, path)
        flag = "" if size <= MAX_GIF_BYTES else "  OVER BUDGET"
        print(f"{path}  {len(frames)} frames  {size} bytes{flag}")
        if size > MAX_GIF_BYTES:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
