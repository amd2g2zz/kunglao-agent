# -*- coding: utf-8 -*-
"""tests/test_hypothesis_admission_109.py — #109 hypothesis admission gate.

#412's seeding contract has an unguarded back half: "the orchestrator fills
candidates BEFORE dispatching the first C-NN for this question" — nothing
enforced it (audit: zero guards). #109 closes it on the un-bypassable face
(hooks/dispatch_gate.py, same enforcement layer as must-stop/top1):

  A dispatch whose target claim `answers_question: qX` (qX a task_spec
  primary_question) is the FIRST dispatch into that PQ neighborhood only
  while the workspace has no dispatch-history row for any claim answering
  qX. That first dispatch REJECTs (exit 2, `<gate-verdict>` repair path)
  unless the hypothesis layer holds >= 2 non-adjudicated candidates for qX.

Framework-rigidity layer (protocol completeness, per the owner's two-layer
ruling): the REJECT reason is "protocol not fulfilled" — no declared
competing explanations — never "method looks bad". Subsequent dispatches on
the same PQ are unrestricted (the first hypothesis round supplies the
prior). Fail-open (#103 tiering): a hypothesis-store read failure WARNs +
traces and does not block.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _factories import write_hook_state

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------- fixtures ----------

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _write_hyp(ws: Path, hyp_id: str, *, candidates: list[str],
               status: str = "open", claim_id: str = "C-PENDING",
               group: str = "pq-q1", body_marker: str = "pq:q1") -> Path:
    """One hypotheses/<id>.md file in the #528 frontmatter shape."""
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        f"claim_id: {claim_id}\n"
        f"competitor_group: {group}\n"
        "candidates: [" + ", ".join(candidates) + "]\n"
        f"status: {status}\n"
        "schema_rev: 1\n"
        "---\n"
        + (f"\n{body_marker}\n\nSeeded scaffold — orchestrator fills "
           "candidates BEFORE the first dispatch (#412).\n"),
        encoding="utf-8")
    return p


def _mk_ws(root: Path, *, pq_ids: tuple[str, ...] = ("q1",)) -> Path:
    """Activated single-claim workspace: C-1 answers q1, q1 is a primary
    question, hypotheses/ NOT yet written (caller adds what it needs)."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write_yaml(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN", "statement": "recover the header mac",
         "answers_question": "q1"}]})
    _write_yaml(ws / "claim_deps.yaml",
                {"depends_on": {}, "competitor_groups": {}})
    _write_yaml(ws / "task_spec.yaml",
                {"primary_questions": list(pq_ids)})
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    (ws / "runs").mkdir()
    return ws


def _run_gate(root: Path, ws: Path, prompt: str,
              agent: str = "kunglao-worker") -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(root),
        "tool_input": {"prompt": prompt, "subagent_type": agent},
    })
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=90,
        cwd=str(REPO_ROOT), errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
    )


def _event_rows(ws: Path) -> list[dict]:
    """All rows from the unified event log (runs/logs/kunglao-*.jsonl)."""
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _intent_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "roi-intents.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


_PROMPT = "[T1 tools=Read,Write] claim C-1 probe the header mac path"


# ---------- AC 1: first dispatch into an empty PQ neighborhood REJECTs ----

class TestFirstDispatchAdmission:
    def test_empty_candidates_first_dispatch_rejects(self, tmp_path) -> None:
        """Scaffold exists (candidates=[] per #412) -> first dispatch into
        q1 REJECTs (exit 2) with the gate-verdict repair path naming q1."""
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=[])
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 2, (
            f"first dispatch into an empty PQ neighborhood must REJECT; "
            f"rc={r.returncode} stderr={r.stderr!r}")
        assert "REJECT hypothesis_admission" in r.stderr, f"stderr={r.stderr!r}"
        assert "REJECT hypothesis_admission (#109)" in r.stdout, (
            f"the face must carry its own issue attribution; {r.stdout!r}")
        assert "<gate-verdict>" in r.stdout, (
            f"the REJECT face must carry the #55 producer tag; "
            f"stdout={r.stdout!r}")
        assert "q1" in r.stdout, f"repair text must name the PQ; {r.stdout!r}"
        assert ("file ≥2 competing candidates for q1, each naming its "
                "falsifier") in r.stdout, (
            f"repair path must carry the #109 wording; stdout={r.stdout!r}")

    def test_absent_hypotheses_dir_rejects(self, tmp_path) -> None:
        """No hypotheses/ at all = zero candidates — same REJECT (the layer
        was never scaffolded is not an exemption, it is the worst case)."""
        root = tmp_path
        ws = _mk_ws(root)
        assert not (ws / "hypotheses").exists()
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        assert "REJECT hypothesis_admission" in r.stderr

    def test_single_candidate_still_rejects(self, tmp_path) -> None:
        """One candidate is the anchoring maximum: nothing can contradict
        the one story being chased (#109 problem statement)."""
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=["AES-CBC"])
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        assert "REJECT hypothesis_admission" in r.stderr

    def test_adjudicated_candidates_do_not_count(self, tmp_path) -> None:
        """A refuted hypothesis's candidates are history, not a live
        competitor field — they cannot satisfy the admission."""
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=["AES-CBC", "ChaCha20"],
                   status="refuted")
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        assert "REJECT hypothesis_admission" in r.stderr

    def test_reject_leaves_trace_and_skips_intent_record(
            self, tmp_path) -> None:
        """The REJECT face reaches the unified log (#459 word
        hypothesis_admission_reject, exit 2) and the #105 intent producer
        never fires — a blocked dispatch declares no intent."""
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=[])
        prompt = _PROMPT + "\nuncertainty: which mac the header uses"
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 2
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "hypothesis_admission_reject"]
        assert rows, f"reject trace missing; rows={_event_rows(ws)}"
        assert rows[0].get("claim") == "C-1"
        assert rows[0].get("exit") == 2
        assert "q1" in str(rows[0].get("detail"))
        assert _intent_rows(ws) == [], (
            "a REJECTed dispatch must not record a roi-intent row")


