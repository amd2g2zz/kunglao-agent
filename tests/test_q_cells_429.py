# -*- coding: utf-8 -*-
"""tests/test_q_cells_429.py — #429 §4 Q cells + DTS call site 2 (W2-T2.2).

RED-first pins for the RL kernel's action-value layer:

  1. cell formation from replayed dispatch history (reindex over a
     fixture root — the #432 usage face + the q-cell observation face);
  2. hierarchical shrinkage toward the family's global anchor
     (leave-one-out anchor; a cell with 1 sample follows the anchor
     until enough LOCAL evidence diverges; cold families stay wide);
  3. sampling distribution ~= discounted posterior probabilities
     (P_LLM ⊗ Q, seeded, chi-square tolerance) + the γ read-face decay;
     the SHIPPED default itself is the discounted adaptive schedule
     (owner ruling 2026-09-29: DTS replaces TS — no plain-TS default);
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

    # gamma=1.0 explicit: this pin is the CELL-FORMATION face (exact
    # counts, pending joins, ordering). The shipped default itself is the
    # discounted adaptive schedule (owner ruling 2026-09-29, DTS replaces
    # TS) and is pinned by test_shipped_default_fold_is_the_discounted_
    # adaptive_schedule — not re-pinned here.
    report = q_cells.reindex(root, gamma=1.0)

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
    fold = _shrink_fold(_shrink_fixture())
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
    fold = _shrink_fold(_shrink_fixture())
    a, b = q_cells.cell_posterior(fold, "dddddddddddd", "diverge-family")
    mean = a / (a + b)
    # 20 local failures outweigh the capped anchor (w <= 8):
    # alpha = 1 + 8*(11/12) + 0 = 25/3, beta = 1 + 8*(1/12) + 20 = 65/3
    assert mean == pytest.approx(25.0 / 90.0, abs=1e-9)
    assert mean < 0.4


def test_cold_family_and_single_cell_family():
    fold = _shrink_fold(_shrink_fixture())
    # family never observed anywhere: the wide Beta(1,1); one local bad
    # sample gives (1, 2) — no anchor exists to borrow from
    a, b = q_cells.cell_posterior(fold, "eeeeeeeeeeee", "brand-new")
    assert (a, b) == (1.0, 2.0)
    # a family observed ONLY in this cell: leave-one-out anchor is empty
    # (no self-echo inflation — the cell stands on its own 3 successes)
    a2, b2 = q_cells.cell_posterior(fold, "ffffffffffff", "lonely-family")
    assert (a2, b2) == (4.0, 1.0)


def test_cold_cell_of_warm_family_uses_the_anchor():
    fold = _shrink_fold(_shrink_fixture())
    # a never-visited cell borrows the FULL family aggregate (12 rows:
    # 11s + 1f -> m = 6/7, w = 8): its posterior mean IS the anchor mean
    a, b = q_cells.cell_posterior(fold, "000000000000", "anchor-family")
    assert a == pytest.approx(55.0 / 7.0, abs=1e-9)     # 1 + 8*(6/7)
    assert b == pytest.approx(15.0 / 7.0, abs=1e-9)     # 1 + 8*(1/7)
    assert a / (a + b) == pytest.approx(11.0 / 14.0, abs=1e-9)


# --------------------------------------------- 3. sampling distribution + gamma

def _shrink_fold(store):
    """Shrinkage pins need EXACT masses: fold at the explicit constant
    γ = 1 (the calibration face). Owner ruling 2026-09-29 (DTS replaces
    TS): the SHIPPED default fold is the adaptive schedule and is pinned
    by test_shipped_default_fold_is_the_discounted_adaptive_schedule —
    these tests pin the shrinkage ARITHMETIC, not the shipped default,
    so they select the constant explicitly."""
    return q_cells.fold(store, gamma=1.0)


def _dist_store():
    return _store(
        [_row("5e5e5e5e5e5e", "fam-a", 1.0) for _ in range(12)]
        + [_row("5e5e5e5e5e5e", "fam-b", 0.0) for _ in range(12)])


def _target_probs(prior, store, sig="5e5e5e5e5e5e", gamma=None):
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


def test_shipped_default_fold_is_the_discounted_adaptive_schedule():
    """Owner ruling 2026-09-29: DTS REPLACES TS as the one engine — the
    SHIPPED default fold is the #428 EX-2-calibrated adaptive schedule
    (imported from rlvr.posteriors, one source of truth), not the γ = 1
    no-forgetting fold. The plain-TS default is dead."""
    from rlvr import posteriors as rp  # noqa: PLC0415
    rows = ([_row("0b0b0b0b0b0b", "fam-dts", 1.0)] * 2
            + [_row("0b0b0b0b0b0b", "fam-dts", 0.0)] * 2)
    store = _store(rows)
    # decay is ACTIVE by default: default masses < γ = 1 masses
    d = q_cells.fold(store).cells[("0b0b0b0b0b0b", "fam-dts")]
    u = q_cells.fold(store, gamma=1.0).cells[("0b0b0b0b0b0b", "fam-dts")]
    assert d.evidence < u.evidence
    # the default IS the posteriors default schedule — bit-identical
    # masses (single source of truth: no duplicated constants here)
    s = q_cells.fold(store, gamma=rp.default_schedule()).cells[
        ("0b0b0b0b0b0b", "fam-dts")]
    assert d.success == s.success
    assert d.failure == s.failure
    # and NOT any constant: a constant-γ replay cannot reproduce the
    # adaptive γ stream's masses (floor 0.8, λ 0.9 — EX-2)
    for const in (0.8, 0.9, 0.95, 1.0):
        c = q_cells.fold(store, gamma=const).cells[
            ("0b0b0b0b0b0b", "fam-dts")]
        assert (c.success, c.failure) != (d.success, d.failure), const


def test_default_sampling_distribution_is_decay_active():
    """The shipped default itself (no override) discounts recency into
    the sampling distribution: default targets move toward recent
    evidence versus the γ = 1 targets, and the sampler's default
    empirical distribution matches the DEFAULT targets. The receipt
    reports the schedule's post-replay γ — the adaptive band, never
    pinned at 1.0."""
    rows = ([_row("0c0c0c0c0c0c", "fam-old", 1.0)] * 4
            + [_row("0c0c0c0c0c0c", "fam-new", 0.0)] * 4)
    store = _store(rows)
    prior = {"fam-old": 0.5, "fam-new": 0.5}
    t_default = _target_probs(prior, store, sig="0c0c0c0c0c0c")
    t_unit = _target_probs(prior, store, sig="0c0c0c0c0c0c", gamma=1.0)
    # the default moved the distribution versus no-forgetting (recent
    # failures discounted lighter -> fam-new's share rises)
    assert t_default["fam-new"] > t_unit["fam-new"]
    assert t_default["fam-old"] < t_unit["fam-old"]
    rng = random.Random(31337)
    counts = {"fam-old": 0, "fam-new": 0}
    for _ in range(N_DRAWS):
        r = q_cells.sample_method_family(
            "0c0c0c0c0c0c", prior, store, rng=rng)
        counts[r["family"]] += 1
    freq = {f: c / N_DRAWS for f, c in counts.items()}
    for f, t in t_default.items():
        assert abs(freq[f] - t) <= 0.02, (f, freq[f], t)
    # the decay shifts weight, it does not invert the ranking: fam-old
    # (successes) still dominates fam-new (failures) — the pin is that
    # the DEFAULT distribution matches the DECAYED targets (above), not
    # the γ = 1 targets (t_default["fam-new"] > t_unit["fam-new"])
    assert freq["fam-old"] > freq["fam-new"]
    # receipt γ: the default schedule's post-replay γ (adaptive band)
    r2 = q_cells.sample_method_family(
        "0c0c0c0c0c0c", prior, store, rng=random.Random(1))
    assert 0.8 <= r2["gamma"] < 1.0


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
    # gamma=1.0 explicit: this pin is the CLAMPING face (exact masses);
    # the shipped default is the DTS adaptive schedule (ruling 2026-09-29)
    fold = q_cells.fold(q_cells.JSONLQStore(ws), gamma=1.0)
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


# ------------------------- 10. the seed contract at call site 2 (462 gate)

def test_seed_state_hashes_the_round_cold_start_unfreezes(tmp_path):
    """462 design-review MEDIUM-1: the #251 contract f(store state,
    round) — the round rides INSIDE the hashed payload, so distinct
    rounds produce distinct seeds even on an evidence-free workspace
    (the round used to be computed and returned but never hashed,
    freezing the cold draw)."""
    import json as _json
    ws = tmp_path / "ws"
    ws.mkdir()
    # a fake convergence ledger whose snapshot-row count IS the round:
    # 0..4 -> five advancing rounds, no evidence anywhere
    seeds = []
    for rnd in range(5):
        ledger = ws / ".convergence_ledger.jsonl"
        rows = [{"open_count": 1} for _ in range(rnd)] \
            + [{"type": "event"}]  # the event row is not a snapshot
        ledger.write_text(
            "\n".join(_json.dumps(r) for r in rows) + "\n",
            encoding="utf-8")
        rng, rnd_out = q_cells.q_cells_seed_state(ws)
        assert rnd_out == rnd
        seeds.append(rng.random())
    assert len(set(seeds)) == 5, \
        "distinct rounds must produce distinct draws (cold start " \
        "unfreezes)"


# ------------------------------------------- 9. settlement feed (462 W5)

def test_settlement_feed_class_is_a_module_member():
    """Collection sentinel (review CRITICAL): an edit once glued this
    class header onto the preceding comment line, dead-nesting all five
    W5 pins inside the previous function (invisible to ruff, the
    hygiene lints, and the manifest). A class glued to a comment never
    becomes a module attribute — this pin fails loudly instead."""
    import sys
    assert hasattr(sys.modules[__name__], "TestSettlementFeed462"), \
        "TestSettlementFeed462 lost its module scope — the W5 pins " \
        "are not being collected"


class TestSettlementFeed462:
    """issue 462 W5: the settlement feed — settled round credits reach
    the Q-cell fold. The missing observe() call was the difference
    between a learning system and a logging system: the fold saw only
    dispatch rows with credit=None, so cells could never learn."""

    @staticmethod
    def _cited(aid: str, creator: str) -> dict:
        return {"id": aid, "creator": creator, "status": "PROVEN",
                "verify_status": "passes", "cited_by_deliverable": True}

    def test_settle_banks_the_matching_q_cell_credit(self, tmp_path):
        """The acceptance integration: settle -> observe -> cell credit
        non-None -> the fold carries real posterior mass."""
        import rollout_ledger as rl
        import scalar_settlement as ss
        ws = tmp_path / "ws"
        ws.mkdir()
        q_cells.record_dispatch_observation(
            ws, V1_PROMPT,
            envelope_meta={"method_family": "static-symbolic"},
            claim="tr-m1-d1")
        sig = ssig.signature_hash(ssig.snapshot(ws))
        res = ss.settle_round_credit(
            ws, [{"dispatch_id": "tr-m1-d1", "round": 1}],
            [self._cited("F1", "tr-m1-d1")], [],
            now="2026-09-30T00:00:00Z")
        assert res["settled"] == 1
        rows = q_cells.JSONLQStore(ws).observations()
        banked = [r for r in rows if r["source"] == "settlement"]
        assert len(banked) == 1
        assert banked[0]["credit"] is not None
        assert banked[0]["credit"] == pytest.approx(1.0)  # the ladder value
        assert banked[0]["signature_hash"] == sig
        assert banked[0]["method_family"] == "static-symbolic"
        assert banked[0]["dispatch_id"] == "tr-m1-d1"
        # the fold now learns: real mass in the cell (shipped default fold)
        fold = q_cells.fold(q_cells.JSONLQStore(ws))
        cell = fold.cells[(sig, "static-symbolic")]
        assert cell.success + cell.failure > 0.0
        assert rl.fold(ws, "round_credit/tr-m1-d1") is not None

    def test_unmatched_dispatch_is_the_honest_gap(self, tmp_path):
        """No pending dispatch row for the settled dispatch id: no row,
        never a fabricated bucket (the record_dispatch_observation
        posture)."""
        import scalar_settlement as ss
        ws = tmp_path / "ws"
        ws.mkdir()
        q_cells.record_dispatch_observation(
            ws, V1_PROMPT,
            envelope_meta={"method_family": "static-symbolic"},
            claim="tr-m1-d1")
        res = ss.settle_round_credit(
            ws, [{"dispatch_id": "tr-m9-z9", "round": 1}],
            [self._cited("F9", "tr-m9-z9")], [],
            now="2026-09-30T00:00:00Z")
        assert res["settled"] == 1  # the ledger row settles fine
        rows = q_cells.JSONLQStore(ws).observations()
        assert len(rows) == 1  # only the original dispatch row
        assert rows[0]["source"] == "dispatch"

    def test_retry_after_recorded_but_unsettled_banks(self, tmp_path):
        """Review MEDIUM fix: the exactly-once guard tests settlement
        PRESENCE in the fold, not row existence — a first run that
        recorded the round_credit identity row but failed/died before
        settling must bank on the retry (the old row-existence guard
        silently skipped that round's credit forever)."""
        import rollout_ledger as rl
        import scalar_settlement as ss
        ws = tmp_path / "ws"
        ws.mkdir()
        q_cells.record_dispatch_observation(
            ws, V1_PROMPT,
            envelope_meta={"method_family": "static-symbolic"},
            claim="tr-m1-d1")
        # the prior run's record face: identity row, NO settlement
        rl.record(ws, kind="round_credit", anchor="tr-m1-d1",
                  signals=[{"type": "round_credit_signal",
                            "source": "scalar_settlement", "value": {},
                            "ts": "2026-09-30T00:00:00Z"}],
                  ts="2026-09-30T00:00:00Z")
        assert rl.fold(ws, "round_credit/tr-m1-d1") is not None
        assert rl.fold(ws, "round_credit/tr-m1-d1").get(
            "settlement") is None
        res = ss.settle_round_credit(
            ws, [{"dispatch_id": "tr-m1-d1", "round": 1}],
            [self._cited("F1", "tr-m1-d1")], [],
            now="2026-09-30T01:00:00Z")
        assert res["settled"] == 1
        banked = [r for r in q_cells.JSONLQStore(ws).observations()
                  if r["source"] == "settlement"]
        assert len(banked) == 1, \
            "the retry settlement must bank the credit"

    def test_replay_never_double_banks(self, tmp_path):
        """The learning clock banks each dispatch credit exactly once: a
        settlement replay (duplicate fold) appends no second credit row,
        and the late-cite amendment path refines the LEDGER only — the
        append-only observation log has no retraction face."""
        import scalar_settlement as ss
        ws = tmp_path / "ws"
        ws.mkdir()
        q_cells.record_dispatch_observation(
            ws, V1_PROMPT,
            envelope_meta={"method_family": "static-symbolic"},
            claim="tr-m1-d1")
        dispatches = [{"dispatch_id": "tr-m1-d1", "round": 1}]
        ss.settle_round_credit(ws, dispatches,
                               [self._cited("F1", "tr-m1-d1")], [],
                               now="2026-09-30T00:00:00Z")
        # replay: identical settlement (duplicate) banks nothing new
        ss.settle_round_credit(ws, dispatches,
                               [self._cited("F1", "tr-m1-d1")], [],
                               now="2026-09-30T06:00:00Z")
        # late-cite amendment: refines the ledger, still no second bank
        ss.settle_round_credit(ws, dispatches,
                               [self._cited("F2", "tr-m1-d1")], [],
                               now="2026-09-30T07:00:00Z")
        banked = [r for r in q_cells.JSONLQStore(ws).observations()
                  if r["source"] == "settlement"]
        assert len(banked) == 1

    def test_credit_boundary_clamps_into_the_unit_interval(self, tmp_path):
        """A negative round credit (waste outran credit) clamps to 0.0 at
        the observation boundary — r_r is rail-clamped per #429 §4."""
        import scalar_settlement as ss
        ws = tmp_path / "ws"
        ws.mkdir()
        q_cells.record_dispatch_observation(
            ws, V1_PROMPT,
            envelope_meta={"method_family": "static-symbolic"},
            claim="tr-m1-d1")
        sig = ssig.signature_hash(ssig.snapshot(ws))
        waste = [{"dispatch_id": "tr-m1-d1"}]  # one attributed waste
        ss.settle_round_credit(
            ws, [{"dispatch_id": "tr-m1-d1", "round": 1}],
            [dict(self._cited("F1", "tr-m1-d1"),
                  cited_by_deliverable=False)], waste,
            now="2026-09-30T00:00:00Z")
        banked = [r for r in q_cells.JSONLQStore(ws).observations()
                  if r["source"] == "settlement"]
        assert len(banked) == 1
        assert banked[0]["credit"] == 0.0
        fold = q_cells.fold(q_cells.JSONLQStore(ws))
        assert fold.cells[(sig, "static-symbolic")].failure \
            == pytest.approx(1.0)
