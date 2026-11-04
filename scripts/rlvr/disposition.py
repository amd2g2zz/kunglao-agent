# -*- coding: utf-8 -*-
"""rlvr/disposition.py — the episode disposition algebra.

Every rollout ends in exactly one **evidence-gated** disposition, assigned by
a total precedence (first match wins):

    SOLVED > OUT_OF_SCOPE > CENSORED_ENV > ATTEMPTED_EXHAUSTED >
    INFRA > FAILED > SURRENDER

The classifier is pure: no I/O, no model call, no clock. The caller assembles
the record (session fields, act outcomes, authorization, the route-attempt
ledger, wall evidence, the recorded strategic action) and persists the row
under ``runs/disposition/<episode>.json``; the consumer mapping (reward,
measurement, learning) reads the row, never a second classifier.

Record shape (absent keys read as None/False; ``authorized`` is REQUIRED and
must be a bool — a dispatch without authorization context is invalid):

    {
      "claim": str,
      "authorized": bool,
      "oracle_pass": bool,
      "wall": {"session_bound": bool, "corroborated": bool} | None,
      "ledger": {"routes": [str], "attempted": [str], "budget": number,
                 "budget_exhausted": bool} | None,
      "act_outcomes": [str],          # ordered; the LAST act terminated the episode
      "session": {"returncode": int | None, "timed_out": bool,
                  "liveness": "alive" | "dead" | None},
      "strategic_action": "FIGHT" | "BYPASS" | "INVEST" | None,
      "propensity": number | None,    # required iff a strategic action is recorded
      "completion_claimed": bool,
      "evidence_refs": [str],         # artifact paths backing the verdict
      "route_ledger_ref": str | None,
      "wall_ref": str | None,
      "authorization_ref": str | None,
      "authorization": dict | None,   # the declared scope; REQUIRED when
                                      # authorized is True, and it must cover
                                      # the episode's `target`
      "target": str | None,           # the episode target (REQUIRED with it)
      "budget": number | None,        # fixed ROUTE_ATTEMPT_BUDGET (row field)
    }

Evidence gates (spec: openspec/changes/redteam-tdd-bidirectional-critique/
specs/episode-disposition):
  SOLVED              oracle/verifier pass
  OUT_OF_SCOPE        authorization excludes the target
  CENSORED_ENV        session-bound AND corroborated environment wall
  ATTEMPTED_EXHAUSTED route ledger covers the declared routes, or budget out
  INFRA               the terminating act was refused by the environment
  FAILED              execution failure (timeout kill / nonzero exit /
                      liveness loss) or an unverified completion claim
  SURRENDER           authorized, in-scope, unfinished, and no earlier gate

The row is `disposition/1` (see `build_row` / `validate_row` / `write_row`):
one JSON object per episode under ``runs/disposition/<episode>.json``,
mirrored into the unified TELEMETRY ledger and announced by the registered
``disposition_recorded`` event. A row must carry every documented field,
the gate must be one the disposition's evidence supports, and the
disposition's defining evidence pointer must be present (SOLVED -> evidence
refs, CENSORED_ENV -> wall_ref, ATTEMPTED_EXHAUSTED -> route_ledger_ref).
``ts`` is an ISO-8601 UTC second stamp. Re-writing the same row is
idempotent (and heals a failed mirror/event); a divergent rewrite is
refused — an episode's disposition is never rewritten.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from kunglao_log import emit, warn

from . import authorization, consolidated_ledger

#: the row schema stamp (the unified-ledger attribution contract)
SCHEMA = "disposition/1"

#: the registered telemetry event word
EVENT = "disposition_recorded"

#: where the one row per episode lives (workspace-relative)
DISPOSITION_DIR = "runs/disposition"

#: the evidence gates a row may carry (the classifier's match reasons)
GATES = (
    "oracle_pass",
    "authorization",
    "wall",
    "route_ledger",
    "blocked_act",
    "execution_failure",
    "unverified_completion",
    "unfinished",
)

#: an episode id is a FILE TOKEN — no separators, no traversal
_EPISODE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

#: the row's identity timestamp format (calendar-validated on write)
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: every field the `disposition/1` row carries (the schema, not a subset)
ROW_FIELDS = (
    "schema",
    "episode_id",
    "claim",
    "disposition",
    "gate",
    "evidence_refs",
    "route_ledger_ref",
    "wall_ref",
    "authorization_ref",
    "strategic_action",
    "propensity",
    "budget",
    "ts",
)

#: each disposition is paired with the evidence gate(s) the classifier emits
GATE_FOR_DISPOSITION = {
    "SOLVED": ("oracle_pass",),
    "OUT_OF_SCOPE": ("authorization",),
    "CENSORED_ENV": ("wall",),
    "ATTEMPTED_EXHAUSTED": ("route_ledger",),
    "INFRA": ("blocked_act",),
    "FAILED": ("execution_failure", "unverified_completion"),
    "SURRENDER": ("unfinished",),
}


class DispositionError(ValueError):
    """A record or row violates the `disposition/1` contract."""

#: the closed disposition vocabulary, in precedence order (first match wins)
DISPOSITIONS = (
    "SOLVED",
    "OUT_OF_SCOPE",
    "CENSORED_ENV",
    "ATTEMPTED_EXHAUSTED",
    "INFRA",
    "FAILED",
    "SURRENDER",
)

#: the strategic vocabulary recorded before termination (the strategic face)
STRATEGIC_ACTIONS = ("FIGHT", "BYPASS", "INVEST")

#: the legacy session ladder classes the mapping table accepts
LEGACY_CLASSES = ("terminal", "censored_env", "agent_death")


def _result(disposition: str, gate: str) -> dict:
    """The classifier's return shape: the disposition plus the gate that
    matched (audit face; consumers branch on the disposition only)."""
    return {"disposition": disposition, "gate": gate}


def _wall_corroborated(wall) -> bool:
    """Censoring requires BOTH legs: the blocker is session-bound and the
    wall fact is corroborated by a harness-side check. One leg is not
    evidence (the anti-laundering rule in interruption.py). Flags are
    strict booleans — the string "false" is not corroboration."""
    if not isinstance(wall, dict):
        return False
    return wall.get("session_bound") is True and wall.get("corroborated") is True


def _ledger_exhausted(ledger) -> bool:
    """ATTEMPTED_EXHAUSTED needs the route ledger to cover every declared
    route, or the declared budget to be spent. A malformed ledger never
    counts as exhaustion (fail toward an honest gap): the budget flag
    pays only with a recorded positive budget beside route/attempt lists."""
    if not isinstance(ledger, dict):
        return False
    routes = ledger.get("routes")
    attempted = ledger.get("attempted")
    if not isinstance(routes, list) or not isinstance(attempted, list):
        return False
    if not routes:
        return False
    if ledger.get("budget_exhausted") is True:
        budget = ledger.get("budget")
        return (isinstance(budget, (int, float))
                and not isinstance(budget, bool) and budget > 0)
    return set(str(r) for r in routes) <= set(str(a) for a in attempted)


def _execution_failed(session) -> bool:
    """Timeout kill, nonzero exit, or a dead liveness verdict at exit."""
    if not isinstance(session, dict):
        return False
    if session.get("timed_out") is True:
        return True
    returncode = session.get("returncode")
    if returncode is not None and returncode not in (0,):
        return True
    return str(session.get("liveness") or "").strip().lower() == "dead"


def classify_episode(record: dict) -> dict:
    """Classify one episode -> {"disposition", "gate"}.

    Raises ValueError when ``authorized`` is missing or not a bool: the
    disposition contract starts with an explicit authorization context
    (a missing context must never be silently treated as authorized).
    """
    if not isinstance(record, dict):
        raise ValueError("disposition record must be a dict")
    authorized = record.get("authorized")
    if not isinstance(authorized, bool):
        raise ValueError(
            "disposition record requires an explicit bool `authorized`")

    # 1. SOLVED — an oracle/verifier pass outranks every other signal.
    if record.get("oracle_pass") is True:
        return _result("SOLVED", "oracle_pass")

    # 2. OUT_OF_SCOPE — the target is outside the declared authorization.
    if authorized is False:
        return _result("OUT_OF_SCOPE", "authorization")

    # 3. CENSORED_ENV — a session-bound AND corroborated wall.
    if _wall_corroborated(record.get("wall")):
        return _result("CENSORED_ENV", "wall")

    # 4. ATTEMPTED_EXHAUSTED — the ledger (or the budget) is complete.
    if _ledger_exhausted(record.get("ledger")):
        return _result("ATTEMPTED_EXHAUSTED", "route_ledger")

    # 5. INFRA — the terminating act was refused by the environment.
    outcomes = record.get("act_outcomes") or []
    if isinstance(outcomes, list) and outcomes:
        if str(outcomes[-1]).strip().upper() == "BLOCKED":
            return _result("INFRA", "blocked_act")

    # 6. FAILED — execution failure, or a completion claim without a pass.
    if _execution_failed(record.get("session")):
        return _result("FAILED", "execution_failure")
    if record.get("completion_claimed") is True:
        return _result("FAILED", "unverified_completion")

    # 7. SURRENDER — in-scope, unfinished, no earlier gate met.
    return _result("SURRENDER", "unfinished")


def legacy_disposition(session_class: str, oracle_pass: bool) -> str:
    """The published legacy map (session ladder -> disposition).

    terminal + pass -> SOLVED; terminal without a pass -> FAILED
    (unverified completion); censored_env -> CENSORED_ENV; agent_death ->
    FAILED. Unknown classes raise (fail closed).
    """
    cls = str(session_class or "").strip().lower()
    if cls == "terminal":
        return "SOLVED" if oracle_pass is True else "FAILED"
    if cls == "censored_env":
        return "CENSORED_ENV"
    if cls == "agent_death":
        return "FAILED"
    raise ValueError(f"unknown legacy session class: {session_class!r}")


# ---------- the row object ----------

def _fail(field: str, why: str) -> DispositionError:
    return DispositionError(f"disposition.{field}: {why}")


def _nonempty_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def _is_real_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _check_authorization(record: dict) -> None:
    """An authorized episode MUST carry a declared scope that covers its
    target — a dispatch without the block is not authorized — and the
    explicit bool must never contradict the scope.

    `authorized is False` with no scope context is the legitimate
    undeclared/out-of-scope case (OUT_OF_SCOPE). `authorized is True`
    without a positive scope is refused: the flag alone is not a scope.
    """
    authorized = record.get("authorized")
    block = record.get("authorization")
    target = record.get("target")
    if authorized is False:
        if (block is not None or target is not None) and (
                authorization.authorized_target(block, target)):
            raise _fail("authorized",
                        "contradicts the declared authorization scope")
        return
    if not isinstance(block, dict) or _nonempty_str(target) is None:
        raise _fail("authorized",
                    "requires a declared authorization block and target")
    if not authorization.authorized_target(block, target):
        raise _fail("authorized",
                    "contradicts the declared authorization scope")


def _evidence_refs(record: dict) -> list[str]:
    refs = record.get("evidence_refs", [])
    if refs is None:
        return []
    if not isinstance(refs, list):
        raise _fail("evidence_refs", "must be a list of strings")
    for ref in refs:
        if _nonempty_str(ref) is None:
            raise _fail("evidence_refs",
                        "every entry must be a non-empty string")
    return list(refs)


def _optional_ref(record: dict, field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    ref = _nonempty_str(value)
    if ref is None:
        raise _fail(field, "must be a non-empty string or None")
    return ref


def _action_fields(record: dict) -> tuple[str | None, float | None]:
    action = record.get("strategic_action")
    if action is not None and action not in STRATEGIC_ACTIONS:
        raise _fail("strategic_action",
                    f"must be one of {STRATEGIC_ACTIONS} or None")
    propensity = record.get("propensity")
    if action is None:
        if propensity is not None:
            raise _fail("propensity", "requires a recorded strategic_action")
        return None, None
    if not _is_real_number(propensity) or not 0.0 <= propensity <= 1.0:
        raise _fail("propensity",
                    "a recorded action requires a number in [0, 1]")
    return action, propensity


def _ledger_budget(record: dict) -> int | float | None:
    ledger = record.get("ledger")
    if not isinstance(ledger, dict):
        return None
    budget = ledger.get("budget")
    if budget is None:
        return None
    if not _is_real_number(budget) or budget <= 0:
        raise _fail("budget",
                    "the route ledger's budget must be a positive number")
    return budget


def _row_budget(record: dict) -> int | float | None:
    """The row's fixed budget. The ledger that produced the exhaustion
    verdict owns the number: a conflicting record-level value is refused
    (the audit face must never show a budget the classifier did not use)."""
    ledger_budget = _ledger_budget(record)
    record_budget = record.get("budget")
    if record_budget is not None and (
            not _is_real_number(record_budget) or record_budget <= 0):
        raise _fail("budget", "must be a positive number or None")
    if (ledger_budget is not None and record_budget is not None
            and record_budget != ledger_budget):
        raise _fail("budget", "contradicts the route ledger's budget")
    return ledger_budget if ledger_budget is not None else record_budget


def _row_authorization_ref(record: dict) -> str | None:
    """The declared block's provenance wins; a contradicting record-level
    value is refused (the block is the authorization context the dispatch
    carried)."""
    declared = authorization.authorization_ref(record.get("authorization"))
    ref = _optional_ref(record, "authorization_ref")
    if declared is not None and ref is not None and ref != declared:
        raise _fail("authorization_ref",
                    "contradicts the declared authorization block")
    return declared if declared is not None else ref


def build_row(record: dict, *, episode_id: str, ts: str) -> dict:
    """Classify one episode and shape its `disposition/1` row.

    The row carries the classifier's verdict (`disposition` + the `gate`
    that matched), the evidence references, the recorded strategic action
    and its propensity, the fixed budget, and the caller-supplied identity
    (`episode_id`, `ts` — no clock lives here). An authorized episode must
    carry the declared `authorization` block and its `target`; the scope
    must cover the target. Raises `DispositionError` when the record or
    the shaped row violates the contract.
    """
    try:
        verdict = classify_episode(record)
    except ValueError as exc:
        raise DispositionError(str(exc)) from exc
    _check_authorization(record)
    claim = _nonempty_str(record.get("claim"))
    if claim is None:
        raise _fail("claim", "must be a non-empty string")
    action, propensity = _action_fields(record)
    row = {
        "schema": SCHEMA,
        "episode_id": episode_id,
        "claim": claim,
        "disposition": verdict["disposition"],
        "gate": verdict["gate"],
        "evidence_refs": _evidence_refs(record),
        "route_ledger_ref": _optional_ref(record, "route_ledger_ref"),
        "wall_ref": _optional_ref(record, "wall_ref"),
        "authorization_ref": _row_authorization_ref(record),
        "strategic_action": action,
        "propensity": propensity,
        "budget": _row_budget(record),
        "ts": ts,
    }
    return validate_row(row)


def _validate_identity(row: dict) -> None:
    if row.get("schema") != SCHEMA:
        raise _fail("schema", f"must be {SCHEMA!r}")
    episode_id = row.get("episode_id")
    if not isinstance(episode_id, str) or not _EPISODE_ID_RE.fullmatch(
            episode_id):
        raise _fail("episode_id",
                    "must be a safe file token (letters, digits, '.', '_', '-')")
    if _nonempty_str(row.get("claim")) is None:
        raise _fail("claim", "must be a non-empty string")
    ts = row.get("ts")
    if not isinstance(ts, str):
        raise _fail("ts",
                    "must be an ISO-8601 UTC second stamp "
                    "(YYYY-MM-DDTHH:MM:SSZ)")
    try:
        datetime.strptime(ts, _TS_FORMAT)
    except ValueError as exc:
        raise _fail("ts",
                    "must be an ISO-8601 UTC second stamp "
                    "(YYYY-MM-DDTHH:MM:SSZ)") from exc


def _validate_verdict(row: dict) -> None:
    disposition = row.get("disposition")
    if disposition not in DISPOSITIONS:
        raise _fail("disposition", f"must be one of {DISPOSITIONS}")
    allowed = GATE_FOR_DISPOSITION[disposition]
    gate = row.get("gate")
    if gate not in allowed:
        raise _fail("gate",
                    f"{gate!r} is not an evidence gate for {disposition}")


def _validate_refs(row: dict) -> None:
    refs = row.get("evidence_refs")
    if not isinstance(refs, list) or any(
            _nonempty_str(ref) is None for ref in refs):
        raise _fail("evidence_refs", "must be a list of non-empty strings")
    for field in ("route_ledger_ref", "wall_ref", "authorization_ref"):
        value = row.get(field)
        if value is not None and _nonempty_str(value) is None:
            raise _fail(field, "must be a non-empty string or None")


def _validate_action(row: dict) -> None:
    action = row.get("strategic_action")
    if action is not None and action not in STRATEGIC_ACTIONS:
        raise _fail("strategic_action",
                    f"must be one of {STRATEGIC_ACTIONS} or None")
    propensity = row.get("propensity")
    if action is None:
        if propensity is not None:
            raise _fail("propensity", "requires a recorded strategic_action")
        return
    if not _is_real_number(propensity) or not 0.0 <= propensity <= 1.0:
        raise _fail("propensity",
                    "a recorded action requires a number in [0, 1]")


def _validate_budget(row: dict) -> None:
    budget = row.get("budget")
    if budget is not None and (
            not _is_real_number(budget) or budget <= 0):
        raise _fail("budget", "must be a positive number or None")


def _validate_evidence_pointers(row: dict) -> None:
    """The disposition's defining evidence must ride the row: a SOLVED
    row names its artifact, a CENSORED_ENV row names the wall, an
    ATTEMPTED_EXHAUSTED row names the route ledger."""
    disposition = row["disposition"]
    if disposition == "SOLVED" and not row["evidence_refs"]:
        raise _fail("evidence_refs",
                    "SOLVED requires at least one evidence reference")
    if disposition == "CENSORED_ENV" and _nonempty_str(
            row.get("wall_ref")) is None:
        raise _fail("wall_ref", "CENSORED_ENV requires the wall reference")
    if disposition == "ATTEMPTED_EXHAUSTED" and _nonempty_str(
            row.get("route_ledger_ref")) is None:
        raise _fail("route_ledger_ref",
                    "ATTEMPTED_EXHAUSTED requires the route-ledger "
                    "reference")


def validate_row(row: dict) -> dict:
    """Fail-closed validation of one `disposition/1` row (returns it)."""
    if not isinstance(row, dict):
        raise _fail("row", "must be a dict")
    missing = [field for field in ROW_FIELDS if field not in row]
    if missing:
        raise _fail("row", f"missing required field(s): {missing}")
    unknown = sorted(set(row) - set(ROW_FIELDS))
    if unknown:
        raise _fail("row", f"unknown field(s): {unknown}")
    _validate_identity(row)
    _validate_verdict(row)
    _validate_refs(row)
    _validate_evidence_pointers(row)
    _validate_action(row)
    _validate_budget(row)
    return row


@contextmanager
def _write_lock(base: Path):
    """Serialize check -> create -> mirror -> emit per workspace.

    POSIX flock (the consolidated-ledger lock pattern). Where fcntl is
    unavailable (Windows), the exclusive-create below still admits exactly
    one row file; the mirror/event faces keep their own dedupe.
    """
    try:
        import fcntl
    except ImportError:
        yield
        return
    lock_path = base / ".disposition.lock"
    with open(lock_path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_existing(path: Path) -> object:
    """The persisted row; a corrupt row raises (fail closed — corruption
    must never be misreported as a divergent rewrite). OSError propagates."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise _fail("episode_id",
                    f"{path.name}: existing row is corrupt") from exc


