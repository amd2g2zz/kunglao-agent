#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comment_hygiene_lint.py — formal-content hygiene gate for scripts/ and tests/.

Rules (fail-closed: exit 0 = clean, exit 1 = violation; never warn-only):

  R1  tracker references: a comment line or docstring containing "#"
      immediately followed by a decimal digit (the tracker-number shape).
      Tracker references belong in commit messages and issue bodies,
      never in formal code.
  R2  phrases in NARRATIVE_MARKERS: process storytelling in comments or
      docstrings. Comments state non-obvious rationale neutrally; change
      history belongs to issues and PR bodies.
  R3  baseline ratchet over per-file R1/R2 counts
      (scripts/hygiene_baseline.yaml): the ledger only shrinks. A count
      above baseline fails; an entry whose counts reach zero must be
      deleted; a partially reduced entry must be tightened in the same
      change; an entry whose file is gone is stale and fails; new debt
      without an entry fails.

  M   mapping integrity (arms when references/re-library/_mapping.yaml
      exists): schema, row shape, unique sources, destination depth <= 3
      under re-library/, no dangling rows (source or destination must
      exist — both missing is a dangling row; the legal pre-move state
      declares an absent destination), full coverage of the re-library
      tree (a file on disk without a row fails), no double coverage.
  F   frontmatter pass (same arming condition): every mapped .md card
      must carry parseable frontmatter whose domain/family equal the
      mapping row.

Generated files are exempt via the ALLOWLIST constant, never via the
ledger. Counting unit: one comment line or one docstring (a docstring
counts once per rule regardless of marker count).

Usage:
  python scripts/comment_hygiene_lint.py
  python scripts/comment_hygiene_lint.py --emit-baseline
  python scripts/comment_hygiene_lint.py --json
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path, PurePosixPath
from tokenize import TokenError

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("scripts", "tests")
DEFAULT_BASELINE_REL = "scripts/hygiene_baseline.yaml"
MAPPING_REL = "references/re-library/_mapping.yaml"
RELIB_REL = "references/re-library"
RELIB_PREFIX = RELIB_REL + "/"

BASELINE_SCHEMA = "comment-hygiene-baseline/1"
MAPPING_SCHEMA = "re-library-mapping/1"
RULES = ("r1", "r2")
MAX_DEPTH = 3

# Generated files are exempt via the ALLOWLIST constant, never via the ledger.
ALLOWLIST: frozenset[str] = frozenset()

ISSUE_NUMBER_RE = re.compile(r"#[0-9]+")

# Narrative markers (formal-content constitution): process storytelling in
# comments/docstrings is banned; the phrases live here as data so the lint
# can name what it flags.
NARRATIVE_MARKERS = (
    r"\btooth\b",
    r"\bred-first\b",
    r"\bgreen target\b",
    r"\blanded via\b",
    r"\bthis wave\b",
    r"\bre-pin\w*",
    r"\bcluster [abcd]\b",
    r"\baggregation-first\b",
    r"\bdistillation wave\b",
)
NARRATIVE_RES = tuple(re.compile(p, re.IGNORECASE) for p in NARRATIVE_MARKERS)

_DOCSTRING_NODES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


# ------------------------------------------------------------- scanning

def _iter_py_files(root: Path):
    for rel_dir in SCAN_ROOTS:
        base = root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in ALLOWLIST:
                continue
            yield rel, path


