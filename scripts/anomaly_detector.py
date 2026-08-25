#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anomaly_detector.py — anomaly scoring against a baseline corpus (#663).

Issue #663: human RE analysts notice "this is unusual" observations throughout
investigation. The current loop has no mechanism to register these. This
gate computes anomaly as the MAX of three sub-scores (lexical rarity,
semantic unusualness, path unusualness) so any single dimension can flag.

Spec: openspec/changes/issue-663-anomaly-detection/{proposal,design,specs/...}.
Design references D1-D10. Fail-open semantics per D5.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


DEFAULT_THRESHOLD = 0.7
NO_SCORE = 0.0
SEP = " | "


# ---------------------------------------------------------------------------
# Baseline corpus carrier (design D2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BaselineCorpus:
    """Three frequency dictionaries; all optional, all default to empty.

    A frozen dataclass so callers can treat instances as immutable keys
    when memoizing scans. The three dicts are deliberately kept independent
    so callers can populate any subset (e.g., operator-provided patterns
    without RE-library refs).
    """
    term_freq: Dict[str, int] = field(default_factory=dict)
    pair_freq: Dict[Tuple[str, str], int] = field(default_factory=dict)
    path_freq: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sub-scores (design D1.1-D1.3)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Whitespace tokenizer. Empty/None input -> []."""
    if not text:
        return []
    return text.split()


def _lexical_rarity_score(tokens: List[str], baseline: BaselineCorpus) -> float:
    """Mean token rarity in [0, 1]. Missing tokens contribute rarity 1.0.

    Per design D1.1: rarity = 1 - freq/max_freq; mean over ALL tokens
    (present tokens contribute their computed rarity; missing tokens
    contribute the maximum rarity 1.0 because "unseen = anomalous").
    """
    if not tokens or not baseline.term_freq:
        return NO_SCORE
    max_freq = max(baseline.term_freq.values())
    rarities = [1.0 - baseline.term_freq.get(t, 0) / max_freq for t in tokens]
    return sum(rarities) / len(rarities)


def _semantic_unusualness_score(
    claim_id: Optional[str],
    conclusion: str,
    baseline: BaselineCorpus,
) -> float:
    """Match (claim_id, conclusion) pair in baseline. Missing pair -> 1.0.

    Per design D1.2. Exact-match only (no fuzzy / prefix) — false positives
    are worse than false negatives here, and the analyst can always
    populate the baseline for known patterns.
    """
    if not conclusion or not baseline.pair_freq:
        return NO_SCORE
    if claim_id is not None:
        exact_key = (claim_id, conclusion)
        if exact_key in baseline.pair_freq:
            max_freq = max(baseline.pair_freq.values())
            return 1.0 - baseline.pair_freq[exact_key] / max_freq
    return 1.0  # missing pair -> anomalous


def _path_unusualness_score(
    sample_refs: List[str],
    baseline: BaselineCorpus,
) -> float:
    """Mean path rarity in [0, 1]. Missing paths contribute rarity 1.0.

    Per design D1.3. Empty sample_refs -> 0.0 (cannot be anomalous on this
    dimension when there's no path to compare).
    """
    if not sample_refs or not baseline.path_freq:
        return NO_SCORE
    max_freq = max(baseline.path_freq.values())
    rarities = [1.0 - baseline.path_freq.get(p, 0) / max_freq for p in sample_refs]
    return sum(rarities) / len(rarities)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_fact(fact_text, baseline: BaselineCorpus) -> float:
    """Compute anomaly score for a fact TEXT (no claim_id / sample_refs).

    Returns float in [0, 1]. For an isolated text call (no claim context),
    only the LEXICAL sub-score is computed — semantic requires claim_id
    (which is None for an isolated string call) and path requires
    sample_refs (none in pure text). scan_anomalies, which has access to
    claim_id and sample_refs from _INDEX/frontmatter, uses all three
    dimensions.

    Fail-open: None / empty text / empty baseline -> 0.0.
    """
    if not fact_text or not isinstance(fact_text, str):
        return NO_SCORE
    if not baseline.term_freq:
        return NO_SCORE
    tokens = _tokenize(fact_text)
    return _lexical_rarity_score(tokens, baseline)


def scan_anomalies(
    index_path: Path,
    facts_dir: Path,
    baseline: Optional[BaselineCorpus] = None,
    threshold: Optional[float] = None,
) -> List[dict]:
    """Scan workspace for anomalous PROVEN facts.

    Per design D4 / D6. Returns list of dicts, each with:
        {fact_id, claim_id, score, top_dimension}
    Empty list if no anomalies, no PROVEN facts, or empty baseline (fail-open
    per design D5 — no signal means no false-positive).

    `baseline` defaults to None which loads via _load_baseline (RE-library
    refs + operator config + samples, per design D2). For tests, pass an
    explicit BaselineCorpus.
    """
    if baseline is None:
        baseline = _load_baseline()
    threshold = threshold if threshold is not None else DEFAULT_THRESHOLD

    # Fail-open: empty baseline = no signal (design D5).
    if not baseline.term_freq and not baseline.pair_freq and not baseline.path_freq:
        return []

    rows = _read_index_rows(index_path)
    anomalies: List[dict] = []
    for row in rows:
        if row.get("status") != "PROVEN":
            continue
        conclusion = row.get("conclusion", "")
        claim_id = row.get("claim_id")
        fact_text = _read_fact_text(facts_dir, row["fact_id"])
        sample_refs = _extract_sample_refs(fact_text)

        tokens = _tokenize(conclusion)
        lex = _lexical_rarity_score(tokens, baseline)
        sem = _semantic_unusualness_score(claim_id, conclusion, baseline)
        path = _path_unusualness_score(sample_refs, baseline)

        score = max(lex, sem, path)
        if score >= threshold:
            # Determine which dimension scored highest (tie-break: lexical
            # over semantic over path — deterministic for unit-test assertions)
            top = "lexical"
            if sem >= lex and sem >= path:
                top = "semantic"
            elif path >= lex and path >= sem:
                top = "path"
            anomalies.append({
                "fact_id": row["fact_id"],
                "claim_id": claim_id,
                "score": score,
                "top_dimension": top,
            })

    return anomalies


def check_fact_anomaly(
    fact_id: str,
    facts_dir: Path,
    baseline: Optional[BaselineCorpus] = None,
    threshold: Optional[float] = None,
) -> Tuple[bool, str]:
    """Single-fact consumer surface. Returns (allowed, reason).

    allowed=False means anomaly detected at >= threshold. The reason
    names the score and threshold (mirrors fact_contradiction_gate's
    check_proven_contradiction shape — hook-wired consumers parse
    the second element).
    """
    if baseline is None:
        baseline = _load_baseline()
    threshold = threshold if threshold is not None else DEFAULT_THRESHOLD

    fact_text = _read_fact_text(facts_dir, fact_id)
    if not fact_text:
        return (True, f"fact {fact_id} not found or empty")

    index_path = facts_dir / "_INDEX.md"
    rows = _read_index_rows(index_path)
    row = next((r for r in rows if r["fact_id"] == fact_id), None)
    if not row:
        return (True, f"fact {fact_id} not in _INDEX")

    conclusion = row.get("conclusion", "")
    claim_id = row.get("claim_id")
    sample_refs = _extract_sample_refs(fact_text)

    tokens = _tokenize(conclusion)
    lex = _lexical_rarity_score(tokens, baseline)
    sem = _semantic_unusualness_score(claim_id, conclusion, baseline)
    path = _path_unusualness_score(sample_refs, baseline)

    score = max(lex, sem, path)
    if score >= threshold:
        return (False, f"fact {fact_id} anomaly score {score:.3f} >= threshold {threshold}")
    return (True, f"fact {fact_id} anomaly score {score:.3f} < threshold {threshold}")


# ---------------------------------------------------------------------------
# Baseline loader (design D2)
# ---------------------------------------------------------------------------

def _load_baseline() -> BaselineCorpus:
    """Load baseline corpus from RE-library refs + operator config + samples.

    Per design D2. Three sources, merged. Fail-open on any failure — returns
    empty BaselineCorpus on error, which scan_anomalies then converts to
    "no anomalies" (no false-positives on a broken baseline).

    The cold-start baseline is empty by design (no prior samples yet);
    RE-library ref scans are a planned followup alongside #358 P4 batch.
    """
    try:
        project_root = Path(__file__).resolve().parents[1]  # scripts/ -> root
    except IndexError:
        return BaselineCorpus()

    term_freq: Dict[str, int] = {}
    pair_freq: Dict[Tuple[str, str], int] = {}
    path_freq: Dict[str, int] = {}

    # Source 1: RE-library pattern docs (deterministic, pre-built)
    re_lib = project_root / "references" / "re-library"
    if re_lib.is_dir():
        for md in sorted(re_lib.glob("*.md")):
            try:
                _ingest_re_library_doc(md, term_freq, pair_freq, path_freq)
            except Exception:
                continue  # skip unreadable docs (fail-open)

    # Source 2: prior samples (~/.kunglao/samples/) — not yet shipped (#358).
    # Placeholder: will be wired when cross-sample baseline lands.

    # Source 3: operator-provided patterns (analysis_state.txt baseline_corpus:)
    # Placeholder: will be wired when operator-config baseline lands.

    return BaselineCorpus(term_freq=term_freq, pair_freq=pair_freq, path_freq=path_freq)


def _ingest_re_library_doc(
    path: Path,
    term_freq: Dict[str, int],
    pair_freq: Dict[Tuple[str, str], int],
    path_freq: Dict[str, int],
) -> None:
    """Best-effort token frequency accumulation from a single RE-library doc.

    Each doc contributes +1 to term_freq per tokenized word. Pair/path
    counters are reserved for future structured ingestion — current docs
    are prose, so we only get term_freq from this source.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    for token in _tokenize(text):
        # Strip markdown noise (code-block operators etc.) by skipping tokens
        # with non-word chars at boundaries. Cheap heuristic: only count
        # tokens that contain at least one alphabetic char.
        if any(c.isalpha() for c in token):
            term_freq[token] = term_freq.get(token, 0) + 1


# ---------------------------------------------------------------------------
# Helpers (file IO + frontmatter parsing)
# ---------------------------------------------------------------------------

def _read_index_rows(index_path: Path) -> List[dict]:
    """Parse facts/_INDEX.md — same row grammar as fact_contradiction_gate.py."""
    if not index_path.exists():
        return []
    rows: List[dict] = []
    for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split(SEP)]
        if len(parts) >= 4:
            rows.append({
                "fact_id": parts[0],
                "status": parts[1],
                "claim_id": parts[2],
                "conclusion": SEP.join(parts[3:]),
            })
    return rows


