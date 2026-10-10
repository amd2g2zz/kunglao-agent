# -*- coding: utf-8 -*-
"""matrix4b C7-chain pins: the delivery chain closes for unit-declared
candidates.

matrix4b field evidence (2026-10-05, dev 231076a1): wt1 broke THROUGH
the C6 delivery gate and died at C7-convergence with the work
done - worker-C-004.json reads "sdk.js fully characterized ... 5 facts
pinned". Four gates stood between the finished work and the verdict:

  G1 orphan gate: the engine refuses CONVERGED while terminal claims
     lack answers_question — but kunglao-init's scaffold seeds (lane /
     project type / material) are BY DESIGN question-less (issue 212
     closed them PROVEN at birth; the operator's questions arrive
     after). The M2 concern (analysis claims answering nothing) never
     applied to them.
  G2 settlement rows: C7 demands >=1 claim_settled row; the sanctioned
     register writer (ws_yaml — workers' only legal write face since
     the single-writer ruling) never emits them, so every real
     promotion lands row-less.
  G3 candidate path: the oracle face hardcodes artifacts/
     derive_reimpl.py (the smoke rehearsal shape); the combat units'
     declared candidate contract is a ws-root client.py — the runner
     must resolve the candidate from the unit's own declaration.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import yaml  # pytest.ini pythonpath carries the repo deps

from e2e import model                    # noqa: E402


# ------------------------------------------------------------------ G1

def test_scaffold_claims_are_not_orphans():
    """The wt1 death verbatim: terminal scaffold seeds + live primary
    questions must not block CONVERGED."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import convergence_check as cc
    reg = {"claims": [
        {"id": "C-001", "status": "PROVEN", "claim_class": "scaffold"},
        {"id": "C-004", "status": "PROVEN", "answers_question": "pq-1"},
        {"id": "C-005", "status": "OPEN"},
    ]}
    assert cc._orphan_terminal_claims(reg, {"pq-1"}) == []


def test_analysis_orphans_still_block():
    """The M2 concern unchanged: a terminal ANALYSIS claim answering
    nothing is still an orphan."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import convergence_check as cc
    reg = {"claims": [
        {"id": "C-004", "status": "PROVEN"},   # no link, no class
    ]}
    assert cc._orphan_terminal_claims(reg, {"pq-1"}) == [
        {"id": "C-004", "status": "PROVEN"}]


def test_init_seeds_carry_scaffold_class():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_mod", ROOT / "scripts" / "kunglao-init.py")
    ki = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ki)
    seeds = ki.seed_claims("sdk.js", "linux", "ab" * 32, lane="algorithm")
    assert all(s.get("claim_class") == "scaffold" for s in seeds), seeds
    legacy = ki.seed_claims("sdk.js", "linux", "ab" * 32, lane=None)
    assert all(s.get("claim_class") == "scaffold" for s in legacy), legacy


# ------------------------------------------------------------------ G2

def test_ws_yaml_register_write_settles(tmp_path):
    """A worker's sanctioned register write emits its claim_settled
    row — the C7 ledger face closes on real promotions."""
    import subprocess
    ws = tmp_path / "ws"
    ws.mkdir()
    reg = ws / "claim-register.yaml"
    reg.write_text(
        "claims:\n  - id: C-004\n    status: OPEN\n", encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ws_yaml.py"),
         "set", str(reg), "claims.0.status", "PROVEN"],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    log = ws / "runs" / "logs"
    rows = []
    for f in sorted(log.glob("kunglao-*.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"claim_settled"' in line:
                rows.append(line)
    assert rows, "no claim_settled row emitted by the sanctioned write"
    assert "C-004" in rows[0] and "OPEN" in rows[0], rows[0]


def test_ws_yaml_non_register_write_does_not_settle(tmp_path):
    """The emission leg arms ONLY on the register carrier."""
    import subprocess
    ws = tmp_path / "ws"
    ws.mkdir()
    other = ws / "mission_ledger.yaml"
    other.write_text("a: 1\n", encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ws_yaml.py"),
         "set", str(other), "a", "2"],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert not (ws / "runs" / "logs").exists()


# ------------------------------------------------------------------ G3

def test_candidate_resolves_from_unit_declaration(tmp_path):
    """checker.candidate in the unit's task.yaml names the ws-relative
    candidate; absent -> the smoke-rehearsal default unchanged."""
    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({
        "task_id": "u", "checker": {"candidate": "client.py"}}),
        encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "client.py").write_text("print('c')", encoding="utf-8")
    got = model.resolve_candidate(ws, task)
    assert got == ws / "client.py", got


def test_candidate_default_unchanged(tmp_path):
    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({"task_id": "u"}), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    got = model.resolve_candidate(ws, task)
    assert got == ws / "artifacts" / "derive_reimpl.py", got
