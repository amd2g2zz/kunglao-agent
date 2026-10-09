# -*- coding: utf-8 -*-
"""tests/test_refutation_fold_582.py — the refutation fold (adversarial
memory).

Refuted verify transitions aggregate by feature signature x claim
boundary type into a per-signature refutation rate; the rate feeds two
consumers (a feature token and a verify-cadence multiplier) and decays
under honest verification streaks (the decay guard: never a permanent
tax, never negative density).

Sections:
  1. the fold math (gamma fold over synthetic transition sets,
     signature/boundary bucketing, the verdict->credit mapping reuse)
  2. the decay guard (monotone honest-streak decay, bounded multiplier)
  3. cross-engagement (the keyed store substrate: a second workspace
     inherits the raised density for the same signature)
  4. the feature-token face (additive token outside the mined fields)
  5. the cadence read point (the single age reader sees the multiplier)
  6. the compose face (strategy key outside the content hash, seam
     section only when the multiplier is active)
  7. fail-open degradation (broken reads land on the zero face, loud)

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (SCRIPTS,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import compose  # noqa: E402
from rlvr import feature_prior as fp  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402
from rlvr import refutation_fold as rf  # noqa: E402
from rlvr import strategy_store as ss  # noqa: E402
import convergence_check as cc  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- helpers

def _ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def _verify_row(sig: str, *, refuted: bool, boundary: str = "verify",
                variant: str = "verify") -> dict:
    return {
        "ts": "2026-10-09T00:00:00Z",
        "dispatch_id": "C-1",
        "action_type": "verify",
        "s": sig,
        "a": "verify-act",
        "o": {"status": "DISPATCHED", "class": variant,
              "facts": 0, "variant": variant},
        "s_prime_phi": 0.0,
        "phi_before": 0.0,
        "r_incr": 0.0,
        "r_settle": 0.0 if refuted else 1.0,
        "done": True,
    }


def _write_ledger(ws: Path, rows: list[dict]) -> None:
    (ws / "runs" / "transitions.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")


def _sig_patch(monkeypatch, sig: str) -> None:
    monkeypatch.setattr(rf, "_workspace_signature", lambda ws: sig,
                        raising=True)


# ===========================================================================
# 1. the fold math
# ===========================================================================

def test_zero_face_is_the_inert_landing(tmp_path: Path) -> None:
    face = rf.fold(_ws(tmp_path))
    assert face == {"buckets": {}, "rates": {},
                    "mine": {"signature": "none", "refuted": 0.0,
                             "honest": 0.0, "rate": 0.0},
                    "multiplier": 1.0}
    assert rf.cadence_multiplier(_ws(tmp_path)) == 1.0


def test_rate_over_synthetic_transitions_exact_gamma_fold(
        tmp_path: Path, monkeypatch) -> None:
    """One refuted then one honest verify at one signature: the folded
    rate is the exact recurrence value (ref, hon) <- g*(ref, hon)+obs."""
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _write_ledger(ws, [_verify_row("K1", refuted=True),
                       _verify_row("K1", refuted=False)])
    face = rf.fold(ws)
    ref = rf.FOLD_GAMMA * 0.0 + 1.0          # refuted lands first
    ref = rf.FOLD_GAMMA * ref + 0.0          # honest row adds no ref mass
    hon = rf.FOLD_GAMMA * 0.0 + 0.0
    hon = rf.FOLD_GAMMA * hon + 1.0
    expected = ref / (ref + hon)
    bucket = face["buckets"]["K1|verify"]
    assert bucket["refuted"] == pytest.approx(ref)
    assert bucket["honest"] == pytest.approx(hon)
    assert bucket["rate"] == pytest.approx(expected)
    assert face["rates"]["K1"] == pytest.approx(expected)
    assert face["mine"]["rate"] == pytest.approx(expected)


def test_signature_and_boundary_bucketing_is_independent(
        tmp_path: Path, monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _write_ledger(ws, [
        _verify_row("K1", refuted=True),
        _verify_row("K2", refuted=False),
        _verify_row("K1", refuted=True, boundary="redteam",
                    variant="redteam"),
        _verify_row("K1", refuted=False),
    ])
    face = rf.fold(ws)
    g = rf.FOLD_GAMMA
    # K1|verify = [refuted, honest]: the honest row discounts the
    # refuted mass too (newer evidence dominates)
    assert face["buckets"]["K1|verify"]["rate"] == pytest.approx(
        g / (g + 1.0))
    assert face["buckets"]["K1|redteam"]["rate"] == 1.0
    assert face["buckets"]["K2|verify"]["rate"] == 0.0
    assert set(face["rates"]) == {"K1", "K2"}


def test_non_verify_rows_and_unset_credit_never_score(
        tmp_path: Path, monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    dispatch = _verify_row("K1", refuted=True)
    dispatch["action_type"] = "dispatch"       # wrong action type
    pending = _verify_row("K1", refuted=False)
    pending["r_settle"] = None                 # never settled
    weird = _verify_row("K1", refuted=False)
    weird["r_settle"] = 0.5                    # not the credit vocabulary
    _write_ledger(ws, [dispatch, pending, weird])
    face = rf.fold(ws)
    assert face["buckets"] == {}
    assert face["mine"]["rate"] == 0.0


def test_refuted_predicate_follows_verify_credit_mapping(
        tmp_path: Path, monkeypatch) -> None:
    """The fold never re-derives the verdict->credit rule: a row banks a
    refutation exactly when verify_credit of the verdict would be 0."""
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    rows = []
    for verdict, refuted in (("verified", False), ("CONFIRMED", False),
                             ("REFUTED", True),
                             ("UNVERIFIED-WITH-GAP", True),
                             ("TIMEOUT", True)):
        row = _verify_row("K1", refuted=refuted)
        row["r_settle"] = ir.verify_credit(verdict)
        rows.append(row)
    _write_ledger(ws, rows)
    face = rf.fold(ws)
    g = rf.FOLD_GAMMA
    assert face["buckets"]["K1|verify"]["refuted"] == pytest.approx(
        g * g + g + 1.0)  # REFUTED, then the gap, then TIMEOUT land and age
    # the three refutations land AFTER the honest mass and discount it
    assert face["buckets"]["K1|verify"]["honest"] == pytest.approx(
        (g ** 3) * (1.0 + g))


def test_multi_refutation_heavy_state_raises_the_rate(
        tmp_path: Path, monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _write_ledger(ws, [_verify_row("K1", refuted=True)] * 4
                  + [_verify_row("K1", refuted=False)])
    face = rf.fold(ws)
    g = rf.FOLD_GAMMA
    # the honest row lands last: hon = 1, ref = the discounted 4-row mass
    ref = (g ** 4 + g ** 3 + g ** 2 + g)
    assert face["mine"]["rate"] == pytest.approx(ref / (ref + 1.0))
    assert face["multiplier"] == pytest.approx(
        1.0 + (rf.MULT_MAX - 1.0) * face["mine"]["rate"])
    assert rf.MULT_MIN <= face["multiplier"] <= rf.MULT_MAX


# ===========================================================================
# 2. the decay guard
# ===========================================================================

def test_honest_streak_decays_monotonically(tmp_path: Path,
                                            monkeypatch) -> None:
    """The guard: with refutations stopped, every honest verify row
    folds the rate DOWN, monotonically, never below zero."""
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    rates = []
    rows: list[dict] = []
    for i in range(30):
        rows.append(_verify_row("K1", refuted=(i == 0)))
        _write_ledger(ws, list(rows))
        rates.append(rf.fold(ws)["mine"]["rate"])
    assert rates[0] == 1.0
    for a, b in zip(rates, rates[1:]):
        assert b <= a
    assert all(r >= 0.0 for r in rates)
    assert rates[-1] < rf.WARM_RATE  # the streak restored near-baseline


def test_multiplier_bounded_and_restores_baseline(tmp_path: Path,
                                                  monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    rows = [_verify_row("K1", refuted=True)] * 6
    _write_ledger(ws, rows)
    hot = rf.fold(ws)
    assert hot["multiplier"] == pytest.approx(rf.MULT_MAX)  # rate 1.0
    _write_ledger(ws, rows + [_verify_row("K1", refuted=False)] * 40)
    healed = rf.fold(ws)
    assert rf.MULT_MIN <= healed["multiplier"] < hot["multiplier"]
    assert healed["multiplier"] < 1.0 + (rf.MULT_MAX - 1.0) * rf.WARM_RATE


def test_honest_only_ledger_never_leaves_baseline(tmp_path: Path,
                                                  monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _write_ledger(ws, [_verify_row("K1", refuted=False)] * 5)
    face = rf.fold(ws)
    assert face["mine"]["rate"] == 0.0
    assert face["multiplier"] == 1.0
    assert rf.cadence_multiplier(ws) == 1.0


def test_tier_faces_for_the_feature_token(tmp_path: Path,
                                          monkeypatch) -> None:
    assert rf.tier(0.0) is None
    assert rf.tier(0.3) == "warm"
    assert rf.tier(0.9) == "hot"


# ===========================================================================
# 3. cross-engagement (the keyed store substrate)
# ===========================================================================

def test_second_workspace_inherits_raised_density(
        tmp_path: Path, monkeypatch) -> None:
    alpha = _ws(tmp_path, "alpha")
    beta = _ws(tmp_path, "beta")
    _sig_patch(monkeypatch, "K shared")
    res = rf.record_verify_outcome(alpha, verdict="REFUTED",
                                   boundary="redteam")
    assert res.get("appended") is True
    # beta: no local ledger at all — the inherited row raises the density
    face_b = rf.fold(beta)
    assert face_b["buckets"]["K shared|redteam"]["refuted"] >= 1.0
    assert face_b["mine"]["rate"] > 0.0
    assert face_b["multiplier"] > 1.0
    # the second workspace's own cadence face sees it too
    assert rf.cadence_multiplier(beta) > 1.0


def test_own_store_rows_never_double_count(tmp_path: Path,
                                           monkeypatch) -> None:
    """A workspace with the refutation in BOTH its ledger and the store
    counts it exactly once (own store rows are duplicates of the
    ledger's truth, never extra evidence)."""
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path, "alpha")
    _write_ledger(ws, [_verify_row("K1", refuted=True)])
    rf.record_verify_outcome(ws, verdict="REFUTED", boundary="verify")
    face = rf.fold(ws)
    assert face["buckets"]["K1|verify"]["refuted"] == pytest.approx(1.0)
    assert face["mine"]["refuted"] == pytest.approx(1.0)


