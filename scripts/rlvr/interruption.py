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
  2 | any        | any       | bound match               | any      | censored_env  | env_<class>
  3 | any        | True      | none                      | any      | agent_death   | timeout_kill
  4 | not in (0, None) | any | none                      | any      | agent_death   | nonzero_exit
  5 | None       | any       | none                      | dead     | agent_death   | liveness_lost
  6 | None       | any       | none                      | other    | agent_death   | unknown_exit

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

Rows 1 wins over a stale blocker: a clean exit is terminal even when the
workspace still carries an env blocker from an earlier session (the
ladder reads ACTIVE blockers only — the house convention: files under
``blockers/`` without the ``INVALIDATED`` marker, ``blockers/.resolved/``
excluded — but active is not the same as fresh, and a completed rollout
needs no excuse). Row 2 dominates any abnormal exit: a session-bound
blocker file is the #340 evidence carrier (observed bytes + attributed
diagnosis, linted at the write gate) — exogenous evidence beats the exit
code's ambiguity, which is exactly the anti-bias direction
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


def active_env_blocker(ws, *, started_ts=None, claim=None) -> str | None:
    """The FIRST env class matched by an ACTIVE blocker file BOUND to
    the dying session (recency: mtime >= started_ts; or claim: the
    claim id names itself in the blocker text), in ``ENV_CLASSES``
    order; None when no blocker carries a session-bound env class.

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
                bound = (floor is not None and path.stat().st_mtime >= floor)
                named = bool(claim) and claim in text
                if bound or named:
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
