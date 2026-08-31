# -*- coding: utf-8 -*-
"""verifier_identity.py — #825 verifier machine-identity extraction + anchor.

Identity carriers (issue #825 "or equivalent" for dispatch records):
  - verify-redteam-*.md          -> `verifier-identity: <tag>` header line
  - verify-<fid>-*.json          -> `l2.verifier_identity` field

anchor(): when the ->PROVEN gate accepts a redteam verdict, append one
verdict_anchor line to the workspace ledger (append-only, #584 line
contract, #831 style): (claim, source, identity, record_sha256). Post-hoc
authorship rebranding is detectable by comparing record_sha256.

Posture: fail-closed extraction (absence = None, gate decides); anchor
writes are audit-grade and never a block reason.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import time
from pathlib import Path

IDENT_MD_RE = re.compile(r"verifier-identity:\s*(\S+)", re.IGNORECASE)
LEDGER_NAME = ".convergence_ledger.jsonl"


def session_tag() -> str:
    """Machine tag for the authoring session (env id first, host fallback)."""
    env = os.environ.get("CLAUDE_SESSION_ID")
    if env:
        return env.strip()
    return (socket.gethostname() + "#" + str(os.getpid())
            + "#" + str(int(time.time())))


def extract_from_md(text: str) -> str | None:
    m = IDENT_MD_RE.search(text or "")
    return m.group(1).strip() if m else None


def extract_from_json(data: dict) -> str | None:
    l2 = (data or {}).get("l2") or {}
    v = str(l2.get("verifier_identity") or "").strip()
    return v or None


def anchors_for(ws: Path, claim_id: str) -> list:
    """All verdict_anchor ledger rows for a claim ([] on any read problem)."""
    p = Path(ws) / LEDGER_NAME
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (row.get("type") == "verdict_anchor"
                    and row.get("claim_id") == claim_id):
                out.append(row)
    except OSError:
        return []
    return out


def anchor(ws: Path, claim_id: str, source: str, identity: str) -> dict:
    """Append one verdict_anchor row (idempotent on (claim, source, sha))."""
    wsp = Path(ws)
    rec = wsp / "runs" / source
    digest = hashlib.sha256(rec.read_bytes()).hexdigest()
    for row in anchors_for(wsp, claim_id):
        if (row.get("source") == source
                and row.get("record_sha256") == digest):
            return row
    row = {"type": "verdict_anchor", "ts": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "claim_id": claim_id, "source": source,
        "verifier_identity": identity, "record_sha256": digest}
    p = wsp / LEDGER_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
