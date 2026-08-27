# gc-harness/test_gc.py — Test lifecycle controller (#720 v1).
# Never judges quality; only "would deleting this lower system protection?"
# Candidates: registered last_failure > 180d, or identical test function
# names in 2+ files (no content analysis — spec-of-record prohibition).
# Quarantine: move + 30d window + restore; expire deletes only on --apply.
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

TEST_NAME_RE = re.compile(r"^\s*def (test_\w+)\(")


def _norm_id(s: str) -> str:
    """Tolerant id match: registry ids are bare (alpha), CLIs may be given
    the file stem (test_alpha) — normalize both sides."""
    s = str(s).strip().lower()
    return s[5:] if s.startswith("test_") else s


def _find(entries: list[dict], test_id: str) -> dict | None:
    want = _norm_id(test_id)
    for e in entries:
        if _norm_id(e.get("id", "")) == want:
            return e
    return None


def _collect_test_names(root: Path) -> dict[str, list[str]]:
    """test function name -> [file relpath, ...] under tests/ (skip quarantine/)."""
    names: dict[str, list[str]] = {}
    base = root / "tests"
    if not base.is_dir():
        return names
    for p in sorted(base.rglob("test_*.py")):
        if "quarantine" in p.relative_to(root).parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(root).as_posix()
        for m in TEST_NAME_RE.finditer(text):
            names.setdefault(m.group(1), []).append(rel)
    return names


def init_registry(root: Path) -> int:
    entries = C.load_registry(root, "tests")
    known = {e.get("path") for e in entries}
    base = root / "tests"
    if base.is_dir():
        for p in sorted(base.rglob("test_*.py")):
            rel = p.relative_to(root).as_posix()
            if rel in known:
                continue
            entries.append({
                "id": p.stem.replace("test_", "", 1) or p.stem,
                "path": rel, "status": "active",
                "created": C.today(), "last_modified": C.today(),
                "last_failure": None,
            })
    C.save_registry(root, "tests", entries)
    print(f"OK: {len(entries)} registered (registration only)")
    return 0


def record(root: Path, test_id: str, failed: bool) -> int:
    entries = C.load_registry(root, "tests")
    e = _find(entries, test_id)
    if e is not None:
        e["last_modified"] = C.today()
        if failed:
            e["last_failure"] = C.today()
        C.save_registry(root, "tests", entries)
        print(f"recorded: {test_id} last_failure="
              f"{e.get('last_failure') if failed else 'unchanged'}")
        return 0
    print(f"unknown test id: {test_id} (registry has "
          f"{len(entries)} entries)", file=sys.stderr)
    return 1


def scan(root: Path) -> int:
    cfg = C.load_config(root).get("test", {})
    stale_days = int(cfg.get("stale_failure_days", 180))
    entries = C.load_registry(root, "tests")
    name_map = _collect_test_names(root)
    for e in entries:
        tid = str(e.get("id", "?"))
        reasons: list[str] = []
        # condition 1: registered last_failure older than the window
        age = C.days_since(str(e.get("last_failure") or "") or None)
        if age is not None and age > stale_days:
            reasons.append(f"last_failure {age}d ago (> {stale_days}d)")
        # condition 2: identical test function name in 2+ files
        for fn, files in name_map.items():
            if len(files) > 1 and (tid in fn or fn == f"test_{tid}"):
                reasons.append(f"identical name '{fn}' in {len(files)} files")
        if reasons:
            print(f"CANDIDATE_DELETE: {tid}  ({'; '.join(reasons)})")
        else:
            print(f"ok: {tid}")
    # duplicates among unregistered files too (registry-independent surface)
    for fn, files in sorted(name_map.items()):
        if len(files) > 1:
            print(f"CANDIDATE_DELETE: {fn}  (identical name in {len(files)} files: "
                  f"{', '.join(files)})")
    return 0


