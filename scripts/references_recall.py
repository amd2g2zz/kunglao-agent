#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""references_recall — scored progressive-disclosure recall over the layered references index (#275).

#261 renamed the flat references/INDEX.md into a layered index:
  references/_INDEX.md          top-level domain index (domain table +
                                scenario->domain table + full catalog rows)
  references/_index-<domain>.md per-domain file-level indexes
  references/_INDEX.yaml        machine-readable manifest (file sha256s) +
                                symptom->file map

This module rebuilds the #229 recall contract on top of the layered index:

  * structured parse — the domain table, scenario->domain table, per-domain
    index files, full catalog rows and the symptom map are all parsed from
    their structural forms (markdown tables / YAML). No grep over reference
    file bodies.
  * scored retrieval — query tokens (ASCII words + CJK unigrams/bigrams, CJK
    and English weighted equally) score each entry: filename > category/domain
    > symptom tag > purpose/summary > when-to-read. Results return top-K
    sorted by score, each with its score and the matched fields.
  * query semantics — scenario label -> Scene(primary, supplementary) rebuilt
    from the scenario->domain expression: a domain name expands to its file
    list; an explicit file short-name is primary; the remaining files of the
    owning domain(s) become supplementary.

CLI surface is unchanged for downstream callers (SKILL.md / hooks / workers):
  python references_recall.py <query>            # scene / scored recall
  python references_recall.py --list-categories  # category -> file counts
  python references_recall.py --scene-map        # scenario -> primary/supplementary
  python references_recall.py --help

Exit codes: 0 = matches found; 1 = no match (closest categories listed);
2 = usage error or _INDEX.md unreadable.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

try:  # PyYAML is a repo dependency; degrade gracefully when absent.
    import yaml as _yaml
except Exception:  # pragma: no cover
    _yaml = None

SECTION_DOMAIN = "## Domain table"
SECTION_INDEXFILES = "## Per-domain index files"
SECTION_TOP = "## Top-level references"
SECTION_RELIB = "## re-library"

# Cells used to skip table header rows (CJK + English catalog headers).
_HEADER_CELLS = {"文件", "场景", "file", "files", "domain", "scenario", "purpose"}

USAGE = (
    "Usage: references_recall.py <query>\n"
    "       references_recall.py --list-categories\n"
    "       references_recall.py --scene-map\n"
    "Scored recall over the layered references index (references/_INDEX.md +\n"
    "per-domain _index-<domain>.md): scenario label -> primary/supplementary\n"
    "files; otherwise top-K entries ranked by relevance score. Output rows\n"
    "carry path + purpose + when-to-read + score (never file contents)."
)

# ---- scoring weights (filename > category/domain > symptom > purpose > when) ----
W_NAME = 3.0
W_NAME_EXACT = 5.0
W_CAT_DOMAIN = 2.0
W_SYMPTOM = 1.5
W_PURPOSE = 1.0
W_WHEN = 0.5


@dataclass(frozen=True)
class Entry:
    """One file row of the full catalog (top-level + re-library tables)."""

    path: str            # repo-relative, e.g. "guardrails.md" | "re-library/tools-crypto.md"
    category: str
    purpose: str
    when: str
    domain: str = ""                     # domain(s) this file belongs to (comma-joined)
    summary: str = ""                    # CJK one-line summary from _index-<domain>.md
    symptoms: tuple[str, ...] = ()       # symptom/F-row tags from _INDEX.yaml

    def tokens(self) -> set[str]:
        """All searchable tokens: filename, category, domain, summary/purpose, when, symptoms."""
        text = " ".join((
            Path(self.path).stem, self.category, self.domain,
            self.purpose, self.summary, self.when, " ".join(self.symptoms),
        ))
        return set(_tokenize(text))


@dataclass(frozen=True)
class Scene:
    """One row of the scenario->domain map: 场景 | Domain(表达式)."""

    label: str
    primary: tuple[str, ...]             # resolved file paths
    supplementary: tuple[str, ...]
    domain_expr: str = ""


