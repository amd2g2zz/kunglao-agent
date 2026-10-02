#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""online_distill.py — the online-distillation engine (one module, five organs).

Online distillation is the runtime capability that fires when the tool
shelf has no viable candidate for the work at hand: the worker's
full-shelf semantic verdict (a structured marker) or an unknown-format
probe failure triggers ONE budgeted distillation act; the act retrieves
from the local re-library first, then the web face; the engine runs
every distilled candidate against the anchored sample bytes and lands
satisfied candidates in the RUN-LOCAL tool shelf only. The global shelf
has no runtime write face — promotion stays a post-run wave task behind
the standing quality bar.

Organs (each fail-closed where it guards a budget, fail-open where it
rides a host):
  scan_triggers     the two mechanical miss signals (nothing else)
  budget ledger     runs/distill-budget.json — per-run act + hop caps,
                    engine-minted run identity, workspace-lifetime
                    global counters, flock-guarded critical section
  validate_report   methodology-first sources + hard expansion caps
  resolve_sample    anchored-sample resolution (the marker hint is a
                    validated hint, never a trust anchor)
  run_candidate     the bounded oracle subprocess against real bytes
  land_candidate    tier-1 landing into <ws>/tools-local/ with the
                    provenance manifest

CLI (production faces; the e2e loop imports the module directly):
  python online_distill.py <ws> --scan       # triggers + trigger row
  python online_distill.py <ws> --reinit     # mint a new run identity
  python online_distill.py <ws> --land <attempt-dir>  # validate + oracle + land

Audit rows (both vocabularies register the three words):
  distill_attempt / distill_result / candidate_landed — 17-field rows;
  the --land CLI face emits the production rows via kunglao_log, the
  e2e host emits through its own stream writer with the same words.

Repo-local siblings (harness_common / kunglao_log) + stdlib only;
deterministic serialization; no network, no LLM.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from harness_common import utc_now_z as _utc_now  # the Family F single source

# the canonical warn — ONE implementation (process-wide dedupe + the
# ledger face); import-guarded so a scripts/-less host context still
# imports the engine (the warn face degrades to stderr).
try:
    from kunglao_log import warn as _warn
except ImportError:  # partial-deploy lifeline, never blocks the engine
    def _warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)

# --- policy constants (the CEILING — a stored budget above these clamps
# down; nothing may raise them; smaller stored values are honored) ------
DISTILL_ACTS_PER_RUN = 2      # hard per-run cap on distillation acts
DISTILL_HOPS_BUDGET = 12      # hard per-run cap on discovery hops
DEPTH_CAP = 1                 # case-expansion chains are forbidden
BREADTH_CAP = 3               # branch hops per root source
ORACLE_TIMEOUT_S = 120        # bounded candidate execution

BUDGET_SCHEMA = "distill-budget/1"
REPORT_SCHEMA = "distill-report/1"
LEDGER_NAME = "runs/distill-budget.json"
TRIGGER_STAMP = "runs/distill-trigger.json"
REPORTS_DIRNAME = "runs/distill-candidates"
TOOLS_LOCAL_DIRNAME = "tools-local"
RUNS_DIRNAME = "runs"

_MARKER_RE = re.compile(
    r"^shelf-miss:[ \t]*(?P<token>[A-Za-z0-9:._-]{2,120})"
    r"(?:[ \t]+sample=(?P<sample>[^\s]+))?[ \t]*$", re.MULTILINE)

#: the probe-evidence faces this engine reads (never re-runs a probe)
DIE_EVIDENCE = "evidence/die.json"
APKID_EVIDENCE = "evidence/apkid.json"


# ---------------------------------------------------------------------------
# organ 1 — the trigger scan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Trigger:
    """One detected miss signal."""

    kind: str            # "shelf-miss" | "format-unknown"
    token: str           # worker vocabulary | format:unknown:<file>
    sample_hint: str | None
    source_file: str     # workspace-relative producer file


