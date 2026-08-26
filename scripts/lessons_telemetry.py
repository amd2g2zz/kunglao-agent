#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lessons_telemetry.py — per-lesson CBM quartet + utility score + tombstone (#526).

CBM quartet (per-lesson counters persisted in frontmatter):
  citation_count   — bumped when the lesson is surfaced as a candidate (the
                     retrieval face). How often retrieval says "this is relevant".
  burn_count       — bumped when the lesson is actually CONSUMED (its next_method
                     was adopted as the new method). A search hit that nobody
                     acts on is noise.
  match_count      — bumped when retrieval returned the lesson with score > 0.
                     Distinct from citation so we can tell "passed threshold"
                     from "showed up at all".
  utility_score    — derived: utility = burn_count / (citation_count + 1). The
                     +1 keeps the 0/0 case at 0 (no ZeroDiv). A lesson cited
                     but never burned = utility 0; one burned out of one
                     citation = utility 0.5.

Tombstone mechanism (deprecate governance):
  - File stays on disk (citations are part of the audit trail; past analyses
    and emit-log rows cite the slug, deletion would lose those cross-refs).
  - Frontmatter gains: deprecated=true, deprecated_reason, deprecated_at.
  - All count_* calls become silent no-ops on tombstoned lessons
    (skipped_deprecated=True on the return dict).
  - Re-deprecate is idempotent — the original reason wins (audit discipline:
    never silently rewrite the reason).
  - active_lessons() filters them out so the live search surface stays clean;
    the file is still on disk for auditors.

Emit-log face (kunglao_log.emit): every counter change emits one event whose
detail carries the CURRENT utility_score so `--tail` can graph per-lesson
utility without re-reading the library. The emit MUST be the LAST step of
the transaction (write file first, then emit) so a log failure never
silently corrupts the counter (the test_emit_failure_does_not_corrupt_counters
guard pins that ordering).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


# ---------- UTC stamp (matches retract_claim / failure_analysis_gate) ----

def _utc_now_iso() -> str:
    """ISO-8601 UTC with a trailing Z — same convention as the rest of the kunglao code."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- emit helper (fail-open — observation must never break counting)

def _safe_emit(workspace: Path | None, action: str, slug: str, utility: float,
               detail_extra: str = "") -> None:
    """Emit one telemetry event. Fails open — a log write failure must never
    raise into the counter transaction. emit() is the LAST step: the file
    write above already committed the counter."""
    try:
        from kunglao_log import emit
        ws = workspace if workspace is not None else "."
        detail = f"utility={utility:.3f}"
        if detail_extra:
            detail = f"{detail} {detail_extra}"
        emit(ws, actor="telemetry", action=action,
             artifact=f"lesson-{slug}.md", detail=detail)
    except Exception:
        pass  # fail-open by contract


# ---------- frontmatter read / write ----------

def _split_parts(text: str) -> tuple[str, str, str]:
    """Split text into (front, meta_yaml, rest). Front is the bytes before
    the opening '---' (usually ''); meta_yaml is the YAML block; rest is the
    body. Tolerant of the closing fence being either on its own line
    (`... value\n---\n`) or glued to the last value (`... value---\n`) —
    the producer's `dump().strip()` + `"---\n"` concatenation produces the
    latter, and a strict `\n---` search would miss it."""
    if text.startswith("---"):
        body = text[3:]
        if body.startswith("\n"):
            body = body[1:]
        # Look for the closing fence on its own line first.
        end = body.find("\n---")
        if end == -1:
            # Fall back to a glued fence (no newline before ---).
            end = body.find("---")
            if end == -1:
                return "", "", text
            meta_yaml = body[:end]
            rest = body[end + 3:]
            if rest.startswith("\n"):
                rest = rest[1:]
            return text[:3], meta_yaml, rest
        meta_yaml = body[:end]
        rest = body[end + 4:]
        if rest.startswith("\n"):
            rest = rest[1:]
        return text[:3], meta_yaml, rest
    return "", "", text


def _load_frontmatter(path: Path) -> tuple[dict, str]:
    """Return (meta_dict, body_text). Tolerant parse — broken YAML returns
    ({}, original) so the caller can degrade to ok=False instead of crashing."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, ""
    _front, meta_yaml, rest = _split_parts(text)
    try:
        meta = yaml.safe_load(meta_yaml) or {}
    except yaml.YAMLError:
        return {}, rest
    if not isinstance(meta, dict):
        meta = {}
    return meta, rest


def _write_frontmatter(path: Path, meta: dict, body: str) -> None:
    """Atomic-enough write: dump frontmatter + body back. yaml.safe_dump
    sort_keys=False preserves insertion order; we re-read & re-emit on every
    counter bump so the field set we touch (counters, deprecated markers)
    shows up while leaving other fields untouched (slug, sources, outcome)."""
    dump = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    text = "---\n" + dump + "\n---\n\n" + body
    path.write_text(text, encoding="utf-8")


