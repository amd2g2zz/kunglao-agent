# -*- coding: utf-8 -*-
"""reward_settlement.py — the ONE deterministic settlement engine (U2/U3).

THE only place reward is computed (owner ruling 2026-09-23: the whole
RLVA reward is unified). Deterministic mapping signals -> band -> reward
per the versioned rules table ``references/contracts/reward-rules.yaml``
(rule_id -> required signals -> band -> reward); every settled row carries
rule_id + evidence_refs, so "这个分数哪来的" always has an answer.

Reward epistemology (the repo's foundation, restated as a design wall):
settlement rewards are NEVER model opinions. The engine consumes only
machine-recorded consumption signals from the unified rollout ledger;
model-produced scores enter the ledger solely as signals marked
``advisory: true`` and are EXCLUDED from rule matching here — advisory
signals can influence nothing alone (and no single signal settles a band
anyway: the rules table requires >=2 distinct signals per rule). The
import surface is allowlisted and pinned by test (no model-call path, no
shell-out or network escape hatch) — the structural half of U3.

Multi-signal anti-pollution: adverse (0.0) requires the full adverse
spectrum (misleading-declaration AND zero-recall AND no-citation); helped
(0.5-1.0) requires consumption AND a downstream positive reference. Rows
no rule can settle land NEUTRAL (rule_id "<kind>/pending") pending
corroboration — including every single-signal row.

Settlement runs on the existing rollup tick (scripts/rollup.py, extended
additively, fail-open — settlement never breaks the terminal transition).
Task rollouts: the oracle checker verdict stays the hard currency
(task/oracle-green is never_demoted); process-credit stays v0.2
replay_ruler scope — this engine unifies the ACCOUNTING, it invents no
process rewards.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

import rollout_ledger as rl

RULES_REL = Path("references") / "contracts" / "reward-rules.yaml"
RULES_SCHEMA = "reward-rules/1"

BANDS = ("SETTLED_GREEN", "SETTLED_RED", "ADVERSE", "HELPED", "NEUTRAL")
NEUTRAL_BAND = "NEUTRAL"
POLARITY_ALPHA_BANDS = frozenset({"SETTLED_GREEN", "HELPED"})
POLARITY_BETA_BANDS = frozenset({"SETTLED_RED", "ADVERSE"})

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] reward_settlement WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


def repo_rules_path() -> Path:
    """The versioned rules file, resolved from the scripts/ parent (works
    for repo checkouts and worktrees alike)."""
    return Path(__file__).resolve().parent.parent / RULES_REL


def load_rules(path: Path | str | None = None) -> dict:
    """Load + validate the rules table. A wrong schema or a rule naming an
    unregistered kind is LOUD (ValueError) — a silently-wrong reward table
    would be the one thing this engine must never be."""
    p = Path(path) if path else repo_rules_path()
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if doc.get("schema") != RULES_SCHEMA:
        raise ValueError(
            f"reward_settlement: rules schema {doc.get('schema')!r} != "
            f"{RULES_SCHEMA!r} ({p})")
    if not isinstance(doc.get("rules"), list) or not doc["rules"]:
        raise ValueError(f"reward_settlement: rules table empty ({p})")
    for rule in doc["rules"]:
        kinds = rule.get("kind")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        for k in kinds:
            if k not in rl.kinds():
                raise ValueError(
                    f"reward_settlement: rule {rule.get('rule_id')!r} "
                    f"references unregistered kind {k!r}")
    return doc


# --- predicate evaluation (pure) ----------------------------------------------

def _advisory(signals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split advisory (model-judged, U3 whitelist) from machine signals."""
    machine = [s for s in signals if not s.get("advisory")]
    advisory = [s for s in signals if s.get("advisory")]
    return machine, advisory