def _die_is_unknown(doc: dict) -> bool:
    """die evidence counts as unknown-format only when the probe actually
    produced data and still classified nothing: at least one usable data
    block AND a falsy derived.language (the producer's undetected
    encoding). All-calls-failed is an operational error, not a miss."""
    if not isinstance(doc, dict):
        return False
    call_errors = doc.get("call_errors")
    detects = doc.get("detects")
    usable = bool(detects) or (
        isinstance(call_errors, dict) and len(call_errors) < 5)
    if not usable:
        return False
    derived = doc.get("derived")
    language = derived.get("language") if isinstance(derived, dict) else None
    return not language


def _apkid_is_unknown(doc: dict) -> bool:
    """apkid evidence counts only on a successful run with zero findings
    (status=error is infra failure — no-signal, per the never-infer rule)."""
    if not isinstance(doc, dict):
        return False
    if str(doc.get("status") or "") != "ok":
        return False
    findings = doc.get("findings")
    return findings in (None, [], {}, "")


def scan_triggers(ws, mtime_floor: float | None = None) -> list[Trigger]:
    """The two mechanical miss signals, nothing else. `mtime_floor`
    defaults to the ledger's run_started_ts (a marker predating the run
    is stale); files recorded as consumed markers are skipped."""
    ws = Path(ws)
    triggers: list[Trigger] = []
    state = ledger_state(ws)
    if mtime_floor is None:
        started = state.get("run_started_epoch")
        mtime_floor = started if isinstance(started, (int, float)) else None
    consumed = set(state.get("consumed_markers") or [])
    for path in sorted((ws / RUNS_DIRNAME).glob("worker-status-*.md")):
        rel = path.relative_to(ws).as_posix()
        if rel in consumed:
            continue
        if mtime_floor is not None:
            try:
                if path.stat().st_mtime < mtime_floor:
                    continue
            except OSError as exc:
                _warn("online_distill_scan", f"stat {rel}: "
                      f"{type(exc).__name__}: {exc} (file skipped)")
                continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _warn("online_distill_scan", f"read {rel}: "
                  f"{type(exc).__name__}: {exc} (file skipped)")
            continue
        for m in _MARKER_RE.finditer(text):
            triggers.append(Trigger(
                kind="shelf-miss", token=m.group("token"),
                sample_hint=m.group("sample"), source_file=rel))
    probe_faces = ((DIE_EVIDENCE, _die_is_unknown),
                   (APKID_EVIDENCE, _apkid_is_unknown))
    for rel, is_unknown in probe_faces:
        doc = _read_json(ws / rel)
        if doc is None:
            continue
        if is_unknown(doc):
            triggers.append(Trigger(
                kind="format-unknown",
                token=f"format:unknown:{rel}", sample_hint=None,
                source_file=rel))
    return triggers


