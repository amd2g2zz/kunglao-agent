# -*- coding: utf-8 -*-
"""rlvr/settlement_scorer.py — the BLIND settlement entry (issue-687).

Credit is the reward: whoever shapes the settlement input shapes the
credit, so settlement over the producer's own output is a
reward-hacking surface. This module is the settlement subagent's only
door in — three mechanical properties:

SHIPPING STATUS: the barrier family is complete and its dispatch
surface exists (the settler agent + the read-barrier markers), but no
production writer builds a ``settler_input`` doc yet — the direct
``settle_step`` path (step grain at the SubagentStop boundary) is what
runs today. The open writer gap is the module's own recorded design
decision; until a writer lands, this door is armed and unbolted, not
walked through.

1. THE BLIND INPUT CONTRACT. ``settler_input`` builds from a WHITELIST
   (raw step artifacts as path + sha256, the claim/question, the rules
   table as path + sha256). Producer narrative (notes/, worker-status,
   verification/verify-note records, fact conclusions, the verdict
   conclusion) and the policy learning faces
   (runs/method-family-log.jsonl, runs/q-cell-log.jsonl, and since #721
   the consolidated runs/experience.jsonl carrying the q-cell arm
   values) are excluded BY CONSTRUCTION: a refused path raises BEFORE
   any read; a legal build opens exactly the listed artifacts (never
   scans the workspace). Case-folded comparisons — the dev filesystem
   is case-insensitive.

2. IDENTITY. Every input doc carries a non-empty settler identity (the
   dual_gate verifier-identity discipline: no named grader, no settle).
   ``check_blind_input`` re-enforces schema/identity/claim and the
   normalized excluded-face scan (artifacts AND rules) at the
   SETTLEMENT — a hand-built doc cannot smuggle what the builder refuses.

3. THE VALIDATOR STACK IS REUSED, NOT REIMPLEMENTED. ``settle_blind``
   routes through scalar.validate_verdict_doc (citation wall -> rail
   clamp -> oracle lock + anti-surrender floor) and
   scalar.apply_trajectory_settlement (fail-closed write; the ledger's
   core-minus-ts dedupe keeps an identical re-application
   byte-identical). Zero-judgment module: no sampling slot, no model
   call, no narrative field in the input doc.

The grader pays: ``record_settler_cost`` closes the settler act's own
transition (action_type ``settle``) so r_incr = ALPHA*dPhi -
LAMBDA*cost_t books its tokens/seconds like any producer act's; the
launch stash is the billing guard (no stash -> no row; first close
consumes it — a re-run cannot double-bill).
"""
from __future__ import annotations

import posixpath
from pathlib import Path

from _common import sha256_file
from rlvr import incremental_reward as ir
from rlvr import scalar

#: the input-doc schema stamp — settle_blind refuses any other shape
SETTLEMENT_INPUT_SCHEMA = "blind-settlement-input/1"

#: the settle act's action_type: its launch stash namespace (and the
#: cost row's identity) stays scoped away from dispatch/verify stashes
SETTLE_ACTION_TYPE = "settle"

#: excluded faces — mirrored from hooks/rt_read_barrier.py's deny list
#: (ACT-side there, doc-side here; cross-pin: test_blind_settlement_687)
EXCLUDED_DIRS = ("facts/", "notes/")
EXCLUDED_PREFIXES = ("runs/worker-status-", "runs/verification-")
EXCLUDED_SUFFIXES = ("-verify-note.md",)
EXCLUDED_FILES = {
    "runs/method-family-log.jsonl": "the method-family learning face",
    "runs/q-cell-log.jsonl": "the q-cell learning face (arm values)",
    # #721: the q-cell arm values now ride the consolidated learning
    # feed — the whole file joins the wall (its transition rows are
    # reward-bearing policy feedback too)
    "runs/experience.jsonl": "the consolidated learning feed (#721)",
    "evidence/verdict.json": "the verdict conclusion",
}
#: basename view — the rules table may live outside the ws
EXCLUDED_FILE_BASES = {k.rsplit("/", 1)[-1]: v
                       for k, v in EXCLUDED_FILES.items()}


def _norm_rel(path) -> str:
    s = str(path or "").replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.strip("/")


def _gate_rel(path) -> str | None:
    """Lexically normalized, relative form of a path for the exclusion
    scan (no filesystem access). None when empty, absolute, or escaping
    upward — the gate refuses those outright."""
    s = str(path or "").replace("\\", "/").strip()
    if not s or s.startswith("/"):
        return None
    norm = posixpath.normpath(s)
    if norm.startswith(".."):
        return None
    return norm.strip("/")


