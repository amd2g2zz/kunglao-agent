"""Distill pipeline for kunglao-agent memory.

Two-tier distill (issue #82, candidate-first): read N entries from staging/,
write ONE immutable candidate record to candidates/ (NEVER a production rule),
record lineage (source hashes / generator version / snapshot ref) in
memory/lifecycle-journal.jsonl. Production longterm/ is written ONLY by the
promotion gate (promote.py) after a complete evaluator receipt + held-out gain
+ safety no-regression + lineage + independent score.

Lifecycle (append-only journal rows):
  CANDIDATE (generated) -> evaluated (evaluate.py) -> PROMOTED | REJECTED | EXPIRED
  plus duplicate / failed rows; RETIRED for promoted rules (promote.py).
  Effective status = last journal row for the candidate id; candidate record
  files are immutable (content-addressed id, hash pinned at generation).

Atomicity rules (from references/memory-protocol.md):
  1. LOCK         create staging/.distill.lock
  2. SNAPSHOT     cp staging/*.md staging/.snapshot/
  3. GENERATE     write 1 immutable candidate record from N staging entries
  4. VERIFY       hash check of the candidate record
  5. JOURNAL      append `generated` row (content hash + source hashes)
  6. RELEASE      rm staging/.distill.lock
  Staging is cleared by evaluate.py ONLY after a completed receipt exists
  (issue #82: never clear merely because a candidate was attempted).

On generation failure: reproducible failure receipt (failure-*.json) + staging
kept byte-identical (source-evidence retention, issue #82 acceptance e).

Threshold: 10 entries by default. Override with --threshold or --force.

Usage:
  python distill.py --dry-run                # show what would happen
  python distill.py --threshold 5            # custom threshold
  python distill.py --force                  # below threshold but proceed
  python distill.py                          # default (threshold=10)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MEMORY_DIR = SCRIPT_DIR.parent
STAGING_DIR = MEMORY_DIR / "staging"
LONGTERM_DIR = MEMORY_DIR / "longterm"
CANDIDATE_DIR = MEMORY_DIR / "candidates"
RECEIPTS_DIR = CANDIDATE_DIR / "receipts"
CORPUS_DIR = CANDIDATE_DIR / "corpus"
BACKUP_DIR = MEMORY_DIR / "rules-backup"
JOURNAL_PATH = MEMORY_DIR / "lifecycle-journal.jsonl"
REGISTRY_PATH = MEMORY_DIR / "rules-registry.json"
DEFAULT_THRESHOLD = 10
GENERATOR_VERSION = "2.0.0"     # candidate-first generator (issue #82)
CANDIDATE_VERSION = 1
HELD_OUT_GAIN_MIN = 0.10        # promotion gate: held-out correctness gain floor
CANDIDATE_EXPIRY_DAYS = 30      # candidates without promotion expire after this
CANDIDATE_SCHEMA = "kunglao-candidate/1"
FAILURE_RECEIPT_SCHEMA = "kunglao-failure-receipt/1"
# body-scan safety invariants (issue #82 acceptance c): a candidate that
# instructs evidence destruction or direct production writes is harmful
HARMFUL_PATTERNS = [
    "delete staging", "clear staging", "delete evidence", "rm ",
    "write longterm", "promote directly", "overwrite longterm",
]


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(obj) -> str:
    """Canonical JSON (sorted keys, no spaces) — digest basis, mirrors #81."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(obj) -> str:
    """sha256 over canonical JSON of obj (or raw bytes)."""
    if isinstance(obj, (bytes, bytearray)):
        return hashlib.sha256(bytes(obj)).hexdigest()
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    # %f keeps snapshot dirs unique even for same-second re-runs (duplicate
    # generation must snapshot again, not collide)
    snap_dir = STAGING_DIR / ".snapshot" / datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ%f")
    snap_dir.mkdir(parents=True, exist_ok=False)
    for p in entries:
        shutil.copy2(p, snap_dir / p.name)
    return snap_dir