def _read_json(path: Path):
    """Tolerant read. A MISSING file is the documented no-signal (probe
    evidence absent, cold-workspace ledger) — explicit existence guard,
    None, no exception face at all. Anything else (corrupt content,
    unreadable) is a degradation: None plus the canonical rate-limited
    warn, never a crash and never silent."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn("online_distill_read", f"{path}: {type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# organ 2 — the budget ledger
# ---------------------------------------------------------------------------


def _fresh_ledger() -> dict:
    return {
        "schema": BUDGET_SCHEMA,
        "run_id": f"dstr-{uuid.uuid4().hex[:8]}",
        "run_started_ts": _utc_now(),
        "per_run_budget": DISTILL_ACTS_PER_RUN, "per_run_used": 0,
        "hops_budget": DISTILL_HOPS_BUDGET, "hops_used": 0,
        "triggers": {}, "consumed_markers": [],
        "global": {"acts": 0, "hops": 0, "landed": 0},
    }


def _epoch_of(ts: str) -> float | None:
    from datetime import datetime
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except (TypeError, ValueError):
        return None


def _clamp(doc: dict) -> dict:
    """Never loosen: stored budgets above the defaults clamp down;
    smaller stored budgets are honored (tightening is always legal).
    Callers run this AFTER the ledger guard validated the counter
    types — a type-garbage document here is an internal-contract
    violation and raises loudly."""
    doc = dict(doc)
    if int(doc.get("per_run_budget", 0)) > DISTILL_ACTS_PER_RUN:
        doc["per_run_budget"] = DISTILL_ACTS_PER_RUN
    if int(doc.get("hops_budget", 0)) > DISTILL_HOPS_BUDGET:
        doc["hops_budget"] = DISTILL_HOPS_BUDGET
    return doc


def _ledger_ints_ok(doc: dict) -> bool:
    """A ledger whose counter fields are not integers is type-garbage —
    unreadable by the fail-closed rule (never a crash, never a reset)."""
    g = doc.get("global")
    if not isinstance(g, dict):
        return False
    checks = (doc.get("per_run_budget"), doc.get("per_run_used"),
              doc.get("hops_budget"), doc.get("hops_used"),
              g.get("acts"), g.get("hops"), g.get("landed"))
    try:
        return all(isinstance(int(v), int) for v in checks)
    except (TypeError, ValueError):
        return False


def ledger_state(ws) -> dict:
    """The effective ledger state. A MISSING ledger mints fresh
    defaults (a cold workspace is not corruption); an EXISTING but
    unreadable/invalid ledger reads as EXHAUSTED (fail-closed) with
    corrupt=True — the optional capability must not open its own
    floodgate on corruption."""
    path = Path(ws) / LEDGER_NAME
    if not path.is_file():
        fresh = _fresh_ledger()
        fresh["corrupt"] = False
        fresh["run_started_epoch"] = 0.0
        fresh.setdefault("harvest_used", 0)  # #477 rider defaults
        return fresh
    raw = _read_json(path)
    if not isinstance(raw, dict) \
            or raw.get("schema") != BUDGET_SCHEMA \
            or not isinstance(raw.get("global"), dict) \
            or not _ledger_ints_ok(raw):
        dead = _fresh_ledger()
        dead.update({
            "corrupt": True, "per_run_budget": 0, "hops_budget": 0,
            "per_run_used": 0, "hops_used": 0,
            "reason": "budget_ledger_unreadable"})
        dead["run_started_epoch"] = 0.0
        dead.setdefault("harvest_used", 0)  # #477 rider defaults
        return dead
    doc = _clamp(raw)
    doc.setdefault("run_id", "dstr-unknown")
    doc.setdefault("run_started_ts", _utc_now())
    doc.setdefault("triggers", {})
    doc.setdefault("consumed_markers", [])
    doc.setdefault("per_run_budget", DISTILL_ACTS_PER_RUN)
    doc.setdefault("hops_budget", DISTILL_HOPS_BUDGET)
    doc.setdefault("per_run_used", 0)
    doc.setdefault("hops_used", 0)
    doc["global"].setdefault("acts", 0)
    doc["global"].setdefault("hops", 0)
    doc["global"].setdefault("landed", 0)
    doc["corrupt"] = False
    started_at = _epoch_of(doc.get("run_started_ts", ""))
    doc["run_started_epoch"] = started_at if started_at is not None else 0.0
    doc.setdefault("harvest_used", 0)  # #477 rider default (carry-safe)
    return doc


def budget_allows(ws) -> tuple[bool, str]:
    state = ledger_state(ws)
    if state.get("corrupt"):
        return False, "budget_ledger_unreadable"
    if int(state["per_run_used"]) >= int(state["per_run_budget"]):
        return False, "per_run_act_budget_exhausted"
    return True, ""


class _LedgerLock:
    """Workspace-scoped advisory lock around the read-check-debit-write
    critical section (atomic replace alone is not mutual exclusion —
    concurrent closure processes share this workspace)."""

    def __init__(self, ws: Path):
        self.path = Path(str(Path(ws) / LEDGER_NAME) + ".lock")
        self.fd: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o644)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        return False


def _atomic_write_json(path: Path, doc: dict) -> None:
    """Writer-unique tmp + os.replace + 0644 parity (the house write
    discipline); non-silent cleanup."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=path.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, sort_keys=True, indent=2) + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError as cleanup_exc:
            # the silent-handler house rule: even tmp cleanup leaves the
            # one trace — a silent pass here would hide disk trouble
            _warn("online_distill_write",
                  f"tmp cleanup {tmp}: {type(cleanup_exc).__name__}: "
                  f"{cleanup_exc}")
        raise