def _read_fact_text(facts_dir: Path, fact_id: str) -> str:
    f = facts_dir / f"{fact_id}.md"
    if f.exists():
        return f.read_text(encoding="utf-8", errors="replace")
    return ""


def _write_anomaly_note(
    fact_path: Path,
    score: float,
    top_dimension: str,
    threshold: float,
) -> Path:
    """Write a co-resident anomaly note (per design.md D8, tasks.md §4.8).

    Per D8: anomaly is NOT a verdict demotion — the fact's own status stays
    unchanged. The anomaly surfaces as a co-resident note at notes/<fact_id>.md
    so analysts see it in progress_report / digest views.

    Returns the written note path. Caller is responsible for logging the
    note creation via kunglao_log (out of scope for this helper).
    """
    fact_id = fact_path.stem
    notes_dir = fact_path.parent.parent / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    note_path = notes_dir / f"{fact_id}.md"
    body = (
        "---\n"
        f"id: {fact_id}\n"
        "type: observation\n"
        f"boundary_type: anomaly\n"
        f"score: {score:.3f}\n"
        f"top_dimension: {top_dimension}\n"
        f"anomaly_threshold: {threshold}\n"
        "verify_status: pending\n"
        "claim_id: C-NNN\n"  # placeholder; analyst fills when reviewing
        "created: 2026-08-25\n"
        "last_reviewed: 2026-08-25\n"
        "---\n\n"
        f"# Anomaly observation: {fact_id}\n\n"
        f"Score {score:.3f} above threshold {threshold} on dimension "
        f"`{top_dimension}`. Per design.md D8: this is a co-resident observation, "
        "NOT a verdict demotion — the source fact's PROVEN status is preserved.\n\n"
        "## Analyst action\n\n"
        "- [ ] Review: is the anomaly a genuine signal or a baseline gap?\n"
        "- [ ] Confirm: note stays (refute baseline gap, or document the anomaly)\n"
        "- [ ] Refute: delete note + extend `analysis_state.txt` baseline_corpus\n"
    )
    note_path.write_text(body, encoding="utf-8")
    return note_path


