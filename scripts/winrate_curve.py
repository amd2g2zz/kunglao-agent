#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""winrate_curve.py — the #420 Phase-2 adapter (CLI + HTML rendering).

The read-side aggregation faces (``face``, ``_cumulative``, ``_windowed``,
``_rate``, the family/summary readers) live in ``rlvr.winrate`` (issue
#420 Phase 2, per scripts/rlvr/README.md — the winrate face map). This
module keeps the CLI (``main``) and the single-file chart rendering
(``render_html`` + the inlined-ECharts .j2 template) — template rendering
is not package surface — and re-exports the read faces so every existing
bare-name importer keeps working unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rlvr.winrate import (  # noqa: F401 — the compat surface
    CASE_BANK_REL,
    DEFAULT_WINDOW,
    ORACLE_STATUS_REL,
    ROI_NEGATIVE,
    ROI_POSITIVE,
    SCHEMA,
    UNKNOWN_FAMILY,
    _count,
    _cumulative,
    _rate,
    _scored,
    _windowed,
    _wins,
    case_bank_summary,
    claim_pq_map,
    face,
    family_of,
    oracle_summary,
    read_settlements,
    scored_stream,
    summarize,
)

__all__ = [
    "SCHEMA", "DEFAULT_WINDOW", "CASE_BANK_REL", "ORACLE_STATUS_REL",
    "UNKNOWN_FAMILY", "ROI_POSITIVE", "ROI_NEGATIVE",
    "claim_pq_map", "family_of", "scored_stream", "face", "summarize",
    "case_bank_summary", "oracle_summary", "read_settlements",
    "_scored", "_count", "_rate", "_wins", "_cumulative", "_windowed",
    "render_html", "main",
]


# --------------------------------------------------------------- html face
# Rendering contract (owner revision on #156, chart file removed by #162):
# Jinja2 template carrying the Apache-2.0 ECharts library INLINED under a
# {% raw %}...{% endraw %} block — real plotted charts with zero CDN, zero
# build step, zero server, no separate library file; double-click opens
# the file offline. Library provenance lives in the template's leading
# comment (npm registry tarball, dist/echarts.min.js, sha256 pinned there).

_TEMPLATE_REL = ("templates", "winrate_curve.html.j2")


def _asset(rel) -> Path:
    """Rendering asset next to the script: a repo checkout
    (<root>/templates/...) and a deployed workspace (<ws>/.claude/scripts/
    ../templates/...) resolve through the same two-up formula."""
    return Path(__file__).resolve().parent.parent.joinpath(*rel)


def render_html(data: dict) -> str:
    """Face dict -> self-contained single-file HTML (the human rendering).

    The chart library rides inside the .j2 (in-file since #162) and
    consumes the SAME inlined face JSON the agent reads — the human
    rendering cannot drift from the primary artifact. Guarded jinja2
    import: the JSON face never needs it (--json works without)."""
    try:
        from jinja2 import Template
    except ImportError as exc:  # declared in pyproject; degrade loudly
        raise RuntimeError(
            "winrate-curve: --html needs the jinja2 dependency (declared "
            "in pyproject; `uv sync` installs it) — the --json face does "
            "not") from exc
    template_path = _asset(_TEMPLATE_REL)
    if not template_path.is_file():
        raise FileNotFoundError(
            "winrate-curve: --html rendering assets missing "
            f"(the .j2 carries the chart library, #162): {template_path}")
    data = data or {}
    rate = (data.get("overall") or {}).get("rate")
    overall_pct = "n/a" if rate is None else f"{rate * 100:.1f}%"
    # HTML-safe JSON embed: < > & become < / > / & — valid JSON
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
        face_json=data_json)


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
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
