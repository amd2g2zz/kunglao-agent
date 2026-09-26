# -*- coding: utf-8 -*-
"""Issue #342 — VERIFY_STALE: verification-slot forcing (anti-starvation).

Failure class (V1): the SCHEDULE probe list evaluates WORK_AND_FREE_SLOT
FIRST, so with a healthy claim frontier PARTIAL facts accumulate unverified
for the whole mission — the verifier is scheduled but never chosen. Back-end
enforcement (blind_gate) works; the defect is TIMELINESS.

Contract (2026-09-22 owner restraint ruling: verification cadence only):
  - New SCHEDULE event VERIFY_STALE, evaluated FIRST, fires when any PARTIAL
    fact's frontmatter age exceeds N ticks (default 12, ~1h at the 5-min
    cadence) AND a free slot exists. Mirrors the #595 precedent
    (STUCK_WORKERS_PRESENT inserted before the saturation tail so a stuck
    worker can never be masked) — here a stale partial can never be masked
    by dispatchable open claims.
  - Transition -> DISPATCH_VERIFIER (exit 2); the action NAMES the stalest
    partial so the orchestrator knows what to verify.
  - Fresh partials (age <= N) keep current priority: DISPATCH (exit 1)
    still wins. No premature verification, no extra tick passes.
  - Age field choice (documented per the issue's "pick the field that
    exists"): frontmatter `created` (one of the 12 MANDATORY schema fields —
    guaranteed present) as the base, with the kunglao extension `verified`
    ("date of last L1 pass", `pending` when none) overriding when it parses
    as a date, so a recently L1-verified partial is not re-forced.
    max(created, verified) is the staleness anchor.
  - Fail-open: an unparseable/missing date yields age None -> never stale
    (a fact whose age cannot be read does not force verification); a
    future-dated frontmatter clamps to age 0 (clock-skew tolerant).
  - Threshold source: liveness_policy.VERIFY_STALE_TICKS (the #597 single
    source), runtime override via KUNGLAO_VERIFY_STALE_TICKS (the
    KUNGLAO_NOOP_BREAKER_N env pattern).

Fast tier: in-process main()/partial_fact_ages calls against tmp_path
workspaces (the #306 test convention).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402
from _factories import write_claims_register, write_worker_status  # noqa: E402
from liveness_policy import TICK_INTERVAL_DEFAULT_MIN  # noqa: E402

ENV_N = "KUNGLAO_VERIFY_STALE_TICKS"

# Two days ago: with the default N=12 ticks (12 x 5 min = 1h), a fact
# created two days ago is stale at ANY wall-clock test time — the stale
# fixtures never depend on when the suite runs.
STALE_DAY = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
# Today's date is NOT deterministically fresh at date granularity (after
# 01:00 local it exceeds the default 1h window), so the fresh-path CLI test
# pins the threshold high via the env knob the issue requires — which also
# exercises the configurability contract.
FRESH_DAY = datetime.now(timezone.utc).date().isoformat()


def _write_fact_file(root: Path, fact_id: str, created: str,
                     verified: str | None = None) -> Path:
    """A partial fact file with the frontmatter date fields under test.

    Same 12-mandatory-field shape lint_facts enforces (only the date fields
    matter here; the reader is regex-based like the verify_status reader).
    Lands in the standard `ws/` workspace of the root, matching _make_ws."""
    ws = root / "ws"
    fm = [
        "---",
        f"id: {fact_id}",
        "type: fact",
        "title: partial fact under test",
        "status: INFERRED",
        f"created: {created}",
    ]
    if verified is not None:
        fm.append(f"verified: {verified}")
    fm += ["claim_id: C-001", "confidence: medium", "---", "", "body."]
    path = ws / "facts" / f"{fact_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(fm) + "\n", encoding="utf-8")
    return path


def _make_ws(tmp_path: Path, *, index_rows: list[str],
             facts: list[Path] | None = None) -> Path:
    """Synthetic workspace: one OPEN claim + the given _INDEX rows."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "runs").mkdir()
    write_claims_register(ws, [{"id": "C-001", "status": "OPEN"}])
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: sample family\n", encoding="utf-8")
    fdir = ws / "facts"
    fdir.mkdir(exist_ok=True)
    (fdir / "_INDEX.md").write_text(
        "# _INDEX\n" + "\n".join(index_rows) + "\n", encoding="utf-8")
    for p in facts or []:
        p.parent.mkdir(parents=True, exist_ok=True)
    return ws


def _run_cc(ws: Path) -> int:
    """In-process CLI run; returns the decided exit code (main() RETURNS
    the verdict byte — SystemExit is only the hard-error path)."""
    return int(cc.main([str(ws)]))


# ------------------------------------------------------------------
# acceptance (a): stale partial forces exit 2, not 1
# ------------------------------------------------------------------