# ---------- core: CBM quartet ----------

def compute_utility(citation_count: int, burn_count: int) -> float:
    """utility = burn_count / (citation_count + 1). Pure (no I/O)."""
    c = max(int(citation_count or 0), 0)
    b = max(int(burn_count or 0), 0)
    return b / (c + 1)


def _resolve_library(library: Path | str | None) -> Path:
    """#752: the default derives from the EXECUTING install (any durable
    ~/.claude/skills/<name>/ package resolves to itself; ephemeral
    checkouts fall back to the production install) — no second hardcoded
    'kunglao-agent' path may exist outside hook_activation."""
    from hook_activation import canonical_install_root  # lazy sibling import
    return (Path(library) if library is not None
            else canonical_install_root() / "references" / "lessons")


def _resolve_workspace(workspace: Path | str | None) -> Path | None:
    return Path(workspace) if workspace is not None else None


def _bump(library: Path, slug: str, counter_name: str, action: str,
          workspace: Path | None) -> dict:
    """Atomic-ish bump: read frontmatter -> increment -> write -> emit.
    Returns a counter dict; ok=False on missing library / missing lesson /
    corrupt frontmatter / tombstoned (with skipped_deprecated=True)."""
    if not library.exists():
        return {"ok": False, "reason": f"library not found: {library}",
                "slug": slug, "citation_count": 0, "burn_count": 0,
                "match_count": 0, "utility_score": 0.0}

    p = library / f"lesson-{slug}.md"
    if not p.exists():
        return {"ok": False, "reason": f"lesson {slug!r} not found in {library}",
                "slug": slug, "citation_count": 0, "burn_count": 0,
                "match_count": 0, "utility_score": 0.0}

    meta, body = _load_frontmatter(p)
    if not meta:
        return {"ok": False,
                "reason": f"lesson {slug!r} has corrupt frontmatter",
                "slug": slug, "citation_count": 0, "burn_count": 0,
                "match_count": 0, "utility_score": 0.0}

    if meta.get("deprecated") is True:
        # Tombstoned lesson: counters freeze. Emit a no-counter event so
        # the audit trail records the attempt (operator wanted to bump
        # a dead lesson — worth seeing) — but DO NOT touch the file.
        # We still report the frozen values for downstream ergonomics.
        cc = int(meta.get("citation_count", 0) or 0)
        bc = int(meta.get("burn_count", 0) or 0)
        mc = int(meta.get("match_count", 0) or 0)
        utility = float(meta.get("utility_score", compute_utility(cc, bc)) or 0.0)
        _safe_emit(workspace, action, slug, utility,
                   detail_extra="skipped_deprecated")
        return {"ok": True, "skipped_deprecated": True, "slug": slug,
                "citation_count": cc, "burn_count": bc, "match_count": mc,
                "utility_score": utility}

    meta[counter_name] = int(meta.get(counter_name, 0) or 0) + 1
    # Materialize the trio up front so all three are visible in frontmatter
    # even when only one has ever been bumped (consumer ergonomics: a reader
    # sees citation_count/burn_count/match_count on every lesson, not
    # sparse-key semantics).
    cc = int(meta.get("citation_count", 0) or 0)
    bc = int(meta.get("burn_count", 0) or 0)
    mc = int(meta.get("match_count", 0) or 0)
    utility = compute_utility(cc, bc)
    meta["citation_count"] = cc
    meta["burn_count"] = bc
    meta["match_count"] = mc
    meta["utility_score"] = utility
    _write_frontmatter(p, meta, body)  # write BEFORE emit (counters are the
                                       # source of truth; a failed emit must
                                       # never corrupt them)
    _safe_emit(workspace, action, slug, utility)
    return {"ok": True, "slug": slug,
            "citation_count": cc, "burn_count": bc, "match_count": mc,
            "utility_score": utility}


def record_citation(library: Path | str, slug: str, workspace: Path | str | None = None) -> dict:
    """Bump citation_count (lesson was surfaced as a candidate)."""
    return _bump(_resolve_library(library), slug, "citation_count",
                 "lesson_citation", _resolve_workspace(workspace))


def record_burn(library: Path | str, slug: str, workspace: Path | str | None = None) -> dict:
    """Bump burn_count (lesson's next_method was adopted as the new method)."""
    return _bump(_resolve_library(library), slug, "burn_count",
                 "lesson_burn", _resolve_workspace(workspace))


def record_match(library: Path | str, slug: str, workspace: Path | str | None = None) -> dict:
    """Bump match_count (lesson appeared in the result set with score > 0)."""
    return _bump(_resolve_library(library), slug, "match_count",
                 "lesson_match", _resolve_workspace(workspace))


# ---------- tombstone: deprecate governance ----------

