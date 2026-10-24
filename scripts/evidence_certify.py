#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evidence_certify.py — the evidence-chain certification face (issue 803).

THE INVERSION: certification ranked process conformance above evidence
strength. In the production workspace a lane=web SCAFFOLD claim with no
evidence class rode a full blind red-team to PROVEN, while F009 — a
byte-exact recovery (GeeTest v4 ``w`` parameter reproduced 528/528
replay pairs, production-oracle accepted, fresh-input verified after
CONFIRMED sign-off) — sat at INFERRED / verified:false waiting on a
dispatch-cycle formality. The evidence body itself lived off-ledger
(transcribed into prose) and its identity chain was broken (trace
93/7108: the artifact a checker "verified" could not be re-identified).

THE FACE: certification = a REPLAYABLE DECLARATION. One evidence row —

    evidence/cert-<claim>.json  (schema ``evidence-cert/1``)

carries the minimal instructions for re-verifying it: the byte-exact leg
(an existing ``replay-equivalence/1`` artifact, validated by
replay_equivalence's own oracle), the fresh-input leg (a
``fresh-input/1`` acceptance artifact — every recorded input accepted),
and a replay command whose stdout is PINNED at mint time. ``replay``
re-executes the command and byte-compares: the pin is
certify -> replay -> result consistent, on synthetic fixtures as in
production. Artifact identity is carried IN the row (sha256 per leg) —
an artifact rewritten after the mint breaks the chain and refuses.

CONSUMED, NOT REBUILT (the foundations this face rides):
  - replay_equivalence      the byte-exact oracle (artifact validity +
                            matched pairs) — issue 652's artifact grammar
  - rlvr/learning_seal      the #799 HMAC face: the row is sealed at
                            mint (armed) and the seal verified fail-closed
  - verifier_integrity      #809: the row carries ``verdict: passed`` so
                            it RESOLVES as a PASSED verification record —
                            claims_store.apply's settle_proven face cites
                            it with zero new semantics

PROMOTION (issue 803, in register_proven_gate): eligibility reads
EVIDENCE CLASS first. A replay-consistent certification admits ->PROVEN
without another dispatch cycle; red-team sample-verification stays
available on suspicion, never as a toll. And the inversion's other end
is pinned dead: a ``claim_class: scaffold`` claim with no evidence class
can no longer reach PROVEN via red-team alone.

Also the single source of the WEB lane's native evidence sources —
capture / replay / fresh-input / offline-execution — the lint face's
web frontmatter contract consumes (issue 803 pin 3).

Commands:
  python3 scripts/evidence_certify.py mint   <ws> <claim> --byte-exact P \
      --fresh-input P --command CMD
  python3 scripts/evidence_certify.py replay <ws> <claim>
  python3 scripts/evidence_certify.py show   <ws> <claim>

Exit codes: 0 ok / 2 refusal (mint/replay refused — the reason is on
stderr, loud).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import replay_equivalence

#: the certification row schema
CERT_SCHEMA = "evidence-cert/1"

#: THE evidence class the promotion gate admits on (the F009 shape):
#: byte-exact reproduction + fresh-input server acceptance
CERT_CLASS = "byte-exact+fresh-input"

#: the web lane's native evidence sources (issue 803 pin 3) — the lint
#: face's web frontmatter contract imports this tuple; ONE registration
WEB_SOURCE_ENUM: tuple[str, ...] = (
    "capture", "replay", "fresh-input", "offline-execution")

#: the fresh-input leg's artifact schema
FRESH_SCHEMA = "fresh-input/1"

#: replay execution bounds (a replay is a verification act, not a run)
REPLAY_TIMEOUT_S = 60


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cert_path(ws, claim: str) -> Path:
    """The claim's certification row surface."""
    return Path(ws) / "evidence" / f"cert-{claim}.json"


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_ws_path(ws: Path, rel: str) -> Path | None:
    """Workspace-containment guard (the verifier_integrity shape): the
    resolved path must stay inside the workspace. None = outside."""
    try:
        ws_root = Path(ws).resolve()
        resolved = (ws_root / rel).resolve()
        if resolved == ws_root or ws_root not in resolved.parents:
            return None
        return resolved
    except (OSError, ValueError):
        return None


