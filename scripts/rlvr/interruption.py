# -*- coding: utf-8 -*-
"""rlvr/interruption.py — the interruption classifier (issue #955, chain link 1).

A rollout can die mid-flight from EXOGENOUS causes (sample deleted,
debugger broken, risk-control account ban, context compaction). The
treatment is CENSORING semantics: env deaths are censored (never scored
as failures), the claim PARKS with escrowed provisional mass, and the
direction posterior gets no observation. Everything downstream keys off
THIS classification, so it is deliberately mechanical: pure if-then over
STRUCTURED state — the session's exit features × the workspace's active
env-class blocker files × the liveness verdict at exit. No prose is
read, no model call exists, no judgment slot.

THE MAPPING TABLE (first match in this order; the ladder's precedence
is terminal > censored_env > agent_death):

  # | returncode | timed_out | SESSION-BOUND env blocker | liveness | class         | reason_code
  --+------------+-----------+---------------------------+----------+---------------+------------------
  1 | 0          | False     | any                       | any      | terminal      | completed
  2 | any        | any       | bound match + corrob*     | any      | censored_env  | env_<class>
  3 | any        | True      | none                      | any      | agent_death   | timeout_kill
  4 | not in (0, None) | any | none                      | any      | agent_death   | nonzero_exit
  5 | None       | any       | none                      | dead     | agent_death   | liveness_lost
  6 | None       | any       | none                      | other    | agent_death   | unknown_exit

  * corroboration per the CORROBORATION table below: a mechanical-check
    AGREES pays on either binding leg; a mechanical-check REFUTAL kills
    that blocker; classes/instances with NO mechanical check pay only on
    BOTH binding legs.

SESSION BINDING (row 2, anti-forge): the agent writes blockers/*.md, so
an unbound keyword match lets a dying agent LAUNDER a real failure into
censored_env (write "captcha verify-wall", exit 1). A blocker therefore
counts as evidence only when it is bound to the DYING session, by
either leg:

  - RECENCY: the blocker file's mtime >= the session's ``started_ts``
    (the blocker was written while THIS rollout ran); or
  - CLAIM: the record's ``claim`` id appears verbatim in the blocker
    text (the blocker names the claim it stalls — the #340 carrier's
    own attribution discipline).

With NEITHER binding key supplied the censor channel is CLOSED — a
keyword match alone never censors (fail toward agent_death, the
dangerous-error direction: censoring requires evidence, not
opportunity). Stale/other-session blockers stay in the workspace but
classify nothing.

CORROBORATION (the round-2 review MEDIUM: both binding legs above are
self-satisfiable — the agent knows its claim id, and any blocker it
writes mid-session has a fresh mtime, so binding alone attests only
that the AGENT authored the blocker, never that the env fact is true).
Before the censor channel pays out, the claimed env fact must agree
with a HARNESS-SIDE mechanical check — the harness re-derives the fact
from the filesystem itself; the blocker's text is a claim, never the
evidence for its own claim:

  class          | mechanical check (harness-observed, never blocker-supplied)
  ---------------+-------------------------------------------------------------
  sample-missing | the strict task_spec ``sample_sha256: <64-hex>`` anchor is
                 | present AND no sample file remains under bins/
  toolchain      | every tool binary the blocker names (jdk/docker/adb/
                 | emulator) is genuinely absent from PATH (shutil.which)
  risk-control   | none — an account ban leaves no harness-observable
                 | on-disk shadow

Payout per matched blocker: the check AGREES -> censor (either binding
leg suffices — the harness fact is the second source); the check
REFUTES (the fact is false on disk — the sample is still there, the
binary still resolves) -> that blocker is not evidence, whatever the
binding; NO check applies (risk-control, or a toolchain blocker naming
no known binary) -> fall back to BOTH binding legs (recency AND claim
id). Design goal: an agent-authored blocker alone must never censor —
at least one harness-observable fact (or both binding legs together)
must agree. The residual after this gate (an agent picking a class
whose mechanical shadow happens to hold on this host) is the write
gate's to police, not the classifier's.

Rows 1 wins over a stale blocker: a clean exit is terminal even when the
workspace still carries an env blocker from an earlier session (the
ladder reads ACTIVE blockers only — the house convention: files under
``blockers/`` without the ``INVALIDATED`` marker, ``blockers/.resolved/``
excluded — but active is not the same as fresh, and a completed rollout
needs no excuse). Row 2 dominates any abnormal exit: a session-bound,
corroborated blocker file is the #340 evidence carrier (observed bytes +
attributed diagnosis, linted at the write gate) — exogenous evidence
beats the exit code's ambiguity, which is exactly the anti-bias direction
(misclassifying an env death as agent death is the dangerous error).

AGENT-DEATH CAVEAT: ``agent_death`` here is the mechanical RESIDUAL
class — the rollout ended without completing and without exogenous
evidence — never an agent-death DECLARATION. Prose death claims stay
owned by the #447/#497 Type E gate; this classifier reads only the
structured session record above and never a worker's narrative.

Session record (the documented input shape; absent keys read as None):

    {"returncode": int | None,   # harness-collected exit code (None = not collected)
     "timed_out":  bool,         # the tier envelope fired
     "liveness":   "alive" | "dead" | None,   # liveness verdict AT EXIT
     "started_ts": epoch secs | "YYYY-MM-DDTHH:MM:SSZ" | None,  # session start
     "claim":      str | None}   # the claim id, for claim-bound blockers

Fail-open: an unreadable workspace contributes no blockers (the ladder
falls through on exit features alone); this face never raises into the
caller's settle path.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation

#: the three env classes the issue names (the closed vocabulary the
#: censored/parking faces key on — reason codes derive from these)
ENV_SAMPLE_MISSING = "sample-missing"
ENV_TOOLCHAIN = "toolchain"
ENV_RISK_CONTROL = "risk-control"

#: match order is FIXED (determinism: the same blocker text always
#: yields the same class); a blocker mentioning several classes classifies
#: as the first match here — risk-control first because an account-level
#: ban explains the widest symptom set and is the costliest to miss.
ENV_CLASSES = (ENV_RISK_CONTROL, ENV_SAMPLE_MISSING, ENV_TOOLCHAIN)

#: class -> content patterns matched against ACTIVE blockers/*.md text
#: (case-insensitive). These are KEYWORD classifiers over the #340
#: schema's attributed-diagnosis field, not a diagnosis engine: the
#: blocker file itself remains the evidence carrier, linted at the
#: write gate.
ENV_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    ENV_RISK_CONTROL: (
        re.compile(r"risk[- ]?control", re.IGNORECASE),
        re.compile(r"account (?:ban|banned|suspended|suspension)", re.IGNORECASE),
        re.compile(r"\bban(?:ned)?\b", re.IGNORECASE),
        re.compile(r"captcha|verify[- ]?wall|device[- ]?check", re.IGNORECASE),
    ),
    ENV_SAMPLE_MISSING: (
        re.compile(r"sample[- ]?(?:missing|deleted|absent|gone)", re.IGNORECASE),
        re.compile(r"(?:missing|deleted) sample", re.IGNORECASE),
        re.compile(r"(?:target|input|sample) (?:file|binary|apk)"
                   r" (?:missing|deleted|not found)", re.IGNORECASE),
        re.compile(r"no such file.*(?:sample|target)", re.IGNORECASE),
    ),
    ENV_TOOLCHAIN: (
        re.compile(r"tool ?chain", re.IGNORECASE),
        re.compile(r"debugger (?:broken|crashed|unavailable)", re.IGNORECASE),
        re.compile(r"(?:jdk|docker) (?:daemon|broken|unavailable|dead)", re.IGNORECASE),
        re.compile(r"emulator|device offline|adb (?:broken|unavailable|dead)", re.IGNORECASE),
    ),
}

#: the classifier's output classes (the closed vocabulary every
#: downstream censoring face switches on)
TERMINAL = "terminal"
CENSORED_ENV = "censored_env"
AGENT_DEATH = "agent_death"

#: the INVALIDATED resolved marker (the stale_blocker_prune convention)
_INVALIDATED = "INVALIDATED"


#: the house Z-timestamp shape (second precision, UTC) — the
#: started_ts string form
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

#: the STRICT task_spec sample anchor — only a top-level
#: ``sample_sha256: <64-hex>`` key is a record (prose that merely
#: mentions sha256 is not; the convention owner is
#: env_check.read_sample_sha256, NOT imported here — it drags the whole
#: toolchain probe matrix at import time, too heavy for this
#: dependency-light module, so the three-line shape is mirrored with
#: this pointer as the drift alarm)
_SAMPLE_SHA_KEY_RE = re.compile(
    r"^\s*sample_sha256:\s*[\"\']?([0-9a-fA-F]{64})[\"\']?\s*$")

#: the tool binaries a toolchain blocker can name, over the same token
#: vocabulary the ENV_TOOLCHAIN patterns already key on (jdk, docker,
#: adb, emulator); "toolchain"/"debugger" name no single binary, so a
#: blocker naming only those is an UNCORROBORATABLE instance (both
#: binding legs). The harness re-derives the absence itself — the
#: blocker naming a tool is a claim, its PATH absence is the fact.
_TOOL_BINARIES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bjdk\b|\bjava\b", re.IGNORECASE), "java"),
    (re.compile(r"\bdocker\b", re.IGNORECASE), "docker"),
    (re.compile(r"\badb\b", re.IGNORECASE), "adb"),
    (re.compile(r"\bemulator\b", re.IGNORECASE), "emulator"),
)

#: the PATH-resolution seam (hermetic pins monkeypatch this)
_which = shutil.which


def _epoch(ts) -> float | None:
    """A session-start timestamp (epoch seconds or the house Z-string)
    -> epoch seconds; unknown shape -> None (binding undecidable)."""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return float(ts)
    try:
        dt = datetime.strptime(str(ts), _TS_FMT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return dt.timestamp()


def _sample_genuinely_absent(ws) -> bool:
    """The sample-missing mechanical check: True only when the workspace
    DECLARES a sample (the strict task_spec ``sample_sha256`` anchor)
    AND no sample file remains under ``bins/``. No anchor -> not
    corroborated (nothing declared, nothing to observe the absence of);
    a file under bins/ -> the claimed absence is REFUTED on disk."""
    try:
        ws = Path(ws)
        tspec = (ws / "task_spec.yaml").read_text(
            encoding="utf-8", errors="replace")
        if not any(_SAMPLE_SHA_KEY_RE.match(line)
                   for line in tspec.splitlines()):
            return False
        bins = ws / "bins"
        if not bins.is_dir():
            return True
        return not any(p.is_file() for p in bins.iterdir())
    except OSError:
        return False


def _named_missing_tools(text: str) -> bool | None:
    """The toolchain mechanical check: True when EVERY tool binary the
    blocker names is genuinely absent from PATH (the harness re-derives
    the absence); False when at least one named binary still resolves
    (the claim is refuted on this host); None when the blocker names no
    known binary (an uncorroboratable instance — the caller falls back
    to BOTH binding legs)."""
    named = sorted({b for pat, b in _TOOL_BINARIES if pat.search(text)})
    if not named:
        return None
    return all(_which(b) is None for b in named)


def _mechanical_check(cls: str, text: str, ws) -> bool | None:
    """The harness-side mechanical check for a claimed env class.
    True = the claimed fact is CORROBORATED; False = REFUTED (the
    harness observed the opposite on disk); None = no check applies for
    this class or this blocker instance (uncorroboratable — the caller
    falls back to BOTH binding legs)."""
    if cls == ENV_SAMPLE_MISSING:
        return _sample_genuinely_absent(ws)
    if cls == ENV_TOOLCHAIN:
        return _named_missing_tools(text)
    return None   # risk-control: an account ban has no on-disk shadow


def corroborate(blocker, ws) -> bool:
    """HARNESS-SIDE CORROBORATION (#955 review round 2, the claim-leg
    MEDIUM): True only when a mechanical check for the env class this
    blocker claims actually RUNS and AGREES — the sample path genuinely
    absent, the named tool binary genuinely missing. The blocker's text
    is a claim, never the evidence for its own claim; an uncorroboratable
    class (or an instance naming no checkable fact) reads False here and
    the classifier instead demands BOTH binding legs."""
    try:
        text = Path(blocker).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if _INVALIDATED in text:
        return False
    for cls in ENV_CLASSES:
        if any(p.search(text) for p in ENV_PATTERNS[cls]):
            return _mechanical_check(cls, text, ws) is True
    return False


def _blocker_pays(cls: str, path: Path, text: str, ws,
                  *, floor: float | None, claim: str) -> bool:
    """One matched blocker's payout rule (the CORROBORATION table):
    binding first (recency or claim leg), then the harness-side
    mechanical check — check AGREES -> pays on the binding leg; check
    REFUTES -> never evidence; NO check for the class/instance -> BOTH
    binding legs required."""
    try:
        bound = floor is not None and path.stat().st_mtime >= floor
    except OSError:
        return False
    named = bool(claim) and claim in text
    if not (bound or named):
        return False
    verdict = _mechanical_check(cls, text, ws)
    if verdict is True:
        return True           # the harness fact agrees
    if verdict is False:
        return False          # refuted — never evidence
    return bound and named    # uncorroboratable: BOTH legs


def active_env_blocker(ws, *, started_ts=None, claim=None) -> str | None:
    """The FIRST env class matched by an ACTIVE blocker file BOUND to
    the dying session (recency: mtime >= started_ts; or claim: the
    claim id names itself in the blocker text) AND CORROBORATED by a
    harness-side mechanical check (see the module docstring's
    CORROBORATION table: check agrees -> either binding leg pays; check
    refutes -> that blocker is not evidence; no check for the class or
    instance -> BOTH binding legs required), in ``ENV_CLASSES`` order;
    None when no blocker carries a session-bound, corroborated env
    class.

    No binding key supplied -> None ALWAYS (the anti-forge fail-closed:
    an unbound keyword match never censors — see the mapping table).
    Unreadable workspace -> None (fail-open, one warn)."""
    if _epoch(started_ts) is None and not str(claim or "").strip():
        return None
    try:
        blockers = Path(ws) / "blockers"
        if not blockers.is_dir():
            return None
        claim = str(claim or "").strip()
        floor = _epoch(started_ts)
        for cls in ENV_CLASSES:
            for path in sorted(blockers.glob("*.md")):
                if ".resolved" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if _INVALIDATED in text:
                    continue  # resolved blocker — not active evidence
                if not any(p.search(text) for p in ENV_PATTERNS[cls]):
                    continue
                if _blocker_pays(cls, path, text, ws,
                                 floor=floor, claim=claim):
                    return cls
        return None
    except OSError as exc:
        warn("rlvr.interruption", f"blocker scan failed: {exc}")
        return None


def classify(session_record, ws) -> dict:
    """One session's interruption class per the mapping table in the
    module docstring. Returns ``{"class": ..., "reason_code": ...}``.
    Pure over the structured record + the workspace's active blocker
    files; never raises into the caller (a malformed record reads as
    the all-None row)."""
    rec = session_record if isinstance(session_record, dict) else {}
    rc = rec.get("returncode")
    timed_out = bool(rec.get("timed_out"))
    liveness = str(rec.get("liveness") or "").strip().lower() or None
    if rc == 0 and not timed_out:
        return {"class": TERMINAL, "reason_code": "completed"}
    env_cls = active_env_blocker(ws,
                                 started_ts=rec.get("started_ts"),
                                 claim=rec.get("claim"))
    if env_cls is not None:
        return {"class": CENSORED_ENV,
                "reason_code": "env_" + env_cls.replace("-", "_")}
    if timed_out:
        return {"class": AGENT_DEATH, "reason_code": "timeout_kill"}
    if rc is not None:
        return {"class": AGENT_DEATH, "reason_code": "nonzero_exit"}
    if liveness == "dead":
        return {"class": AGENT_DEATH, "reason_code": "liveness_lost"}
    return {"class": AGENT_DEATH, "reason_code": "unknown_exit"}
