# devkit/gc/code_gc.py — the code rot sweep leg (#735 v1, #1091 witness fix).
# Report-only: scan writes nothing, deletes nothing, edits nothing — there is
# no apply flag to remove. Identity/status/linkage fields only (no scores, no
# embeddings — the spec-of-record prohibition list).
#
# Detection classes (two-observer keep-alive: any single witness keeps a
# subject alive):
#   B dead_local     CONFIRMED  ruff F401/F841 over the code trees; every
#                               finding is a candidate.
#   C unwired_module SUSPECT    a scripts/tools/hooks module that NO dispatch
#                               witness names and that NO production module
#                               imports. #1091: the witness SET was wrong —
#                               deploy-manifest.yaml (deployment), tests/**
#                               (coverage) and the inventory/catalog rows
#                               (registration) say an artifact is KNOWN, never
#                               that it is REACHED, so they are reported with
#                               the finding and never clear liveness.
#   A dead_symbol    SUSPECT    a top-level def/class of a LIVE module that no
#                               dispatch witness names, that no other module
#                               references as an identifier, that its own
#                               module never uses as an identifier (a log-tag
#                               string is not a call site), and whose GitNexus
#                               incoming-call probe is no witness (absent/stale
#                               index fails open — evidence only, never a DEAD
#                               input on its own). #1091: keep-alive is
#                               SYMBOL-level now — a witnessed file no longer
#                               keeps every symbol inside it alive (84% of the
#                               old verdicts rested on one manifest row).
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
CODE_SUBDIRS = ("scripts", "tools", "hooks", "devkit/gc")
INVENTORY_SUBDIRS = ("scripts", "tools", "hooks")
#: modules whose text may witness a CALL (source of the caller index)
CALLER_SUBDIRS = ("scripts", "tools", "hooks", "devkit")
#: the harness's own source is never a liveness witness (self-reference)
_SELF_PREFIX = "devkit/gc/"
RUFF_SELECT = ("F401", "F841")
RUFF_TIMEOUT = 300
GITNEXUS_TIMEOUT = 60
#: the per-symbol GitNexus observer is one subprocess per probe: cap it and
#: say so (S24 replaces this with a single index census + freshness gate)
GITNEXUS_PROBE_CAP = 25
IDENT_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: dispatch witnesses — a hit here means something at runtime REACHES the
#: subject (the agent-facing faces, the hook wiring table, the CI/devkit
#: runners, the execution registry). config code.liveness_surfaces overrides.
DEFAULT_LIVENESS_SURFACES = (
    "scripts/mechanisms.yaml",
    "scripts/wire_up_settings.py",
    "agents/*.md",
    "skills/**",
    "hooks/**",
    "devkit/**",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "tools/_INDEX.yaml",
)

#: declaration witnesses — deployment / registration / coverage evidence,
#: ordered so the likeliest row is found first. Never a keep-alive (#1091);
#: reported as the "declared:" attribution so disposal reads in one line.
DEFAULT_DECLARATION_SURFACES = (
    "deploy-manifest.yaml",
    "release-manifest.yaml",
    "scripts/README.md",
    "tools/_INDEX.ext.yaml",
    "tools/_index-*.md",
    "tools/_INDEX.md",
    "pyproject.toml",
    "references/**",
    "tests/**",
    "docs/**",
    "openspec/**",
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


def _surface_key(cfg: dict, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    code = cfg.get("code")
    declared = code.get(key) if isinstance(code, dict) else None
    if (isinstance(declared, list) and declared
            and all(isinstance(s, str) and s for s in declared)):
        return tuple(declared)
    return default


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


def _surface_space(root: Path, patterns: tuple[str, ...],
                   skip_self: bool = False) -> dict[str, str]:
    """rel -> raw text for every file a witness pattern reaches."""
    space: dict[str, str] = {}
    for pattern in patterns:
        for rel in _expand(root, pattern):
            if rel in space or (skip_self and rel.startswith(_SELF_PREFIX)):
                continue
            text = _read(root / rel)
            if text is not None:
                space[rel] = text
    return space


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


# ---------- subject facts (one AST pass per module) --------------------------

def _module_facts(root: Path, rels: list[str]) -> dict[str, dict]:
    """rel -> {imports, names, symbols}: what a module CONSUMES and EXPOSES.

    `names` is the identifier set (Name/Attribute/arg/keyword) — a mention
    inside a string literal (the log-tag shape) is deliberately not a
    witness, and neither is a prose mention in a comment.
    """
    facts: dict[str, dict] = {}
    for rel in rels:
        text = _read(root / rel) or ""
        try:
            tree = ast.parse(text)
        except SyntaxError:
            facts[rel] = {"imports": set(), "names": set(), "symbols": []}
            continue
        imports: set[str] = set()
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
            elif isinstance(node, ast.Import):
                imports.update((a.name or "").rsplit(".", 1)[-1]
                               for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.rsplit(".", 1)[-1])
                imports.update(a.name for a in node.names)
        facts[rel] = {
            "imports": imports, "names": names,
            "symbols": [(n.name, n.lineno) for n in tree.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                          ast.ClassDef))],
        }
    return facts


