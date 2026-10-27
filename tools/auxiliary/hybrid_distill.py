# -*- coding: utf-8 -*-
"""hybrid_distill.py — the distillation engine's collection kernel
the engine charter: TWO collection strategies, ONE pipeline.

    python tools/auxiliary/hybrid_distill.py <ws> --strategy self
        [--lessons-library DIR] [--json]

    self   — sources = own context + local products + environment
             observation: D-gate-passing notes (rlvr.distill_dgate),
             active lessons with a next_method, facts/ + env-state
             references. NO search.
    hybrid — self sources ⊕ a network-search ACTION shaped as a research
             LOOP: hypothesis -> search -> SNR gate (novel-increment) ->
             next hypothesis (<= MAX_RESEARCH_ROUNDS; two CONSECUTIVE
             barren rounds ABANDON). The search action is INJECTED
             (`search=` callable / the module performs no network IO of
             its own — tests inject a mock; the CLI refuses hybrid
             without an explicit scripted --research-file). One-shot
             searching is pretending to verify.

The shared downstream (identical for both strategies): clean ->
`distill-item/1` block -> 0-1 score (rlvr.distill_score; assessor
injectable) -> conflict flags (recall top-k similarity, never a silent
overwrite; the lineage wall: external-derived never supersedes
evidence-derived) -> the P1 pool write gate (`episode_pool.write_episode`
UNMODIFIED — the scorecard verification record rides the canonical
surface) -> a `distill-rollout/1` row (admitted +1 / abandoned 0.01 with
the reason kept).

Budget caps per stage are documented policy constants. Zero telemetry
points in the loop faces (Standard 11): refusals raise to the caller.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TOOLS_DIR = next(_p for _p in Path(__file__).resolve().parents
                  if _p.name == "tools")
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402 — CLI convention

_REPO = _TOOLS_DIR.parent
for _base in (str(_REPO / "scripts"), str(_REPO)):
    if _base not in sys.path:
        sys.path.insert(0, _base)

import distill_schema as dsc  # noqa: E402
from rlvr import distill_dgate as dg  # noqa: E402
from rlvr import distill_rollout as dr  # noqa: E402
from rlvr import distill_score as sc  # noqa: E402

#: policy constants (documented, not fitted) — the research-loop budget
MAX_RESEARCH_ROUNDS = 4      # the <=N cap (ruling 2)
BARREN_ABANDON = 2           # consecutive barren rounds -> ABANDON
RESULTS_PER_ROUND_CAP = 8    # per-round results cap (per-stage budget)

#: the conflict face: a corpus ref at/above this similarity must be
#: superseded EXPLICITLY (flagged rows, never silent overwrites)
CONFLICT_SIMILARITY = 0.8
CONFLICT_TOP_K = 3

_TOKEN_RE = re.compile(r"[a-z][a-z-]+")


class CollectionError(ValueError):
    """The collection refused: hybrid without an injected search action,
    or a malformed source."""


# ------------------------------------------------------------ SNR gate

def _tokens(text) -> set[str]:
    return set(_TOKEN_RE.findall(str(text or "").lower()))


def novel_increment(results: list[str], corpus: list[str]) -> list[str]:
    """The SNR face: the results' novel-token increment over the known
    corpus (self sources + all prior rounds). Empty = barren round."""
    seen: set[str] = set()
    for entry in corpus:
        seen |= _tokens(entry)
    novel: list[str] = []
    novel_tokens: set[str] = set()
    for result in results:
        fresh = _tokens(result) - seen - novel_tokens
        if fresh:
            novel_tokens |= fresh
            novel.append(str(result))
    return novel


def run_research(seed_hypothesis: str, search, *,
                 known_corpus: list[str] | None = None,
                 next_hypothesis=None,
                 max_rounds: int | None = None) -> dict:
    """THE research loop (ruling 2): hypothesis -> search -> SNR gate ->
    next hypothesis, <= max_rounds; two consecutive barren rounds abandon.
    `search` is the injected action; `next_hypothesis(results, corpus,
    prior)` returns the next hypothesis or None to stop. Convergence with
    zero corpus growth is the no-signal abandon (a one-shot search cannot
    pass). Returns {status, reason, rounds, corpus}."""
    max_rounds = int(max_rounds or MAX_RESEARCH_ROUNDS)
    corpus = [str(c) for c in (known_corpus or [])]
    baseline = len(corpus)
    rounds: list[dict] = []
    barren = 0
    hyp = str(seed_hypothesis)
    for round_no in range(1, max_rounds + 1):
        results = [str(r) for r in (search(hyp) or [])] \
            [:RESULTS_PER_ROUND_CAP]
        novel = novel_increment(results, corpus)
        fertile = bool(novel)
        rounds.append({"round": round_no, "hypothesis": hyp,
                       "fertile": fertile, "novel": len(novel)})
        if fertile:
            corpus.extend(novel)
            barren = 0
        else:
            barren += 1
            if barren >= BARREN_ABANDON:
                return {"status": "abandoned", "reason": "barren",
                        "rounds": rounds, "corpus": corpus}
        nxt = next_hypothesis(results, corpus, hyp) \
            if next_hypothesis else None
        if nxt is None:
            if len(corpus) > baseline:
                return {"status": "converged", "rounds": rounds,
                        "corpus": corpus}
            return {"status": "abandoned", "reason": "no-signal",
                    "rounds": rounds, "corpus": corpus}
        hyp = str(nxt)
    return {"status": "budget", "reason": "max-rounds",
            "rounds": rounds, "corpus": corpus}


# --------------------------------------------------------------- clean

def clean_note(text: str) -> dict:
    """A D-gate-passing note's body -> the methodology skeleton. Lines
    classify deterministically: verdict algebra (:= / pass|fail lead),
    pseudocode (a paren-call tail), otherwise branch rows."""
    body = str(text or "")
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
    content = {"branch_table": [], "verdict_algebra": [],
               "pseudocode_groups": []}
    for raw in body.splitlines():
        line = raw.strip().lstrip("-*").strip()
        line = re.sub(r"^\d+[.)]\s*", "", line)
        if not line or line.startswith("#"):
            continue
        if ":=" in line or re.match(r"^(pass|fail)\b", line,
                                    re.IGNORECASE):
            content["verdict_algebra"].append(line)
        elif line.endswith(")"):
            content["pseudocode_groups"].append(line)
        else:
            content["branch_table"].append(line)
    return content


def clean_lesson(meta: dict) -> dict:
    """An active lesson's next_method -> the methodology skeleton (a
    single branch row: the method IS the rule)."""
    method = str((meta or {}).get("next_method") or "").strip()
    return {"branch_table": [method] if method else [],
            "verdict_algebra": [], "pseudocode_groups": []}


# ---------------------------------------------------------- collection

def _load_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    try:
        import yaml  # noqa: PLC0415 — lazy, the block is optional
        meta = yaml.safe_load(parts[1]) or {}
        return meta if isinstance(meta, dict) else {}
    except Exception:  # noqa: BLE001 — a bad block degrades to empty
        return {}


def collect_sources(ws, *, lessons_library=None) -> dict:
    """The self sources (ruling 1): D-gate-passing notes + active lessons
    + facts/ and env-state references. Returns {notes: [Path],
    lessons: [(slug, meta)], refs: [str], features: [str]}. Absent
    sources contribute nothing (absence is not a source)."""
    ws = Path(ws)
    notes = dg.passing_notes(ws)
    lessons: list[tuple[str, dict]] = []
    lib = Path(lessons_library) if lessons_library else None
    if lib is not None and lib.is_dir():
        for p in sorted(lib.glob("lesson-*.md")):
            meta = _load_frontmatter(p)
            if meta.get("deprecated") is True:
                continue  # tombstoned lessons are off the shelves
            if not str(meta.get("next_method") or "").strip():
                continue
            lessons.append((str(meta.get("slug") or p.stem), meta))
    refs: list[str] = []
    features = {"distill"}
    facts = ws / "facts"
    if facts.is_dir():
        for p in sorted(facts.glob("*.md")):
            if p.name.upper() == "_INDEX.MD":
                continue
            refs.append(f"facts/{p.name}")
    env = ws / "runs" / "env-state.json"
    if env.is_file():
        refs.append("runs/env-state.json")
        features.add("env-state")
    for note in notes:
        refs.append(str(note.relative_to(ws)))
    return {"notes": notes, "lessons": lessons, "refs": refs,
            "features": sorted(features)}


def _block_for(source: str, content: dict, *, strategy: str,
               refs: list[str], features: list[str],
               epistemic_class: str = "evidence-derived") -> dict:
    return dsc.lint_block({
        "schema": "distill-item/1",
        "source_strategy": str(strategy),
        "source_refs": refs or [source],
        "collection_ts": _now_z(),
        "content": content,
        "scoring": {d: 0.0 for d in dsc.SCORING_DIMENSIONS}
        | {"total": 0.0, "assessor": "pending"},
        "epistemic_class": epistemic_class,
        "lineage": {"supersedes": "", "superseded_by": ""},
        "optimization_rounds": 0,
        "context_features": [str(f)[:64] for f in features[:16]],
    })


# ------------------------------------------------------- conflict face

def flag_conflicts(ws, fragments: list[str], *,
                   top_k: int = CONFLICT_TOP_K) -> list[dict]:
    """Recall top-k similarity against existing pool items (Jaccard on
    fragment tokens). Flagged rows, never silent resolutions."""
    want = _tokens(" ".join(str(f) for f in fragments or []))
    if not want:
        return []
    from rlvr import episode_pool as pool  # noqa: PLC0415 — lazy
    scored: list[dict] = []
    for _path, doc in pool.load_all(ws):
        have = _tokens(" ".join(doc.get("reusable_fragments") or []))
        union = want | have
        j = len(want & have) / len(union) if union else 0.0
        scored.append({"claim": str(doc.get("claim")),
                       "similarity": j})
    scored.sort(key=lambda r: (-r["similarity"], r["claim"]))
    return [r for r in scored[:top_k] if r["similarity"] > 0.0]


# ------------------------------------------------------- the land face

def _fragments_from(content: dict) -> list[str]:
    rows = list(content.get("branch_table") or []) \
        + list(content.get("verdict_algebra") or [])
    return [r[:240] for r in rows][:12]


def land_item(ws, item_id: str, block: dict, *,
              assessor=None) -> dict:
    """THE shared downstream, one item: score -> conflict gate (the
    lineage wall) -> scorecard verification -> the P1 pool write gate ->
    the rollout row. A refusal NEVER touches the pool; an abandoned
    attempt still settles (reward 0.01, reason kept)."""
    ws = Path(ws)
    from rlvr import episode_pool as pool  # noqa: PLC0415 — lazy
    corpus = [doc for _p, doc in pool.load_all(ws)]
    result = sc.score_item(block, corpus, assessor=assessor)
    block = dict(block, scoring=dict(
        block["scoring"], **{d: result[d] for d in dsc.SCORING_DIMENSIONS},
        total=result["total"], assessor=result["assessor"]))
    fragments = _fragments_from(block["content"])
    conflicts = flag_conflicts(ws, fragments)
    hot = [c for c in conflicts
           if c["similarity"] >= CONFLICT_SIMILARITY]
    if hot and not str(block["lineage"].get("supersedes") or "").strip():
        row = dr.record_attempt(
            ws, item_id, strategy=block["source_strategy"],
            score=result["total"], product=None,
            reason="conflict: near-duplicate of "
                   + ",".join(c["claim"] for c in hot)
                   + " without supersedes")
        return {"landed": False, "reason": "conflict",
                "conflicts": conflicts, "score": result["total"],
                "reward": row["reward"], "row": row}
    if hot and block["lineage"].get("supersedes"):
        old_claim = str(block["lineage"]["supersedes"])
        old = next((doc for _p, doc in pool.load_all(ws)
                    if str(doc.get("claim")) == old_claim), None)
        if old is None:
            return {"landed": False, "reason": "unknown-supersedes",
                    "conflicts": conflicts, "score": result["total"]}
        old_class = str((old.get("distill") or {})
                        .get("epistemic_class") or "evidence-derived")
        if not dsc.lineage_wall_ok(block["epistemic_class"], old_class):
            row = dr.record_attempt(
                ws, item_id, strategy=block["source_strategy"],
                score=result["total"], product=None,
                reason="lineage-wall: "
                       f"{block['epistemic_class']} never "
                       f"supersedes {old_class}")
            return {"landed": False, "reason": "lineage-wall",
                    "conflicts": conflicts, "score": result["total"],
                    "reward": row["reward"], "row": row}
    if not result["admitted"]:
        row = dr.record_attempt(ws, item_id,
                                strategy=block["source_strategy"],
                                score=result["total"], product=None,
                                reason=result["reason"])
        return {"landed": False, "reason": "below-threshold",
                "conflicts": conflicts, "score": result["total"],
                "reward": row["reward"], "row": row,
                "score_result": result}

    # admitted: the scorecard verification rides the canonical surface,
    # then the P1 write gate (trust resolves through the UNMODIFIED spine)
    card = ws / "runs" / f"verification-{item_id}.md"
    card.parent.mkdir(parents=True, exist_ok=True)
    dims = ", ".join(f"{d}={result[d]:.2f}"
                     for d in dsc.SCORING_DIMENSIONS)
    card.write_text(
        f"# distill scorecard {item_id}\n\nverdict: verified\n\n"
        f"assessor: {result['assessor']}\n{dims}\n"
        f"total: {result['total']:.2f}\n", encoding="utf-8")
    doc = {
        "schema": "episode/1",
        "id": f"E-{item_id}",
        "claim": str(item_id),
        "created": _now_z(),
        "updated": _now_z(),
        "context_features": list(block.get("context_features")
                                 or ["distill"]),
        "commits": [
            {"seq": 1, "action": "select",
             "summary": f"collected via {block['source_strategy']}"},
            {"seq": 2, "action": "deliver",
             "summary": f"item scored {result['total']:.2f} "
                        f"({result['assessor']})"},
        ],
        "outcome": {"status": "completed", "verified": True,
                    "evidence_ref": f"runs/verification-{item_id}.md"},
        "cost": {"tokens": 0.0, "seconds": 0.0},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
        "reusable_fragments": fragments,
        "milestones": [],
        "distill": dsc.lint_block(block),
    }
    path = pool.write_episode(ws, doc)
    row = dr.record_attempt(ws, item_id,
                            strategy=block["source_strategy"],
                            score=result["total"], product=str(path))
    return {"landed": True, "reason": "", "conflicts": conflicts,
            "score": result["total"], "reward": row["reward"],
            "row": row, "path": str(path),
            "score_result": result}


# --------------------------------------------------- the pipeline face

def run_collection(ws, *, strategy: str = "self",
                   lessons_library=None, assessor=None,
                   search=None, known_corpus=None,
                   next_hypothesis=None) -> dict:
    """TWO strategies, ONE pipeline (ruling 1). `hybrid` REQUIRES the
    injected `search` action (CollectionError otherwise) and runs the
    research loop first; the corpus it converges on joins the sources.
    Returns {strategy, attempts: [rows], rollout_rows, research}."""
    if strategy not in dsc.SOURCE_STRATEGIES:
        raise CollectionError(
            f"strategy must be one of {dsc.SOURCE_STRATEGIES}")
    if strategy == "hybrid" and search is None:
        raise CollectionError(
            "hybrid requires the injected search action — one-shot "
            "searching is pretending to verify")
    ws = Path(ws)
    sources = collect_sources(ws, lessons_library=lessons_library)
    research = None
    corpus = [str(c) for c in (known_corpus or [])]
    if strategy == "hybrid":
        research = run_research(
            _hypothesis_from(sources), search,
            known_corpus=corpus + [str(s) for s in sources["refs"]],
            next_hypothesis=next_hypothesis)
        corpus = research["corpus"]

    attempts: list[dict] = []
    rollout_rows: list[dict] = []

    def _try(item_id: str, content: dict, refs: list[str],
             cls: str = "evidence-derived") -> None:
        block = _block_for(item_id, content, strategy=strategy,
                           refs=refs,
                           features=list(sources["features"]), )
        block["epistemic_class"] = cls
        out = land_item(ws, item_id, block, assessor=assessor)
        attempts.append({
            "item": item_id,
            "score": out["score"],
            "product": out.get("path", "abandoned"),
            "reason": out["reason"],
            "reward": out["reward"],
            "source_refs": refs,
            "conflicts": out["conflicts"],
        })
        rollout_rows.append(out["row"])

    for note in sources["notes"]:
        content = clean_note(note.read_text(encoding="utf-8",
                                            errors="replace"))
        if not any(content.values()):
            continue  # no skeleton -> the item doesn't exist
        _try(f"D-note-{note.stem}", content,
             [str(note.relative_to(ws))])
    for slug, meta in sources["lessons"]:
        content = clean_lesson(meta)
        if not any(content.values()):
            continue
        _try(f"D-lesson-{slug}", content, [f"lesson:{slug}"])
    return {"strategy": strategy, "attempts": attempts,
            "rollout_rows": rollout_rows, "research": research,
            "source_refs": sources["refs"],
            "features": sources["features"]}


def _hypothesis_from(sources: dict) -> str:
    """The seed hypothesis: the collection's open question, derived from
    the self sources' faces (never a canned query)."""
    faces = ", ".join(sources["features"]) or "cold workspace"
    return f"what method guidance is missing for: {faces}"


