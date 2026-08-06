"""F4 — Forgetting mechanism: decay, archive, prune.

Three sub-mechanisms:

1. **Recency decay** — for each longterm entry, if (now - last_cited) > 30 days
   AND citations < 2, reduce confidence by 0.1. If confidence drops below 0.3,
   archive to .archived/. (Ebbinghaus-style selective retention.)

2. **Supersession marking** — newer entry that explicitly cites an older one
   via `## Supersedes: <older-name>` reduces the older's confidence to 0.4
   and sets `superseded_by` in metadata. (Caller responsibility: distill.py
   step 4 writes the new entry; this script applies the consequence.)

3. **Explicit prune** — walk longterm/, archive anything with confidence < 0.3
   OR superseded_by set OR no citations in 60 days. (User-invoked via
   /memory-prune OR run by SessionEnd hook.)

What forgetting does NOT do:
  - Never delete an entry. Archive to .archived/ keeps the audit trail.
  - Never lower confidence below MIN_CONFIDENCE_FLOOR unless supersession
    explicitly forces it.

Usage:
  python forget.py decay          # step 1: gentle decay for all entries
  python forget.py supersede NEWER OLDER  # step 2: mark OLDER superseded by NEWER
  python forget.py prune          # step 3: explicit archive pass
  python forget.py --dry-run decay # show what would change, no writes
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
LONGTERM_DIR = SCRIPT_DIR.parent / "longterm"
ARCHIVE_DIR = LONGTERM_DIR / ".archived"


def _archive_dir() -> Path:
    """Derived at call time so test-swap of LONGTERM_DIR propagates."""
    return LONGTERM_DIR / ".archived"

MIN_CONFIDENCE_FLOOR = 0.3
DECAY_RATE = 0.1
DECAY_THRESHOLD_DAYS = 30
DECAY_MIN_CITATIONS = 2
PRUNE_NO_CITATION_DAYS = 60
SUPERSEDE_CONFIDENCE = 0.4
DECAY_RATE = 0.1
DECAY_THRESHOLD_DAYS = 30
DECAY_MIN_CITATIONS = 2
PRUNE_NO_CITATION_DAYS = 60
SUPERSEDE_CONFIDENCE = 0.4


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _read_frontmatter(path: Path) -> tuple:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text, -1
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text, -1
    try:
        fm = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}, text, -1
    body = text[end + 4:]
    return fm, body, end


def _write_frontmatter(path: Path, fm: dict, body: str) -> None:
    yaml_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{yaml_text}---{body}", encoding="utf-8")


def _archive(path: Path) -> Path:
    dest_dir = _archive_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), str(dest))
    return dest


def decay(dry_run: bool = False) -> list:
    changes = []
    now = utc_now()
    for p in LONGTERM_DIR.glob("*.md"):
        fm, body, _ = _read_frontmatter(p)
        if not fm:
            continue
        meta = fm.get("metadata") or {}
        if "superseded_by" in meta or "archived_at" in meta:
            continue
        confidence = float(meta.get("confidence", 0.5))
        citations = int(meta.get("citations", 0))
        modified = meta.get("modified")
        if not modified:
            continue
        try:
            mod_dt = parse_iso(modified)
        except ValueError:
            continue
        age_days = (now - mod_dt).total_seconds() / 86400
        if age_days <= DECAY_THRESHOLD_DAYS:
            continue
        if citations >= DECAY_MIN_CITATIONS:
            continue
        new_confidence = max(MIN_CONFIDENCE_FLOOR, confidence - DECAY_RATE)
        if new_confidence == confidence:
            continue
        meta["confidence"] = round(new_confidence, 2)
        change = {"file": p.name, "old": confidence, "new": new_confidence, "archived": False}
        if new_confidence <= MIN_CONFIDENCE_FLOOR:
            meta["archived_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            change["archived"] = True
            if not dry_run:
                _write_frontmatter(p, fm, body)
                dest = _archive(p)
                change["moved_to"] = str(dest.relative_to(LONGTERM_DIR.parent))
        else:
            if not dry_run:
                _write_frontmatter(p, fm, body)
        changes.append(change)
    return changes


def supersede(newer_name: str, older_name: str, dry_run: bool = False) -> tuple:
    older_path = None
    for p in LONGTERM_DIR.glob("*.md"):
        fm, _, _ = _read_frontmatter(p)
        if fm.get("name") == older_name:
            older_path = p
            break
    if older_path is None:
        return None, False
    fm, body, _ = _read_frontmatter(older_path)
    meta = fm.get("metadata") or {}
    meta["superseded_by"] = newer_name
    meta["confidence"] = SUPERSEDE_CONFIDENCE
    meta["superseded_at"] = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_frontmatter(older_path, fm, body)
    return older_path, True


def prune(dry_run: bool = False) -> list:
    changes = []
    now = utc_now()
    for p in LONGTERM_DIR.glob("*.md"):
        fm, _, _ = _read_frontmatter(p)
        if not fm:
            continue
        meta = fm.get("metadata") or {}
        if "superseded_by" in meta or "archived_at" in meta:
            if not dry_run:
                dest = _archive(p)
                changes.append({"file": p.name, "reason": "already-marked", "moved_to": str(dest.relative_to(LONGTERM_DIR.parent))})
            else:
                changes.append({"file": p.name, "reason": "already-marked", "would_archive": True})
            continue
        confidence = float(meta.get("confidence", 0.5))
        citations = int(meta.get("citations", 0))
        modified = meta.get("modified")
        if not modified:
            continue
        try:
            mod_dt = parse_iso(modified)
        except ValueError:
            continue
        age_days = (now - mod_dt).total_seconds() / 86400
        if citations == 0 and age_days > PRUNE_NO_CITATION_DAYS:
            if not dry_run:
                dest = _archive(p)
                changes.append({"file": p.name, "reason": "no-citations-stale", "moved_to": str(dest.relative_to(LONGTERM_DIR.parent))})
            else:
                changes.append({"file": p.name, "reason": "no-citations-stale", "would_archive": True})
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Forget longterm entries via decay/supersede/prune")
    parser.add_argument("mode", choices=["decay", "prune", "supersede"], help="which sub-mechanism")
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    parser.add_argument("args", nargs="*", help="for supersede: NEWER_NAME OLDER_NAME")
    args = parser.parse_args()

    if args.mode == "decay":
        changes = decay(dry_run=args.dry_run)
    elif args.mode == "prune":
        changes = prune(dry_run=args.dry_run)
    elif args.mode == "supersede":
        if len(args.args) != 2:
            print("FAIL: supersede needs NEWER_NAME OLDER_NAME", file=sys.stderr)
            return 1
        path, applied = supersede(args.args[0], args.args[1], dry_run=args.dry_run)
        changes = [{"file": str(path) if path else None, "applied": applied, "newer": args.args[0], "older": args.args[1]}]

    if not changes:
        print(f"{args.mode.upper()}: no changes{' (dry-run)' if args.dry_run else ''}")
        return 0
    print(f"{args.mode.upper()}{'(dry-run)' if args.dry_run else ''}: {len(changes)} changes")
    for c in changes:
        print(f"  - {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())