def _pred_hold(pred: dict, machine: list[dict]) -> bool:
    """One requires/optional predicate against the machine signals only."""
    ptype = str(pred.get("type") or "")
    matching = [s for s in machine if str(s.get("type") or "") == ptype]
    if not matching:
        return False
    if "equals" in pred:
        return any(s.get("value") == pred["equals"] for s in matching)
    if "in" in pred:
        return any(s.get("value") in pred["in"] for s in matching)
    if "min_count" in pred:
        return any(isinstance(s.get("value"), (int, float))
                   and s.get("value") >= pred["min_count"]
                   for s in matching)
    return False  # unknown predicate form: never grants a band


def _signal_ref(sig: dict) -> str:
    value = sig.get("value")
    return (f"{sig.get('type')}:{sig.get('source')}="
            f"{json.dumps(value, ensure_ascii=False, sort_keys=True)}")


def classify(kind: str, signals: list[dict], rules_doc: dict) -> dict:
    """Deterministic classification: signals -> settlement document.

    Returns {"reward", "band", "rule_id", "evidence_refs"} — always
    complete (NEUTRAL "<kind>/pending" is the default), so every settled
    row carries its audit trail. Advisory signals never match; they appear
    in evidence_refs as advisory:<type> context only."""
    machine, advisory = _advisory(signals or [])
    matched = None
    for rule in sorted(rules_doc.get("rules") or [],
                       key=lambda r: r.get("order", 0)):
        kinds = rule.get("kind")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if kind not in kinds:
            continue
        if all(_pred_hold(p, machine)
               for p in (rule.get("requires") or [])):
            matched = rule
            break

    refs = [_signal_ref(s) for s in machine]
    refs += [f"advisory:{s.get('type')}" for s in advisory]
    if matched is None:
        return {"reward": 0.0, "band": NEUTRAL_BAND,
                "rule_id": f"{kind}/pending", "evidence_refs": refs}

    optional_ok = all(_pred_hold(p, machine)
                      for p in (matched.get("optional") or []))
    reward = matched.get("reward_full", matched.get("reward", 0.0)) \
        if optional_ok else matched.get("reward", 0.0)
    band = str(matched.get("band") or NEUTRAL_BAND)
    evidence = [str(e) for e in (matched.get("evidence") or [])]
    satisfied = [_signal_ref(s) for s in machine
                 if any(str(p.get("type") or "") == str(s.get("type"))
                        for p in ((matched.get("requires") or [])
                                  + (matched.get("optional") or [])))]
    return {"reward": reward, "band": band,
            "rule_id": str(matched.get("rule_id")),
            "evidence_refs": evidence + satisfied}


# --- the settlement run ---------------------------------------------------------

def settle_workspace(ws, rules_path: Path | str | None = None,
                     now=None) -> dict:
    """Settle every pending rollout in the workspace's unified ledger.

    Idempotent (settled rollouts are skipped); deterministic; fail-open is
    the CALLER's posture — here a missing rules file or an unregistered
    kind in the rules table is LOUD (a silently-wrong reward engine is the
    one failure mode this module exists to make impossible).

    Returns {"pending", "settled", "by_band", "rules_version"}."""
    ws = Path(ws)
    rules_doc = load_rules(rules_path)
    pending = rl.pending_settlement(ws)
    by_band: dict[str, int] = {}
    settled_n = 0
    for row in pending:
        settlement = classify(str(row.get("kind")), row.get("signals") or [],
                              rules_doc)
        res = rl.settle(ws, str(row.get("rollout_id")), settlement)
        if res.get("appended"):
            settled_n += 1
            by_band[settlement["band"]] = by_band.get(settlement["band"], 0) + 1
        else:
            warn("settle_workspace",
                 f"{row.get('rollout_id')}: {res.get('reason')}")
    return {"pending": len(pending), "settled": settled_n,
            "by_band": by_band,
            "rules_version": rules_doc.get("version")}


# --- prior-feed polarity face (consumed by compute_priors, U4) -----------

def polarity_of(band: str) -> str:
    """band -> "positive" | "negative" | "none" (the prior observation)."""
    if band in POLARITY_ALPHA_BANDS:
        return "positive"
    if band in POLARITY_BETA_BANDS:
        return "negative"
    return "none"


