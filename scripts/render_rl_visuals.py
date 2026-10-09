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
        text(d, (340, y), f"mean {mean:.2f}", TEXT_DIM, 12, anchor="ra")
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
        text(d, (500, y + 23), label, TEXT if active else TEXT_DIM, 13,
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
             TEXT_DIM, 11, anchor="mm")
    elif 8 <= f <= 12:
        stamp(d, (500, 489), f"ORACLE: {verdict}", v_color, 14)
    elif 13 <= f <= 16:
        d.rounded_rectangle([396, 464, 604, 514], radius=6, fill=ACTIVE_BOX,
                            outline=SPINE_COLORS[4], width=2)
        text(d, (500, 478), f"ledger row {rows}", SPINE_COLORS[4], 12,
             anchor="mm")
        text(d, (500, 498), f"settle {act_name} → posterior", TEXT_DIM,
             11, anchor="mm")


def loop_reward(d, spec, reveal_t):
    panel(d, (628, 56, 936, 516), "reward")
    text(d, (644, 118), "r = ΔΦ·α − λ·cost",
         TEXT, 16)
    dphi = spec["dphi"] * reveal_t
    r = dphi * ALPHA_W - LAM * COST
    text(d, (644, 156), f"ΔΦ  {dphi:.2f}", GREEN, 13)
    text(d, (644, 180), f"α  {ALPHA_W:.2f}", TEXT_DIM, 13)
    text(d, (644, 204),
         f"λ  {LAM:.2f} × cost {COST:.2f} = {LAM * COST:.2f}",
         TEXT_DIM, 13)
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


