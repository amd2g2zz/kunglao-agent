# -*- coding: utf-8 -*-
"""tests/test_round_credit_alignment_433.py — round-credit value ladder
(issue 433: value alignment, anti fact-farming).

The defect: round credit gave FULL credit to every oracle-verified
artifact — verified-but-never-cited facts included — so a worker could
farm N true-but-inconsequential verified facts (string dumps, constant
tables), each earning full credit without advancing any stage, and the
method-family policy learned fact-farming.

The fix (value ladder, FIRST-MATCH):
  cited-by-deliverable / used-toward-stage verified -> FULL 1.0
  stage-milestone artifact                          -> FULL (plus the
    existing V-jump attribution face — untouched by this change; a
    milestone artifact is by construction used toward its stage)
  refuted-with-replay-evidence                      -> TRACE 0.01
  verified but never cited                          -> TRACE 0.01
    (demotion reason ``uncited_verified`` — the exploration option,
    worthless until cited)
  action success / tool ran                         -> 0

``verified`` demotes from sufficient condition to ADMISSION TICKET;
``cited / used-toward-stage`` is the value condition. The uncited
demotion is a CLASS demotion: N uncited verified facts settle ONE trace
total per dispatch row per demotion class (the TRACE canonical reused
from the validator rails), never N x full and never N x trace — the
farming gradient dies at any N. A late citation back-promotes the fact
to FULL through the amendment path (append-only ledger rows; promoted
ids named in the settlement) — no punishment for foresight, no farming
of uncited facts.

Citation relation (single chokepoint ``_artifact_cited``): named by a
deliverable (``cited_by_deliverable``) OR linked via claim provenance to
a question-bearing claim (fact ``claim_id`` resolving in
claim-register.yaml to a claim with non-null ``answers_question`` — the
same surface the verdict scorer walks pq -> claim -> linked fact).

DECLARED PIN RE-MINT (issue 433 semantic change, the declared-section
precedent): the round-credit expectations in test_scalar_settlement_379
that assumed verified-or-refutation = FULL were re-minted THERE under
their own declared section; this file carries the new-ladder pins. All
fixtures are SYNTHETIC (privacy rule).

Owner ruling 2026-09-28: within-cell homogeneity is a STATE-SIGNATURE
property, not a reward property — NO reward-side normalization (no
z-score, no rescaling); the cell structure already conditions the
comparison. Pinned below as source + declaration.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import reward_settlement as rs  # noqa: E402
import scalar_settlement as ss  # noqa: E402

RULES_PATH = ROOT / "references" / "contracts" / "reward-rules.yaml"


def _artifact(aid, creator, status="PROVEN", verify="passes",
              cited=False, answers=False, refutation=False):
    return {"id": aid, "creator": creator, "status": status,
            "verify_status": verify, "cited_by_deliverable": cited,
            "answers_question": answers,
            "oracle_backed_refutation": refutation}


DISPATCHES = [{"dispatch_id": "tr-m1-d1", "round": 1},
              {"dispatch_id": "tr-m1-d2", "round": 2}]


def _row(out, dispatch_id):
    return next(r for r in out["rows"]
                if r["dispatch_id"] == dispatch_id)


# ---------- the value ladder (pure core) -----------------------------------

class TestValueLadder:
    def test_trace_canonical_is_reused_not_redeclared(self):
        """The demotion value is the validator's TRACE canonical — the
        exact number already declared in the rails, not a new constant."""
        assert ss.TRACE_CANONICAL == 0.01

    def test_farming_gradient_five_uncited_settle_one_trace_total(self):
        """THE issue pin: N uncited verified facts settle a TRACE TOTAL
        (0.01), not N x full — farming inconsequential verified facts
        earns the same single exploration-option value as one."""
        artifacts = [_artifact(f"F{i:03d}-u", "tr-m1-d1") for i in range(5)]
        out = ss.round_credit(DISPATCHES, artifacts, waste=[])
        row = _row(out, "tr-m1-d1")
        assert row["credited"] == []
        assert row["r"] == 0.01
        assert [e["id"] for e in row["demoted"]] == \
            [f"F{i:03d}-u" for i in range(5)]
        assert {e["reason"] for e in row["demoted"]} == \
            {"uncited_verified"}

    def test_cited_toward_deliverable_verified_fact_settles_full(self):
        artifacts = [_artifact("F100-c", "tr-m1-d1", cited=True)]
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == ["F100-c"]
        assert row["r"] == 1.0
        assert row["demoted"] == []

    def test_used_toward_stage_via_claim_provenance_settles_full(self):
        """The used-toward-stage leg: a fact linked to a question-bearing
        claim (answers_question face) is mechanically cited — FULL."""
        artifacts = [_artifact("F101-q", "tr-m1-d1", answers=True)]
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == ["F101-q"]
        assert row["r"] == 1.0

    def test_mixed_three_uncited_two_cited(self):
        """2 x full + ONE uncited trace total: 2.01 — the uncited mass
        does not scale with its count."""
        artifacts = ([_artifact(f"F20{i}-u", "tr-m1-d1") for i in (0, 1, 2)]
                     + [_artifact(f"F21{i}-c", "tr-m1-d1", cited=True)
                        for i in (0, 1)])
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == ["F210-c", "F211-c"]
        assert row["r"] == 2.01
        assert len(row["demoted"]) == 3

    def test_refuted_with_replay_evidence_is_the_trace_information_option(self):
        """Oracle-backed refutation demotes from FULL to TRACE (the
        information option) — reason named in the row."""
        artifacts = [_artifact("F110-n", "tr-m1-d1", status="NEGATIVE",
                               refutation=True)]
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == []
        assert row["r"] == 0.01
        assert row["demoted"] == \
            [{"id": "F110-n", "reason": "refuted_with_replay_evidence"}]

    def test_demotion_totals_are_per_class_not_per_unit(self):
        """Each demotion CLASS settles its trace total once: 5 uncited +
        2 replay refutations -> 0.02 (two classes), while 5 uncited
        alone stay 0.01."""
        artifacts = ([_artifact(f"F{i:03d}-u", "tr-m1-d1") for i in range(5)]
                     + [_artifact("F120-n", "tr-m1-d1", status="NEGATIVE",
                                  refutation=True),
                        _artifact("F121-n", "tr-m1-d1", status="NEGATIVE",
                                  refutation=True)])
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["r"] == 0.02

    def test_action_success_settles_zero(self):
        """Unchanged leg: a tool-ran / OPEN artifact earns nothing and is
        listed neither as credited nor as demoted."""
        artifacts = [_artifact("F130-o", "tr-m1-d1", status="OPEN",
                               verify="pending")]
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == []
        assert row["demoted"] == []
        assert row["r"] == 0.0

    def test_cited_but_unverified_earns_nothing(self):
        """Verified is the ADMISSION TICKET: a deliverable naming an
        unverified fact buys no credit."""
        artifacts = [_artifact("F140-o", "tr-m1-d1", status="OPEN",
                               verify="pending", cited=True)]
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["credited"] == []
        assert row["r"] == 0.0

    def test_stage_milestone_keeps_full_credit(self):
        """Stage-milestone artifacts (layer falls, key recovered) enter
        through the used-toward-stage leg (a milestone IS stage use) and
        keep FULL credit; the V-jump attribution face is a separate
        existing surface this change does not touch."""
        artifacts = [_artifact("F150-m", "tr-m1-d1", answers=True)]
        row = _row(ss.round_credit(DISPATCHES, artifacts, waste=[]),
                   "tr-m1-d1")
        assert row["r"] == 1.0
        assert row["credited"] == ["F150-m"]

    def test_no_positional_discount_order_invariant(self):
        """gamma stays ruled out: round ORDER changes nothing — per-
        dispatch r is a provenance value sum, never position-weighted."""
        artifacts = [_artifact("F160-a", "tr-m1-d1"),
                     _artifact("F161-b", "tr-m1-d2", cited=True)]
        waste = [{"kind": "decoy_follow", "dispatch_id": "tr-m1-d2",
                  "ref": "C-9"}]
        fwd = ss.round_credit(DISPATCHES, artifacts, waste)
        rev = ss.round_credit(list(reversed(DISPATCHES)), artifacts, waste)
        by_dispatch = lambda out: {r["dispatch_id"]: r["r"]
                                   for r in out["rows"]}
        assert by_dispatch(fwd) == by_dispatch(rev) \
            == {"tr-m1-d1": 0.01, "tr-m1-d2": 0.0}


# ---------- the citation chokepoint (claim provenance face) ----------------

class TestCitationChokepoint:
    def _fact(self, ws: Path, fid: str, creator, claim_id=None) -> None:
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "facts").mkdir(exist_ok=True)
        lines = ["---", f"id: {fid}", "type: fact", "status: PROVEN",
                 "verify_status: passes"]
        if creator:
            lines.append(f"creator: {creator}")
        if claim_id:
            lines.append(f"claim_id: {claim_id}")
        lines += ["---", "", "demo"]
        (ws / "facts" / f"{fid}.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    def _register(self, ws: Path, claims: list[dict]) -> None:
        ws.mkdir(parents=True, exist_ok=True)
        body = ["claims:"]
        for c in claims:
            aq = 'answers_question: null' \
                if c["answers_question"] is None \
                else f'answers_question: {c["answers_question"]}'
            body += [f'  - id: {c["id"]}', f'    {aq}',
                     '    statement: demo']
        (ws / "claim-register.yaml").write_text(
            "\n".join(body) + "\n", encoding="utf-8")

    def test_question_claims_reads_the_register(self, tmp_path):
        ws = tmp_path / "ws"
        self._register(ws, [{"id": "C-001", "answers_question": "pq-main"},
                            {"id": "C-002", "answers_question": None}])
        assert ss.question_claims(ws) == {"C-001"}

    def test_fact_on_a_question_bearing_claim_is_used_toward_stage(
            self, tmp_path):
        """fact.claim_id -> claim.answers_question non-null = the fact
        feeds a deliverable-facing question: mechanically cited."""
        ws = tmp_path / "ws"
        self._register(ws, [{"id": "C-001", "answers_question": "pq-main"},
                            {"id": "C-002", "answers_question": None}])
        self._fact(ws, "F200-a", "tr-m1-d1", claim_id="C-001")
        self._fact(ws, "F201-b", "tr-m1-d1", claim_id="C-002")
        rows = {r["id"]: r for r in ss.fact_artifacts(ws)}
        assert rows["F200-a"]["answers_question"] is True
        assert rows["F200-a"]["claim_id"] == "C-001"
        assert rows["F201-b"]["answers_question"] is False

    def test_missing_register_degrades_to_no_claim_citations(self, tmp_path):
        """Tolerant read: no register -> no claim-provenance citations
        (the deliverable face is unaffected)."""
        ws = tmp_path / "ws"
        self._fact(ws, "F202-c", "tr-m1-d1", claim_id="C-001")
        assert ss.question_claims(ws) == set()
        rows = ss.fact_artifacts(ws)
        assert rows[0]["answers_question"] is False

    def test_end_to_end_claim_provenance_settles_full(self, tmp_path):
        """The whole chain: register + fact frontmatter -> fact_artifacts
        -> round_credit settles the question-linked fact FULL and the
        unlinked verified fact at the trace total."""
        ws = tmp_path / "ws"
        self._register(ws, [{"id": "C-001", "answers_question": "pq-main"}])
        self._fact(ws, "F203-q", "tr-m1-d1", claim_id="C-001")
        self._fact(ws, "F204-u", "tr-m1-d1")
        row = _row(ss.round_credit(
            DISPATCHES, ss.fact_artifacts(ws), waste=[]), "tr-m1-d1")
        assert row["credited"] == ["F203-q"]
        assert [e["id"] for e in row["demoted"]] == ["F204-u"]
        assert row["r"] == 1.01


# ---------- settlement rows + the late-cite amendment path -----------------

class TestSettlementAndLateCite:
    def test_settlement_row_names_the_demotion_reason(self, tmp_path):
        """The demotion is visible in the settlement row — the worker
        sees WHY the credit is low (auditable gradient)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        artifacts = [_artifact("F300-u", "tr-m1-d1")]
        res = ss.settle_round_credit(ws, DISPATCHES, artifacts, [],
                                     now="2026-09-28T00:00:00Z")
        assert res["settled"] == 2
        st = rl.fold(ws, "round_credit/tr-m1-d1")["settlement"]
        assert st["band"] == "ROUND_CREDIT"
        assert st["rule_id"] == ss.RULE_ROUND_CREDIT
        assert st["reward"] == 0.01
        assert st["credited"] == []
        assert st["demoted"] == \
            [{"id": "F300-u", "reason": "uncited_verified"}]
        assert any(r.startswith("demoted:F300-u:uncited_verified")
                   for r in st["evidence_refs"])

    def test_late_citation_back_promotes_via_the_amendment_path(
            self, tmp_path):
        """An early fact cited later AMENDS upward: record + settle
        append amendment rows (append-only ledger), the fold raises the
        reward to full, and the settlement names the promoted id with
        provenance. No punishment for foresight."""
        ws = tmp_path / "ws"
        ws.mkdir()
        uncited = [_artifact("F310-f", "tr-m1-d1")]
        ss.settle_round_credit(ws, DISPATCHES, uncited, [],
                               now="2026-09-28T00:00:00Z")
        assert rl.fold(ws, "round_credit/tr-m1-d1")["settlement"][
            "reward"] == 0.01
        rows_before = [r for r in rl.read(ws)
                       if r["rollout_id"] == "round_credit/tr-m1-d1"]
        assert len(rows_before) == 2

        cited = [_artifact("F310-f", "tr-m1-d1", cited=True)]
        res = ss.settle_round_credit(ws, DISPATCHES, cited, [],
                                     now="2026-09-28T06:00:00Z")
        assert res["settled"] == 1
        rows_after = [r for r in rl.read(ws)
                      if r["rollout_id"] == "round_credit/tr-m1-d1"]
        assert len(rows_after) == 4          # append-only: 2 + 2 amendments
        assert [json.dumps(r, sort_keys=True) for r in rows_before] == \
            [json.dumps(r, sort_keys=True) for r in rows_after[:2]]
        st = rl.fold(ws, "round_credit/tr-m1-d1")["settlement"]
        assert st["reward"] == 1.0
        assert st["credited"] == ["F310-f"]
        assert st["demoted"] == []
        assert st["late_cited"] == ["F310-f"]
        assert "credited:F310-f" in st["evidence_refs"]

        # settled state is idempotent from here
        again = ss.settle_round_credit(ws, DISPATCHES, cited, [],
                                       now="2026-09-28T09:00:00Z")
        assert again["settled"] == 0
        assert len([r for r in rl.read(ws)
                    if r["rollout_id"] == "round_credit/tr-m1-d1"]) == 4

    def test_first_settlement_is_not_marked_late_cited(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.settle_round_credit(
            ws, DISPATCHES, [_artifact("F320-c", "tr-m1-d1", cited=True)],
            [], now="2026-09-28T00:00:00Z")
        st = rl.fold(ws, "round_credit/tr-m1-d1")["settlement"]
        assert "late_cited" not in st


# ---------- the rules table declares the ladder ----------------------------

class TestRulesDeclareTheLadder:
    def test_value_ladder_legs_declared(self):
        doc = rs.load_rules(RULES_PATH)
        rc = doc["round_credit"]
        ladder = rc["value_ladder"]
        assert ladder["full"] == 1.0
        assert ladder["trace"] == 0.01
        legs = ladder["legs"]
        assert legs["cited_or_used_toward_stage_verified"] == "full"
        assert legs["stage_milestone"] == "full"
        assert legs["refuted_with_replay_evidence"] == "trace"
        assert legs["uncited_verified"] == "trace"
        assert legs["action_success_tool_ran"] == 0.0

    def test_ladder_note_states_the_inversion_and_class_demotion(self):
        doc = rs.load_rules(RULES_PATH)
        low = str(doc["round_credit"]["value_ladder"]["note"]).lower()
        assert "admission ticket" in low
        assert "value condition" in low
        assert "late citation" in low or "late-cite" in low

    def test_no_reward_side_normalization_ruling_recorded(self):
        """Owner ruling 2026-09-28 in the rules file: within-cell
        homogeneity is a state-signature property — no reward-side
        normalization."""
        doc = rs.load_rules(RULES_PATH)
        low = str(doc["round_credit"]["value_ladder"]["note"]).lower()
        assert "state-signature" in low
        assert "z-score" in low and "rescaling" in low

    def test_version_bumped_for_the_semantic_change(self):
        doc = rs.load_rules(RULES_PATH)
        assert doc["schema"] == "reward-rules/1"
        assert doc["version"] == 3

    def test_prior_version_faces_still_foldable(self):
        """The pre-existing round_credit pins keep folding: attribution,
        positional_discount, untraced."""
        doc = rs.load_rules(RULES_PATH)
        rc = doc["round_credit"]
        assert rc["positional_discount"] is False
        assert "creator" in str(rc["attribution"])
        assert rc["untraced"]["counted"] is False
        assert rc["band"] == "ROUND_CREDIT"


# ---------- no reward-side normalization (source pin) ----------------------

class TestNoRewardSideNormalization:
    def test_no_normalization_symbols_in_the_settlement_source(self):
        text = (SCRIPTS / "scalar_settlement.py").read_text(
            encoding="utf-8").lower()
        # operation tokens only: the ruling VOCABULARY (the no-z-score,
        # no-rescaling wording) lives in reward-rules.yaml
        # round_credit.value_ladder.note, pinned by
        # TestRulesDeclareTheLadder — the source pin forbids the
        # operations, not the ruling sentence.
        for needle in ("z-score", "zscore", "z_score", "rescale"):
            assert needle not in text, needle

    def test_ruling_comment_lives_next_to_the_ladder(self):
        # issue 420 Phase 2: the ladder body lives at scripts/rlvr/scalar.py
        # (scripts/scalar_settlement.py is the re-export shim)
        low = (SCRIPTS / "rlvr" / "scalar.py").read_text(
            encoding="utf-8").lower()
        assert "state-signature" in low
        assert "2026-09-28" in low