def deprecate_lesson(library: Path | str, slug: str, reason: str,
                     workspace: Path | str | None = None) -> dict:
    """Tombstone a lesson (soft delete). File stays on disk (audit trail);
    frontmatter gains deprecated=true, deprecated_reason, deprecated_at.
    Idempotent: re-deprecating keeps the ORIGINAL reason + at (audit
    discipline — never silently rewrite). Empty reason is rejected."""
    lib = _resolve_library(library)
    if not lib.exists():
        return {"ok": False, "reason": f"library not found: {lib}"}
    p = lib / f"lesson-{slug}.md"
    if not p.exists():
        return {"ok": False, "reason": f"lesson {slug!r} not found in {lib}"}
    reason_norm = (reason or "").strip()
    if not reason_norm:
        return {"ok": False,
                "reason": "reason is required (audit discipline — must record WHY)"}

    meta, body = _load_frontmatter(p)
    if not meta:
        return {"ok": False,
                "reason": f"lesson {slug!r} has corrupt frontmatter"}

    if meta.get("deprecated") is True:
        # Idempotent: original reason + at preserved. NO emit on the
        # idempotent path — the first deprecate already emitted and the
        # detail would otherwise repeat; the test that pins this is
        # test_deprecate_is_idempotent.
        return {"ok": True, "already_deprecated": True, "slug": slug,
                "file_kept": True,
                "deprecated_reason": meta.get("deprecated_reason"),
                "deprecated_at": meta.get("deprecated_at")}

    meta["deprecated"] = True
    meta["deprecated_reason"] = reason_norm
    meta["deprecated_at"] = _utc_now_iso()
    _write_frontmatter(p, meta, body)  # write BEFORE emit
    utility = float(meta.get("utility_score", 0.0) or 0.0)
    _safe_emit(_resolve_workspace(workspace), "lesson_deprecated", slug,
               utility,
               detail_extra=f"reason={reason_norm[:60]}")
    return {"ok": True, "slug": slug, "file_kept": True,
            "deprecated_reason": reason_norm,
            "deprecated_at": meta["deprecated_at"]}


def is_deprecated(library: Path | str, slug: str) -> bool:
    """True iff the lesson file exists AND frontmatter has deprecated=true.
    Missing file is NOT deprecated (it never existed)."""
    p = _resolve_library(library) / f"lesson-{slug}.md"
    if not p.exists():
        return False
    meta, _ = _load_frontmatter(p)
    return bool(meta) and meta.get("deprecated") is True


def list_deprecated(library: Path | str) -> list[str]:
    """Slugs of all tombstoned lessons in the library (sorted)."""
    lib = _resolve_library(library)
    if not lib.exists():
        return []
    out: list[str] = []
    for p in sorted(lib.glob("lesson-*.md")):
        meta, _ = _load_frontmatter(p)
        if meta and meta.get("deprecated") is True:
            slug = p.name.removeprefix("lesson-").removesuffix(".md")
            out.append(slug)
    return out


def active_lessons(library: Path | str) -> list[Path]:
    """Paths to NON-deprecated lessons (the live search surface). Order:
    deterministic — sorted by name."""
    lib = _resolve_library(library)
    if not lib.exists():
        return []
    out: list[Path] = []
    for p in sorted(lib.glob("lesson-*.md")):
        meta, _ = _load_frontmatter(p)
        if not meta:
            continue
        if meta.get("deprecated") is True:
            continue
        out.append(p)
    return out


# ---------- CLI (lightweight — the gate / search caller owns the main flow)

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="lessons_telemetry.py",
        description="CBM quartet + utility_score + tombstone (#526)")
    ap.add_argument("library", help="lessons library directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cit = sub.add_parser("cite", help="bump citation_count")
    p_cit.add_argument("slug")
    p_cit.add_argument("--workspace", default=None,
                       help="emit-log workspace (omit to emit to cwd)")

    p_burn = sub.add_parser("burn", help="bump burn_count")
    p_burn.add_argument("slug")
    p_burn.add_argument("--workspace", default=None)

    p_match = sub.add_parser("match", help="bump match_count")
    p_match.add_argument("slug")
    p_match.add_argument("--workspace", default=None)

    p_dep = sub.add_parser("deprecate", help="tombstone a lesson (file kept)")
    p_dep.add_argument("slug")
    p_dep.add_argument("--reason", required=True,
                       help="WHY the lesson is being deprecated (audit trail)")
    p_dep.add_argument("--workspace", default=None)

    args = ap.parse_args(argv)
    lib = Path(args.library)

    if args.cmd == "cite":
        r = record_citation(lib, args.slug, workspace=args.workspace)
    elif args.cmd == "burn":
        r = record_burn(lib, args.slug, workspace=args.workspace)
    elif args.cmd == "match":
        r = record_match(lib, args.slug, workspace=args.workspace)
    elif args.cmd == "deprecate":
        r = deprecate_lesson(lib, args.slug, args.reason, workspace=args.workspace)
    else:  # pragma: no cover — argparse 'required=True' rejects unknown cmds
        ap.error(f"unknown cmd {args.cmd!r}")

    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())