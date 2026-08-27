# gc-harness/spec_gc.py — Spec lifecycle controller (#720 v1).
# Creation gate (search) + Rule 1 (orphan → ARCHIVED, apply only)
# + Rule 2 (zero tests → SUSPECT, report only) + Rule 3 (duplicates,
# report only — never auto-merge). init registers, never adjudicates.
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

CODE_SUBDIRS = ("scripts", "hooks", "tools", "gc-harness")


def _next_id(entries: list[dict]) -> str:
    nums = [int(e["id"].rsplit("-", 1)[-1]) for e in entries
            if re.fullmatch(r"SPEC-\d+", str(e.get("id", "")))]
    return f"SPEC-{(max(nums) + 1) if nums else 1:03d}"


def init_registry(root: Path) -> int:
    """Register every openspec/changes/<dir> with a proposal.md as ACTIVE.
    Registration only — no adjudication (spec D5)."""
    entries = C.load_registry(root, "specs")
    known = {e.get("path") for e in entries}
    base = root / "openspec" / "changes"
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if not d.is_dir() or not (d / "proposal.md").is_file():
                continue
            rel = (d / "proposal.md").relative_to(root).as_posix()
            if rel in known:
                continue
            entries.append({
                "id": C.stem_token(rel).upper(), "path": rel,
                "status": "active",
                "created": C.today(), "last_modified": C.today(),
                "linked_tests": [],
            })
            print(f"registered: {rel} -> ACTIVE")
    C.save_registry(root, "specs", entries)
    print(f"OK: {len(entries)} registered (registration only, no adjudication)")
    return 0


def search(root: Path, query: str) -> int:
    """Creation gate: existing ACTIVE specs matching the query + decision hint."""
    entries = [e for e in C.load_registry(root, "specs")
               if str(e.get("status", "")).lower() == "active"]
    q = (query or "").lower().strip()
    matches = [e for e in entries
               if q and (q in str(e.get("id", "")).lower()
                         or q in C.stem_token(str(e.get("path", ""))).lower())]
    print("Existing:")
    if matches:
        for e in matches:
            print(f"  {e['id']}  {e.get('path')}  (similar topic)")
        print("\nDecision: modify existing (default) | create (new domain capability only)")
    else:
        print("  (no matching active spec)")
        print("\nDecision: create (no existing spec covers this topic)")
    return 0


def scan(root: Path, apply: bool) -> int:
    """Rule 1/2/3 over the registry. Dry-run report by default; --apply
    writes only ARCHIVED status transitions (SUSPECT/duplicates never write)."""
    cfg = C.load_config(root).get("spec", {})
    orphan_days = int(cfg.get("orphan_days", 90))
    entries = C.load_registry(root, "specs")
    if not entries:
        print("OK: empty registry — run `init` first (fail-open, nothing scanned)")
        return 0
    stems: dict[str, list[str]] = {}
    for e in entries:
        stems.setdefault(
            C.norm_stem(C.stem_token(str(e.get("path", "")))), []).append(
                str(e.get("id")))
    for e in entries:
        sid = str(e.get("id", "?"))
        token = C.stem_token(str(e.get("path", "")))
        code_refs = C.grep_count(root, token, CODE_SUBDIRS)
        test_refs = C.grep_count(root, token, ("tests",))
        age = C.days_since(str(e.get("last_modified") or ""))
        status = str(e.get("status", "")).lower()
        line = (f"{sid}  refs: code={code_refs} test={test_refs} "
                f"age={age if age is not None else '?'}d  status={status}")
        # Rule 1: zero code refs AND older than orphan_days -> ARCHIVED
        if status == "active" and code_refs == 0 and age is not None \
                and age > orphan_days:
            if apply:
                e["status"] = "archived"
                print(f"ARCHIVED (applied): {line}")
            else:
                print(f"ARCHIVED (dry-run — apply to write): {line}")
        # Rule 2: zero test refs -> SUSPECT (report only, never delete)
        elif code_refs > 0 and test_refs == 0:
            print(f"SUSPECT (no test linkage — report only): {line}")
        else:
            print(f"ok: {line}")
        # Rule 3: duplicates -> report only (normalized stems collide)
        siblings = [i for i in stems.get(
            C.norm_stem(C.stem_token(str(e.get("path", "")))), []) if i != sid]
        if siblings or len(stems.get(
                C.norm_stem(C.stem_token(str(e.get("path", "")))), [])) > 1:
            dup_key = C.norm_stem(C.stem_token(str(e.get("path", ""))))
            group = stems.get(dup_key, [])
            if len(group) > 1:
                others = [i for i in group if i != sid]
                if others:
                    print(f"DUPLICATE (report only, one-off manual merge): "
                          f"{sid} <-> {', '.join(others)} [stem={dup_key}]")
    if apply:
        C.save_registry(root, "specs", entries)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="spec_gc — Spec lifecycle controller (#720)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("query", nargs="?", default="")
    sub.add_parser("init")
    sc = sub.add_parser("scan"); sc.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)
    root = C.repo_root()
    if a.cmd == "search":
        return search(root, a.query)
    if a.cmd == "init":
        return init_registry(root)
    return scan(root, a.apply)


if __name__ == "__main__":
    sys.exit(main())
