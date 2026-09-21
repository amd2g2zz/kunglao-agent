# -*- coding: utf-8 -*-
"""Issue #306 — emptiness-grade workspace identity (payload face of #240).

#240 made workspace identity fail-closed on marker ABSENCE (exit 64), but
only existence-only: an existing-but-empty (or key-less) task_spec.yaml +
an empty claim-register.yaml still drained to a WRONG CONVERGED rc=0 —
_parse_primary_questions maps key-absent/[] to "feature unused", zero
primary_questions leaves every DRAIN gate silent. Pre-#240 behavior was
identical (not a regression); the intake validation at analysis entry
(kunglao.py RC_ORACLE_ANCHORS_MISSING=7) leaves the residual window
"passed intake once, then rotted empty".

Contract (#306, hard-error design — the #240 family, never a verdict):
  - task_spec payload EMPTY (no live primary_questions AND no oracle-anchor
    stamp) + claim register EMPTY -> hard error, exit 66
    (EXIT_EMPTY_WORKSPACE), stderr names the state, stdout stays
    verdict-free. The probe lives inside decide(), so EVERY verdict
    consumer inherits it (CLI main, kunglao.py cmd_decide,
    kunglao-decide, kunglao_resume).
  - Discriminator (what init writes): kunglao-init's oracle-anchor intake
    runs BEFORE every scaffold write — a workspace that passed intake
    carries the three non-blank anchors (goal_verbatim /
    success_criterion / verification_method) in task_spec.yaml, while a
    pre-intake template scaffold ships a live placeholder primary
    question. Either one keeps the workspace verdictable; only the
    BOTH-EMPTY payload pair is degenerate ("intake never really happened",
    or the contract files rotted after intake).
  - Fail-open to the existing byte space: unreadable bytes stay with the
    #99 CRASHED face; the probe refuses only DEMONSTRABLY empty payloads.

Fast tier: in-process main()/decide() calls (the CLI cwd matrix lives in
test_convergence_cwd_matrix_240).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import contracts  # noqa: E402
import convergence_check as cc  # noqa: E402

TEMPLATE_TASK_SPEC = ROOT / "templates" / "state" / "task_spec.yaml"
TEMPLATE_REGISTER = ROOT / "templates" / "state" / "claim-register.yaml"

ANCHOR_STAMP = (
    "goal_verbatim: retrieve the family config\n"
    "success_criterion: family named with reproduction evidence\n"
    "verification_method: static\n"
)


def _rotted_ws(tmp_path: Path) -> Path:
    """Both markers EXIST, both payloads EMPTY — the issue's degenerate
    state that drained to CONVERGED rc=0 pre-fix."""
    ws = tmp_path / "rotted"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text("primary_questions: []\n",
                                       encoding="utf-8")
    return ws


def _assert_empty_workspace_error(excinfo, captured) -> None:
    assert excinfo.value.code == cc.EXIT_EMPTY_WORKSPACE
    assert cc.EXIT_EMPTY_WORKSPACE == 66
    err = captured.err
    assert "degenerate" in err, f"stderr must name the state: {err[-300:]}"
    assert "CONVERGED" not in captured.out, "a verdict escaped the hard error"
    assert captured.out.strip() == "", "stdout must stay verdict-free"


# ------------------------------------------------------------------
# acceptance (a): the degenerate pair is a hard error, never CONVERGED
# ------------------------------------------------------------------

def test_empty_task_spec_and_empty_register_hard_error(tmp_path, capsys):
    """THE issue repro: empty-key task_spec + empty register -> today
    CONVERGED rc=0; after: exit 66 hard error (pinned)."""
    ws = _rotted_ws(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        cc.main([str(ws), "--json"])
    _assert_empty_workspace_error(excinfo, capsys.readouterr())


def test_keyless_task_spec_and_empty_register_hard_error(tmp_path, capsys):
    """A key-less task_spec (comments only -> YAML null) is the same
    emptiness grade as the [] form."""
    ws = _rotted_ws(tmp_path)
    (ws / "task_spec.yaml").write_text(
        "# task_spec.yaml — filled by the init interview\n",
        encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cc.main([str(ws)])
    _assert_empty_workspace_error(excinfo, capsys.readouterr())


def test_zero_byte_task_spec_and_empty_register_hard_error(tmp_path, capsys):
    """An existing-but-zero-byte task_spec (truncation rot) is degenerate
    too: the marker exists, the contract is gone."""
    ws = _rotted_ws(tmp_path)
    (ws / "task_spec.yaml").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cc.main([str(ws)])
    _assert_empty_workspace_error(excinfo, capsys.readouterr())


def test_decide_direct_call_raises_the_same_byte(tmp_path):
    """kunglao.py cmd_decide / kunglao-decide / kunglao_resume call
    cc.decide() directly (never main) — the probe must live on the shared
    path so the router can never read a CONVERGED off a rotted workspace
    either."""
    ws = _rotted_ws(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        cc.decide(ws)
    assert excinfo.value.code == cc.EXIT_EMPTY_WORKSPACE


# ------------------------------------------------------------------
# the discriminators: what init writes keeps healthy shapes verdictable
# ------------------------------------------------------------------

def test_anchor_stamped_workspace_still_converges(tmp_path, capsys):
    """Feature-unused primary_questions + zero claims CONVERGES when the
    oracle-anchor stamp is present — a post-intake workspace that simply
    has no live questions. The anchors are what init's intake writes."""
    ws = _rotted_ws(tmp_path)
    (ws / "task_spec.yaml").write_text("primary_questions: []\n"
                                       + ANCHOR_STAMP, encoding="utf-8")
    rc = cc.main([str(ws), "--json"])
    captured = capsys.readouterr()
    assert rc == cc.EXIT_CONVERGED, (
        f"anchor-stamped feature-unused workspace must stay CONVERGED, "
        f"got rc={rc}; stderr={captured.err[-300:]}")
    assert '"decision": "CONVERGED"' in captured.out


