# -*- coding: utf-8 -*-
"""Event schema mandatory-fields contract: mechanical population + tick axis.

The five schema fields that spent their whole life null (duration_ms, arm,
epoch, hypothesis_ref, matched_rule) are populated from execution structure
at the sites that structurally know them, and the epoch axis IS the tick
(the convergence ledger's raw snapshot-row count — the single time axis).
A field that is populated-by-construction leaves the auto-documented null
set; sites that genuinely cannot know a field keep the honest documented
null — the rot must never return as fabricated values.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import kunglao_log  # noqa: E402
from kunglao_log import AUTO_NULL_FIELDS, current_tick, emit, log_path, timed  # noqa: E402


def _rows(ws: Path) -> list[dict]:
    p = log_path(ws)
    if not p.exists():
        return []
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").strip().splitlines() if line.strip()]


def _append_ledger(ws: Path, snapshots: int, events: int = 0) -> None:
    """Raw convergence-ledger writer: snapshot rows carry open_count and no
    type key; event rows carry a type key (they are not snapshots)."""
    p = ws / ".convergence_ledger.jsonl"
    lines = [json.dumps({"open_count": 3, "total": 5}) for _ in range(snapshots)]
    lines += [json.dumps({"type": "operator_action", "ts": "t"}) for _ in range(events)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------- tick axis (epoch)

def test_current_tick_counts_raw_snapshot_rows(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _append_ledger(ws, snapshots=2, events=1)
    assert current_tick(ws) == 2


def test_current_tick_absent_ledger_is_cold_start_zero(tmp_path):
    assert current_tick(tmp_path) == 0


def test_current_tick_unreadable_ledger_is_none_not_fake_zero(tmp_path):
    ledger = tmp_path / ".convergence_ledger.jsonl"
    ledger.mkdir()  # a directory: stat succeeds, read fails
    assert current_tick(tmp_path) is None


def test_tick_accessor_ledger_name_matches_the_writer():
    """The tick axis reads the convergence ledger by the writer's own name."""
    import convergence_check
    assert kunglao_log.CONV_LEDGER_NAME == convergence_check.LEDGER_NAME