def reserve_act(ws, token: str, source_file: str | None = None,
                sample_hint: str | None = None) -> dict | None:
    """Atomically check-and-debit ONE distillation act for `token`.
    Returns the attempt receipt, or None when refused (cap exhausted,
    duplicate token, or a corrupt ledger — every refusal is the
    caller's row to record with the ledger's reason)."""
    ws = Path(ws)
    with _LedgerLock(ws):
        state = ledger_state(ws)
        if state.get("corrupt"):
            return None
        if int(state["per_run_used"]) >= int(state["per_run_budget"]):
            return None
        if token in (state.get("triggers") or {}):
            return None
        attempt_n = int(state["global"]["acts"]) + 1
        attempt = f"attempt-{attempt_n}"
        doc = _read_json(ws / LEDGER_NAME)
        if not isinstance(doc, dict):
            doc = _fresh_ledger()
        doc["per_run_used"] = int(doc.get("per_run_used", 0)) + 1
        doc.setdefault("triggers", {})[token] = attempt
        if source_file:
            consumed = list(doc.setdefault("consumed_markers", []))
            if source_file not in consumed:
                consumed.append(source_file)
                doc["consumed_markers"] = consumed
        g = doc.setdefault("global", {"acts": 0, "hops": 0, "landed": 0})
        g["acts"] = int(g.get("acts", 0)) + 1
        _atomic_write_json(ws / LEDGER_NAME, doc)
        return {"attempt": attempt, "token": token,
                "sample_hint": sample_hint,
                "per_run_budget": _clamp(doc)["per_run_budget"],
                "per_run_used": doc["per_run_used"]}


def refuse_reason(ws, token: str) -> str:
    """Why a trigger would be refused right now (for the refusal row)."""
    state = ledger_state(ws)
    if state.get("corrupt"):
        return "budget_ledger_unreadable"
    if token in (state.get("triggers") or {}):
        return "duplicate_trigger_token"
    if int(state["per_run_used"]) >= int(state["per_run_budget"]):
        return "per_run_act_budget_exhausted"
    return ""


def spend_hops(ws, n: int) -> bool:
    """Debit n hop-units if the per-run hop budget allows; False leaves
    the ledger untouched."""
    if n <= 0:
        return True
    ws = Path(ws)
    with _LedgerLock(ws):
        state = ledger_state(ws)
        if state.get("corrupt"):
            return False
        if int(state["hops_used"]) + n > int(state["hops_budget"]):
            return False
        doc = _read_json(ws / LEDGER_NAME)
        if not isinstance(doc, dict):
            # no ledger file yet (the corrupt case already returned):
            # debit starts from the fresh defaults
            doc = _fresh_ledger()
        doc["hops_used"] = int(doc.get("hops_used", 0)) + n
        g = doc.setdefault("global", {"acts": 0, "hops": 0, "landed": 0})
        g["hops"] = int(g.get("hops", 0)) + n
        _atomic_write_json(ws / LEDGER_NAME, doc)
        return True


def reinit_run(ws) -> dict:
    """Mint a NEW run identity (the ONLY reset face): per-run counters
    zero, run_started_ts moves, the global counters carry over."""
    ws = Path(ws)
    with _LedgerLock(ws):
        doc = _read_json(ws / LEDGER_NAME)
        fresh = _fresh_ledger()
        if isinstance(doc, dict) and isinstance(doc.get("global"), dict):
            fresh["global"] = dict(doc["global"])
        if isinstance(doc, dict) and "harvest_used" in doc:
            # #477 rider counters ride this ledger with the spine's own
            # semantics: the cap carries over, the per-run counter resets
            # with the run (mirrors per_run_used).
            fresh["harvest_used"] = 0
            if "harvest_budget" in doc:
                fresh["harvest_budget"] = doc["harvest_budget"]
        _atomic_write_json(ws / LEDGER_NAME, fresh)
        return fresh


def count_landed(ws, n: int = 1) -> None:
    ws = Path(ws)
    with _LedgerLock(ws):
        doc = _read_json(ws / LEDGER_NAME)
        if not isinstance(doc, dict):
            return
        g = doc.setdefault("global", {"acts": 0, "hops": 0, "landed": 0})
        g["landed"] = int(g.get("landed", 0)) + n
        _atomic_write_json(ws / LEDGER_NAME, doc)