def prior_observations(ws, kind: str | None = None,
                       window: tuple | None = None) -> tuple[int, int]:
    """(alpha_obs, beta_obs) over settled rows via THE one interface
    (rollout_ledger.settled). NEUTRAL contributes nothing. Never raises on
    a missing ledger."""
    alpha = beta = 0
    for row in rl.settled(ws, kind=kind, window=window):
        band = str((row.get("settlement") or {}).get("band") or "")
        pol = polarity_of(band)
        if pol == "positive":
            alpha += 1
        elif pol == "negative":
            beta += 1
    return alpha, beta


# --- emission adapters (adapters only, no domain-state rewrites) -------
# The unified ledger is the settlement CURRENCY, not a replacement for
# domain state: mission_ledger / convergence / lessons keep their faces and
# EMIT rows here. Adapters read machine surfaces only (oracle verdict file,
# claim register closure, outcome rows, lesson files) — never a model.

ORACLE_STATUS_REL = Path("runs") / "oracle-status.json"


def _now() -> str:
    from harness_common import utc_now_z
    return utc_now_z()


def _oracle_verdict(ws: Path) -> str | None:
    """Machine verdict face: all registered cases pass -> "pass"; any
    explicit fail -> "fail"; no file / no cases / pending-only -> None
    (no signal — an unmeasured claim settles nothing through this leg)."""
    path = ws / ORACLE_STATUS_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        cases = doc.get("cases")
        if not isinstance(cases, dict):
            return None
        statuses = [str((c or {}).get("status") or "").lower()
                    for c in cases.values() if isinstance(c, dict)]
    except (OSError, ValueError, TypeError):
        return None
    if not statuses:
        return None
    if all(s == "pass" for s in statuses):
        return "pass"
    if any(s == "fail" for s in statuses):
        return "fail"
    return None


def _redteam_confirmed(ws: Path, claim_id: str) -> bool | None:
    """Outcome-row face: red-team CONFIRMED recorded for this claim. None
    when no outcome rows exist at all (no claim -> no signal)."""
    try:
        import outcome_capture
        rows = outcome_capture.read_outcome_rows(ws)
    except Exception as exc:  # noqa: BLE001 — telemetry face degrades
        warn("redteam_face", f"{type(exc).__name__}: {exc}")
        return None
    mine = [r for r in rows
            if str(r.get("claim_id") or "") == str(claim_id)]
    if not mine:
        return None
    return any(str(r.get("checker") or "") == "red-team"
               and str(r.get("result") or "") == "CONFIRMED"
               for r in mine)


def task_signals(ws: Path, claim_id: str, terminal_status: str) -> list[dict]:
    """Machine signals for one task-rollout row (kind=task)."""
    ts = _now()
    signals = [{"type": "claim_terminal", "source": "convergence_check",
                "value": str(terminal_status), "ts": ts}]
    verdict = _oracle_verdict(ws)
    if verdict is not None:
        signals.append({"type": "oracle_verdict", "source": "oracle_runner",
                        "value": verdict, "ts": ts})
    redteam = _redteam_confirmed(ws, claim_id)
    if redteam is not None:
        signals.append({"type": "redteam_confirmed", "source": "outcome_capture",
                        "value": redteam, "ts": ts})
    return signals


def _lesson_frontmatter(path: Path) -> dict:
    """Tolerant frontmatter read of a lesson file (the lessons family's
    own parsing posture)."""
    try:
        parts = path.read_text(encoding="utf-8", errors="replace").split("---", 2)
    except OSError:
        return {}
    if len(parts) < 3:
        return {}
    try:
        meta = yaml.safe_load(parts[1])
        return meta if isinstance(meta, dict) else {}
    except yaml.YAMLError:
        return {}


def self_distill_signals(lesson_path: Path) -> list[dict]:
    """Machine signals for one self_distill rollout row. Consumption
    spectrum signals proper (distill_consumption /
    downstream_positive_reference / the adverse triple) arrive with the
    the distill engine and telemetry producers — this adapter records
    what exists mechanically today."""
    ts = _now()
    stem = lesson_path.stem
    signals = [{"type": "lesson_written", "source": "rollup",
                "value": stem, "ts": ts}]
    meta = _lesson_frontmatter(lesson_path)
    try:
        citations = int(meta.get("citations") or 0)
    except (TypeError, ValueError):
        citations = 0
    if citations > 0:
        signals.append({"type": "lesson_citations",
                        "source": "lessons_telemetry",
                        "value": citations, "ts": ts})
    return signals


