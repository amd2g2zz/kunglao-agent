# gc-harness/code_gc.py — the code rot sweep leg (#735 v1). Report-only:
# scan writes nothing, deletes nothing, edits nothing — there is no apply
# flag to remove. Identity/status/linkage fields only (no scores, no
# embeddings — the spec-of-record prohibition list).
#
# Detection classes (two-observer keep-alive: any single witness keeps a
# subject alive):
#   B dead_local     CONFIRMED  ruff F401/F841 over the code trees; every
#                               finding is a candidate.
#   C orphan_module  SUSPECT    a scripts/tools/hooks module whose stem and
#                               path forms hit NO declared surface file
#                               (tripwire).
#   A dead_symbol    SUSPECT    a top-level def/class whose file has no
#                               surface hit (dispatch-surface liveness:
#                               agents/skills dispatch keeps every symbol
#                               of a surfaced file alive), whose bare name
#                               occurs nowhere outside its own def line
#                               across code+tests+surfaces, and whose
#                               GitNexus incoming-call probe is no witness
#                               (absent/stale index fails open — evidence
#                               only, never a DEAD input on its own).
#   D                           out of scope in v1 (named follow-up).
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

LEG = "code_gc"
CODE_SUBDIRS = ("scripts", "tools", "hooks", "gc-harness")
INVENTORY_SUBDIRS = ("scripts", "tools", "hooks")
RUFF_SELECT = ("F401", "F841")
RUFF_TIMEOUT = 300
GITNEXUS_TIMEOUT = 60
TEXT_SUFFIXES = (".py", ".md", ".yaml", ".yml")

#: surfaces that keep modules/symbols alive (config code.surfaces overrides)
DEFAULT_SURFACES = (
    "scripts/mechanisms.yaml",
    "deploy-manifest.yaml",
    "tools/_INDEX.ext.yaml",
    "scripts/README.md",
    "agents/*.md",
    "skills/**",
    "hooks/*.py",
    "tests/**",
    "gc-harness/**",
)

RUFF_LINE_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?P<col>\d+): "
    r"(?P<code>[A-Z]+\d+) (?P<msg>.+)$")
BACKTICK_RE = re.compile(r"`([^`]+)`")
SHA40_RE = re.compile(r"\b[0-9a-f]{40}\b")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _surfaces(cfg: dict) -> tuple[str, ...]:
    code = cfg.get("code")
    declared = code.get("surfaces") if isinstance(code, dict) else None
    if (isinstance(declared, list) and declared
            and all(isinstance(s, str) and s for s in declared)):
        return tuple(declared)
    return DEFAULT_SURFACES


def _expand(root: Path, pattern: str) -> list[str]:
    """Repo-relative file paths for one surface pattern (missing → [])."""
    if pattern.endswith("/**"):
        base = root / pattern[:-3]
        if not base.is_dir():
            return []
        return [p.relative_to(root).as_posix() for p in sorted(base.rglob("*"))
                if p.is_file() and "__pycache__" not in p.parts]
    exact = root / pattern
    if exact.is_file():
        return [exact.relative_to(root).as_posix()]
    try:
        return [p.relative_to(root).as_posix() for p in sorted(root.glob(pattern))
                if p.is_file() and "__pycache__" not in p.parts]
    except (ValueError, OSError):
        return []


def _surface_files(root: Path, patterns: tuple[str, ...]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for pattern in patterns:
        for rel in _expand(root, pattern):
            if rel in seen:
                continue
            text = _read(root / rel)
            if text is not None:
                seen[rel] = text
    return sorted(seen.items())


def _iter_py(root: Path, subdirs: tuple[str, ...]) -> list[str]:
    out = []
    for sub in subdirs:
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if p.is_file() and "__pycache__" not in p.parts:
                out.append(p.relative_to(root).as_posix())
    return out


# ---------- class B: dead_local (CONFIRMED) ----------

def _ruff_command() -> list[str] | None:
    """Same-venv ruff first, PATH fallback, else None (fail-open skip)."""
    try:
        probe = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                               capture_output=True, text=True, timeout=60)
        if probe.returncode == 0:
            return [sys.executable, "-m", "ruff"]
    except (OSError, subprocess.TimeoutExpired):
        pass
    exe = shutil.which("ruff")
    return [exe] if exe else None


