#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""relib_audit.py — #817 re-library 知识库审查器。

三类问题检出 + 可逆 quarantine + 质量度量：
  孤儿        .md 文件未出现在任何 _index-*.md / _INDEX.md 目录中
              （recall 引擎永不返回 = 等于不存在）
  tracker 残留  正文含历史卡号字样 #NNN（内容策展归人工，机制只检出计量）
  声明行缺失    文件尾缺 worker 反馈声明 `recall_useful:`——缺失则
              feedback 管道对声明维度的数据永远为空

CLI:
  python scripts/relib_audit.py <lib_dir> [--json]
  python scripts/relib_audit.py --quarantine <lib_dir> <file.md> --reason <why>

Production-semantics tier (#866 de-whitewash):
  python scripts/relib_audit.py --production <repo_root> [--json]

  Judges every scripts/*.py module and every tools/ ``__main__`` CLI by
  production wiring, not by "tests mention it": seed faces are
  hooks/ skills/ agents/ devkit/ .github/workflows/ and the execution
  registry tools/_INDEX.yaml (consumed by the toolfirst gate);
  tests/openspec/docs/references, the describe-only ext index, the human
  catalogs, and both manifests (deploy-manifest now ships 100% of both
  trees — zero discrimination; release-manifest is packaging) are
  DIAGNOSTIC only. A subject consumed by an already-wired subject
  (filename literal or ``import/from <stem>``) is wired transitively.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_TRACKER_RE = re.compile(r"#\d{3}\b")
_MD_REF_RE = re.compile(r"\b([A-Za-z0-9-]+\.md)\b")
_DECL = "recall_useful:"


# ---- production-semantics tier (#866) --------------------------------------

# tools-root infra trio: by their own discipline the generator/querier never
# enters the registry it serves (ext-scan docstring) — they are not subjects.
_PROD_INFRA = {
    "tools/ext-scan.py",
    "tools/tool-search.py",
    "tools/validate_index.py",
}

# Seed faces: a hit in these surfaces is production wiring.
# index_yaml = tools/_INDEX.yaml, the execution registry that
# hooks/worker_budget_gates._load_tool_index_keywords consumes at dispatch
# time — a row there makes a CLI discoverable by the production gate.
_PROD_SEED_FACES = {
    "hooks": ("hooks/**/*.py",),
    "skills": ("skills/**/*.md", "skills/**/*.py", "skills/*.yaml"),
    "agents": ("agents/*.md",),
    "devkit": ("devkit/**",),
    "ci": (".github/workflows/*.yml", ".github/workflows/*.yaml"),
    "index_yaml": ("tools/_INDEX.yaml",),
}

# Diagnostic faces: recorded per subject, never counted (the #817 lesson —
# "tests count as references" was the single-metric whitewash; shipping in a
# manifest is the same lie one level up once deploy-manifest grew to the
# full tree).
_PROD_DIAG_FACES = {
    "tests": ("tests/**",),
    "openspec": ("openspec/**",),
    "docs": ("docs/**",),
    "references": ("references/**",),
    "ext_index": ("tools/_INDEX.ext.yaml",),
    "catalogs_md": ("tools/_INDEX.md", "tools/_index-*.md"),
    "deploy_manifest": ("deploy-manifest.yaml",),
    "release_manifest": ("release-manifest.yaml",),
    "scripts_readme": ("scripts/README.md",),
    "gc_harness": ("gc-harness/**",),
    "eval": ("eval/**", "evals/**"),
    "kunglao_bench": ("kunglao-bench/**",),
}


# The discovery gate's own debt ledger lists unwired CLI paths by design —
# counting it as a face would wire every CLI it lists (self-reference
# leak). Bookkeeping is not consumption; same for the lib audit's
# quarantine manifest.
_PROD_BOOKKEEPING = {
    "devkit/.discovery-gate-baseline.txt",
    "references/archive/quarantine-manifest.yaml",
}


