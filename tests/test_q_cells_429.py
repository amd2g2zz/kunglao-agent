# -*- coding: utf-8 -*-
"""tests/test_q_cells_429.py — #429 §4 Q cells + TS call site 2 (W2-T2.2).

RED-first pins for the RL kernel's action-value layer:

  1. cell formation from replayed dispatch history (reindex over a
     fixture root — the #432 usage face + the q-cell observation face);
  2. hierarchical shrinkage toward the family's global anchor
     (leave-one-out anchor; a cell with 1 sample follows the anchor
     until enough LOCAL evidence diverges; cold families stay wide);
  3. sampling distribution ~= discounted posterior probabilities
     (P_LLM ⊗ Q, seeded, chi-square tolerance) + the γ read-face decay;
  4. determinism given seed (and the Random(0) anchor default);
  5. the Store protocol seam (stub store, no filesystem);
  6. the recording faces: dispatch observation (dual-face family
     declaration), settlement observe (credit clamping);
  7. the dispatch-gate ALLOW-tail hook records and never blocks.

Freeze note: hooks/worker_budget_sinks.py must NEVER import
state_signature directly (test_experience_freeze_396); the hook lazy-
imports rlvr.q_cells and the signature computation lives in the module.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import state_signature as ssig  # noqa: E402
from rlvr import q_cells  # noqa: E402

# chi-square critical value, df=2, p=0.01
CHI2_DF2_P01 = 9.21
N_DRAWS = 9000


def _row(sig: str, fam: str, credit, ts="2026-09-29T00:00:00Z",
         source="settlement", claim=None) -> dict:
    return {"schema": q_cells.OBS_SCHEMA, "ts": ts, "source": source,
            "signature_hash": sig, "method_family": fam,
            "claim": claim, "agent": None, "credit": credit}


def _store(rows):
    return q_cells.InMemoryStore(rows)


# ---------------------------------------------------------------- 1. reindex

def test_reindex_forms_cells_from_replayed_history(tmp_path):
    root = tmp_path / "campaign"
    ws_a = root / "wsA"
    ws_b = root / "wsB"
    ws_c = root / "wsC"
    sig_a1, sig_a2 = "aaaa0000aaaa", "aaaa0000bbbb"

    # face 1 — the authoritative q-cell observation log (exact signatures)
    obs = ws_a / q_cells.OBS_REL
    obs.parent.mkdir(parents=True)
    obs.write_text("\n".join(json.dumps(r) for r in [
        _row(sig_a1, "static-symbolic", 1.0),
        _row(sig_a1, "static-symbolic", 0.0),
        _row(sig_a2, "dynamic-instrumentation", 0.5),
    ]) + "\n", encoding="utf-8")

    # face 2 — the #432 usage face (family + claim; no signature/credit);
    # one row WITHOUT a family is the honest unattributed gap
    usage = ws_b / "runs" / "method-family-log.jsonl"
    usage.parent.mkdir(parents=True)
    usage.write_text("\n".join(json.dumps(r) for r in [
        {"schema": "method-family-usage/1", "ts": "2026-09-29T00:00:00Z",
         "claim": "C-1", "cell": "C-1", "family": "static-symbolic",
         "agent": "kunglao-worker", "tier": 1, "tools": []},
        {"schema": "method-family-usage/1", "ts": "2026-09-29T00:00:01Z",
         "claim": "C-2", "cell": "C-2", "family": "",
         "agent": "kunglao-worker", "tier": 1, "tools": []},
    ]) + "\n", encoding="utf-8")

    # face 3 — the unified-log dispatch row (method_family= in detail)
    ulog = ws_c / "runs" / "logs" / "kunglao-2026-09-29.jsonl"
    ulog.parent.mkdir(parents=True)
    ulog.write_text(json.dumps({
        "ts": "2026-09-29T00:00:02Z", "actor": "hook:worker_budget",
        "action": "dispatch", "claim": "C-9",
        "detail": "tier=1 tools=Bash agent=? method_family=arm-kdf "
                  "(#461 linkage: renew + arm + phase=DISPATCH)"}) + "\n",
        encoding="utf-8")

    report = q_cells.reindex(root)

    assert report["schema"] == q_cells.REINDEX_SCHEMA
    assert report["rows_scanned"] == 6
    assert report["unattributed"] == 1
    cells = {(c["signature_hash"], c["method_family"]): c
             for c in report["cells"]}
    # face-1 rows: exact cells with credit masses
    a1 = cells[(sig_a1, "static-symbolic")]
    assert a1["credit_observations"] == 2
    assert a1["success"] == pytest.approx(1.0)
    assert a1["failure"] == pytest.approx(1.0)
    assert a1["pending"] == 0
    a2 = cells[(sig_a2, "dynamic-instrumentation")]
    assert a2["credit_observations"] == 1
    assert a2["success"] == pytest.approx(0.5)
    # face-2/3 rows: pending cells under the workspace CURRENT signature
    # (the replay approximation — historical signatures are unrecoverable)
    sig_b = ssig.signature_hash(ssig.snapshot(ws_b))
    b_cell = cells[(sig_b, "static-symbolic")]
    assert b_cell["pending"] == 1
    assert b_cell["credit_observations"] == 0
    sig_c = ssig.signature_hash(ssig.snapshot(ws_c))
    c_cell = cells[(sig_c, "arm-kdf")]
    assert c_cell["pending"] == 1
    assert report["signature_approximated_cells"] == 2
    # deterministic ordering
    keys = [(c["signature_hash"], c["method_family"])
            for c in report["cells"]]
    assert keys == sorted(keys)


# --------------------------------------------------- 2. hierarchical shrinkage

def _shrink_fixture():
    """anchor-family: a strong anchor (10x credit 1.0 at one OTHER
    signature) with three target cells (1 good / 1 bad / cold cell);
    diverge-family: the same anchor against 20 local failures (its own
    family, so its failures never pollute the other targets' anchors —
    the anchor is leave-one-out per CELL, not per fixture)."""
    rows = [_row("aaaaaaaaaaaa", "anchor-family", 1.0) for _ in range(10)]
    rows += [_row("bbbbbbbbbbbb", "anchor-family", 1.0)]        # 1 good
    rows += [_row("cccccccccccc", "anchor-family", 0.0)]        # 1 bad
    rows += [_row("aaaaaaaaaaaa", "diverge-family", 1.0) for _ in range(10)]
    rows += [_row("dddddddddddd", "diverge-family", 0.0)
             for _ in range(20)]                                # divergence
    rows += [_row("eeeeeeeeeeee", "brand-new", 0.0)]            # cold fam
    rows += [_row("ffffffffffff", "lonely-family", 1.0)
             for _ in range(3)]                                 # single cell
    return _store(rows)


def test_cell_with_one_sample_follows_the_global_anchor():
    fold = q_cells.fold(_shrink_fixture())
    # anchor-family totals (10x1.0 @aaaa + 1 good @bbbb + 1 bad @cccc):
    # bbbb's leave-one-out anchor = 10s + 1f -> m = 11/13, w = min(8,11) = 8
    a, b = q_cells.cell_posterior(fold, "bbbbbbbbbbbb", "anchor-family")
    assert a == pytest.approx(114.0 / 13.0, abs=1e-9)   # 1 + 8*(11/13) + 1
    assert b == pytest.approx(29.0 / 13.0, abs=1e-9)    # 1 + 8*(2/13) + 0
    # one BAD local sample still ranks by the anchor (borrowed strength)
    a2, b2 = q_cells.cell_posterior(fold, "cccccccccccc", "anchor-family")
    mean2 = a2 / (a2 + b2)
    assert mean2 > 0.7
    # monotone: more + worse local evidence -> lower posterior mean
    mean1 = a / (a + b)
    a3, b3 = q_cells.cell_posterior(fold, "dddddddddddd", "diverge-family")
    mean3 = a3 / (a3 + b3)
    assert mean1 > mean2 > mean3


def test_local_evidence_diverges_from_the_anchor():
    fold = q_cells.fold(_shrink_fixture())
    a, b = q_cells.cell_posterior(fold, "dddddddddddd", "diverge-family")
    mean = a / (a + b)
    # 20 local failures outweigh the capped anchor (w <= 8):
    # alpha = 1 + 8*(11/12) + 0 = 25/3, beta = 1 + 8*(1/12) + 20 = 65/3
    assert mean == pytest.approx(25.0 / 90.0, abs=1e-9)
    assert mean < 0.4


def test_cold_family_and_single_cell_family():
    fold = q_cells.fold(_shrink_fixture())
    # family never observed anywhere: the wide Beta(1,1); one local bad
    # sample gives (1, 2) — no anchor exists to borrow from
    a, b = q_cells.cell_posterior(fold, "eeeeeeeeeeee", "brand-new")
    assert (a, b) == (1.0, 2.0)
    # a family observed ONLY in this cell: leave-one-out anchor is empty
    # (no self-echo inflation — the cell stands on its own 3 successes)
    a2, b2 = q_cells.cell_posterior(fold, "ffffffffffff", "lonely-family")
    assert (a2, b2) == (4.0, 1.0)


def test_cold_cell_of_warm_family_uses_the_anchor():
    fold = q_cells.fold(_shrink_fixture())
    # a never-visited cell borrows the FULL family aggregate (12 rows:
    # 11s + 1f -> m = 6/7, w = 8): its posterior mean IS the anchor mean
    a, b = q_cells.cell_posterior(fold, "000000000000", "anchor-family")
    assert a == pytest.approx(55.0 / 7.0, abs=1e-9)     # 1 + 8*(6/7)
    assert b == pytest.approx(15.0 / 7.0, abs=1e-9)     # 1 + 8*(1/7)
    assert a / (a + b) == pytest.approx(11.0 / 14.0, abs=1e-9)


# --------------------------------------------- 3. sampling distribution + gamma

def _dist_store():
    return _store(
        [_row("5e5e5e5e5e5e", "fam-a", 1.0) for _ in range(12)]
        + [_row("5e5e5e5e5e5e", "fam-b", 0.0) for _ in range(12)])


def _target_probs(prior, store, sig="5e5e5e5e5e5e", gamma=q_cells.GAMMA):
    fold = q_cells.fold(store, gamma=gamma)
    raw = {}
    for fam, p in prior.items():
        a, b = q_cells.cell_posterior(fold, sig, fam)
        raw[fam] = p * (a / (a + b))
    total = sum(raw.values())
    return {f: v / total for f, v in raw.items()}


def test_sampling_distribution_matches_discounted_posterior():
    prior = {"fam-a": 0.5, "fam-b": 0.3, "fam-c": 0.2}
    store = _dist_store()
    targets = _target_probs(prior, store)
    rng = random.Random(20260929)
    counts = {f: 0 for f in prior}
    for _ in range(N_DRAWS):
        receipt = q_cells.sample_method_family(
            "5e5e5e5e5e5e", prior, store, rng=rng)
        counts[receipt["family"]] += 1
    freq = {f: c / N_DRAWS for f, c in counts.items()}
    # per-family absolute tolerance
    for f, t in targets.items():
        assert abs(freq[f] - t) <= 0.02, (f, freq[f], t)
    # chi-square goodness of fit (df=2, p=0.01 -> 9.21)
    chi2 = sum((counts[f] - N_DRAWS * t) ** 2 / (N_DRAWS * t)
               for f, t in targets.items())
    assert chi2 < CHI2_DF2_P01, (chi2, freq, targets)


def test_gamma_read_face_discounts_old_evidence():
    # fam-h: 2 OLD successes; fam-i: 2 RECENT successes (append order)
    rows = ([_row("0a0a0a0a0a0a", "fam-h", 1.0)] * 2
            + [_row("0a0a0a0a0a0a", "fam-i", 1.0)] * 2)
    store = _store(rows)
    fold_g1 = q_cells.fold(store, gamma=1.0)
    fold_g5 = q_cells.fold(store, gamma=0.5)
    h1 = fold_g1.cells[("0a0a0a0a0a0a", "fam-h")]
    h5 = fold_g5.cells[("0a0a0a0a0a0a", "fam-h")]
    i5 = fold_g5.cells[("0a0a0a0a0a0a", "fam-i")]
    # exact discounted masses (binary-exact powers of two)
    assert h1.success == pytest.approx(2.0)
    assert h5.success == pytest.approx(0.375)   # 0.5^3 + 0.5^2
    assert i5.success == pytest.approx(1.5)     # 0.5^1 + 0.5^0
    # raw rows are NEVER rewritten: same store re-folded at gamma=1 unchanged
    assert store.observations()[0]["credit"] == 1.0
    # the discount shifts the sampling target toward recent evidence
    prior = {"fam-h": 0.5, "fam-i": 0.5}
    t1 = _target_probs(prior, store, gamma=1.0)
    t5 = _target_probs(prior, store, gamma=0.5)
    assert abs(t1["fam-h"] - 0.5) < 1e-9
    assert t5["fam-i"] - t5["fam-h"] >= 0.05


def test_gamma_discount_shifts_empirical_distribution():
    rows = ([_row("0a0a0a0a0a0a", "fam-h", 1.0)] * 2
            + [_row("0a0a0a0a0a0a", "fam-i", 1.0)] * 2)
    store = _store(rows)
    prior = {"fam-h": 0.5, "fam-i": 0.5}
    targets = _target_probs(prior, store, sig="0a0a0a0a0a0a", gamma=0.5)
    rng = random.Random(777)
    counts = {"fam-h": 0, "fam-i": 0}
    for _ in range(N_DRAWS):
        r = q_cells.sample_method_family(
            "0a0a0a0a0a0a", prior, store, rng=rng, gamma=0.5)
        counts[r["family"]] += 1
    freq = {f: c / N_DRAWS for f, c in counts.items()}
    for f, t in targets.items():
        assert abs(freq[f] - t) <= 0.02, (f, freq[f], t)
    assert freq["fam-i"] > freq["fam-h"]


# --------------------------------------------------------- 4. determinism

def test_determinism_given_seed():
    store = _dist_store()
    prior = {"fam-a": 0.5, "fam-b": 0.3, "fam-c": 0.2}
    seqs, receipts = [], []
    for _ in range(2):
        rng = random.Random(4242)
        seq = [q_cells.sample_method_family(
            "5e5e5e5e5e5e", prior, store, rng=rng)["family"]
            for _ in range(50)]
        seqs.append(seq)
        rng2 = random.Random(4242)
        receipts.append(q_cells.sample_method_family(
            "5e5e5e5e5e5e", prior, store, rng=rng2))
    assert seqs[0] == seqs[1]
    assert json.dumps(receipts[0], sort_keys=True) == \
        json.dumps(receipts[1], sort_keys=True)
    # default rng=None is the Random(0) anchor-deterministic default
    r1 = q_cells.sample_method_family("5e5e5e5e5e5e", prior, store)
    r2 = q_cells.sample_method_family("5e5e5e5e5e5e", prior, store)
    assert r1["family"] == r2["family"]


def test_candidate_order_never_reshuffles_selection():
    store = _dist_store()
    prior_a = {"fam-a": 0.5, "fam-b": 0.5}
    prior_b = {"fam-b": 0.5, "fam-a": 0.5}   # same mass, other order
    r1 = q_cells.sample_method_family("5e5e5e5e5e5e", prior_a, store)
    r2 = q_cells.sample_method_family("5e5e5e5e5e5e", prior_b, store)
    assert r1["family"] == r2["family"]
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


# ------------------------------------------------- 5. Store protocol seam

class _StubStore:
    """The thin Store protocol stub — no filesystem anywhere."""

    def __init__(self, rows):
        self._rows = rows

    def observations(self):
        return list(self._rows)


def test_protocol_store_without_filesystem():
    store = _StubStore([_row("abcdabcdabcd", "fam-a", 1.0)])
    fold = q_cells.fold(store)
    receipt = q_cells.sample_method_family(
        "abcdabcdabcd", {"fam-a": 0.6, "fam-b": 0.4}, store)
    assert receipt["family"] in {"fam-a", "fam-b"}
    assert receipt["candidates"]["fam-a"]["p_llm"] == 0.6
    # fam-b is cold: the wide Beta(1,1) rides the receipt
    assert receipt["candidates"]["fam-b"]["alpha"] == 1.0
    assert receipt["candidates"]["fam-b"]["beta"] == 1.0


def test_receipt_is_attributable():
    store = _dist_store()
    receipt = q_cells.sample_method_family(
        "5e5e5e5e5e5e", {"fam-a": 0.5, "fam-b": 0.3}, store)
    assert receipt["schema"] == q_cells.SAMPLE_SCHEMA
    assert receipt["signature_hash"] == "5e5e5e5e5e5e"
    for fam in ("fam-a", "fam-b"):
        c = receipt["candidates"][fam]
        assert set(c) >= {"p_llm", "alpha", "beta", "theta", "weight"}


# ------------------------------------------------- 6. sampler input validation

def test_sampler_input_validation():
    store = _dist_store()
    with pytest.raises(ValueError):
        q_cells.sample_method_family("5e5e5e5e5e5e", {}, store)
    with pytest.raises(ValueError):
        q_cells.sample_method_family("5e5e5e5e5e5e",
                                     {"fam-a": 0.0}, store)
    with pytest.raises(ValueError):
        q_cells.sample_method_family("5e5e5e5e5e5e",
                                     {"fam-a": -0.5, "fam-b": 1.0}, store)
    with pytest.raises(ValueError):
        q_cells.sample_method_family("not-a-hash!!", {"fam-a": 1.0}, store)
    # a snapshot dict is coerced through the canonical signature face
    snap = ssig.snapshot(store if False else Path("/nonexistent-ws"))
    r = q_cells.sample_method_family(snap, {"fam-a": 1.0}, store)
    assert r["signature_hash"] == ssig.signature_hash(snap)


def test_single_candidate_always_wins():
    store = _dist_store()
    r = q_cells.sample_method_family("5e5e5e5e5e5e", {"fam-z": 1.0}, store)
    assert r["family"] == "fam-z"


# ------------------------------------------------- 7. recording faces

V1_PROMPT = ('{"kunglao_dispatch": {"version": 1, "claim": "C-12", '
             '"tier": 1, "tools": ["Bash"], '
             '"method_family": "static-symbolic"}} trace the KDF')


def test_record_dispatch_observation_v1_envelope(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    out = q_cells.record_dispatch_observation(
        ws, V1_PROMPT,
        envelope_meta={"method_family": "static-symbolic"},
        claim="C-12", agent="kunglao-worker")
    assert out["appended"] is True
    assert out["family"] == "static-symbolic"
    assert out["signature_hash"] == ssig.signature_hash(ssig.snapshot(ws))
    rows = q_cells.JSONLQStore(ws).observations()
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == q_cells.OBS_SCHEMA
    assert row["source"] == "dispatch"
    assert row["credit"] is None      # pending until settlement
    assert row["signature_hash"] == out["signature_hash"]
    assert row["method_family"] == "static-symbolic"


def test_record_dispatch_observation_prose_marker_fallback(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    prompt = '{"kunglao_dispatch": {"version": 1, "claim": "C-13", ' \
             '"tier": 1, "tools": ["Bash"]}}\n' \
             "— extract the KDF\n" \
             "method-family: dynamic-instrumentation\n"
    out = q_cells.record_dispatch_observation(ws, prompt, claim="C-13")
    assert out["appended"] is True
    assert out["family"] == "dynamic-instrumentation"


def test_record_dispatch_observation_undeclared_is_honest_gap(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    out = q_cells.record_dispatch_observation(
        ws, '{"kunglao_dispatch": {"version": 1, "claim": "C-14", '
        '"tier": 1, "tools": ["Bash"]}}\n— no declaration',
        envelope_meta=None)
    assert out["appended"] is False
    assert out["reason"] == "undeclared"
    assert not (ws / q_cells.OBS_REL).exists()


def test_observe_clamps_credit_into_the_unit_interval(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    q_cells.observe(ws, "abcdabcdabcd", "static-symbolic", 1.5)
    q_cells.observe(ws, "abcdabcdabcd", "static-symbolic", -0.25)
    q_cells.observe(ws, "abcdabcdabcd", "static-symbolic", 0.5)
    rows = q_cells.JSONLQStore(ws).observations()
    assert [r["credit"] for r in rows] == [1.0, 0.0, 0.5]
    assert all(r["source"] == "settlement" for r in rows)
    fold = q_cells.fold(q_cells.JSONLQStore(ws))
    cell = fold.cells[("abcdabcdabcd", "static-symbolic")]
    assert cell.success == pytest.approx(1.5)
    assert cell.failure == pytest.approx(1.5)


def test_dispatch_pending_and_settlement_credit_share_the_fold(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    # dispatch row: pending (credit None) — never posterior mass
    q_cells.record_dispatch_observation(
        ws, V1_PROMPT,
        envelope_meta={"method_family": "static-symbolic"}, claim="C-12")
    sig = ssig.signature_hash(ssig.snapshot(ws))
    q_cells.observe(ws, sig, "static-symbolic", 1.0)
    fold = q_cells.fold(q_cells.JSONLQStore(ws))
    cell = fold.cells[(sig, "static-symbolic")]
    assert cell.n_pending == 1
    assert cell.success == pytest.approx(1.0)


# ------------------------------------------------- 8. gate hook wiring

def test_dispatch_lifecycle_records_q_cell_observation(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(ROOT / "hooks"))
    try:
        import worker_budget_sinks as wbs
    finally:
        pass
    paths = {"workspace": str(ws)}
    # must not raise even with linkage/log modules unavailable — and the
    # recording itself must never turn the ALLOW into anything else
    wbs._dispatch_lifecycle(paths, 1, ["Bash"], "C-12", "kunglao-worker",
                            prompt=V1_PROMPT)
    rows = q_cells.JSONLQStore(ws).observations()
    assert len(rows) == 1
    assert rows[0]["method_family"] == "static-symbolic"
    assert rows[0]["signature_hash"] == ssig.signature_hash(
        ssig.snapshot(ws))
    assert rows[0]["claim"] == "C-12"


def test_dispatch_lifecycle_recording_is_fail_open(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(ROOT / "hooks"))
    import worker_budget_sinks as wbs
    # a broken workspace (file where the dir belongs) must not raise
    bad = tmp_path / "not-a-ws"
    bad.write_text("i am a file", encoding="utf-8")
    paths = {"workspace": str(bad)}
    wbs._dispatch_lifecycle(paths, 1, ["Bash"], "C-12", "kunglao-worker",
                            prompt=V1_PROMPT)  # no exception == pass
