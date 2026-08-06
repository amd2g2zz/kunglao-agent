"""Distill pipeline for kunglao-agent memory.

Two-tier distill: read N entries from staging/, write 1 longterm entry to
longterm/, clear staging/ — all as one atomic transaction.

Atomicity rules (from `references/memory-protocol.md`):
  1. LOCK         create staging/.distill.lock
  2. SNAPSHOT     cp staging/*.md staging/.snapshot/
  3. DISTILL      (this script) write 1 longterm entry from 10 staging entries
  4. WRITE_LONGTERM  append to longterm/<date>-distill-N.md + INDEX.md
  5. VERIFY       hash check
  6. CLEAR_STAGING  rm staging/*.md (ONLY if step 5 passed)
  7. RELEASE      rm staging/.distill.lock

Threshold: 10 entries by default. Override with --threshold or --force.

Usage:
  python distill.py --dry-run                # show what would happen
  python distill.py --threshold 5            # custom threshold
  python distill.py --force                  # below threshold but proceed
  python distill.py                          # default (threshold=10)

The DISTILL step (step 3) is currently a stub that emits a templated
longterm entry. Replace with an LLM call when the orchestrator is wired up.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MEMORY_DIR = SCRIPT_DIR.parent
STAGING_DIR = MEMORY_DIR / "staging"
LONGTERM_DIR = MEMORY_DIR / "longterm"
DEFAULT_THRESHOLD = 10


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def count_staging() -> list:
    """Return sorted list of staging entries (excluding INDEX.md, lock, snapshot)."""
    if not STAGING_DIR.exists():
        return []
    excluded = {"INDEX.md", ".distill.lock"}
    files = [
        p for p in STAGING_DIR.iterdir()
        if p.is_file() and p.name not in excluded and not p.name.startswith(".snapshot")
    ]
    return sorted(files)


def lock_held() -> bool:
    return (STAGING_DIR / ".distill.lock").exists()


def acquire_lock() -> None:
    lock_path = STAGING_DIR / ".distill.lock"
    if lock_path.exists():
        raise RuntimeError(f"distill already in progress: {lock_path}")
    lock_path.write_text(f"lock acquired at {utc_now()}\n", encoding="utf-8")


def release_lock() -> None:
    lock_path = STAGING_DIR / ".distill.lock"
    if lock_path.exists():
        lock_path.unlink()


def snapshot_staging(entries: list) -> Path:
    snap_dir = STAGING_DIR / ".snapshot" / datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_dir.mkdir(parents=True, exist_ok=False)
    for p in entries:
        shutil.copy2(p, snap_dir / p.name)
    return snap_dir


def synthesize_longterm_body(entries: list) -> tuple:
    """Stub: produce a templated longterm body from staging entries."""
    sections: list = []
    for p in entries:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        in_symptom = False
        for line in text.splitlines():
            if line.startswith("## Symptom"):
                in_symptom = True
                sections.append(f"### From {p.name}")
                continue
            if in_symptom:
                if line.startswith("## "):
                    in_symptom = False
                else:
                    sections.append(line)
    body = (
        "## Rule\n\n"
        "(Auto-distilled from staging/. LLM prompt not yet wired — "
        "this stub captures the union of Symptom observations. "
        "Replace with LLM-generated forward-looking rule.)\n\n"
        "## Examples\n\n"
        + "\n".join(sections)
        + "\n"
    )
    slug = f"distill-{datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')}-N"
    return slug, body


def write_longterm(entries: list) -> tuple:
    """Step 4: write the longterm entry + INDEX.md line."""
    LONGTERM_DIR.mkdir(parents=True, exist_ok=True)
    slug, body = synthesize_longterm_body(entries)
    date_part = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    existing = sorted(LONGTERM_DIR.glob(f"{date_part}-distill-*.md"))
    n = len(existing) + 1
    out_path = LONGTERM_DIR / f"{date_part}-distill-{n}.md"
    frontmatter = (
        "---\n"
        f"name: {slug}\n"
        f"description: Distilled from {len(entries)} staging entries on {date_part}\n"
        "metadata:\n"
        "  node_type: memory\n"
        "  type: rule\n"
        f"  originSessionId: distill-{date_part}-{n}\n"
        f"  modified: {utc_now()}\n"
        "  cross_project: true\n"
        "  source_staging:\n"
    )
    for e in entries:
        frontmatter += f"    - {e.name}\n"
    frontmatter += "---\n\n"
    full = frontmatter + body
    out_path.write_text(full, encoding="utf-8")
    h = hashlib.sha256(full.encode("utf-8")).hexdigest()

    idx_path = LONGTERM_DIR / "INDEX.md"
    if not idx_path.exists():
        idx_path.write_text("# Longterm memory index\n\n", encoding="utf-8")
    with idx_path.open("a", encoding="utf-8") as f:
        f.write(f"- {date_part}-distill-{n}: {slug} ({len(entries)} entries → 1 rule)\n")

    return out_path, h


def verify_longterm(path: Path, expected_hash: str) -> bool:
    if not path.exists():
        return False
    actual = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    return actual == expected_hash


def clear_staging(entries: list) -> None:
    """Step 6: rm the distilled entries. ONLY call after step 5 passes."""
    for p in entries:
        p.unlink()


def distill(threshold: int = DEFAULT_THRESHOLD, force: bool = False, dry_run: bool = False) -> int:
    if lock_held():
        print("FAIL: another distill in progress (.distill.lock present)")
        return 1

    entries = count_staging()
    if not entries:
        print("NOOP: staging empty")
        return 2
    if len(entries) < threshold and not force:
        print(f"NOOP: staging has {len(entries)} entries, threshold={threshold} (use --force to override)")
        return 2

    if dry_run:
        print(f"DRY_RUN: would distill {len(entries)} entries from staging → longterm")
        for e in entries:
            print(f"  - {e.name}")
        return 0

    snap_dir = None
    longterm_path = None
    longterm_hash = None

    try:
        acquire_lock()
        snap_dir = snapshot_staging(entries)
        longterm_path, longterm_hash = write_longterm(entries)
        if not verify_longterm(longterm_path, longterm_hash):
            raise RuntimeError(f"longterm verify failed for {longterm_path}")
        clear_staging(entries)
        release_lock()
        print(f"OK: distilled {len(entries)} entries → {longterm_path}")
        print(f"     snapshot at {snap_dir} (kept for audit)")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        if longterm_path and longterm_path.exists():
            longterm_path.unlink()
            print(f"     rolled back longterm write: {longterm_path}")
        if snap_dir and snap_dir.exists():
            print(f"     staging snapshot kept at {snap_dir} for manual recovery")
        release_lock()
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Distill kunglao-agent staging → longterm")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help=f"min staging entries (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--force", action="store_true", help="bypass threshold check")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen")
    args = parser.parse_args()
    return distill(threshold=args.threshold, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())