# ---------- AC 2: filing the candidates admits the same dispatch ---------

class TestAdmissionSatisfied:
    def test_two_candidates_on_one_scaffold_pass(self, tmp_path) -> None:
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=["AES-CBC", "ChaCha20"])
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 0, (
            f"filled candidate field must admit the dispatch; "
            f"stderr={r.stderr!r}")

    def test_two_open_hypotheses_one_candidate_each_pass(
            self, tmp_path) -> None:
        """The unit is the candidate, not the file: two open hypotheses
        holding one candidate each also clear the bar."""
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=["AES-CBC"])
        _write_hyp(ws, "H-002", candidates=["custom-rolling-mac"])
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 0, f"stderr={r.stderr!r}"

    def test_claim_linked_hypothesis_counts(self, tmp_path) -> None:
        """A hypothesis bound via claim_id (its claim answers q1) counts
        even without the seeder marker/competitor_group shape."""
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=["AES-CBC"],
                   claim_id="C-1", group="mac-structure", body_marker="")
        _write_hyp(ws, "H-002", candidates=["truncated-digest"],
                   claim_id="C-1", group="mac-structure", body_marker="")
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 0, f"stderr={r.stderr!r}"

    def test_colon_group_shape_counts(self, tmp_path) -> None:
        """`pq:q1` (colon variant) binds like the seeder's `pq-q1`."""
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=["AES-CBC"], group="pq:q1")
        _write_hyp(ws, "H-002", candidates=["ChaCha20"], group="pq:q1")
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 0, f"stderr={r.stderr!r}"


# ---------- AC 3: second dispatch on the same PQ is unrestricted ---------

class TestSecondDispatchUnrestricted:
    def test_redispatch_after_allowed_first_passes(self, tmp_path) -> None:
        """First dispatch admits (candidates filed, uncertainty declared ->
        roi-intents row). Stripping the candidates afterwards must NOT
        re-arm the gate: the history face (runs/roi-intents.jsonl claim
        association, #105 producer) shows q1 was already dispatched."""
        root = tmp_path
        ws = _mk_ws(root)
        _write_hyp(ws, "H-001", candidates=["AES-CBC", "ChaCha20"])
        first = _PROMPT + "\nuncertainty: which mac the header uses"
        assert _run_gate(root, ws, first).returncode == 0
        assert _intent_rows(ws), "first dispatch must land the history row"
        # strip the competitor field — the gate must stay open on history
        _write_hyp(ws, "H-001", candidates=[])
        second = _PROMPT + "\nuncertainty: re-check the mac branch"
        r = _run_gate(root, ws, second)
        assert r.returncode == 0, (
            f"a second dispatch on the same PQ must not re-trigger the "
            f"admission; stderr={r.stderr!r}")
        assert "REJECT hypothesis_admission" not in r.stderr

    def test_strategy_log_history_counts(self, tmp_path) -> None:
        """The #120-face dispatch history (runs/strategy-log.jsonl
        event=dispatch rows) also marks the PQ as already dispatched."""
        root = tmp_path
        ws = _mk_ws(root)
        log = ws / "runs" / "strategy-log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps({
            "ts": "2026-09-06T00:00:00Z", "event": "dispatch",
            "strategy": "s1", "claim": "C-1",
            "attempts_at_snapshot": 0}) + "\n", encoding="utf-8")
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 0, (
            f"strategy-log dispatch history must satisfy the first-dispatch "
            f"face; stderr={r.stderr!r}")


# ---------- guards: what must NOT trigger the gate ------------------------

