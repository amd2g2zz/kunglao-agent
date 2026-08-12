"""Promotion gate + rule-set registry for kunglao-agent memory (issue #82).

Five mandatory conditions (ALL must hold before a candidate becomes a
production rule):

  1. Complete evaluator receipt — schema valid, receipt_digest recomputes,
     and no non-evidence value is claimed as PASS (forged receipts rejected).
  2. Held-out gain — held-out correctness over the baseline receipt
     >= HELD_OUT_GAIN_MIN (0.10).
  3. Safety no-regression — overclaims/invalid_work dims pass on every
     candidate trial, and the rule body carries no harmful directive
     (evidence destruction / direct production writes).
  4. Source-hash lineage — candidate content hash matches the journaled
     `generated` digest; snapshot bytes and surviving staging entries
     hash-match the recorded source hashes.
  5. Independent score — scores are read ONLY from evaluator receipts
     (evaluator module bytes pinned in digests.code).

Rejected candidates are terminal (journal `rejected` row; re-promotion needs
a new generation). Rollback restores the EXACT prior rule set (byte backup +
digest verification) and records action/reason/digests in
memory/lifecycle-journal.jsonl (acceptance d: promotion-and-rollback drill).

Usage:
  python promote.py promote <candidate-id> --reason "..."
  python promote.py rollback --to <promotion-id> --reason "..."
  python promote.py retire <rule-file> --reason "..."
  python promote.py registry
  python promote.py status <candidate-id>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import distill
import evaluate as ev

HELD_OUT_GAIN_MIN = distill.HELD_OUT_GAIN_MIN

# aliases (read module attrs at call time -> monkeypatch-safe)
journal_rows = distill.journal_rows
load_registry = distill.load_registry


def _is_expired(candidate_id: str) -> bool:
    return any(r.get("action") == "expired" for r in journal_rows(candidate_id))


def _load_receipts(candidate_id: str) -> list:
    out: list = []
    if not distill.RECEIPTS_DIR.exists():
        return out
    for p in sorted(distill.RECEIPTS_DIR.glob(f"receipt-{candidate_id}-*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def _receipt_files(candidate_id: str) -> list:
    if not distill.RECEIPTS_DIR.exists():
        return []
    return sorted(distill.RECEIPTS_DIR.glob(f"receipt-{candidate_id}-*.json"))


def _is_forged(rec: dict) -> bool:
    """D6: digest recompute / evaluator code digest / non-evidence claiming PASS."""
    claimed = rec.get("receipt_digest")
    if not isinstance(claimed, str) or len(claimed) != 64:
        return True
    if ev.recompute_and_set_digest(rec) != claimed:
        return True
    if rec.get("digests", {}).get("code") != distill._sha(Path(ev.__file__).read_bytes()):
        return True
    if (rec.get("oracle") or {}).get("overall") == "PASS" and rec.get("non_evidence") is True:
        return True
    return False


def _lineage_ok(candidate_id: str) -> bool:
    """D4 condition 4: content hash + snapshot bytes + surviving staging entries."""
    try:
        path, fm, _ = distill.load_candidate(candidate_id)
    except (OSError, ValueError):
        return False
    meta = fm.get("metadata") or {}
    rows = journal_rows(candidate_id)
    gen = next((r for r in rows if r.get("action") == "generated"), None)
    if gen is None or gen.get("digests", {}).get("content") != distill._file_sha256(path):
        return False  # record mutated since generation
    hashes = meta.get("source_hashes") or {}
    snap_ref = meta.get("snapshot_ref")
    for name, expected in hashes.items():
        snap = distill.STAGING_DIR / ".snapshot" / snap_ref / name if snap_ref else None
        if snap is not None:
            if not snap.exists() or distill._file_sha256(snap) != expected:
                return False  # snapshot changed / missing since generation
        live = distill.STAGING_DIR / name
        if live.exists() and distill._file_sha256(live) != expected:
            return False  # staging entry changed since snapshot
    return True


def _safety_violation(candidate_id: str, receipts: list) -> str | None:
    """D4 condition 3: body-scan invariants + episode overclaims/invalid_work."""
    try:
        _, _, body = distill.load_candidate(candidate_id)
    except (OSError, ValueError):
        return "candidate unreadable"
    low = body.lower()
    for pat in distill.HARMFUL_PATTERNS:
        if pat.lower() in low:
            return f"body contains harmful directive: {pat!r}"
    for rec in receipts:
        if rec.get("split") == "baseline-held-out":
            continue  # baseline is the reference, not the subject
        dims = (rec.get("oracle") or {}).get("dimensions") or {}
        for inv in ("overclaims", "invalid_work"):
            d = dims.get(inv)
            if isinstance(d, dict) and d.get("pass") is False:
                return f"invariant {inv} failed on {rec.get('case_id')} ({rec.get('split')})"
    return None


def check_gate(candidate_id: str) -> tuple[bool, str | None]:
    """(promotable, failure_reason). Pure read — never mutates registry/journal."""
    rows = journal_rows(candidate_id)
    if not any(r.get("action") == "generated" for r in rows):
        return False, "no-generated-row"
    if not any(r.get("action") == "evaluated" for r in rows):
        return False, "no-receipt"
    if _is_expired(candidate_id):
        return False, "expired"
    receipts = _load_receipts(candidate_id)
    if not receipts:
        return False, "no-receipt"
    # 1 + 5: complete receipt + independent score (forged detection)
    for rec in receipts:
        if _is_forged(rec):
            return False, "forged-receipt"
    # 4: source-hash lineage
    if not _lineage_ok(candidate_id):
        return False, "stale"
    # 3: safety no-regression
    harm = _safety_violation(candidate_id, receipts)
    if harm:
        return False, "harmful"
    # 2: held-out gain over baseline
    scores = ev.recompute_scores(receipts)
    if scores["gain"] < HELD_OUT_GAIN_MIN:
        return False, "overfit"
    return True, None


# ----------------------------- rule set helpers -----------------------------

def _longterm_entries() -> dict:
    """{name: sha256} over all top-level longterm md files (incl INDEX.md)."""
    out: dict = {}
    if distill.LONGTERM_DIR.exists():
        for p in sorted(distill.LONGTERM_DIR.glob("*.md")):
            out[p.name] = distill._file_sha256(p)
    return out


def _current_rule_set_digest() -> str:
    return distill._sha(_longterm_entries())


def _init_registry() -> dict:
    reg = load_registry()
    if not distill.REGISTRY_PATH.exists():
        distill.save_registry(reg)
    return reg


def _snapshot_current_rules(snap_id: str) -> tuple[dict, str, Path]:
    """Byte-copy the current longterm set to rules-backup/<snap_id>/ (last-known-good)."""
    backup = distill.BACKUP_DIR / snap_id
    backup.mkdir(parents=True, exist_ok=True)
    if distill.LONGTERM_DIR.exists():
        for p in distill.LONGTERM_DIR.glob("*.md"):
            shutil.copy2(p, backup / p.name)
    entries = _longterm_entries()
    return entries, distill._sha(entries), backup


def _write_rule_file(candidate_id: str, cand_path: Path) -> Path:
    distill.LONGTERM_DIR.mkdir(parents=True, exist_ok=True)
    date_part = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    text = cand_path.read_text(encoding="utf-8").replace("status: CANDIDATE", "status: PROMOTED")
    n = len(list(distill.LONGTERM_DIR.glob(f"{date_part}-rule-*.md"))) + 1
    out = distill.LONGTERM_DIR / f"{date_part}-rule-{candidate_id[:8]}-{n}.md"
    out.write_text(text, encoding="utf-8")
    idx = distill.LONGTERM_DIR / "INDEX.md"
    if not idx.exists():
        idx.write_text("# Longterm memory index\n\n", encoding="utf-8")
    with idx.open("a", encoding="utf-8") as f:
        f.write(f"- {out.name}: promoted from {candidate_id}\n")
    return out


# ----------------------------- promote / rollback / retire -----------------------------

def promote(candidate_id: str, reason: str) -> bool:
    ok, why = check_gate(candidate_id)
    if not ok:
        print(f"REJECT: {candidate_id} gate failed: {why}")
        return False
    path, fm, _ = distill.load_candidate(candidate_id)
    discipline = ((fm.get("metadata") or {}).get("evaluation") or {}).get("discipline") or "naive"
    rule_file: Path | None = None
    try:
        pre_entries, pre_digest, backup_dir = _snapshot_current_rules(candidate_id)
        rule_file = _write_rule_file(candidate_id, path)
        post_entries = _longterm_entries()
        post_digest = distill._sha(post_entries)
        reg = load_registry()
        snap_id = candidate_id
        reg.setdefault("snapshots", {})[snap_id] = {
            "entries": pre_entries, "rule_set_digest": pre_digest,
            "backup_dir": str(backup_dir), "promoted_at": distill.utc_now(),
            "candidate_id": candidate_id, "discipline": discipline,
        }
        reg["current"] = {
            "id": snap_id, "candidate_id": candidate_id, "discipline": discipline,
            "entries": post_entries, "rule_set_digest": post_digest,
            "promoted_at": distill.utc_now(),
            "receipt_ref": [str(p) for p in _receipt_files(candidate_id)],
        }
        reg.setdefault("history", []).append({
            "action": "promoted", "candidate_id": candidate_id, "reason": reason,
            "rule_set_digest": post_digest, "ts": distill.utc_now()})
        distill.save_registry(reg)
        distill.journal_append({
            "ts": distill.utc_now(), "action": "promoted", "candidate_id": candidate_id,
            "reason": reason,
            "receipt_ref": [str(p) for p in _receipt_files(candidate_id)],
            "digests": {"content": distill._file_sha256(path), "rule_set": post_digest},
            "discipline": discipline,
        })
        print(f"PROMOTED: {candidate_id} -> longterm/{rule_file.name} (rule set {post_digest[:12]})")
        return True
    except Exception as exc:
        print(f"FAIL: promotion aborted: {exc}")
        if rule_file is not None and rule_file.exists():
            rule_file.unlink()  # rollback-of-write: registry untouched
            print(f"     rolled back rule file: {rule_file.name}")
        return False


def rollback(to_id: str, reason: str) -> bool:
    """Restore the EXACT rule set of snapshot <to_id>; verify byte-for-byte."""
    reg = load_registry()
    target = reg.get("snapshots", {}).get(to_id)
    if target is None:
        print(f"FAIL: no snapshot for {to_id}")
        return False
    backup = Path(target["backup_dir"])
    restored: dict = {}
    current_entries = _longterm_entries()
    # remove files not in the target set (the promoted rule)
    for name in list(current_entries):
        if name not in target["entries"]:
            p = distill.LONGTERM_DIR / name
            if p.exists():
                before = distill._file_sha256(p)
                p.unlink()
                restored[name] = {"before": before, "after": None, "ok": True}
    # restore differing / missing files from the byte backup
    for name, expected in target["entries"].items():
        p = distill.LONGTERM_DIR / name
        if p.exists() and distill._file_sha256(p) == expected:
            continue
        backup_file = backup / name
        if not backup_file.exists():
            return False  # cannot restore exactly -> fail closed, nothing recorded
        before = distill._file_sha256(p) if p.exists() else None
        shutil.copy2(backup_file, p)
        after = distill._file_sha256(p)
        restored[name] = {"before": before, "after": after, "ok": after == expected}
        if after != expected:
            return False
    final_entries = _longterm_entries()
    final_digest = distill._sha(final_entries)
    if final_entries != target["entries"]:
        print(f"FAIL: restored set digest mismatch (expected {target['rule_set_digest'][:12]}, "
              f"got {final_digest[:12]})")
        return False
    reg["current"] = {"id": to_id, "candidate_id": target.get("candidate_id"),
                      "discipline": target.get("discipline", "naive"),
                      "entries": final_entries, "rule_set_digest": final_digest,
                      "promoted_at": target.get("promoted_at"), "receipt_ref": None}
    reg.setdefault("history", []).append({
        "action": "rolled_back", "to": to_id, "reason": reason,
        "rule_set_digest": final_digest, "ts": distill.utc_now()})
    distill.save_registry(reg)
    distill.journal_append({
        "ts": distill.utc_now(), "action": "rolled_back", "candidate_id": target.get("candidate_id"),
        "reason": reason, "to": to_id, "receipt_ref": None,
        "digests": {"restored": restored, "rule_set": final_digest},
    })
    print(f"ROLLED_BACK: restored exact rule set {final_digest[:12]} from snapshot {to_id}")
    return True


def retire(name: str, reason: str) -> bool:
    """Explicit retirement: archive the rule + record reason/digest (distinct from decay)."""
    p = distill.LONGTERM_DIR / name
    if not p.exists():
        print(f"FAIL: no such rule: {name}")
        return False
    archive = distill.LONGTERM_DIR / ".archived"
    archive.mkdir(parents=True, exist_ok=True)
    content_hash = distill._file_sha256(p)
    shutil.move(str(p), str(archive / name))
    reg = load_registry()
    cur = reg.get("current")
    if cur is not None:
        entries = {k: v for k, v in (cur.get("entries") or {}).items() if k != name}
        cur["entries"] = entries
        cur["rule_set_digest"] = distill._sha(entries)
        cur["retired"] = name
        distill.save_registry(reg)
    distill.journal_append({
        "ts": distill.utc_now(), "action": "retired", "candidate_id": None,
        "reason": reason, "name": name, "receipt_ref": None,
        "digests": {"content": content_hash},
    })
    print(f"RETIRED: {name} ({reason})")
    return True


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="promote.py", description="candidate promotion gate")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("promote", help="promote a candidate to a production rule")
    p.add_argument("candidate_id")
    p.add_argument("--reason", required=True)
    r = sub.add_parser("rollback", help="restore an exact prior rule set")
    r.add_argument("--to", required=True)
    r.add_argument("--reason", required=True)
    t = sub.add_parser("retire", help="retire a promoted rule")
    t.add_argument("name")
    t.add_argument("--reason", required=True)
    sub.add_parser("registry", help="print current rule set + history")
    st = sub.add_parser("status", help="gate status for a candidate")
    st.add_argument("candidate_id")
    args = ap.parse_args(argv)
    if args.cmd == "promote":
        return 0 if promote(args.candidate_id, args.reason) else 1
    if args.cmd == "rollback":
        return 0 if rollback(args.to, args.reason) else 1
    if args.cmd == "retire":
        return 0 if retire(args.name, args.reason) else 1
    if args.cmd == "registry":
        print(json.dumps(load_registry(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "status":
        ok, why = check_gate(args.candidate_id)
        print(f"promotable={ok}" + (f" reason={why}" if why else ""))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