def resolve_library(library: Path | str | None) -> Path:
    """Same resolution aggregate_lessons uses (one library, one truth)."""
    from failure_analysis_gate import LESSONS_DIR_DEFAULT
    return Path(library) if library else LESSONS_DIR_DEFAULT


def snapshot_lessons(library: Path | str | None = None) -> set[str]:
    """Lesson stems present BEFORE a rollup's aggregation — the diff base
    for the self_distill adapter (no domain-state rewrite of
    aggregate_lessons; a snapshot-diff is the adapter seam)."""
    lib = resolve_library(library)
    if not lib.is_dir():
        return set()
    return {p.stem for p in sorted(lib.glob("lesson-*.md"))}


def emit_unified_rows(ws: Path, claim_id: str, terminal_status: str,
                      lessons_before: set[str] | None,
                      library: Path | str | None = None) -> dict:
    """Record task + self_distill rows for a terminal rollup (adapters
    only). Task row: one per claim (rollout_id task/<claim>, folds across
    DEFERRED->PROVEN rerolls). Distill rows: one per NEW lesson file since
    the snapshot. Returns a small counter dict; never raises."""
    ws = Path(ws)
    out = {"task_rows": 0, "distill_rows": 0, "reason": None}
    try:
        res = rl.record(ws, kind="task", anchor=str(claim_id),
                        signals=task_signals(ws, claim_id, terminal_status))
        if res.get("appended"):
            out["task_rows"] = 1
        elif res.get("reason") not in (None, "duplicate: unchanged",
                                       "duplicate: already settled"):
            out["reason"] = f"task: {res.get('reason')}"
        if lessons_before is None:
            lessons_before = set()
        lib = resolve_library(library)
        for p in sorted(lib.glob("lesson-*.md")) if lib.is_dir() else []:
            if p.stem in lessons_before:
                continue
            res = rl.record(ws, kind="self_distill", anchor=p.stem,
                            signals=self_distill_signals(p))
            if res.get("appended"):
                out["distill_rows"] += 1
        return out
    except Exception as exc:  # noqa: BLE001 — emission never breaks rollup
        out["reason"] = f"{type(exc).__name__}: {exc}"
        warn("emit_unified_rows", out["reason"])
        return out


def rollup_face(ws: Path, claim_id: str, terminal_status: str,
                lessons_before: set[str] | None,
                library: Path | str | None = None) -> dict:
    """The tick face (called by scripts/rollup.py): emit adapters, settle,
    and emit ONE `rollout_settled` summary event. Each phase caged — the
    terminal transition must not break (the fail-open doctrine)."""
    summary: dict = {"emit": "skipped", "settlement": "skipped"}
    summary["emit"] = emit_unified_rows(
        ws, claim_id, terminal_status,
        lessons_before=lessons_before, library=library)
    try:
        res = settle_workspace(ws)
        summary["settlement"] = res
        summary["settled"] = res.get("settled", 0)
    except Exception as exc:  # noqa: BLE001 — settlement never breaks rollup
        summary["settlement"] = f"error: {exc!r}"
        warn("rollup_face_settle", f"{type(exc).__name__}: {exc}")
    try:
        from kunglao_log import emit
        emit(ws, actor="reward_settlement", action="rollout_settled",
             claim=str(claim_id),
             detail=json.dumps(
                 {"emit": summary.get("emit"),
                  "settled": summary.get("settled", 0)},
                 ensure_ascii=False, sort_keys=True, default=str))
    except Exception as exc:  # noqa: BLE001 — observability only
        warn("rollup_face_emit", f"{type(exc).__name__}: {exc}")
    return summary



if __name__ == "__main__":  # pragma: no cover — library module; tick face via rollup
    print(__doc__)
