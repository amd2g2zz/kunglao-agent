# -*- coding: utf-8 -*-
"""tests/test_round_credit_cited_cap_438.py — per-dispatch cited cap
(issue 438: the ACTIVE farming vector).

The #433 inversion killed the PASSIVE gradient (N uncited verified facts
settle ONE trace total per row), but the ACTIVE vector survived:
``claim_id`` in fact frontmatter is worker-written and lint checks
register EXISTENCE only, so a worker stamps ONE question-bearing
claim_id on N verified facts and every one resolves the citation
relation — N x 1.0 full credit — without advancing anything.

The fix (minimum viable option 2): a PER-DISPATCH-ROW cited cap — at
most ``CITED_CAP_DEFAULT`` cited artifacts per dispatch row earn FULL
credit; the excess settle at the TRACE CLASS level (one trace total for
the capped class, mirroring the uncited demotion's class semantics) with
the named reason ``cited_over_cap`` — auditable, the worker sees WHY.

Selection rule (which K earn full): DETERMINISTIC, no preference
channel — the row's cited artifacts sort by artifact id, the first K
stay full. Genuine deep citations still reward: a capped artifact that
lands within a LATER settlement's cap amends UP through the existing
late-cite amendment path (no new code — pinned below).

DECLARED PIN RE-MINT AUDIT (issue 438, the declared-section precedent):
the cap changes expectations ONLY where a dispatch row carries more than
``CITED_CAP_DEFAULT`` cited artifacts. The #433 suite
(test_round_credit_alignment_433) and the re-minted #379 round-credit
section (test_scalar_settlement_379.TestRoundCredit) each keep at most
2 cited artifacts per row — the cap is not binding on any existing pin,
so NO pins are re-minted and none are silently weakened.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import scalar_settlement as ss  # noqa: E402

DISPATCHES = [{"dispatch_id": "tr-m1-d1", "round": 1},
              {"dispatch_id": "tr-m1-d2", "round": 2}]


def _artifact(aid, creator, status="PROVEN", verify="passes",
              cited=False, answers=False):
    return {"id": aid, "creator": creator, "status": status,
            "verify_status": verify, "cited_by_deliverable": cited,
            "answers_question": answers,
            "oracle_backed_refutation": False}


def _row(out, dispatch_id):
    return next(r for r in out["rows"]
                if r["dispatch_id"] == dispatch_id)


def _cited(aids, creator="tr-m1-d1"):
    return [_artifact(a, creator, cited=True) for a in aids]


def _over_cap(row):
    return sorted(e["id"] for e in row["demoted"]
                  if e["reason"] == ss.DEMOTION_CITED_OVER_CAP)


# ---------- the cap (pure core) ---------------------------------------------

class TestPerDispatchCitedCap:
    def test_cap_constant_is_two_and_reason_is_named(self):
        """The cap is a named module constant (minimum-diff: no yaml
        version — yaml promotion is a follow-up) and the demotion reason
        is a named constant like its uncited/refuted siblings."""
        assert ss.CITED_CAP_DEFAULT == 2
        assert ss.DEMOTION_CITED_OVER_CAP == "cited_over_cap"

    def test_five_cited_settle_two_full_plus_one_capped_class_trace(self):
        """THE issue pin: one worker-stamped claim surface on N=5 verified
        facts earns at most the cap in FULL — 2 x 1.0 + ONE trace total
        for the capped class (0.01) = 2.01. Never 5 x full; and the
        excess is a CLASS demotion (one total), never 3 x trace."""
        aids = [f"F51{i}-c" for i in range(5)]
        row = _row(ss.round_credit(DISPATCHES, _cited(aids), waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == ["F510-c", "F511-c"]
        assert _over_cap(row) == ["F512-c", "F513-c", "F514-c"]
        assert row["r"] == 2.01

    def test_two_cited_cap_not_binding(self):
        """At exactly the cap nothing demotes — the ladder below the cap
        is byte-identical to the issue-433 ladder."""
        aids = ["F520-a", "F521-b"]
        row = _row(ss.round_credit(DISPATCHES, _cited(aids), waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == ["F520-a", "F521-b"]
        assert row["demoted"] == []
        assert row["r"] == 2.0

    def test_mixed_five_cited_three_uncited_two_distinct_trace_classes(self):
        """5 cited + 3 uncited: 2 full + capped-class trace + uncited-
        class trace = 2.02 — TWO class totals, two distinct reasons, each
        settling once regardless of its count."""
        aids = [f"F53{i}-c" for i in range(5)]
        artifacts = _cited(aids) + [_artifact(f"F53{i}-u", "tr-m1-d1")
                                    for i in range(3)]
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == ["F530-c", "F531-c"]
        assert {e["reason"] for e in row["demoted"]} == \
            {ss.DEMOTION_CITED_OVER_CAP, ss.DEMOTION_UNCITED_VERIFIED}
        assert row["r"] == 2.02

    def test_selection_is_deterministic_id_sort_not_input_order(self):
        """Same ledger -> same rows: the survivors are the id-sorted
        FIRST K even when artifact input order is reversed — no
        preference channel, no positional weight."""
        aids = [f"F54{i}-c" for i in range(5)]
        fwd = ss.round_credit(DISPATCHES, _cited(aids), waste=[])
        rev = ss.round_credit(DISPATCHES, _cited(list(reversed(aids))),
                              waste=[])
        assert fwd == rev
        assert _row(fwd, "tr-m1-d1")["credited"] == ["F540-c", "F541-c"]

    def test_cap_is_per_row_not_per_dispatch_set(self):
        """The cap is PER DISPATCH ROW: two rows each carrying 3 cited
        keep 2 full each — a worker cannot launder the cap by splitting
        one claim stamp across rows, and honest rows do not pay for each
        other."""
        aids_d1 = [f"F55{i}-a" for i in range(3)]
        aids_d2 = [f"F55{i}-b" for i in range(3)]
        artifacts = _cited(aids_d1, "tr-m1-d1") + \
            _cited(aids_d2, "tr-m1-d2")
        out = ss.round_credit(DISPATCHES, artifacts, waste=[])
        assert _row(out, "tr-m1-d1")["r"] == 2.01
        assert _row(out, "tr-m1-d2")["r"] == 2.01

    def test_capped_excess_lose_full_not_everything(self):
        """The cap demotes from FULL to the TRACE CLASS level — the
        excess keeps its admission (verified) and its audit entry, so a
        later genuine citation can amend it up (rescue path below)."""
        aids = [f"F56{i}-c" for i in range(5)]
        row = _row(ss.round_credit(DISPATCHES, _cited(aids), waste=[]),
                   "tr-m1-d1")
        over = [e for e in row["demoted"]
                if e["reason"] == ss.DEMOTION_CITED_OVER_CAP]
        assert len(over) == 3
        assert all(e["id"] in aids for e in over)


# ---------- settlement rows + the late-rescue amendment path ----------------

class TestCapSettlementAndLateRescue:
    def test_settlement_row_names_cited_over_cap_like_uncited(self, tmp_path):
        """Same audit shape as the uncited demotion: the settlement
        ``demoted`` list carries {id, reason: cited_over_cap} entries and
        the evidence refs name each capped id with its reason — the
        worker sees WHY."""
        ws = tmp_path / "ws"
        ws.mkdir()
        aids = [f"F57{i}-c" for i in range(5)]
        res = ss.settle_round_credit(ws, DISPATCHES, _cited(aids), [],
                                     now="2026-09-29T00:00:00Z")
        assert res["settled"] == 2
        st = rl.fold(ws, "round_credit/tr-m1-d1")["settlement"]
        assert st["reward"] == 2.01
        assert st["credited"] == ["F570-c", "F571-c"]
        assert _over_cap(st) == ["F572-c", "F573-c", "F574-c"]
        assert any(
            r.startswith("demoted:F572-c:cited_over_cap")
            for r in st["evidence_refs"])

    def test_late_rescue_capped_artifact_within_a_later_cap_amends_up(
            self, tmp_path):
        """Genuine deep citations still reward: the first settlement caps
        F573 (5 cited, cap 2); a later settlement narrows the citation
        surface so F573 sits within the cap — the EXISTING amendment path
        raises it up and names it late_cited (append-only, no new code —
        verified flowing, pinned here)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        aids = [f"F58{i}-c" for i in range(5)]
        ss.settle_round_credit(ws, DISPATCHES, _cited(aids), [],
                               now="2026-09-29T00:00:00Z")
        st1 = rl.fold(ws, "round_credit/tr-m1-d1")["settlement"]
        assert st1["credited"] == ["F580-c", "F581-c"]
        assert "F583-c" in _over_cap(st1)
        rows_before = [r for r in rl.read(ws)
                       if r["rollout_id"] == "round_credit/tr-m1-d1"]
        assert len(rows_before) == 2

        # citation surface narrows: only F580/F583 stay cited, the rest
        # revert to plain verified-uncited
        narrowed = _cited(["F580-c", "F583-c"]) + [
            _artifact("F581-c", "tr-m1-d1"),
            _artifact("F582-c", "tr-m1-d1"),
            _artifact("F584-c", "tr-m1-d1")]
        ss.settle_round_credit(ws, DISPATCHES, narrowed, [],
                               now="2026-09-29T06:00:00Z")
        rows_after = [r for r in rl.read(ws)
                      if r["rollout_id"] == "round_credit/tr-m1-d1"]
        # append-only; the rescue is COUNT-STABLE (credited 2 -> 2,
        # demoted 3 -> 3), so the record signal dedupes and only the
        # SETTLEMENT amendment appends (2 + 1) — identities live in the
        # settlement row, which is the audit carrier here
        assert len(rows_after) == 3
        assert [json.dumps(r, sort_keys=True) for r in rows_before] == \
            [json.dumps(r, sort_keys=True) for r in rows_after[:2]]
        st2 = rl.fold(ws, "round_credit/tr-m1-d1")["settlement"]
        assert st2["credited"] == ["F580-c", "F583-c"]
        assert st2["late_cited"] == ["F583-c"]
        assert st2["reward"] == 2.01  # 2 full + the uncited class total
        assert {e["reason"] for e in st2["demoted"]} == \
            {ss.DEMOTION_UNCITED_VERIFIED}

    def test_capped_settlement_is_idempotent(self, tmp_path):
        """Re-running the same capped ledger settles nothing new — the
        signal set (credited count + demoted count) is stable under the
        cap, so record/settle dedupe holds (no ledger churn)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        aids = [f"F59{i}-c" for i in range(5)]
        ss.settle_round_credit(ws, DISPATCHES, _cited(aids), [],
                               now="2026-09-29T00:00:00Z")
        again = ss.settle_round_credit(ws, DISPATCHES, _cited(aids), [],
                                       now="2026-09-29T09:00:00Z")
        assert again["settled"] == 0
        assert len([r for r in rl.read(ws)
                    if r["rollout_id"] == "round_credit/tr-m1-d1"]) == 2


# ---------- the issue's exact attack, end to end ----------------------------

class TestClaimStampAttackEndToEnd:
    def test_one_claim_stamp_on_five_facts_closes_at_the_cap(self, tmp_path):
        """The issue's ACTIVE vector replayed against the read face: one
        question-bearing claim_id stamped on 5 verified facts — all 5
        resolve the citation relation, the cap keeps exactly 2 full, and
        the other 3 settle the single capped-class trace total (2.01,
        never 5 x full)."""
        ws = tmp_path / "ws"
        (ws / "facts").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "claims:\n"
            "  - id: C-001\n"
            "    answers_question: pq-main\n"
            "    statement: demo\n", encoding="utf-8")
        aids = [f"F70{i}-s" for i in range(5)]
        for fid in aids:
            (ws / "facts" / f"{fid}.md").write_text(
                "---\n"
                f"id: {fid}\n"
                "type: fact\n"
                "status: PROVEN\n"
                "verify_status: passes\n"
                "creator: tr-m1-d1\n"
                "claim_id: C-001\n"
                "---\n\ndemo\n", encoding="utf-8")
        row = _row(ss.round_credit(DISPATCHES, ss.fact_artifacts(ws),
                                   waste=[]), "tr-m1-d1")
        assert row["credited"] == ["F700-s", "F701-s"]
        assert _over_cap(row) == ["F702-s", "F703-s", "F704-s"]
        assert row["r"] == 2.01
