# -*- coding: utf-8 -*-
"""tests/test_compute_priors_137.py — on-demand cross-workspace prior
computation (issue 137, v0.1.6 promoted slice).

compute_priors(ws_paths) is a PURE function over EXPLICITLY-NAMED
workspaces: it sums Beta alpha/beta pseudo-counts from each named
workspace's case bank and posterior ledger, returns the aggregate prior,
WRITES NOTHING anywhere, and DISCARDS everything after the call.

Semantics (documented contract):
  - One Beta(1,1) uniform base for the AGGREGATE (bases never multiply
    per workspace; only observations sum).
  - case-bank rows contribute observations: roi_class POSITIVE -> +1
    alpha, NEGATIVE -> +1 beta, NEUTRAL/UNRESOLVED -> nothing.
  - runs/posteriors.yaml contributes the observations ON TOP of its own
    per-case uniform base: per case max(alpha-1,0)/max(beta-1,0).
    The two namespaces count DIFFERENT observables (settled claim
    outcomes vs oracle-case runner verdicts) — both are additive
    experience, summed transparently with per-source decomposition in
    the result.
  - Missing state files contribute zero (a workspace is allowed to have
    no bank / no ledger yet). CORRUPT or UNKNOWN-SCHEMA state is LOUD
    (no silent fabrication of a prior from a workspace the caller
    explicitly named).
  - Result carries schema "aggregate-prior/1" so the prior itself is
    self-describing.

All fixtures here are SYNTHETIC (privacy rule: no real workspace data).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import case_bank as cb  # noqa: E402
from posteriors import CasePosterior, PosteriorLedger  # noqa: E402


# ---------- synthetic workspace builders ----------

def _bank_entry(claim_id: str, roi_class: str) -> dict:
    e = {"claim_id": claim_id, "method": "device-trace(x)",
         "roi_class": roi_class, "context_tags": ["auth"]}
    if roi_class == "NEGATIVE":
        e["attribution"] = "wrong primitive assumed"
    return e


def _tree_snapshot(root: Path) -> dict:
    """Deterministic {relative path: sha256} of every file under root."""
    snap = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            snap[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
        elif p.is_dir():
            snap[str(p.relative_to(root)) + "/"] = "dir"
    return snap


def _make_workspace(ws: Path, bank: list[dict] | None = None,
                    cases: list[CasePosterior] | None = None,
                    with_posteriors: bool = True) -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    for e in (bank or []):
        cb.append(ws, e)
    if with_posteriors and cases is not None:
        led = PosteriorLedger()
        for c in cases:
            led.cases[c.case_id] = c
        led.save(ws)
    return ws


# ---------- determinism ----------

def test_same_inputs_same_prior(tmp_path):
    """Determinism: two calls over identical explicitly-named workspaces
    return the identical aggregate (no clock, no ambient state, no rng)."""
    spec = dict(
        bank=[_bank_entry("C-1", "POSITIVE"), _bank_entry("C-2", "NEGATIVE")],
        cases=[CasePosterior("case-a", alpha=3.5, beta=1.25)])
    ws1 = _make_workspace(tmp_path / "ws1", **spec)
    ws2 = _make_workspace(tmp_path / "ws2", **spec)
    from compute_priors import compute_priors
    r1 = compute_priors([ws1, ws2])
    r2 = compute_priors([ws1, ws2])
    assert r1 == r2


# ---------- purity: writes nothing, discards everything ----------

def test_writes_nothing_anywhere(tmp_path):
    """Filesystem snapshot before/after is identical — the function never
    persists a cache, never rewrites state it read, never creates dirs."""
    ws = _make_workspace(
        tmp_path / "ws",
        bank=[_bank_entry("C-1", "POSITIVE")],
        cases=[CasePosterior("case-a", alpha=2.0, beta=1.0)])
    before = _tree_snapshot(tmp_path)
    from compute_priors import compute_priors
    compute_priors([ws])
    assert _tree_snapshot(tmp_path) == before


# ---------- explicit paths only ----------

def test_nonexistent_path_is_a_loud_error(tmp_path):
    """No ambient discovery, no silent scan, no silent zero: a named path
    that does not exist fails loudly naming the path."""
    from compute_priors import compute_priors
    ghost = tmp_path / "does-not-exist"
    with pytest.raises(ValueError) as ei:
        compute_priors([ghost])
    assert "does-not-exist" in str(ei.value)


def test_file_path_is_a_loud_error(tmp_path):
    """A named path must be a workspace DIRECTORY — a file path is a
    caller mistake, refused loudly."""
    f = tmp_path / "not-a-ws.txt"
    f.write_text("x", encoding="utf-8")
    from compute_priors import compute_priors
    with pytest.raises(ValueError):
        compute_priors([f])


def test_no_ambient_discovery_sibling_state_is_invisible(tmp_path):
    """Only the NAMED workspaces count: a sibling workspace full of state
    must not leak into a prior computed over an empty named workspace."""
    rich = _make_workspace(
        tmp_path / "rich", bank=[_bank_entry("C-1", "POSITIVE")] * 3)
    empty = _make_workspace(tmp_path / "empty")
    assert rich.exists() and empty.exists()
    from compute_priors import compute_priors
    r = compute_priors([empty])
    assert r["alpha"] == 1.0 and r["beta"] == 1.0  # base prior only


# ---------- documented sum semantics ----------

def test_known_sums_across_two_workspaces(tmp_path):
    ws1 = _make_workspace(
        tmp_path / "ws1",
        bank=[_bank_entry("C-1", "POSITIVE"), _bank_entry("C-2", "POSITIVE"),
              _bank_entry("C-3", "NEGATIVE")],
        cases=[CasePosterior("case-a", alpha=3.5, beta=1.25)])
    ws2 = _make_workspace(
        tmp_path / "ws2",
        bank=[_bank_entry("C-4", "NEGATIVE")],
        with_posteriors=False)
    from compute_priors import compute_priors
    r = compute_priors([ws1, ws2])
    # case bank: 2 POSITIVE / 2 NEGATIVE across both workspaces
    assert r["sources"]["case_bank"]["alpha"] == 2
    assert r["sources"]["case_bank"]["beta"] == 2
    # posteriors: observations on top of the uniform base (3.5-1 / 1.25-1)
    assert r["sources"]["posteriors"]["alpha"] == pytest.approx(2.5)
    assert r["sources"]["posteriors"]["beta"] == pytest.approx(0.25)
    # aggregate = ONE base + all observations
    assert r["alpha"] == pytest.approx(1.0 + 2 + 2.5)
    assert r["beta"] == pytest.approx(1.0 + 2 + 0.25)
    assert r["mean"] == pytest.approx(r["alpha"] / (r["alpha"] + r["beta"]))
    assert r["schema"] == "aggregate-prior/1"
    assert [str(p) for p in r["workspaces"]] == [str(ws1), str(ws2)]


def test_empty_workspace_contributes_base_only(tmp_path):
    from compute_priors import compute_priors
    r = compute_priors([_make_workspace(tmp_path / "bare")])
    assert r["alpha"] == 1.0 and r["beta"] == 1.0
    assert r["sources"]["case_bank"] == {"alpha": 0, "beta": 0}
    assert r["sources"]["posteriors"] == {"alpha": 0, "beta": 0}


def test_no_workspaces_is_base_prior(tmp_path):
    from compute_priors import compute_priors
    r = compute_priors([])
    assert r["alpha"] == 1.0 and r["beta"] == 1.0


def test_unknown_posteriors_schema_is_loud(tmp_path):
    """The migration-insurance face: a workspace whose posterior ledger is
    in an UNKNOWN format must be detected loudly, never folded into the
    sum as zero (this is exactly what historical-format replay needs)."""
    ws = tmp_path / "ws-future"
    ws.mkdir()
    runs = ws / "runs"
    runs.mkdir()
    (runs / "posteriors.yaml").write_text(
        "schema: posteriors-schema/99\ncases: {}\npqs: {}\n",
        encoding="utf-8")
    from compute_priors import compute_priors
    from posteriors import PosteriorSchemaError
    with pytest.raises(PosteriorSchemaError):
        compute_priors([ws])


def test_corrupt_posteriors_is_loud(tmp_path):
    ws = tmp_path / "ws-corrupt"
    ws.mkdir()
    runs = ws / "runs"
    runs.mkdir()
    (runs / "posteriors.yaml").write_text(
        "not: [valid: yaml: structure\n", encoding="utf-8")
    from compute_priors import compute_priors
    with pytest.raises(ValueError):
        compute_priors([ws])


def test_legacy_case_bank_rows_without_stamp_still_sum(tmp_path):
    """Pre-stamp bank rows (no schema field) sum like any other row —
    historical workspaces feed the prior unmodified (never rewritten)."""
    ws = tmp_path / "ws-legacy"
    ws.mkdir()
    runs = ws / "runs"
    runs.mkdir()
    rows = [
        {"ts": "t", "claim_id": "C-1", "method": "m",
         "context_tags": [], "outcome_observed": {}, "roi_class": "POSITIVE",
         "attribution": None, "premise_correction": None, "how": None},
        {"ts": "t", "claim_id": "C-2", "method": "m",
         "context_tags": [], "outcome_observed": {}, "roi_class": "NEGATIVE",
         "attribution": "why", "premise_correction": None, "how": None},
        {"ts": "t", "claim_id": "C-3", "method": "m",
         "context_tags": [], "outcome_observed": {}, "roi_class": "NEUTRAL",
         "attribution": None, "premise_correction": None, "how": None},
    ]
    (runs / "case-bank.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    from compute_priors import compute_priors
    r = compute_priors([ws])
    assert r["sources"]["case_bank"] == {"alpha": 1, "beta": 1}


# ---------- CLI face ----------

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "compute_priors.py"), *args],
        capture_output=True, text=True, timeout=60)


def test_cli_prints_json_and_writes_nothing(tmp_path):
    ws = _make_workspace(
        tmp_path / "ws", bank=[_bank_entry("C-1", "POSITIVE")])
    before = _tree_snapshot(tmp_path)
    proc = _run_cli(str(ws))
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["schema"] == "aggregate-prior/1"
    assert doc["alpha"] == 2.0 and doc["beta"] == 1.0
    assert _tree_snapshot(tmp_path) == before  # CLI writes nothing either


def test_cli_nonexistent_path_loud_failure(tmp_path):
    proc = _run_cli(str(tmp_path / "ghost"))
    assert proc.returncode != 0
    assert "ghost" in (proc.stderr + proc.stdout)


def test_cli_multiple_paths_aggregate(tmp_path):
    ws1 = _make_workspace(tmp_path / "a", bank=[_bank_entry("C-1", "POSITIVE")])
    ws2 = _make_workspace(tmp_path / "b", bank=[_bank_entry("C-2", "NEGATIVE")])
    proc = _run_cli(str(ws1), str(ws2))
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["sources"]["case_bank"] == {"alpha": 1, "beta": 1}
    assert doc["alpha"] == 2.0 and doc["beta"] == 2.0