# ---------------------------------------------------------------------------
# organ 3 — report validation (methodology-first, hard caps)
# ---------------------------------------------------------------------------


def _check_sources(repo: Path, sources) -> list[str]:
    """Local citations must resolve to real repo files; web sources
    carry a URL and an access date; every kind must be known."""
    violations: list[str] = []
    for idx, src in enumerate(sources):
        if not isinstance(src, dict):
            violations.append(f"source[{idx}]: not an object")
            continue
        kind = str(src.get("kind") or "")
        ref = str(src.get("ref") or "")
        if kind == "relibrary":
            if not ref.startswith("references/"):
                violations.append(f"source[{idx}]: relibrary ref outside "
                                  f"the library: {ref}")
            elif not (repo / ref).is_file():
                violations.append(f"source[{idx}]: fabricated local "
                                  f"citation (no such file): {ref}")
        elif kind == "web":
            if not ref.startswith(("http://", "https://")):
                violations.append(f"source[{idx}]: web ref is not a URL: "
                                  f"{ref}")
            if not str(src.get("date") or "").strip():
                violations.append(f"source[{idx}]: web ref missing "
                                  f"access date: {ref}")
        else:
            violations.append(f"source[{idx}]: unknown source kind {kind!r}")
    return violations


def _check_hops(sources, hops) -> tuple[list[str], int]:
    """Depth cap: a branch may never serve as another hop's root.
    Breadth cap: at most BREADTH_CAP branch hops per root. Returns
    (violations, hop_count)."""
    violations: list[str] = []
    branches: set[int] = set()
    per_root: dict[int, int] = {}
    count = 0
    for idx, hop in enumerate(hops):
        if not isinstance(hop, dict):
            violations.append(f"hop[{idx}]: not an object")
            continue
        root, branch = hop.get("root"), hop.get("branch")
        if not isinstance(root, int) or not isinstance(branch, int) \
                or not (0 <= root < len(sources)) \
                or not (0 <= branch < len(sources)) or root == branch:
            violations.append(f"hop[{idx}]: root/branch not valid "
                              f"source indices")
            continue
        if root in branches:
            violations.append(f"hop[{idx}]: depth cap {DEPTH_CAP} violated "
                              f"(root {root} is itself a branch)")
            continue
        per_root[root] = per_root.get(root, 0) + 1
        branches.add(branch)
        count += 1
    for root, n in sorted(per_root.items()):
        if n > BREADTH_CAP:
            violations.append(f"breadth cap {BREADTH_CAP} violated under "
                              f"root {root} ({n} branch hops)")
    return violations, count