def _now_z() -> str:
    try:
        from harness_common import utc_now_z  # noqa: PLC0415 — lazy
        return utc_now_z()
    except Exception:  # noqa: BLE001 — the block needs a clock stamp
        import datetime
        return datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hybrid_distill.py",
        description="the distillation engine's collection kernel")
    ap.add_argument("workspace")
    ap.add_argument("--strategy", choices=dsc.SOURCE_STRATEGIES,
                    default="self")
    ap.add_argument("--lessons-library", default=None)
    ap.add_argument("--research-file", default=None,
                    help="hybrid via CLI: a scripted JSON "
                         "([{results: [...], next: ...}]) — the module "
                         "performs no network IO of its own")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    search = None
    if args.strategy == "hybrid":
        if not args.research_file:
            ap.error("--strategy hybrid requires --research-file (the "
                     "module performs no network IO of its own)")
        script = json.loads(Path(args.research_file).read_text(
            encoding="utf-8"))
        state = {"n": 0}

        def search(_hyp: str) -> list[str]:  # noqa: F811
            state["n"] += 1
            page = script[state["n"] - 1] \
                if state["n"] <= len(script) else {}
            return [str(r) for r in (page.get("results") or [])]

        # a scripted page's `next` closes or continues the loop
        def next_hyp(results, corpus, hyp):
            page = script[min(state["n"], len(script)) - 1]
            return page.get("next")

    out = run_collection(args.workspace, strategy=args.strategy,
                         lessons_library=args.lessons_library,
                         search=search,
                         next_hypothesis=next_hyp
                         if args.strategy == "hybrid" else None)
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        landed = [a for a in out["attempts"] if a["product"]
                  != "abandoned"]
        print(f"strategy={out['strategy']} "
              f"items={len(out['attempts'])} landed={len(landed)}")
        for a in out["attempts"]:
            print(f"  {a['item']} score={a['score']:.2f} "
                  f"{a['product']}"
                  + (f" ({a['reason']})" if a["reason"] else ""))
    return 0


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
