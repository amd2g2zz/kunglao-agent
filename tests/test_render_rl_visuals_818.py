# -*- coding: utf-8 -*-
"""tests/test_render_rl_visuals_818.py — the README visual renderer.

Real-render behavior pins (issue #818 coverage climb): every renderer
produces a real, non-empty 960x540 frame stack; a GIF really lands on
disk and re-opens with the right frame count; the SVG comparison is a
well-formed single-root document carrying the four lanes; the seeded
Thompson draws make the designated winner the max; the posterior update
is exactly the +1 win / +0.5 loss decay shape. No mocks — the fixtures
are real PIL canvases and real files in tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import render_rl_visuals as rr  # noqa: E402


# ---------- pure model helpers ----------

def test_lerp_clamps_t_into_unit_interval() -> None:
    assert rr.lerp(0.0, 10.0, 0.5) == 5.0
    assert rr.lerp(0.0, 10.0, -3.0) == 0.0      # below 0 clamps to a
    assert rr.lerp(0.0, 10.0, 7.0) == 10.0      # above 1 clamps to b


def test_beta_stats_mean_and_sd_shapes() -> None:
    mean, sd = rr.beta_stats(2.0, 2.0)
    assert mean == 0.5
    # variance = ab / ((a+b)^2 (a+b+1)) = 4 / (16*5)
    assert sd == pytest.approx((4 / 80.0) ** 0.5)
    mean, sd = rr.beta_stats(8.0, 2.0)
    assert mean == pytest.approx(0.8)
    assert sd < (4 / 80.0) ** 0.5  # the posterior sharpens


def test_cycle_post_pass_adds_win_and_decays_loser() -> None:
    counts = [(f"arm{i}", 2.0, 2.0) for i in range(4)]
    post = rr.cycle_post(counts, cyc=0)   # winner 0 PASS, loser 2
    assert post[0][1] == pytest.approx(3.0)   # winner +1 alpha
    assert post[0][2] == pytest.approx(2.0)
    assert post[2][2] == pytest.approx(2.5)   # loser +0.5 beta decay
    assert post[2][1] == pytest.approx(2.0)
    # the input counts list is never mutated
    assert counts[0][1] == 2.0 and counts[2][2] == 2.0


def test_cycle_post_fail_banks_the_loss() -> None:
    counts = [(f"arm{i}", 2.0, 2.0) for i in range(4)]
    post = rr.cycle_post(counts, cyc=2)   # winner 0 FAIL verdict
    assert post[0][1] == pytest.approx(2.0)
    assert post[0][2] == pytest.approx(3.0)   # FAIL -> beta +1
    assert post[2][2] == pytest.approx(2.0)   # no loser decay on FAIL


def test_draw_samples_designated_winner_is_max() -> None:
    for cyc in range(len(rr.CYCLES)):
        samples = rr.draw_samples(cyc)
        assert len(samples) == len(rr.ARMS)
        assert samples[rr.CYCLES[cyc]["winner"]] == max(samples)


# ---------- svg faces ----------

def test_svg_helpers_produce_the_documented_fragments() -> None:
    assert 'fill="#181b26"' in rr.svg_box(0, 0, 10, 10, "x")
    assert ">x</text>" in rr.svg_box(0, 0, 10, 10, "x")
    frag = rr.svg_arrow(10, 30, 5, color="#f00")
    assert 'stroke="#f00"' in frag and "<polygon" in frag
    lane = rr.svg_lane(52, "label", "#fff", "note", "#888")
    assert 'y="52"' in lane and ">label</text>" in lane
    back = rr.svg_loop_back(10, 90, 60, "#0f0", "loop")
    assert 'd="M 90 76' in back and ">loop</text>" in back


def test_render_comparison_svg_is_wellformed_four_lanes() -> None:
    svg = rr.render_comparison_svg()
    root = ElementTree.fromstring(svg)   # raises on malformed xml
    assert root.tag.endswith("svg")
    assert root.get("width") == "960" and root.get("height") == "720"
    text = svg
    for lane_label in ("Static knowledge routing", "Bounded pipeline",
                       "Single-verdict triage",
                       "kunglao-agent (act-level RL controller)"):
        assert lane_label in text
    # the closing loop is the only accent-colored lane
    assert 'stroke="#9ece6a"' in svg


# ---------- canvas + drawing helpers on a real image ----------

def test_new_canvas_draws_titlebar_and_dots() -> None:
    img, d = rr.new_canvas("title bar text")
    assert img.size == (rr.W, rr.H)
    px = img.load()
    assert px[22, 18][:3] == (255, 95, 87)      # DOT_RED traffic light
    assert px[42, 18][:3] == (254, 188, 46)     # DOT_YELLOW
    assert px[62, 18][:3] == (40, 200, 64)      # DOT_GREEN


def test_panel_chip_stamp_arrow_helpers_draw() -> None:
    img, d = rr.new_canvas("helpers")
    rr.panel(d, (20, 40, 300, 200), "panel title")
    rr.chip(d, (150, 260), "chip label", rr.BLUE)
    rr.stamp(d, (150, 320), "STAMPED", rr.GREEN)
    rr.arrow_down(d, 480, 100, 160)
    rr.hex_card(d, (600, 40, 940, 200), "hex card",
                ("4d 5a 90 00", "e8 2f 1b c9"), lit_rows=(1,))
    rr.entropy_gauge(d, 600, 240, "entropy", 0.6)
    rr.qcell_grid(d, (600, 280, 940, 420), ("kind a",), ("m1", "m2"),
                  [[[3, 1], [1, 2]]], highlight_state=0)
    rr._card(d, (600, 440, 940, 530), "card", ("line one", "line two"))
    rr._method_chip(d, 760, 470, "method", "pick", sub="picked now")
    rr._method_chip(d, 760, 500, "method", "dead")
    rr._cost_meter(d, 600, 520, 2, "cost")
    # every helper drew without error; the canvas is a real image
    assert img.getbbox() is not None


def test_beta_curve_and_progress_curve_draw() -> None:
    img, d = rr.new_canvas("curves")
    rr.beta_curve(d, (40, 60, 300, 200), 2.0, 5.0, rr.BLUE)
    rr.progress_curve(d, (40, 220, 300, 360), [0.3, 0.35, 0.7], rr.GREEN,
                      "progress")
    # the degenerate single-point series takes the label-only face
    rr.progress_curve(d, (40, 220, 300, 360), [0.4], rr.AMBER, "lone")
    assert img.getbbox() is not None


def test_text_anchor_fallback_manual_centering() -> None:
    img, d = rr.new_canvas("anchor")
    # anchor given + a font with getbbox takes the d.text(anchor=...) path
    rr.text(d, (480, 100), "centered", rr.TEXT, 13, anchor="mm")
    # anchor "la" rides the no-anchor fast path
    rr.text(d, (40, 140), "left", rr.TEXT, 13, anchor="la")
    # horizontal/vertical re-centering math for the other anchor faces
    rr.text(d, (480, 180), "right", rr.TEXT, 13, anchor="rm")
    rr.text(d, (480, 220), "middled", rr.TEXT, 13, anchor="ma")
    assert img.getbbox() is not None


# ---------- the seven gif renderers (real frame stacks) ----------

@pytest.mark.parametrize("name", [
    "rl-loop", "rl-features", "rl-death-discovery", "rl-pricing",
    "rl-drive", "rl-comparison", "rl-curves",
])
def test_every_renderer_emits_real_frames(name: str) -> None:
    frames = rr.RENDERERS[name][1]()
    assert len(frames) >= 30          # every visual is a real animation
    assert all(f.size == (rr.W, rr.H) for f in frames)


def test_shared_palette_and_save_gif_roundtrip(tmp_path: Path) -> None:
    frames = [rr.new_canvas(f"frame {i}")[0] for i in range(3)]
    palette = rr.shared_palette(frames)
    assert palette.mode == "P"
    path = tmp_path / "mini.gif"
    size = rr.save_gif(frames, path)
    assert path.is_file() and size == path.stat().st_size
    assert size > 0
    with rr.Image.open(path) as gif:
        assert gif.n_frames == 3
        assert gif.size == (rr.W, rr.H)


def test_main_renders_selected_visual_to_out_dir(tmp_path: Path,
                                                 capsys) -> None:
    rc = rr.main(["--out", str(tmp_path), "--only", "comparison"])
    assert rc == 0
    svg_path = tmp_path / "approach-comparison.svg"
    assert svg_path.is_file()
    text = svg_path.read_text(encoding="utf-8")
    assert "<svg" in text and "kunglao-agent (act-level RL controller)" in text
    assert "svg" in capsys.readouterr().out


def test_main_gif_budget_flag_surface(tmp_path: Path) -> None:
    # the OVER BUDGET guard: a budget breach returns rc 2 (rc face only —
    # the 2.5MB breach itself is not fabricated here)
    assert rr.MAX_GIF_BYTES == 2_500_000