def derive_discipline(body: str) -> str:
    """Rule discipline from the rule body (fail-closed: no marker => naive).

    anchored rules mandate anchor-based conclusions; naive rules conclude from
    any successful dispatch. A rule that does not say it anchors evidence is
    treated as naive so it cannot promote by default (issue #82 b/c).
    """
    for line in body.splitlines():
        s = line.strip().lower()
        if s.startswith("## discipline:"):
            val = s.split(":", 1)[1].strip()
            return "anchored" if val == "anchored" else "naive"
    return "naive"


def synthesize_candidate_body(entries: list) -> str:
    """Stub generator: templated candidate body from staging Symptom sections.

    (LLM integration not wired — same stub status as pre-#82; the difference is
    its OUTPUT is a candidate record, never a production rule.)
    """
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
        "(Auto-distilled from staging/. LLM prompt not yet wired — this stub "
        "captures the union of Symptom observations. A forward-looking rule "
        "must mandate anchored evidence conclusions to be promotable "
        "(## Discipline: anchored).)\n\n"
        "## Examples\n\n"
        + "\n".join(sections)
        + "\n"
    )
    return body


def candidate_id(entries: list, snap_dir: Path, body: str) -> str:
    """Content-addressed id: source hashes + generator version + body digest.

    Deterministic: identical staging + generator yields the same id, so
    duplicates are detectable without opening candidate files.
    """
    sources = {p.name: _file_sha256(snap_dir / p.name) for p in entries}
    digest = _sha({
        "sources": sources,
        "generator": GENERATOR_VERSION,
        "body": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    })
    return f"cand-{digest[:12]}"


def candidate_record_text(cid: str, entries: list, snap_dir: Path, body: str) -> str:
    """Frontmatter + body of the immutable candidate record (written once)."""
    sources = {p.name: _file_sha256(snap_dir / p.name) for p in entries}
    date_part = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    fm = (
        "---\n"
        f"name: {cid}\n"
        f"description: Distilled from {len(entries)} staging entries on {date_part}\n"
        "metadata:\n"
        "  node_type: memory\n"
        "  type: rule\n"
        f"  originSessionId: distill-{date_part}\n"
        f"  modified: {utc_now()}\n"
        "  cross_project: true\n"
        "  status: CANDIDATE\n"
        f"  candidate_id: {cid}\n"
        "  source_staging:\n"
    )
    for p in entries:
        fm += f"    - {p.name}\n"
    fm += "  source_hashes:\n"
    for p in entries:
        fm += f"    {p.name}: {sources[p.name]}\n"
    fm += (
        f"  snapshot_ref: {snap_dir.name}\n"
        "  generator:\n    name: template-stub\n"
        f"    version: {GENERATOR_VERSION}\n"
        f"  candidate_version: {CANDIDATE_VERSION}\n"
        f"  evaluation:\n    discipline: {derive_discipline(body)}\n"
        "---\n\n"
    )
    return fm + body


def write_candidate(entries: list, snap_dir: Path) -> tuple[Path, str]:
    """Step 3-4: write the candidate record; return (path, content_hash)."""
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    body = synthesize_candidate_body(entries)
    cid = candidate_id(entries, snap_dir, body)
    out_path = CANDIDATE_DIR / f"{cid}.md"
    text = candidate_record_text(cid, entries, snap_dir, body)
    out_path.write_text(text, encoding="utf-8")
    return out_path, _file_sha256(out_path)


def verify_candidate(path: Path, expected_hash: str) -> bool:
    if not path.exists():
        return False
    return _file_sha256(path) == expected_hash


def clear_staging(entries: list) -> None:
    """Delete the given staging entry files (caller enforces the clear gate)."""
    for p in entries:
        p.unlink()


def load_candidate(candidate_id: str) -> tuple:
    """(path, frontmatter_dict, body) for a candidate record; raises on absence."""
    from memory_schema import extract_frontmatter
    path = CANDIDATE_DIR / f"{candidate_id}.md"
    text = path.read_text(encoding="utf-8")
    fm, body = extract_frontmatter(text)
    if "_parse_error" in fm:
        raise ValueError(f"candidate frontmatter parse error: {fm['_parse_error']}")
    return path, fm, body


# ----------------------------- lifecycle journal -----------------------------

def journal_append(row: dict) -> None:
    """Append one lifecycle event (append-only; never rewritten)."""
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def journal_rows(candidate_id: str | None = None) -> list:
    """All journal rows, or rows for one candidate id (None -> every row)."""
    if not JOURNAL_PATH.exists():
        return []
    rows: list = []
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if candidate_id is None:
        return rows
    return [r for r in rows if r.get("candidate_id") == candidate_id]