def read_certification(ws, claim: str) -> dict | None:
    """The parsed certification row, or None. Corrupt reads as absent —
    with ONE loud canonical warn (a broken certification must never read
    as a valid one, and must never read as silence either)."""
    p = cert_path(ws, claim)
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        from kunglao_log import warn
        warn("evidence_certify", f"cert-{claim}.json corrupt "
             f"({type(exc).__name__}: {exc}) — reads as absent")
        return None
    return doc if isinstance(doc, dict) else None


# ------------------------------------------------------------ mint face

def _validate_byte_exact(ws: Path, rel: str,
                         claim: str) -> tuple[dict | None, str]:
    """The byte-exact leg: an existing, valid replay-equivalence/1
    artifact bound to THIS claim with >= 1 matched pair
    (replay_equivalence owns the grammar — consumed, not rebuilt)."""
    p = _safe_ws_path(ws, rel)
    if p is None or not p.is_file():
        return None, f"byte-exact artifact missing or outside ws: {rel}"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, f"byte-exact artifact unparseable: {exc}"
    errors = replay_equivalence.artifact_errors(doc)
    if errors:
        return None, ("byte-exact artifact invalid: "
                      + "; ".join(errors[:3]))
    if int(replay_equivalence.matched_pairs(doc)) < 1:
        return None, "byte-exact artifact carries no matched pair"
    if str(doc.get("claim_id") or "") != claim:
        return None, (f"byte-exact artifact claim_id "
                      f"{doc.get('claim_id')!r} != {claim!r} — evidence "
                      "for one claim never certifies another")
    return doc, ""


def _validate_fresh_input(ws: Path, rel: str,
                          claim: str) -> tuple[dict | None, str]:
    """The fresh-input leg: an existing fresh-input/1 artifact bound to
    THIS claim whose every recorded input is ACCEPTED (the acceptance
    is the point — a rejected fresh input is not server acceptance)."""
    p = _safe_ws_path(ws, rel)
    if p is None or not p.is_file():
        return None, f"fresh-input artifact missing or outside ws: {rel}"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, f"fresh-input artifact unparseable: {exc}"
    if not isinstance(doc, dict) or doc.get("schema") != FRESH_SCHEMA:
        return None, f"fresh-input artifact schema must be {FRESH_SCHEMA!r}"
    if str(doc.get("claim_id") or "") != claim:
        return None, (f"fresh-input artifact claim_id "
                      f"{doc.get('claim_id')!r} != {claim!r} — evidence "
                      "for one claim never certifies another")
    inputs = doc.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        return None, "fresh-input artifact carries no input rows"
    for i, row in enumerate(inputs):
        if not isinstance(row, dict) or not str(row.get("input_id") or "").strip():
            return None, f"fresh-input inputs[{i}]: needs input_id"
        if row.get("accepted") is not True:
            return None, (f"fresh-input inputs[{i}] "
                          f"({row.get('input_id')}): not accepted — "
                          "a rejected fresh input is not server acceptance")
    return doc, ""


def _validate_command(ws: Path, command: str) -> tuple[list | None, str]:
    """The replay instruction: an argv line executed with cwd=ws, so
    every path-shaped token (contains a separator) is a
    workspace-relative reference. At least one such token must resolve
    to an existing in-workspace file — the replay anchor (the
    recompute-script convention); an unresolvable anchor refuses."""
    try:
        argv = shlex.split(str(command or ""))
    except ValueError as exc:
        return None, f"replay command unparseable: {exc}"
    if not argv:
        return None, "replay command is empty"
    pathish = [a for a in argv if "/" in a or a.endswith((".py", ".json"))]
    if not pathish:
        return None, ("replay command carries no workspace-relative "
                      "reference — no replay anchor")
    for tok in pathish:
        anchor = _safe_ws_path(ws, tok)
        if anchor is None or not anchor.is_file():
            return None, (f"replay command anchor {tok!r} is not an "
                          "existing workspace-relative file")
    return argv, ""


