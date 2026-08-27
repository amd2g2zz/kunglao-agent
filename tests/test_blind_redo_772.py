#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_blind_redo_772.py — issue #772 重做方向的盲性缺口 (L 组).

Sections (TDD order):
  1. T1 = L1+L2 — scripts/dispatch_context.py::build_redo_context(ws,
     diff_path): the REDO slice. Symmetric to #527's verifier BLIND slice
     but on the OPPOSITE edge: when the orchestrator re-dispatches a claim
     after a redteam DIFF, the redo prompt must carry WHERE the maker
     diverged (gap shape) and NEVER WHAT the right answer is (the red team's
     derived values / conclusion lines / anchors).
  2. T2 = L3   — contract in three places: SKILL.md §1b GAP-ONLY clause,
     kunglao-worker "you receive a GAP not an answer" clause, kunglao-redteam
     "DIFF readers are the adjudication layer" note.
  3. T3 = L4   — hooks/dispatch_gate.py::_redo_leak_check: a dispatch prompt
     marked redo/重做 that overlaps the latest verify-redteam DIFF on value
     strings (>=4-digit numbers / >=16-char hex) draws a stderr WARN and
     keeps rc=0 (WARN discipline: heuristic false positives are too costly
     for REJECT).

#772 gap forensics: #527 hard-exclusion protects the verifier INPUT side
only (dispatch_context.py L373 BLIND slice). The reverse direction had zero
protection — the sample-incident-01 real case ("producer claimed anchor 3494,
actual 3446") would have leaked straight into a redo prompt and the worker's
second "independent derivation" would just be copying the checker.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
HOOKS_DIR = REPO_ROOT / "hooks"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_dc = _load("_dispatch_context_772", SCRIPTS_DIR / "dispatch_context.py")

# ==========================================================================
# Shared fixtures: a red-team DIFF carrying the sample-incident-01 leak shape
# ==========================================================================

DIFF_BODY = """\
# Red-team verification: claim C-005 sec_user_id anchor recovery
## Claim under attack
producer claimed anchor 3494 for sec_user_id via StringBuilder scope sweep
## My independent derivation
recomputed from raw dex bytes: actual anchor 3446, delta -48 from producer
sha256 of recomputed region: 3f9a11c2d47b6e8055aa12bb34cc90ee
static offset derivation chain starts at 0x1a2b3c
## Attack attempts
method blind spot suspected: wrong search granularity in v4 StringBuilder
scope assumption was challenged as unfounded
negative-result overreach: single-method derivation only
## RED-TEAM VERDICT: REFUTED
## MACHINE-CHECK (oracle contract #332)
```machine_check
[{"command": "xxd -p -s 0x0 -l 4 bins/abc", "expected": "61323639",
  "actual": "36343436", "passed": false}]
```
## GAPs (if any)
- anchor mismatch at sec_user_id field: producer value not reproduced from
  raw bytes; evidence gap on which tokenizer version applies
- method assumption unproven: producer never showed >=2 independent paths
"""


@pytest.fixture
def tmp_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-005\n  status: OPEN\n",
        encoding="utf-8")
    diff = ws / "runs" / "verify-redteam-C-005.md"
    diff.write_text(DIFF_BODY, encoding="utf-8")
    return ws


def _redo(ws: Path, diff: Path | None = None) -> dict:
    return _dc.build_redo_context(
        ws, diff if diff is not None else ws / "runs" / "verify-redteam-C-005.md")


# ==========================================================================
# 1. T1/L1+L2 — build_redo_context sanitization (#772)
# ==========================================================================