def test_stale_partial_forces_dispatch_verifier_exit_2(tmp_path):
    """THE issue repro: open claim + free slot + PARTIAL older than N.
    Pre-#342 this was DISPATCH (exit 1) — the verifier starved; after,
    VERIFY_STALE evaluated FIRST yields DISPATCH_VERIFIER (exit 2)."""
    fact = _write_fact_file(tmp_path, "F001-config-xor", STALE_DAY)
    ws = _make_ws(
        tmp_path,
        index_rows=["F001-config-xor | PARTIAL | C-001 | xor key is 0x4d"],
        facts=[fact])
    code = _run_cc(ws)
    assert code == cc.EXIT_VERIFY, f"expected exit 2, got {code}"


def test_verify_stale_action_names_the_stalest_partial(tmp_path, capsys):
    """The action output must name the stalest partial so the orchestrator
    knows what to verify (issue scope A, action contract)."""
    f1 = _write_fact_file(tmp_path, "F001-old", STALE_DAY)
    f2 = _write_fact_file(tmp_path, "F002-staler",
                          (datetime.now(timezone.utc)
                           - timedelta(days=5)).date().isoformat())
    ws = _make_ws(
        tmp_path,
        index_rows=["F001-old | PARTIAL | C-001 | a",
                    "F002-staler | PARTIAL | C-001 | b"],
        facts=[f1, f2])
    cc.main([str(ws)])
    out = capsys.readouterr().out
    assert "F002-staler" in out, "action must name the STALEST partial"
    assert "DISPATCH_VERIFIER" in out


def test_verify_stale_preempts_dispatchable_open_claims(tmp_path):
    """Evaluated FIRST: even with a dispatchable open claim in front, the
    stale partial wins the slot (the anti-starvation point)."""
    fact = _write_fact_file(tmp_path, "F001-config-xor", STALE_DAY)
    ws = _make_ws(
        tmp_path,
        index_rows=["F001-config-xor | PARTIAL | C-001 | x"],
        facts=[fact])
    snap = cc._decide_inputs(ws)
    assert snap.unblocked_open, "fixture needs a dispatchable open claim"
    assert snap.free_slots > 0
    assert cc._verify_stale(snap), "VERIFY_STALE must fire before DISPATCH"


# ------------------------------------------------------------------
# acceptance (b): fresh partial keeps exit 1 (DISPATCH priority preserved)
# ------------------------------------------------------------------

def test_fresh_partial_keeps_dispatch_priority_exit_1(tmp_path, monkeypatch):
    """age < N + open claims + free slot -> exit 1. The env knob (issue:
    configurable) pins freshness deterministically at date granularity."""
    monkeypatch.setenv(ENV_N, "999999")
    fact = _write_fact_file(tmp_path, "F001-config-xor", FRESH_DAY)
    ws = _make_ws(
        tmp_path,
        index_rows=["F001-config-xor | PARTIAL | C-001 | x"],
        facts=[fact])
    assert _run_cc(ws) == cc.EXIT_DISPATCH == 1


