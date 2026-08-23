# -*- coding: utf-8 -*-
"""#443 regression anchor — pre/post-refactor decide() output equality.

Design (openspec/changes/issue-443-decide-state-machine/design.md §5):
decide() is reorganized into an explicit state machine with ZERO gate
semantics change. This module proves it with TWO channels:

  1. LIVE BASELINE (maker-checker): extract the pre-refactor decide()
     from git commit c5cb1ae at test time, run it and the current
     decide() on the SAME fixture workspace, compare full outputs.
     Expected values are derived from the OLD code — never hand-written.
  2. FROZEN SNAPSHOT (permanent): tests/decide_anchor_c5cb1ae.json holds
     the machine-generated c5cb1ae outputs (design §5 regen command);
     the current decide() must reproduce them byte-for-byte per case.
     Survives git history pruning; channel 1 skips without history.

Matrix: ~30 cases covering every branch of the old elif chain, gate
interleavings where ORDER decides (schema>dispatch, orphan>unverified,
unverified>note-gap, note-gap>discovery, discovery>contradiction,
opens>partials, queue>failure, failure>all-blocked), and the #495/#497
interleavings (failure three-artifact protocol, ladder-exhaustion).

Determinism: worker-status files are freshly written (mtime fresh →
stuck_workers always []), removing age_min time drift from the anchor.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check  # module under test (== baseline before #443 GREEN)

BASELINE_COMMIT = "c5cb1ae"  # origin/dev at v012/issue-443-decide-state-machine branch point
ANCHOR_FILE = Path(__file__).parent / "decide_anchor_c5cb1ae.json"

_CLEAN_INDEX = "# facts\n"
_CONTRA_INDEX = (
    "# facts\n"
    "F001 | PROVEN | C-001 | payload is shellcode\n"
    "F002 | PROVEN | C-002 | payload is not shellcode\n"
)
_PARTIAL_INDEX = "# facts\nF001 | PARTIAL | C-1 | needs verification\n"


# ---------------------------------------------------------------- fixtures

def _ws(base: Path, name: str) -> Path:
    ws = base / name
    (ws / "runs").mkdir(parents=True)
    return ws


def _reg(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False, allow_unicode=True),
        encoding="utf-8")


def _ts(ws: Path, text: str) -> None:
    (ws / "task_spec.yaml").write_text(text, encoding="utf-8")


def _pq(questions: str = "[]") -> str:
    return f"primary_questions: {questions}\n"


def _pq_canonical(qid: str = "q1", need: str = "model_selection") -> str:
    return (f"primary_questions:\n  - id: {qid}\n    q: what is it\n"
            f"    need: {need}\n")


def _fact_dir(ws: Path, index: str = _CLEAN_INDEX, files: dict | None = None) -> None:
    fdir = ws / "facts"
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / "_INDEX.md").write_text(index, encoding="utf-8")
    for fname, body in (files or {}).items():
        (fdir / fname).write_text(body, encoding="utf-8")


def _notes(ws: Path, notes: dict[str, tuple[str, str]]) -> None:
    """notes[name] = (claim_id, verify_status)."""
    ndir = ws / "notes"
    ndir.mkdir(parents=True, exist_ok=True)
    for fname, (cid, vs) in notes.items():
        (ndir / fname).write_text(
            f"---\nclaim_id: {cid}\nverify_status: {vs}\n---\nnote body\n",
            encoding="utf-8")


def _workers(ws: Path, n: int, status: str = "in-progress") -> None:
    for i in range(1, n + 1):
        (ws / "runs" / f"worker-status-w{i}.md").write_text(
            f"claim C-{i} | step x | status: {status}\n", encoding="utf-8")


def _analysis(ws: Path, claim_id: str, **fields) -> None:
    """#495 failure analysis record (analyses/failure-<C-NN>.yaml shape)."""
    adir = ws / "analyses"
    adir.mkdir(parents=True, exist_ok=True)
    entry = {"claim": claim_id, **fields}
    (adir / f"failure-{claim_id}.yaml").write_text(
        yaml.safe_dump(entry, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _blocker_files(ws: Path, names: list[str]) -> None:
    bdir = ws / "blockers"
    bdir.mkdir(parents=True, exist_ok=True)
    for b in names:
        (bdir / f"{b}.md").write_text("reason: env down\n", encoding="utf-8")


def _claim(cid: str, **fields) -> dict:
    return {"id": cid, "status": "OPEN", **fields}


# ------------------------------------------------------------- the matrix

def _c_schema_invalid_int_item(base: Path) -> Path:
    ws = _ws(base, "schema_invalid_int_item")
    _reg(ws, [_claim("C-1")])
    _ts(ws, "primary_questions:\n  - 5\n")
    return ws


def _c_schema_invalid_duplicate_qid(base: Path) -> Path:
    ws = _ws(base, "schema_invalid_duplicate_qid")
    _reg(ws, [_claim("C-1")])
    _ts(ws, "primary_questions:\n  - id: q1\n  - id: q1\n")
    return ws


def _c_schema_invalid_beats_dispatch(base: Path) -> Path:
    """Order anchor: malformed schema wins even with dispatchable work."""
    ws = _ws(base, "schema_invalid_beats_dispatch")
    _reg(ws, [_claim("C-1")])  # unblocked open + 3 free slots
    _ts(ws, "primary_questions:\n  - [1, 2]\n")
    return ws


def _c_drain_converged_minimal(base: Path) -> Path:
    ws = _ws(base, "drain_converged_minimal")
    _reg(ws, [])
    _ts(ws, _pq("[]"))
    return ws


def _c_drain_converged_full(base: Path) -> Path:
    ws = _ws(base, "drain_converged_full")
    _reg(ws, [{"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    _ts(ws, _pq_canonical())
    _notes(ws, {"n1.md": ("C-1", "passes")})
    _fact_dir(ws)
    return ws


def _c_drain_converged_yesno_negative(base: Path) -> Path:
    """need=yes_no_with_evidence is satisfied by a NEGATIVE terminal answer."""
    ws = _ws(base, "drain_converged_yesno_negative")
    _reg(ws, [{"id": "C-1", "status": "NEGATIVE", "answers_question": "q1"}])
    _ts(ws, _pq_canonical(need="yes_no_with_evidence"))
    _notes(ws, {"n1.md": ("C-1", "passes")})
    _fact_dir(ws)
    return ws


def _c_drain_blocked_orphans(base: Path) -> Path:
    ws = _ws(base, "drain_blocked_orphans")
    _reg(ws, [
        {"id": "C-1", "status": "PROVEN", "answers_question": "q1"},
        {"id": "C-2", "status": "PROVEN"},  # terminal, no answers_question
    ])
    _ts(ws, _pq_canonical())
    _notes(ws, {"n1.md": ("C-1", "passes")})
    _fact_dir(ws)
    return ws


def _c_drain_saturated_unverified(base: Path) -> Path:
    ws = _ws(base, "drain_saturated_unverified")
    _reg(ws, [])  # nobody answers q1
    _ts(ws, _pq_canonical())
    _fact_dir(ws)
    return ws


def _c_drain_verify_note_gaps(base: Path) -> Path:
    ws = _ws(base, "drain_verify_note_gaps")
    _reg(ws, [{"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    _ts(ws, _pq_canonical())
    _notes(ws, {"n1.md": ("C-1", "pending")})  # notes/ exists, no passes note
    _fact_dir(ws)
    return ws


def _c_drain_dispatch_discovery(base: Path) -> Path:
    ws = _ws(base, "drain_dispatch_discovery")
    _reg(ws, [{"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    _ts(ws, _pq_canonical())
    _notes(ws, {"n1.md": ("C-1", "passes")})
    _fact_dir(ws, files={"F001.md": "discovered shellcode, downstream payload not analyzed\n"})
    return ws


def _c_drain_blocked_contradiction(base: Path) -> Path:
    ws = _ws(base, "drain_blocked_contradiction")
    _reg(ws, [{"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    _ts(ws, _pq_canonical())
    _notes(ws, {"n1.md": ("C-1", "passes")})
    _fact_dir(ws, index=_CONTRA_INDEX,
              files={"F001.md": "sample_refs: artifact-A\n",
                     "F002.md": "sample_refs: artifact-A\n"})
    return ws


def _c_order_orphans_beats_unverified(base: Path) -> Path:
    """Both M2 gates live: orphan check wins (old chain order)."""
    ws = _ws(base, "order_orphans_beats_unverified")
    _reg(ws, [
        {"id": "C-2", "status": "PROVEN"},  # orphan
        # no claim answers q1 -> unverified
    ])
    _ts(ws, _pq_canonical())
    _fact_dir(ws)
    return ws


def _c_order_unverified_beats_note_gap(base: Path) -> Path:
    """Both gates live: unverified wins over the note-layer gap."""
    ws = _ws(base, "order_unverified_beats_note_gap")
    _reg(ws, [])
    _ts(ws, _pq_canonical())
    _notes(ws, {"n1.md": ("C-9", "passes")})  # q1 still lacks a passes note
    _fact_dir(ws)
    return ws


def _c_order_note_gap_beats_discovery(base: Path) -> Path:
    ws = _ws(base, "order_note_gap_beats_discovery")
    _reg(ws, [{"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    _ts(ws, _pq_canonical())
    _notes(ws, {"n1.md": ("C-1", "pending")})  # note gap
    _fact_dir(ws, files={"F001.md": "discovered shellcode\n"})  # discovery
    return ws


def _c_order_discovery_beats_contradiction(base: Path) -> Path:
    ws = _ws(base, "order_discovery_beats_contradiction")
    _reg(ws, [{"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    _ts(ws, _pq_canonical())
    _notes(ws, {"n1.md": ("C-1", "passes")})
    _fact_dir(ws, index=_CONTRA_INDEX,
              files={"F001.md": "sample_refs: artifact-A\nshellcode found\n",
                     "F002.md": "sample_refs: artifact-A\n"})
    return ws


def _c_sched_dispatch_open_free(base: Path) -> Path:
    ws = _ws(base, "sched_dispatch_open_free")
    _reg(ws, [_claim("C-1")])
    _ts(ws, _pq("[]"))
    return ws


def _c_sched_dispatch_two_active(base: Path) -> Path:
    """free_slots edge: 2 of 3 busy still leaves a dispatchable slot."""
    ws = _ws(base, "sched_dispatch_two_active")
    _reg(ws, [_claim("C-1")])
    _ts(ws, _pq("[]"))
    _workers(ws, 2)
    return ws


def _c_sched_verify_partials_free(base: Path) -> Path:
    ws = _ws(base, "sched_verify_partials_free")
    _reg(ws, [])
    _ts(ws, _pq("[]"))
    _fact_dir(ws, index=_PARTIAL_INDEX)
    return ws


def _c_sched_saturated_no_slots(base: Path) -> Path:
    ws = _ws(base, "sched_saturated_no_slots")
    _reg(ws, [_claim("C-1")])
    _ts(ws, _pq("[]"))
    _workers(ws, 3)
    return ws


def _c_sched_unexpected_partials_no_slots(base: Path) -> Path:
    """Reachable old-`else`: partials + zero slots (fresh workers → no stuck)."""
    ws = _ws(base, "sched_unexpected_partials_no_slots")
    _reg(ws, [])
    _ts(ws, _pq("[]"))
    _fact_dir(ws, index=_PARTIAL_INDEX)
    _workers(ws, 3)
    return ws


def _c_sched_blocked_failure_due(base: Path) -> Path:
    """#495: failed attempt with NO analysis → failure artifacts due."""
    ws = _ws(base, "sched_blocked_failure_due")
    _reg(ws, [_claim("C-1", promotion_attempts=2)])
    _ts(ws, _pq("[]"))
    return ws


def _c_sched_failure_partial_artifacts(base: Path) -> Path:
    """#495: analysis missing identified_obstacle → still BLOCKED."""
    ws = _ws(base, "sched_failure_partial_artifacts")
    _reg(ws, [_claim("C-1", promotion_attempts=1)])
    _ts(ws, _pq("[]"))
    _analysis(ws, "C-1", covers_attempt=1,
              validated_capability="frida bridge works",
              identified_obstacle="")
    return ws


def _c_sched_failure_full_analysis_dispatch(base: Path) -> Path:
    """#495: both artifacts recorded → covered → dispatchable again."""
    ws = _ws(base, "sched_failure_full_analysis_dispatch")
    _reg(ws, [_claim("C-1", promotion_attempts=1)])
    _ts(ws, _pq("[]"))
    _analysis(ws, "C-1", covers_attempt=1,
              validated_capability="frida bridge works",
              identified_obstacle="vm network blocked")
    return ws


def _c_sched_blocked_all_infra(base: Path) -> Path:
    ws = _ws(base, "sched_blocked_all_infra")
    _reg(ws, [_claim("C-1", blocked=True), _claim("C-2", blocked=True)])
    _ts(ws, _pq("[]"))
    return ws


def _c_sched_blocked_all_infra_files(base: Path) -> Path:
    ws = _ws(base, "sched_blocked_all_infra_files")
    _reg(ws, [_claim("C-1", blocked=True)])
    _ts(ws, _pq("[]"))
    _blocker_files(ws, ["B-1"])
    return ws


def _c_sched_ladder_exhausted_infra(base: Path) -> Path:
    """#497 interleave: exhausted ladder (attempts>=3, no candidates) on a
    blocked claim — LADDER_EXHAUSTED flavor, same BLOCKED verdict."""
    ws = _ws(base, "sched_ladder_exhausted_infra")
    _reg(ws, [_claim("C-1", blocked=True, promotion_attempts=3)])
    _ts(ws, _pq("[]"))
    _analysis(ws, "C-1", covers_attempt=3,
              validated_capability="static triage works",
              identified_obstacle="unpacker unavailable",
              candidates=[])
    return ws


def _c_sched_ladder_exhausted_unblocked(base: Path) -> Path:
    """#497 interleave: ladder-exhausted but NOT blocked → still dispatchable
    (decide() does not own the must-ask/climb split)."""
    ws = _ws(base, "sched_ladder_exhausted_unblocked")
    _reg(ws, [_claim("C-1", promotion_attempts=3)])
    _ts(ws, _pq("[]"))
    _analysis(ws, "C-1", covers_attempt=3,
              validated_capability="static triage works",
              identified_obstacle="unpacker unavailable",
              candidates=[])
    return ws


def _c_order_opens_beat_partials(base: Path) -> Path:
    ws = _ws(base, "order_opens_beat_partials")
    _reg(ws, [_claim("C-1")])
    _ts(ws, _pq("[]"))
    _fact_dir(ws, index=_PARTIAL_INDEX)
    return ws


def _c_order_queue_beats_failure(base: Path) -> Path:
    """Order anchor: full queue (SATURATED) wins over failure artifacts due."""
    ws = _ws(base, "order_queue_beats_failure")
    _reg(ws, [_claim("C-1"), _claim("C-2", promotion_attempts=1)])
    _ts(ws, _pq("[]"))
    _workers(ws, 3)
    return ws


def _c_order_failure_beats_all_infra(base: Path) -> Path:
    ws = _ws(base, "order_failure_beats_all_infra")
    _reg(ws, [_claim("C-1", promotion_attempts=2), _claim("C-2", blocked=True)])
    _ts(ws, _pq("[]"))
    return ws


def _c_mixed_blocked_and_unblocked_dispatch(base: Path) -> Path:
    ws = _ws(base, "mixed_blocked_and_unblocked_dispatch")
    _reg(ws, [_claim("C-1", blocked=True), _claim("C-2")])
    _ts(ws, _pq("[]"))
    return ws


CASES: dict = {
    "schema_invalid_int_item": _c_schema_invalid_int_item,
    "schema_invalid_duplicate_qid": _c_schema_invalid_duplicate_qid,
    "schema_invalid_beats_dispatch": _c_schema_invalid_beats_dispatch,
    "drain_converged_minimal": _c_drain_converged_minimal,
    "drain_converged_full": _c_drain_converged_full,
    "drain_converged_yesno_negative": _c_drain_converged_yesno_negative,
    "drain_blocked_orphans": _c_drain_blocked_orphans,
    "drain_saturated_unverified": _c_drain_saturated_unverified,
    "drain_verify_note_gaps": _c_drain_verify_note_gaps,
    "drain_dispatch_discovery": _c_drain_dispatch_discovery,
    "drain_blocked_contradiction": _c_drain_blocked_contradiction,
    "order_orphans_beats_unverified": _c_order_orphans_beats_unverified,
    "order_unverified_beats_note_gap": _c_order_unverified_beats_note_gap,
    "order_note_gap_beats_discovery": _c_order_note_gap_beats_discovery,
    "order_discovery_beats_contradiction": _c_order_discovery_beats_contradiction,
    "sched_dispatch_open_free": _c_sched_dispatch_open_free,
    "sched_dispatch_two_active": _c_sched_dispatch_two_active,
    "sched_verify_partials_free": _c_sched_verify_partials_free,
    "sched_saturated_no_slots": _c_sched_saturated_no_slots,
    "sched_unexpected_partials_no_slots": _c_sched_unexpected_partials_no_slots,
    "sched_blocked_failure_due": _c_sched_blocked_failure_due,
    "sched_failure_partial_artifacts": _c_sched_failure_partial_artifacts,
    "sched_failure_full_analysis_dispatch": _c_sched_failure_full_analysis_dispatch,
    "sched_blocked_all_infra": _c_sched_blocked_all_infra,
    "sched_blocked_all_infra_files": _c_sched_blocked_all_infra_files,
    "sched_ladder_exhausted_infra": _c_sched_ladder_exhausted_infra,
    "sched_ladder_exhausted_unblocked": _c_sched_ladder_exhausted_unblocked,
    "order_opens_beat_partials": _c_order_opens_beat_partials,
    "order_queue_beats_failure": _c_order_queue_beats_failure,
    "order_failure_beats_all_infra": _c_order_failure_beats_all_infra,
    "mixed_blocked_and_unblocked_dispatch": _c_mixed_blocked_and_unblocked_dispatch,
}


def build_case(name: str, base: Path | None = None) -> Path:
    if name not in CASES:
        raise KeyError(f"unknown anchor case {name!r}; have {sorted(CASES)}")
    base = base or Path(tempfile.mkdtemp(prefix="decide-anchor-"))
    return CASES[name](base)


# ------------------------------------------------------------- baseline IO

def _canonical(d: dict) -> str:
    return json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)


class BaselineUnavailable(RuntimeError):
    """git history lacks BASELINE_COMMIT (shallow clone / pruned)."""


def _load_baseline_module():
    """Extract the PRE-refactor convergence_check from BASELINE_COMMIT and
    import it under a unique name. Sibling imports (status_defs, yaml, ...)
    resolve on sys.path to the current tree — identical to the baseline
    tree for every module #443 does not touch (only convergence_check.py
    changes). hooks/lib_kunglao.py is copied alongside to satisfy the
    baseline module's __file__-relative loader.

    Raises BaselineUnavailable (never skips) — usable inside AND outside
    pytest (the frozen-snapshot regen path)."""
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{BASELINE_COMMIT}:scripts/convergence_check.py"],
        capture_output=True, text=True, timeout=60, errors="replace")
    if r.returncode != 0:
        raise BaselineUnavailable(
            f"baseline {BASELINE_COMMIT} unavailable: {r.stderr.strip()[:200]}")
    tmp = Path(tempfile.mkdtemp(prefix="decide-anchor-baseline-"))
    (tmp / "scripts").mkdir(parents=True)
    (tmp / "scripts" / "convergence_check.py").write_text(r.stdout, encoding="utf-8")
    (tmp / "hooks").mkdir()
    (tmp / "hooks" / "lib_kunglao.py").write_text(
        (ROOT / "hooks" / "lib_kunglao.py").read_text(encoding="utf-8"), encoding="utf-8")
    name = f"convergence_check_baseline_{BASELINE_COMMIT[:7]}"
    if name in sys.modules:  # one process, one baseline instance
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, tmp / "scripts" / "convergence_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_baseline_or_skip():
    try:
        return _load_baseline_module()
    except BaselineUnavailable as exc:
        pytest.skip(str(exc))


def capture_from_git_baseline() -> dict:
    """Regenerate the frozen anchor from the c5cb1ae baseline (design §5).

    The returned dict is what gets written to decide_anchor_c5cb1ae.json —
    it MUST be produced by the baseline module, never by the refactored
    code (maker-checker).

    Regenerate (from the worktree root):
      uv run python - <<'EOF'
      import importlib.util, json
      from pathlib import Path
      spec = importlib.util.spec_from_file_location(
          "anchor_mod", "tests/test_decide_regression_anchor.py")
      m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
      Path("tests/decide_anchor_c5cb1ae.json").write_text(
          json.dumps(m.capture_from_git_baseline(), indent=2, sort_keys=True,
                     ensure_ascii=False) + "\\n", encoding="utf-8")
      EOF
    """
    baseline = _load_baseline_module()
    base = Path(tempfile.mkdtemp(prefix="decide-anchor-capture-"))
    return {name: baseline.decide(build_case(name, base))
            for name in sorted(CASES)}


def _load_frozen() -> dict:
    if not ANCHOR_FILE.exists():
        pytest.fail(f"frozen anchor {ANCHOR_FILE} missing — regenerate it from the "
                    f"{BASELINE_COMMIT} baseline via the design §5 command "
                    "(never from the refactored code)")
    return json.loads(ANCHOR_FILE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ tests

@pytest.mark.parametrize("case", sorted(CASES))
def test_live_baseline_output_equality(case: str, tmp_path: Path) -> None:
    """Channel 1: baseline decide() (c5cb1ae) == current decide(), per case,
    full output dict. The hard #443 acceptance."""
    baseline = _load_baseline_or_skip()
    ws = build_case(case, tmp_path)
    old = baseline.decide(ws)
    new = convergence_check.decide(ws)  # same workspace: decide() is read-only
    assert _canonical(new) == _canonical(old), (
        f"case {case}: decide() output drifted from {BASELINE_COMMIT} baseline\n"
        f"--- baseline ---\n{_canonical(old)}\n--- current ---\n{_canonical(new)}")


@pytest.mark.parametrize("case", sorted(CASES))
def test_frozen_snapshot_output_equality(case: str, tmp_path: Path) -> None:
    """Channel 2: current decide() == frozen c5cb1ae snapshot (permanent,
    survives history pruning)."""
    frozen = _load_frozen()
    if case not in frozen:
        pytest.fail(f"frozen anchor lacks case {case!r}; regenerate per design §5")
    ws = build_case(case, tmp_path)
    new = convergence_check.decide(ws)
    assert _canonical(new) == _canonical(frozen[case]), (
        f"case {case}: decide() output drifted from frozen anchor\n"
        f"--- frozen ---\n{_canonical(frozen[case])}\n--- current ---\n{_canonical(new)}")


def test_anchor_matrix_covers_every_decision() -> None:
    """Meta: the matrix must exercise all six decisions and all distinct
    action families (incl. the reachable 'Unexpected state' fallback)."""
    frozen = _load_frozen()
    decisions = {frozen[c]["decision"] for c in frozen}
    assert decisions == {"INVALID", "CONVERGED", "DISPATCH", "DISPATCH_VERIFIER",
                         "SATURATED", "BLOCKED"}, decisions
    actions = "\n".join(frozen[c]["action"] for c in frozen)
    for needle in ("Unexpected state", "failure_analysis_gate", "orphan",
                   "priority_ratio.py", "partial fact(s)", "slots busy",
                   "STOP dispatch; deliver", "primary_questions"):
        assert needle in actions, f"action family {needle!r} not covered by matrix"
    assert set(frozen) == set(CASES), "frozen anchor and CASES matrix diverged"
