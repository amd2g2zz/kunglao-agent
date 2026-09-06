# -*- coding: utf-8 -*-
"""#110 case_bank goes live — write side (settlement -> bank) + read side
(cold-start retrieval injection into the hypothesis layer) + dedup.

RED-first tests pin the #110 contract:

- Write side: every SUCCESSFULLY settled claim lands one case row
  (scene/method/roi_class/outcome triple per ruling 1); NEGATIVE rows carry
  attribution (synthesized from the settlement's verdict/checker/signals when
  the producer supplied none — ruling 4 forbids unattributed failures).
- Fail-open: a case-bank append failure NEVER breaks settlement — a
  `case_bank_refused` warn event is the durable signal.
- Dedup: idempotent on (claim_id, method, roi_class) — duplicate settlements
  produce one row.
- Read side: at cold start (digest_build seeding chain), the bank is queried
  by (project_type + protection traits) and hits inject into the hypothesis
  layer as prior candidates with provenance "case-bank prior: <claim_id>";
  NEGATIVE rows lead (counterexample pruning); zero hits / zero rows /
  zero derivable context -> silent skip (cold start unchanged, no fabricated
  priors).

Storage note (design): case_bank is PER-WORKSPACE (runs/case-bank.jsonl), so
the issue's two-workspace cross-run face cannot read across workspaces — the
read side rides the cold-start digest chain (the same chain that already
fires seed_from_task_spec at every restart), which is the initialized
workspace's recurring cold start.
"""
import json
from pathlib import Path

import pytest

import case_bank as cb
import digest_build
import hypothesis_seeder as hs
import outcome_capture as oc
import roi_settlement as roi
from event_taxonomy import EMIT_ACTIONS


# ---------- fixtures ----------

def _write_task_spec(ws: Path, qid: str = "pq1") -> None:
    (ws / "task_spec.yaml").write_text(
        "project_type: android\n"
        "primary_questions:\n"
        f"  - id: {qid}\n"
        "    q: which unpack order restores the OEP\n",
        encoding="utf-8")


def _write_project_type(ws: Path, ptype: str = "android") -> None:
    (ws / "analysis_state.txt").write_text(
        f"project_type={ptype}\n", encoding="utf-8")


def _write_die(ws: Path, packer: str = "UPX") -> None:
    ev = ws / "evidence"
    ev.mkdir(exist_ok=True)
    (ev / "die.json").write_text(
        json.dumps({"derived": {"detected_packer": packer,
                                "high_entropy_sections": [".text"]}}),
        encoding="utf-8")


def _verify_note(ws: Path, name: str, claim_id: str, verdict: str) -> None:
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    (runs / name).write_text(
        f"---\nclaim_id: {claim_id}\n---\n\n## Overall verdict\n{verdict}\n",
        encoding="utf-8")


def _record_intent(ws: Path, claim_id: str = "C-1", **kw) -> dict:
    args = dict(method="upx-unpack", context_tags=["android", "packed"],
                uncertainty="which unpack order restores the OEP",
                expected_artifact="")
    args.update(kw)
    return roi.record_intent(ws, claim_id, **args)


def _case_entry(claim_id: str, **kw) -> dict:
    base = dict(claim_id=claim_id, method="upx-unpack",
                context_tags=["android", "packed"],
                intent_uncertainty="which unpack order restores the OEP",
                outcome_observed={"verdict": "passes"},
                roi_class="POSITIVE")
    base.update(kw)
    return base


# ---------- write side: settlement -> case row ----------

