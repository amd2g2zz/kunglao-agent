#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""challenge_ledger — adversarial-loop data layer.

The maker-checker loop was in GAN collapse: redteam's cheapest PASS was
replaying the worker's own path. This module is the DATA LAYER of the
fix — every challenge/rebuttal/arbitration act lands here as structured,
grounded, tamper-evident JSON.

Design invariants:

  * Grounding: a challenge MUST carry a falsifier — a runnable command
    or an artifact path. Hand-wavy challenges are rejected at write
    time: they never enter the ledger, so they never burn a round.
    Rebuttal MUST reference the challenge it answers and point at
    reviewable evidence.

  * Open attack surface: the dimension tag is a FREE label plus a
    one-line self-description. The machine validates structure only —
    whether an attack angle is smart is decided by the adversarial
    process and the arbitrator, never by a vocabulary list.

  * Assertion freeze: the claim's assertion text is hashed at round 1.
    A worker that quietly weakens its claim mid-battle gets its write
    REJECTED (AssertionDrift) — moving the goalposts means re-filing
    as a NEW claim and restarting the full pipeline.

  * Max 5 rounds: a hard, non-configurable cap. Round 6+ writes raise
    RoundCapExceeded. Only after round 5 does the orchestrator
    arbitrate (the stalemate phase).

  * Anti-forgery trust root: round files are append-only and chained
    (each round signs the previous round's file sha); every linked
    document carries an HMAC, verified on every chain walk, and the
    orchestrator summary is keyed with the key that lives ONLY in the
    orchestrator's process context (review_gate precedent). A worker
    that reverse-engineers every validation rule still cannot forge a
    resolved state without the key.

Schema (runs/challenges/<claim>/round-N.json):

    {
      "round": 1,
      "claim": "C-12",
      "assertion_snapshot_sha": "<sha256 of frozen assertion text>",
      "prev_round_sha": null | "<sha256 of previous chained bytes>",
      "events": [ {kind: challenge|rebuttal|verifier_call|arbitration,
                   ...kind-specific fields...} ],
      "hmac": "<HMAC(chain inputs)>"
    }

Event kinds:
  challenge      {id, dimension, dimension_free, target, falsifier{cmd,expect}, impact}
  rebuttal       {id, rebutts:<challenge id>, new_evidence{cmd|artifact}, argument}
  verifier_call  {id, ref:"<event id>.falsifier", verifier, finding}   # on-demand
  arbitration    {round_final:true, outcome:"upheld"|"rebutted", basis:[event ids]}

NEVER RAISES on disk errors except where a raise IS the contract
(InvalidEvent / AssertionDrift / RoundCapExceeded — rejections are the
mechanical teeth, not failures).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path

MAX_ADVERSARIAL_ROUNDS = 5  # hard cap: round 6+ is refused, non-configurable

CLAIM_RE = re.compile(r"^C-\d+$")


class InvalidEvent(Exception):
    """Structurally invalid event: missing falsifier, orphan rebuttal,
    unknown kind, bad claim id. Rejected at write time."""


class AssertionDrift(Exception):
    """The claim's assertion text changed mid-battle. The worker must
    re-file as a new claim (moving the goalposts is not a rebuttal)."""


class RoundCapExceeded(Exception):
    """Tried to write past MAX_ADVERSARIAL_ROUNDS. Not configurable."""


def _dir(ws: Path, claim: str) -> Path:
    if not CLAIM_RE.match(claim or ""):
        raise InvalidEvent(f"bad claim id: {claim!r}")
    return Path(ws) / "runs" / "challenges" / claim


def _round_path(ws: Path, claim: str, n: int) -> Path:
    return _dir(ws, claim) / f"round-{n}.json"


def _active_round_path(ws: Path, claim: str) -> Path:
    return _dir(ws, claim) / ".active-round"


def _read_active_round(ws: Path, claim: str) -> int:
    p = _active_round_path(ws, claim)
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _set_active_round(ws: Path, claim: str, n: int) -> None:
    """Advance the active round pointer (test + orchestrator face)."""
    _active_round_path(ws, claim).write_text(str(n), encoding="utf-8")


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sign(key: bytes, claim: str, round_n: int, snapshot_sha: str,
          prev_sha: str | None, events: list) -> str:
    payload = json.dumps(
        {"claim": claim, "round": round_n,
         "assertion_snapshot_sha": snapshot_sha,
         "prev_round_sha": prev_sha, "events": events},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(key, payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def begin_claim(ws: Path, claim: str, *, assertion_text: str,
                key: bytes) -> None:
    """Freeze the claim's assertion text and open the ledger. Must run
    before the first challenge; the freeze is write-once per claim."""
    d = _dir(ws, claim)
    d.mkdir(parents=True, exist_ok=True)
    snapshot = _sha256_bytes(assertion_text.encode("utf-8"))
    meta_path = d / "meta.json"
    if meta_path.exists():
        return  # idempotent: the freeze is write-once per claim
    doc = {"round": 0, "claim": claim,
           "assertion_snapshot_sha": snapshot,
           "prev_round_sha": None, "events": [],
           "hmac": _sign(key, claim, 0, snapshot, None, [])}
    meta_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    _set_active_round(ws, claim, 0)


def _load_meta(ws: Path, claim: str) -> dict:
    p = _dir(ws, claim) / "meta.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidEvent(
            f"ledger not initialized (begin_claim first): {exc}")


def _validate_event(ev: dict, known_ids: set) -> None:
    kind = ev.get("kind")
    if kind == "challenge":
        f = ev.get("falsifier")
        if not isinstance(f, dict) or not (f.get("cmd") or f.get("artifact")):
            raise InvalidEvent(
                "challenge without a falsifier (cmd or artifact) — "
                "grounding rule: no falsifier, no ledger entry, "
                "no round cost")
        if not ev.get("id") or not ev.get("target"):
            raise InvalidEvent("challenge needs id + target assertion")
        if not ev.get("dimension_free"):
            raise InvalidEvent(
                "challenge needs dimension_free: one line saying where "
                "this attack strikes (free text, not a vocabulary check)")
    elif kind == "rebuttal":
        if ev.get("rebutts") not in known_ids:
            raise InvalidEvent(
                f"rebuttal references unknown challenge {ev.get('rebutts')!r}")
        ne = ev.get("new_evidence")
        if not isinstance(ne, dict) or not (ne.get("cmd") or ne.get("artifact")):
            raise InvalidEvent("rebuttal needs grounded new_evidence")
    elif kind == "verifier_call":
        if not ev.get("id"):
            raise InvalidEvent("verifier_call needs id")
    elif kind == "arbitration":
        if ev.get("outcome") not in ("upheld", "rebutted"):
            raise InvalidEvent("arbitration outcome must be upheld|rebutted")
    else:
        raise InvalidEvent(f"unknown event kind: {kind!r}")


def append_event(ws: Path, claim: str, event: dict, *, key: bytes,
                 assertion_text: str | None = None) -> Path:
    """Append one event to the active round (creating round N+1 on the
    first event after an advance). Returns the round file path.

    Rejections ARE the mechanical teeth: InvalidEvent (structure /
    grounding), AssertionDrift (goalposts moved), RoundCapExceeded
    (past round 5)."""
    meta = _load_meta(ws, claim)
    n = _read_active_round(ws, claim)
    # The cap blocks contest writes only: the terminal arbitration must
    # stay writable at round 5, or "the orchestrator arbitrates the
    # stalemate after round 5" could never be recorded. Double
    # arbitration is blocked by the round_final guard below.
    is_terminal_arbitration = (event.get("kind") == "arbitration"
                               and event.get("round_final") is True)
    if n >= MAX_ADVERSARIAL_ROUNDS and not is_terminal_arbitration:
        raise RoundCapExceeded(
            f"round {n + 1} refused: MAX_ADVERSARIAL_ROUNDS="
            f"{MAX_ADVERSARIAL_ROUNDS} is a hard cap")
    if assertion_text is not None:
        got = _sha256_bytes(assertion_text.encode("utf-8"))
        if got != meta["assertion_snapshot_sha"]:
            raise AssertionDrift(
                "claim assertion text changed mid-battle — re-file as a "
                "new claim (moving the goalposts is not a rebuttal)")

    # known challenge/rebuttal ids across ALL rounds so far (cross-round
    # references are legal: a round-3 rebuttal answers a round-1 challenge)
    known: set = set()
    for i in range(1, n + 1):
        p = _round_path(ws, claim, i)
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for e in doc.get("events", []):
            if e.get("id"):
                known.add(e["id"])

    _validate_event(event, known)

    if is_terminal_arbitration:
        for i in range(1, n + 1):
            p = _round_path(ws, claim, i)
            if not p.exists():
                continue
            try:
                prior = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if any(e.get("kind") == "arbitration" and e.get("round_final")
                   for e in prior.get("events", [])):
                raise InvalidEvent(
                    "ledger already carries a final arbitration — the "
                    "stalemate was decided; no second arbitration")

    rp = _round_path(ws, claim, n + 1)
    if n > 0:
        prev_sha = _sha256_bytes(_round_path(ws, claim, n).read_bytes())
    else:
        # chaining starts from the meta (snapshot) file
        prev_sha = _sha256_bytes((_dir(ws, claim) / "meta.json").read_bytes())

    doc = {
        "round": n + 1,
        "claim": claim,
        "assertion_snapshot_sha": meta["assertion_snapshot_sha"],
        "prev_round_sha": prev_sha,
        "events": [event],
        "hmac": _sign(key, claim, n + 1, meta["assertion_snapshot_sha"],
                      prev_sha, [event]),
    }
    rp.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                  encoding="utf-8")
    _set_active_round(ws, claim, n + 1)
    return rp


def rounds(ws: Path, claim: str) -> list[Path]:
    """Round files in order (missing dir -> [])."""
    d = _dir(ws, claim)
    if not d.is_dir():
        return []
    out = []
    for i in range(1, MAX_ADVERSARIAL_ROUNDS + 2):
        p = d / f"round-{i}.json"
        if p.exists():
            out.append(p)
    return out


def verify_chain(ws: Path, claim: str, *, key: bytes) -> tuple[bool, str]:
    """Recompute the chain AND authenticate every linked document.

    Tamper faces, all mechanically checked:

      1. forward linkage: prev_round_sha binds each round to the
         previous linked bytes (meta.json anchors round 1);
      2. per-round authentication: each round's hmac is
         recomputed with the orchestrator key — fabricated tails,
         refabricated histories, and any post-hoc edit fail without
         the key;
      3. meta authentication: meta's OWN round-0 hmac is
         verified too — a pre-round-1 rewrite of the assertion
         snapshot previously voided the freeze;
      4. fail-closed parsing: malformed documents (wrong
         types anywhere the checks touch) return not-ok with a reason,
         never raise out of verification.
    """
    meta_path = _dir(ws, claim) / "meta.json"
    if not meta_path.exists():
        return False, "ledger not initialized"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return False, "meta.json: not an object"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return False, f"meta.json: unparsable ({exc})"
    if not isinstance(meta.get("hmac"), str):
        return False, "meta.json: hmac malformed"
    expect_meta = _sign(key, claim, 0, meta.get("assertion_snapshot_sha", ""),
                        meta.get("prev_round_sha"), meta.get("events", []))
    if not hmac.compare_digest(meta["hmac"], expect_meta):
        return False, "meta.json: hmac authentication failed"
    prev_sha = _sha256_bytes(meta_path.read_bytes())
    rs = rounds(ws, claim)
    for idx, rp in enumerate(rs, start=1):
        raw = rp.read_bytes()
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return False, f"{rp.name}: unparsable ({exc})"
        if not isinstance(doc, dict):
            return False, f"{rp.name}: not an object"
        if doc.get("prev_round_sha") != prev_sha:
            return False, (
                f"{rp.name}: prev_round_sha mismatch — round {idx - 1} "
                f"was modified after this round was written")
        events = doc.get("events", [])
        if not isinstance(events, list):
            return False, f"{rp.name}: events malformed"
        if not isinstance(doc.get("hmac"), str):
            return False, f"{rp.name}: hmac malformed"
        expect = _sign(key, claim, idx,
                       doc.get("assertion_snapshot_sha", ""),
                       doc.get("prev_round_sha"), events)
        if not hmac.compare_digest(doc["hmac"], expect):
            return False, (
                f"{rp.name}: hmac authentication failed — this round was "
                f"written or rewritten without the orchestrator key")
        prev_sha = _sha256_bytes(raw)
    return True, "ok"


def open_challenges(ws: Path, claim: str) -> list[dict]:
    """Challenges not yet answered by a rebuttal (cross-round view).
    The gate consumes this via summary()."""
    answered: set = set()
    challenges: list[dict] = []
    for rp in rounds(ws, claim):
        try:
            doc = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for e in doc.get("events", []):
            if e.get("kind") == "challenge":
                challenges.append(e)
            elif e.get("kind") == "rebuttal":
                answered.add(e.get("rebutts"))
            elif (e.get("kind") == "arbitration"
                  and e.get("outcome") == "rebutted"):
                # a final arbitration can clear remaining challenges
                for c in challenges:
                    answered.add(c.get("id"))
    return [c for c in challenges if c.get("id") not in answered]


def current_head_sha(ws: Path, claim: str) -> str:
    """Sha of the CURRENT ledger head (newest round file, else meta).
    The freshness anchor: a summary minted at an earlier head fails
    authentication once the head moves (stale-replay is dead)."""
    rs = rounds(ws, claim)
    head = rs[-1].read_bytes() if rs else meta_path_bytes(ws, claim)
    return _sha256_bytes(head)


def summary(ws: Path, claim: str, *, key: bytes) -> dict:
    """Orchestrator-side adversarial summary — the input the signature
    gate consumes. The gate MUST NOT trust this dict's own claims: it
    calls authenticate_summary(summary, key=gate_key, ws=…, claim=…)
    and only acts on the summary when that returns True.

    Freshness binding: the HMAC covers head_sha = the current
    summary minted before new challenges land fails authentication
    after the head moves: stale all-clear replays are dead."""
    chain_ok, why = verify_chain(ws, claim, key=key)
    oc = open_challenges(ws, claim)
    core = {
        "claim": claim,
        "rounds": len(rounds(ws, claim)),
        "chain_ok": chain_ok,
        "chain_why": why,
        "open_challenges": sorted(c.get("id", "?") for c in oc),
        "head_sha": current_head_sha(ws, claim),
    }
    core["hmac"] = hmac.new(
        key,
        json.dumps(core, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8"),
        hashlib.sha256).hexdigest()
    return core


def meta_path_bytes(ws: Path, claim: str) -> bytes:
    """The meta file's current bytes (chain anchor for empty ledgers)."""
    return (_dir(ws, claim) / "meta.json").read_bytes()


def authenticate_summary(summary_doc: dict, *, key: bytes,
                         ws: Path | None = None,
                         claim: str | None = None) -> bool:
    """Gate-side check, two layers:

    1. HMAC: recompute over the summary's core with the GATE's key —
       a summary minted with any other key fails (knowing the code is
       worthless without the key).
    2. Freshness: when ws+claim are provided, the summary's
       head_sha must equal the CURRENT ledger head — a legitimately
       minted all-clear summary replayed after new challenges landed
       fails here.
    """
    core = {k: v for k, v in summary_doc.items() if k != "hmac"}
    expect = hmac.new(
        key,
        json.dumps(core, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8"),
        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(summary_doc.get("hmac", ""), expect):
        return False
    if ws is not None and claim is not None:
        try:
            if summary_doc.get("head_sha") != current_head_sha(ws, claim):
                return False
        except OSError:
            return False
    return True