def class_b(root: Path) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    cmd = _ruff_command()
    if cmd is None:
        return [], ["warn: ruff unavailable — dead_local sweep skipped"]
    targets = [sub for sub in CODE_SUBDIRS if (root / sub).is_dir()]
    if not targets:
        return [], []
    try:
        proc = subprocess.run(
            cmd + ["check", "--no-cache", "--no-fix",
                   "--select", ",".join(RUFF_SELECT),
                   "--output-format", "concise", *targets],
            cwd=str(root), capture_output=True, text=True,
            timeout=RUFF_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], [f"warn: ruff failed ({exc}) — dead_local sweep skipped"]
    if proc.returncode not in (0, 1):  # 1 = findings exist (expected)
        return [], [f"warn: ruff rc={proc.returncode} — dead_local sweep skipped"]
    candidates = []
    for line in proc.stdout.splitlines():
        m = RUFF_LINE_RE.match(line.strip())
        if not m:
            continue
        sm = BACKTICK_RE.search(m.group("msg"))
        candidates.append({
            "class": "dead_local", "tier": "CONFIRMED",
            "path": m.group("path").replace("\\", "/"),
            "line": int(m.group("line")),
            "symbol": sm.group(1) if sm else m.group("code"),
            "evidence": f"ruff {m.group('code')}",
        })
    return candidates, notes


# ---------- class C: orphan_module tripwire (SUSPECT) ----------

def _module_tokens(rel: str) -> tuple[str, ...]:
    """Stem + file name + path forms, case-folded and -/_ folded."""
    posix = rel.replace("\\", "/").lower()
    name = posix.rsplit("/", 1)[-1]
    stem = name[:-3] if name.endswith(".py") else name
    return (stem, name, posix,
            stem.replace("-", "_"), stem.replace("_", "-"))


def _first_surface_hit(tokens: tuple[str, ...],
                       surfaces: list[tuple[str, str]]) -> str | None:
    for srel, text in surfaces:
        low = text.lower()
        if any(t in low for t in tokens):
            return srel
    return None


def class_c(inventory: list[str],
            surfaces: list[tuple[str, str]]) -> tuple[list[dict], dict[str, str | None]]:
    hits: dict[str, str | None] = {}
    candidates = []
    for rel in inventory:
        tokens = _module_tokens(rel)
        hit = _first_surface_hit(tokens, surfaces)
        hits[rel] = hit
        if hit is None:
            stem = tokens[0]
            candidates.append({
                "class": "orphan_module", "tier": "SUSPECT",
                "path": rel, "line": None, "symbol": stem,
                "evidence": "no surface hits",
            })
    return candidates, hits


# ---------- class A: dead_symbol (SUSPECT, evidence-only third observer) ----------

def _top_level_symbols(path: Path) -> list[tuple[str, int]]:
    text = _read(path)
    if text is None:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    return [(n.name, n.lineno) for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]


def _witness(name: str, def_rel: str, def_line: int,
             space: list[tuple[str, str]]) -> str | None:
    """First file holding the bare name outside the def line itself."""
    for rel, text in space:
        if rel == def_rel:
            for i, ln in enumerate(text.splitlines(), 1):
                if i != def_line and name in ln:
                    return rel
        elif name in text:
            return rel
    return None


