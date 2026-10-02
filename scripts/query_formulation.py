#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""query_formulation.py — problem enumeration + faceted retrieval (#487).

The online-distillation flow gap: the act jumped from shelf-miss trigger
straight to mixed-source retrieval — the query was whatever fragments
the trigger carried. This module is the missing flow segment (classic IR
query formulation), inserted BEFORE any retrieval in both hosts:

  formulate_problem   enumerate + summarize the problem from structured
                      workspace state ONLY (die/apkid probe evidence —
                      the environment snapshot; the obstacle registry
                      runs/obstacles/ through the rlvr.obstacles reader;
                      the trigger itself) into 3-5 typed facets, every
                      term carrying provenance (a term without
                      provenance is fabrication)
  retrieve_facets     per-facet retrieval over the local re-library
                      (each facet independently) recording the
                      distill-coverage/1 matrix; an empty facet is
                      disambiguated with EXACTLY ONE reformulation
                      (the facet re-worded from its provenance terms) —
                      still empty is verdict corpus-lack, the REAL
                      shelf-miss: the act proceeds exactly as before

Facet kinds (closed, the issue's four term classes): format_family /
technique / tool / error_signature. Facet count is evidence-bounded:
the three standing facets are always derivable (format falls back to
the sample suffix map or `binary`; technique to the token components);
the two error_signature faces (obstacle / probe) appear only when the
material exists — cap 5.

Discipline (#474 verbatim): repo-local siblings + stdlib only; no LLM,
no network; deterministic serialization; formulation debits NO budget.
Corpus default references/re-library/ resolved against the module's
install parent (in-repo AND .claude/-deployed); explicit override for
fixtures/CLI.

CLI:
  python query_formulation.py <ws> --formulate [--corpus DIR]
      # read runs/distill-trigger.json, print {formulation, coverage}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from kunglao_log import warn as _warn
except ImportError:  # partial-deploy lifeline, never blocks the module
    def _warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)

SCHEMA = "query-formulation/1"
COVERAGE_SCHEMA = "distill-coverage/1"
TRIGGER_STAMP_REL = "runs/distill-trigger.json"

#: the closed facet vocabulary (issue #487's four term classes)
FACET_KINDS = ("format_family", "technique", "tool", "error_signature")

MIN_FACETS = 3
MAX_FACETS = 5
MAX_TERMS = 6
TOP_K = 5
TERM_MAX_CHARS = 40
CARD_SUFFIXES = (".md", ".yaml", ".yml")
CARD_MAX_BYTES = 512 * 1024

#: sample-hint suffix -> format-family term (closed map, no sniffing)
SUFFIX_TERMS = {
    ".apk": "android", ".so": "native library", ".dex": "dex",
    ".jar": "java", ".zip": "archive",
}

#: the format-unknown trigger's closed fallback vocabulary
FORMAT_UNKNOWN_TERMS = ("unknown format", "file identification", "entropy")

#: obstacle kind -> technique term (closed map; `other` contributes none)
OBSTACLE_KIND_TERMS = {
    "encryption_layer": "encryption",
    "detection_trigger": "anti analysis",
    "tool_limit": "tooling",
    "missing_env_entry": "environment",
}

#: tokenizer noise floor for provenance/cause lines (closed list)
STOPWORDS = frozenset((
    "the", "a", "an", "and", "or", "but", "with", "from", "this", "that",
    "then", "when", "where", "which", "while", "must", "should", "could",
    "would", "using", "used", "use", "into", "over", "under", "after",
    "before", "during", "fails", "failed", "failing", "error", "errors",
    "returns", "return", "returned", "not", "no", "nor", "its", "their",
    "there", "here", "also", "only", "than", "them", "they", "you",
    "your", "for", "are", "was", "were", "has", "have", "had",
))

_NORM_TABLE = {ord(c): " " for c in "._:/\\-\t\n\r"}


# ---------------------------------------------------------------------------
# primitives (pure)
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    """The one normalization both sides of matching use: lowercase,
    separator chars to spaces, whitespace collapse — so `anti_debug`,
    `anti-debug` and `anti debug` are the same surface."""
    return " ".join(str(text or "").lower().translate(_NORM_TABLE).split())


def _term_pattern(term: str) -> re.Pattern:
    body = re.escape(_norm(term))
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def _tokenize(value: str) -> list[str]:
    """Words for term pools: len >= 3, stopwords dropped, order kept."""
    words = re.split(r"[^a-z0-9]+", _norm(value))
    return [w for w in words if len(w) >= 3 and w not in STOPWORDS]


def _need(terms: list[str]) -> int:
    """The half-ceiling hit rule: a card covers a facet at >= ceil(n/2)
    distinct term matches (a single-term facet asks for its one term)."""
    return max(1, -(-len(terms) // 2))


def _read_json(path: Path):
    """Tolerant read: missing = no-signal None; unreadable/corrupt =
    None + the canonical warn (never a crash, never silent)."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn("query_formulation_read",
              f"{path}: {type(exc).__name__}: {exc}")
        return None


def _trigger_fields(trigger) -> tuple[str, str, str | None, str]:
    """Kind/token/sample_hint/source_file from a Trigger-like object or
    a mapping (the stamp's trigger rows are mappings)."""
    if isinstance(trigger, dict):
        get = trigger.get
    else:
        get = lambda k, d=None: getattr(trigger, k, d)  # noqa: E731
    kind = str(get("kind") or "shelf-miss") or "shelf-miss"
    token = str(get("token") or "")
    hint = get("sample_hint")
    return kind, token, str(hint) if hint else None, \
        str(get("source_file") or "")


# ---------------------------------------------------------------------------
# problem enumeration (organ 1)
# ---------------------------------------------------------------------------


def _read_obstacles(ws: Path) -> list[dict]:
    """The obstacle registry through its sanctioned reader (tolerant;
    a missing/unimportable rlvr package degrades to no rows)."""
    try:
        from rlvr import obstacles  # noqa: PLC0415 — lazy, deploy-safe
    except ImportError:
        return []
    try:
        return obstacles.read(ws)
    except Exception as exc:  # noqa: BLE001 — state read, never a raise
        _warn("query_formulation_obstacles",
              f"{type(exc).__name__}: {exc}")
        return []


def _die_format_terms(die, add) -> None:
    """Format terms from die evidence (language / packer / detects)."""
    derived = die.get("derived") if isinstance(die, dict) else None
    derived = derived if isinstance(derived, dict) else {}
    if derived.get("language"):
        add(str(derived["language"]), "evidence/die.json#derived.language",
            derived["language"])
    if derived.get("detected_packer"):
        add(str(derived["detected_packer"]),
            "evidence/die.json#derived.detected_packer",
            derived["detected_packer"])
    detects = die.get("detects") if isinstance(die, dict) else None
    for entry in (detects or [])[:2] if isinstance(detects, list) else []:
        if isinstance(entry, dict):
            entry = entry.get("type") or entry.get("name") or ""
        if entry:
            add(str(entry), "evidence/die.json#detects", entry)


def _apkid_format_terms(apkid, add) -> None:
    """Format terms from apkid summary (packer / obfuscator rules)."""
    summary = apkid.get("summary") if isinstance(apkid, dict) else None
    summary = summary if isinstance(summary, dict) else {}
    for field in ("packer", "obfuscator"):
        for value in summary.get(field) or []:
            if isinstance(value, str) and value:
                add(value, f"evidence/apkid.json#summary.{field}", value)


def _format_pool(die, apkid, sample_hint: str | None,
                 kind: str) -> list[tuple[str, dict]]:
    """(term, provenance) pairs for the format-family facet."""
    out: list[tuple[str, dict]] = []

    def add(term: str, source: str, value) -> None:
        term = _norm(term)
        if term and len(term) <= TERM_MAX_CHARS:
            out.append((term, {"source": source, "value": str(value)}))

    _die_format_terms(die, add)
    _apkid_format_terms(apkid, add)
    if kind == "format-unknown":
        for term in FORMAT_UNKNOWN_TERMS:
            add(term, "trigger#kind", kind)
    elif sample_hint:
        suffix = Path(str(sample_hint)).suffix.lower()
        if suffix in SUFFIX_TERMS:
            add(SUFFIX_TERMS[suffix], "trigger#sample_hint", sample_hint)
    if not out:
        # the anchored sample is a byte container — always true, never
        # fabricated (the standing-facet floor)
        out.append(("binary", {"source": "sample:bins",
                               "value": sample_hint or "bins"}))
    return out


def _technique_pool(apkid, obstacles: list[dict],
                    token: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []

    def add(term: str, source: str, value) -> None:
        term = _norm(term)
        if term and len(term) <= TERM_MAX_CHARS:
            out.append((term, {"source": source, "value": str(value)}))

    summary = apkid.get("summary") if isinstance(apkid, dict) else None
    summary = summary if isinstance(summary, dict) else {}
    for rule in summary.get("anti_analysis") or []:
        if isinstance(rule, str) and rule:
            add(rule, "evidence/apkid.json#summary.anti_analysis", rule)
    for row in obstacles:
        term = OBSTACLE_KIND_TERMS.get(str(row.get("kind") or ""))
        if term:
            add(term, f"runs/obstacles/{row.get('id')}#kind",
                row.get("kind"))
    if not out:
        for word in _tokenize(token):
            add(word, "trigger#token", token)
    return out


def _tool_pool(token: str,
               obstacles: list[dict]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    full = _norm(token)
    if full:
        out.append((full, {"source": "trigger#token", "value": token}))
    for word in re.split(r"[^a-z0-9]+", full):
        if len(word) >= 2:
            out.append((word, {"source": "trigger#token", "value": token}))
    for row in obstacles:
        family = str(row.get("method_family") or "")
        if family:
            out.append((_norm(family),
                        {"source": f"runs/obstacles/{row.get('id')}"
                                   "#method_family", "value": family}))
    return out


def _error_pools(die, obstacles: list[dict]) -> tuple[list, list]:
    """(obstacle-face pool, probe-face pool) from cause lines and die
    call_errors — only real material, never fabricated."""
    obstacle_pool: list[tuple[str, dict]] = []
    for row in obstacles[-3:]:  # the most recent rows
        cause = str(row.get("cause") or "")
        for word in _tokenize(cause):
            obstacle_pool.append((word, {
                "source": f"runs/obstacles/{row.get('id')}#cause",
                "value": cause}))
    probe_pool: list[tuple[str, dict]] = []
    errors = die.get("call_errors") if isinstance(die, dict) else None
    if isinstance(errors, dict):
        for key in sorted(errors):
            probe_pool.append((_norm(key), {
                "source": "evidence/die.json#call_errors", "value": key}))
    return obstacle_pool, probe_pool


def _facet(kind: str, face: str | None,
           pool: list[tuple[str, dict]]) -> dict | None:
    """Dedup (first appearance wins), cap MAX_TERMS, attach per-term
    provenance. An empty pool yields no facet (never fabricated)."""
    terms: list[str] = []
    prov: list[dict] = []
    for term, p in pool:
        if term in terms:
            continue
        terms.append(term)
        prov.append({**p, "term": term})
        if len(terms) >= MAX_TERMS:
            break
    if not terms:
        return None
    return {"kind": kind, "face": face, "terms": terms,
            "query": " ".join(terms), "provenance": prov}


def formulate_problem(ws, trigger) -> dict:
    """The problem representation: enumerate from the environment
    snapshot + obstacle registry + trigger, summarize into 3-5 facets.
    Pure read; never raises on workspace garbage (tolerant reads)."""
    ws = Path(ws)
    kind, token, sample_hint, source_file = _trigger_fields(trigger)
    die = _read_json(ws / "evidence" / "die.json")
    apkid = _read_json(ws / "evidence" / "apkid.json")
    obstacles = _read_obstacles(ws)
    facets: list[dict] = []
    for facet in (
        _facet("format_family", None,
               _format_pool(die, apkid, sample_hint, kind)),
        _facet("technique", None,
               _technique_pool(apkid, obstacles, token)),
        _facet("tool", None, _tool_pool(token, obstacles)),
    ):
        if facet:
            facets.append(facet)
    obstacle_pool, probe_pool = _error_pools(die, obstacles)
    for face, pool in (("obstacle", obstacle_pool),
                       ("probe", probe_pool)):
        facet = _facet("error_signature", face, pool)
        if facet:
            facets.append(facet)
    return {
        "schema": SCHEMA,
        "trigger": {"kind": kind, "token": token,
                    "sample_hint": sample_hint,
                    "source_file": source_file},
        "facets": facets[:MAX_FACETS],
        "sources_read": [
            rel for rel, present in (
                ("evidence/die.json", die is not None),
                ("evidence/apkid.json", apkid is not None),
                ("runs/obstacles", bool(obstacles)),
            ) if present
        ] + ["trigger:" + (source_file or kind)],
    }


def fragment_baseline_terms(token: str) -> list[str]:
    """The pre-#487 query: exactly the fragments the trigger carried
    (the full token + its component words) — the fixture comparison's
    baseline."""
    full = _norm(token)
    terms = [full] if full else []
    terms += [w for w in re.split(r"[^a-z0-9]+", full) if len(w) >= 2]
    return list(dict.fromkeys(terms))


# ---------------------------------------------------------------------------
# faceted retrieval + coverage (organ 2)
# ---------------------------------------------------------------------------


def _load_cards(corpus: Path) -> list[tuple[str, str]]:
    """(corpus-relative path, normalized text) for every card file,
    sorted for determinism; unreadable/oversized cards are skipped."""
    cards: list[tuple[str, str]] = []
    for path in sorted(corpus.rglob("*")):
        if not path.is_file() or path.suffix not in CARD_SUFFIXES:
            continue
        try:
            if path.stat().st_size > CARD_MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _warn("query_formulation_card",
                  f"{path}: {type(exc).__name__}: {exc}")
            continue
        cards.append((path.relative_to(corpus).as_posix(), _norm(text)))
    return cards


def _hits_for(cards: list[tuple[str, str]], terms: list[str],
              top_k: int) -> list[dict]:
    """Cards covering the term set at the half-ceiling rule, ranked
    (score desc, path asc), capped top_k."""
    need = _need(terms)
    patterns = [(t, _term_pattern(t)) for t in terms]
    scored: list[tuple[str, list[str]]] = []
    for path, ntext in cards:
        matched = [t for t, pat in patterns if pat.search(ntext)]
        if len(matched) >= need:
            scored.append((path, matched))
    scored.sort(key=lambda item: (-len(item[1]), item[0]))
    return [{"path": path, "matched": matched, "score": len(matched)}
            for path, matched in scored[:top_k]]


def _reformulated_terms(facet: dict) -> list[str]:
    """The ONE-retry rewording: provenance values tokenized, minus the
    original terms, capped MAX_TERMS. Empty/identical material yields
    no retry (a fake retry is worse than an honest corpus-lack)."""
    originals = set(facet.get("terms") or [])
    seen = set(originals)
    out: list[str] = []
    for p in facet.get("provenance") or []:
        if not isinstance(p, dict):
            continue
        for word in _tokenize(str(p.get("value") or "")):
            if word not in seen:
                seen.add(word)
                out.append(word)
                if len(out) >= MAX_TERMS:
                    return out
    return out


def _corpus_label(corpus: Path) -> str:
    if corpus.parent.name == "references" and corpus.name == "re-library":
        return "references/re-library"
    return corpus.as_posix()


def retrieve_facets(corpus, formulation: dict | None,
                    *, top_k: int = TOP_K) -> dict:
    """The coverage matrix: per facet (independently), the hit cards +
    verdict. Empty facet -> ONE reformulation -> re-retrieve -> else
    corpus-lack. A missing corpus is a named degradation (facets=[]),
    never wrong verdicts."""
    corpus = Path(corpus)
    facets = [f for f in ((formulation or {}).get("facets") or [])
              if isinstance(f, dict) and f.get("terms")]
    if not corpus.is_dir():
        return {"schema": COVERAGE_SCHEMA, "corpus": _corpus_label(corpus),
                "error": "corpus-missing", "facets": [],
                "summary": {"facets": 0, "hits": 0,
                            "reformulated_hits": 0, "corpus_lack": 0}}
    cards = _load_cards(corpus)
    rows: list[dict] = []
    for facet in facets:
        terms = [str(t) for t in facet["terms"]]
        row = {"kind": facet.get("kind"), "face": facet.get("face"),
               "query": facet.get("query") or " ".join(terms),
               "terms": terms,
               "hits": _hits_for(cards, terms, top_k),
               "reformulated": False}
        if row["hits"]:
            row["verdict"] = "hit"
        else:
            alt = _reformulated_terms(facet)
            if alt:
                row["reformulated"] = True
                row["reformulated_query"] = " ".join(alt)
                retry = _hits_for(cards, alt, top_k)
                if retry:
                    row["hits"] = retry
                    row["verdict"] = "reformulated-hit"
                else:
                    row["verdict"] = "corpus-lack"
            else:
                row["verdict"] = "corpus-lack"
        rows.append(row)
    return {"schema": COVERAGE_SCHEMA, "corpus": _corpus_label(corpus),
            "facets": rows, "summary": _summarize(rows)}


def _summarize(rows: list[dict]) -> dict:
    return {
        "facets": len(rows),
        "hits": sum(1 for r in rows if r["verdict"] == "hit"),
        "reformulated_hits": sum(1 for r in rows
                                 if r["verdict"] == "reformulated-hit"),
        "corpus_lack": sum(1 for r in rows
                           if r["verdict"] == "corpus-lack"),
    }


def coverage_summary(coverage: dict | None) -> dict:
    """The compact audit face of the matrix (the detail-row payload)."""
    if not isinstance(coverage, dict):
        return {}
    return dict(coverage.get("summary") or {})


def default_corpus(repo=None) -> Path:
    """references/re-library against the module's install parent
    (in-repo scripts/ -> repo root; deployed .claude/scripts ->
    .claude/) — or an explicit repo root."""
    root = Path(repo) if repo else Path(__file__).resolve().parents[1]
    return root / "references" / "re-library"


def formulate_and_retrieve(ws, trigger, repo=None) -> dict:
    """The host convenience: one call, both documents."""
    formulation = formulate_problem(ws, trigger)
    coverage = retrieve_facets(default_corpus(repo), formulation)
    return {"formulation": formulation, "coverage": coverage}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="query formulation (#487): problem enumeration + "
                    "faceted retrieval coverage")
    ap.add_argument("ws", help="workspace path")
    ap.add_argument("--formulate", action="store_true",
                    help="read runs/distill-trigger.json, formulate + "
                         "retrieve, print the two documents")
    ap.add_argument("--corpus", default=None,
                    help="retrieval corpus override (default: the "
                         "install-parent references/re-library)")
    args = ap.parse_args(argv)
    if not args.formulate:
        ap.print_usage()
        return 2
    ws = Path(args.ws)
    stamp = _read_json(ws / TRIGGER_STAMP_REL)
    triggers = stamp.get("triggers") if isinstance(stamp, dict) else None
    if not isinstance(triggers, list) or not triggers:
        print(json.dumps({"formulation": None, "coverage": None,
                          "reason": "no trigger stamp"},
                         sort_keys=True))
        return 1
    trigger = triggers[0] if isinstance(triggers[0], dict) else {}
    out = formulate_and_retrieve(ws, trigger)
    if args.corpus:
        out["coverage"] = retrieve_facets(
            Path(args.corpus), out["formulation"])
    print(json.dumps(out, sort_keys=True, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
