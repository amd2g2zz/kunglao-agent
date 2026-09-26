# -*- coding: utf-8 -*-
"""tests/test_gap_note_injection_391.py — gap-note read face via recall_inject.

Issue 391 acceptance (read face):
  - a same-unit retry dispatch injects prior gap-notes through the existing
    recall_inject dispatch-scoped channel;
  - different units are unaffected (claim-keyed, no cross-claim bleed);
  - per-worker content dedup applies: an unchanged (recall + notes) set for
    the same worker is silent; a NEW gap-note for the same claim re-injects;
  - the injected block carries the advisory marker (context supply, never a
    reward signal) and never changes rc (recall never blocks dispatch).
The recall engine is injected (recall_runner) so these tests exercise only
the gap-note channel, not reference ranking.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import reward_settlement as rs  # noqa: E402

import gap_notes as gn  # noqa: E402
from recall_inject import evaluate  # noqa: E402  (pytest.ini pythonpath)

RULES_PATH = ROOT / "references" / "contracts" / "reward-rules.yaml"

CLAIM = "[T2 tools=ghidra] claim C-391 retry: recover the config builder " \
        "from the packed sample"
OTHER_CLAIM = "[T2 tools=ghidra] claim C-777 disassemble the unpacked " \
              "sample and decode the import table"


def _sig(type_: str, source: str, value, ts="2026-09-26T00:00:00Z"):
    return {"type": type_, "source": source, "value": value, "ts": ts}


def _kunglao_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-391\n  status: OPEN\n"
        "- id: C-777\n  status: OPEN\n", encoding="utf-8")
    return ws


def _payload(ws: Path, prompt: str) -> dict:
    return {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": prompt},
    }


def _recall_runner(files: tuple[str, ...] = ()):
    def run(query: str):
        if not files:
            return 1, ""  # recall matched nothing
        return 0, "".join(f"{f} | category | scene\n" for f in files)
    return run


def _seed_fail_note(ws: Path, claim: str = "C-391") -> None:
    """The full machine path: FAIL signals -> settled ledger row -> one
    gap-note on disk (no fixtures hand-written — the write face writes)."""
    rl.record(ws, kind="task", anchor=claim, signals=[
        _sig("claim_terminal", "convergence_check", "NEGATIVE"),
        _sig("oracle_verdict", "oracle_runner", "fail"),
        _sig("static_probes", "eval_checker", {"passed": 1, "total": 3}),
        _sig("evidence_class", "rerun_discipline", "asserted"),
    ])
    rs.settle_workspace(ws, rules_path=RULES_PATH)
    assert gn.emit_gap_notes(ws)["emitted"] == 1


# ---- same-unit retry injection ----

def test_retry_dispatch_injects_prior_gap_notes(tmp_path):
    ws = _kunglao_ws(tmp_path)
    _seed_fail_note(ws)
    rc, stderr, ctx = evaluate(_payload(ws, CLAIM),
                               recall_runner=_recall_runner())
    assert rc == 0, "recall never rejects"
    assert stderr == ""
    assert ctx, "a retry dispatch must see what prior attempts hit"
    assert '<kunglao-facts advisory="true">' in ctx
    assert "never a reward signal" in ctx
    assert "<gap-note" in ctx
    assert 'static="1/3"' in ctx, "checker sub-scores cited, not summaries"
    assert "runs/gap-notes/C-391/" in ctx, "concrete file label present"


def test_recall_and_gap_notes_share_one_channel(tmp_path):
    """When recall matches too, both blocks arrive in one additionalContext
    (recall guidance unchanged, gap-note block appended)."""
    ws = _kunglao_ws(tmp_path)
    _seed_fail_note(ws)
    runner = _recall_runner(("re-library/mock/reference.md",))
    rc, stderr, ctx = evaluate(_payload(ws, CLAIM), recall_runner=runner)
    assert rc == 0 and ctx
    assert "Before dispatching, read:" in ctx
    assert "prior-attempt-note" in ctx


def test_dispatch_without_notes_is_unchanged(tmp_path):
    """No gap-notes for the unit -> no gap-note block (recall-only or
    silent exactly as before issue 391)."""
    ws = _kunglao_ws(tmp_path)
    runner = _recall_runner(("re-library/mock/reference.md",))
    rc, stderr, ctx = evaluate(_payload(ws, CLAIM), recall_runner=runner)
    assert rc == 0 and ctx
    assert "prior-attempt-note" not in ctx
    assert "gap-notes/" not in ctx


# ---- isolation + dedup ----

def test_different_unit_is_unaffected(tmp_path):
    """Claim C-777's dispatch never sees C-391's gap-notes."""
    ws = _kunglao_ws(tmp_path)
    _seed_fail_note(ws, "C-391")
    rc, stderr, ctx = evaluate(_payload(ws, OTHER_CLAIM),
                               recall_runner=_recall_runner())
    assert rc == 0
    assert ctx is None or "gap-notes/C-391" not in ctx


def test_per_worker_dedup_silents_repeat_and_new_note_reinjects(tmp_path):
    """The per-worker content-hash dedup applies: same recall + same notes
    -> silent; a NEW gap-note for the same claim -> re-injects (attempt 3
    sees attempts 1..2)."""
    ws = _kunglao_ws(tmp_path)
    _seed_fail_note(ws)
    first_rc, _, first_ctx = evaluate(_payload(ws, CLAIM),
                                      recall_runner=_recall_runner())
    assert first_rc == 0 and first_ctx
    # identical re-dispatch: unchanged (recall + notes) set -> silent
    _, _, repeat_ctx = evaluate(_payload(ws, CLAIM),
                                recall_runner=_recall_runner())
    assert repeat_ctx is None
    # attempt 2 fails too: grown signals re-settle -> a second gap-note
    rl.record(ws, kind="task", anchor="C-391", signals=[
        _sig("claim_terminal", "convergence_check", "NEGATIVE",
             ts="2026-09-26T06:00:00Z"),
        _sig("oracle_verdict", "oracle_runner", "fail",
             ts="2026-09-26T06:00:00Z"),
        _sig("static_probes", "eval_checker", {"passed": 2, "total": 3},
             ts="2026-09-26T06:00:00Z"),
        _sig("replay_probes", "eval_checker", {"passed": 0, "total": 2},
             ts="2026-09-26T06:00:00Z"),
        _sig("evidence_class", "rerun_discipline", "asserted",
             ts="2026-09-26T06:00:00Z"),
    ])
    rs.settle_workspace(ws, rules_path=RULES_PATH)
    assert gn.emit_gap_notes(ws)["emitted"] == 1
    rc, _, ctx = evaluate(_payload(ws, CLAIM),
                          recall_runner=_recall_runner())
    assert rc == 0 and ctx
    assert ctx.count("<prior-attempt-note") == 2, \
        "attempt 3 sees the two prior attempts"


def test_non_claim_dispatch_gets_no_gap_notes(tmp_path):
    """Red-team / non-claim dispatches are outside the gap-note channel."""
    ws = _kunglao_ws(tmp_path)
    _seed_fail_note(ws)
    rc, stderr, ctx = evaluate(
        _payload(ws, "verify-redteam plan attacks for the packed sample"),
        recall_runner=_recall_runner())
    assert rc == 0
    assert ctx is None or "prior-attempt-note" not in ctx