def _module_tokens(rel: str) -> tuple[str, ...]:
    """Stem + file name + path forms, case-folded and -/_ folded."""
    posix = rel.replace("\\", "/").lower()
    name = posix.rsplit("/", 1)[-1]
    stem = name[:-3] if name.endswith(".py") else name
    return (stem, name, posix,
            stem.replace("-", "_"), stem.replace("_", "-"))


def _first_hit(rel: str, space: list[tuple[str, str]]) -> str | None:
    """First witness file (other than the subject itself) naming the module."""
    tokens = _module_tokens(rel)
    for srel, low in space:
        if srel == rel:
            continue
        if any(t in low for t in tokens):
            return srel
    return None


def _importers(rel: str, facts: dict[str, dict], subjects: list[str]) -> list[str]:
    """Production modules with a real `import`/`from` edge to `rel`."""
    stem, name = Path(rel).stem, Path(rel).name
    return [r for r in subjects
            if r != rel and (stem in facts[r]["imports"] or name in facts[r]["imports"])]


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


# ---------- class C: unwired_module (SUSPECT) + liveness map ----------------

def _declared_in(root: Path, rel: str, patterns: tuple[str, ...]) -> str:
    """First declaration witness (registration/deployment/coverage row).

    Read lazily in pattern order and never returned as a keep-alive: it is
    disposal context only (#1091).
    """
    tokens = _module_tokens(rel)
    for pattern in patterns:
        for srel in _expand(root, pattern):
            if srel == rel:
                continue
            text = _read(root / srel)
            if text is None:
                continue
            low = text.lower()
            if any(t in low for t in tokens):
                return srel
    return "nowhere"


Liveness = dict[str, tuple[str, str]]


def _liveness(inventory: list[str], facts: dict[str, dict],
              liveness: list[tuple[str, str]]) -> tuple[Liveness, list[str]]:
    """Fixpoint over the import graph.

    Dispatch witnesses are the roots. An import edge propagates liveness only
    from an ALREADY-live importer (scripts/relib_audit.py's "wired transitively"
    rule) — a module whose sole consumer is itself unwired stays unwired, which
    is what keeps scripts/scheduling_selection.py from being cleared by
    scripts/intelligent_scheduling.py.
    """
    live: Liveness = {}
    for rel in inventory:
        hit = _first_hit(rel, liveness)
        if hit is not None:
            live[rel] = ("dispatch_surface", hit)
    pending = [rel for rel in inventory if rel not in live]
    while pending:
        promoted: Liveness = {}
        for rel in pending:
            for imp in _importers(rel, facts, inventory):
                if imp in live:
                    promoted[rel] = ("import_edge", imp)
                    break
        if not promoted:
            break
        live.update(promoted)
        pending = [rel for rel in pending if rel not in promoted]
    return live, sorted(pending)


def class_c(root: Path, inventory: list[str], facts: dict[str, dict],
            liveness: list[tuple[str, str]],
            decl_patterns: tuple[str, ...]) -> tuple[list[dict], Liveness, list[str]]:
    """Liveness map: rel -> (witness kind, witness evidence)."""
    live, unwired = _liveness(inventory, facts, liveness)
    suspects: list[dict] = []
    notes: list[str] = []
    for rel in unwired:
        declared = _declared_in(root, rel, decl_patterns)
        suspects.append({
            "class": "orphan_module", "tier": "SUSPECT",
            "path": rel, "line": None, "symbol": Path(rel).stem,
            "evidence": f"no dispatch witness, no live importer; declared: {declared}",
        })
    if not live:
        notes.append("warn: no module carries a liveness witness — "
                     "witness surfaces are likely misconfigured")
    return suspects, live, notes


# ---------- class A: dead_symbol (SUSPECT, evidence-only third observer) ----

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


def _reference_index(facts: dict[str, dict]) -> dict[str, set[str]]:
    """symbol name -> modules holding it as an identifier (call sites)."""
    index: dict[str, set[str]] = {}
    for rel, fact in facts.items():
        for name in fact["names"]:
            index.setdefault(name, set()).add(rel)
    return index


