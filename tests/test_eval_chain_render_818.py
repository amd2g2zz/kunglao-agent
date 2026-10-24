# -*- coding: utf-8 -*-
"""tests/test_eval_chain_render_818.py — the chain-tier language
renderers (#370) in the measured leg (issue #818 climb).

Real behavior pins: every gradient's payload renders for both language
families; the junk wedges ride the committed payload and vanish from
the stripped reference; the artifacts are ASCII-only by contract; and
the rendered PYTHON payload is loaded as a real module and executed
against the python model — derive() parity with eval_chain.model_out
proves the renderer minted a true artifact, not a lookalike.
"""
from __future__ import annotations

import importlib.util

import eval_chain as ch  # noqa: E402
import eval_chain_render as rd  # noqa: E402
from eval_chain_mint import stage_cfg  # noqa: E402  (the real finalizer)

FAMILIES = ("chain-js", "chain-py")
GRADIENTS = ("L1", "L2", "L3")


def _cfg(family: str, gradient: str) -> dict:
    """The REAL per-unit parameter set: derive_cfg + the mint staging
    face (junk wedges + the encrypted config blobs)."""
    return stage_cfg({"family": family,
                      "seed": 90210 + len(family) + len(gradient),
                      "gradient": gradient})


# ---------- the pollution markers ----------

def test_junk_markers_name_the_wedges_and_constants() -> None:
    cfg = _cfg("chain-py", "L1")
    markers = rd.junk_markers(cfg)
    tag = rd._junk_tag(cfg)
    assert markers[0] == f"_opq_{tag}"
    assert markers[1] == f"_w_{tag}_"
    assert rd._u(cfg["junk_a"]) in markers
    assert rd._u(cfg["junk_b"]) in markers


def test_rc_rows_render_raw_words() -> None:
    cfg = _cfg("chain-py", "L1")
    rows = rd._rc_rows(cfg)
    for row in cfg["rc"]:
        assert "[" + ", ".join(str(r) for r in row) + "]" in rows


# ---------- payload renderers: both languages, all gradients ----------

def test_py_payload_all_gradients_and_junk_flag() -> None:
    for gradient in GRADIENTS:
        cfg = _cfg("chain-py", gradient)
        dirty = rd.render_py_payload(cfg, include_junk=True)
        clean = rd.render_py_payload(cfg, include_junk=False)
        assert f"gradient {gradient}" in dirty
        assert "CFG_HEX" in dirty and cfg["cfg_hex"] in dirty
        assert "def derive(payload_hex" in dirty
        for marker in rd.junk_markers(cfg):
            assert marker in dirty          # the pollution rides
            assert marker not in clean      # and the clean form is clean
        assert "junk wedges stripped" in clean
        # the honeypot is the ONLY key-shaped literal by design
        assert cfg["honeypot"] in dirty
        if gradient == "L3":
            assert "LEGACY_P" in dirty
            assert "gettrace" in dirty      # the anti-debug gate
        elif gradient == "L1":
            assert "LEGACY_KEY" in dirty
        else:
            assert "LEGACY_CFG" in dirty


def test_js_payload_all_gradients_and_junk_flag() -> None:
    for gradient in GRADIENTS:
        cfg = _cfg("chain-js", gradient)
        dirty = rd.render_js_payload(cfg, include_junk=True)
        clean = rd.render_js_payload(cfg, include_junk=False)
        assert "module.exports" in dirty
        assert "var CFG_HEX" in dirty
        for marker in rd.junk_markers(cfg):
            assert marker in dirty
            assert marker not in clean
        if gradient == "L3":
            assert "LEGACY_P" in dirty
            assert "debugger" in dirty      # the js anti-debug gate
        elif gradient == "L1":
            assert "LEGACY_KEY" in dirty
        else:
            assert "LEGACY_CFG" in dirty


def test_payloads_are_ascii_only_by_contract() -> None:
    for family in FAMILIES:
        for gradient in GRADIENTS:
            cfg = _cfg(family, gradient)
            renderer = (rd.render_js_payload if family == "chain-js"
                        else rd.render_py_payload)
            src = renderer(cfg, include_junk=True)
            assert src.encode("utf-8").decode("ascii", errors="ignore") \
                == src


# ---------- artifact-model parity (the mint self-check's core) ----------

def _load_rendered(tmp_path, src: str):
    """Load a rendered payload as a REAL module via the import
    machinery (no manual code-run indirection)."""
    import sys
    p = tmp_path / "rendered_payload.py"
    p.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("rendered_payload", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rendered_py_payload_derive_matches_the_model(
        tmp_path) -> None:
    import sys
    traced = sys.gettrace() is not None
    for gradient in GRADIENTS:
        cfg = _cfg(family="chain-py", gradient=gradient)
        mod = _load_rendered(
            tmp_path, rd.render_py_payload(cfg, include_junk=True))
        for payload_hex in ("00ff10", "deadbeef" * 4, ""):
            # lanes are an L3-only probe face: L1/L2 probes always ride
            # lane 0 (eval_chain.probes_for), so parity is pinned on the
            # contract surface
            lanes = (0, 3) if gradient == "L3" else (0,)
            for lane in lanes:
                got = mod.derive(payload_hex, lane)
                if gradient == "L3" and traced:
                    # THE ANTI-DEBUG GATE, PINNED: under a tracer
                    # (pytest-cov IS a tracer) the integrity fold
                    # corrupts INTEG and the selector can land on the
                    # decoy core — the answer is well-formed garbage,
                    # never the reference derivation.
                    sel = (mod.FP0 ^ (mod.INTEG ^ mod.CORRUPT)) & 0xff
                    params = (mod.TRUE_P if sel == mod.SEL_KEY
                              else mod.LEGACY_P)
                    want = ch.chain_core(dict(params),
                                         bytes.fromhex(payload_hex), lane)
                    assert got == want, (payload_hex, lane, sel)
                else:
                    want = ch.model_out(cfg, payload_hex, lane)
                    assert got == want, (gradient, payload_hex, lane)