def _execute(ws: Path, argv: list) -> tuple[bytes | None, str]:
    """Run the replay command (cwd=ws). Returns (stdout bytes, error)."""
    try:
        proc = subprocess.run(
            argv, cwd=str(Path(ws)), capture_output=True,
            timeout=REPLAY_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"replay command failed: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace").strip()[-200:]
        return None, f"replay command rc={proc.returncode}: {tail}"
    return proc.stdout, ""


def mint(ws, claim: str, *, byte_exact_artifact: str,
         fresh_input_artifact: str, command: str,
         verdict: str = "passed") -> dict:
    """Certify the claim's evidence chain: validate both legs, execute
    the replay once to pin the expected output sha, seal the row
    (#799 face — armed) and land it atomically. Fail-closed: any leg
    refusal lands nothing."""
    ws = Path(ws)
    claim = str(claim or "").strip()
    if not claim:
        return {"ok": False, "error": "claim id required"}
    p = cert_path(ws, claim)
    if p.exists():
        return {"ok": False,
                "error": f"{p.name} already exists — a certification is "
                         "immutable evidence; a new verification round "
                         "supersedes via the audit, not an overwrite"}
    be_doc, be_err = _validate_byte_exact(ws, byte_exact_artifact, claim)
    if be_doc is None:
        return {"ok": False, "error": be_err}
    fi_doc, fi_err = _validate_fresh_input(ws, fresh_input_artifact, claim)
    if fi_doc is None:
        return {"ok": False, "error": fi_err}
    argv, cmd_err = _validate_command(ws, command)
    if argv is None:
        return {"ok": False, "error": cmd_err}
    out, exec_err = _execute(ws, argv)
    if out is None:
        return {"ok": False, "error": exec_err}
    be_rel = str(byte_exact_artifact)
    fi_rel = str(fresh_input_artifact)
    row = {
        "schema": CERT_SCHEMA,
        "claim_id": claim,
        "evidence_class": CERT_CLASS,
        "verdict": str(verdict or "passed").strip().lower(),
        "byte_exact": {
            "artifact": be_rel,
            "sha256": _sha256_file(ws / be_rel),
            "matched_pairs": replay_equivalence.matched_pairs(be_doc),
        },
        "fresh_input": {
            "artifact": fi_rel,
            "sha256": _sha256_file(ws / fi_rel),
            "inputs": len(fi_doc.get("inputs") or []),
        },
        "replay": {
            "command": command,
            "expect_sha256": hashlib.sha256(out).hexdigest(),
        },
        "minted": _now(),
    }
    import rlvr.learning_seal as seal
    row = seal.sign_row(row)  # armed -> additive seal; unarmed rides
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(row, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        return {"ok": False, "error": f"cert row write failed: {exc}"}
    try:
        from kunglao_log import emit
        emit(ws, actor="evidence_certify", action="evidence_certified",
             claim=claim,
             detail=json.dumps(
                 {"evidence_class": CERT_CLASS,
                  "byte_exact": be_rel,
                  "fresh_input": fi_rel,
                  "expect_sha256": row["replay"]["expect_sha256"],
                  "sealed": "seal" in row},
                 sort_keys=True, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — telemetry, never the mint
        from kunglao_log import warn
        warn("evidence_certify", f"cert emit failed: "
             f"{type(exc).__name__}: {exc}")
    return {"ok": True, "path": str(p), "row": row}


# ---------------------------------------------------------- replay face

def replay(ws, claim: str) -> tuple[bool, str]:
    """Re-execute the row's own replay instruction and byte-compare the
    output against the pinned sha. The pin: certification line ->
    replay -> result consistent. Fail-closed on every miss."""
    ws = Path(ws)
    claim = str(claim or "").strip()
    row = read_certification(ws, claim)
    if row is None:
        return False, f"no certification row for {claim}"
    if row.get("schema") != CERT_SCHEMA:
        return False, f"schema {row.get('schema')!r} is not {CERT_SCHEMA!r}"
    import rlvr.learning_seal as seal
    if seal.armed():
        ok, why = seal.verify_row(row)
        if not ok:
            return False, f"seal refused: {why}"
    rep = row.get("replay")
    if not isinstance(rep, dict) or not str(rep.get("command") or "").strip():
        return False, "row carries no replay instruction"
    argv, cmd_err = _validate_command(ws, rep["command"])
    if argv is None:
        return False, cmd_err
    out, exec_err = _execute(ws, argv)
    if out is None:
        return False, exec_err
    got = hashlib.sha256(out).hexdigest()
    expect = str(rep.get("expect_sha256") or "")
    if got != expect:
        return False, (f"replay output sha mismatch (pinned {expect[:12]}…, "
                       f"got {got[:12]}…) — the certification does not "
                       "replay to its own result")
    # the certify->replay->result pin, OBSERVED (issue 803 liveness):
    # one registered word per replay act; a refusal rides the boolean +
    # caller telemetry, never a fabricated pass row
    try:
        from kunglao_log import emit
        emit(ws, actor="evidence_certify", action="evidence_replayed",
             claim=claim,
             detail=json.dumps(
                 {"expect_sha256": expect, "got_sha256": got,
                  "byte_consistent": True},
                 sort_keys=True, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — telemetry, never the verdict
        from kunglao_log import warn
        warn("evidence_certify", f"replay emit failed: "
             f"{type(exc).__name__}: {exc}")
    return True, "replay byte-consistent with the pinned result"


def admission(ws, claim: str) -> tuple[bool, str]:
    """The promotion-gate predicate (register_proven_gate consumes this,
    issue 803): a certification of the F009 evidence class whose
    artifacts still carry their minted identity and whose replay is
    byte-consistent. Fail-closed: any miss is a named refusal."""
    ws = Path(ws)
    claim = str(claim or "").strip()
    row = read_certification(ws, claim)
    if row is None:
        return False, "no certification row"
    if row.get("schema") != CERT_SCHEMA:
        return False, f"schema {row.get('schema')!r} is not {CERT_SCHEMA!r}"
    if str(row.get("evidence_class") or "") != CERT_CLASS:
        return False, (f"evidence_class {row.get('evidence_class')!r} is "
                       f"not the PROVEN-eligible class {CERT_CLASS!r}")
    if str(row.get("claim_id") or "") != claim:
        return False, "row claim_id mismatch"
    for leg in ("byte_exact", "fresh_input"):
        block = row.get(leg)
        if not isinstance(block, dict):
            return False, f"{leg} leg missing from the row"
        rel = str(block.get("artifact") or "")
        p = _safe_ws_path(ws, rel)
        if p is None or not p.is_file():
            return False, f"{leg} artifact {rel!r} missing or outside ws"
        pinned = str(block.get("sha256") or "")
        if not pinned or _sha256_file(p) != pinned:
            return False, (f"{leg} artifact identity broken — {rel!r} was "
                           "rewritten after the mint (trace 93/7108 face)")
    return replay(ws, claim)


# --------------------------------------------------------------- CLI ---

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3:
        print("usage: evidence_certify.py mint|replay|show <ws> <claim> "
              "[--byte-exact P --fresh-input P --command CMD]", file=sys.stderr)
        return 2
    cmd, ws, claim = argv[0], argv[1], argv[2]
    if cmd == "mint":
        rest = argv[3:]
        opts = {}
        for flag, key in (("--byte-exact", "byte_exact_artifact"),
                          ("--fresh-input", "fresh_input_artifact"),
                          ("--command", "command")):
            if flag in rest:
                i = rest.index(flag)
                if i + 1 >= len(rest):
                    print(f"mint REFUSED: {flag} needs a value", file=sys.stderr)
                    return 2
                opts[key] = rest[i + 1]
        if len(opts) != 3:
            print("mint REFUSED: need --byte-exact, --fresh-input and "
                  "--command", file=sys.stderr)
            return 2
        res = mint(ws, claim, **opts)
        if res.get("ok"):
            print(f"cert OK: {res['path']}")
            return 0
        print(f"mint REFUSED: {res.get('error')}", file=sys.stderr)
        return 2
    if cmd == "replay":
        ok, detail = replay(ws, claim)
        print(f"replay {'CONSISTENT' if ok else 'REFUSED'}: {detail}")
        return 0 if ok else 2
    if cmd == "show":
        row = read_certification(ws, claim)
        if row is None:
            print(f"no certification row for {claim}", file=sys.stderr)
            return 2
        print(json.dumps(row, indent=2, ensure_ascii=False))
        return 0
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
