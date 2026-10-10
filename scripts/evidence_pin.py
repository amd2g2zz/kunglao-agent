# -*- coding: utf-8 -*-
"""evidence_pin.py — sha-pin policy for checker-consumed evidence.

WHY: evidence/** was maker-writable (write_guard carriers cover only
facts/**.md, notes/**.md, claim-register.yaml, facts/_INDEX.md) while BOTH
checker faces consume evidence/replay-<claim>.json as ground truth (the
verifier gate in e2e checkpoints; convergence's replay-equivalence face via
scripts/replay_equivalence.py). A maker can pre-place or overwrite the
artifact a checker "verifies" against — the checker's byte-exact comparison
then certifies bytes the maker chose after the fact.

THE POLICY: a checker-consumed artifact is FROZEN at first consumption —
its sha256 is recorded here (runs/evidence-pins.json), and
hooks/evidence_pin_guard.py refuses every later write to that path (Write /
Edit / Bash mutations). Replacing a pinned artifact requires an EXPLICIT,
audited supersede: `unpin --reason <why>` (a blank reason refuses); the
typical reason is a new verification round. The engine pins at act-land and
unpins at act-launch (scripts/e2e/checkpoints.py helpers) so the freeze
never deadlocks a legitimate re-verification.

Commands:
  python3 scripts/evidence_pin.py <ws> pin   <relpath> [--by X] [--note Y]
  python3 scripts/evidence_pin.py <ws> check [--json]
  python3 scripts/evidence_pin.py <ws> unpin <relpath> --reason R [--by X]
  python3 scripts/evidence_pin.py <ws> list

Exit codes: 0 ok / 2 check violations / 3 refusal (blank reason, bad path).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

#: the evidence surface this policy covers — nothing else is pinnable.
EVIDENCE_REL = "evidence"

#: the pin store (machine channel: runs/).
PIN_FILE_REL = ("runs", "evidence-pins.json")

#: the surface-policy refusal when a caller tries to pin outside evidence/.
OUTSIDE_SURFACE_MSG = (
    "the evidence pin policy covers evidence/** only (got {rel!r}); "
    "facts/ and notes/ are write_guard carriers — pinning them here "
    "would duplicate a different contract")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_rel(relpath: str) -> str:
    """WS-relative posix path, normalized; refuses absolutes and elopement
    (a pin key always carries the workspace-relative identity)."""
    p = str(relpath or "").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    parts: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ValueError(f"pin path escapes the workspace: {relpath!r}")
        parts.append(seg)
    if not parts:
        raise ValueError("pin path is empty")
    return "/".join(parts)


def _pin_file(ws) -> Path:
    return Path(ws).joinpath(*PIN_FILE_REL)


def load_store(ws) -> dict:
    """The pin store document. Missing -> the empty shape; corrupt -> raise
    (corruption is NEVER read as absence — check() reports it loudly)."""
    p = _pin_file(ws)
    if not p.is_file():
        return {"version": 1, "pins": {}, "history": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"pin store corrupt: {p}: {exc}") from None
    if not isinstance(doc, dict):
        raise ValueError(f"pin store corrupt (not an object): {p}")
    doc.setdefault("version", 1)
    doc.setdefault("pins", {})
    doc.setdefault("history", [])
    if not isinstance(doc["pins"], dict):
        raise ValueError(f"pin store corrupt (pins is not an object): {p}")
    return doc


def _write_store(ws, doc: dict) -> None:
    p = _pin_file(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")


def pins_of(ws) -> dict:
    """{relpath: pin-row}; {} when the store is missing. A corrupt store
    raises — every caller decides its own posture (check() reports it)."""
    return dict(load_store(ws).get("pins") or {})


def pin(ws, relpath: str, *, by: str = "", note: str = "") -> dict:
    """Freeze `relpath` at its CURRENT bytes. The file must exist (a pin
    over nothing is a broken policy). Returns the pin row."""
    rel = normalize_rel(relpath)
    if not (rel == EVIDENCE_REL or rel.startswith(EVIDENCE_REL + "/")):
        raise ValueError(OUTSIDE_SURFACE_MSG.format(rel=rel))
    p = Path(ws) / rel
    if not p.is_file():
        raise FileNotFoundError(f"cannot pin a missing artifact: {rel}")
    row = {"sha256": sha256_file(p), "bytes": p.stat().st_size,
           "ts": _now(), "by": str(by or ""), "note": str(note or "")}
    doc = load_store(ws)
    doc["pins"][rel] = row
    doc.setdefault("history", []).append(
        {"ts": row["ts"], "action": "pin", "path": rel,
         "sha256": row["sha256"], "by": row["by"]})
    _write_store(ws, doc)
    return row


def unpin(ws, relpath: str, *, reason: str, by: str = "") -> dict:
    """Release a pin — the AUDITED supersede. A blank reason refuses
    (ValueError): an unexplained release is exactly the silent rewrite the
    policy exists to stop."""
    if not str(reason or "").strip():
        raise ValueError("unpin requires a non-blank reason (audited supersede)")
    rel = normalize_rel(relpath)
    doc = load_store(ws)
    row = doc["pins"].pop(rel, None)
    removed = row is not None
    doc.setdefault("history", []).append(
        {"ts": _now(), "action": "unpin", "path": rel,
         "sha256": (row or {}).get("sha256", ""),
         "reason": str(reason).strip(), "by": str(by or "")})
    _write_store(ws, doc)
    return {"removed": removed, "path": rel}


def check(ws) -> list[str]:
    """Violations for the whole store: a pinned artifact that is missing,
    or whose bytes no longer hash to its pin. A corrupt store is itself a
    violation (never a silent pass)."""
    try:
        doc = load_store(ws)
    except ValueError as exc:
        return [f"pin store corrupt: {exc}"]
    out: list[str] = []
    for rel, row in sorted((doc.get("pins") or {}).items()):
        p = Path(ws) / rel
        if not p.is_file():
            out.append(f"{rel}: pinned artifact missing (consumed by a "
                       f"checker at {row.get('ts', '?')})")
            continue
        cur = sha256_file(p)
        if cur != str(row.get("sha256") or ""):
            out.append(f"{rel}: pinned artifact changed after consumption "
                       f"(pin {str(row.get('sha256'))[:12]}… now "
                       f"{cur[:12]}…, pinned {row.get('ts', '?')} by "
                       f"{row.get('by') or '?'})")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="evidence sha-pin policy (#652): pin/check/unpin "
                    "checker-consumed artifacts under evidence/")
    parser.add_argument("workspace", help="workspace root")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pin = sub.add_parser("pin", help="freeze an artifact at its current bytes")
    p_pin.add_argument("relpath")
    p_pin.add_argument("--by", default="")
    p_pin.add_argument("--note", default="")

    p_check = sub.add_parser("check", help="verify every pin (exit 2 on violations)")
    p_check.add_argument("--json", action="store_true")

    p_unpin = sub.add_parser("unpin", help="audited supersede (reason required)")
    p_unpin.add_argument("relpath")
    p_unpin.add_argument("--reason", default="")
    p_unpin.add_argument("--by", default="")

    sub.add_parser("list", help="list current pins")

    args = parser.parse_args(argv)
    ws = Path(args.workspace)
    try:
        if args.cmd == "pin":
            row = pin(ws, args.relpath, by=args.by, note=args.note)
            print(f"pinned {normalize_rel(args.relpath)} sha256={row['sha256']}")
            return 0
        if args.cmd == "check":
            violations = check(ws)
            if args.json:
                print(json.dumps({"violations": violations}))
            elif violations:
                for v in violations:
                    print(f"VIOLATION: {v}")
            else:
                print("OK: every pinned artifact matches its consumed bytes")
            return 2 if violations else 0
        if args.cmd == "unpin":
            res = unpin(ws, args.relpath, reason=args.reason, by=args.by)
            state = "released" if res["removed"] else "was not pinned"
            print(f"unpin {res['path']}: {state} (reason: {args.reason})")
            return 0
        if args.cmd == "list":
            pins = pins_of(ws)
            for rel, row in sorted(pins.items()):
                print(f"{rel}  sha256={row.get('sha256')}  pinned={row.get('ts')}  "
                      f"by={row.get('by') or '-'}")
            if not pins:
                print("(no pins)")
            return 0
    except FileNotFoundError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    return 3


if __name__ == "__main__":
    sys.exit(main())