def _check_candidates(candidates) -> list[str]:
    """Every candidate needs a shelf-safe name and a complete oracle
    declaration."""
    violations: list[str] = []
    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            violations.append(f"candidate[{idx}]: not an object")
            continue
        name = str(cand.get("name") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", name):
            violations.append(f"candidate[{idx}]: bad name {name!r}")
        oracle = cand.get("oracle")
        if not isinstance(oracle, dict) \
                or not isinstance(oracle.get("expect_rc"), int) \
                or not str(oracle.get("expect_stdout_contains") or ""):
            violations.append(f"candidate[{idx}]: oracle declaration "
                              f"incomplete")
    return violations


def validate_report(repo, ws, report: dict) -> tuple[bool, list[str]]:
    """Validate a distillation report. Whole-report semantics: any
    violation rejects the report (its candidates never reach the
    oracle). Local citations must resolve to real repo files; web
    sources carry URL + access date; at least one method; hops obey
    depth 1 / breadth 3 and the remaining per-run hop budget."""
    repo = Path(repo)
    ws = Path(ws)
    if not isinstance(report, dict) \
            or report.get("schema") != REPORT_SCHEMA:
        return False, [f"schema != {REPORT_SCHEMA}"]
    sources = report.get("sources")
    if not isinstance(sources, list) or not sources:
        return False, ["no sources recorded"]
    violations = _check_sources(repo, sources)
    methods = report.get("methods")
    if not isinstance(methods, list) or not methods \
            or not all(isinstance(m, str) and m.strip() for m in methods):
        violations.append("no methods extracted (methodology-first bar)")
    hops = report.get("hops")
    hops = hops if isinstance(hops, list) else []
    hop_violations, hop_count = _check_hops(sources, hops)
    violations.extend(hop_violations)
    if not violations and hop_count:
        state = ledger_state(ws)
        remaining = int(state["hops_budget"]) - int(state["hops_used"])
        if hop_count > remaining:
            violations.append(f"hop budget exceeded: {hop_count} hops > "
                              f"{remaining} remaining")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        violations.append("no candidates")
    else:
        violations.extend(_check_candidates(candidates))
    return (not violations), violations


def commit_hops(ws, report: dict) -> bool:
    """Debit the report's hops after validation passed."""
    hops = report.get("hops") if isinstance(report, dict) else None
    return spend_hops(ws, len(hops) if isinstance(hops, list) else 0)


# ---------------------------------------------------------------------------
# organ 4 — anchored sample resolution + the oracle
# ---------------------------------------------------------------------------


def _expect_of(decl: dict) -> tuple[int, str]:
    """Safe oracle-expectation coercion for call sites running
    validated reports (defense in depth: a non-int rc reads as a
    failing sentinel, never a tick-crashing raise)."""
    try:
        rc = int(decl.get("expect_rc"))
    except (TypeError, ValueError):
        rc = 1
    marker = str(decl.get("expect_stdout_contains") or "")
    return rc, marker


def resolve_sample(ws, trigger: Trigger) -> tuple[Path | None, str]:
    """Resolve the oracle sample. The ANCHOR is the workspace's sample
    container (bins/ — the immutable analysis input): a single file
    there is the anchored sample outright; with several, the marker
    hint may pick one BY NAME (validated against the anchor set). An
    anchorless workspace falls back to the guarded marker hint (marked
    fallback). A hint that escapes the workspace never resolves."""
    ws = Path(ws)
    hint = (trigger.sample_hint or "").strip()
    bins = ws / "bins"
    if bins.is_dir():
        files = sorted(p for p in bins.iterdir() if p.is_file())
        if len(files) == 1:
            anchored = files[0]
            if not hint:
                return anchored, "anchored"
            if hint == anchored.relative_to(ws).as_posix() \
                    or hint in (anchored.name,):
                return anchored, "anchored"
            return None, "hint-mismatch"
        if files and hint:
            for f in files:
                if hint in (f.name, f.relative_to(ws).as_posix()):
                    return f, "anchored"
            return None, "hint-mismatch"
    if hint:
        cand = (ws / hint).resolve()
        try:
            cand.relative_to(ws.resolve())
        except ValueError:
            return None, "hint-mismatch"
        if cand.is_file():
            return cand, "marker-fallback"
    return None, "none"


def run_candidate(candidate: Path, sample: Path, *, expect_rc: int = 0,
                  expect_stdout_contains: str = "",
                  timeout_s: int = ORACLE_TIMEOUT_S,
                  runner=None) -> dict:
    """Run one candidate against the sample bytes as a bounded
    subprocess. The engine injects the resolved sample path — a
    manifest-supplied path is never executed. Mechanical conformance
    only: declared rc + stdout marker + non-empty stdout."""
    out = {"satisfied": False, "rc": None, "timed_out": False,
           "stdout_sha256": None, "stdout_tail": "",
           "expect_rc": expect_rc,
           "expect_stdout_contains": expect_stdout_contains}
    if not Path(candidate).is_file() or not Path(sample).is_file():
        out["error"] = "candidate-or-sample-missing"
        return out
    cmd = [sys.executable, str(candidate), str(sample)]
    try:
        if runner is not None:
            proc_out = runner(cmd)
        else:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_s,
                encoding="utf-8", errors="replace")
            proc_out = (proc.returncode, proc.stdout)
        rc, stdout = proc_out
        out["rc"] = rc
        out["stdout_sha256"] = hashlib.sha256(
            stdout.encode("utf-8", "replace")).hexdigest()
        out["stdout_tail"] = stdout[-400:]
        out["satisfied"] = (rc == expect_rc and bool(stdout.strip())
                            and (not expect_stdout_contains
                                 or expect_stdout_contains in stdout))
    except subprocess.TimeoutExpired:
        out["timed_out"] = True
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# ---------------------------------------------------------------------------
# organ 5 — tier-1 landing
# ---------------------------------------------------------------------------