@dataclass(frozen=True)
class ScoredEntry:
    entry: Entry
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecallResult:
    query: str
    kind: str                            # "scene" | "scored" | "none"
    scenes: tuple[Scene, ...] = ()
    scored: tuple[ScoredEntry, ...] = ()

    @property
    def files(self) -> tuple[str, ...]:
        """All matched file paths in deterministic order, deduped."""
        if self.kind == "scene":
            seen: set[str] = set()
            out: list[str] = []
            for s in self.scenes:
                for p in (*s.primary, *s.supplementary):
                    if p not in seen:
                        seen.add(p)
                        out.append(p)
            return tuple(out)
        return tuple(se.entry.path for se in self.scored)

    @property
    def entries(self) -> tuple[Entry, ...]:
        """Scored entries (kept for callers that consume Entry rows)."""
        return tuple(se.entry for se in self.scored)


@dataclass(frozen=True)
class DomainInfo:
    name: str
    files: tuple[str, ...]               # short names, e.g. ("tools", "tools-dynamic")
    purpose: str


@dataclass
class Index:
    """Fully parsed layered index."""

    index_path: Path
    entries: tuple[Entry, ...] = ()
    scenes: tuple[Scene, ...] = ()
    domains: dict[str, DomainInfo] = field(default_factory=dict)
    symptom_map: dict[str, str] = field(default_factory=dict)


def default_index_path() -> Path:
    """_INDEX.md lives next to the skill root (this script is under scripts/)."""
    return Path(__file__).resolve().parent.parent / "references" / "_INDEX.md"


# ---------- low-level table parsing ----------

def _split_table_row(line: str) -> list[str] | None:
    """Split a markdown table row; return None for non-rows and separators."""
    s = line.strip()
    if not s.startswith("|") or not s.endswith("|"):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
        return None  # separator row
    return cells


def _is_header(cells: list[str]) -> bool:
    """True when a row looks like a header (first cell is a header label)."""
    first = cells[0].strip("`").strip().lower()
    return first in _HEADER_CELLS


# ---------- tokenization / normalization ----------

_CJK = r"一-鿿"


def _norm(text: str) -> str:
    """Case-fold and strip separators so 'dynamic analysis' == 'dynamic-analysis'
    and posix/Windows paths compare equal."""
    return re.sub(r"[\s\-_/\\]+", "", text).lower()


def _tokenize(text: str) -> tuple[str, ...]:
    """Extract search tokens: ASCII words (+ hyphen parts) and CJK unigrams,
    bigrams and whole runs. CJK and English end up on equal footing."""
    text = text.lower()
    toks: list[str] = []
    for m in re.finditer(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text):
        toks.append(m.group(0))
        for part in re.split(r"[^a-z0-9]+", m.group(0)):
            if part:
                toks.append(part)
    for run in re.findall(f"[{_CJK}]+", text):
        n = len(run)
        toks.append(run)
        for i in range(n):
            toks.append(run[i])
            if i + 1 < n:
                toks.append(run[i:i + 2])
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return tuple(out)


# ---------- per-domain index files ----------

