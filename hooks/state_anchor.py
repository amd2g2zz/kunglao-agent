#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""state_anchor.py - per-turn mechanical state re-anchor (v1.9.#44, L1 PREVENT).

WHY: v1.9's convergence loop is reliable only as long as the orchestrator
REMEMBERS the current mechanical state every turn. When it forgets (absorbed
in a worker report, compacted, context-limited) there is no backstop — the
loop drifts and "kunglao-agent got dumb" (user's words, 原文 Chinese: kunglao-agent 笨了) returns as a mystery. worker_pulse (#38)
fires only on dispatch-prefix Agent calls; external_kicker (#39/#43) recovers
DEAD or alive-but-stuck sessions. Between them lies context rot (research F5:
the deterministic Executive must own belief — know / change / commit / forget
/ recover; F1: 72.5% process-level). This hook is the missing per-turn
"forget/refresh" layer: on every Agent-tool completion it injects a compact
state signature built from the SAME fired predicates #45's resume prompt
reads (ledger last snapshot + claim register + facts index + active workers),
so the live session never drifts. When drift_detected (#43 — signature
rotation frozen, no worker progressing) it prepends a prominent
`⚠ STATE FLAT` warning that triggers a re-read of the claim register — the
cure-first nudge that should preempt #43's escalation-to-kick.

SMART = narrow + alive-only (same philosophy as worker_pulse / dispatch_gate):
  - fires ONLY when tool_name == "agent" (case-insensitive; the harness
    lowercases tool names). Every other tool -> silent.
  - fires ONLY while kunglao-agent is ACTIVATED (30-min TTL, strict). No
    activation / expired -> hooks sleep.
  - INJECTS context (additionalContext), never aborts. FAIL_OPEN at every
    layer — any exception -> empty output, exit 0. A state_anchor failure
    must never block a worker completion.

Drift semantics are sourced SINGLE-FILE from scripts/lib_kunglao.py (loaded
by importlib under lib_kunglao_scripts — the exact external_kicker.should_kick
precedent), NOT re-derived and NOT a hooks mirror: the drift signal is
semantically coupled between this cure layer (warn at ROTATION_WINDOW) and
the recovery layer (external_kicker kicks at DRIFT_ESCALATE_ROWS); a single
source guarantees the cure-first window contract cannot fork. See
openspec/archive/state-anchor-hook/design.md (D3 / R1).

Output shape (mirrors worker_pulse emission):
  {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                          "additionalContext": "<anchor text>"}}

Wiring (in .claude/settings.json PostToolUse, Agent matcher — alongside
worker_pulse / worker_budget):
  {"matcher": "Agent", "hooks": [{"type": "command",
    "command": "uv run --project <skill_root> <skill_root>/hooks/state_anchor.py"}]}
Registered idempotently by scripts/hook_activation.py --wire-up (registry:
wire_up_settings.WIRE_UP_HOOK_FILES, #445) + listed in
scripts/hook_activation.py::ALL_HOOKS.

Pure read: reads ledger / claim-register / facts/_INDEX / worker-status +
runs the lib_kunglao drift helpers in-process. No state writes, no files
touched.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
SCRIPTS_DIR = SKILL_DIR / "scripts"
ANCHOR_CAP = 500  # issue requirement: <=500 chars

# Import status_defs constants from scripts/ (single source of truth, #34, #95).
# sys.path must include scripts/ before the import; same pattern as other hooks
# (dispatch_gate, worker_budget, worker_pulse).
sys.path.insert(0, str(SCRIPTS_DIR))
from status_defs import PARTIAL_STATUSES  # noqa: E402

_LEDGER_FILE = ".convergence_ledger.jsonl"
_CLAIM_ID_RE = re.compile(r"^-\s+id:\s*(\S+)")
_CLAIM_STATUS_RE = re.compile(r"^\s+status:\s*(\S+)")

# #528: open hypotheses ride the anchor as a STRUCTURED id list (never
# narrative — the anti-narrative contract at test_anchor_excludes_
# progress_narrative). Bounded like every other anchor segment.
HYP_SEGMENT_CAP = 10


# ---------- drift lib: single-source load of scripts/lib_kunglao.py ----------

def _load_drift_lib():
    """Load scripts/lib_kunglao.py under the unique name lib_kunglao_scripts
    (the exact external_kicker.should_kick / tests/test_drift_detection
    precedent). Cached in sys.modules so prod and pytest share one instance.
    FAIL_OPEN -> None on any failure (the anchor summary does not depend on
    the drift warning)."""
    import importlib.util
    name = "lib_kunglao_scripts"
    lib = sys.modules.get(name)
    if lib is not None:
        return lib
    try:
        path = SKILL_DIR / "scripts" / "lib_kunglao.py"
        spec = importlib.util.spec_from_file_location(name, path)
        lib = importlib.util.module_from_spec(spec)
        sys.modules[name] = lib
        spec.loader.exec_module(lib)
        return lib
    except Exception:  # noqa: BLE001 — FAIL_OPEN: drift warning is optional
        return None


# ---------- workspace + activation (mirror worker_pulse) ----------

def _resolve_workspace(payload: dict) -> Path | None:
    """First candidate with a convergence ledger wins. state_anchor's primary
    input is the ledger (build_anchor returns "" without one), so the ledger
    is the correct marker — not claim-register.yaml (worker_pulse's marker,
    which fits worker_pulse because it shells out to convergence_check). The
    real workspace carries the ledger at its root."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / _LEDGER_FILE).exists():
            return base
    return None


def _kunglao_active(ws: Path) -> bool:
    """Strict activation (default-inactive): state_anchor fires only if
    explicitly activated AND not expired. Mirrors worker_pulse / dispatch_gate."""
    if not (ws / ".hook_state.json").exists():
        return False
    try:
        sys.path.insert(0, str(SKILL_DIR / "scripts"))
        import hook_activation as ha
        return ha.is_active_strict(ws, "state_anchor")
    except Exception:  # noqa: BLE001 — never block on an activation-check error
        return False


# ---------- mechanical-state readers (fired predicates; never raise) ----------

def _last_snapshot(ws: Path) -> tuple[dict | None, int]:
    """Return (last SNAPSHOT row, snapshot_count) from the convergence ledger.
    OUTCOME rows (type == "outcome"; status_defs LedgerLineType contract) are
    events, never snapshots — skipped. Lines without `type` default to SNAPSHOT.
    Missing/corrupt ledger -> (None, 0). Never raises."""
    p = ws / _LEDGER_FILE
    if not p.exists():
        return None, 0
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None, 0
    last, count = None, 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(row, dict) or row.get("type") == "outcome":
            continue
        count += 1
        last = row
    return last, count


def _register_open_ids(ws: Path) -> list:
    """OPEN / PARTIALLY-VERIFIED claim ids from claim-register.yaml (line scan,
    no yaml dep). Mirrors external_kicker._register_open_ids. Never raises."""
    p = ws / "claim-register.yaml"
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out, cur_id, cur_status = [], None, None
    for line in lines:
        m = _CLAIM_ID_RE.match(line)
        if m:
            if cur_id is not None and (cur_status == "OPEN" or cur_status in PARTIAL_STATUSES):
                out.append(cur_id)
            cur_id, cur_status = m.group(1), None
            continue
        s = _CLAIM_STATUS_RE.match(line)
        if s and cur_id is not None:
            cur_status = s.group(1).upper()
    if cur_id is not None and (cur_status == "OPEN" or cur_status in PARTIAL_STATUSES):
        out.append(cur_id)
    return out


def _open_ids(ws: Path, snap_row: dict | None) -> list:
    """Fired predicates: ledger snapshot open_ids (most-recent mechanical
    truth) first, then claim-register OPEN/PARTIALLY ids not already listed.
    Dedup, order-preserving. Never raises."""
    ids, seen = [], set()
    for i in (snap_row or {}).get("open_ids") or []:
        s = str(i)
        if s not in seen:
            ids.append(s)
            seen.add(s)
    try:
        for i in _register_open_ids(ws):
            if i not in seen:
                ids.append(i)
                seen.add(i)
    except Exception:  # noqa: BLE001 — register read is best-effort
        pass
    return ids


def _count_facts(ws: Path) -> int:
    fdir = ws / "facts"
    if not fdir.exists():
        return 0
    try:
        return sum(1 for p in fdir.glob("F*.md")
                   if p.is_file() and p.name.upper().startswith("F"))
    except OSError:
        return 0


def _open_hypothesis_pointers(ws: Path) -> list[dict[str, str]]:
    """Structured open-hypothesis pointers [{"claim_id", "hyp_id"}] from
    <ws>/hypotheses/ (#528). Reads ONLY the hypothesis layer — never
    notes/ (the result layer). FAIL_OPEN: any failure -> [] (a broken
    hypotheses layer must never break the anchor)."""
    hyp_dir = ws / "hypotheses"
    if not hyp_dir.is_dir():
        return []
    try:
        from hypothesis_store import HypothesisStore
        return [{"claim_id": h.claim_id, "hyp_id": h.id}
                for h in HypothesisStore(hyp_dir).list_open()]
    except Exception:  # noqa: BLE001 — FAIL_OPEN: pointers are optional
        return []


# ---------- anchor composition (<= ANCHOR_CAP chars; truncate from tail) ----------

def _compose(drift_prefix: str, round_n: int, decision: str, open_count: int,
             partial_count, active_workers, blockers, facts_total,
             open_ids: list, hyp_pointers: list[dict[str, str]] | None = None
             ) -> str:
    """Assemble the anchor text, truncating the open_ids list from the tail
    until the whole (drift_prefix + summary) fits ANCHOR_CAP chars.

    #528: open hypotheses ride as a STRUCTURED id segment
    (`| hyps=N: H-1(C-1) …`) — ids only, never narrative — inside the
    SAME 500-char budget. The hypothesis segment never displaces the
    claim-id list: it is appended after it and drops first when tight."""
    header = (f"[state_anchor] round={round_n} decision={decision} "
              f"open_count={open_count} partial={partial_count} "
              f"workers={active_workers} blk={len(blockers or [])} "
              f"facts={facts_total} | open_ids: ")
    hyp_seg = ""
    hyps = hyp_pointers or []
    if hyps:
        shown = hyps[:HYP_SEGMENT_CAP]
        pairs = ", ".join(f"{p['hyp_id']}({p['claim_id']})" for p in shown)
        more = len(hyps) - len(shown)
        hyp_seg = f" | hyps={len(hyps)}: {pairs}" + (f", +{more}" if more > 0 else "")
    budget = ANCHOR_CAP - len(drift_prefix) - len(header) - len(hyp_seg)
    # Fit as many ids as the budget allows; reserve room for a trailing ", …".
    shown, running, truncated = [], 0, False
    ELLIPSIS = ", ..."
    for cid in open_ids:
        piece = (", " if shown else "") + str(cid)
        need = len(piece) + (len(ELLIPSIS) if shown else 0)
        if running + need > budget and shown:
            truncated = True
            break
        shown.append(str(cid))
        running += len(piece)
    if not shown:
        ids_text = "(none)" if not open_ids else "..."
    else:
        ids_text = ", ".join(shown) + (ELLIPSIS if truncated else "")
    full = drift_prefix + header + ids_text + hyp_seg
    if len(full) > ANCHOR_CAP:
        full = full[:ANCHOR_CAP]
    return full


def build_anchor(ws) -> str:
    """Compact mechanical-state signature (<= ANCHOR_CAP chars). Reads ONLY
    fired-predicate state (ledger last snapshot + claim register + facts count
    + the snapshot's active_workers) plus, since #528, OPEN hypothesis
    pointers from hypotheses/ (ids only, never narrative). Prepends a
    `⚠ STATE FLAT` drift warning when drift_detected (#43). NEVER reads
    progress.txt / analysis_state.txt (LLM narrative). FAIL_OPEN: any
    exception -> ""."""
    try:
        ws = Path(ws)
        snap_row, round_n = _last_snapshot(ws)
        if snap_row is None:
            return ""  # nothing mechanical to anchor on — silent

        decision = str(snap_row.get("decision") or "?")
        open_ids = _open_ids(ws, snap_row)
        open_count = snap_row.get("open_count")
        if open_count is None:
            open_count = len(open_ids)
        partial_count = snap_row.get("partial_count", 0)
        active_workers = snap_row.get("active_workers", 0)
        blockers = snap_row.get("blockers") or []
        facts_total = snap_row.get("facts_total")
        if facts_total is None:
            facts_total = _count_facts(ws)

        # Drift warning (cure layer) — single-source drift semantics shared
        # with external_kicker.should_kick. FAIL_OPEN: load failure or drift
        # lookup error -> no warning this turn (the summary still injects).
        drift_prefix = ""
        lib = _load_drift_lib()
        if lib is not None:
            try:
                if lib.drift_detected(ws):
                    n = int(lib.signature_rotation(ws))
                    drift_prefix = (f"WARNING: STATE FLAT: {n} identical turns, "
                                    f"re-read claim-register\n")
            except Exception:  # noqa: BLE001 — drift warning is best-effort
                drift_prefix = ""

        return _compose(drift_prefix, round_n, decision, open_count,
                        partial_count, active_workers, blockers, facts_total,
                        open_ids, _open_hypothesis_pointers(ws))
    except Exception:  # noqa: BLE001 — FAIL_OPEN: never raise into the harness
        return ""


def build_anchor_payload(ws) -> dict:
    """Machine-readable form of the anchor's structured segments (#528).

    Consumers that want dicts instead of the capped anchor STRING (tests,
    introspection tooling) read this. It exposes exactly what the string
    form's structured segments carry — hypothesis pointers as
    [{"claim_id", "hyp_id"}] — and nothing narrative."""
    ws = Path(ws)
    snap_row, round_n = _last_snapshot(ws)
    return {
        "round": round_n,
        "decision": (snap_row or {}).get("decision"),
        "open_ids": _open_ids(ws, snap_row) if snap_row else [],
        "hypothesis_pointers": _open_hypothesis_pointers(ws),
    }


# ---------- emission + entry points ----------

def _emit(anchor: str) -> int:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": anchor,
        }
    }, ensure_ascii=False))
    return 0


def process_event(payload: dict) -> int:
    """Testable core: tool_name gate (case-insensitive 'agent') -> workspace
    resolve -> strict activation -> build_anchor (FAIL_OPEN) -> emit. Returns
    rc (always 0 — the hook injects, never aborts). Non-agent tools / inactive
    sessions / empty anchors SKIP (empty stdout)."""
    tool_name = str(payload.get("tool_name", "")).lower()
    if tool_name != "agent":
        return 0  # non-agent tool — silent (issue: only Agent completion)
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    if not _kunglao_active(ws):
        return 0  # default-inactive: no activation, no firing
    try:
        anchor = build_anchor(ws)
    except Exception:  # noqa: BLE001 — defense-in-depth FAIL_OPEN
        anchor = ""
    if not anchor:
        return 0
    return _emit(anchor)


def main(stdin_stream=None) -> int:
    """PostToolUse entry. Reads JSON payload from stdin (or stdin_stream for
    tests). FAIL_OPEN: unparseable stdin or any processing error -> exit 0,
    empty stdout (never abort the worker completion)."""
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
        payload = json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        return process_event(payload)
    except Exception:  # noqa: BLE001 — FAIL_OPEN at the body level
        return 0


if __name__ == "__main__":
    sys.exit(main())