def class_a(root: Path, live: Liveness, facts: dict[str, dict],
            liveness_tokens: set[str]) -> tuple[list[dict], list[str], dict, list[str]]:
    """Per-symbol keep-alive over the LIVE modules only — an unwired module is
    already reported once by class C, so its faces are not enumerated."""
    refs = _reference_index(facts)
    candidates: list[dict] = []
    ok_lines: list[str] = []
    tally = {"dispatch_surface": 0, "external_caller": 0,
             "internal_use": 0, "gitnexus": 0}
    notes: list[str] = []
    probes = 0
    for rel in sorted(live):
        kind, witness = live[rel]
        symbols = facts[rel]["symbols"]
        if not symbols:
            continue
        alive = 0
        for name, lineno in symbols:
            if name in liveness_tokens:
                tally["dispatch_surface"] += 1
                alive += 1
                continue
            callers = {r for r in refs.get(name, ()) if r != rel}
            if callers:
                tally["external_caller"] += 1
                alive += 1
                continue
            if name in facts[rel]["names"]:
                tally["internal_use"] += 1
                alive += 1
                continue
            verdict, commit = ("unavailable", "")
            if probes < GITNEXUS_PROBE_CAP:
                probes += 1
                verdict, commit = _gitnexus_probe(root, name)
            if verdict == "witness":
                tally["gitnexus"] += 1
                alive += 1
                continue
            evidence = "no caller, no dispatch mention"
            if commit:
                evidence += f"; gitnexus index {commit[:12]}"
            candidates.append({
                "class": "dead_symbol", "tier": "SUSPECT",
                "path": rel, "line": lineno, "symbol": name,
                "evidence": f"{evidence}; gitnexus={verdict}",
            })
        ok_lines.append(f"ok: {rel} {alive}/{len(symbols)} symbols alive "
                        f"(witness: {kind} {witness})")
    if probes >= GITNEXUS_PROBE_CAP:
        notes.append(f"note: gitnexus incoming-call observer capped at "
                     f"{GITNEXUS_PROBE_CAP} probes this run — uncaptured "
                     "candidates stay SUSPECT (S24 census replaces it)")
    return candidates, ok_lines, tally, notes


# ---------- report ----------

def _head(root: Path) -> str:
    r = C.git(root, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


def scan(root: Path, as_json: bool) -> int:
    cfg = C.load_config(root)
    liveness_pats = _surface_key(cfg, "liveness_surfaces",
                                 DEFAULT_LIVENESS_SURFACES)
    decl_pats = _surface_key(cfg, "declaration_surfaces",
                             DEFAULT_DECLARATION_SURFACES)
    liveness_files = _surface_space(root, liveness_pats, skip_self=True)
    liveness = [(rel, text.lower()) for rel, text in sorted(liveness_files.items())]
    liveness_tokens: set[str] = set()
    for text in liveness_files.values():
        liveness_tokens.update(IDENT_TOKEN_RE.findall(text))

    inventory = _iter_py(root, INVENTORY_SUBDIRS)
    callers = [rel for rel in _iter_py(root, CALLER_SUBDIRS)
               if not rel.startswith(_SELF_PREFIX)]
    facts = _module_facts(root, sorted(set(inventory) | set(callers)))

    notes: list[str] = []
    confirmed, notes_b = class_b(root)
    notes.extend(notes_b)

    suspects_c, live, notes_c = class_c(root, inventory, facts, liveness, decl_pats)
    notes.extend(notes_c)
    suspects_a, ok_lines, face_tally, notes_a = class_a(
        root, live, facts, liveness_tokens)
    notes.extend(notes_a)

    candidates = confirmed + suspects_c + suspects_a
    counts = {"confirmed": len(confirmed),
              "suspect": len(suspects_c) + len(suspects_a),
              "total": len(candidates)}
    faces_total = sum(len(facts[rel]["symbols"]) for rel in inventory)
    keepalive = {
        "modules": {
            "total": len(inventory), "live": len(live),
            "unwired": len(suspects_c),
            "by_witness": _module_tally(live),
        },
        "faces": {
            "total": faces_total,
            "alive": sum(face_tally.values()),
            "suspect": len(suspects_a),
            "by_witness": face_tally,
        },
        "never_clears": list(decl_pats),
    }

    if as_json:
        print(json.dumps({
            "leg": LEG, "generated": C.today(), "head": _head(root),
            "scopes": list(CODE_SUBDIRS), "candidates": candidates,
            "counts": counts, "keepalive": keepalive,
        }, indent=2))
        for note in notes:
            print(note, file=sys.stderr)
        return 0

    for c in confirmed:
        rule = str(c["evidence"]).rsplit(" ", 1)[-1]
        print(f"CONFIRMED: {c['path']}:{c['line']} {c['symbol']} ({rule})")
    for c in suspects_c:
        print(f"SUSPECT: {c['path']} unwired module ({c['evidence']})")
    for c in suspects_a:
        print(f"SUSPECT: {c['path']}:{c['line']} {c['symbol']} (dead_symbol)")
    for line in ok_lines:
        print(line)
    for note in notes:
        print(note, file=sys.stderr)
    print(f"keepalive: modules {keepalive['modules']['live']}/"
          f"{keepalive['modules']['total']} live "
          f"{keepalive['modules']['by_witness']}, faces "
          f"{keepalive['faces']['alive']}/{faces_total} alive "
          f"{keepalive['faces']['by_witness']}")
    print(f"summary: {counts['confirmed']} confirmed, {counts['suspect']} "
          f"suspect (report-only — no changes made)")
    return 0


def _module_tally(live: dict[str, tuple[str, str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for kind, _ in live.values():
        out[kind] = out.get(kind, 0) + 1
    return out


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
