#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""winrate_curve.py — #156 win-rate curve aggregator + single-file chart face.

All offline (tuition_curve discipline): pure read-side over the settlement
stream — no thresholds, no gating, no calibration, nothing written into the
workspace except the --html rendering target handed to it explicitly.

Counting-only slice of the value-loop curve (v0.1.5): the data spine that
#129 (windowed thresholds), #134 (Platt training history) and #135
(prediction hit-rate) all read. The calibrated curve + divergence stay
v0.1.6 — this card accumulates the history.

Streams consumed (tolerant readers — blank / malformed / non-dict lines are
skipped; missing files are an EMPTY stream, never an error):
  runs/roi-settlements.jsonl  — settlement rows (roi_settlement.py schema:
                                settle_id, claim_id, intent.context_tags,
                                intent_met, roi_class, outcome)
  runs/case-bank.jsonl        — the settled-case mirror (roi_class +
                                context_tags; case_bank.py schema)
  runs/oracle-status.json     — oracle status face (oracle_runner.py
                                write_status schema: per-case pass/fail/
                                pending + counts)
  claim-register.yaml         — claim -> answers_question (PQ-family key)

Counting contract (belief-side, owner-approved minimal slice):
  - the curve runs over SCORED settlements only: roi_class POSITIVE or
    NEGATIVE. NEUTRAL / UNRESOLVED rows are settlements but not win-rate
    observations (roi_settlement ruling 2: nothing comparable observed is
    never a negative), so they never enter a denominator. The case-bank
    mirror NEVER joins the series either — every settled case is banked,
    so merging would double-count; it ships as a counts-only summary.
  - rate = POSITIVE / (POSITIVE + NEGATIVE), rounded to 4 decimals
    (tuition_curve rounding convention); zero observations -> None
    (insufficient, never 0.0).
  - stream order is file append order — deterministic, no clock parsing
    (case_bank retrieval convention).
  - PQ family of a settlement: the claim's answers_question from
    claim-register.yaml; a claim outside the register falls back to its
    intent context_tags (sorted, comma-joined); neither -> "unknown".

The JSON face is the primary artifact (agent and human read the same data);
--html OUT is its human rendering: a self-contained single file whose charts
come from the VENDORED Apache-2.0 ECharts build (templates/vendor/, checked
in once and INLINED at render time — never a CDN reference) through a Jinja2
template (templates/winrate_curve.html.j2). No build step, no server;
double-click to open, works fully offline. The chart JS consumes the SAME
inlined face JSON the agent reads.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from kunglao_log import iter_jsonl  # #863 Family K single source
from roi_settlement import ROI_NEGATIVE, ROI_POSITIVE, read_settlements

SCHEMA = "winrate-curve/1"
DEFAULT_WINDOW = 5
CASE_BANK_REL = "runs/case-bank.jsonl"
ORACLE_STATUS_REL = "runs/oracle-status.json"
UNKNOWN_FAMILY = "unknown"


# ------------------------------------------------------------- aggregation