def render_rl_loop():
    frames = []
    counts = [tuple(row) for row in ARMS]
    rows = 41
    for cyc in range(3):
        pre = list(counts)
        post = cycle_post(counts, cyc)
        spec = CYCLES[cyc]
        act_name = counts[spec["winner"]][0]
        samples = draw_samples(cyc)
        for f in range(20):
            img, d = new_canvas(
                "the learning loop — draw, dispatch, verdict, ledger")
            panel(d, (24, 56, 372, 516), "method arms · beta posterior")
            panel(d, (388, 56, 612, 448), "loop spine")
            phase = (1 if f <= 3 else 2 if f <= 7 else 3 if f <= 12 else 4)
            if f >= 17:
                phase = 0
            verdict = spec["verdict"] if f >= 8 else ""
            rows_now = rows + (1 if f >= 13 else 0)
            t_blend = 0.0 if f < 17 else (f - 16) / 3.0
            loop_arms(d, post, pre, post, t_blend, spec["winner"], f <= 3,
                      samples)
            loop_spine(d, phase)
            loop_center_card(d, f, act_name, verdict, rows_now)
            loop_reward(d, spec, 1.0 if f >= 8 else f / 12.0)
            if f >= 17:
                text(d, (500, 482), "posterior update → next state",
                     SPINE_COLORS[0], 12, anchor="mm")
            text(d, (W // 2, 528),
                 "frozen model, external policy — every number traces to "
                 "a ledger row", TEXT_FAINT, 11, anchor="mm")
            frames.append(img)
        counts = post
        rows += 1
    return frames


# ---------------------------------------------------------------------------
# rl-features — feature-keyed states
# ---------------------------------------------------------------------------
TARGETS = (
    ("plain-js-bundle", ("ent:low", "fc:sparse", "die:none"), BLUE),
    ("hardened-apk", ("ent:saturated", "fc:dense", "die:packer-x"), AMBER),
)
RANKINGS = (
    (("static-decompile", 0.81), ("kdf-chain", 0.72), ("dynamic-trace", 0.63)),
    (("obfuscation-peeling", 0.81), ("dynamic-trace", 0.72),
     ("static-decompile", 0.63)),
)
RANK_NOTES = (("one cheap act → STOP", GREEN),
              ("multi-method opening", AMBER))


def feature_targets(d, reveal):
    for col, (name, tokens, color) in enumerate(TARGETS):
        x0 = 24 + col * 480
        panel(d, (x0, 56, x0 + 432, 190), f"target {name}", color)
        for i, tok in enumerate(tokens):
            if reveal > col * 8 + i * 2:
                chip(d, (x0 + 90 + i * 130, 146), tok, color)


def feature_token_flow(d, f):
    """Feature tokens travel from each target toward its own q-cell bucket."""
    for col in range(2):
        x0 = 24 + col * 480
        tokens, color = TARGETS[col][1], TARGETS[col][2]
        for i in range(3):
            start = 4 + col * 8 + i * 2
            if f < start or f > start + 11:
                continue
            t = (f - start) / 11.0
            x = int(lerp(x0 + 90 + i * 130, x0 + 216, t))
            y = int(lerp(170, 306, t))
            chip(d, (x, y), tokens[i], color)


def feature_bucket(d, col, label, done):
    x0 = 24 + col * 480
    box = (x0, 318, x0 + 432, 500)
    color = TARGETS[col][2]
    if done:
        panel(d, box, f"{label} · q-cell", color)
    else:
        d.rounded_rectangle(box, radius=8, outline=PANEL_EDGE, width=1)
    return box


def feature_docked(d, box, col):
    _, tokens, color = TARGETS[col]
    for i, tok in enumerate(tokens):
        chip(d, (box[0] + 90 + i * 130, box[1] + 46), tok, color, size=11)


def feature_ranking(d, box, col, reveal_rows):
    x0, y0, x1, _ = box
    for i, (name, mean) in enumerate(RANKINGS[col]):
        if i >= reveal_rows:
            break
        y = y0 + 88 + i * 30
        first = i == 0
        if first:
            d.rounded_rectangle([x0 + 12, y - 14, x1 - 12, y + 14], radius=5,
                                fill=ACTIVE_BOX, outline=GLOW, width=2)
        text(d, (x0 + 24, y), f"{i + 1}. {name}",
             GLOW if first else TEXT_DIM, 13)
        text(d, (x1 - 24, y), f"mean {mean:.2f}",
             GLOW if first else TEXT_FAINT, 12, anchor="ra")
    if reveal_rows >= 3:
        note, note_color = RANK_NOTES[col]
        text(d, (x0 + 24, y0 + 168), note, note_color, 12)


def render_rl_features():
    frames = []
    for f in range(40):
        img, d = new_canvas(
            "feature-keyed states — one vocabulary, two rankings")
        feature_targets(d, f)
        feature_token_flow(d, f)
        done_a = f >= 16
        done_b = f >= 18
        box_a = feature_bucket(d, 0, "state A", done_a)
        box_b = feature_bucket(d, 1, "state B", done_b)
        if done_a:
            feature_docked(d, box_a, 0)
        if done_b:
            feature_docked(d, box_b, 1)
        rows_a = 0 if f < 22 else min(3, (f - 22) // 2 + 1)
        rows_b = 0 if f < 29 else min(3, (f - 29) // 2 + 1)
        if rows_a:
            feature_ranking(d, box_a, 0, rows_a)
        if rows_b:
            feature_ranking(d, box_b, 1, rows_b)
        text(d, (W // 2, 528),
             "probe tokens key the state — the same actions rank "
             "differently per state", TEXT_FAINT, 11, anchor="mm")
        frames.append(img)
    return frames


# ---------------------------------------------------------------------------
# rl-death-discovery — arm death, park, discovery
# ---------------------------------------------------------------------------
DOT_COLORS = (GREEN, RED, GREEN, RED, RED, GREEN, RED, RED, RED, RED)
P_DEAD_TRAIL = (0.42, 0.42, 0.47, 0.47, 0.52, 0.56, 0.56, 0.61, 0.66,
                0.71, 0.78)
NOVELTY = 0.83


def death_timeline(d, dots, park, new_dot):
    panel(d, (24, 56, 936, 268), "arm kdf-chain · dispatch timeline",
          RED if park else CYAN)
    d.line([70, 176, 890, 176], fill=PANEL_EDGE, width=2)
    for i in range(dots):
        x = 70 + i * (820 / 9.0)
        color = TEXT_FAINT if park else DOT_COLORS[i]
        d.ellipse([x - 7, 169, x + 7, 183], fill=color)
    if new_dot:
        d.ellipse([880, 159, 900, 179], outline=GLOW, width=2)
        d.ellipse([884, 169, 896, 181], fill=PURPLE)
    text(d, (56, 216), "green = fact-bearing", GREEN, 11)
    text(d, (230, 216), "red = zero-fact", RED, 11)
    text(d, (920, 216), f"p_dead {P_DEAD_TRAIL[min(dots, 10)]:.2f}",
         RED if dots else TEXT_FAINT, 13, anchor="ra")


def death_arm_card(d, park):
    edge = TEXT_FAINT if park else GREEN
    d.rounded_rectangle([40, 236 - 22, 460, 236 + 22], radius=6, fill=PANEL,
                        outline=edge, width=2)
    text(d, (56, 236), "kdf-chain", TEXT if not park else TEXT_FAINT, 14)
    if park:
        chip(d, (200, 236), "PARK", RED)
        text(d, (280, 236), "revivable — never deleted", TEXT_FAINT, 11)
    else:
        text(d, (200, 236), "ACTIVE", GREEN, 12)


def death_discovery(d, f):
    panel(d, (24, 284, 936, 516), "discovery layer", PURPLE)
    if f >= 29:
        pulse = (f % 4) < 2
        edge = AMBER if pulse else PANEL_EDGE
        d.rounded_rectangle([40, 320, 480, 356], radius=6, fill=PANEL,
                            outline=edge, width=2)
        text(d, (56, 338), "DISCOVERY: obstacles ≥ K + stalled", AMBER, 13)
    if 33 <= f <= 37:
        d.rounded_rectangle([500, 320, 920, 356], radius=6, fill=PANEL,
                            outline=RED, width=1)
        text(d, (516, 338), "renamed retry → novelty 0.00 → rejected",
             RED, 12)
    if f >= 38:
        t = min(1.0, (f - 38) / 6.0)
        x_off = int(lerp(380, 0, t))
        box = [500 + x_off, 380, 920 + x_off, 470]
        edge = GREEN if f >= 45 else PURPLE
        d.rounded_rectangle(box, radius=8, fill=PANEL, outline=edge, width=2)
        text(d, (box[0] + 16, box[1] + 22), "expand:unicorn-emu", PURPLE, 13)
        text(d, (box[0] + 16, box[1] + 48), f"novelty {NOVELTY:.2f}", GLOW, 12)
        for i, tok in enumerate(("fc:dense", "die:packer-x")):
            chip(d, (box[0] + 250 + i * 100, box[1] + 22), tok, AMBER, 11)
        text(d, (box[0] + 16, box[1] + 72),
             "feature-keyed: new tokens, not a renamed dead arm",
             TEXT_FAINT, 11)
    if f >= 45:
        stamp(d, (770, 492), "ADMITTED", GREEN, 13)


def render_rl_death_discovery():
    frames = []
    for f in range(50):
        img, d = new_canvas("arm death → park → discovery")
        dots = 0 if f < 4 else min(10, (f - 4) // 2 + 1)
        park = f >= 24
        death_timeline(d, dots, park, f >= 48)
        death_arm_card(d, park)
        death_discovery(d, f)
        text(d, (W // 2, 528),
             "a dead arm parks — it is never deleted; novelty admits a "
             "genuinely new arm", TEXT_FAINT, 11, anchor="mm")
        frames.append(img)
    return frames


# ---------------------------------------------------------------------------
# rl-pricing — the oracle prices honest vs fabricated
# ---------------------------------------------------------------------------
def pricing_panel(d, col, title, act_line, title_color):
    x0 = 24 + col * 468
    panel(d, (x0, 56, x0 + 444, 430), title, title_color)
    text(d, (x0 + 16, 106), act_line, TEXT_DIM, 12)
    d.line([x0 + 16, 124, x0 + 428, 124], fill=PANEL_EDGE, width=1)


def pricing_meter(d, col, phi, claims_done):
    x0 = 24 + col * 468
    text(d, (x0 + 16, 148), "Φ · goal condition met", TEXT_DIM, 12)
    d.rounded_rectangle([x0 + 16, 162, x0 + 428, 186], radius=4, fill=TRACK,
                        outline=PANEL_EDGE)
    fill_w = int(phi * 412)
    if fill_w > 4:
        d.rounded_rectangle([x0 + 16, 162, x0 + 16 + fill_w, 186], radius=4,
                            fill=GREEN)
    text(d, (x0 + 428, 204), f"{phi:.2f}", GREEN, 14, anchor="ra")
    if claims_done:
        chip(d, (x0 + 90, 232), "claims: done", RED)


def pricing_reward(d, col, value, caption, color):
    x0 = 24 + col * 468
    mid = x0 + 222
    text(d, (x0 + 16, 356), f"r = {caption}", TEXT_DIM, 12)
    d.line([x0 + 16, 396, x0 + 428, 396], fill=PANEL_EDGE, width=2)
    bar_len = abs(value) / 0.7 * 200
    if abs(value) > 0.01 and bar_len > 1:
        bx0 = mid if value >= 0 else mid - bar_len
        bx1 = mid + bar_len if value >= 0 else mid
        d.rounded_rectangle([bx0, 386, bx1, 406], radius=3, fill=color)
    label_x, anchor = (x0 + 428, "ra") if value >= 0 else (x0 + 16, "la")
    text(d, (label_x, 370), f"{value:+.2f}", color, 14, anchor=anchor)


def render_rl_pricing():
    frames = []
    for f in range(40):
        img, d = new_canvas("the oracle prices the act — honest vs "
                            "fabricated")
        pricing_panel(d, 0, "honest act", "run held-out replay — bytes "
                      "match", GREEN)
        pricing_panel(d, 1, "fabricated act", "write facts — skip the "
                      "run", RED)
        t_rise = 0.0 if f < 5 else min(1.0, (f - 5) / 11.0)
        pricing_meter(d, 0, lerp(0.34, 0.41, t_rise), False)
        pricing_meter(d, 1, 0.34, f >= 8)
        if f >= 17:
            stamp(d, (246, 296), "ORACLE: PASS", CYAN, 14)
            stamp(d, (714, 296), "STAMP — not PROVEN", RED, 13)
        if f >= 22:
            t_bar = min(1.0, (f - 22) / 8.0)
            pricing_reward(d, 0, 0.61 * t_bar,
                           "ΔΦ·α − λ·cost"
                           f" = {0.61 * t_bar:+.2f}", GREEN)
            pricing_reward(d, 1, -0.18 * t_bar,
                           "0 − λ·cost"
                           f" = {0.18 * t_bar:+.2f}", RED)
        if f >= 33:
            d.rounded_rectangle([240, 456, 720, 496], radius=8,
                                fill=ACTIVE_BOX, outline=GLOW, width=2)
            text(d, (480, 476), "Φ moves on oracle verdicts only.",
                 TEXT, 15, anchor="mm")
        text(d, (W // 2, 528),
             "the maker cannot grade itself — the mechanical oracle "
             "prices every act", TEXT_FAINT, 11, anchor="mm")
        frames.append(img)
    return frames


# ---------------------------------------------------------------------------
# approach-comparison.svg — static, no third-party project names
# ---------------------------------------------------------------------------
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
    parts.append(svg_lane(y, "Static knowledge routing", TEXT_DIM,
                          "open chain, no feedback", TEXT_FAINT))
    parts.append(svg_box(48, y + 48, 170, 40, "methodology manual"))
    parts.append(svg_arrow(222, 264, y + 68))
    parts.append(svg_box(268, y + 48, 170, 40, "LLM improvises"))
    parts.append(svg_arrow(442, 484, y + 68))
    parts.append(svg_box(488, y + 48, 130, 40, "output"))
    y2 = y + 148
    parts.append(svg_lane(y2, "Bounded pipeline", TEXT_DIM,
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
    parts.append(svg_lane(y3, "Single-verdict triage", TEXT_DIM,
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