# ----------------------------- rules registry -----------------------------

def default_registry() -> dict:
    return {"schema": "kunglao-rules-registry/1", "current": None,
            "snapshots": {}, "history": []}


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return default_registry()
    try:
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_registry()
    if not isinstance(reg, dict) or "current" not in reg:
        return default_registry()
    return reg


def save_registry(reg: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")


# ----------------------------- failure receipts -----------------------------

def write_failure_receipt(*, stage: str, reason: str, candidate_id: str | None,
                          input_digests: dict, exit_code: int = 1,
                          error_taxonomy: list | None = None) -> Path:
    """Reproducible failure receipt (same inputs -> same receipt_digest; ts excluded).

    stage: 'generation' | 'evaluation'. Staging evidence is retained by the
    caller's contract (issue #82 acceptance e: keep raw evidence on failure).
    """
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    cid_part = f"{candidate_id}-" if candidate_id else ""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RECEIPTS_DIR / f"failure-{cid_part}{ts}-{stage}.json"
    rec = {
        "schema": FAILURE_RECEIPT_SCHEMA,
        "stage": stage,
        "status": "FAIL",
        "reason": reason,
        "candidate_id": candidate_id,
        "generator_version": GENERATOR_VERSION,
        "input_digests": input_digests,
        "error_taxonomy": error_taxonomy or [],
        "exit_code": exit_code,
        "started_at": utc_now(),
        "finished_at": utc_now(),
    }
    stable = {k: v for k, v in rec.items() if k not in ("started_at", "finished_at")}
    rec["receipt_digest"] = _sha(stable)
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    journal_append({"ts": utc_now(), "action": "failed", "candidate_id": candidate_id,
                    "reason": f"{stage} failure: {reason}", "receipt_ref": str(path),
                    "digests": {"receipt": rec["receipt_digest"]}})
    return path


# ----------------------------- distill pipeline -----------------------------

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
        print(f"DRY_RUN: would distill {len(entries)} entries from staging → candidate record")
        for e in entries:
            print(f"  - {e.name}")
        return 0

    snap_dir = None
    try:
        acquire_lock()
        snap_dir = snapshot_staging(entries)
        out_path, content_hash = write_candidate(entries, snap_dir)
        if not verify_candidate(out_path, content_hash):
            raise RuntimeError(f"candidate verify failed for {out_path}")
        cid = out_path.stem
        if any(r.get("action") == "generated" and r.get("candidate_id") == cid
               for r in journal_rows()):
            journal_append({"ts": utc_now(), "action": "duplicate", "candidate_id": cid,
                            "reason": "identical staging + generator already distilled",
                            "receipt_ref": None, "digests": {"content": content_hash}})
            print(f"DUPLICATE: {cid} already distilled (staging kept for evidence)")
            return 0
        text = out_path.read_text(encoding="utf-8")
        body = text.split("---\n\n", 1)[-1] if text.startswith("---") else text
        sources = {p.name: _file_sha256(snap_dir / p.name) for p in entries}
        journal_append({"ts": utc_now(), "action": "generated", "candidate_id": cid,
                        "reason": None, "receipt_ref": None,
                        "digests": {"content": content_hash, "sources": sources},
                        "discipline": derive_discipline(body)})
        print(f"OK: candidate {cid} written ({len(entries)} entries → 1 candidate)")
        print(f"     snapshot at {snap_dir} (kept for audit; staging cleared only after evaluation)")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        try:
            input_digests = {p.name: _file_sha256(p) for p in entries}
        except OSError:
            input_digests = {}
        write_failure_receipt(stage="generation", reason=str(exc), candidate_id=None,
                              input_digests=input_digests)
        print("     staging kept (source-evidence retention, issue #82)")
        return 1
    finally:
        release_lock()


def main() -> int:
    parser = argparse.ArgumentParser(description="Distill kunglao-agent staging → candidate")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help=f"min staging entries (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--force", action="store_true", help="bypass threshold check")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen")
    args = parser.parse_args()
    return distill(threshold=args.threshold, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
