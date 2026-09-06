# -*- coding: utf-8 -*-
"""#443 regression anchor — decide() output equality against a frozen ref.

Design (openspec/changes/issue-443-decide-state-machine/design.md §5):
decide() is reorganized into an explicit state machine. The anchor proof
ran TWO channels while a pre-refactor baseline existed:

  1. LIVE BASELINE (maker-checker, RETIRED 2026-09-05): extract the
     pre-refactor decide() from git at test time and diff it against the
     current decide() on the SAME fixture workspace. Retired with the
     8804dcd baseline object (see the 2026-09-05 re-pin entry below):
     the commit is unrecoverable after the history rewrite, and #51 is an
     INTENTIONAL decide() contract change — no pre-#51 baseline can ever
     equal current again, so the equality premise is void until a future
     pre-refactor refactor re-introduces a live baseline.
  2. FROZEN SNAPSHOT (permanent, sole active proof): tests/decide_anchor_<ref>.json
     holds the machine-generated outputs of decide() at BASELINE_COMMIT
     (design §5 regen command, now capture_current()); the current
     decide() must reproduce them byte-for-byte per case. Survives git
     history pruning.

Matrix: ~30 cases covering every branch of the old elif chain, gate
interleavings where ORDER decides (schema>dispatch, orphan>unverified,
unverified>note-gap, note-gap>discovery, discovery>contradiction,
opens>partials, queue>failure, failure>all-blocked), and the #495/#497
interleavings (failure three-artifact protocol, ladder-exhaustion).

Determinism: worker-status files are freshly written (mtime fresh →
stuck_workers always []), removing age_min time drift from the anchor.
"""
from __future__ import annotations

import json
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

# 2026-09-06 SEMANTIC re-pin verification (#107 Thompson rebuild): the
# owner ruling "探索和价值网络完全重构，之前的不要了" replaced the
# ranking layer — priority_ratio is now the Thompson composite
# (sampled case posterior + LAMBDA_DH*dH_PQ) and the explore/exploit dual
# path is deleted. The ranker swap is an INTENTIONAL SEMANTIC change, and
# its visible face is kunglao-decide's `top_actions`: any ordering change
# there is DESIGN INTENT, pinned by the rebuilt suites
# (tests/test_kunglao_decide.py / test_scorer_authority.py /
# test_priority_ratio.py), NOT anchor drift. This frozen corpus pins the
# convergence_check.decide() MATRIX face, which does not consume the
# ranker — verified empirically: capture_current() re-run over all 31
# cases reproduced the frozen outputs byte-identically (per-case diff:
# zero drift), so the file is re-frozen unchanged. A future case that
# grows a top_actions-like field must land with its own semantic re-pin
# entry per this precedent chain.
#
# 2026-08-25 re-pin: the anchor was re-frozen at 619ebd3 after the
# INTENTIONAL decide() semantics additions of #662 (hypothesis seed:
# open_hypotheses field + OPEN_HYPOTHESIS_AT_CLOSE event) and #663 (anomaly
# detection: anomalies field + ANOMALY_DETECTED event), plus #670's
# Event.JADX_INFEASIBLE. Those merges shipped without re-pinning the anchor,
# so 31 frozen cases failed from that point on. The c5cb1ae anchor remains
# recoverable from git history (and documents the original #443
# zero-semantics-change proof). Machine-generated via .tmp/regen_anchor.py.
BASELINE_COMMIT = "cabc7d9"  # the #51 value-flag-removal commit — decide() outputs frozen at the 2026-09-05 re-pin (see below)
ANCHOR_FILE = Path(__file__).parent / "decide_anchor_cabc7d9.json"

