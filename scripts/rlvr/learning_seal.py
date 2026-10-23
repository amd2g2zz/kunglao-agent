#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/learning_seal.py — the learning channel's HMAC seal (#799).

The #736 ``_sanction_sign`` construction applied to every reward-bearing
record: HMAC-SHA256 over a NUL-joined payload (versioned schema stamp +
canonical record sha + mint time), verified with ``hmac.compare_digest``,
keyed at a FIXED path outside the workspace (no env override face — the
same posture as the stop-sanction and review-gate keys). A worker who can
rewrite the workspace's runs/ trees cannot forge the seal; a learner that
refuses unsealed rows converts the three surviving exploit families
(launch-stash Φ inflation, step-credit self-certification, oracle-status
forgery — #601 L7/L8) into loud telemetry instead of banked reward.

Posture:
- armed   = the key file exists and carries >= _KEY_MIN bytes. Writes
  seal (additive ``"seal"`` key only); learners refuse unsealed/forged
  rows FAIL-CLOSED on the learning path (loud warn, the store bytes stay
  untouched — telemetry, never a crash of the mission path).
- unarmed = the channel rides legacy byte-identically; ONE per-process
  notice names the repair path (a hard fail-closed here would kill the
  live loop on every unprovisioned box — the notice keeps the gap
  visible instead).
- no backcompat window (owner ruling 2026-09-01): when armed, a record
  without a valid seal is refused, legacy rows included.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from kunglao_log import warn
from template_version import read_skill_version

#: versioned schema stamp — rides every seal block (the #736 stamp face)
SEAL_SCHEMA = "learning-seal/1"

#: THE key: fixed path outside the workspace, provisioned by the
#: operator. No env override face — a split resolution would let a row
#: be signed under one key and checked under another (#736 precedent).
KEY_PATH = Path(os.path.expanduser("~/.claude/kunglao-learning.key"))

_KEY_MIN = 32

_NOTICE: dict[str, bool] = {"shown": False}

#: R2a: the run-head build anchor — captured at the FIRST armed seal
#: operation in this process and never re-anchored; a mid-run build
#: change IS the loud event, not a new baseline.
_ANCHOR: dict[str, str | None] = {"build": None}


def _live_version() -> str:
    """The live build version — the receipt-checked single source
    (``template_version.read_skill_version``, the rc2 8-surface version
    mechanism). Seam for tests. Raises nothing: an unreadable version
    source is the loud ``unresolved`` face (a release defect), never a
    crash of the mission path."""
    try:
        return str(read_skill_version())
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("learning_seal",
             f"build version unreadable ({type(exc).__name__}: {exc}) — "
             f"anchoring 'unresolved' (a release defect, loudly visible)")
        return "unresolved"


def run_head_version() -> str:
    """The run-head build version: anchored ONCE at the first armed seal
    operation, frozen for the rest of the process. Every mint re-reads
    the LIVE version and a divergence refuses the mint (#799 R2a — one
    run riding two builds is the production failure this face closes)."""
    if _ANCHOR["build"] is None:
        _ANCHOR["build"] = _live_version()
    return str(_ANCHOR["build"])


def keyfile() -> Path:
    """ONE key resolution point shared by sign and verify."""
    return KEY_PATH


def _key() -> bytes | None:
    """The provisioned key, or None (unarmed). Never raises."""
    try:
        key = keyfile().read_bytes().strip()
    except OSError:
        return None
    if len(key) < _KEY_MIN:
        return None
    return key


def armed() -> bool:
    """Enforcement is armed iff the learning key is provisioned."""
    return _key() is not None


def _notice_once() -> None:
    """The unarmed face is legacy; the gap stays visible exactly once
    per process (loud, never silent, never a crash)."""
    if _NOTICE["shown"]:
        return
    _NOTICE["shown"] = True
    warn("learning_seal",
         f"learning channel UNSEALED — provision {keyfile()} "
         f"(>= {_KEY_MIN} bytes) to arm the #799 learning seal; rows "
         f"and stashes ride legacy until then")


def record_sha(row: dict) -> str:
    """Canonical record sha: sha256 over the row WITHOUT its ``seal``
    key, sorted keys, tight separators (the frozen-bytes face — any
    post-seal edit flips the sha and the verify refuses)."""
    payload = {k: v for k, v in row.items() if k != "seal"}
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _sign(key: bytes, record_sha256: str, minted_ts: int,
          build: str) -> str:
    """The #736 NUL-join HMAC shape over (schema, record sha, mint
    time, build) — the row's identity IS its frozen canonical sha, and
    the minting build is INSIDE the payload (a build-column edit flips
    the HMAC; tamper-evident, #799 R2a)."""
    payload = "\0".join([SEAL_SCHEMA, record_sha256, str(minted_ts),
                         build])
    return hmac.new(key, payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def sign_row(row: dict) -> dict:
    """Return a NEW row with the ``seal`` block appended. Unarmed (no
    key) the row returns unchanged — sealing never invents a key and
    never alters a pre-existing column (additive-key-only contract).
    Armed with a mid-run build change (the live version diverging from
    the run-head anchor) the mint REFUSES — a loud event, never a
    warn-and-continue: the row rides unsealed and armed learners refuse
    it, so nothing banks (#799 R2a)."""
    key = _key()
    if key is None:
        _notice_once()
        return row
    anchored = run_head_version()
    live = _live_version()
    if live != anchored:
        warn("learning_seal",
             f"build version changed mid-run (run head anchored "
             f"{anchored!r}, live {live!r}) — seal mint REFUSED, the "
             f"row rides unsealed and armed learners refuse it: one "
             f"run must never ride two builds (#799 R2a)")
        return row
    sha = record_sha(row)
    minted_ts = int(time.time())
    return {**row, "seal": {
        "schema": SEAL_SCHEMA,
        "record_sha256": sha,
        "minted_ts": minted_ts,
        "build": anchored,
        "hmac": _sign(key, sha, minted_ts, anchored),
    }}


def verify_row(row) -> tuple[bool, str | None]:
    """Fail-closed verify: mapping shape, seal present, schema known,
    frozen sha matches the bytes on disk, HMAC valid. (False, reason)
    on ANY miss — the reason names the face for the learner's loud
    telemetry. Never raises."""
    if not isinstance(row, dict):
        return False, "row is not a mapping"
    seal = row.get("seal")
    if not isinstance(seal, dict):
        return False, "row carries no seal block"
    if seal.get("schema") != SEAL_SCHEMA:
        return False, "seal carries an unknown schema"
    build = str(seal.get("build") or "")
    anchored = run_head_version()
    if build != anchored:
        return False, (f"seal minted by build {build!r}, run head "
                       f"anchored {anchored!r} — mid-run build change "
                       f"(mixed-build rows never fold, #799 R2a)")
    try:
        minted_ts = int(seal.get("minted_ts"))
    except (TypeError, ValueError):
        return False, "seal mint time unreadable"
    sha = record_sha(row)
    if str(seal.get("record_sha256") or "") != sha:
        return False, ("record sha mismatch — the row was altered after "
                       "sealing (tamper detected)")
    key = _key()
    if key is None:
        return False, "learning key missing — seal unverifiable"
    expect = _sign(key, sha, minted_ts, build)
    if not hmac.compare_digest(str(seal.get("hmac") or ""), expect):
        return False, "seal HMAC invalid (forged or foreign key)"
    return True, None


def trusted_rows(rows, *, op: str) -> list[dict]:
    """The learner read face: armed, ONLY seal-valid rows survive (ONE
    loud warn per refusal, each naming its own sha label so the
    rate-limited tracer cannot collapse distinct refusals); unarmed,
    the rows pass through silently (the notice lives on the WRITE face).
    The input
    list is never mutated; the underlying store files are never
    written."""
    if not armed():
        _notice_once()
        return list(rows)
    kept: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ok, why = verify_row(row)
        if ok:
            kept.append(row)
            continue
        label = record_sha(row)[:12] if isinstance(row, dict) else "?"
        warn(op, f"refused unsealed/forged learning row "
                 f"(sha={label}, {why}) — no mass banked, store bytes "
                 f"untouched (#799)")
    return kept