def test_epoch_stamps_tick_by_construction(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _append_ledger(ws, snapshots=2)
    emit(ws, actor="orchestrator", action="dispatch")
    row = _rows(ws)[0]
    assert row["epoch"] == 2
    assert "epoch" not in row["null_reasons"]


def test_epoch_explicit_value_wins_over_tick(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _append_ledger(ws, snapshots=2)
    emit(ws, actor="orchestrator", action="dispatch", epoch=7)
    assert _rows(ws)[0]["epoch"] == 7


def test_epoch_advances_monotonically_with_the_single_axis(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    emit(ws, actor="orchestrator", action="dispatch")
    _append_ledger(ws, snapshots=1)
    emit(ws, actor="orchestrator", action="dispatch")
    epochs = [r["epoch"] for r in _rows(ws)]
    assert epochs == [0, 1]


def test_epoch_unreadable_ledger_is_honest_documented_null(tmp_path):
    (tmp_path / ".convergence_ledger.jsonl").mkdir()
    emit(tmp_path, actor="orchestrator", action="dispatch")
    row = _rows(tmp_path)[0]
    assert row["epoch"] is None
    assert row["null_reasons"]["epoch"] == "tick_ledger_unreadable"


def test_epoch_leaves_the_auto_null_set():
    """Populated-by-construction fields leave the auto-documented set."""
    assert "epoch" not in AUTO_NULL_FIELDS
    assert AUTO_NULL_FIELDS == ("duration_ms", "arm", "hypothesis_ref",
                                "matched_rule")


# --------------------------------------------------------- timing wrapper

def test_timed_measures_the_wrapped_block(tmp_path):
    with timed() as box:
        time.sleep(0.01)
    assert isinstance(box["duration_ms"], int)
    assert box["duration_ms"] >= 1


def test_timed_records_duration_even_when_the_block_raises(tmp_path):
    box: dict = {}
    try:
        with timed() as caught:
            box = caught
            raise RuntimeError("work failed")
    except RuntimeError:
        pass
    assert box["duration_ms"] is not None


def test_monotonic_ms_is_a_monotone_integer_clock():
    a = kunglao_log.monotonic_ms()
    b = kunglao_log.monotonic_ms()
    assert isinstance(a, int) and isinstance(b, int)
    assert b >= a


# --------------------------------------------- emit-site population: rank

def test_rank_feeds_carries_the_selected_arm(tmp_path):
    import priority_ratio as pr
    ws = tmp_path / "ws"
    ws.mkdir()
    actions = [
        pr.Action(claim_id="C-002", action="dispatch", score=0.9, skill=None,
                  tier=1, attempts=0, cost=0.0),
        pr.Action(claim_id="C-001", action="dispatch", score=0.1, skill=None,
                  tier=1, attempts=0, cost=0.0),
    ]
    evidence = pr.EvidenceView()
    pr._emit_rank_feeds(ws, claims=[], evidence=evidence, rng_base=0,
                        actions=actions)
    row = _rows(ws)[0]
    assert row["action"] == "rank_feeds"
    assert row["arm"] == "C-002"


def test_rank_feeds_without_actions_keeps_arm_honestly_null(tmp_path):
    import priority_ratio as pr
    ws = tmp_path / "ws"
    ws.mkdir()
    pr._emit_rank_feeds(ws, claims=[], evidence=pr.EvidenceView(), rng_base=0,
                        actions=[])
    row = _rows(ws)[0]
    assert row["arm"] is None
    assert row["null_reasons"]["arm"] == "omitted"


# ------------------------------------------ emit-site population: verify

def _mk_verify_ws(tmp_path):
    import hashlib
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    expected = hashlib.sha256(b"hello").hexdigest()
    (ws / "facts" / "F001.md").write_text(
        "---\nid: F001\nclaim_id: C-001\n"
        "reproduce: print('hello')\nexpected: " + expected + "\n"
        "---\n\nbody\n", encoding="utf-8")
    return ws


def test_verify_face_carries_measured_duration_ms(tmp_path):
    import kunglao_verify
    ws = _mk_verify_ws(tmp_path)
    kunglao_verify.verify(ws, "F001")
    row = next(r for r in _rows(ws) if r["action"] == "verify")
    assert isinstance(row["duration_ms"], int)
    assert row["duration_ms"] >= 0


# --------------------------------- emit-site population: settlement face

def _settle_texts():
    old = "claims:\n  - id: C-001\n    status: OPEN\n    statement: s\n"
    new = "claims:\n  - id: C-001\n    status: PROVEN\n    statement: s\n"
    return new, old


def _mk_settle_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / "logs").mkdir()
    (ws / "claims" / "claim-register.yaml").parent.mkdir(parents=True,
                                                         exist_ok=True)
    new, old = _settle_texts()
    (ws / "claims" / "claim-register.yaml").write_text(new, encoding="utf-8")
    return ws


def test_claim_settled_carries_hypothesis_ref_from_settlement_structure(
        tmp_path):
    from hypothesis_store import Hypothesis, HypothesisStore
    from register_proven_gate import emit_settlements
    ws = _mk_settle_ws(tmp_path)
    store = HypothesisStore(ws / "hypotheses")
    store.create(Hypothesis(id="H-001", claim_id="C-001",
                            competitor_group="bet", status="open"))
    emit_settlements(ws, *_settle_texts())
    row = next(r for r in _rows(ws) if r["action"] == "claim_settled")
    assert row["hypothesis_ref"] == "H-001"


def test_claim_settled_without_a_hypothesis_keeps_honest_null(tmp_path):
    from register_proven_gate import emit_settlements
    ws = _mk_settle_ws(tmp_path)
    emit_settlements(ws, *_settle_texts())
    row = next(r for r in _rows(ws) if r["action"] == "claim_settled")
    assert row["hypothesis_ref"] is None
    assert row["null_reasons"]["hypothesis_ref"] == "no_hypothesis"


def test_claim_settled_broken_store_documents_unreadable(tmp_path):
    from register_proven_gate import emit_settlements
    ws = _mk_settle_ws(tmp_path)
    (ws / "hypotheses").write_text("not a directory\n", encoding="utf-8")
    emit_settlements(ws, *_settle_texts())
    row = next(r for r in _rows(ws) if r["action"] == "claim_settled")
    assert row["hypothesis_ref"] is None
    assert (row["null_reasons"]["hypothesis_ref"]
            == "hypothesis_store_unreadable")


def test_latest_hypothesis_is_numeric_across_the_padding_width(tmp_path):
    """A string max returns H-999 over H-1000 — the numeric sequence is the
    latest ordering, so the parse must be numeric."""
    from hypothesis_store import Hypothesis, HypothesisStore
    from register_proven_gate import _claim_hypothesis_ref
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    store = HypothesisStore(ws / "hypotheses")
    for hid in ("H-001", "H-999", "H-1000"):
        store.create(Hypothesis(id=hid, claim_id="C-001",
                                competitor_group="bet", status="open"))
    ref, reason = _claim_hypothesis_ref(ws, "C-001")
    assert reason is None
    assert ref == "H-1000"


# ------------------------------------------------ adversarial honesty faces

def test_plain_emit_never_fabricates_unknown_fields(tmp_path):
    """A site that cannot know arm/duration_ms still emits the honest
    documented null — never a made-up value."""
    emit(tmp_path, actor="hook:dispatch_gate", action="dispatch")
    row = _rows(tmp_path)[0]
    assert row["arm"] is None and row["duration_ms"] is None
    assert row["null_reasons"]["arm"] == "omitted"
    assert row["null_reasons"]["duration_ms"] == "omitted"
    assert row["epoch"] == 0  # cold start is a REAL tick, not a fake value


def test_single_axis_no_second_epoch_counter_in_producers():
    """The tick axis is the ONLY epoch source: audit emit-producing modules
    for a second counter. Only the schema face itself and the ledger
    snapshot passthrough may name the kwarg — and the exemption is pinned
    to the passthrough SHAPE, not to mere absence of callers."""
    allowed = {"kunglao_log.py", "mission_ledger.py"}
    kwarg = re.compile(r"(?<![\w.])epoch\s*=\s*(?!=)")
    violations = {}
    for sub in ("scripts", "hooks"):
        base = REPO_ROOT / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if p.name in allowed:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if kwarg.search(text):
                violations[f"{sub}/{p.name}"] = True
    assert not violations, f"second epoch counter found: {violations}"


def test_epoch_producer_exemption_is_pinned_to_its_shape():
    """The two exemptions must exist and carry exactly their defining
    shape, so the audit cannot rot silently:
    - kunglao_log.py defines the axis (the tick accessor and its ledger
      name) plus the emitting signature;
    - mission_ledger.py forwards epoch as a pure passthrough
      (`epoch=epoch` into emit) — never computing a value of its own."""
    log_src = (REPO_ROOT / "scripts" / "kunglao_log.py").read_text(
        encoding="utf-8")
    assert "def current_tick(" in log_src
    assert 'CONV_LEDGER_NAME = ".convergence_ledger.jsonl"' in log_src
    ml_src = (REPO_ROOT / "scripts" / "mission_ledger.py").read_text(
        encoding="utf-8")
    assert re.search(r"def emit_snapshot\([^)]*epoch", ml_src)
    # every epoch assignment in the module must be the literal passthrough
    # (`epoch=epoch` into emit) — a computed value would be a second counter
    assignments = re.findall(r"epoch\s*=\s*[^,)\n]+", ml_src)
    assert assignments, "passthrough gone — audit exemption is stale"
    assert all(a.split("=", 1)[1].strip() == "epoch" for a in assignments)