class TestRedoSliceSanitization:
    def test_leaked_actual_value_absent(self, tmp_ws: Path) -> None:
        """The sample-incident-01 shape: DIFF carries 'actual anchor 3446'. The
        REDO slice MUST NOT carry the literal '3446' anywhere."""
        blob = json.dumps(_redo(tmp_ws), ensure_ascii=False)
        assert "3446" not in blob, f"leaked red-team derived value: {blob!r}"

    def test_producer_claimed_value_also_absent(self, tmp_ws: Path) -> None:
        """The producer's OWN wrong value is equally an answer from the redo
        worker's perspective (worker-writes-to-the-answer failure mode)."""
        blob = json.dumps(_redo(tmp_ws), ensure_ascii=False)
        assert "3494" not in blob, f"leaked producer claimed value: {blob!r}"

    def test_gap_shape_preserved(self, tmp_ws: Path) -> None:
        ctx = _redo(tmp_ws)
        # divergence class by keyword classification
        assert ctx["divergence_class"] == "anchor_mismatch"
        # field-level pointer survives ("where", not "what")
        assert "sec_user_id" in ctx["gap"]
        assert ctx["kind"] == "REDO"
        assert ctx["sanitized"] is True
        assert ctx["claim_id"] == "C-005"

    def test_independent_derivation_section_withheld(self, tmp_ws: Path) -> None:
        """The red team's own derivation body IS the answer — the whole
        section must be withheld from the slice."""
        blob = json.dumps(_redo(tmp_ws), ensure_ascii=False)
        assert "delta -48" not in blob
        assert "tokenizer" not in blob.split('"gap"')[0]

    def test_withhold_placeholder_fires_on_real_contract_form(
            self, tmp_path: Path) -> None:
        """r1 F1 pin (presence face): a DIFF whose header is the REAL
        contract form `## My independent derivation` must trip the withhold
        marker — pre-fix, the `##` prefix defeated the startswith comparison
        and only accidental line-drop regexes masked it."""
        ws = tmp_path / "p1"
        (ws / "runs").mkdir(parents=True)
        diff = ws / "runs" / "verify-redteam-p.md"
        diff.write_text(
            "# Red-team verification: p\n"
            "## My independent derivation\nplain prose with no digits\n"
            "## RED-TEAM VERDICT: REFUTED\n## GAPs\n- shape noted\n",
            encoding="utf-8")
        kept, _n = _dc._sanitize_diff_body(
            diff.read_text(encoding="utf-8"))
        assert any("withheld from redo slice (#772)" in ln for ln in kept), (
            f"withhold placeholder missing from kept lines: {kept!r}")
        # and the answer prose is NOT anywhere in the built slice
        blob = json.dumps(_dc.build_redo_context(ws, diff),
                          ensure_ascii=False)
        assert "plain prose with no digits" not in blob

    def test_r1_face_leak_prose_absent(self, tmp_path: Path) -> None:
        """r1 F1 pin (absence face): the two reviewer-measured leak
        sentences — small-value anchors that evade >=3-digit scrubbing and
        drop-line regexes alike — MUST be absent when they live under the
        independent-derivation section."""
        ws = tmp_path / "p2"
        (ws / "runs").mkdir(parents=True)
        diff = ws / "runs" / "verify-redteam-q.md"
        diff.write_text(
            "# Red-team verification: q\n"
            "## My independent derivation\n...correct descriptor index "
            "is 9.\nThe correct field number is 6, which settles it.\n"
            "## Attack attempts\ntable walk compared against itself twice\n"
            "## GAPs\n- divergence recorded at the table-walk stage\n",
            encoding="utf-8")
        blob = json.dumps(_dc.build_redo_context(ws, diff),
                          ensure_ascii=False)
        assert "descriptor index is 9" not in blob, (
            "Face A leak sentence survived into the redo slice")
        assert "field number is 6" not in blob, (
            "Face B leak sentence survived into the redo slice")
        # gap-shape pointer survives
        assert "divergence recorded" in blob

    def test_machine_check_fence_values_withheld(self, tmp_ws: Path) -> None:
        """machine_check fences carry expected/actual literals by contract
        (#332) — exactly what a redo worker must not see."""
        blob = json.dumps(_redo(tmp_ws), ensure_ascii=False)
        assert "61323639" not in blob
        assert "36343436" not in blob

    def test_hex_and_addr_tokens_scrubbed(self, tmp_path: Path) -> None:
        ws = tmp_path / "w2"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir(parents=True, exist_ok=True)
        diff = ws / "runs" / "verify-redteam-x.md"
        diff.write_text(
            "# Red-team verification: x\n## My independent derivation\n"
            "region hash deadbeefcafe12345678 at base 0x7ffd1a2b\n"
            "## RED-TEAM VERDICT: REFUTED\n## GAPs\n- mismatch noted\n",
            encoding="utf-8")
        blob = json.dumps(_dc.build_redo_context(ws, diff),
                          ensure_ascii=False)
        assert "deadbeefcafe12345678" not in blob
        assert "0x7ffd1a2b" not in blob

    def test_claim_and_fact_id_references_survive(self, tmp_path: Path) -> None:
        """F<NNN>/C-NN references are bookkeeping, not derived answers — they
        must survive scrubbing so the redo worker knows where to look."""
        ws = tmp_path / "w3"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir(parents=True, exist_ok=True)
        diff = ws / "runs" / "verify-redteam-y.md"
        diff.write_text(
            "# Red-team verification: y cites C-007 / F018\n"
            "## My independent derivation\nvalue 987654 recomputed twice\n"
            "## RED-TEAM VERDICT: UNVERIFIED-WITH-GAP\n"
            "## GAPs\n- F018 does not cover the searched range; see C-007\n",
            encoding="utf-8")
        blob = json.dumps(_dc.build_redo_context(ws, diff),
                          allow_nan=False, default=str)
        assert "C-007" in blob
        assert "F018" in blob
        assert "987654" not in blob

    def test_conclusion_led_lines_dropped(self, tmp_path: Path) -> None:
        ws = tmp_path / "w4"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir(parents=True, exist_ok=True)
        diff = ws / "runs" / "verify-redteam-z.md"
        diff.write_text(
            "# Red-team verification: z\n## Attack attempts\n"
            "actual anchor recovered: 424242 matches intent\n"
            "expected result was a different table walk\n"
            "## GAPs\n- where it diverged is recorded here instead\n",
            encoding="utf-8")
        blob = json.dumps(_dc.build_redo_context(ws, diff),
                          ensure_ascii=False)
        assert "424242" not in blob