def _exclusive_create(tmp: str, path: Path) -> bool:
    """Create without hard links (O_CREAT|O_EXCL) — still exclusive, and
    a loser returns False so the caller runs the identity check."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(Path(tmp).read_bytes())
            fh.flush()
            os.fsync(fh.fileno())
        return True
    except BaseException:
        try:
            os.unlink(path)
        except OSError as exc:
            warn("rlvr.disposition.fallback_cleanup",
                 f"{type(exc).__name__}: {exc}")
        raise


def _atomic_create(path: Path, row: dict) -> bool:
    """Create the row file exclusively (temp + hard-link). Returns False
    when another writer won the create (the caller reads the winner). A
    filesystem without hard links falls back to exclusive create — never
    an unconditional rename (that would bypass the no-rewrite rule)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(row, fh, ensure_ascii=False, sort_keys=True, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            warn("rlvr.disposition.link_fallback",
                 f"{type(exc).__name__}: {exc} — using exclusive create")
            return _exclusive_create(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError as exc:
                warn("rlvr.disposition.temp_cleanup",
                     f"{type(exc).__name__}: {exc}")


def _event_detail(row: dict) -> str:
    """The event detail payload (the row's audit face, JSON-encoded)."""
    return json.dumps({
        "episode_id": row["episode_id"],
        "claim": row["claim"],
        "disposition": row["disposition"],
        "gate": row["gate"],
        "evidence_refs": row["evidence_refs"],
        "route_ledger_ref": row["route_ledger_ref"],
        "wall_ref": row["wall_ref"],
        "authorization_ref": row["authorization_ref"],
        "strategic_action": row["strategic_action"],
        "propensity": row["propensity"],
        "budget": row["budget"],
    }, ensure_ascii=False, sort_keys=True)


def _event_matches(line: str, row: dict) -> bool:
    try:
        event = json.loads(line)
        if event.get("action") != EVENT:
            return False
        detail = json.loads(event.get("detail") or "{}")
    except (TypeError, ValueError):
        return False
    return (detail.get("episode_id") == row["episode_id"]
            and detail.get("claim") == row["claim"]
            and detail.get("disposition") == row["disposition"])


def _event_exists(ws, row: dict) -> bool:
    """An already-emitted disposition event for THIS row (retry dedupe:
    the event stream is append-only, so a retry must not add a second row
    for the same episode; episode id + claim + disposition identify it)."""
    logs = Path(ws) / "runs" / "logs"
    if not logs.is_dir():
        return False
    for path in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
        except OSError as exc:
            warn("rlvr.disposition.event_scan",
                 f"{path}: {type(exc).__name__}: {exc}")
            continue
        if any(_event_matches(line, row) for line in lines):
            return True
    return False


def _ensure_mirrored(ws, row: dict) -> bool:
    for existing in consolidated_ledger.read(
            ws, "telemetry", schema_prefix=SCHEMA):
        if existing == row:
            return True
    return bool(consolidated_ledger.append(ws, "telemetry", row))


def _ensure_emitted(ws, row: dict) -> bool:
    if _event_exists(ws, row):
        return True
    return bool(emit(ws, "orchestrator", EVENT, claim=row["claim"],
                     detail=_event_detail(row)))


def _persist_row(ws: str | Path, row: dict) -> dict:
    """Persist a BUILT row (the private write path; public callers go
    through `write_row`, which cannot skip classification)."""
    validate_row(row)
    base = Path(ws) / DISPOSITION_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{row['episode_id']}.json"
    with _write_lock(base):
        created = _atomic_create(path, row)
        if not created and _read_existing(path) != row:
            raise _fail("episode_id",
                        f"{row['episode_id']!r} already has a different "
                        "disposition row")
        if created:
            mirrored = bool(consolidated_ledger.append(
                ws, "telemetry", row))
            emitted = bool(emit(ws, "orchestrator", EVENT,
                                claim=row["claim"],
                                detail=_event_detail(row)))
        else:
            mirrored = _ensure_mirrored(ws, row)
            emitted = _ensure_emitted(ws, row)
    return {"path": path, "created": created,
            "mirrored": mirrored, "emitted": emitted}


def write_row(ws: str | Path, record: dict, *, episode_id: str,
              ts: str) -> dict:
    """Classify an episode record and persist its `disposition/1` row.

    The RECORD is the only public write input: the row is built by
    `build_row`, so a caller cannot hand-build a row and skip the
    classifier, the gate coupling, or the evidence pointers. Writes
    ``runs/disposition/<episode_id>.json`` with an exclusive create, then
    mirrors the row into the unified TELEMETRY ledger and emits the
    registered ``disposition_recorded`` event. The file is the primary
    object: mirror and event failures are reported (``mirrored`` /
    ``emitted`` False), never allowed to lose the row; the flags report
    the POST-CALL state, so a retry heals a failed mirror/event without
    duplicating it. Re-writing the identical row is idempotent
    (``created`` False); a different row for the same episode raises —
    an episode's disposition is never rewritten.
    """
    return _persist_row(ws, build_row(record, episode_id=episode_id, ts=ts))