def test_default_threshold_keeps_recent_verify_attempt_fresh(tmp_path):
    """The `verified` extension field resets the staleness clock: a fact
    created long ago but L1-verified 30 min ago (6 ticks) is NOT stale at
    the default N=12 (no premature re-verification). Full ISO datetime on
    `verified` keeps the boundary off the wall clock."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    fact = _write_fact_file(tmp_path, "F001-config-xor", STALE_DAY,
                            verified=recent)
    ws = _make_ws(
        tmp_path,
        index_rows=["F001-config-xor | PARTIAL | C-001 | x"],
        facts=[fact])
    snap = cc._decide_inputs(ws)
    assert not cc._verify_stale(snap)


# ------------------------------------------------------------------
# threshold boundary + fail-open (unit level, injected clock)
# ------------------------------------------------------------------

def test_boundary_exactly_n_ticks_is_not_stale(tmp_path):
    """Exceeds N is strict: age == N does not fire. (Full ISO datetime in
    `created` — the reader accepts date-only and datetime forms; the
    datetime form makes the boundary exact.)"""
    now = datetime(2026, 9, 22, 12, 0, 0)
    created = (now - timedelta(seconds=12 * TICK_INTERVAL_DEFAULT_MIN * 60)
               ).isoformat()
    fact = _write_fact_file(tmp_path, "F001", created)
    ws = _make_ws(tmp_path, index_rows=["F001 | PARTIAL | C-001 | x"],
                  facts=[fact])
    rows = cc.partial_fact_ages(ws, now=now.replace(tzinfo=timezone.utc))
    assert rows and rows[0]["stale"] is False
    assert rows[0]["age_ticks"] == pytest.approx(12.0)


def test_just_past_n_ticks_is_stale(tmp_path):
    now = datetime(2026, 9, 22, 12, 0, 0)
    anchor = (now - timedelta(seconds=13 * TICK_INTERVAL_DEFAULT_MIN * 60)
              ).isoformat()
    fact = _write_fact_file(tmp_path, "F001", anchor)
    ws = _make_ws(tmp_path, index_rows=["F001 | PARTIAL | C-001 | x"],
                  facts=[fact])
    rows = cc.partial_fact_ages(ws, now=now.replace(tzinfo=timezone.utc))
    assert rows[0]["stale"] is True


def test_unparseable_created_fails_open_never_stale(tmp_path):
    """A fact whose age cannot be read never forces verification
    (fail-open: the machine degrades to the pre-#342 event order)."""
    ws = _make_ws(tmp_path,
                  index_rows=["F001-nofm | PARTIAL | C-001 | x"])
    (ws / "facts" / "F001-nofm.md").write_text(
        "# no frontmatter at all\n", encoding="utf-8")
    snap = cc._decide_inputs(ws)
    assert not cc._verify_stale(snap)
    assert _run_cc(ws) == cc.EXIT_DISPATCH


def test_future_created_clamps_to_fresh(tmp_path):
    """A frontmatter date in the future (clock skew) is age 0, not
    negative — never stale, never a crash."""
    future = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    fact = _write_fact_file(tmp_path, "F001", future)
    ws = _make_ws(tmp_path, index_rows=["F001 | PARTIAL | C-001 | x"],
                  facts=[fact])
    rows = cc.partial_fact_ages(ws)
    assert rows[0]["age_ticks"] == 0.0
    assert rows[0]["stale"] is False


def test_env_threshold_override_changes_the_verdict(tmp_path, monkeypatch):
    """KUNGLAO_VERIFY_STALE_TICKS (the noop-breaker env pattern): N=1 makes
    a ~2h-old fact stale even though the default N=12 would not... at date
    granularity 2 days is stale at any N <= ~500 — here we pin the OTHER
    direction: a huge N keeps the same fact fresh."""
    monkeypatch.setenv(ENV_N, "999999")
    fact = _write_fact_file(tmp_path, "F001", STALE_DAY)
    ws = _make_ws(tmp_path, index_rows=["F001 | PARTIAL | C-001 | x"],
                  facts=[fact])
    snap = cc._decide_inputs(ws)
    assert not cc._verify_stale(snap), "huge N must keep the stale fixture fresh"


# ------------------------------------------------------------------
# slot semantics: no free slot -> no forced verification
# ------------------------------------------------------------------

def test_stale_partial_without_free_slot_does_not_force_verify(tmp_path):
    """VERIFY_STALE requires a free slot (sibling semantics of
    _work_and_free_slot/_partials_and_free_slot): with all 3 slots busy the
    machine reads SATURATED (poll) — never DISPATCH_VERIFIER without a slot."""
    fact = _write_fact_file(tmp_path, "F001", STALE_DAY)
    ws = _make_ws(tmp_path,
                  index_rows=["F001 | PARTIAL | C-001 | x"], facts=[fact])
    for i in range(cc.WORKER_CAP):
        write_worker_status(ws, f"w{i}", "in-progress", age_min=1)
    assert _run_cc(ws) == cc.EXIT_SATURATED


# ------------------------------------------------------------------
# restraint: the event list order keeps every existing transition
# ------------------------------------------------------------------

def test_schedule_probe_order_puts_verify_stale_first(tmp_path):
    """#342 mirrors #595: the inserted event sits at the FRONT of the
    SCHEDULE probes (before WORK_AND_FREE_SLOT), and the rest of the order
    is unchanged — a fresh partial still reaches DISPATCH exactly as
    before, and STUCK still precedes the saturation tail."""
    order = cc.STAGE_PROBES[cc.State.SCHEDULE]
    assert order[0] == cc.Event.VERIFY_STALE
    assert order.index(cc.Event.STUCK_WORKERS_PRESENT) \
        < order.index(cc.Event.WORK_NO_FREE_SLOT)
    for ev in (cc.Event.WORK_AND_FREE_SLOT, cc.Event.PARTIALS_AND_FREE_SLOT,
               cc.Event.STUCK_WORKERS_PRESENT, cc.Event.WORK_NO_FREE_SLOT,
               cc.Event.FAILURE_ARTIFACTS_DUE, cc.Event.UNEXPECTED_STATE):
        assert ev in order, f"existing event {ev} must stay in the table"
    assert (cc.State.SCHEDULE, cc.Event.VERIFY_STALE) in cc.TRANSITIONS
    assert cc.TRANSITIONS[(cc.State.SCHEDULE, cc.Event.VERIFY_STALE)][0] \
        == cc.State.DISPATCH_VERIFIER


def test_verify_backlog_face_shares_the_age_reader(tmp_path):
    """The #342 telemetry face (part C) and the event (part A) read ONE
    age implementation — same source, no drift."""
    fact = _write_fact_file(tmp_path, "F001", STALE_DAY)
    ws = _make_ws(tmp_path, index_rows=["F001 | PARTIAL | C-001 | x"],
                  facts=[fact])
    rows = cc.partial_fact_ages(ws)
    assert len(rows) == 1
    assert rows[0]["fact"] == "F001"
    assert rows[0]["age_ticks"] > 12
    assert rows[0]["stale"] is True