def excluded_face(rel) -> str | None:
    """The exclusion reason for a workspace-relative path, else None.

    Case-FOLDED (the dev filesystem is case-insensitive — a case alias
    must land on the same refusal). The single source for BOTH refusal
    points (builder and settlement gate)."""
    rel = _norm_rel(rel)
    if not rel:
        return None
    low = rel.lower()
    if low == "facts" or low.startswith("facts/"):
        return f"{rel} (maker conclusions)"
    if low == "notes" or low.startswith("notes/"):
        return f"{rel} (producer narrative)"
    for prefix in EXCLUDED_PREFIXES:
        if low.startswith(prefix):
            return f"{rel} (worker/verifier narrative)"
    for suffix in EXCLUDED_SUFFIXES:
        if low.endswith(suffix):
            return f"{rel} (worker verify note)"
    if low in EXCLUDED_FILES:
        return f"{rel} ({EXCLUDED_FILES[low]})"
    return None


def _ws_rel(target, ws: Path) -> str:
    """Workspace-relative posix path; refuses targets outside the ws."""
    t = Path(str(target))
    base = t if t.is_absolute() else (ws / t)
    try:
        return base.resolve().relative_to(ws.resolve()).as_posix()
    except (ValueError, OSError) as exc:
        raise ValueError(
            f"blind settlement input: {target} is outside the workspace"
        ) from exc


def _excluded_in_path(norm) -> str | None:
    """Exclusion scan for paths allowed OUTSIDE the workspace (the rules
    table may be repo-side): no excluded FACE segment anywhere, and the
    basename may not be a denied file (case-folded)."""
    low = str(norm or "").replace("\\", "/").lower()
    if not low:
        return None
    for part in low.split("/"):
        if part in ("notes", "facts"):
            return f"{norm} (contains a {part}/ face segment)"
    base = low.rsplit("/", 1)[-1]
    if base in EXCLUDED_FILE_BASES:
        return f"{norm} ({EXCLUDED_FILE_BASES[base]})"
    if base.startswith(("worker-status-", "verification-")):
        return f"{norm} (worker/verifier narrative)"
    if base.endswith("-verify-note.md"):
        return f"{norm} (worker verify note)"
    return None


def settler_input(ws, *, claim, artifact_paths, identity,
                  question="", rules_path=None) -> dict:
    """Build the BLIND settler input (path + sha256 artifacts only).

    Raises ValueError at the boundary — empty identity, empty claim, an
    excluded face (case-folded, resolved), an artifact outside the ws or
    missing on disk, an unreadable rules table. The builder never scans
    the workspace: it opens exactly the listed artifact paths (after the
    exclusion check). Deterministic: same arguments -> same bytes."""
    ident = str(identity or "").strip()
    if not ident:
        raise ValueError("blind settlement input: settler identity "
                         "required (verifier-identity)")
    if not str(claim or "").strip():
        raise ValueError("blind settlement input: claim required")
    ws = Path(ws)
    artifacts = []
    for raw in artifact_paths or ():
        rel = _ws_rel(raw, ws)
        face = excluded_face(rel)
        if face:
            raise ValueError(
                f"blind settlement input: {rel} is excluded ({face})")
        p = ws / rel
        if not p.is_file():
            raise ValueError(
                f"blind settlement input: artifact missing: {rel}")
        artifacts.append({"path": rel, "sha256": sha256_file(p)})
    rules = None
    if rules_path:
        # repo-side policy path: face-scan the normalized path (never
        # the workspace bounding — a notes/-shaped rules path refuses)
        norm = _norm_rel(posixpath.normpath(
            str(rules_path).replace("\\", "/")))
        face = _excluded_in_path(norm)
        if face:
            raise ValueError(
                f"blind settlement input: rules table excluded ({face})")
        rp = Path(rules_path)
        if not rp.is_file():
            raise ValueError(
                f"blind settlement input: rules table missing: "
                f"{rules_path}")
        rules = {"path": norm, "sha256": sha256_file(rp)}
    return {
        "schema": SETTLEMENT_INPUT_SCHEMA,
        "identity": ident,
        "claim": str(claim),
        "question": str(question or ""),
        "artifacts": artifacts,
        "rules": rules,
    }