def quarantine(root: Path, rel_path: str) -> int:
    src = root / rel_path
    if not src.is_file():
        print(f"not a file: {rel_path}", file=sys.stderr)
        return 1
    qdir = root / "tests" / "quarantine"
    qdir.mkdir(exist_ok=True)
    r = C.git(root, "mv", rel_path, f"tests/quarantine/{src.name}")
    if r.returncode != 0:
        print(f"git mv failed: {r.stderr.strip()}", file=sys.stderr)
        return 1
    entries = C.load_registry(root, "tests")
    hit = False
    for e in entries:
        if str(e.get("path")) == rel_path:
            e.update({"status": "quarantined",
                      "quarantined_at": C.today(),
                      "original_path": rel_path,
                      "path": f"tests/quarantine/{src.name}"})
            hit = True
    if not hit:
        entries.append({
            "id": src.stem.replace("test_", "", 1) or src.stem,
            "path": f"tests/quarantine/{src.name}",
            "status": "quarantined", "created": C.today(),
            "last_modified": C.today(), "last_failure": None,
            "quarantined_at": C.today(), "original_path": rel_path,
        })
    C.save_registry(root, "tests", entries)
    print(f"quarantined: {rel_path} -> tests/quarantine/{src.name} "
          f"(restore with: restore {src.stem.replace('test_', '', 1) or src.stem})")
    return 0


def restore(root: Path, test_id: str) -> int:
    entries = C.load_registry(root, "tests")
    e = _find(entries, test_id)
    if e is not None and e.get("status") == "quarantined":
        qpath = str(e.get("path", ""))
        orig = str(e.get("original_path") or
                   f"tests/{Path(qpath).name}")
        r = C.git(root, "mv", qpath, orig)
        if r.returncode != 0:
            print(f"git mv failed: {r.stderr.strip()}", file=sys.stderr)
            return 1
        e.update({"status": "active", "path": orig,
                  "last_modified": C.today()})
        e.pop("quarantined_at", None)
        C.save_registry(root, "tests", entries)
        print(f"restored: {qpath} -> {orig}")
        return 0
    print(f"no quarantined entry for id: {test_id}", file=sys.stderr)
    return 1


def expire(root: Path, apply: bool) -> int:
    cfg = C.load_config(root).get("test", {})
    window = int(cfg.get("quarantine_days", 30))
    entries = C.load_registry(root, "tests")
    for e in entries:
        if str(e.get("status", "")) != "quarantined":
            continue
        tid = str(e.get("id", "?"))
        age = C.days_since(str(e.get("quarantined_at") or ""))
        if age is not None and age > window:
            print(f"DELETE CANDIDATE: {tid} (quarantined {age}d > {window}d)")
            if apply:
                C.git(root, "rm", "-q", "--cached", str(e.get("path", "")))
                f = root / str(e.get("path", ""))
                if f.is_file():
                    f.unlink()
                e.update({"status": "removed", "last_modified": C.today()})
                print(f"  removed (applied): {e.get('path')}")
    if apply:
        C.save_registry(root, "tests", entries)
    return 0


def experiment(root: Path, rel_path: str) -> int:
    """Removal-experiment PROTOCOL only — no built-in mutation runner (v1)."""
    print(f"# removal experiment for {rel_path}")
    print("1. uv run mutmut run --paths-to-mutate=<module under test>   # baseline score")
    print(f"2. git mv {rel_path} tests/quarantine/")
    print("3. uv run mutmut run --paths-to-mutate=<module under test>   # without the test")
    print("4. score unchanged -> CANDIDATE_DELETE confirmed; score dropped -> restore")
    print("# (interface only — v1 does not run the experiment, per #720 design)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="test_gc — Test lifecycle controller (#720)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("scan")
    rq = sub.add_parser("record"); rq.add_argument("id"); rq.add_argument("--failed", action="store_true")
    q = sub.add_parser("quarantine"); q.add_argument("path")
    rs = sub.add_parser("restore"); rs.add_argument("id")
    ex = sub.add_parser("expire"); ex.add_argument("--apply", action="store_true")
    xp = sub.add_parser("experiment"); xp.add_argument("path")
    a = p.parse_args(argv)
    root = C.repo_root()
    return {"init": lambda: init_registry(root),
            "scan": lambda: scan(root),
            "record": lambda: record(root, a.id, a.failed),
            "quarantine": lambda: quarantine(root, a.path),
            "restore": lambda: restore(root, a.id),
            "expire": lambda: expire(root, a.apply),
            "experiment": lambda: experiment(root, a.path)}[a.cmd]()


if __name__ == "__main__":
    sys.exit(main())