class TestSettlementBanking:
    def test_negative_settlement_banks_attributed_case_row(self, tmp_path):
        """fails verdict + recorded intent -> one NEGATIVE case row WITH
        attribution (ruling 4) carrying the full scene/method/outcome triple."""
        _record_intent(tmp_path)
        _verify_note(tmp_path, "a-verify-01.md", "C-1", "fails")

        added = oc.capture(tmp_path)

        assert added == 1
        rows = cb.read_entries(tmp_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["claim_id"] == "C-1"
        assert row["method"] == "upx-unpack"
        assert row["roi_class"] == "NEGATIVE"
        assert row["context_tags"] == ["android", "packed"]
        assert row["intent_uncertainty"] == \
            "which unpack order restores the OEP"
        assert row["outcome_observed"]["verdict"] == "fails"
        assert row["attribution"], "NEGATIVE row must carry attribution"
        assert "fails" in row["attribution"]

    def test_positive_settlement_banks_row_without_attribution(self, tmp_path):
        _record_intent(tmp_path)
        _verify_note(tmp_path, "a-verify-01.md", "C-1", "passes")

        oc.capture(tmp_path)

        rows = cb.read_entries(tmp_path)
        assert len(rows) == 1
        assert rows[0]["roi_class"] == "POSITIVE"
        assert rows[0]["attribution"] is None

    def test_producer_supplied_attribution_and_correction_ride_along(
            self, tmp_path):
        """A producer may pass attribution/premise_correction inside the
        settlement outcome; they land verbatim in the case row."""
        _record_intent(tmp_path)
        res = roi.settle_intent(tmp_path, "C-1", {
            "verdict": "fails", "checker": "verify-note",
            "attribution": "entrypoint guess skipped the real OEP",
            "premise_correction": "entrypoint != OEP for UPX"})
        assert res["ok"] is True
        entry = oc._case_entry_from_settlement(res["settlement"])
        assert entry["attribution"] == \
            "entrypoint guess skipped the real OEP"
        assert entry["premise_correction"] == "entrypoint != OEP for UPX"

    def test_unsettled_claim_banks_nothing(self, tmp_path):
        """No recorded intent -> no settlement -> no case row (unchanged)."""
        _verify_note(tmp_path, "a-verify-01.md", "C-1", "fails")
        oc.capture(tmp_path)
        assert cb.read_entries(tmp_path) == []

    def test_settlement_failure_still_fail_open(self, tmp_path, monkeypatch):
        """Banking failure must not break capture — the settlement row exists
        and a case_bank_refused warn event is emitted (fail-open contract)."""
        import kunglao_log

        _record_intent(tmp_path)
        _verify_note(tmp_path, "a-verify-01.md", "C-1", "fails")
        calls: list[dict] = []
        real_emit = kunglao_log.emit

        def _recorder(ws, actor, action, **kw):
            calls.append({"actor": actor, "action": action})
            return real_emit(ws, actor, action, **kw)

        monkeypatch.setattr(kunglao_log, "emit", _recorder)

        def _boom(ws, entry):
            raise cb.CaseBankError("disk full")

        monkeypatch.setattr(cb, "append_once", _boom)
        added = oc.capture(tmp_path)

        assert added == 1
        assert len(roi.read_settlements(tmp_path)) == 1
        assert cb.read_entries(tmp_path) == []
        assert any(c["action"] == "case_bank_refused" for c in calls)

    def test_case_bank_refused_is_registered_vocabulary(self):
        """Emit-face words come from EMIT_ACTIONS (#459 discipline)."""
        assert "case_bank_refused" in EMIT_ACTIONS
        assert "case_priors_seeded" in EMIT_ACTIONS


# ---------- dedup: (claim_id, method, roi_class) idempotent ----------

class TestDedup:
    def test_append_once_dedups_same_triple(self, tmp_path):
        first = cb.append_once(tmp_path, _case_entry("C-1"))
        second = cb.append_once(tmp_path, _case_entry("C-1"))
        assert first["ok"] is True and first["duplicate"] is False
        assert second["ok"] is True and second["duplicate"] is True
        assert len(cb.read_entries(tmp_path)) == 1

    def test_append_once_allows_different_roi_class(self, tmp_path):
        """An evolving verdict (fails -> passes) banks a NEW row: the dedup
        key is the (claim, method, roi_class) triple, not the claim alone."""
        cb.append_once(tmp_path, _case_entry(
            "C-1", roi_class="NEGATIVE",
            attribution="wrong unpack order",
            outcome_observed={"verdict": "fails"}))
        cb.append_once(tmp_path, _case_entry("C-1"))
        rows = cb.read_entries(tmp_path)
        assert sorted(r["roi_class"] for r in rows) == ["NEGATIVE", "POSITIVE"]

    def test_duplicate_settlement_produces_one_row(self, tmp_path):
        """Same settlement re-fired (ledger replay) -> bank stays at one row."""
        _record_intent(tmp_path)
        _verify_note(tmp_path, "a-verify-01.md", "C-1", "fails")
        oc.capture(tmp_path)
        assert len(cb.read_entries(tmp_path)) == 1

        ledger = tmp_path / oc.LEDGER_NAME
        ledger.unlink()  # simulate a replay of the same verify file
        oc.capture(tmp_path)
        assert len(cb.read_entries(tmp_path)) == 1

    def test_append_once_still_enforces_ruling4_lint(self, tmp_path):
        """Dedup never bypasses validation: an unattributed NEGATIVE is
        refused even on the once-face."""
        with pytest.raises(cb.CaseBankError, match="attribution"):
            cb.append_once(tmp_path, _case_entry("C-1", roi_class="NEGATIVE"))
        assert not cb.bank_path(tmp_path).exists()


# ---------- read side: cold-start retrieval injection ----------

class TestCasePriorInjection:
    def test_injects_failure_first_with_provenance(self, tmp_path):
        """Hits inject as prior candidates, NEGATIVE leading (counterexample
        pruning), each carrying "case-bank prior: <claim_id>" provenance."""
        _write_task_spec(tmp_path)
        _write_project_type(tmp_path)
        _write_die(tmp_path)
        cb.append(tmp_path, _case_entry("C-1"))  # POSITIVE, oldest
        cb.append(tmp_path, _case_entry("C-2", roi_class="NEGATIVE",
                                        attribution="wrong unpack order",
                                        premise_correction="entrypoint != OEP",
                                        outcome_observed={"verdict": "fails"}))
        cb.append(tmp_path, _case_entry("C-3"))  # POSITIVE, newest

        n = hs.seed_case_candidates(tmp_path)

        assert n == 3
        store = hs.HypothesisStore(tmp_path / "hypotheses")
        carrier = [h for h in store.list_all()
                   if hs.CASE_BODY_MARKER in h.body]
        assert len(carrier) == 1
        cands = carrier[0].candidates
        assert cands[0].startswith("case-bank prior: C-2")
        assert "NEGATIVE" in cands[0]
        assert "wrong unpack order" in cands[0]
        assert "entrypoint != OEP" in cands[0]
        assert [c.split(": ")[1].split(" ")[0] for c in cands] == \
            ["C-2", "C-3", "C-1"]

    def test_tag_intersection_scopes_injection(self, tmp_path):
        """A row whose context shares no tag with the derived context
        (project_type + protection traits) is NOT injected."""
        _write_task_spec(tmp_path)
        _write_project_type(tmp_path)
        cb.append(tmp_path, _case_entry("C-1"))
        cb.append(tmp_path, _case_entry("C-9", context_tags=["osint"],
                                        method="osint-query"))

        n = hs.seed_case_candidates(tmp_path)

        assert n == 1
        store = hs.HypothesisStore(tmp_path / "hypotheses")
        carrier = [h for h in store.list_all()
                   if hs.CASE_BODY_MARKER in h.body][0]
        assert len(carrier.candidates) == 1
        assert "case-bank prior: C-1" in carrier.candidates[0]
        assert all("C-9" not in c for c in carrier.candidates)

    def test_idempotent_rerun_adds_nothing(self, tmp_path):
        _write_task_spec(tmp_path)
        _write_project_type(tmp_path)
        cb.append(tmp_path, _case_entry("C-1"))

        assert hs.seed_case_candidates(tmp_path) == 1
        assert hs.seed_case_candidates(tmp_path) == 0

        store = hs.HypothesisStore(tmp_path / "hypotheses")
        carrier = [h for h in store.list_all()
                   if hs.CASE_BODY_MARKER in h.body][0]
        assert len(carrier.candidates) == 1

    def test_new_case_joins_existing_carrier(self, tmp_path):
        _write_task_spec(tmp_path)
        _write_project_type(tmp_path)
        cb.append(tmp_path, _case_entry("C-1"))
        hs.seed_case_candidates(tmp_path)
        cb.append(tmp_path, _case_entry("C-2", roi_class="NEGATIVE",
                                        attribution="packed entrypoint guess"))

        assert hs.seed_case_candidates(tmp_path) == 1

        store = hs.HypothesisStore(tmp_path / "hypotheses")
        carrier = [h for h in store.list_all()
                   if hs.CASE_BODY_MARKER in h.body]
        assert len(carrier) == 1  # no second carrier file
        assert len(carrier[0].candidates) == 2

    def test_zero_rows_silent(self, tmp_path):
        """Empty bank -> nothing injected, cold start unchanged (#110
        acceptance: no fabricated priors)."""
        _write_task_spec(tmp_path)
        _write_project_type(tmp_path)

        assert hs.seed_case_candidates(tmp_path) == 0
        store = hs.HypothesisStore(tmp_path / "hypotheses")
        assert [h for h in store.list_all()
                if hs.CASE_BODY_MARKER in h.body] == []

    def test_no_derivable_context_silent(self, tmp_path):
        """No project_type + no protection evidence -> no query context ->
        no injection (never a context-free 'match everything' prior)."""
        _write_task_spec(tmp_path)
        cb.append(tmp_path, _case_entry("C-1"))

        assert hs.seed_case_candidates(tmp_path) == 0
        store = hs.HypothesisStore(tmp_path / "hypotheses")
        assert [h for h in store.list_all()
                if hs.CASE_BODY_MARKER in h.body] == []

    def test_protection_traits_derive_query_tags(self, tmp_path):
        """DIE packer evidence widens the query context beyond project_type:
        a row tagged only with the trait token still matches."""
        _write_project_type(tmp_path)
        _write_die(tmp_path, packer="VMProtect")
        tags = hs._case_query_tags(tmp_path)
        assert "android" in tags
        assert "packed" in tags
        assert "vmprotect" in tags
        assert "high-entropy" in tags

    def test_cold_start_digest_chain_injects(self, tmp_path):
        """The injection rides the cold-start digest chain (the same chain
        that fires seed_from_task_spec) and is visible in sec_g — the
        initialized workspace's recurring cold start."""
        _write_task_spec(tmp_path)
        _write_project_type(tmp_path)
        cb.append(tmp_path, _case_entry("C-1"))
        cb.append(tmp_path, _case_entry("C-2", roi_class="NEGATIVE",
                                        attribution="wrong unpack order",
                                        outcome_observed={"verdict": "fails"}))

        md = digest_build.build_digest(tmp_path)

        store = hs.HypothesisStore(tmp_path / "hypotheses")
        assert any("pq:pq1" in h.body for h in store.list_all()), \
            "pq scaffolds still seeded (unchanged face)"
        assert "case-bank prior: C-2" in md  # sec_g carries the priors
        assert md.index("case-bank prior: C-2") < md.index("case-bank prior: C-1")

    def test_case_priors_seeded_event(self, tmp_path, monkeypatch):
        """Injection emits its telemetry face (like apkid/taint seeders)."""
        import kunglao_log
        _write_task_spec(tmp_path)
        _write_project_type(tmp_path)
        cb.append(tmp_path, _case_entry("C-1"))
        calls: list[dict] = []
        real_emit = kunglao_log.emit

        def _recorder(ws, actor, action, **kw):
            calls.append({"actor": actor, "action": action})
            return real_emit(ws, actor, action, **kw)

        monkeypatch.setattr(kunglao_log, "emit", _recorder)
        hs.seed_case_candidates(tmp_path)
        assert any(c["action"] == "case_priors_seeded" for c in calls)
