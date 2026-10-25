#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_corpus_lint.py — the #816 measurement-integrity corpus lint.

Owner ruling (2026-10-24): an RE (逆向) mission must NEVER be solvable by
reading the target's source. A unit whose material class is black-box
(RE-intent: the analysis subject is a binary/net surface) is INVALID the
moment any target-semantics source file (.rs/.c/.py/...) shows up inside
its ``target/`` tree — the agent would be handed the answer sheet inside
the envelope. Source-readable units (smoke/chain/misdirection and the
text-face release families; win-pe-kdf's goal NAMES its source) ship
source BY DESIGN and stay green.

Per unit (every task.yaml under the corpus roots):
  R1 material_class declared, value in {source-readable, black-box}
     — an unclassified unit is an unlintable unit (unlintable = red);
  R2 the declared class matches the family registry below
     — self-declared black-box shortcuts fail loudly;
  R3 black-box + source under target/ → CONTAMINATED[TARGET_SOURCE]
     — the #816 fail-red face (the tf-novelvm/tf-novelcipher defect).

The lint also reports the black-box (RE-capability-admissible) unit
count: RE capability metrics count black-box material ONLY (the
source-readable face measures source-reading, not reverse engineering).

Usage:
  python scripts/eval_corpus_lint.py [--corpus-root <dir>] ...
Exit codes: 0 clean / 1 contaminated-or-invalid.

stdlib + PyYAML only (house eval-script rule).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

MATERIAL_CLASSES: tuple[str, ...] = ("source-readable", "black-box")

# family -> material class (the corpus registry; mirrors eval_contract
# FAMILY_CONTRACT target_surface with the #816 ruling applied: text-face
# analysis-subject families read their source BY DESIGN, native/net/
# blocked-path families are black-box).
FAMILY_MATERIAL_CLASS: dict[str, str] = {
    # smoke (eval-v1)
    "go-arx": "source-readable",
    "js-sign": "source-readable",
    "py-derive": "source-readable",
    # release, web/net text faces (the committed bundle IS the subject)
    "web-pack-sign": "source-readable",
    "mod-crypto-js": "source-readable",
    "req-sign": "source-readable",
    "net-verify-license": "source-readable",
    # release, native ladder — binary RE, never source
    "arm-native-kdf": "black-box",
    "win-pe-kdf": "source-readable",  # goal names target/sample_kdf.go
    "smc-x86": "black-box",
    "mod-crypto-native": "black-box",
    # release, combat matrix (#518)
    "web-token": "black-box",
    "web-pow-lite": "black-box",
    "apk-static-license": "black-box",
    "web-anticrawl": "black-box",
    "apk-webview-attest": "black-box",
    "rust-apk-beacon": "black-box",
    # misdirection (eval-v1.2) — the decoy/bundle source IS the subject
    "env-misattr-js": "source-readable",
    "env-misattr-net": "source-readable",
    "key-rotation-js": "source-readable",
    "key-rotation-net": "source-readable",
    "decoy-marker-js": "source-readable",
    "decoy-marker-go": "source-readable",
    # toolflex (eval-v1.3) + blocked-path constructions — black-box
    "tf-chain2": "black-box",
    "tf-chain3": "black-box",
    "tf-chain4": "black-box",
    "tf-novelvm": "black-box",
    "tf-novelcipher": "black-box",
    "tf-hardwall-beacon": "black-box",
    "tf-hardwall-ledger": "black-box",
    # chain (eval-v1.4) — the obfuscated bundle IS the subject
    "chain-js": "source-readable",
    "chain-py": "source-readable",
    "chain-go": "source-readable",
}

# source extensions that implement target semantics (#816 sweep set)
SOURCE_EXTS: frozenset[str] = frozenset({
    ".rs", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".py", ".go", ".js",
    ".mjs", ".cjs", ".ts", ".tsx", ".kt", ".kts", ".java", ".swift", ".m",
    ".mm", ".rb", ".php", ".cs", ".lua", ".pl", ".zig", ".v",
})


def corpus_roots(explicit: list[Path], repo: Path) -> list[Path]:
    """The corpus faces: explicit --corpus-root args win; else the eval
    root (KUNGLAO_EVAL_ROOT or repo eval/) task tiers + the operator-local
    blocked-path units when present."""
    if explicit:
        return explicit
    override = os.environ.get("KUNGLAO_EVAL_ROOT", "")
    root = Path(override) if override else repo / "eval"
    roots = [root / "v1" / "tasks"]
    bp = repo / "experiments" / "blocked-path-units"
    if bp.is_dir():
        roots.append(bp)
    return [r for r in roots if r.is_dir()]


def iter_units(roots: list[Path]) -> list[Path]:
    """Every directory carrying a task.yaml (any nesting depth below a
    corpus root), sorted."""
    out: list[Path] = []
    for r in roots:
        out += sorted(d for d in r.rglob("task.yaml"))
    return out


def target_source_files(unit_dir: Path) -> list[str]:
    """Source files under the unit's target/ tree (posix relative paths)."""
    tgt = unit_dir / "target"
    if not tgt.is_dir():
        return []
    return sorted(
        p.relative_to(unit_dir).as_posix()
        for p in tgt.rglob("*")
        if p.is_file() and p.suffix.lower() in SOURCE_EXTS
    )


def lint_unit(task_path: Path) -> list[str]:
    """R1/R2/R3 for one unit; returns violation rows (empty = clean)."""
    try:
        task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"CONTAMINATED[TASK_UNREADABLE] {task_path}: {exc}"]
    if not isinstance(task, dict):
        return [f"CONTAMINATED[TASK_UNREADABLE] {task_path}: not a mapping"]
    uid = task.get("task_id") or task_path.parent.name
    where = task_path.parent
    family = task.get("family")
    rows: list[str] = []

    declared = task.get("material_class")
    if not declared:
        rows.append(
            f"CONTAMINATED[UNDECLARED] {uid}: material_class missing — "
            "an unclassified unit is an unlintable unit (#816)")
        declared = None
    elif declared not in MATERIAL_CLASSES:
        rows.append(
            f"CONTAMINATED[BAD_DECL] {uid}: material_class {declared!r} "
            f"outside {list(MATERIAL_CLASSES)}")
        declared = None

    registry = FAMILY_MATERIAL_CLASS.get(family)
    if family is not None and registry is None:
        rows.append(
            f"CONTAMINATED[UNREGISTERED_FAMILY] {uid}: family {family!r} "
            "not in the #816 registry — fail-closed, register it")
    if declared is not None and registry is not None and declared != registry:
        rows.append(
            f"CONTAMINATED[REGISTRY_MISMATCH] {uid}: declares "
            f"{declared!r}, family {family!r} registry says {registry!r}")

    eff = declared or registry
    srcs = target_source_files(where)
    if eff == "black-box" and srcs:
        rows.append(
            f"CONTAMINATED[TARGET_SOURCE] {uid}: black-box unit ships "
            f"target source {srcs} — an RE mission solved by reading the "
            "answer sheet (#816)")
    return rows


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(prog="eval_corpus_lint")
    ap.add_argument("--corpus-root", action="append", default=None,
                    help="corpus root (repeatable; default: the eval root "
                         "+ operator-local blocked-path units)")
    args = ap.parse_args(argv)
    explicit = [Path(p) for p in (args.corpus_root or [])]
    roots = corpus_roots(explicit, repo)
    if not roots:
        # the corpus is operator-LOCAL since #759 — an absent corpus is a
        # skip, not a violation (CI carries no eval/ tree); an EXPLICIT
        # root that resolves to nothing stays a hard error.
        if explicit:
            print("eval_corpus_lint: explicit corpus root(s) missing: "
                  f"{[str(r) for r in explicit]}")
            return 1
        print("eval_corpus_lint: corpus not present on this host "
              "(local-only since #759) — skipped")
        return 0

    units = iter_units(roots)
    if not units:
        print("eval_corpus_lint: no task units found under "
              f"{[str(r) for r in roots]}")
        return 1

    violations: list[str] = []
    classes: dict[str, int] = {"source-readable": 0, "black-box": 0}
    for tp in units:
        violations += lint_unit(tp)
        try:
            task = yaml.safe_load(tp.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        mc = (task or {}).get("material_class")
        if mc in classes:
            classes[mc] += 1

    if violations:
        print("\n".join(violations))
        return 1
    print(f"eval_corpus_lint: clean ({len(units)} units, "
          f"{classes['black-box']} black-box / "
          f"{classes['source-readable']} source-readable — RE capability "
          "metrics count the black-box face only, #816)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