def claim_pq_map(ws) -> dict:
    """claim-register.yaml -> {claim_id: answers_question} (tolerant)."""
    try:
        data = yaml.safe_load(
            (Path(ws) / "claim-register.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, str] = {}
    if not isinstance(data, dict):  # valid YAML, non-mapping top level
        return out
    for c in data.get("claims") or []:
        if isinstance(c, dict) and c.get("id") and c.get("answers_question"):
            out[str(c["id"])] = str(c["answers_question"])
    return out


def family_of(row: dict, claim_pqs: dict) -> str:
    """PQ family of one settlement row (see module docstring)."""
    aq = claim_pqs.get(str(row.get("claim_id") or ""))
    if aq:
        return aq
    tags = ((row.get("intent") or {}).get("context_tags")) or []
    tags = [str(t) for t in tags if str(t).strip()]
    if tags:
        return ",".join(sorted(tags))
    return UNKNOWN_FAMILY


def _scored(rows: list[dict]) -> list[dict]:
    """Settlement rows -> scored observations (POSITIVE/NEGATIVE only)."""
    return [{"roi_class": str(r["roi_class"]), "row": r} for r in rows
            if r.get("roi_class") in (ROI_POSITIVE, ROI_NEGATIVE)]


def scored_stream(ws) -> list[dict]:
    """Settlement stream -> scored observations (POSITIVE/NEGATIVE only)."""
    return _scored(read_settlements(Path(ws)))


def _count(value) -> int:
    """Tolerant count coercion (roi_settlement._num convention): garbage
    counts read as 0 — a typed-garbage face never crashes the read."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _rate(pos: int, neg: int):
    """POSITIVE share of scored observations; None when nothing scored."""
    return round(pos / (pos + neg), 4) if (pos + neg) else None


def _cumulative(stream: list[dict]) -> list[dict]:
    """Running rate after each scored settlement (index is 1-based)."""
    pts, pos, neg = [], 0, 0
    for i, obs in enumerate(stream, start=1):
        if obs["roi_class"] == ROI_POSITIVE:
            pos += 1
        else:
            neg += 1
        pts.append({"index": i, "positive": pos, "negative": neg,
                    "rate": _rate(pos, neg)})
    return pts


def _windowed(stream: list[dict], window: int) -> list[dict]:
    """Per-window rate over consecutive chunks; [start, end) are 0-based
    scored-stream indices and the last window may be partial (its own
    counts stand — a short window is still an honest observation)."""
    pts = []
    for wi, start in enumerate(range(0, len(stream), window)):
        chunk = stream[start:start + window]
        pos = sum(1 for o in chunk if o["roi_class"] == ROI_POSITIVE)
        neg = len(chunk) - pos
        pts.append({"index": wi, "start": start, "end": start + len(chunk),
                    "positive": pos, "negative": neg,
                    "rate": _rate(pos, neg)})
    return pts


def case_bank_summary(ws) -> dict | None:
    """runs/case-bank.jsonl -> counts-only summary (tolerant; None absent).

    Counts never rates: the bank mirrors the settlements (append_once at
    settle time), so folding it into the curve would double-count."""
    p = Path(ws) / CASE_BANK_REL
    if not p.exists():
        return None
    counts: dict[str, int] = {}
    for row in iter_jsonl(
            p.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not isinstance(row, dict):
            continue
        cls = str(row.get("roi_class") or "")
        counts[cls] = counts.get(cls, 0) + 1
    return {"n_entries": sum(counts.values()), "by_roi_class": counts}


def oracle_summary(ws) -> dict | None:
    """runs/oracle-status.json -> per-case-type counts (tolerant; None
    when absent or unreadable). `cases` narrows to the status face."""
    p = Path(ws) / ORACLE_STATUS_REL
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    counts = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    cases = doc.get("cases") if isinstance(doc.get("cases"), dict) else {}
    return {"schema": str(doc.get("schema") or ""),
            "counts": {"green": _count(counts.get("green")),
                       "red": _count(counts.get("red")),
                       "pending": _count(counts.get("pending"))},
            "cases": {str(cid): str(row.get("status") or "")
                      for cid, row in cases.items() if isinstance(row, dict)}}


def face(ws, window: int = DEFAULT_WINDOW) -> dict:
    """Settlement stream (+ side faces) -> the win-rate face.

    Empty stream -> empty face, no error: n_settlements 0, empty series,
    rate None. Window sizes below 1 clamp to 1 (a window of zero is
    meaningless, not an error). One settlement-stream read per face:
    n_rows_read and the series come from the same snapshot."""
    ws = Path(ws)
    window = max(int(window), 1)
    rows = read_settlements(ws)  # ONE read: series and n_rows_read share a
    stream = _scored(rows)       # snapshot (a concurrent settle cannot skew)

    claim_pqs = claim_pq_map(ws)
    pos = sum(1 for o in stream if o["roi_class"] == ROI_POSITIVE)
    neg = len(stream) - pos
    by_family: dict[str, list[dict]] = {}
    for obs in stream:
        by_family.setdefault(family_of(obs["row"], claim_pqs),
                             []).append(obs)
    families = {}
    for fam, obs in by_family.items():
        fp = sum(1 for o in obs if o["roi_class"] == ROI_POSITIVE)
        fn = len(obs) - fp
        families[fam] = {"positive": fp, "negative": fn,
                         "rate": _rate(fp, fn),
                         "cumulative": _cumulative(obs)}
    return {
        "schema": SCHEMA,
        "window": window,
        "n_settlements": len(stream),
        "n_rows_read": len(rows),
        "overall": {"positive": pos, "negative": neg,
                    "rate": _rate(pos, neg)},
        "windowed": _windowed(stream, window),
        "cumulative": _cumulative(stream),
        "by_family": dict(sorted(families.items())),
        "case_bank": case_bank_summary(ws),
        "oracle": oracle_summary(ws),
    }


def summarize(data: dict) -> str:
    """Text summary (cockpit text face)."""
    data = data or {}
    n = data.get("n_settlements") or 0
    if not n:
        return ("winrate-curve: no scored settlements (POSITIVE/NEGATIVE) "
                "— empty face")
    overall = data.get("overall") or {}
    lines = [f"winrate-curve: n={n} win_rate={overall.get('rate')} "
             f"(P={overall.get('positive')} N={overall.get('negative')}, "
             f"window={data.get('window')})"]
    for w in data.get("windowed") or []:
        lines.append(f"  window {w['index']} [{w['start']}:{w['end']}) "
                     f"rate={w['rate']} (P={w['positive']} N={w['negative']})")
    for fam, d in sorted((data.get("by_family") or {}).items()):
        lines.append(f"  family {fam}: n={d['positive'] + d['negative']} "
                     f"win_rate={d['rate']}")
    oracle = data.get("oracle")
    if oracle:
        c = oracle.get("counts") or {}
        lines.append(f"  oracle: {c.get('green')} green / {c.get('red')} red"
                     f" / {c.get('pending')} pending")
    return "\n".join(lines)


# --------------------------------------------------------------- html face
# Rendering contract (owner revision on #156): Jinja2 template + the
# vendored Apache-2.0 ECharts build inlined into the output — real plotted
# charts with zero CDN, zero build step, zero server; double-click opens
# the file offline. Vendored build provenance (checked in ONCE, so the
# generated HTML never reaches for the network either): npm registry
# tarball https://registry.npmjs.org/echarts/-/echarts-5.6.0.tgz
# (dist/echarts.min.js, sha256 bf4a223524e40b77c304bec67e1222cf551f14880
# cf42c69dc046558e11c07b1).

_TEMPLATE_REL = ("templates", "winrate_curve.html.j2")
_ECHARTS_VENDOR_REL = ("templates", "vendor", "echarts-5.6.0.min.js")


def _asset(rel) -> Path:
    """Rendering asset next to the script: a repo checkout
    (<root>/templates/...) and a deployed workspace (<ws>/.claude/scripts/
    ../templates/...) resolve through the same two-up formula."""
    return Path(__file__).resolve().parent.parent.joinpath(*rel)


def render_html(data: dict) -> str:
    """Face dict -> self-contained single-file HTML (the human rendering).

    The chart JS consumes the SAME inlined face JSON the agent reads —
    the human rendering cannot drift from the primary artifact. Guarded
    jinja2 import: the JSON face never needs it (--json works without)."""
    try:
        from jinja2 import Template
    except ImportError as exc:  # declared in pyproject; degrade loudly
        raise RuntimeError(
            "winrate-curve: --html needs the jinja2 dependency (declared "
            "in pyproject; `uv sync` installs it) — the --json face does "
            "not") from exc
    template_path = _asset(_TEMPLATE_REL)
    echarts_path = _asset(_ECHARTS_VENDOR_REL)
    missing = [p for p in (template_path, echarts_path) if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            "winrate-curve: --html rendering assets missing (the vendored "
            "ECharts build is required — never a CDN reference): "
            + ", ".join(str(p) for p in missing))
    data = data or {}
    rate = (data.get("overall") or {}).get("rate")
    overall_pct = "n/a" if rate is None else f"{rate * 100:.1f}%"
    # HTML-safe JSON embed: < > & become \u003c / \u003e / \u0026 — valid JSON
    # escapes that decode to the SAME characters, so the block can never
    # close the <script> element early (or smuggle markup) while agents
    # read back byte-identical face data.
    data_json = json.dumps(data, ensure_ascii=False, indent=2,
                           sort_keys=True)
    data_json = (data_json.replace("<", "\\u003c").replace(">", "\\u003e")
                 .replace("&", "\\u0026"))
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.render(
        schema=data.get("schema", ""),
        n=data.get("n_settlements", 0),
        window=data.get("window", 0),
        overall_pct=overall_pct,
        has_data=bool(data.get("n_settlements")),
        face_json=data_json,
        echarts_js=echarts_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    """CLI: python winrate_curve.py <ws> [--json] [--html OUT] [--window N]"""
    ap = argparse.ArgumentParser(
        prog="winrate_curve.py",
        description="#156 win-rate curve — rolling success-rate over the "
                    "settlement stream (offline aggregator)")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable face on stdout")
    ap.add_argument("--html", metavar="OUT", default=None,
                    help="write the single-file chart rendering to OUT")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                    help=f"rolling window size (default {DEFAULT_WINDOW})")
    args = ap.parse_args(argv)
    data = face(args.workspace, window=args.window)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(summarize(data))
    if args.html:
        try:
            page = render_html(data)
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"winrate-curve: REFUSED — {exc}", file=sys.stderr)
            return 2
        out = Path(args.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        print(f"winrate-curve: chart face written -> {out}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