def _extract_sample_refs(fact_text: str) -> List[str]:
    """Extract sample_refs from YAML frontmatter (yaml block or line-level).

    Mirrors lint_facts.py tolerant frontmatter parsing — fenced ```yaml
    block first, line-level `sample_refs:` fallback. No LLM call.
    """
    if not fact_text:
        return []
    if yaml is not None:
        for m in re.finditer(r"```yaml\s*(.*?)```", fact_text, re.DOTALL):
            try:
                parsed = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                continue
            if isinstance(parsed, dict):
                refs = parsed.get("sample_refs")
                if isinstance(refs, list):
                    return [str(r) for r in refs if r]
                if isinstance(refs, str) and refs:
                    return [refs]
    # line-level fallback (mirrors lint_facts._extract_yaml_keys)
    for line in fact_text.splitlines():
        if line.lstrip().startswith("sample_refs:"):
            rest = line.split(":", 1)[1].split("#", 1)[0].strip()
            return [r.strip() for r in rest.split(",") if r.strip()]
    return []


# ---------------------------------------------------------------------------
# CLI (design D6)
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="anomaly_detector — scan workspace for anomalous facts"
    )
    parser.add_argument("workspace", type=Path, help="workspace root")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--threshold", type=float, default=None,
                        help=f"anomaly threshold (default {DEFAULT_THRESHOLD})")
    args = parser.parse_args(argv)

    facts_dir = args.workspace / "facts"
    index_path = facts_dir / "_INDEX.md"
    if not index_path.exists():
        print(f"FAIL: no {index_path}", file=sys.stderr)
        return 2

    baseline = _load_baseline()
    anomalies = scan_anomalies(
        index_path, facts_dir,
        baseline=baseline, threshold=args.threshold,
    )

    if args.json:
        print(json.dumps(
            {"anomalies": anomalies, "count": len(anomalies)},
            ensure_ascii=False, indent=2,
        ))
    else:
        for a in anomalies:
            print(f"ANOMALY: {a['fact_id']} (claim {a['claim_id']}) "
                  f"score={a['score']:.3f} top={a['top_dimension']}")
    return 1 if anomalies else 0


if __name__ == "__main__":
    sys.exit(main())
