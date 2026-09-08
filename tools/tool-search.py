#!/usr/bin/env python3
"""tool-search.py — deterministic tool catalog query (issue #278 P4-a).

Zero-LLM, zero-network catalog query over tools/_INDEX.yaml. The index lists
analysis tools; tool-search itself is meta and is deliberately NOT registered
in the index.

Filters (combinable, AND semantics):
  --capability <domain:op>      exact or prefix match on the capability tag
                                ("crypto:decode" matches itself and any
                                "crypto:decode:*"; "ghidra" matches every
                                "ghidra:*" tag)
  --tier T1|T2|T3               exact tier match
  --cost-max probe|cheap|deep   budget filter: probe < cheap < deep
                                (inclusive — cheap returns probe + cheap)

Discovery mode (issue #476, #162: THE single search entry — no per-tier
search tools exist):
  --find <keyword>              case-insensitive substring search across
                                ALL THREE data sources:
                                  1. the internal registry
                                     (tools/_INDEX.yaml);
                                  2. the typed ext catalog
                                     (tools/_INDEX.ext.yaml — entry-point
                                     scripts/ CLIs, hooks/ gates,
                                     templates/**/*.tmpl skeletons,
                                     references/re-library/ capability
                                     docs; entries carry generated
                                     type + consume fields);
                                  3. the references index
                                     (references/_INDEX.yaml file list —
                                     its own generator's schema is left
                                     untouched; type/consume are DERIVED
                                     at query time: type=reference,
                                     consume=read).
                                Hits carry name + score + kind + type +
                                consume + source + usage + one-line
                                description — a hit decides without
                                opening the file. score = keyword match
                                strength, LEXICAL not semantic (high =
                                keywords overlapped, NOT relevance; low
                                != irrelevant); it ranks candidates for
                                inspection and never gates surfacing.
                                A source path enumerated by both the ext
                                index and the references index surfaces
                                ONCE (the typed ext entry wins). --find is
                                mutually exclusive with the internal
                                filters (ext/reference entries carry no
                                tier/cost_tier — ANDing would silently
                                drop them; refuse instead).

Output: matching entries (name/category/capability/tier/cost_tier/
input_output, plus when_not when present) as JSON (--json: {count, tools})
or compact text (one line per entry).

Exit codes:
  0  query answered (matches, or a valid query with no match → empty output)
  2  usage error
  3  index missing/unreadable

Usage:
  python tools/tool-search.py --capability crypto:decode --json
  python tools/tool-search.py --tier T1 --cost-max cheap
  python tools/tool-search.py --capability ghidra --json path/to/_INDEX.yaml
  python tools/tool-search.py --find converg
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402


import argparse
import json
import sys
from pathlib import Path

# UTF-8 stdout contract (#317, follow-up completed by #476): --find
# prints docstring-derived usage/description lines carrying non-ASCII;
# stdout unified on UTF-8 with errors=replace (canonical guard shape,
# enforced by tests/test_utf8_stdout_convention.py — the test helper in
# tests/test_tool_search.py decodes UTF-8 with this change).

COST_ORDER = ("probe", "cheap", "deep")   # probe < cheap < deep (budget)
TIERS = ("T1", "T2", "T3")
PUBLIC_KEYS = ("name", "category", "capability", "tier", "cost_tier",
               "input_output")

EXT_INDEX_NAME = "_INDEX.ext.yaml"   # describe-only catalog (#476, #162)
INTERNAL_SOURCE = "tools/_INDEX.yaml"  # resolution registry for internal hits
# #162 third data source: the references index (its own generator's file
# list; type/consume derived at query time — the file is never rewritten).
REFERENCES_INDEX_REL = ("references", "_INDEX.yaml")
REFERENCES_HEAD_LINES = 80   # haystack/description read depth per card
REFERENCE_USAGE_TEMPLATE = "read {source} (capability reference)"


def load_index(index_path: Path) -> list[dict]:
    """Load tools/_INDEX.yaml → list of raw entries (order preserved)."""
    import yaml
    data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    tools = data.get("tools") if isinstance(data, dict) else None
    return tools if isinstance(tools, list) else []


def load_ext_index(index_path: Path) -> list[dict]:
    """Load the optional ext catalog next to the internal index.

    Absent/broken ext file → empty list: discovery degrades to
    internal-only (the internal registry stays fully queryable — an ext
    problem must not brick the query face)."""
    if not index_path.is_file():
        return []
    import yaml
    try:
        data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - unreadable ext = no ext hits
        return []
    ext = data.get("ext") if isinstance(data, dict) else None
    return ext if isinstance(ext, list) else []


def capability_matches(capability: str, query: str) -> bool:
    """Exact or prefix match on the capability tag."""
    return capability == query or capability.startswith(query)


def matches(entry: dict, capability: str | None, tier: str | None,
            cost_max: str | None) -> bool:
    """AND semantics: every provided filter must match the entry."""
    if capability is not None and not capability_matches(
            str(entry.get("capability", "")), capability):
        return False
    if tier is not None and entry.get("tier") != tier:
        return False
    if cost_max is not None:
        entry_cost = entry.get("cost_tier", "")
        if entry_cost in COST_ORDER and \
                COST_ORDER.index(entry_cost) > COST_ORDER.index(cost_max):
            return False
    return True


def entry_public(entry: dict) -> dict:
    """Project an index entry onto the public contract fields.

    when_not is optional in the schema — emitted only when present.
    """
    out = {k: entry.get(k) for k in PUBLIC_KEYS}
    if entry.get("when_not") is not None:
        out["when_not"] = entry["when_not"]
    return out


def format_text(tools: list[dict]) -> str:
    """Compact text: one line per entry, tab-separated public fields."""
    lines = []
    for t in tools:
        lines.append("\t".join(str(t.get(k, ""))
                               for k in ("name", "category", "capability",
                                         "tier", "cost_tier")))
    return "\n".join(lines)


# ---- #162 third data source: references index (query-time typing) ---------

def load_reference_paths(refs_index_path: Path) -> list[str]:
    """references/_INDEX.yaml `files:` mapping keys -> sorted source paths.

    Absent/broken index -> empty list: the third source degrades to
    silence (the other two stay fully queryable — one index's problem
    must not brick the query face)."""
    if not refs_index_path.is_file():
        return []
    import yaml
    try:
        data = yaml.safe_load(refs_index_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - unreadable index = no reference hits
        return []
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return []
    return sorted(str(k) for k in files)


def _reference_head(repo_root: Path, source: str) -> str:
    """First lines of the card — the haystack/description read depth.
    Unreadable cards match on their path alone."""
    p = repo_root / source
    try:
        lines = p.read_text(encoding="utf-8", errors="replace") \
            .splitlines()
    except OSError:
        return ""
    return "\n".join(lines[:REFERENCES_HEAD_LINES])


def _reference_description(head: str) -> str:
    """Frontmatter `description:`, else the first `# ` heading."""
    lines = head.splitlines()
    if lines and lines[0].strip() == "---":
        for ln in lines[1:]:
            if ln.strip() == "---":
                break
            if ln.startswith("description:"):
                return ln.partition(":")[2].strip()
    for ln in lines:
        if ln.startswith("# "):
            return ln[2:].strip()
    return ""


def find_references(repo_root: Path, ref_paths: list[str],
                    terms: list[str], mode: str = "any") -> list[dict]:
    hits: list[dict] = []
    for source in ref_paths:
        head = _reference_head(repo_root, source)
        if not _haystack_hit(f"{source}\n{head}".lower(), terms, mode):
            continue
        hits.append({
            "name": Path(source).stem,
            "kind": "reference",
            "type": "reference",       # derived at query time (#162)
            "consume": "read",         # derived at query time (#162)
            "source": source,
            "usage": REFERENCE_USAGE_TEMPLATE.format(source=source),
            "description": _reference_description(head),
        })
    return hits


# ---- #162 addendum: keyword match score (lexical, not semantic) ------------
# The score is ONLY text similarity — keyword/lexical matching degree. It is
# NOT semantic similarity and does NOT represent topical relevance. Honest
# reading: a high score means keywords overlapped, nothing more; a low score
# does NOT mean irrelevant (semantically related items can share no
# keywords). The score ranks candidates for inspection and measures nothing
# beyond word overlap. It is a REFERENCE signal for the agent's own decision
# — never an applicability verdict — and, being lexically shallow, it never
# gates surfacing (no threshold-drop): hits are surfaced and the agent
# judges. Hit descriptions state EXPECTED outcomes, not guaranteed facts
# (expectation != fact).

SCORE_FIELDS = (   # (field, weight) — name matches are the strongest signal
    ("name", 1.0),
    ("capability", 0.8),
    ("source", 0.6),
    ("usage", 0.5),
    ("description", 0.5),
)


def match_score(entry: dict, keyword: str) -> float:
    """Keyword match score (lexical, not semantic): normalized 0-1
    matching degree, 2-decimal, deterministic — the strongest per-field
    weighted match density (occurrences * keyword length over field
    length, capped, scaled by field weight). High = keywords overlapped,
    NOT relevance; low != irrelevant. It ranks candidates for inspection
    and never gates surfacing."""
    kw = keyword.lower()
    best = 0.0
    for field, weight in SCORE_FIELDS:
        text = str(entry.get(field, "") or "").lower()
        if not text or kw not in text:
            continue
        density = (len(kw) * text.count(kw)) / len(text)
        best = max(best, min(1.0, density) * weight)
    return round(best, 2)


def _with_score(hits: list[dict], terms: list[str]) -> list[dict]:
    """Attach the lexical match score (strongest term) and rank by it
    (descending, stable). Ordering only — no hit is ever dropped by
    score (wide boundary)."""
    for h in hits:
        h["score"] = max(match_score(h, t) for t in terms) if terms else 0.0
    return sorted(hits, key=lambda h: h["score"], reverse=True)


# ---- --find discovery mode (#476) -----------------------------------------

def _io_text(value: object) -> str:
    if isinstance(value, dict):
        # Drop None-valued keys: some inline flow mappings in the index
        # carry commas inside unquoted scalars, which YAML splits into
        # extra null-valued keys (authoring quirk) — display keeps the
        # meaningful input/output pairs, insertion order preserved.
        cleaned = {k: v for k, v in value.items() if v is not None}
        return json.dumps(cleaned, ensure_ascii=False)
    return str(value or "")


def _internal_haystack(entry: dict) -> str:
    return "\n".join(str(entry.get(k, "") or "") for k in
                     ("name", "category", "capability", "description")) \
        + "\n" + _io_text(entry.get("input_output"))


def _ext_haystack(entry: dict) -> str:
    return "\n".join(str(entry.get(k, "") or "") for k in
                     ("name", "capability", "source", "usage", "description"))


# ---- #162 keyword matching: multi-term boolean over the haystacks ----------

def _haystack_hit(haystack: str, terms: list[str], mode: str) -> bool:
    """any = boolean OR (default), all = boolean AND over the terms."""
    hay = haystack.lower()
    if mode == "all":
        return all(t in hay for t in terms)
    return any(t in hay for t in terms)


def find_internal(tools: list[dict], terms: list[str],
                  mode: str = "any") -> list[dict]:
    hits = [t for t in tools
            if _haystack_hit(_internal_haystack(t).lower(), terms, mode)]
    return [_find_projection_internal(t) for t in hits]


def find_ext(ext: list[dict], terms: list[str],
             mode: str = "any") -> list[dict]:
    hits = [e for e in ext
            if _haystack_hit(_ext_haystack(e).lower(), terms, mode)]
    return [_find_projection_ext(e) for e in hits]


def _find_projection_internal(entry: dict) -> dict:
    return {
        "name": entry.get("name"),
        "kind": "internal",
        "type": "tool",
        "consume": "invoke",
        "category": entry.get("category"),
        "capability": entry.get("capability"),
        "tier": entry.get("tier"),
        "cost_tier": entry.get("cost_tier"),
        "source": INTERNAL_SOURCE,
        "usage": _io_text(entry.get("input_output")),
        "description": entry.get("description"),
    }


def _find_projection_ext(entry: dict) -> dict:
    # #515: environment-side entries (name mcp__<server>, merged via
    # ext-scan --with-mcp) project kind=mcp — the structural mcp__
    # prefix is the single naming rule (no on-disk kind field).
    kind = "mcp" if str(entry.get("name", "")).startswith("mcp__") else "ext"
    return {
        "name": entry.get("name"),
        "kind": kind,
        "type": entry.get("type"),        # generated tier label (#162)
        "consume": entry.get("consume"),  # generated consume label (#162)
        "capability": entry.get("capability"),
        "source": entry.get("source"),
        "usage": entry.get("usage"),
        "description": entry.get("description"),
    }


def format_find_text(hits: list[dict]) -> str:
    """One line per hit: name, score, type, consume, source, description
    (#162 display contract — a hit decides without opening the file;
    score is a reference signal, never a verdict)."""
    return "\n".join(
        "\t".join(str(h.get(k, "") or "") for k in
                  ("name", "score", "type", "consume", "source",
                   "description"))
        for h in hits)


def _emit(hits: list[dict], as_json: bool, text_formatter) -> None:
    if as_json:
        print(json.dumps({"count": len(hits), "tools": hits},
                         ensure_ascii=False))
    else:
        text = text_formatter(hits)
        if text:
            print(text)


def _find_mode(args, tools: list[dict], index_path: Path) -> int:
    """--find: the #162 unified typed search face (all three sources)."""
    terms = [t.strip().lower() for t in args.find.split(",") if t.strip()]
    if not terms:
        print("error: --find needs at least one keyword", file=sys.stderr)
        return 2
    mode = args.match or "any"
    ext = load_ext_index(index_path.parent / EXT_INDEX_NAME)
    refs_index = index_path.parent.parent.joinpath(*REFERENCES_INDEX_REL)
    ref_paths = load_reference_paths(refs_index)
    repo_root = index_path.parent.parent
    # dedup by source path: a re-library card enumerated by both the ext
    # index and the references index surfaces once (typed ext entry wins)
    hits = find_internal(tools, terms, mode) + find_ext(ext, terms, mode)
    seen_sources = {str(h.get("source", "")) for h in hits}
    for h in find_references(repo_root, ref_paths, terms, mode):
        if h["source"] not in seen_sources:
            hits.append(h)
    if args.type is not None:
        hits = [h for h in hits if h.get("type") == args.type]
    hits = _with_score(hits, terms)
    _emit(hits, args.json, format_find_text)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="deterministic tool catalog query over tools/_INDEX.yaml "
                    "(issue #278 P4-a; --find discovery over the ext "
                    "catalog, issue #476)")
    ap.add_argument("--capability", default=None,
                    help="capability tag, exact or prefix match "
                         "(e.g. crypto:decode, ghidra)")
    ap.add_argument("--tier", choices=TIERS, default=None,
                    help="exact tier match (T1 static / T2 emulation / "
                         "T3 VM-dynamic)")
    ap.add_argument("--cost-max", choices=COST_ORDER, default=None,
                    help="cost budget filter, inclusive: probe < cheap < deep")
    ap.add_argument("--find", default=None, metavar="KEYWORD[,KEYWORD...]",
                    help="discovery mode (#162): case-insensitive keyword "
                         "search over ALL THREE data sources (internal "
                         "registry, typed ext catalog, references index); "
                         "comma-separated terms combine boolean-style via "
                         "--match (default any = OR); hits carry name + "
                         "score + type + consume + source + usage + "
                         "description; mutually exclusive with "
                         "--capability/--tier/--cost-max")
    ap.add_argument("--match", choices=("any", "all"), default=None,
                    help="multi-term boolean mode for --find: any = OR "
                         "(default), all = AND (every term must match)")
    ap.add_argument("--type", choices=("tool", "template", "reference"),
                    default=None,
                    help="tier filter on the results (#162): combinable "
                         "with --find and with the internal filters")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON {count, tools} instead of compact text")
    ap.epilog = (
        "keyword match score contract (#162 addendum): the score column "
        "is keyword match strength — LEXICAL, NOT SEMANTIC. It never "
        "represents topical relevance or applicability: a high score "
        "means keywords overlapped, NOT that the hit is relevant; a low "
        "score does NOT mean irrelevant (semantically related items can "
        "share no keywords). The score ranks candidates for inspection "
        "and measures nothing beyond word overlap. Reference signal for "
        "the agent's own decision — the search narrows, the agent decides "
        "fit. Because the score is lexically shallow it NEVER gates "
        "surfacing (no threshold-drop): near-miss hits stay surfaced, "
        "since a poorly-matching attempt sometimes solves a big problem "
        "and a highly-matching one can still fail on variant factors. "
        "Hit descriptions state EXPECTED outcomes, not guaranteed facts "
        "(expectation != fact). Boolean syntax: --find takes comma-"
        "separated terms; --match any = OR (default), --match all = AND "
        "(every term must match). --type tool|template|reference filters "
        "the results by tier and composes with both --find and the "
        "internal filters.")
    ap.add_argument("index_path", nargs="?", default=None,
                    help="index yaml (default: tools/_INDEX.yaml next to "
                         "this script)")
    args = ap.parse_args(argv)

    if args.find is not None and (args.capability or args.tier
                                  or args.cost_max):
        ap.error("--find cannot combine with --capability/--tier/--cost-max "
                 "(ext entries carry no tier/cost_tier; ANDing would "
                 "silently drop them — run two queries instead)")
    if args.match is not None and args.find is None:
        ap.error("--match requires --find (it has no meaning for the "
                 "internal filters)")
    if args.type is not None and args.type not in ("tool", "template",
                                                   "reference"):
        ap.error("--type must be tool|template|reference")

    index_path = Path(args.index_path) if args.index_path \
        else Path(__file__).resolve().parent / "_INDEX.yaml"
    if not index_path.is_file():
        print(f"error: index file not found: {index_path}", file=sys.stderr)
        return 3
    try:
        tools = load_index(index_path)
    except Exception as exc:  # noqa: BLE001 - report any unreadable index
        print(f"error: cannot read index {index_path}: {exc}", file=sys.stderr)
        return 3

    if args.find is not None:
        return _find_mode(args, tools, index_path)

    hits = [entry_public(t) for t in tools
            if matches(t, args.capability, args.tier, args.cost_max)]
    if args.type is not None:
        # the internal registry face holds only tools — a --type filter
        # answering anything else there is a valid empty query
        hits = hits if args.type == "tool" else []
    _emit(hits, args.json, format_text)
    return 0

    if args.json:
        print(json.dumps({"count": len(hits), "tools": hits},
                         ensure_ascii=False))
    else:
        text = format_text(hits)
        if text:
            print(text)
    return 0


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