class TestRedoSliceContract:
    def test_divergence_class_method_challenged(self, tmp_path: Path) -> None:
        ws = tmp_path / "m1"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir(parents=True, exist_ok=True)
        diff = ws / "runs" / "verify-redteam-m.md"
        diff.write_text(
            "# Red-team verification: m\n"
            "## Attack attempts\nwrong granularity on the PE export walk; "
            "the underlying method assumption is invalid\n"
            "## RED-TEAM VERDICT: UNVERIFIED-WITH-GAP\n"
            "## GAPs\n- no reproducible path either way\n",
            encoding="utf-8")
        ctx = _dc.build_redo_context(ws, diff)
        assert ctx["divergence_class"] == "method_challenged"

    def test_divergence_class_evidence_gap(self, tmp_path: Path) -> None:
        ws = tmp_path / "e1"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir(parents=True, exist_ok=True)
        diff = ws / "runs" / "verify-redteam-e.md"
        diff.write_text(
            "# Red-team verification: e\n## GAPs\n"
            "- insufficient coverage: behavior unproven beyond the "
            "searched window (missing dynamic evidence)\n",
            encoding="utf-8")
        ctx = _dc.build_redo_context(ws, diff)
        assert ctx["divergence_class"] == "evidence_gap"

    def test_challenged_assumptions_extracted(self, tmp_ws: Path) -> None:
        ctx = _redo(tmp_ws)
        assert any("assumption" in c.lower() or "StringBuilder" in c
                   for c in ctx["challenged"])

    def test_hint_direction_present(self, tmp_ws: Path) -> None:
        ctx = _redo(tmp_ws)
        hint = ctx["hint_direction"].lower()
        assert "re-derive" in hint or "独立重推" in hint
        # the hint must instruct independence, not name values
        assert "3446" not in hint

    def test_missing_diff_fails_open(self, tmp_path: Path) -> None:
        ws = tmp_path / "nope"
        ws.mkdir()
        ctx = _dc.build_redo_context(ws, ws / "runs" / "absent.md")
        assert ctx["sanitized"] is True
        assert ctx.get("error") == "diff_not_found"
        assert ctx["gap"] == ""
        assert "3446" in "" or True  # honest empty slice, never raises

    def test_unreadable_diff_fails_open(self, tmp_ws: Path,
                                        monkeypatch: pytest.MonkeyPatch
                                        ) -> None:
        diff = tmp_ws / "runs" / "verify-redteam-C-005.md"
        monkeypatch.setattr(Path, "read_text",
                            lambda *a, **k: (_ for _ in ()).throw(
                                OSError("denied")))
        ctx = _dc.build_redo_context(tmp_ws, diff)
        assert ctx["sanitized"] is True
        assert ctx.get("error") == "diff_unreadable"

    def test_cli_redo_diff_smoke(self, tmp_ws: Path) -> None:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "dispatch_context.py"),
             str(tmp_ws), "--redo-diff",
             str(tmp_ws / "runs" / "verify-redteam-C-005.md")],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        out = json.loads(r.stdout)
        assert out["kind"] == "REDO"
        assert "3446" not in r.stdout


# ==========================================================================
# 2. T2/L3 — contract in three places (#772)
# ==========================================================================