def test_work_face_alone_still_dispatches(tmp_path, capsys):
    """One live claim keeps the workspace verdictable even with an empty
    task_spec payload — the #240 cwd-matrix shape is untouched."""
    ws = _rotted_ws(tmp_path)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-1\n"
        "  status: OPEN\n"
        "  boundary_type: positive_observation\n"
        "  evidence_tier_attempted: 0\n"
        "  promotion_attempts: 0\n"
        "  depends_on: '[]'\n",
        encoding="utf-8")
    rc = cc.main([str(ws), "--json"])
    captured = capsys.readouterr()
    assert rc == cc.EXIT_DISPATCH, (
        f"a live claim must still dispatch, got rc={rc}; "
        f"stderr={captured.err[-300:]}")
    assert '"decision": "DISPATCH"' in captured.out


def test_template_scaffold_is_not_misjudged_as_rotted(tmp_path, capsys):
    """Acceptance (b): a legitimately-keyless PRE-INTAKE template scaffold
    (the bytes kunglao-init's template ships: blank anchors + placeholder
    primary question, register `claims: []`) stays on the decided-state
    path — distinguishable from a rotted workspace, which hard-errors."""
    ws = tmp_path / "scaffold"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        TEMPLATE_REGISTER.read_text(encoding="utf-8"), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        TEMPLATE_TASK_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
    rc = cc.main([str(ws), "--json"])
    captured = capsys.readouterr()
    assert rc != cc.EXIT_EMPTY_WORKSPACE, (
        f"the template scaffold must not be misjudged as rotted: "
        f"stderr={captured.err[-300:]}")
    # the placeholder question keeps the loop honest: SATURATED (unanswered
    # primary question), never the degenerate CONVERGED
    assert '"decision": "SATURATED"' in captured.out
    assert rc == cc.EXIT_SATURATED


# ------------------------------------------------------------------
# byte-space + fail-open pins
# ------------------------------------------------------------------

def test_exit_byte_is_registered_and_distinct():
    """The #306 class joins the #99 consumer registry at the next free
    byte: 66 (0-5 decided, 64 MISSING_WORKSPACE, 65 CRASHED)."""
    assert contracts.EXIT_EMPTY_WORKSPACE == 66
    assert cc.EXIT_EMPTY_WORKSPACE is contracts.EXIT_EMPTY_WORKSPACE
    assert cc.EXIT_EMPTY_WORKSPACE not in (0, 1, 2, 3, 4, 5, 64, 65)


def test_corrupt_register_stays_with_the_crash_face(tmp_path, capsys):
    """Fail-open split (#275): unreadable bytes are #99's CRASHED face,
    not the #306 emptiness face — the probe refuses only demonstrably
    empty payloads. (main() RETURNS 65 per #99; it does not raise.)"""
    ws = _rotted_ws(tmp_path)
    (ws / "claim-register.yaml").write_text("title: [unclosed\nclaims: []\n",
                                            encoding="utf-8")
    rc = cc.main([str(ws), "--json"])
    captured = capsys.readouterr()
    assert rc == cc.EXIT_CRASHED
    assert rc != cc.EXIT_EMPTY_WORKSPACE
    assert '"decision": "CRASHED"' in captured.out


def test_probe_unit_faces(tmp_path):
    """The predicate itself: degenerate pair -> reason; every healthy /
    fail-open shape -> None."""
    ws = _rotted_ws(tmp_path)
    reason = cc._degenerate_reason(ws)
    assert reason is not None and "task_spec" in reason

    (ws / "task_spec.yaml").write_text("primary_questions: []\n"
                                       + ANCHOR_STAMP, encoding="utf-8")
    assert cc._degenerate_reason(ws) is None

    (ws / "task_spec.yaml").write_text("primary_questions: []\n",
                                       encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    assert cc._degenerate_reason(ws) is None

    (ws / "claim-register.yaml").write_text("title: [unclosed\n",
                                            encoding="utf-8")
    assert cc._degenerate_reason(ws) is None
