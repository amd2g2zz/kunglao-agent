# -*- coding: utf-8 -*-
"""#863 Family E — the kunglao_upgrade WARN-triple is single-sourced.

One degradation used to repeat the three-signal block (stderr WARN print +
structured `[event]` trail #753 B2 + workspace ledger emit, design D6) at
every failure face — 16 print sites measured 2026-09-02 (8 exact triples,
2 near-triples with custom ledger detail, 1 print+event, 2 print+ledger,
3 print-only). Enforcement-by-copying is replaced by enforcement-by-
mechanism: `_warn` (three signals) and `_warn_line` (stderr-only face)
are the only two printers of a `kunglao-upgrade: WARN` line.

Behavior parity of the migrated sites stays pinned by the UNCHANGED
behavioral suite test_deploy_surface_755.py (same input -> same output).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load_upgrade():
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade_warn_863f", SCRIPTS / "kunglao_upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- confinement: WARN printing is mechanism, not copying ----------

def test_no_direct_warn_print_outside_the_helpers():
    """Every `kunglao-upgrade: WARN` stderr line must ride `_warn` /
    `_warn_line` — a direct `print(f"kunglao-upgrade: WARN ...` at a call
    site is a resurrected Family E copy and is red."""
    source = (SCRIPTS / "kunglao_upgrade.py").read_text(encoding="utf-8")
    direct = re.findall(r'print\(\s*f?"kunglao-upgrade: WARN', source)
    assert not direct, (
        f"direct stderr WARN prints are banned outside _warn/_warn_line "
        f"(#863 Family E): {len(direct)} resurrected copy/copies")
    assert source.count("def _warn(") == 1, "exactly one _warn definition"
    assert source.count("def _warn_line(") == 1, \
        "exactly one _warn_line definition"


def test_warn_triple_event_face_exists_exactly_once():
    """The triple's structured-event face lives only inside `_warn` —
    the parameterized call statement is unique in source (line-anchored so
    the docstring mention inside `_warn` itself does not count; literal-
    status warn events at non-triple sites are a different, allowed shape)."""
    source = (SCRIPTS / "kunglao_upgrade.py").read_text(encoding="utf-8")
    calls = re.findall(r'^\s+_emit_event\(event, "warn", why\)\s*$',
                       source, re.MULTILINE)
    assert len(calls) == 1, (
        f"the WARN triple's event face must appear exactly once (inside "
        f"_warn), found {len(calls)} — a second is an inlined triple "
        f"(#863 Family E)")


# ---------- util contract: the three signals, the two variants ----------

def test_warn_emits_all_three_signals(monkeypatch, capsys):
    up = _load_upgrade()
    events: list[tuple] = []
    ledgers: list[tuple] = []
    monkeypatch.setattr(
        up, "_emit_event",
        lambda name, status, detail="": events.append((name, status, detail)))
    monkeypatch.setattr(
        up, "_emit",
        lambda ws, action, detail: ledgers.append((action, detail)))

    up._warn("kunglao-upgrade: WARN — 863f face", "why-x", "ev_x", None)

    err = capsys.readouterr().err
    assert "kunglao-upgrade: WARN — 863f face" in err, err
    assert events == [("ev_x", "warn", "why-x")], events
    assert ledgers == [], "ws=None keeps the ledger face silent"


def test_warn_ledger_detail_default_and_override(monkeypatch, capsys):
    """Default ledger detail is `warn:{why}`; `ledger_detail` overrides it
    (the claudemd `skipped:` and toolchain-manifest plain-detail variants
    carry their own prefix — byte-identical output pre/post extraction)."""
    up = _load_upgrade()
    ledgers: list[tuple] = []
    monkeypatch.setattr(up, "_emit_event", lambda *a, **k: None)
    monkeypatch.setattr(
        up, "_emit",
        lambda ws, action, detail: ledgers.append((action, detail)))
    ws = Path("ws")

    up._warn("m1", "why1", "ev1", ws)
    up._warn("m2", "why2", "ev2", ws, ledger_detail="skipped:why2")

    assert ledgers == [("ev1", "warn:why1"), ("ev2", "skipped:why2")], ledgers
    assert "m1" in capsys.readouterr().err


def test_warn_line_is_stderr_only(monkeypatch, capsys):
    """`_warn_line` is the quiet face: stderr line, zero event/ledger
    signals (frame-stamp single-WARN posture, git-skip, sweep fail-open)."""
    up = _load_upgrade()
    calls: list[str] = []
    monkeypatch.setattr(up, "_emit_event", lambda *a, **k: calls.append("event"))
    monkeypatch.setattr(up, "_emit", lambda *a, **k: calls.append("ledger"))

    up._warn_line("kunglao-upgrade: WARN — quiet face")

    assert "kunglao-upgrade: WARN — quiet face" in capsys.readouterr().err
    assert calls == [], f"_warn_line must stay stderr-only: {calls}"