def _parse_domain_index(path: Path) -> dict[str, tuple[str, str]]:
    """Parse one _index-<domain>.md into {rel_path: (summary, when)}.

    Rows are markdown links: | [name.md](re-library/name.md) | 摘要 | 何时读 |.
    """
    out: dict[str, tuple[str, str]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = _split_table_row(line)
        if not cells or len(cells) < 3 or _is_header(cells):
            continue
        m = re.match(r"\[[^\]]+\]\s*\(([^)]+)\)", cells[0].strip())
        if not m:
            continue
        href = m.group(1).strip()
        summary = cells[1].strip()
        when = cells[2].strip() if len(cells) > 2 else ""
        if href and (href != "-"):
            out[href] = (summary, when)
    return out


# ---------- path resolution ----------

def _short_to_path(short: str, refs_dir: Path) -> str:
    """Map a short file name ("tools-crypto") to a repo-relative path."""
    short = short.strip()
    if short.endswith(".md"):
        short = short[:-3]
    for rel in (f"re-library/{short}.md", f"{short}.md"):
        if (refs_dir / rel).is_file():
            return rel
    return f"re-library/{short}.md"  # best-effort (kept for report-only tokens)


def _domain_of(short: str, domains: dict[str, DomainInfo]) -> str | None:
    """Return the domain that owns a file short name, or None."""
    for dom, info in domains.items():
        if short in info.files:
            return dom
    return None


# ---------- scenario expression resolution ----------

def _split_paren(part: str) -> tuple[str, list[str]]:
    """Split "methodology (a, b)" into ("methodology", ["a", "b"])."""
    m = re.match(r"^([^()]+?)\s*\(([^()]*)\)$", part.strip())
    if m:
        parens = [x.strip() for x in m.group(2).split(",") if x.strip()]
        return m.group(1).strip(), parens
    return part.strip(), []


def _dedupe(paths: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return tuple(out)


def _resolve_scene_expr(expr: str, domains: dict[str, DomainInfo],
                        refs_dir: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Rebuild primary/supplementary semantics from a scenario->domain expression.

    - a domain name expands to all its files  -> primary
    - an explicit file short name is primary; the remaining files of the
      owning domain(s) become supplementary
    - "domain (a, b)" selects a+b as primary and the rest of the domain as
      supplementary
    """
    primary: list[str] = []
    supplementary: list[str] = []
    for part in expr.split("+"):
        part = part.strip()
        if not part:
            continue
        base, parens = _split_paren(part)
        if base in domains:
            dom_paths = [_short_to_path(f, refs_dir) for f in domains[base].files]
            if parens:
                paren_paths = [_short_to_path(p, refs_dir) for p in parens]
                primary.extend(p for p in paren_paths if p in dom_paths)
                supplementary.extend(p for p in dom_paths if p not in paren_paths)
            else:
                primary.extend(dom_paths)
        else:
            p = _short_to_path(base, refs_dir)
            primary.append(p)
            owner = _domain_of(base, domains)
            if owner:
                for f in domains[owner].files:
                    other = _short_to_path(f, refs_dir)
                    if other != p:
                        supplementary.append(other)
    return _dedupe(primary), _dedupe(supplementary)


# ---------- _INDEX.yaml ----------

def _load_symptom_map(index_path: Path) -> dict[str, str]:
    """Parse references/_INDEX.yaml symptom_map (symptom/F-row -> file path)."""
    if _yaml is None:
        return {}
    yaml_path = index_path.with_name("_INDEX.yaml")
    if not yaml_path.is_file():
        return {}
    try:
        data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        sm = data.get("symptom_map", {}) or {}
        return {str(k): str(v) for k, v in sm.items()}
    except Exception:
        return {}


# ---------- top-level index assembly ----------

def build_index(index_path: Path) -> Index:
    """Parse the layered index: domain tables, scenario map, per-domain files,
    full catalog rows and the symptom map."""
    text = index_path.read_text(encoding="utf-8")
    refs_dir = index_path.parent

    domains: dict[str, DomainInfo] = {}
    scenario_rows: list[tuple[str, str]] = []
    index_files: list[tuple[str, str]] = []       # (_index-<domain>.md, domain)
    catalog: list[Entry] = []

    section = ""
    pending_domain_header = False
    pending_scenario_header = False

    for line in text.splitlines():
        if line.startswith("## "):
            section = line
            pending_domain_header = False
            pending_scenario_header = False
            continue
        cells = _split_table_row(line)
        if not cells or not section:
            continue

        if section.startswith(SECTION_DOMAIN):
            if _is_header(cells):
                first = cells[0].strip("`").strip().lower()
                pending_domain_header = first == "domain"
                pending_scenario_header = first == "scenario"
                continue
            if pending_domain_header and len(cells) >= 3:
                name = cells[0].strip()
                files = tuple(f.strip() for f in cells[1].split(",") if f.strip())
                domains[name] = DomainInfo(name=name, files=files, purpose=cells[2].strip())
            elif pending_scenario_header and len(cells) >= 2:
                scenario_rows.append((cells[0].strip(), cells[1].strip()))

        elif section.startswith(SECTION_INDEXFILES):
            if _is_header(cells) or len(cells) < 2:
                continue
            fname = cells[0].strip("`").strip()
            dom = cells[1].strip()
            index_files.append((fname, dom))

        elif section.startswith(SECTION_TOP) or section.startswith(SECTION_RELIB):
            if _is_header(cells) or len(cells) < 4:
                continue
            path = cells[0].strip("`").strip()
            if not path.endswith(".md"):
                path += ".md"
            if section.startswith(SECTION_RELIB) and not path.startswith("re-library/"):
                path = "re-library/" + path
            catalog.append(Entry(
                path=path,
                category=cells[1],
                purpose=cells[2],
                when=cells[3],
            ))

    # per-domain summaries enrich catalog entries
    summaries: dict[str, tuple[str, str]] = {}
    for fname, _dom in index_files:
        if not fname.endswith(".md"):
            fname += ".md"
        summaries.update(_parse_domain_index(refs_dir / fname))

    # reverse short-name -> domain(s)
    short_domain: dict[str, str] = {}
    for dom, info in domains.items():
        for f in info.files:
            short_domain.setdefault(f, dom)

    # symptom_map -> symptoms per file
    sym_by_path: dict[str, list[str]] = {}
    for symptom, path in _load_symptom_map(index_path).items():
        key = path.removeprefix("references/")
        sym_by_path.setdefault(key, []).append(symptom)

    entries: list[Entry] = []
    for e in catalog:
        short = e.path.removeprefix("re-library/").removesuffix(".md")
        domain = short_domain.get(short, "")
        summary, _when = summaries.get(e.path, ("", ""))
        entries.append(Entry(
            path=e.path, category=e.category, purpose=e.purpose, when=e.when,
            domain=domain, summary=summary,
            symptoms=tuple(sorted(sym_by_path.get(e.path, ()))),
        ))

    scenes = [
        Scene(label=label, domain_expr=expr,
              primary=pp, supplementary=sp)
        for label, expr in scenario_rows
        for pp, sp in (_resolve_scene_expr(expr, domains, refs_dir),)
    ]

    return Index(index_path=index_path, entries=tuple(entries), scenes=tuple(scenes),
                 domains=domains, symptom_map=dict(sym_by_path))


def parse_index(index_path: Path) -> tuple[list[Entry], list[Scene]]:
    """Back-compat shim: (entries, scenes) from the layered index."""
    idx = build_index(index_path)
    return list(idx.entries), list(idx.scenes)


# ---------- scoring ----------

def _score_entry(entry: Entry, qset: set[str], q_norm: str) -> tuple[float, tuple[str, ...]]:
    """Relevance score for one entry against the query token set."""
    stem = Path(entry.path).stem
    name_toks = set(_tokenize(stem))
    cat_toks = set(_tokenize(entry.category))
    dom_toks = set(_tokenize(entry.domain))
    sym_toks = set(_tokenize(" ".join(entry.symptoms)))
    purpose_toks = set(_tokenize(f"{entry.purpose} {entry.summary}"))
    when_toks = set(_tokenize(entry.when))

    score = 0.0
    reasons: list[str] = []

    name_hits = qset & name_toks
    if name_hits:
        score += W_NAME * len(name_hits)
        reasons.append("name:" + ",".join(sorted(name_hits)))
    if _norm(stem) == q_norm:
        score += W_NAME_EXACT
        reasons.append("name-exact")

    cat_hits = qset & cat_toks
    if cat_hits:
        score += W_CAT_DOMAIN * len(cat_hits)
        reasons.append("category:" + ",".join(sorted(cat_hits)))

    dom_hits = qset & dom_toks
    if dom_hits:
        score += W_CAT_DOMAIN * len(dom_hits)
        reasons.append("domain:" + ",".join(sorted(dom_hits)))

    sym_hits = qset & sym_toks
    if sym_hits:
        score += W_SYMPTOM * len(sym_hits)
        reasons.append("symptom:" + ",".join(sorted(sym_hits)))

    purp_hits = qset & purpose_toks
    if purp_hits:
        score += W_PURPOSE * len(purp_hits)
        reasons.append("purpose:" + ",".join(sorted(purp_hits)))

    when_hits = qset & when_toks
    if when_hits:
        score += W_WHEN * len(when_hits)
        reasons.append("when:" + ",".join(sorted(when_hits)))

    return round(score, 3), tuple(reasons)


def _scene_score(scene: Scene, qset: set[str]) -> tuple[float, set[str]]:
    label_toks = set(_tokenize(scene.label))
    hits = qset & label_toks
    return float(len(hits)), hits


def recall(entries: list[Entry], scenes: list[Scene], query: str,
           top_k: int = 10) -> RecallResult:
    """Scored recall: scene label match (primary/supplementary) wins on tie or
    better; otherwise top-K entries ranked by relevance score descending."""
    q_tokens = _tokenize(query)
    qset = set(q_tokens)
    q_norm = _norm(query)

    scene_hits: list[tuple[float, Scene]] = []
    for s in scenes:
        sc, hits = _scene_score(s, qset)
        if sc > 0 and hits:
            scene_hits.append((sc, s))
    scene_hits.sort(key=lambda t: (-t[0], scenes.index(t[1])))

    scored: list[ScoredEntry] = []
    for e in entries:
        sc, reasons = _score_entry(e, qset, q_norm)
        if sc > 0:
            scored.append(ScoredEntry(entry=e, score=sc, reasons=reasons))
    scored.sort(key=lambda se: (-se.score, entries.index(se.entry)))

    best_scene = scene_hits[0] if scene_hits else None
    best_entry = scored[0] if scored else None

    if best_scene and (best_entry is None or best_scene[0] >= best_entry.score):
        return RecallResult(query=query, kind="scene",
                            scenes=tuple(s for _, s in scene_hits))
    if best_entry:
        return RecallResult(query=query, kind="scored",
                            scored=tuple(scored[:top_k]))
    return RecallResult(query=query, kind="none")


# ---------- output ----------

def _format_entry(e: Entry) -> str:
    return f"{e.path} | {e.category} | {e.purpose} | {e.when}"


def _entry_by_path(entries: list[Entry], path: str) -> Entry:
    for e in entries:
        if e.path == path:
            return e
    return Entry(path=path, category="", purpose="", when="")


def print_result(result: RecallResult, entries: list[Entry] | None = None) -> None:
    entries = entries or []
    if result.kind == "scene":
        print(f"# references recall: {result.query} — {len(result.files)} file(s)")
        for s in result.scenes:
            print(f"## scene: {s.label}")
            print("primary:")
            for p in s.primary:
                print(_format_entry(_entry_by_path(entries, p)))
            print("supplementary:")
            for p in s.supplementary:
                print(_format_entry(_entry_by_path(entries, p)))
    else:
        print(f"# references recall: {result.query} — {len(result.scored)} file(s)")
        print("# matched by score (top-K descending)")
        for se in result.scored:
            reasons = "; ".join(se.reasons) if se.reasons else "-"
            print(f"{_format_entry(se.entry)} | score={se.score:.2f} | {reasons}")


def print_categories(entries: list[Entry]) -> None:
    counts = Counter(e.category for e in entries)
    print(f"# categories ({len(counts)}) — file count per category")
    for cat, n in sorted(counts.items()):
        print(f"{cat} ({n})")


def print_scene_map(scenes: list[Scene]) -> None:
    print(f"# scene map ({len(scenes)} scene(s)) — scenario -> primary/supplementary")
    for s in scenes:
        print(f"## {s.label}")
        print(f"primary: {', '.join(s.primary)}")
        print(f"supplementary: {', '.join(s.supplementary)}")


def print_no_match(query: str, entries: list[Entry]) -> None:
    print(f"# references recall: {query} — no match")
    print("No reference file matches the query. Closest categories:")
    counts = Counter(e.category for e in entries)
    for cat, n in sorted(counts.items()):
        print(f"  {cat} ({n})")
    print("Try a scenario keyword (--scene-map) or a file name; "
          "see references/_INDEX.md for the full domain index.")


def main(argv: list[str]) -> int:
    # _INDEX.md is UTF-8 with CJK scene labels; force UTF-8 stdout so piped
    # output (agents, CI) round-trips on Windows consoles regardless of the
    # active code page.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0 if len(argv) >= 2 else 2

    index_path = default_index_path()
    if not index_path.is_file():
        print(f"error: _INDEX.md not found at {index_path}", file=sys.stderr)
        return 2

    idx = build_index(index_path)
    entries, scenes = list(idx.entries), list(idx.scenes)

    arg = argv[1]
    if arg == "--list-categories":
        print_categories(entries)
        return 0
    if arg == "--scene-map":
        print_scene_map(scenes)
        return 0

    result = recall(entries, scenes, arg)
    if result.kind == "none":
        print_no_match(arg, entries)
        return 1

    print_result(result, entries)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