class TestTripleContractText:
    def _text(self, rel: str) -> str:
        return (REPO_ROOT / rel).read_text(encoding="utf-8")

    def test_skill_md_gap_only_clause(self) -> None:
        t = self._text("skills/kunglao-agent/SKILL.md")
        assert "GAP-ONLY" in t and "WHERE it diverged" in t, (
            "SKILL.md §1b must carry the symmetric redo-blindness clause")
        assert "verifiers must be BLIND" in t
        # SKILL.md body forbids bare issue refs (test_skill_contract) —
        # the clause must not smuggle one back in (body = post-frontmatter)
        import re as _re
        body = t.split("---", 2)[2]
        assert not _re.search(r"#\d{2,3}", body), (
            "issue-number refs are forbidden in SKILL.md body")

    def test_worker_md_gap_not_answer_clause(self) -> None:
        t = self._text("agents/kunglao-worker.md")
        assert "GAP-shaped" in t, (
            "worker md must pin the redo-gap contract (GAP-shaped inputs)")
        assert "never checker-derived values" in t, (
            "worker contract: you receive a GAP, not an answer")
        assert "independent derivation is a FAIL" in t, (
            "worker contract: matching a DIFF-seen value without independent "
            "derivation is a FAIL, not a pass")

    def test_redteam_md_adjudication_reader_clause(self) -> None:
        t = self._text("agents/kunglao-redteam.md")
        assert "DIFF readers are the orchestrator" in t, (
            "redteam md must pin the DIFF-reader rule")
        assert "adjudication layer" in t, (
            "DIFF readers are the adjudication layer")
        # conclusions stay full on the red-team side — the filter lives
        # in dispatch_context's REDO slice, NOT in the red-team writer.
        assert "REDO slice" in t or "build_redo_context" in t


# ==========================================================================
# 3. T3/L4 — dispatch gate redo-leak WARN (#772)
# ==========================================================================

_GATE = REPO_ROOT / "hooks" / "dispatch_gate.py"


def _run_gate(root: Path, prompt: str) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(root / "malware-analysis-workspace"),
        "tool_input": {"prompt": prompt},
    })
    return subprocess.run(
        [sys.executable, str(_GATE)],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT), errors="replace")


def _ws_with_diff(root: Path) -> Path:
    ws = root / "malware-analysis-workspace"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-005\n  status: OPEN\n", encoding="utf-8")
    (ws / "runs" / "verify-redteam-C-005.md").write_text(
        DIFF_BODY, encoding="utf-8")
    return ws


class TestRedoLeakWarn:
    def test_leaky_redo_prompt_warns_rc0(self, tmp_path: Path) -> None:
        """redo-marked prompt overlapping a DIFF value string → WARN, and
        rc stays 0 (WARN-not-REJECT discipline; heuristics false-positive)."""
        _ws_with_diff(tmp_path)
        r = _run_gate(
            tmp_path,
            "[T1 tools=Read,Write,Grep] claim C-005 redo — you got this "
            "wrong, correct sec_user_id to actual anchor 3446 and rerun")
        assert r.returncode == 0, (
            f"WARN must not REJECT; rc={r.returncode} stderr={r.stderr!r}")
        blob = r.stdout + r.stderr
        assert "redo" in blob.lower() and ("WARN" in blob or "warn" in blob)

    def test_clean_gap_prompt_no_warn(self, tmp_path: Path) -> None:
        """A properly built GAP-only redo prompt triggers nothing."""
        _ws_with_diff(tmp_path)
        r = _run_gate(
            tmp_path,
            "[T1 tools=Read,Write,Grep] claim C-005 redo — prior attempt "
            "diverged: anchor mismatch at sec_user_id, StringBuilder scope "
            "assumption questioned. Re-derive independently.")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        blob = r.stdout + r.stderr
        assert "redo-leak" not in blob.lower()
        assert "redo_leak" not in blob
        assert "overlap" not in blob.lower()

    def test_non_redo_prompt_untouched(self, tmp_path: Path) -> None:
        """No redo marker → the face sleeps even with a leaking prompt."""
        _ws_with_diff(tmp_path)
        r = _run_gate(
            tmp_path,
            "[T1 tools=Read,Write,Grep] claim C-005 fresh sweep — recover "
            "sec_user_id anchor 3446 from raw bytes")
        assert r.returncode == 0
        assert "redo_leak" not in (r.stdout + r.stderr)

    def test_failopen_without_diff_files(self, tmp_path: Path) -> None:
        """No workspace / no DIFF files → silent open, never an exception."""
        _run_gate(tmp_path,
                  "[T1 tools=Read,Write] claim C-005 redo — retry")
        ws = _ws_with_diff(tmp_path)
        (ws / "runs" / "verify-redteam-C-005.md").unlink()
        r = _run_gate(
            ws.parent,
            "[T1 tools=Read,Write,Grep] claim C-005 redo — anything at all "
            "with number 3446 inside")
        assert r.returncode == 0
        assert "redo_leak" not in (r.stdout + r.stderr)

    def test_emit_action_registered(self) -> None:
        """#459 discipline: every emit face word comes from EMIT_ACTIONS."""
        et = _load("_event_taxonomy_772", SCRIPTS_DIR / "event_taxonomy.py")
        assert "redo_leak_warn" in et.EMIT_ACTIONS
