#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adversarial_loop — orchestrator-side process layer of #909.

The DATA layer (challenge_ledger.py) and the mechanical SIGNATURE gate
(adversarial_gate.py) are separate modules; this is the orchestrator's
CLI over them. Issue-909 phases (user rulings 2026-09-03):

  contest (rounds 1-5)   challenge <-> rebuttal advance round by round;
                         no per-round verdict — materials complete means
                         continue. Every write is grounded (evidence id +
                         command + assertion) or the ledger rejects it.
  stalemate (after 5)    open challenges at round 5 = stalemate; ONLY the
                         orchestrator arbitrates now (`arbitrate` refuses
                         earlier: EXIT_EARLY_ARBITRATION). outcome=rebutted
                         clears the open set; outcome=upheld leaves it
                         listed — the gate then BLOCKS (FAILED path).
  on-demand summons      `verify-run` executes ONE disputed falsifier
                         command (timeout-capped) and packages the finding
                         as a verifier_call event JSON on stdout, for the
                         orchestrator to file via `verifier-call`. Never a
                         blanket re-run: quadratic cost (#909 comment 1).

Key handling: --keyfile (default = review_gate key path, resolved via
expanduser at call time). The key is loaded once into process memory and
is NEVER printed — not in summaries, findings, or error paths; `status`
strips the summary hmac as well.

Exit codes (named-constant style, cf. convergence_health):
  0 ok · 1 CLI-level error (unreadable file, closed ledger, empty basis)
  2 InvalidEvent · 3 AssertionDrift · 4 RoundCapExceeded
  5 early arbitration refused (stalemate gate)

Writes only under <ws>/runs/challenges/<claim>/. stdlib +
challenge_ledger only; never imports hooks/lib_kunglao (twin ambiguity).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import challenge_ledger as cl

# review_gate precedent: the key lives ONLY in orchestrator process
# context; the default path is resolved via expanduser at call time.
DEFAULT_KEYFILE = "~/.claude/kunglao-review.key"
DEFAULT_FALSIFIER_TIMEOUT_SEC = 60.0  # one disputed command, not a sweep

EXIT_OK = 0
EXIT_ERROR = 1              # CLI-level: bad file, closed ledger, empty basis
EXIT_INVALID_EVENT = 2      # challenge_ledger.InvalidEvent
EXIT_ASSERTION_DRIFT = 3    # challenge_ledger.AssertionDrift
EXIT_ROUND_CAP = 4          # challenge_ledger.RoundCapExceeded
EXIT_EARLY_ARBITRATION = 5  # stalemate gate: arbitration before round 5

PREMATURE_REASON = "stalemate arbitration requires 5 rounds"

# subcommand -> event kind the ledger expects (append wrappers)
_APPEND_KINDS = {
    "challenge": "challenge",
    "rebuttal": "rebuttal",
    "verifier-call": "verifier_call",
}


def default_keyfile() -> str:
    return os.path.expanduser(DEFAULT_KEYFILE)


def load_key(keyfile: str) -> bytes:
    """Read the orchestrator HMAC key once. The bytes are NEVER logged or
    echoed — error paths name the keyfile path only."""
    path = Path(os.path.expanduser(keyfile))
    try:
        key = path.read_bytes().strip()
    except OSError as exc:
        print(f"keyfile unreadable: {path} ({exc})", file=sys.stderr)
        raise SystemExit(EXIT_ERROR) from None
    if not key:
        print(f"keyfile empty: {path}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR) from None
    return key


def _print_json(doc: dict) -> None:
    print(json.dumps(doc, ensure_ascii=False, indent=1))


def _bad_claim(claim: str) -> None:
    if not cl.CLAIM_RE.match(claim or ""):
        raise cl.InvalidEvent(f"bad claim id: {claim!r}")


def _read_event_file(path: str) -> dict:
    """Event JSON passed via file (shell-quoting hell avoided). Boundary
    validation: must read, must parse, must be a JSON object."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"event file unreadable: {path} ({exc})", file=sys.stderr)
        raise SystemExit(EXIT_ERROR) from None
    try:
        ev = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"event file is not valid JSON: {path} ({exc})", file=sys.stderr)
        raise SystemExit(EXIT_ERROR) from None
    if not isinstance(ev, dict):
        print(f"event file must contain a JSON object: {path}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR) from None
    return ev


def run_falsifier(cmd: str, *, timeout_sec: float) -> dict:
    """Execute ONE disputed falsifier command and package the finding.

    shell=True is BY DESIGN: the orchestrator summons a verifier to re-run
    a concrete disputed command; the finding (rc/stdout/stderr/timeout) is
    evidence either way — a failing falsifier is a finding, not an error.
    """
    t0 = time.monotonic()
    rc: int | None = None
    out: bytes = b""
    err: bytes = b""
    timed_out = False
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True,
                              timeout=timeout_sec)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = exc.stdout or b""
        err = exc.stderr or b""
    return {
        "cmd": cmd,
        "rc": rc,
        "stdout": out.decode("utf-8", errors="replace"),
        "stderr": err.decode("utf-8", errors="replace"),
        "timed_out": timed_out,
        "timeout_sec": timeout_sec,
        "duration_sec": round(time.monotonic() - t0, 3),
    }


def _has_arbitration(ws: Path, claim: str) -> bool:
    for rp in cl.rounds(ws, claim):
        try:
            doc = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for e in doc.get("events", []):
            if e.get("kind") == "arbitration":
                return True
    return False


def _split_basis(basis: str) -> list[str]:
    return [b.strip() for b in basis.split(",") if b.strip()]


def cmd_begin(args: argparse.Namespace, key: bytes) -> int:
    _bad_claim(args.claim)
    meta = Path(args.ws) / "runs" / "challenges" / args.claim / "meta.json"
    existed = meta.is_file()
    cl.begin_claim(Path(args.ws), args.claim,
                   assertion_text=args.assertion, key=key)
    _print_json({"ok": True, "claim": args.claim,
                 "assertion": "already frozen (write-once)" if existed
                 else "frozen (snapshot sha anchored to meta.json)"})
    return EXIT_OK


def cmd_append(args: argparse.Namespace, key: bytes) -> int:
    kind = _APPEND_KINDS[args.cmd]
    event = _read_event_file(args.file)
    if event.get("kind") != kind:
        print(f"event kind {event.get('kind')!r} does not match subcommand "
              f"{args.cmd!r} (expected {kind!r})", file=sys.stderr)
        return EXIT_ERROR
    ws = Path(args.ws)
    rp = cl.append_event(ws, args.claim, event, key=key)
    _print_json({"ok": True, "event": kind,
                 "round": len(cl.rounds(ws, args.claim)),
                 "round_file": str(rp)})
    return EXIT_OK


def cmd_status(args: argparse.Namespace, key: bytes) -> int:
    _bad_claim(args.claim)
    meta = Path(args.ws) / "runs" / "challenges" / args.claim / "meta.json"
    if not meta.is_file():
        _print_json({"claim": args.claim, "initialized": False,
                     "rounds": 0, "chain_ok": False, "open_challenges": []})
        return EXIT_ERROR
    s = cl.summary(Path(args.ws), args.claim, key=key)
    # NO hmac printed — key-derived material stays in process context
    _print_json({k: v for k, v in s.items() if k != "hmac"})
    return EXIT_OK


def cmd_arbitrate(args: argparse.Namespace, key: bytes) -> int:
    ws, claim = Path(args.ws), args.claim
    _bad_claim(claim)
    active = cl._read_active_round(ws, claim)
    if active < cl.MAX_ADVERSARIAL_ROUNDS:
        _print_json({"ok": False, "error": "premature arbitration",
                     "reason": PREMATURE_REASON,
                     "active_round": active,
                     "required_rounds": cl.MAX_ADVERSARIAL_ROUNDS})
        return EXIT_EARLY_ARBITRATION
    if _has_arbitration(ws, claim):
        print("arbitration already recorded (round_final) — ledger closed "
              "for this claim", file=sys.stderr)
        return EXIT_ERROR
    basis = _split_basis(args.basis)
    if not basis:
        print("arbitration basis must cite evidence ids (--basis CH-1,RB-1)",
              file=sys.stderr)
        return EXIT_ERROR
    event = {"kind": "arbitration", "round_final": True,
             "outcome": args.outcome, "basis": basis}
    try:
        rp = cl.append_event(ws, claim, event, key=key)
    except cl.RoundCapExceeded:
        # the cap exempts terminal arbitration; reaching here means the
        # active-round pointer is somehow past MAX — treat as closed
        print("ledger already closed or round pointer corrupt",
              file=sys.stderr)
        return EXIT_ERROR
    after = sorted(c.get("id", "?") for c in cl.open_challenges(ws, claim))
    _print_json({"ok": True, "outcome": args.outcome,
                 "round_file": str(rp), "open_challenges_after": after,
                 "note": "rebutted clears the open set; upheld leaves it "
                         "listed (gate blocks -> FAILED path)"})
    return EXIT_OK


def cmd_verify_run(args: argparse.Namespace, key: bytes) -> int:
    _bad_claim(args.claim)  # context sanity only — the ledger is untouched
    if not args.falsifier_cmd.strip():
        print("falsifier command is empty", file=sys.stderr)
        return EXIT_ERROR
    finding = run_falsifier(args.falsifier_cmd, timeout_sec=args.timeout)
    _print_json({"kind": "verifier_call",
                 "id": f"VC-{uuid.uuid4().hex[:8]}",
                 "ref": args.ref,
                 "verifier": "adversarial_loop.verify-run",
                 "finding": finding})
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="adversarial_loop.py",
        description="Orchestrator-side adversarial loop CLI (#909). "
                    "--keyfile must precede the subcommand.")
    p.add_argument("--keyfile", default=default_keyfile(),
                   help="orchestrator HMAC key file (review_gate precedent; "
                        "never printed)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("begin", help="freeze the assertion, open the ledger")
    sp.add_argument("ws")
    sp.add_argument("claim")
    sp.add_argument("--assertion", required=True,
                    help="claim assertion text, frozen at round 0")
    sp.set_defaults(fn=cmd_begin)

    for name, hlp in (("challenge", "file one grounded challenge event"),
                      ("rebuttal", "file one rebuttal answering a challenge"),
                      ("verifier-call",
                       "file one on-demand verifier_call event")):
        sp = sub.add_parser(name, help=hlp)
        sp.add_argument("ws")
        sp.add_argument("claim")
        sp.add_argument("--file", required=True,
                        help="event JSON file (one event object)")
        sp.set_defaults(fn=cmd_append)

    sp = sub.add_parser("status",
                        help="rounds count, open challenges, chain_ok")
    sp.add_argument("ws")
    sp.add_argument("claim")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("arbitrate",
                        help="terminal stalemate arbitration (round 5+ only)")
    sp.add_argument("ws")
    sp.add_argument("claim")
    sp.add_argument("--outcome", required=True,
                    choices=("upheld", "rebutted"))
    sp.add_argument("--basis", required=True,
                    help="comma-separated evidence ids, e.g. CH-1,RB-1")
    sp.set_defaults(fn=cmd_arbitrate)

    sp = sub.add_parser("verify-run",
                        help="run ONE disputed falsifier, package the finding")
    sp.add_argument("ws")
    sp.add_argument("claim")
    sp.add_argument("falsifier_cmd")
    sp.add_argument("--timeout", type=float,
                    default=DEFAULT_FALSIFIER_TIMEOUT_SEC)
    sp.add_argument("--ref", default="adhoc",
                    help="disputed event id, e.g. CH-1.falsifier")
    sp.set_defaults(fn=cmd_verify_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key = load_key(args.keyfile)
    try:
        return args.fn(args, key)
    except cl.InvalidEvent as exc:
        print(f"rejected (InvalidEvent): {exc}", file=sys.stderr)
        return EXIT_INVALID_EVENT
    except cl.AssertionDrift as exc:
        print(f"rejected (AssertionDrift): {exc}", file=sys.stderr)
        return EXIT_ASSERTION_DRIFT
    except cl.RoundCapExceeded as exc:
        print(f"rejected (RoundCapExceeded): {exc}", file=sys.stderr)
        return EXIT_ROUND_CAP


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