def test_cross_honest_rows_decay_the_inherited_density(
        tmp_path: Path, monkeypatch) -> None:
    alpha = _ws(tmp_path, "alpha")
    beta = _ws(tmp_path, "beta")
    _sig_patch(monkeypatch, "K shared")
    rf.record_verify_outcome(alpha, verdict="REFUTED")
    before = rf.fold(beta)["multiplier"]
    rf.record_verify_outcome(alpha, verdict="verified")
    rf.record_verify_outcome(alpha, verdict="verified")
    after = rf.fold(beta)["multiplier"]
    assert before > after >= 1.0


def test_mismatched_signature_never_inherits(tmp_path: Path,
                                             monkeypatch) -> None:
    alpha = _ws(tmp_path, "alpha")
    beta = _ws(tmp_path, "beta")
    sigs = {"alpha": "K-a", "beta": "K-b"}
    monkeypatch.setattr(rf, "_workspace_signature",
                        lambda ws: sigs[Path(ws).name], raising=True)
    rf.record_verify_outcome(alpha, verdict="REFUTED")
    face_b = rf.fold(beta)
    assert face_b["mine"]["rate"] == 0.0
    assert face_b["multiplier"] == 1.0


def test_record_reuses_the_credit_mapping(tmp_path: Path,
                                          monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path, "alpha")
    rf.record_verify_outcome(ws, verdict="CONFIRMED")
    rf.record_verify_outcome(ws, verdict="REFUTED", boundary="redteam")
    rows = ss.load_rows(ws=None)
    mine = [r for r in rows if r.get("arm_key") == rf.STORE_ARM]
    assert [r["credit"] for r in mine] == [1.0, 0.0]
    assert mine[1]["status"] == "redteam"