def _face_corpus(root: Path, globs) -> str:
    """Concatenated text of every file the globs reach. A pattern ending in
    bare '**' yields DIRECTORIES on pathlib — when a dir comes back, walk
    it recursively so the face corpus is never silently empty. Bookkeeping
    files (_PROD_BOOKKEEPING) never enter any corpus."""
    def _read(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _bookkeeping(p: Path) -> bool:
        return p.relative_to(root).as_posix() in _PROD_BOOKKEEPING

    parts = []
    for g in globs:
        for f in sorted(root.glob(g)):
            if f.is_dir():
                parts.extend(_read(sub) for sub in sorted(f.rglob("*"))
                             if sub.is_file() and not _bookkeeping(sub))
            elif f.is_file() and not _bookkeeping(f):
                parts.append(_read(f))
    return "\n".join(parts)


def production_subjects(root: Path) -> dict:
    """Subject repo-relative path -> source text (scripts/*.py + tools/
    ``__main__`` CLIs). Keys are repo-relative POSIX paths."""
    subjects: dict = {}
    scripts = root / "scripts"
    if scripts.is_dir():
        for p in sorted(scripts.glob("*.py")):
            try:
                subjects[p.relative_to(root).as_posix()] = p.read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                continue
    tools = root / "tools"
    if tools.is_dir():
        for p in sorted(tools.rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            if rel in _PROD_INFRA or "_lib" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "__main__" in text:
                subjects[rel] = text
    return subjects


def _token_hit(text: str, token: str) -> bool:
    """Whole-token containment: token must not be flanked by name chars
    (alnum/underscore/hyphen) — keeps stem 'gen' from matching inside
    'widget-gen'. Uses C-speed str.find first, so this is cheap even on
    multi-megabyte face corpora."""
    start = 0
    n = len(text)
    while True:
        i = text.find(token, start)
        if i < 0:
            return False
        a = text[i - 1] if i > 0 else " "
        j = i + len(token)
        b = text[j] if j < n else " "
        if not (a.isalnum() or a in "_-") and not (b.isalnum() or b in "_-"):
            return True
        start = j


_IMPORT_PAT_CACHE: dict = {}


def _hits(rel: str, text: str, *, bare_stem: bool) -> bool:
    """True when `text` references subject `rel`: filename literal,
    repo-relative path, import/from of the stem — plus the bare stem
    (how catalogs/teaching faces name a tool) only when bare_stem.

    bare_stem=False (consumption closure): a scripts/ module stem can
    equal a HOOK name registered as a plain string elsewhere (e.g.
    reuse_gate), a different identity class — bare-stem closure would
    wire the script on a name collision.
    """
    name = Path(rel).name
    stem = Path(rel).stem
    for v in ((name, rel, stem) if bare_stem else (name, rel)):
        if v in text and _token_hit(text, v):
            return True
    if stem in text:
        pat = _IMPORT_PAT_CACHE.get(stem)
        if pat is None:
            pat = _IMPORT_PAT_CACHE[stem] = re.compile(
                r"(?:import|from)\s+" + re.escape(stem) + r"\b")
        if pat.search(text):
            return True
    return False


def audit_production(root) -> dict:
    """#866 production-wiring audit over scripts/ + tools/ CLIs.

    Returns subjects/wired/unwired per side, per-subject face hits (seed
    faces + diagnostics + 'lib_closure'), and LOC of the unwired set.
    """
    root = Path(root)
    subjects = production_subjects(root)
    faces_def = {**_PROD_SEED_FACES, **_PROD_DIAG_FACES}
    corpus = {face: _face_corpus(root, globs)
              for face, globs in faces_def.items()}

    wired: set = set()
    faces: dict = {}
    for rel in subjects:
        hit = [face for face in _PROD_SEED_FACES
               if _hits(rel, corpus[face], bare_stem=True)]
        diag = [face for face in _PROD_DIAG_FACES
                if _hits(rel, corpus[face], bare_stem=True)]
        faces[rel] = hit + diag
        if hit:
            wired.add(rel)

    # Transitive closure along real consumption edges (issue: 产线语义传递闭包):
    # a subject is wired when a wired subject's source consumes it.
    wired_texts = [(rel, subjects[rel]) for rel in subjects if rel in wired]
    changed = True
    while changed:
        changed = False
        for rel in subjects:
            if rel in wired:
                continue
            for _other, text in wired_texts:
                if _hits(rel, text, bare_stem=False):
                    wired.add(rel)
                    faces[rel].append("lib_closure")
                    wired_texts.append((rel, subjects[rel]))
                    changed = True
                    break

    unwired = [rel for rel in subjects if rel not in wired]
    by_side = lambda rels, prefix: sorted(r for r in rels if r.startswith(prefix))
    unwired_scripts = by_side(unwired, "scripts/")
    unwired_tools = by_side(unwired, "tools/")
    unwired_loc = sum(len(subjects[r].splitlines()) for r in unwired)
    n_scripts = sum(1 for r in subjects if r.startswith("scripts/"))
    n_tools = len(subjects) - n_scripts
    return {
        "subjects": {
            "scripts": by_side(subjects, "scripts/"),
            "tools": by_side(subjects, "tools/"),
        },
        "wired": {
            "scripts": by_side(wired, "scripts/"),
            "tools": by_side(wired, "tools/"),
        },
        "unwired": {"scripts": unwired_scripts, "tools": unwired_tools},
        "faces": faces,
        "counts": {
            "subjects_scripts": n_scripts,
            "subjects_tools": n_tools,
            "wired_scripts": len(by_side(wired, "scripts/")),
            "wired_tools": len(by_side(wired, "tools/")),
            "unwired_scripts": len(unwired_scripts),
            "unwired_tools": len(unwired_tools),
            "unwired_total": len(unwired),
            "unwired_loc": unwired_loc,
        },
        "metrics": {"files_total": len(subjects)},
    }


def _catalog(lib: Path) -> set:
    """被任何 _index-*.md（及顶层 _INDEX.md）提及的文件名集合。"""
    catalog: set = set()
    index_files = sorted(lib.glob("_index-*.md"))
    top = lib / "_INDEX.md"
    if top.exists():
        index_files.append(top)
    for f in index_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        catalog |= set(_MD_REF_RE.findall(text))
    return catalog


def audit(lib_dir) -> dict:
    """审查库目录。返回 {orphans, trackers, missing_decl, counts, metrics}。"""
    lib = Path(lib_dir)
    catalog = _catalog(lib)
    files = sorted(p for p in lib.glob("*.md") if not p.name.startswith("_"))
    orphans = [p.name for p in files if p.name not in catalog]
    trackers: dict = {}
    missing_decl: list = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tids = sorted(set(_TRACKER_RE.findall(text)))
        if tids:
            trackers[p.name] = tids
        if _DECL not in text:
            missing_decl.append(p.name)
    return {
        "orphans": orphans,
        "trackers": trackers,
        "missing_decl": missing_decl,
        "counts": {"orphans": len(orphans), "trackers": len(trackers),
                   "missing_decl": len(missing_decl)},
        "metrics": {"files_total": len(files)},
    }


def quarantine(lib_dir, name: str, reason: str):
    """孤儿文件可逆隔离：移入 archive/ 并留 manifest 记账。

    拒绝对已收录（非孤儿）文件执行——archive 只收孤儿。
    """
    lib = Path(lib_dir)
    if name in _catalog(lib):
        raise ValueError(f"refusing to quarantine indexed file: {name}")
    src = lib / name
    if not src.is_file():
        raise FileNotFoundError(f"not a file in library: {name}")
    arch = lib / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    dest = arch / name
    src.replace(dest)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = arch / "quarantine-manifest.yaml"
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(f"- file: {name}\n  reason: {reason}\n  quarantined_at: {now}\n")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="re-library 审查器 (#817)")
    ap.add_argument("lib_dir", nargs="?", default=None,
                    help="library dir (legacy lib audit) or repo root "
                         "(with --production)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quarantine", metavar="FILE")
    ap.add_argument("--reason", default="orphan-audit")
    ap.add_argument("--production", action="store_true",
                    help="#866 production-wiring audit over scripts/ + tools/ "
                         "CLIs (lib_dir is the repo root)")
    args = ap.parse_args()
    if args.production:
        if not args.lib_dir:
            ap.error("--production needs the repo root as lib_dir")
        r = audit_production(args.lib_dir)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            c = r["counts"]
            print(f"production audit: scripts={c['subjects_scripts']} "
                  f"tools_cli={c['subjects_tools']} "
                  f"unwired={c['unwired_total']} "
                  f"(scripts {c['unwired_scripts']}, tools {c['unwired_tools']}, "
                  f"~{c['unwired_loc']} LOC)")
            if r["unwired"]["tools"]:
                print("  unwired tools:")
                for rel in r["unwired"]["tools"]:
                    print(f"    {rel}")
            if r["unwired"]["scripts"]:
                print("  unwired scripts:")
                for rel in r["unwired"]["scripts"]:
                    print(f"    {rel}")
        return 0
    if not args.lib_dir:
        ap.error("lib_dir is required (or pass --production <repo_root>)")
    lib = Path(args.lib_dir)
    if args.quarantine:
        dest = quarantine(lib, args.quarantine, args.reason)
        print(f"quarantined: {args.quarantine} -> {dest}")
        return 0
    r = audit(lib)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"files={r['metrics']['files_total']} "
              f"orphans={r['counts']['orphans']} "
              f"trackers={r['counts']['trackers']} "
              f"missing_decl={r['counts']['missing_decl']}")
        for name, tids in sorted(r["trackers"].items()):
            print(f"  tracker {name}: {', '.join(tids)}")
        if r["orphans"]:
            print("  orphans: " + ", ".join(r["orphans"]))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