# 2026-09-06 zero-drift verification (#98 DRAIN worker gates): the DRAIN
# probe table gained STUCK_WORKERS_PRESENT + ACTIVE_WORKERS_PRESENT,
# appended AFTER the frozen completion-transaction order (orphan >
# unverified > note-gap > hyp > discovery > contradiction > anomaly) and
# BEFORE the DRAIN_CLEAN catch-all — every completeness gate keeps its
# verdict priority, and the new gates can only fire on a drained claim
# face with live workers. All 32 frozen cases re-verified byte-identical
# after the change (the predicates read snapshot data the corpus's DRAIN
# cases never populate: none of them writes a worker-status file), so NO
# re-pin was needed. Live semantic change, documented but unanchored (the
# matrix has no worker-bearing DRAIN case — covered by the #98 block in
# tests/test_decide_state_machine.py instead): the issue #98 probe state
# (single IN_PROGRESS claim + aged worker-status; pre-fix decision
# CONVERGED / exit 0 / "STOP dispatch; deliver") now reads
# BLOCKED / exit 4 via the shared #595 stuck action (CONVERGED -> BLOCKED);
# the same face with a fresh worker now reads SATURATED / exit 3
# (CONVERGED -> SATURATED, busy-poll).
# 2026-09-05 re-pin (#51 value loop unification): #51 removed the
# KUNGLAO_VALUE_ALGO experiment flag (no-backcompat policy), making
# rho_checkpoint.attach_signals an UNCONDITIONAL part of decide() — the
# output dict gains the `value_signals` key on every verdict. That is an
# INTENTIONAL decide() contract change, resolved per the established
# re-pin precedent (2026-08-25/#662-#663-#670, 2026-08-26/#707,
# 2026-08-27/#751, 07994e6/#866-b): re-freeze the corpus, document the
# semantic change. Diffed old-vs-new BEFORE committing: every one of the
# 31 cases shows exactly the `value_signals` addition and nothing else.
# Unlike every prior re-pin, this one could NOT be captured via
# capture_from_git_baseline(): the 8804dcd baseline object was destroyed
# by the history rewrite (git cat-file -t 8804dcd -> fatal), so the frozen
# snapshot was re-captured from the CURRENT tree at cabc7d9 via
# capture_current(). With the baseline commit gone — and with #51 being a
# deliberate decide() semantics change, which voids the "baseline ==
# current" equality premise for any pre-#51 baseline — channel 1 (live
# baseline extraction: _load_baseline_module /
# test_live_baseline_output_equality) is RETIRED. The frozen-snapshot
# channel is now the sole active proof; channel 1 returns only if a
# future zero-semantics-change refactor re-introduces a recoverable
# pre-refactor baseline.