# ===========================================================================
# 4. the feature-token face
# ===========================================================================

def test_feature_tokens_gains_the_refutation_tier_token() -> None:
    base = {"lane": "apk"}
    plain = fp.feature_tokens(base)
    assert not any(t.startswith("refute:") for t in plain)
    carried = fp.feature_tokens({**base, fp.REFUTATION_TIER_KEY: "hot"})
    assert "refute:hot" in carried
    assert fp.feature_tokens({**base, fp.REFUTATION_TIER_KEY: "warm"}) \
        == (plain | {"refute:warm"})


def test_with_refutation_token_is_additive_and_immutable(
        tmp_path: Path, monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _write_ledger(ws, [_verify_row("K1", refuted=True)] * 3)
    feats = {"lane": "apk"}
    out = fp.with_refutation_token(ws, feats)
    assert out is not feats                       # the input is never mutated
    assert feats == {"lane": "apk"}
    assert out[fp.REFUTATION_TIER_KEY] == "hot"
    assert fp.feature_tokens(out) >= {"lane=apk", "refute:hot"}


def test_with_refutation_token_inert_without_refutations(
        tmp_path: Path, monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    feats = {"lane": "apk"}
    out = fp.with_refutation_token(ws, feats)
    assert out == feats
    assert fp.REFUTATION_TIER_KEY not in out


def test_feature_key_digest_stays_fold_blind(tmp_path: Path,
                                             monkeypatch) -> None:
    """The keyed store's feature key must never re-key when the fold
    activates: the digest reads the mined fields only, never the tier
    token."""
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n", encoding="utf-8")
    before = ss.feature_key_of(ws)
    _write_ledger(ws, [_verify_row("K1", refuted=True)] * 4)
    after = ss.feature_key_of(ws)
    assert before == after


# ===========================================================================
# 5. the cadence read point
# ===========================================================================

def _partial_fact(ws: Path, fid: str, created: datetime) -> None:
    (ws / "facts").mkdir(exist_ok=True)
    (ws / "facts" / f"{fid}.md").write_text(
        f"---\nid: {fid}\ncreated: {created.isoformat()}\n"
        f"verified: pending\n---\nbody\n", encoding="utf-8")
    (ws / "facts" / "_INDEX.md").write_text(
        f"| {fid} | PARTIAL | note |\n", encoding="utf-8")


def _partials_stub(ws: Path, fid: str) -> list:
    return [{"fact": fid, "status": "PARTIAL"}]


def test_explicit_ticks_caller_stays_deterministic(
        tmp_path: Path, monkeypatch) -> None:
    """The determinism wall: an explicit ticks argument bypasses the
    fold entirely (existing pins and the tick chip keep exact values)."""
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _write_ledger(ws, [_verify_row("K1", refuted=True)] * 4)
    _partial_fact(ws, "F001", NOW - timedelta(hours=48))
    rows = cc.partial_fact_ages(ws, partials=_partials_stub(ws, "F001"),
                                ticks=12.0, now=NOW)
    assert rows[0]["stale"] is True
    rows = cc.partial_fact_ages(ws, partials=_partials_stub(ws, "F001"),
                                ticks=1e9, now=NOW)
    assert rows[0]["stale"] is False


def test_refutations_lower_the_effective_threshold(
        tmp_path: Path, monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    base = cc._verify_stale_ticks()
    interval_hours = cc._TICK_INTERVAL_MIN / 60.0
    _write_ledger(ws, [_verify_row("K1", refuted=True)] * 4)
    eff = cc._effective_stale_ticks(ws)
    assert base / rf.MULT_MAX <= eff < base
    # a fact older than the multiplied threshold but younger than the
    # base one goes stale (density raised, no new gate invented)
    target_ticks = (base + base / rf.MULT_MAX) / 2.0
    age = timedelta(hours=target_ticks * interval_hours)
    _partial_fact(ws, "F001", NOW - age)
    rows = cc.partial_fact_ages(ws, partials=_partials_stub(ws, "F001"),
                                now=NOW)
    assert rows[0]["stale"] is True


def test_effective_threshold_rejects_out_of_domain_reads(
        tmp_path: Path, monkeypatch) -> None:
    """A poisoned leaf read (a value the fold cannot produce by
    construction) is refused at the consumer — fail-open to the exact
    policy threshold, never an unbounded density move."""
    ws = _ws(tmp_path)
    base = cc._verify_stale_ticks()
    assert cc._effective_stale_ticks(ws) == base  # no refutations: exact
    monkeypatch.setattr(rf, "cadence_multiplier",
                        lambda target: 99.0, raising=True)
    assert cc._effective_stale_ticks(ws) == base
    monkeypatch.setattr(rf, "cadence_multiplier",
                        lambda target: -1.0, raising=True)
    assert cc._effective_stale_ticks(ws) == base


def test_multiplier_never_negative_density(tmp_path: Path,
                                           monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _write_ledger(ws, [_verify_row("K1", refuted=True)] * 4)
    mult = rf.cadence_multiplier(ws)
    assert rf.MULT_MIN <= mult <= rf.MULT_MAX
    base = cc._verify_stale_ticks()
    assert base / mult > 0.0  # density stays positive, never inverted


# ===========================================================================
# 6. the compose face
# ===========================================================================

def _spec(ws: Path) -> None:
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n"
        "goal_verbatim: retrieve the family config\n"
        "success_criterion: family named with evidence\n"
        "verification_method: static\n", encoding="utf-8")


def test_strategy_key_rides_outside_the_content_hash(
        tmp_path: Path, monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _spec(ws)
    cold = compose.compose(ws, 1)
    assert "refutation" in cold
    assert cold["refutation"] == {"rate": 0.0, "multiplier": 1.0}
    _write_ledger(ws, [_verify_row("K1", refuted=True)] * 4)
    hot = compose.compose(ws, 1)
    # the sections are byte-identical (cold start silence) -> same hash
    assert hot["content_hash"] == cold["content_hash"]
    assert hot["refutation"]["multiplier"] == pytest.approx(rf.MULT_MAX)


def test_seam_section_renders_only_when_multiplier_active(
        tmp_path: Path, monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    _spec(ws)
    obj = compose.compose(ws, 1)
    assert compose.write_seam(ws, obj)["written"] is True
    doc = json.loads((ws / compose.SEAM_REL).read_text(encoding="utf-8"))
    assert not any(s["title"] == "refutation-defense"
                   for s in doc["sections"])
    _write_ledger(ws, [_verify_row("K1", refuted=True)] * 4)
    obj = compose.compose(ws, 2)
    compose.write_seam(ws, obj)
    doc = json.loads((ws / compose.SEAM_REL).read_text(encoding="utf-8"))
    section = next(s for s in doc["sections"]
                   if s["title"] == "refutation-defense")
    assert "rate 1.00" in section["body"]
    assert "honest verification" in section["body"]


def _legacy_tick(refutation: dict | None = None) -> dict:
    obj = {
        "schema": compose.SCHEMA, "tick": 0, "ts": "t",
        "state_fingerprint": "0123456789ab", "composed_from": [],
        "content_hash": "0" * 64,
        "debt": {"D": 0.0, "slope": None, "top": None},
        "dispatch": {"method_lead": None, "anti_hints": [],
                     "budget_hint": None},
        "loop": {"monitor_focus": [], "ping_policy": "p",
                 "stall_rules": []},
        "hooks": {"cards": []},
        "amendments": [],
    }
    if refutation is not None:
        obj["refutation"] = refutation
    return obj


def test_validator_accepts_legacy_ticks_without_the_key() -> None:
    assert compose.validate_strategy(_legacy_tick()) == []
    errors = compose.validate_strategy(
        _legacy_tick({"rate": 2.0, "multiplier": -1.0}))
    assert any("rate" in e for e in errors)
    assert any("multiplier" in e for e in errors)


# ===========================================================================
# 7. fail-open degradation
# ===========================================================================

def test_corrupt_ledger_lands_zero_face(tmp_path: Path,
                                        monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path)
    (ws / "runs" / "transitions.jsonl").write_text(
        "{not json}\n", encoding="utf-8")
    face = rf.fold(ws)
    assert face["multiplier"] == 1.0
    assert rf.cadence_multiplier(ws) == 1.0


def test_store_failure_fails_open_loud(tmp_path: Path,
                                       monkeypatch) -> None:
    _sig_patch(monkeypatch, "K1")
    ws = _ws(tmp_path, "alpha")
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "store-root"))
    store_root = tmp_path / "store-root"
    store_root.mkdir(parents=True)
    (store_root / "posterior-store.jsonl").write_text(
        "garbage line\n", encoding="utf-8")
    # the append lands past the corrupt line; the schema-enforced read
    # skips the garbage and keeps the one well-formed row
    res = rf.record_verify_outcome(ws, verdict="REFUTED")
    assert res.get("appended") is True
    rows = [r for r in ss.load_rows(ws=None)
            if r.get("arm_key") == rf.STORE_ARM]
    assert len(rows) == 1
    assert rows[0]["credit"] == 0.0


def test_record_refuses_holdout_contaminated_rows(
        tmp_path: Path, monkeypatch) -> None:
    """The firewall rides the shared append face: a row whose serialized
    form carries a holdout unit-id is refused, not appended."""
    ws = _ws(tmp_path, "unit-nine")  # the workspace id carries the id
    _sig_patch(monkeypatch, "K1")
    monkeypatch.setattr(ss, "holdout_unit_ids",
                        lambda: {"unit-nine"}, raising=True)
    res = rf.record_verify_outcome(ws, verdict="REFUTED",
                                   signature="K1")
    assert res.get("appended") is False
    assert str(res.get("reason", "")).startswith("holdout-filter")


if __name__ == "__main__":  # pragma: no cover
    SystemExit(pytest.main([__file__, "-q"]))