def _comment_and_docstring_units(source: str) -> list[tuple[int, str]]:
    """One unit per comment line and per docstring, with a source line."""
    units: list[tuple[int, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            units.append((tok.start[0], tok.string))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_NODES):
            text = ast.get_docstring(node, clean=False)
            if text:
                units.append((getattr(node, "lineno", 1), text))
    return units


def _count_units(units: list[tuple[int, str]]) -> tuple[int, int]:
    r1 = sum(1 for _, text in units if ISSUE_NUMBER_RE.search(text))
    r2 = sum(1 for _, text in units
             if any(rx.search(text) for rx in NARRATIVE_RES))
    return r1, r2


def scan_counts(root: Path) -> tuple[dict[str, tuple[int, int]], list[dict]]:
    """Per-file (R1, R2) unit counts plus fail-closed structural findings."""
    counts: dict[str, tuple[int, int]] = {}
    structural: list[dict] = []
    for rel, path in _iter_py_files(root):
        try:
            source = path.read_text(encoding="utf-8")
            units = _comment_and_docstring_units(source)
        except (UnicodeDecodeError, OSError) as exc:
            structural.append({"kind": "unreadable", "file": rel,
                               "detail": str(exc)})
            continue
        except (SyntaxError, ValueError, TokenError) as exc:
            structural.append({"kind": "syntax", "file": rel,
                               "detail": str(exc)})
            continue
        counts[rel] = _count_units(units)
    return counts, structural


# ------------------------------------------------------- baseline ratchet

def load_baseline(path: Path) -> dict:
    """Parse the ledger file into {rel_path: {rule: count}}."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    files = doc.get("files") or {}
    entries: dict = {}
    for rel, rules in files.items():
        rules = rules or {}
        entries[str(rel)] = {rule: int(rules.get(rule, 0)) for rule in RULES}
    return entries


def compare(counts: dict, entries: dict) -> list[dict]:
    """Shrink-only ratchet: increase / zero-clear / loose-tighten / stale."""
    out: list[dict] = []
    for rel in sorted(set(counts) | set(entries)):
        if rel not in counts:
            out.append({"kind": "stale-entry", "file": rel,
                        "detail": "ledger entry for a file that no longer exists"})
            continue
        r1, r2 = counts[rel]
        current = {"r1": r1, "r2": r2}
        entry = entries.get(rel)
        if entry is None:
            if r1 + r2 > 0:
                out.append({"kind": "unbaselined", "file": rel,
                            "detail": f"r1={r1} r2={r2} with no ledger entry"})
            continue
        grew = [rule for rule in RULES if current[rule] > entry[rule]]
        if grew:
            out.append({"kind": "increase", "file": rel,
                        "detail": "grew " + ", ".join(
                            f"{rule}: {entry[rule]} -> {current[rule]}"
                            for rule in grew)})
        elif r1 + r2 == 0:
            out.append({"kind": "cleared-entry", "file": rel,
                        "detail": "counts reached zero: delete the ledger entry"})
        elif any(0 < current[rule] < entry[rule] for rule in RULES):
            out.append({"kind": "loose-entry", "file": rel,
                        "detail": "partially cleared: tighten the ledger entry"})
        elif all(entry[rule] == 0 for rule in RULES):
            out.append({"kind": "cleared-entry", "file": rel,
                        "detail": "empty ledger entry: delete it"})
    return out


def emit_baseline(counts: dict, path: Path) -> None:
    """Write the ledger from current counts; only debt files get entries."""
    files: dict = {}
    for rel in sorted(counts):
        r1, r2 = counts[rel]
        rules = {rule: n for rule, n in zip(RULES, (r1, r2)) if n > 0}
        if rules:
            files[rel] = rules
    doc = {
        "schema": BASELINE_SCHEMA,
        "unit": "per-file count of flagged comment lines and docstrings",
        "policy": (
            "ratchet only shrinks: a count above the ledger fails; an entry "
            "whose counts reach zero is deleted; a partially cleared entry is "
            "tightened in the same change; an entry whose file is gone is "
            "stale and fails; new debt without an entry fails"
        ),
        "files": files,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8")


# --------------------------------------------- mapping + frontmatter pass

def _check_row_shape(row, idx: int) -> list[dict]:
    if not isinstance(row, dict):
        return [{"kind": "row-shape", "file": MAPPING_REL,
                 "detail": f"row {idx}: not a mapping"}]
    for key in ("from", "to", "domain", "family"):
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            return [{"kind": "row-shape", "file": MAPPING_REL,
                     "detail": f"row {idx}: missing/non-string {key!r}"}]
    if not row["to"].startswith(RELIB_PREFIX):
        return [{"kind": "row-shape", "file": MAPPING_REL,
                 "detail": f"row {idx}: destination escapes re-library/"}]
    return []


def _check_row_paths(root: Path, row: dict, covered: dict) -> list[dict]:
    src, dst = row["from"], row["to"]
    rest = dst[len(RELIB_PREFIX):]
    depth = len(PurePosixPath(rest).parent.parts)
    if depth > MAX_DEPTH:
        return [{"kind": "depth", "file": dst,
                 "detail": f"depth {depth} exceeds the {MAX_DEPTH}-level cap"}]
    src_path, dst_path = root / src, root / dst
    exists_src, exists_dst = src_path.is_file(), dst_path.is_file()
    if not (exists_src or exists_dst):
        return [{"kind": "dangling-row", "file": src,
                 "detail": "neither source nor destination exists on disk"}]
    if exists_src:
        covered[src] = covered.get(src, 0) + 1
    if exists_dst:
        covered[dst] = covered.get(dst, 0) + 1
    existing = dst_path if exists_dst else src_path
    if existing.suffix != ".md":
        return []
    return _fm_violations(root, existing, row)


def _fm_violations(root: Path, path: Path, row: dict) -> list[dict]:
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return [{"kind": "fm-parse", "file": rel, "detail": str(exc)}]
    if not text.startswith("---\n") or len(text.split("---\n", 2)) < 3:
        return [{"kind": "fm-missing", "file": rel,
                 "detail": "mapped card has no frontmatter block"}]
    block = text.split("---\n", 2)[1]
    try:
        fm = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        return [{"kind": "fm-parse", "file": rel, "detail": str(exc)}]
    if not isinstance(fm, dict):
        return [{"kind": "fm-parse", "file": rel,
                 "detail": "frontmatter is not a YAML mapping"}]
    for key in ("domain", "family"):
        if fm.get(key) != row.get(key):
            return [{"kind": "fm-mismatch", "file": rel,
                     "detail": f"{key}: frontmatter {fm.get(key)!r} != row "
                               f"{row.get(key)!r}"}]
    return []


def mapping_violations(root: Path) -> list[dict]:
    """Trivially clean while the mapping file is absent; hard once it lands."""
    map_path = root / MAPPING_REL
    if not map_path.is_file():
        return []
    try:
        doc = yaml.safe_load(map_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        return [{"kind": "mapping-parse", "file": MAPPING_REL,
                 "detail": str(exc)}]
    doc = doc or {}
    out: list[dict] = []
    if doc.get("schema") != MAPPING_SCHEMA:
        out.append({"kind": "mapping-schema", "file": MAPPING_REL,
                    "detail": f"schema must be {MAPPING_SCHEMA!r}"})
    rows = doc.get("cards")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        return out + [{"kind": "mapping-schema", "file": MAPPING_REL,
                       "detail": "cards must be a list"}]
    seen_from: set[str] = set()
    covered: dict[str, int] = {}
    for idx, row in enumerate(rows):
        shape = _check_row_shape(row, idx)
        if shape:
            out.extend(shape)
            continue
        src = row["from"]
        if src in seen_from:
            out.append({"kind": "duplicate-row", "file": src,
                        "detail": "mapping declares this source twice"})
        seen_from.add(src)
        out.extend(_check_row_paths(root, row, covered))
    out.extend(_coverage_violations(root, covered))
    return out


def _coverage_violations(root: Path, covered: dict) -> list[dict]:
    """Every re-library file needs exactly one mapping row (bijection)."""
    out: list[dict] = []
    relib = root / RELIB_REL
    if not relib.is_dir():
        return out
    for path in sorted(relib.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == MAPPING_REL:
            continue
        hits = covered.get(rel, 0)
        if hits == 0:
            out.append({"kind": "outside-mapping", "file": rel,
                        "detail": "file under re-library has no mapping row"})
        elif hits > 1:
            out.append({"kind": "duplicate-coverage", "file": rel,
                        "detail": "covered by more than one mapping row"})
    return out


# ------------------------------------------------------------ gate faces

def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Formal-content hygiene gate over scripts/ and tests/.")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="repository root to scan (default: this repo)")
    parser.add_argument("--baseline", default=None,
                        help=f"ledger path (default: <root>/{DEFAULT_BASELINE_REL})")
    parser.add_argument("--emit-baseline", action="store_true",
                        help="write the ledger from current counts and exit")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable payload on stdout")
    return parser.parse_args(argv)


def build_report(argv: list[str] | None = None) -> dict:
    """Evaluate every pass and return {"violations": [...], "exit": 0|1}."""
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    baseline_path = (Path(args.baseline) if args.baseline
                     else root / DEFAULT_BASELINE_REL)
    counts, structural = scan_counts(root)
    violations = list(structural)
    debt = sum(r1 + r2 for r1, r2 in counts.values())
    if args.emit_baseline:
        if violations:
            return {"violations": violations, "exit": 1,
                    "summary": "refused to emit: structural errors above"}
        emit_baseline(counts, baseline_path)
        return {"violations": [], "exit": 0,
                "summary": f"emitted {baseline_path} ({len(counts)} files scanned)"}
    if not baseline_path.is_file():
        if debt:
            violations.append({"kind": "no-baseline",
                               "file": baseline_path.as_posix(),
                               "detail": "debt present but no ledger at "
                                         f"{baseline_path}"})
    else:
        try:
            entries = load_baseline(baseline_path)
        except (yaml.YAMLError, OSError, ValueError) as exc:
            violations.append({"kind": "baseline-parse",
                               "file": baseline_path.as_posix(),
                               "detail": str(exc)})
        else:
            violations.extend(compare(counts, entries))
    violations.extend(mapping_violations(root))
    exit_code = 1 if violations else 0
    clean = "clean" if not violations else f"{len(violations)} violation(s)"
    return {"violations": violations, "exit": exit_code,
            "summary": f"{clean}; {len(counts)} files scanned, {debt} flagged units"}


def _print_report(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for v in payload["violations"]:
        print(f"{v['kind']}: {v['file']}: {v['detail']}")
    print(f"comment-hygiene: {payload['summary']}")


def main(argv: list[str] | None = None) -> int:
    payload = build_report(argv)
    _print_report(payload, "--json" in (argv or sys.argv[1:]))
    return payload["exit"]


if __name__ == "__main__":
    sys.exit(main())