def _gitnexus_probe(root: Path, name: str) -> tuple[str, str]:
    """Incoming-call observer: (verdict, index-commit-if-visible).
    Absent/broken index fails open as 'unavailable' — evidence only."""
    runner = root / ".gitnexus" / "run.cjs"
    if not runner.is_file():
        return "unavailable", ""
    try:
        proc = subprocess.run(
            ["node", str(runner), "context", name, "--repo", str(root)],
            cwd=str(root), capture_output=True, text=True,
            timeout=GITNEXUS_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable", ""
    if proc.returncode != 0:
        return "unavailable", ""
    # the probe executes the SCANNED repo's run.cjs — trusted repos only
    out = proc.stdout or ""
    commit_m = SHA40_RE.search(out)
    commit = commit_m.group(0) if commit_m else ""
    low = out.lower()
    if not out.strip() or "0 incoming" in low or "no incoming" in low \
            or "no results" in low or "no callers" in low:
        return "zero-incoming", commit
    return "witness", commit


def _gate_space(root: Path,
                surfaces: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Gate-2 search space: surfaces + code trees + tests (name witnesses)."""
    space: dict[str, str] = dict(surfaces)
    for rel in _iter_py(root, CODE_SUBDIRS):
        space.setdefault(rel, _read(root / rel) or "")
    for rel in _expand(root, "tests/**"):
        if rel not in space:
            text = _read(root / rel)
            if text is not None:
                space[rel] = text
    return sorted(space.items())


def class_a(hits: dict[str, str | None], root: Path,
            surfaces: list[tuple[str, str]]) -> tuple[list[dict], list[str]]:
    ordered = _gate_space(root, surfaces)
    candidates, ok_lines = [], []
    for rel in sorted(hits):
        syms = _top_level_symbols(root / rel)
        if not syms:
            continue
        hit = hits[rel]
        if hit is not None:
            ok_lines.append(
                f"ok: {rel} {len(syms)} symbols alive (surface hit: {hit})")
            continue
        for name, lineno in syms:
            if _witness(name, rel, lineno, ordered) is not None:
                continue
            verdict, commit = _gitnexus_probe(root, name)
            if verdict == "witness":
                continue
            evidence = f"no refs outside def; gitnexus={verdict}"
            if commit:
                evidence += f"; index {commit[:12]}"
            candidates.append({
                "class": "dead_symbol", "tier": "SUSPECT",
                "path": rel, "line": lineno, "symbol": name,
                "evidence": evidence,
            })
    return candidates, ok_lines


# ---------- report ----------

def _head(root: Path) -> str:
    r = C.git(root, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


def scan(root: Path, as_json: bool) -> int:
    cfg = C.load_config(root)
    surfaces = _surface_files(root, _surfaces(cfg))
    notes: list[str] = []

    confirmed, notes_b = class_b(root)
    notes.extend(notes_b)

    inventory = _iter_py(root, INVENTORY_SUBDIRS)
    suspects_c, hits = class_c(inventory, surfaces)
    suspects_a, ok_lines = class_a(hits, root, surfaces)

    candidates = confirmed + suspects_c + suspects_a
    counts = {"confirmed": len(confirmed),
              "suspect": len(suspects_c) + len(suspects_a),
              "total": len(candidates)}

    if as_json:
        print(json.dumps({
            "leg": LEG, "generated": C.today(), "head": _head(root),
            "scopes": list(CODE_SUBDIRS), "candidates": candidates,
            "counts": counts,
        }, indent=2))
        for note in notes:
            print(note, file=sys.stderr)
        return 0

    for c in confirmed:
        rule = str(c["evidence"]).rsplit(" ", 1)[-1]
        print(f"CONFIRMED: {c['path']}:{c['line']} {c['symbol']} ({rule})")
    for c in suspects_c:
        print(f"SUSPECT: {c['path']} orphan module (no surface hits)")
    for c in suspects_a:
        print(f"SUSPECT: {c['path']}:{c['line']} {c['symbol']} (dead_symbol)")
    for line in ok_lines:
        print(line)
    for note in notes:
        print(note, file=sys.stderr)
    print(f"summary: {counts['confirmed']} confirmed, {counts['suspect']} "
          f"suspect (report-only — no changes made)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="code_gc", description="code rot sweep (report-only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("scan", help="report dead-code candidates; writes nothing")
    sp.add_argument("--json", action="store_true", dest="as_json",
                    help="emit the JSON report instead of text lines")
    a = p.parse_args(argv)
    if a.cmd == "scan":
        return scan(C.repo_root(), a.as_json)
    return 2


if __name__ == "__main__":
    sys.exit(main())
