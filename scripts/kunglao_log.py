#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_log — structured JSONL event log (#287 observability).

One JSON object per line, appended to runs/logs/kunglao-<YYYY-MM-DD>.jsonl
under the workspace. Worker, orchestrator, and hook events share ONE schema:

  ts          ISO8601 UTC timestamp (auto, Z suffix)
  actor       who did it (#879 vocabulary: orchestrator / worker:<name> /
              verifier:<name> / hook:<name> / subagent:<type>; legacy names
              adopted in LEGACY_ACTORS)
  action      what happened (dispatch / tool_call / artifact_written / verify / ...)
              — #459: emit-side words come from the controlled vocabulary
              event_taxonomy.EMIT_ACTIONS (CI-anchored, unregistered = red)
  claim       claim id the event concerns (or null)
  tool        tool name for tool events (or null)
  artifact    artifact id / path written or read (or null)
  duration_ms integer milliseconds the action took (or null)
  exit        integer exit / verdict code (or null)
  detail      free-text detail (or null)
  matched_rule gate rule id / glob a WARN/REJECT face matched (#601, or null)
  trace_id    mission chain id `tr-<mission>-<seq>` (#879, or null — the
              nulls ARE the un-attributed rate)
  null_reasons {} or {field: why} (#58 S2b — a normally-required field that
              landed null is DOCUMENTED, so the log cannot go silently hollow)

Design contract:
  - stdlib only (json / os / sys / datetime / pathlib).
  - deterministic output: sort_keys + compact separators + ensure_ascii=False.
  - NEVER raises on write failure — emit degrades to a stderr warning and
    returns; logging must never break analysis.

#459 read side: `kunglao_log.py --tail <ws> [N]` prints the most recent N
events (default 20, merged across all day files, JSON lines) — the minimal
answer to "诊断不可解释": one command reconstructs what just happened.
"""
from __future__ import annotations



# issue 275 batch-3: fail-open handlers keep their liveness posture (never
# raise, never change the return shape) but must leave ONE trace - a stderr
# WARN naming the operation + reason, rate-limited to once per op until the
# reason changes (the _zof_warn pattern of issue 276).
#
# THIS is now the single implementation. The ~85 per-module
# copies (each with its own `_WARN_LAST` dict) were migrated to
# `from kunglao_log import warn`. Two deliberate consequences:
#
#   * PROCESS-WIDE DEDUPE (intended semantics change): the rate limit used
#     to live in one dict per module, so two modules warning the same
#     (op, reason) in one process each printed. One process, one dict —
#     the same (op, reason) now collapses to the first print, process-wide.
#   * LEDGER FACE: a dedupe-window pass also lands one structured row
#     (action=warn, actor=telemetry) via emit() when a workspace is
#     resolvable (explicit set_warn_workspace() registration, else a cwd
#     walk-up for a workspace marker) — headless runs finally see the
#     fail-open traces. The stderr print STAYS; only the visibility face
#     is added, and the ledger row is written once per dedupe window,
#     never per call.
#
# The module tag in the message is derived from the CALLER's file (the
# stem of the frame's __file__), so `warn("x", "y")` inside rollup.py
# still prints `[kunglao-agent] rollup WARN (fail-open): x: y` — the
# diagnosability token the old private copies hard-coded, now automatic.
import sys
_WARN_LAST: dict[str, str] = {}

# re-entrancy guard: the ledger face calls emit(); an emit write failure
# itself warns — without the guard, warn -> emit -> fail -> warn would
# recurse. While a warn row is being emitted, nested warn calls stay
# stderr-only.
_WARN_LEDGER_ACTIVE = False

# single-slot explicit workspace registration for the ledger face
# (set_warn_workspace); a list is used as an immutable-by-convention box.
_WARN_WS_OVERRIDE: list = []

#: the emit action word for warn ledger rows (registered in
#: event_taxonomy.EMIT_ACTIONS — the controlled emit-action vocabulary).
WARN_LEDGER_ACTION = "warn"


def set_warn_workspace(ws) -> None:
    """Explicitly register the process workspace the warn() ledger face
    writes to. Hooks and entry points that KNOW their workspace can pin
    it here; without a registration the face falls back to a cwd walk-up
    (a directory holding `task_spec.yaml` or a `runs/` dir), and with
    neither, warn() stays stderr-only (the pre-batch behavior)."""
    _WARN_WS_OVERRIDE.clear()
    if ws is not None:
        _WARN_WS_OVERRIDE.append(Path(ws))


def _discover_warn_workspace() -> Path | None:
    """Best-effort workspace resolution for the ledger face: the nearest
    directory at-or-above cwd that carries a workspace marker. None when
    nothing matches (honest "no workspace known" — stderr-only warn)."""
    try:
        cwd = Path.cwd()
    except OSError:
        return None
    for cand in (cwd, *cwd.parents):
        try:
            if (cand / "task_spec.yaml").exists() or (cand / "runs").is_dir():
                return cand
        except OSError:
            continue
    return None


def _warn_workspace():
    if _WARN_WS_OVERRIDE:
        return _WARN_WS_OVERRIDE[0]
    return _discover_warn_workspace()


def _caller_tag() -> str | None:
    """The caller's module token: the stem of the calling frame's
    __file__ (real for CLI runs, pytest imports, and by-path loads), or
    the frame module name as a fallback. Never raises, and deliberately
    exception-FREE (a try/except here would recurse through warn when
    tagging itself fails under exotic interpreters)."""
    getter = getattr(sys, "_getframe", None)
    frame = getter(2) if callable(getter) else None  # <- warn <- caller
    if frame is None:
        return None
    g = getattr(frame, "f_globals", None) or {}
    f = g.get("__file__")
    if f:
        return Path(f).stem
    return g.get("__name__") or None


def _warn_to_ledger(op: str, reason: str, tag: str | None) -> None:
    """The ledger face: one action=warn row per dedupe window, into
    the resolvable workspace (if any). Never raises; re-entrancy guarded
    so the emit-failure warn cannot recurse through this face."""
    global _WARN_LEDGER_ACTIVE
    if _WARN_LEDGER_ACTIVE:
        return
    ws = _warn_workspace()
    if ws is None:
        return
    _WARN_LEDGER_ACTIVE = True
    try:
        emit(ws, "telemetry", WARN_LEDGER_ACTION,
             detail=(f"{tag}: {op}: {reason}" if tag
                     else f"{op}: {reason}"))
    except Exception as exc:  # noqa: BLE001 — never break warn; leave the trace
        warn("warn_ledger", f"ledger row failed: {type(exc).__name__}: {exc}")
    finally:
        _WARN_LEDGER_ACTIVE = False


def warn(op: str, reason: str, *, tag: str | None = None) -> None:
    """The ONE rate-limited fail-open tracer (issue 275 batch-3 policy,
    the single implementation).

    Rate limit: per op until the reason changes, process-wide (used to be
    per-module dicts — the collapse to one process-wide dict is the documented semantics
    change). Faces, in order: the stderr print (console face, module tag
    auto-derived from the caller's file unless `tag` is explicit), then —
    when a workspace is resolvable — ONE action=warn ledger row (persistence
    face, headless visibility). Never raises on any face."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    if tag is None:
        tag = _caller_tag()
    if tag:
        print(f"[kunglao-agent] {tag} WARN (fail-open): "
              f"{op}: {reason}",
              file=sys.stderr)
    else:
        print(f"[kunglao-agent] WARN (fail-open): "
              f"{op}: {reason}",
              file=sys.stderr)
    _warn_to_ledger(op, reason, tag)
import argparse
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

RC_USAGE = 64  # bad invocation (missing workspace / N < 1) — fail fast
DEFAULT_TAIL = 20

# ------------------------- #879 trace identity ------------------------------
# trace_id: the mission-scoped chain id (`tr-<mission>-<seq>`). Identity is
# anchored on three layers (issue #879): mission (trace_id STABLE for the
# whole mission) / claim (C-NN immutable + state machine) / span (append-only
# ledger). The seq disambiguates mission restarts on the same workspace name.
TRACE_ID_RE = re.compile(r"^tr-[a-z0-9][a-z0-9._-]*-\d+$")
TRACE_STATE = Path("runs") / ".trace-state.json"
_MISSION_MAX = 48

# actor vocabulary (#879): the strict forms new emitters must use. `hook:<name>`
# is already the established shape (hook:dispatch_gate / hook:worker_budget).
ACTOR_RE = re.compile(
    r"^(?:orchestrator"
    r"|worker:[A-Za-z0-9._-]+"
    r"|verifier:[A-Za-z0-9._-]+"
    r"|subagent:[A-Za-z0-9._:-]+"
    r"|hook:[A-Za-z0-9._-]+)$")

# Adoption discipline mirrors #459 EMIT_ACTIONS ("words already emitted by
# real producers were incorporated verbatim"): pre-existing actor literals are
# adopted here instead of mass-rewriting ~50 emit sites. The CI anchor
# (scan_actor_literals, anchored by tests/test_trace_identity_879.py) makes
# every NEW literal vocabulary-or-red; legacy names stop growing.
LEGACY_ACTORS = frozenset({
    # #415/#830 durable tick-sidecar actor labels (runs/.heartbeat.log rows,
    # NOT ledger actors): "tick" = real cron/main-flow tick, "register" =
    # registration marker, "hook" = heartbeat_touch pulse. Adopted so the
    # repo-wide actor-literal anchor stays green.
    "tick", "register", "hook",
    "anomaly_detector", "ask_for_direction", "ask_for_direction_gate",
    "backtrack_loop",  # #882 retrospective-loop host (retro_report/retro_policy faces)
    "bash_fact_guard", "blind_gate", "carrier_consistency", "cockpit_summary",
    "claim_granularity",  # issue 293 tagged decision emission (split fan-out + verdict)
    "complete_teardown", "completion_gate", "convergence_check",
    "convergence_health",  # #127 detector liveness telemetry (detector_eval/detector_fired)
    "dead_letter",  # issue-234 dispatch-failure 3-strike writer (must_ask escalation face)
    "decision_pending", "digest_build", "dispatch_context", "dual_gate",
    "env_check", "env_check_gate", "env_repair_l1", "env_state_probe",
    "event_taxonomy", "external_kicker", "failure_analysis",
    "failure_analysis_gate",
    "fix_guard",  # issue 304 fix-as-guard: dormancy sweep writer (guard_dormant face)
    "heartbeat_tick", "heartbeat_touch",
    "hypothesis_bridge",  # issue-252 family-ledger sync + bridge lint writer
    "hypothesis_seeder", "infeasible_proposal", "infeasible_signal",
    "instrument_menu",  # issue 243 menu/beat faces (handroll_warn + promotion emit)
    "hook", "hook_activation", "hypothesis", "init", "kunglao-decide",
    "kunglao_record", "kunglao_resume", "kunglao_status", "kunglao_upgrade",
    "kubectl_test", "lessons_telemetry", "lint", "log_setup", "loop_state",
    "migrate_facts", "mission_ledger", "mission_stall", "notes_writer",
    "nursery", "operator", "oracle_runner",  # #146 retirement coverage WARN face
    "orchestrator_tool_guard", "outcome_capture",
    "plan_drift", "plan_drift_detector", "plan_epistemics", "priority",
    "priority_ratio", "progress_timeline",  # issue 293 tagged decision emission
    "queue", "recall_inject", "refutation_propagate", "rho_checkpoint",
    "reward_settlement",  # unified-reward tick face (rollout_settled summary emit)
    "rollup",
    "rotation_induction",  # issue-341 same-slot value-join induction writer
    "retract_claim", "rho_verifier", "scan_worker_budget",
    "statusline_snapshot",  # #883 statusline health-snapshot writer (event-driven, #142)
    "target_ladder",  # issue 293 tagged decision emission (sibling fan-out + settlement gate)
    "telemetry", "think_seat", "toolchain_install", "tuition_curve",
    "update_index", "upgrade", "user", "user_signal", "verdict_scorer",
    "verify_status_watch", "verifier", "violation_capture",
    "wire_up_settings", "worker", "worker_budget",
    "zero_output_fingerprint",
})

_REPO_SHA: str | None = None
_REPO_SHA_RESOLVED = False


def _repo_sha() -> str | None:
    """Cached git SHA of the running checkout (subprocess, #818 batch-1).

    None on any failure (not a repo / git missing / timeout) — logging must
    never block analysis."""
    global _REPO_SHA, _REPO_SHA_RESOLVED
    if _REPO_SHA_RESOLVED:
        return _REPO_SHA
    _REPO_SHA_RESOLVED = True
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace")
        sha = out.stdout.strip() if out.returncode == 0 else ""
        _REPO_SHA = sha or None
    except Exception:
        _REPO_SHA = None
    return _REPO_SHA


def log_path(ws: Path) -> Path:
    """runs/logs/kunglao-<date>.jsonl — one file per UTC day."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Path(ws) / "runs" / "logs" / f"kunglao-{day}.jsonl"


from harness_common import utc_now_z as _utc_now  # #863 Family F: single source (was a local def)


# ------------------- #58 S1: trace inheritance ------------------------------
# A module-level "current trace" cannot work across processes (hooks run as
# subprocesses), so the inheritance source IS the durable allocator state
# (runs/.trace-state.json, written by allocate_trace_id at the dispatch face).
# Reads are memoized per (workspace, mtime) so the hot emit path costs one
# stat, and a freshly (re-)allocated trace is picked up immediately.
_TRACE_MEMO: dict = {"key": None, "tid": None}


def current_trace(ws) -> str | None:
    """The workspace's current mission trace_id (#58 S1), or None.

    Reads runs/.trace-state.json — the same state allocate_trace_id maintains
    — and returns its trace_id when format-valid. Best-effort, never raises:
    a missing/corrupt state file means "nothing to inherit" (the caller's row
    then documents the gap via null_reasons, see emit)."""
    ws = Path(ws)
    state = ws / TRACE_STATE
    try:
        key = (str(state), state.stat().st_mtime_ns)
    except OSError:
        key = (str(state), None)
    if _TRACE_MEMO["key"] == key:
        return _TRACE_MEMO["tid"]
    tid = None
    try:
        raw = json.loads(state.read_text(encoding="utf-8")).get("trace_id")
        if validate_trace_id(raw):
            tid = raw
    except (OSError, ValueError, TypeError, AttributeError):
        tid = None
    _TRACE_MEMO["key"] = key
    _TRACE_MEMO["tid"] = tid
    return tid


# _UNSET: "kwarg omitted" vs "explicitly None" (#58 S1). Omitted -> inherit
# the mission trace; explicit None is the caller's documented out-of-band face.
_UNSET = object()

# The tick axis: the convergence ledger's raw snapshot-row count, written by
# convergence_check (LEDGER_NAME — pinned equal by
# tests/test_event_schema_255.py::test_tick_accessor_ledger_name_matches_the_writer).
# A local constant keeps this module import-light.
CONV_LEDGER_NAME = ".convergence_ledger.jsonl"

_TICK_MEMO: dict = {"key": None, "tick": None}


def current_tick(ws) -> int | None:
    """The workspace's current tick: RAW snapshot-row count of the
    convergence ledger (the single time axis; round := tick alias).

    Mirrors the ranker's round contract deliberately: the RAW count, never
    a deduped view (dedup collapses same-turn rows on wall-clock proximity
    and would leak the clock into the axis); a snapshot row is a mapping
    with no "type" key that carries "open_count" (event rows are not
    snapshots); unparseable dirty lines are skipped by the tolerant reader.

    Faces: absent ledger -> 0 (a REAL cold-start tick, not a fake value);
    stat-succeeds-but-read-fails (e.g. a directory at the path) -> None —
    that is honest "cannot know", and the emit face documents it
    (``tick_ledger_unreadable``) instead of stamping a fabricated value.
    A dangling symlink at the ledger path reads the same as an absent
    file (the cold-start tick 0) — the same fail-open face the seed
    contract accepts. Reads are memoized per (path, mtime) so the hot
    emit path costs one stat; a ledger append bumps mtime and is picked
    up on the next emit."""
    ws = Path(ws)
    state = ws / CONV_LEDGER_NAME
    try:
        key = (str(state), state.stat().st_mtime_ns)
    except OSError:
        key = (str(state), None)
    if _TICK_MEMO["key"] == key:
        return _TICK_MEMO["tick"]
    tick: int | None
    if not state.exists():
        tick = 0
    else:
        try:
            tick = sum(1 for e in iter_jsonl(
                           state.read_text(
                               encoding="utf-8",
                               errors="replace").splitlines())
                       if isinstance(e, dict)
                       and "type" not in e and "open_count" in e)
        except OSError:
            tick = None
    _TICK_MEMO["key"] = key
    _TICK_MEMO["tick"] = tick
    return tick


def monotonic_ms() -> int:
    """Monotonic clock reading in integer milliseconds (the duration_ms
    source). Monotonic, so a concurrent clock adjustment can never produce
    a negative duration; callers take a pair of readings around bounded
    work and pass ``max(t1 - t0, 0)`` — a measured interval, never a
    wall-clock guess."""
    return int(time.perf_counter() * 1000)


@contextmanager
def timed():
    """Timing wrapper for block-scoped work: yields a one-key dict that
    carries the measured integer milliseconds on exit. The measurement
    happens in ``finally`` so a raising block still records how long it
    ran before the exception propagates (logging must never swallow — nor
    be swallowed by — the caller's error path)."""
    box: dict = {"duration_ms": None}
    start = time.perf_counter()
    try:
        yield box
    finally:
        box["duration_ms"] = max(int((time.perf_counter() - start) * 1000), 0)

# The auto-documented null set; at adoption it was the measured starved set
# (these five fields were 100% null across the 382 live rows at the rot
# audit — "exists but always null is not a stable schema, it is rot"). A
# field from this set that lands null is documented in the row's
# null_reasons sibling ("omitted", or the caller's stated reason).
# trace_id/version are handled beside it (inheritance face /
# sha-unavailable face). Fields NOT in this set (claim/tool/artifact/exit/
# detail) are legitimately optional per action and are never
# auto-documented — that would make the sibling pure noise.
#
# Shrinkage is earned, never declared: a field leaves the set only when it
# is populated-by-construction at every site that emits it. epoch left via
# the tick axis — emit inherits the convergence-ledger tick when the kwarg
# is omitted, so every event carries the axis (an unreadable ledger stays a
# documented null: "tick_ledger_unreadable"). duration_ms / arm /
# hypothesis_ref / matched_rule stay: their values live in caller-side
# execution structure (timing wrapper, actor/action context, settlement),
# so a site that genuinely cannot know one keeps the honest documented
# null rather than a fabricated value.
AUTO_NULL_FIELDS = ("duration_ms", "arm", "hypothesis_ref", "matched_rule")


def _resolve_epoch(ws, epoch: int | None) -> tuple[int | None, str | None]:
    """The tick-axis inheritance face: an explicit epoch wins; an omitted
    one inherits current_tick(ws). Returns (epoch, reason) — the reason is
    non-None only for the honest unknowable face (unreadable ledger)."""
    if epoch is not None:
        return epoch, None
    inherited = current_tick(ws)
    if inherited is None:
        return None, "tick_ledger_unreadable"
    return inherited, None


def emit(ws, actor: str, action: str, *, claim: str | None = None,
         tool: str | None = None, artifact: str | None = None,
         duration_ms: int | None = None, exit: int | None = None,
         detail: str | None = None,
         arm: str | None = None, epoch: int | None = None,
         hypothesis_ref: str | None = None,
         matched_rule: str | None = None,
         trace_id=_UNSET,
         version: str | None = None,
         channel: str | None = None,
         null_reasons: dict | None = None) -> bool:
    """Append one structured event line. Never raises — write failure degrades
    to a stderr warning so logging can never break analysis.

    Returns True when the row reached the ledger, False when the write
    failed (the caller-visible health bit: a caller that must know whether
    observability actually landed checks this instead of assuming).

    #818 batch-1: arm/epoch/hypothesis_ref per #823 attribution contract;
    version auto-fills with the checkout git SHA when omitted (None on
    failure). Absent optional fields are explicit null keys — stable schema,
    old consumers use .get().

    #601: matched_rule — the gate rule id / namespace glob a WARN/REJECT face
    matched (e.g. must_stop_chmod_permissive, jadx, mcp__ghidra__*). Additive
    in the #818 batch-1 style: absent -> explicit null key, old consumers
    keep working via .get().

    #879: trace_id joins the row into its mission chain
    (`tr-<mission>-<seq>`, mission-stable per #879 identity layer); null on
    legacy rows — the gap IS the un-attributed rate signal.

    #699: channel — where the event executed (#698 FINALIZED vocabulary:
    ssh|docker|vmr|adb|local, + mcp). Defaults from the KUNGLAO_CHANNEL
    env var, falling back to ``local``; an explicit kwarg wins (a worker
    relaying through a specific endpoint stamps ``ssh:9876``, not the
    session default). Legacy rows lack the key; the .get() gap IS the
    un-tagged rate signal.

    #58 S1: an OMITTED trace_id inherits the workspace's current mission
    trace (current_trace — the #879 allocator state dispatch maintains), so
    attribution no longer depends on caller discipline. Explicit ``None``
    stays the documented out-of-band face; when nothing is inheritable the
    gap lands in null_reasons (``no_trace_allocated``) instead of starving.

    #58 S2b: normally-required fields that land null are documented. The
    measured starved set (AUTO_NULL_FIELDS — 100% null across 382 live rows)
    gets an automatic ``omitted`` reason; a caller reason (``null_reasons=``
    kwarg) always wins, and fields that actually carry a value are never
    explained. ``null_reasons`` is an always-present explicit key ({}
    when clean) — same stable-schema rule as the null fields themselves.

    epoch IS the tick axis (single time axis; round := tick alias): an
    omitted kwarg inherits current_tick(ws) — the convergence ledger's raw
    snapshot-row count — so events carry the axis by construction, and an
    explicit non-null kwarg wins. Deliberately there is NO explicit-null
    face for epoch (unlike trace_id's sentinel above): ``epoch=None`` is
    treated exactly as omitted and the axis is stamped anyway — the axis
    always exists (0 = cold start), so a caller passing None to mean
    "unknown" receives the tick, not a null. Only a genuinely unreadable
    ledger leaves the field null, documented as
    ``tick_ledger_unreadable`` (honesty rule: a missing measurement is
    explained, never fabricated).

    #58 S3: version already auto-fills from the cached _repo_sha(); an
    unavailable sha is documented (``repo_sha_unavailable``), not silent."""
    if trace_id is _UNSET:
        trace_id = current_trace(ws)
        trace_reason = None if trace_id else "no_trace_allocated"
    elif trace_id:  # explicit non-empty id wins over inheritance
        trace_reason = None
    else:  # explicit None (or empty) is the documented out-of-band face
        trace_reason = "explicit_out_of_band"
    trace_id = str(trace_id) if trace_id else None

    # epoch IS the tick axis: an omitted kwarg inherits the workspace's
    # current tick, so every event carries the single time axis by
    # construction. Only a genuinely unreadable ledger leaves the null,
    # documented — never faked.
    epoch, epoch_reason = _resolve_epoch(ws, epoch)

    reasons: dict = {}
    if null_reasons:
        reasons.update({str(k): str(v) for k, v in null_reasons.items()})
    event = {
        "ts": _utc_now(),
        "actor": actor,
        "action": action,
        "claim": str(claim) if claim is not None else None,
        "tool": str(tool) if tool is not None else None,
        "artifact": str(artifact) if artifact is not None else None,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "exit": int(exit) if exit is not None else None,
        "detail": str(detail) if detail is not None else None,
        "arm": str(arm) if arm is not None else None,
        "epoch": int(epoch) if epoch is not None else None,
        "hypothesis_ref": str(hypothesis_ref) if hypothesis_ref is not None else None,
        "matched_rule": str(matched_rule) if matched_rule is not None else None,
        "trace_id": trace_id,
        "version": str(version) if version else _repo_sha(),
        "channel": (str(channel).lower() if channel
                    else os.environ.get("KUNGLAO_CHANNEL", "local").lower()),
    }
    for f in AUTO_NULL_FIELDS:
        if event[f] is None and f not in reasons:
            reasons[f] = "omitted"
    if epoch_reason and "epoch" not in reasons:
        reasons["epoch"] = epoch_reason
    if trace_reason and "trace_id" not in reasons:
        reasons["trace_id"] = trace_reason
    if event["version"] is None and "version" not in reasons:
        reasons["version"] = "repo_sha_unavailable"
    # a reason for a field that actually carries a value is stale input —
    # null_reasons documents NULLS, so prune it
    for f in [k for k in reasons if event.get(k) is not None]:
        del reasons[f]
    event["null_reasons"] = reasons
    line = json.dumps(event, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False) + "\n"
    p = log_path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        # self-dogfood: the emit-failure face IS this module's warn
        # (dedupe + ledger posture like every other fail-open face); the
        # re-entrancy guard in _warn_to_ledger stops warn -> emit -> warn
        # from recursing.
        warn("emit", f"cannot write {p}: {exc}")
        return False
    _maybe_prune(ws)
    return True


# ------------------- day-file retention --------------------------------
# Keep the newest N `kunglao-<date>.jsonl` day files per workspace. N=30 is
# derived, not vibes: two full milestone windows at the roadmap's ~2-week
# release-train cadence (v0.1.x) plus slack for a long mission's forensic
# replay — day files are small append-only JSONL (KB-scale/day at the rot
# audit's 382-row ledger), so the cap bounds directory growth without
# pruning history an active investigation still needs. Deletes happen at
# write time, gated to once per UTC day per process, and are FAIL-OPEN:
# any unlink error warns and stops the sweep — retention must never break
# emit, and only files matching `kunglao-<YYYY-MM-DD>.jsonl` are ever
# touched (a sibling `kunglao_init-*.log` or foreign file is never a
# candidate).
LOG_DAY_RETENTION = 30
_DAY_FILE_RE = re.compile(r"^kunglao-\d{4}-\d{2}-\d{2}\.jsonl$")

# last UTC day the retention sweep ran (single slot; per-process memo —
# hooks and short CLIs emit once anyway, long runners re-sweep on day-roll)
_PRUNED_DAY: list[str] = []


def prune_day_logs(ws, keep: int = LOG_DAY_RETENTION) -> int:
    """Delete the oldest day files beyond `keep` (newest kept). Returns
    the number removed; stops at the first unlink error (warn + fail-open).
    Only `kunglao-<date>.jsonl` names are candidates."""
    logs = Path(ws) / "runs" / "logs"
    try:
        files = sorted(p for p in logs.glob("kunglao-*.jsonl")
                       if _DAY_FILE_RE.match(p.name))
    except OSError:
        return 0
    excess = len(files) - max(1, int(keep))
    removed = 0
    for p in files[:max(0, excess)]:
        try:
            p.unlink()
            removed += 1
        except OSError as exc:
            warn("prune_day_logs", f"{type(exc).__name__}: {exc}")
            break
    return removed


def _maybe_prune(ws) -> None:
    """Write-time retention gate: at most one sweep per UTC day per
    process. Never raises (retention must never break emit)."""
    today = _utc_now()[:10]
    if _PRUNED_DAY and _PRUNED_DAY[0] == today:
        return
    _PRUNED_DAY.clear()
    _PRUNED_DAY.append(today)
    try:
        prune_day_logs(ws)
    except Exception as exc:  # noqa: BLE001 — best-effort, but never silent
        warn("prune_day_logs",
             f"retention sweep failed: {type(exc).__name__}: {exc}")


# ------------------- #58 S2: subagent lifecycle events ----------------------
# Live evidence (issue #58): worker/verifier/subagent actors had ZERO ledger
# rows — the subagent session has no emit pipe, so dispatch → start → deliver
# → verify was invisible. This is the ledger-side contract: six PER-TRANSITION
# event types (never per-heartbeat) plus derived-event ingestion with dedupe.
# The FILE-SYSTEM→event derivation (worker-status writes, write_guard surfaces)
# is the #57 sibling wiring; these helpers are what it calls.
#
# The words are spelled out (not f-stringed) so the #880 emit-gate forward net
# finds their production emitters in this file.
LIFECYCLE_PHASES = ("spawned", "started", "completed", "failed", "stalled",
                    "reaped")
LIFECYCLE_ACTIONS = {
    "spawned": "lifecycle_spawned",    # Task-spawn observed (orchestrator face)
    "started": "lifecycle_started",    # first subagent output observed
    "completed": "lifecycle_completed",  # delivered (digest may ride detail)
    "failed": "lifecycle_failed",      # terminated with failure
    "stalled": "lifecycle_stalled",    # stall detector fired
    "reaped": "lifecycle_reaped",      # torn down without completion
}


def emit_lifecycle(ws, actor: str, phase: str, *, claim: str | None = None,
                   digest: dict | None = None, detail: str | None = None,
                   artifact: str | None = None, duration_ms: int | None = None,
                   exit: int | None = None, trace_id=_UNSET) -> None:
    """One subagent lifecycle transition row (action=`lifecycle_<phase>`).

    Per-transition by contract — a heartbeat is NOT a lifecycle event. The
    result digest (S2b) rides `detail` as JSON when `digest` is given.
    Unknown phases warn on stderr and write nothing (logging must never
    break analysis, and garbage phases must not pollute the ledger)."""
    action = LIFECYCLE_ACTIONS.get(str(phase))
    if action is None:
        # self-dogfood: same face as the emit-failure warn above.
        warn("emit_lifecycle",
             f"unknown lifecycle phase {phase!r} "
             f"(vocabulary: {', '.join(LIFECYCLE_PHASES)})")
        return
    if digest is not None:
        detail = json.dumps(digest, sort_keys=True, ensure_ascii=False)
    emit(ws, actor, action, claim=claim, artifact=artifact, detail=detail,
         duration_ms=duration_ms, exit=exit, trace_id=trace_id)


def _lifecycle_key(row: dict) -> tuple:
    """Dedupe identity of one lifecycle row: (actor, phase, claim)."""
    action = row.get("action")
    if not isinstance(action, str) or not action.startswith("lifecycle_"):
        return ()
    return (row.get("actor"), action[len("lifecycle_"):], row.get("claim"))


def ingest_lifecycle(ws, candidates) -> list[dict]:
    """Derived-event ingestion (#58 S2): emit lifecycle candidates that are
    NEW, skip ones already on the ledger (same actor/phase/claim), and
    collapse repeats inside the batch itself.

    `candidates`: dicts with actor/phase/claim (+ optional digest/detail/
    artifact/duration_ms/exit/trace_id) — e.g. derived from worker-status
    file transitions. Returns the descriptors actually emitted, in order.
    Never raises on bad candidate shapes: a candidate without actor/phase is
    skipped silently (it has no identity to dedupe on)."""
    ws = Path(ws)
    seen = {_lifecycle_key(r) for r in _all_rows(ws)}
    seen.discard(())
    emitted: list[dict] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        actor, phase = c.get("actor"), c.get("phase")
        if not actor or not phase:
            continue
        key = (actor, str(phase), c.get("claim"))
        if key in seen or key in {e["_key"] for e in emitted}:
            continue
        emit_lifecycle(ws, actor, phase, claim=c.get("claim"),
                       digest=c.get("digest"), detail=c.get("detail"),
                       artifact=c.get("artifact"),
                       duration_ms=c.get("duration_ms"), exit=c.get("exit"),
                       trace_id=c.get("trace_id", _UNSET))
        emitted.append({"actor": actor, "phase": str(phase),
                        "claim": c.get("claim"), "_key": key})
    for e in emitted:
        del e["_key"]
    return emitted


def emit_result_digest(ws, actor: str, *, claim: str | None = None,
                       files_written=(), claims_touched=(), verdict=None,
                       artifact: str | None = None,
                       duration_ms: int | None = None, exit: int | None = None,
                       trace_id=_UNSET) -> None:
    """#58 S2b result-summary face: close the one-way log. `emit()` records
    that a call happened; this records WHAT CAME BACK — files written,
    claims touched, and the verdict — as the ``result_digest`` action with
    the digest JSON in detail (artifact pointers + counts, not blob dumps)."""
    payload = {
        "files_written": [str(f) for f in files_written],
        "claims_touched": [str(c) for c in claims_touched],
        "verdict": str(verdict) if verdict is not None else None,
    }
    emit(ws, actor, "result_digest", claim=claim, artifact=artifact,
         duration_ms=duration_ms, exit=exit,
         detail=json.dumps(payload, sort_keys=True, ensure_ascii=False),
         trace_id=trace_id)


def iter_jsonl(lines, source: str | None = None):
    """Tolerant JSONL line reader (#863 Family K single source).

    Yields parsed values from `lines`, skipping blank lines and lines that
    fail json.loads (JSONDecodeError is a ValueError — one handler covers
    every historical handler shape in the family). Yields ANY parsed value
    (including ``None`` for a literal ``null`` line): filtering to dicts or
    to specific shapes stays with the consumer, byte-equivalent with the
    pre-consolidation loops. Accepts any iterable of str (lists, generators,
    ``reversed(...)``).

    `source` (optional) names the origin for the record-only tier:
    when given, dropped-row count is rate-limited-WARNed once at stream
    end (`jsonl_drop:<source>`); without it the reader stays fully silent
    (byte-compatible with every pre-existing caller)."""
    dropped = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except ValueError:
            dropped += 1
            continue
        yield row
    if source is not None and dropped:
        warn(f"jsonl_drop:{source}", f"{dropped} unparseable row(s) skipped")


def _all_rows(ws: Path) -> list[dict]:
    """Every parseable row across ALL day files, chronological order.

    Shared by tail / unattributed_rate / actor_violations — one read path,
    one tolerance rule (unparseable lines are skipped; record-only:
    per-file drops and unreadable files leave a rate-limited WARN)."""
    logs = Path(ws) / "runs" / "logs"
    rows: list[dict] = []
    if not logs.is_dir():
        return rows
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warn(f"day_file_read:{p.name}", f"{type(exc).__name__}: {exc}")
            continue
        rows.extend(iter_jsonl(text.splitlines(), source=p.name))
    return rows


def tail(ws, n: int = DEFAULT_TAIL) -> list[dict]:
    """The most recent n events across ALL day files, chronological order.

    Read-only: creates/modifies nothing. Day files sort by name (= date), so
    file order is stream order; within a file, append order is stream order.
    Unparseable lines are skipped (same tolerance event_taxonomy applies).
    n <= 0 returns [] (the CLI rejects it earlier; the function degrades)."""
    return _all_rows(ws)[-n:] if n > 0 else []


# ------------------- #879 trace identity helpers ---------------------------

def validate_trace_id(value) -> bool:
    """True iff value is a well-formed `tr-<mission>-<seq>` trace id."""
    return bool(value) and isinstance(value, str) and \
        bool(TRACE_ID_RE.match(value))


def _sanitize_mission(name: str) -> str:
    lowered = re.sub(r"[^a-z0-9._-]+", "-", str(name).lower()).strip("-")
    return (lowered or "mission")[:_MISSION_MAX]


def mission_id(ws: Path) -> str:
    """Mission identity for trace ids: `task_spec.yaml` `mission:` when
    declared, else the workspace dir name (sanitized). Best-effort, never
    raises."""
    try:
        import yaml  # stdlib-adjacent; kunglao_log stays import-light
        spec = yaml.safe_load(
            (Path(ws) / "task_spec.yaml").read_text(encoding="utf-8",
                                                    errors="replace"))
        m = (spec or {}).get("mission") if isinstance(spec, dict) else None
        if isinstance(m, str) and m.strip():
            return _sanitize_mission(m)
    except Exception as exc:  # noqa: BLE001 — identity is best-effort, never fatal
        warn("mission_id", f"{type(exc).__name__}: {exc}")
    return _sanitize_mission(Path(ws).name)


def new_trace_id(mission: str, seq: int) -> str:
    """`tr-<mission>-<seq>` — the #879 pinned format (seq zero-padded 4)."""
    return f"tr-{_sanitize_mission(mission)}-{int(seq):04d}"


def allocate_trace_id(ws, mission: str | None = None) -> tuple[str, bool]:
    """Mission-stable trace allocation (the #879 identity guarantee).

    The SAME mission reuses its trace_id ("mission(trace_id 不变)"); a NEW
    mission (or a corrupted/absent state file) bumps the seq. State lives in
    runs/.trace-state.json — best-effort, fail-open: allocation must never
    break dispatch (on state failure the seq restarts at 1; the id stays
    format-valid). Returns (trace_id, created) — created=True only when a
    NEW id was minted (the durable trace_allocated row fires on that face
    only)."""
    ws = Path(ws)
    if mission is None:
        mission = mission_id(ws)
    seq = 0
    reuse = None
    try:
        state = json.loads(
            (ws / TRACE_STATE).read_text(encoding="utf-8"))
        seq = int(state.get("seq") or 0)
        if str(state.get("mission") or "") == mission:
            prior = state.get("trace_id")
            if validate_trace_id(prior):
                reuse = prior
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        seq = 0
    if reuse:
        return reuse, False
    seq += 1
    tid = new_trace_id(mission, seq)
    try:
        (ws / TRACE_STATE).parent.mkdir(parents=True, exist_ok=True)
        (ws / TRACE_STATE).write_text(
            json.dumps({"mission": mission, "seq": seq, "trace_id": tid},
                       ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
    except OSError as exc:
        warn("allocate_trace_id", f"{type(exc).__name__}: {exc}")
    return tid, True


def validate_actor(actor) -> tuple[bool, str]:
    """Strict #879 actor vocabulary: `orchestrator` |
    `worker:<name>` | `verifier:<name>` | `hook:<name>` | `subagent:<type>`.

    Returns (ok, reason). Emission is NEVER gated on this (logging must not
    break analysis) — the mechanical faces are the repo-wide literal anchor
    (scan_actor_literals) and the ledger query (--check-actors)."""
    if actor is None:
        return False, "actor is None"
    a = str(actor)
    if not a:
        return False, "actor is empty"
    if ACTOR_RE.match(a):
        return True, ""
    head = a.split(":", 1)[0]
    if a in LEGACY_ACTORS:
        return True, ""  # adopted (see LEGACY_ACTORS note)
    if ":" in a:
        return False, f"bad {head!r} form or unknown prefix (vocabulary: " \
                      f"orchestrator/worker:/verifier:/hook:/subagent:)"
    return False, f"unknown actor {a!r} (vocabulary: orchestrator/worker:" \
                  f"/verifier:/hook:/subagent:; legacy names via " \
                  f"LEGACY_ACTORS)"


def scan_actor_literals(root: Path) -> dict[str, set[str]]:
    """Repo-wide #879 actor CI anchor: every actor literal in scripts/*.py +
    hooks/*.py must be vocabulary-valid OR adopted (LEGACY_ACTORS). Mirrors
    the #459 EMIT_ACTIONS anchor shape (unknown literal = red)."""
    known_forms = {
        "orchestrator", "worker:kunglao-worker", "verifier:kunglao-redteam",
        "hook:dispatch_gate", "hook:worker_budget", "subagent:general-purpose",
    }
    violations: dict[str, set[str]] = {}
    for sub in ("scripts", "hooks"):
        sdir = Path(root) / sub
        if not sdir.is_dir():
            continue
        for p in sorted(sdir.glob("*.py")):
            text = p.read_text(encoding="utf-8", errors="replace")
            found: set[str] = set()
            for m in re.finditer(
                    r'(?:\bactor\s*=\s*|\.emit\(\s*[^,()]+,\s*|(?<![\w.])emit\(\s*[^,()]+,\s*)["\']([^"\']+)["\']',
                    text):
                found.add(m.group(1))
            bad = {a for a in found
                   if not (ACTOR_RE.match(a) or a in LEGACY_ACTORS)}
            bad -= known_forms
            if bad:
                violations[f"{sub}/{p.name}"] = bad
    return violations


def unattributed_rate(ws) -> dict:
    """#879 acceptance: how much of the ledger is NOT joinable to a mission
    chain — rows with a null trace_id as a fraction of all rows. The cockpit
    "未归因率" field's data source (#882 downstream)."""
    rows = _all_rows(Path(ws))
    total = len(rows)
    unattr = sum(1 for r in rows if not r.get("trace_id"))
    return {"rows": total,
            "attributed": total - unattr,
            "unattributed": unattr,
            "rate": round(unattr / total, 4) if total else 0.0}


def actor_violations(ws) -> list[dict]:
    """Ledger rows whose actor is neither vocabulary-valid nor adopted —
    the query face behind `--check-actors` (garbage values are visible)."""
    out: list[dict] = []
    for r in _all_rows(Path(ws)):
        actor = r.get("actor")
        if actor is None:
            continue
        ok, _ = validate_actor(actor)
        if not ok:
            out.append({"ts": r.get("ts"), "actor": actor,
                        "action": r.get("action")})
    return out


def main(argv: list[str] | None = None) -> int:
    """Read-only diagnostic CLI. `--tail <ws> [N]` → JSON lines on stdout;
    `--check-actors <ws>` → ledger actor violations (rc 1 on any)."""
    ap = argparse.ArgumentParser(
        prog="kunglao_log.py",
        description="unified event log (sink read side)")
    ap.add_argument("--tail", metavar="WORKSPACE", default=None,
                    help="print the most recent N events of this workspace "
                         f"(default {DEFAULT_TAIL}), JSON lines, read-only")
    ap.add_argument("--check-actors", metavar="WORKSPACE", default=None,
                    help="scan the ledger for actor values outside the #879 "
                         "vocabulary (and not adopted); rc 1 on violations")
    ap.add_argument("n", nargs="?", type=int, default=DEFAULT_TAIL,
                    help=f"how many events (default {DEFAULT_TAIL})")
    args = ap.parse_args(argv)
    if args.tail is None and args.check_actors is None:
        ap.print_help(sys.stderr)
        return RC_USAGE
    if args.check_actors is not None:
        ws = Path(args.check_actors)
        if not ws.is_dir():
            print(f"FAIL: workspace not found: {ws}", file=sys.stderr)
            return RC_USAGE
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError) as exc:
            warn("cli.check_actors", f"{type(exc).__name__}: {exc}")
        viols = actor_violations(ws)
        for v in viols:
            print(f"ACTOR-VIOLATION {v['ts']} actor={v['actor']!r} "
                  f"action={v['action']!r}")
        print(f"checked; {len(viols)} violation(s)")
        return 1 if viols else 0
    ws = Path(args.tail)
    if not ws.is_dir():
        print(f"FAIL: workspace not found: {ws}", file=sys.stderr)
        return RC_USAGE
    if args.n < 1:
        print(f"FAIL: N must be >= 1 (got {args.n})", file=sys.stderr)
        return RC_USAGE
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError) as exc:
        warn("cli.tail", f"{type(exc).__name__}: {exc}")
    for row in tail(ws, args.n):
        # canonical form = the emit serialization (sort_keys, compact,
        # ensure_ascii=False) so tail output round-trips with the file bytes
        print(json.dumps(row, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