def land_candidate(ws, attempt_dir, report: dict, candidate_name: str,
                   oracle_outcome: dict) -> tuple[Path, Path] | None:
    """Land ONE satisfied candidate into the run-local shelf with its
    provenance manifest. Unsatisfied outcomes never land; the manifest
    carries everything the post-run promotion wave needs (sources,
    hops, methods, oracle outcome with the anchored sample sha256 and
    the self-declared flag)."""
    if not oracle_outcome.get("satisfied"):
        return None
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", str(candidate_name)):
        return None
    ws = Path(ws)
    attempt_dir = Path(attempt_dir)
    cand_file = attempt_dir / f"{candidate_name}.py"
    if not cand_file.is_file():
        return None
    entry = None
    for cand in report.get("candidates") or []:
        if isinstance(cand, dict) and cand.get("name") == candidate_name:
            entry = cand
            break
    if entry is None:
        return None
    tools_dir = ws / TOOLS_LOCAL_DIRNAME
    tools_dir.mkdir(parents=True, exist_ok=True)
    dest = tools_dir / f"{candidate_name}.py"
    dest.write_bytes(cand_file.read_bytes())
    os.chmod(dest, 0o755)
    oracle = dict(oracle_outcome)
    oracle["oracle_self_declared"] = True
    manifest = {
        "schema": "distill-manifest/1",
        "name": candidate_name,
        "capability": entry.get("capability"),
        "attempt": attempt_dir.name,
        "sources": report.get("sources") or [],
        "hops": report.get("hops") or [],
        "methods": report.get("methods") or [],
        "oracle": oracle,
        # #478 PR2 (owner challenge: file-landing != toolchain): the
        # usage metadata rides the manifest so the run-local shelf scan
        # (tool-search --find, fourth source) surfaces an INVOCABLE,
        # behavior-annotated candidate — the next worker decides
        # without opening the file.
        "usage": {
            "invoke": f"python {TOOLS_LOCAL_DIRNAME}/{candidate_name}.py"
                      " <sample-path>",
            "verified": "oracle satisfied on the anchored sample "
                        "(self-declared)",
        },
        "landed_ts": _utc_now(),
    }
    manifest_path = tools_dir / f"{candidate_name}.manifest.json"
    _atomic_write_json(manifest_path, manifest)
    count_landed(ws, 1)
    return dest, manifest_path


# ---------------------------------------------------------------------------
# the production trigger stamp + rows (kunglao_log faces)
# ---------------------------------------------------------------------------


def emit_trigger_row(ws, trigger: Trigger, allowed: bool, reason: str,
                     actor: str = "hook:round_closure") -> bool:
    """The production closure's signal row: distill_attempt with
    phase=triggered (an explicitly exempted signal face — the act
    itself is the orchestrator's decision and may never follow)."""
    try:
        import kunglao_log
    except ImportError:
        return False
    return kunglao_log.emit(
        ws, actor, "distill_attempt",
        detail=json.dumps({
            "phase": "triggered",
            "trigger": {"kind": trigger.kind, "token": trigger.token,
                        "sample_hint": trigger.sample_hint,
                        "source_file": trigger.source_file},
            "budget_allowed": allowed, "refusal_reason": reason,
            "note": "signal face: the distill act is the orchestrator's "
                    "decision per the loop protocol",
        }, sort_keys=True, ensure_ascii=False))


def _emit_production_row(ws, action: str, *, detail: dict,
                         tool: str | None = None) -> bool:
    """The --land CLI face's production rows (distill_result /
    candidate_landed) via kunglao_log — the 17-field schema, actor
    `orchestrator` (the loop protocol's orchestrator invokes the
    engine). Never raises: a logging failure degrades to False."""
    try:
        import kunglao_log
    except ImportError:
        return False
    return kunglao_log.emit(
        ws, "orchestrator", action, tool=tool,
        detail=json.dumps(detail, sort_keys=True, ensure_ascii=False))