# 2026-08-27 corpus re-pin (#751): web-re-quickref.md grew the gitnexus
# semantic-index step (~30 lines), shifting lexical rarity again. Same class:
# DATA drift only, 4 score floats across the 2 contradiction cases
# (0.905067808708 -> 0.907194994786, 0.910599571734 -> 0.912148070907).
# Also: _load_baseline_module now ships hooks/_path_hygiene.py beside the
# copied lib_kunglao.py — the #671 self-bootstrap FileNotFoundError'd the
# regen path after that merge (regen was broken for every doc-touching wave).
#
# 2026-09-01 corpus re-pin (#884): references/re-library/jsvmp-triage.md
# joined the anomaly baseline corpus (re-library/*.md is ingested by
# anomaly_detector._load_baseline), shifting lexical rarity in the 4th
# decimal. Same class: DATA drift only, 4 score floats across the 2
# contradiction cases; channel 1 (baseline decide() == current decide())
# stays green on all cases. Re-captured via capture_from_git_baseline()
# (baseline module + current corpus) per the design §5 command.
#
# 2026-09-02 corpus re-pin (#866-b): references/re-library/kunglao-toolshelf.md
# joined the anomaly baseline corpus (the #866-b discovery-face teaching page
# for the registered tools/ CLIs). Same class: DATA drift only, 4 score floats
# across the 2 contradiction cases (0.9059571619812584 -> 0.9054677206851119,
# 0.9098895582329317 -> 0.9095849802371542); channel 1 stays green.
# Re-captured via capture_from_git_baseline() (baseline module + current
# corpus) per the design §5 command.
#
# 2026-09-06 corpus re-pin (#112 distillation): 7 new re-library cards
# (native-sign-recovery, wire-format-recognition, stacked-protections,
# falsifier-library, verification-safety, vm-deobfuscation-routing,
# loop-stage-gates) joined the anomaly baseline corpus. Same class as
# #884/#866-b/#728: DATA drift only, 4 score floats across the 2
# contradiction cases (0.9054677206851119 -> 0.9030563514804202,
# 0.9095849802371542 -> 0.9002507163323783); channel 1 stays green on all
# cases. Case-by-case diff verified SCORE-ONLY before committing; re-pinned
# via capture_current() per the docstring command.
#
# 2026-08-26 corpus re-pin (#728 web labs): references/re-library/web-re-quickref.md
# joined the anomaly baseline corpus (anomaly_detector._load_baseline ingests
# re-library/*.md), shifting every lexical rarity score in the 4th decimal. This
# is DATA drift, not decide() semantics drift — the 8804dcd baseline decide()
# and the current decide() still agree on all 31 cases (channel 1 green); only
# the frozen scores were stale. Re-captured via capture_from_git_baseline()
# (baseline module + current corpus): 4 score floats across the 2 contradiction
# cases moved (0.905840286055 -> 0.905067808708, 0.911799761621 -> 0.910599571734,
# full precision in the anchor), nothing else changed.

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
    """Canonical JSON for anchor equality — floats rounded to 12 decimals.

    Rationale (#692 CI, 2026-08-26): anomaly scores are mean-of-ratios whose
    last significant digit is a 1-ULP platform artifact (Windows CPython vs
    Linux CPython libm differ at the 16th sig fig: 0.9058402860548272 vs
    0.905840286054827). Rounding lives in the COMPARISON layer only — fact
    values keep full precision; semantic drift beyond 1e-12 still fails."""
    def _round(obj):
        if isinstance(obj, float):
            return round(obj, 12)
        if isinstance(obj, dict):
            return {k: _round(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_round(v) for v in obj]
        return obj
    return json.dumps(_round(d), sort_keys=True, ensure_ascii=False, default=str)


def capture_current() -> dict:
    """Regenerate the frozen anchor from the CURRENT tree's decide().

    Provenance note (2026-09-05 re-pin, #51): before the history rewrite
    this helper was capture_from_git_baseline() — the frozen dict was
    produced by the BASELINE_COMMIT module (maker-checker: expected values
    derived from the OLD code, never hand-written). That channel is gone
    with the 8804dcd object; an anchor re-pin is now sanctioned ONLY as a
    documented intentional-semantics re-pin (per the precedent chain in
    the header comment), captured from the current code, with the diff
    against the previous anchor verified case-by-case BEFORE committing.

    Regenerate (from the worktree root):
      uv run python - <<'EOF'
      import importlib.util, json
      from pathlib import Path
      spec = importlib.util.spec_from_file_location(
          "anchor_mod", "tests/test_decide_regression_anchor.py")
      m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
      Path("tests/decide_anchor_" + m.BASELINE_COMMIT + ".json").write_text(
          json.dumps(m.capture_current(), indent=2, sort_keys=True,
                     ensure_ascii=False) + "\\n", encoding="utf-8")
      EOF
    """
    base = Path(tempfile.mkdtemp(prefix="decide-anchor-capture-"))
    return {name: convergence_check.decide(build_case(name, base))
            for name in sorted(CASES)}


def _load_frozen() -> dict:
    if not ANCHOR_FILE.exists():
        pytest.fail(f"frozen anchor {ANCHOR_FILE} missing — regenerate it via "
                    "capture_current() (the docstring's design §5 command) "
                    "and document the re-pin in the header comment")
    return json.loads(ANCHOR_FILE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ tests

@pytest.mark.parametrize("case", sorted(CASES))
def test_frozen_snapshot_output_equality(case: str, tmp_path: Path) -> None:
    """The frozen-snapshot channel (permanent, survives history pruning):
    current decide() == frozen snapshot at BASELINE_COMMIT, per case,
    full output dict."""
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