def check_blind_input(input_doc) -> dict:
    """The settlement-side blind re-check: schema, identity, claim, and
    no excluded face among the artifacts — PATH checks, not string
    checks: artifact paths are lexically normalized (dot segments
    collapse; absolute/upward-escaping paths refuse) and case-folded
    before the scan, exactly like the builder's resolution; the rules
    path rides the same face scan. Returns ``{"ok", "reason"}`` — the
    gate never raises; ok=False means nothing settles."""
    if not isinstance(input_doc, dict):
        return {"ok": False, "reason": "input: not a mapping"}
    if input_doc.get("schema") != SETTLEMENT_INPUT_SCHEMA:
        return {"ok": False,
                "reason": f"input: schema must be "
                          f"{SETTLEMENT_INPUT_SCHEMA}"}
    if not str(input_doc.get("identity") or "").strip():
        return {"ok": False, "reason": "input: settler identity required"}
    if not str(input_doc.get("claim") or "").strip():
        return {"ok": False, "reason": "input: claim required"}
    arts = input_doc.get("artifacts")
    if not isinstance(arts, list):
        return {"ok": False, "reason": "input: artifacts must be a list"}
    for a in arts:
        raw = (str((a or {}).get("path") or "")
               if isinstance(a, dict) else str(a or ""))
        norm = _gate_rel(raw)
        if norm is None:
            return {"ok": False,
                    "reason": f"input: {raw} is absolute or escapes "
                              f"the workspace"}
        face = excluded_face(norm)
        if face:
            return {"ok": False,
                    "reason": f"input: {raw} is excluded ({face})"}
    rules = input_doc.get("rules")
    if isinstance(rules, dict) and rules.get("path"):
        norm = _norm_rel(posixpath.normpath(
            str(rules.get("path")).replace("\\", "/")))
        face = _excluded_in_path(norm)
        if face:
            return {"ok": False,
                    "reason": f"input: rules table excluded ({face})"}
    return {"ok": True, "reason": None}


def record_settler_cost(ws, claim, *, tokens=0.0, seconds=0.0,
                        outcome="SUCCESS", attempt_id="") -> dict | None:
    """Book the settler act's own run cost into the transition ledger —
    cost_t (tokens/COST_TOKENS_DIV + seconds/COST_SECONDS_DIV) lands in
    this row's r_incr, so the grader is priced like any producer act.
    Scoped action_type keeps the settle stash apart from dispatch/verify
    stashes; no stash -> no row (fail-loud), first close consumes the
    stash — a re-run cannot double-bill. None when nothing was booked."""
    return ir.append_transition(
        str(ws), str(claim), str(outcome), tokens=float(tokens),
        seconds=float(seconds), action_type=SETTLE_ACTION_TYPE,
        attempt_id=str(attempt_id or ""))


def settle_blind(ws, rollout_id, verdict_doc, *, input_doc,
                 oracle_verdict, has_reproducible_evidence,
                 claim="", cost_tokens=0.0, cost_seconds=0.0,
                 attempt_id="", now=None) -> dict:
    """Settle one trajectory through the blind entry.

    Order: the blind gate first (a bad input doc settles NOTHING — an
    ``input: ...`` reason), then the reused validator stack (fail-closed:
    an invalid verdict writes nothing). Cost books after the gate
    whenever claim+cost are supplied — the run happened even when the
    verdict failed validation (cost is telemetry truth, credit is not);
    the row's outcome names the result (SUCCESS iff the ledger row
    landed, SETTLE-DENIED otherwise) and ``attempt_id`` keeps the
    stale-attempt guard usable. Cost without a claim, and a missing
    workspace, refuse loudly. Never raises on contract violations."""
    if ws is None:
        return {"settled": False, "reason": "input: workspace required"}
    gate = check_blind_input(input_doc)
    if not gate["ok"]:
        return {"settled": False, "reason": gate["reason"]}
    if (cost_tokens or cost_seconds) and not str(claim or "").strip():
        return {"settled": False,
                "reason": "input: settler cost requires the claim it "
                          "settles (a silent drop would hide spend)"}
    res = scalar.apply_trajectory_settlement(
        Path(ws), rollout_id, verdict_doc, oracle_verdict=oracle_verdict,
        has_reproducible_evidence=has_reproducible_evidence,
        extra_resolvable=[str(a.get("path") or "")
                          for a in (input_doc.get("artifacts") or [])
                          if isinstance(a, dict)],
        now=now)
    if str(claim or "").strip() and (cost_tokens or cost_seconds):
        res["settler_cost"] = record_settler_cost(
            ws, claim, tokens=cost_tokens, seconds=cost_seconds,
            outcome="SUCCESS" if res.get("settled") else "SETTLE-DENIED",
            attempt_id=attempt_id)
    return res


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