def stamp_trigger(ws, triggers: list[Trigger]) -> bool:
    """Persist the trigger state the orchestrator's tick reads."""
    if not triggers:
        return False
    doc = {
        "schema": "distill-trigger/1",
        "ts": _utc_now(),
        "triggers": [
            {"kind": t.kind, "token": t.token,
             "sample_hint": t.sample_hint, "source_file": t.source_file}
            for t in triggers],
    }
    _atomic_write_json(Path(ws) / TRIGGER_STAMP, doc)
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="online distillation engine — trigger scan, budget, "
                    "validate + oracle + land")
    ap.add_argument("ws", help="workspace path")
    ap.add_argument("--scan", action="store_true",
                    help="scan for miss signals, stamp the trigger file, "
                         "emit the production trigger rows")
    ap.add_argument("--reinit", action="store_true",
                    help="mint a new run identity (resets per-run "
                         "counters; global carries over)")
    ap.add_argument("--land", metavar="ATTEMPT_DIR",
                    help="validate the attempt's report, run candidates "
                         "against the anchored sample, land satisfied ones")
    ap.add_argument("--sample", default=None,
                    help="with --land: the sample path when no trigger "
                         "record is available (guarded, ws-relative)")
    args = ap.parse_args(argv)
    ws = Path(args.ws)
    if args.scan:
        triggers = scan_triggers(ws)
        for t in triggers:
            allowed, reason = budget_allows(ws), refuse_reason(ws, t.token)
            allowed = allowed and not reason
            emit_trigger_row(ws, t, allowed, reason)
        return 0 if stamp_trigger(ws, triggers) else 0
    if args.reinit:
        doc = reinit_run(ws)
        print(json.dumps({"run_id": doc["run_id"]}, sort_keys=True))
        return 0
    if args.land:
        attempt_dir = Path(args.land)
        report = _read_json(attempt_dir / "report.json")
        if not isinstance(report, dict):
            print(json.dumps({"landed": [],
                              "error": "report missing or unreadable"}),
                  file=sys.stderr)
            return 2
        repo = Path(__file__).resolve().parents[1]
        ok, violations = validate_report(repo, ws, report)
        if not ok:
            print(json.dumps({"landed": [], "violations": violations},
                             sort_keys=True))
            return 2
        commit_hops(ws, report)
        sample_hint = str(((report.get("trigger") or {})
                           .get("sample_hint")) or args.sample or "")
        trigger = Trigger("shelf-miss",
                          str((report.get("trigger") or {}).get("token")
                              or "cli"),
                          sample_hint or None, "")
        sample, source = resolve_sample(ws, trigger)
        landed: list[str] = []
        if sample is None:
            print(json.dumps({"landed": [], "sample_source": source}))
            return 3
        for cand in report.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            expect_rc, marker = _expect_of(cand.get("oracle") or {})
            oracle = run_candidate(
                attempt_dir / f"{cand.get('name')}.py", sample,
                expect_rc=expect_rc, expect_stdout_contains=marker)
            oracle["sample_sha256"] = hashlib.sha256(
                sample.read_bytes()).hexdigest()
            oracle["sample_source"] = source
            got = land_candidate(ws, attempt_dir, report,
                                 str(cand.get("name")), oracle)
            if got:
                landed.append(str(got[0]))
                _emit_production_row(
                    ws, "candidate_landed",
                    tool=str(got[0].relative_to(ws)),
                    detail={"attempt": attempt_dir.name,
                            "name": str(cand.get("name")),
                            "capability": cand.get("capability"),
                            "tool_path": str(got[0].relative_to(ws))})
        result_detail = {
            "attempt": attempt_dir.name, "phase": "result",
            "validated": True, "violations": [],
            "hops": len(report.get("hops") or []),
            "oracle": {"satisfied": bool(landed),
                       "sample_source": source,
                       "landed": landed}}
        _emit_production_row(ws, "distill_result",
                             detail=result_detail,
                             tool=(landed[0] if landed else None))
        print(json.dumps({"landed": landed, "sample_source": source},
                         sort_keys=True))
        return 0
    ap.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