class TestGateScopeGuards:
    def test_non_pq_claim_never_triggers(self, tmp_path) -> None:
        """answers_question null -> no PQ neighborhood -> no admission
        (parks/reinstatements and plain task claims stay unaffected)."""
        root = tmp_path
        ws = _mk_ws(root)
        reg = {"claims": [{"id": "C-1", "status": "OPEN",
                           "statement": "background sweep"}]}
        _write_yaml(ws / "claim-register.yaml", reg)
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        assert "REJECT hypothesis_admission" not in r.stderr

    def test_answers_to_unknown_id_is_not_a_pq(self, tmp_path) -> None:
        """qX must be a task_spec primary_question: a claim pointing at an
        id task_spec never declared is register drift, not an admission
        concern (the PQ neighborhood does not exist)."""
        root = tmp_path
        ws = _mk_ws(root, pq_ids=("q1",))
        reg = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8"))
        reg["claims"][0]["answers_question"] = "q99"
        _write_yaml(ws / "claim-register.yaml", reg)
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 0, f"stderr={r.stderr!r}"

    def test_inactive_gate_stays_asleep(self, tmp_path) -> None:
        """v1.9.7 hooks-sleep discipline: no activation -> no admission,
        rc 0 (the gate never fires outside the activated main flow)."""
        root = tmp_path
        ws = _mk_ws(root)
        write_hook_state(ws, active_hooks=[])
        r = _run_gate(root, ws, _PROMPT)
        assert r.returncode == 0, f"stderr={r.stderr!r}"


# ---------- fail-open: store outage warns + traces, never blocks ---------

class TestStoreFailureFailOpen:
    def test_store_read_failure_fails_open(self, tmp_path,
                                            monkeypatch) -> None:
        """A hypothesis-store read failure -> WARN + trace
        (hypothesis_admission_fail_open) and the dispatch proceeds."""
        import hypothesis_store as hs
        import dispatch_gate as dg

        def _boom(self):
            raise OSError("hypotheses/ unreadable")

        monkeypatch.setattr(hs.HypothesisStore, "list_all", _boom)
        ws = _mk_ws(tmp_path)
        _write_hyp(ws, "H-001", candidates=[])
        payload = {"tool_input": {"prompt": _PROMPT}}
        rc = dg._hypothesis_admission(ws, "C-1", payload)
        assert rc is None, "a store outage must not block the dispatch"
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "hypothesis_admission_fail_open"]
        assert rows, f"fail-open trace missing; rows={_event_rows(ws)}"
        assert rows[0].get("claim") == "C-1"
        assert "OSError" in str(rows[0].get("detail"))

    def test_register_unreadable_stays_silent(self, tmp_path,
                                              monkeypatch) -> None:
        """An unreadable claim register means the PQ neighborhood cannot be
        identified — the gate stays silent (no crash, no false REJECT)."""
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        (ws / "claim-register.yaml").write_text("::: not yaml :::[",
                                                encoding="utf-8")
        assert dg._hypothesis_admission(
            ws, "C-1", {"tool_input": {"prompt": _PROMPT}}) is None


# ---------- the store read helper (#109 surface on hypothesis_store) ------

class TestOpenCandidatesForQuestion:
    def _hyps(self, *specs: dict) -> list:
        from hypothesis_store import Hypothesis
        return [Hypothesis(id=s["id"], claim_id=s.get("claim_id", "C-PENDING"),
                           competitor_group=s.get("group", "pq-q1"),
                           candidates=s.get("candidates", []),
                           status=s.get("status", "open"),
                           body=s.get("body", ""))
                for s in specs]

    def test_binds_by_marker_group_and_claim_map(self) -> None:
        from hypothesis_store import open_candidates_for_question
        hyps = self._hyps(
            {"id": "H-1", "candidates": ["a"], "body": "pq:q1\nscaffold"},
            {"id": "H-2", "candidates": ["b"], "group": "pq-q1"},
            {"id": "H-3", "candidates": ["c"], "group": "pq:q1"},
            {"id": "H-4", "candidates": ["d"], "claim_id": "C-1",
             "group": "other"},
        )
        got = open_candidates_for_question(hyps, "q1", {"C-1": "q1"})
        assert sorted(got) == ["a", "b", "c", "d"], f"got {got}"

    def test_open_only_and_other_questions_excluded(self) -> None:
        from hypothesis_store import open_candidates_for_question
        hyps = self._hyps(
            {"id": "H-1", "candidates": ["live"], "body": "pq:q1"},
            {"id": "H-2", "candidates": ["dead"], "status": "refuted",
             "body": "pq:q1"},
            {"id": "H-3", "candidates": ["other-q"], "body": "pq:q2",
             "group": "pq-q2"},
        )
        got = open_candidates_for_question(hyps, "q1", {})
        assert got == ["live"], f"got {got}"

    def test_no_map_and_no_marker_binds_nothing(self) -> None:
        from hypothesis_store import open_candidates_for_question
        hyps = self._hyps({"id": "H-1", "candidates": ["x"],
                           "claim_id": "C-1", "group": "g"})
        assert open_candidates_for_question(hyps, "q1", None) == []


# ---------- vocabulary registration (#459 anchor sibling) -----------------

@pytest.mark.parametrize("word", ["hypothesis_admission_reject",
                                  "hypothesis_admission_fail_open"])
def test_admission_words_are_registered_emit_actions(word: str) -> None:
    """The gate's two new faces draw their event words from the controlled
    vocabulary (an unregistered literal turns the CI anchor red)."""
    import event_taxonomy as et
    assert word in et.EMIT_ACTIONS
