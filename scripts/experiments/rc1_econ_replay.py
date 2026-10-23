#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rc1_econ_replay.py — the rc1 economics-audit queries as a regression
runner (issue #801 acceptance 6).

The rc1 post-mortem computed the machine:analysis ratio over the session
transcripts with DuckDB (the dispatch:tick ≈1.2:1 verdict; the 750k
tok/h wake burn). Those queries lived only in the audit session — this
script commits them: hourly machine-overhead input tokens vs
analysis-output tokens over ONE transcript JSONL, alarm when ratio > 1.

Usage:
    python scripts/experiments/rc1_econ_replay.py <transcript.jsonl> [--ws <workspace>]

Row arithmetic (identical live face: hooks/cost_input_capture.py):
  machine  = rows with isSidechain falsy  -> input_tokens + cache_read_input_tokens
  analysis = rows with isSidechain truthy -> output_tokens
  ratio    = machine / max(analysis, 1)   (per hour; alarm > 1)

Executor: DuckDB when importable (the canonical SQL is embedded below and
executed verbatim); otherwise a documented stdlib fold with the SAME
output schema (the queries stay replayable on any CI box). Exit 0 always
on a readable transcript; rc 2 on usage error.

Output (stdout, JSON):
  {"hours": [{"hour", "machine_input_tokens", "analysis_output_tokens",
              "ratio", "alarm"}...],
   "alarm_hours": <int>, "total_ratio": <float>}
With --ws, the same object also lands in <ws>/runs/.rc1-econ-replay.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ALARM_RATIO = 1.0

DETECTOR_EVAL_WORD = "detector_eval"
DETECTOR_FIRED_WORD = "detector_fired"

try:  # the canonical warn — ONE implementation (process-wide dedupe)
    from kunglao_log import warn
except ImportError:  # standalone-CI lifeline: stderr fallback, ONE trace
    def warn(op: str, reason: str) -> None:
        print(f"[rc1_econ_replay] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)

# The canonical rc1 query (DuckDB over one transcript JSONL). read_json
# auto-extracts the nested usage struct; the CASE split is the row
# arithmetic documented above.
CANONICAL_SQL = """
SELECT
    strftime(CAST(timestamp AS TIMESTAMP), '%Y-%m-%dT%H') AS hour,
    SUM(CASE WHEN NOT COALESCE(isSidechain, FALSE)
             THEN COALESCE(usage.input_tokens, 0)
                + COALESCE(usage.cache_read_input_tokens, 0)
             ELSE 0 END) AS machine_input_tokens,
    SUM(CASE WHEN COALESCE(isSidechain, FALSE)
             THEN COALESCE(usage.output_tokens, 0)
             ELSE 0 END) AS analysis_output_tokens
FROM read_json(?, format='newline_delimited')
WHERE usage IS NOT NULL
GROUP BY hour ORDER BY hour
"""


def _fold(path: Path) -> dict:
    """The stdlib twin of CANONICAL_SQL — same grouping, same schema."""
    machine_by_hour: dict[str, int] = defaultdict(int)
    analysis_by_hour: dict[str, int] = defaultdict(int)
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                usage = (row.get("message") or {}).get("usage") or {}
            except ValueError:
                continue
            if not isinstance(usage, dict):
                continue
            ts = str(row.get("timestamp") or "")
            hour = ts[:13] if len(ts) >= 13 else "unknown"
            if row.get("isSidechain"):
                analysis_by_hour[hour] += int(usage.get("output_tokens") or 0)
            else:
                machine_by_hour[hour] += (
                    int(usage.get("input_tokens") or 0)
                    + int(usage.get("cache_read_input_tokens") or 0))
    return machine_by_hour, analysis_by_hour


def replay(transcript: Path) -> dict:
    """Run the audit over one transcript; DuckDB-first, stdlib fallback."""
    hours: list[dict] = []
    try:
        import duckdb  # type: ignore
        con = duckdb.connect()
        rows = con.execute(CANONICAL_SQL, [str(transcript)]).fetchall()
        for hour, machine, analysis in rows:
            hours.append({"hour": hour,
                          "machine_input_tokens": int(machine),
                          "analysis_output_tokens": int(analysis)})
    except ImportError:
        # #275 batch-3: the fallback is fail-open but never silent — ONE
        # rate-limited canonical-warn trace names the degraded executor.
        warn("rc1_econ_replay",
             "duckdb unavailable — documented stdlib fold (same schema)")
        machine_by_hour, analysis_by_hour = _fold(transcript)
        for hour in sorted(set(machine_by_hour) | set(analysis_by_hour)):
            hours.append({"hour": hour,
                          "machine_input_tokens": machine_by_hour.get(hour, 0),
                          "analysis_output_tokens":
                              analysis_by_hour.get(hour, 0)})
    for h in hours:
        h["ratio"] = (h["machine_input_tokens"]
                      / max(h["analysis_output_tokens"], 1))
        h["alarm"] = h["ratio"] > ALARM_RATIO
    total_m = sum(h["machine_input_tokens"] for h in hours)
    total_a = sum(h["analysis_output_tokens"] for h in hours)
    return {"hours": hours,
            "alarm_hours": sum(1 for h in hours if h["alarm"]),
            "total_ratio": total_m / max(total_a, 1)}


def detector_accounting(ledger_paths: list[Path] | None) -> dict | None:
    """#801 R2c: the eval/fire consumption accounting (the 62:1 / 142:1
    production shapes) over the given workspace ledger file(s). Per
    detector (detail JSON `detector` field): evals vs fires; unactuated =
    sum(max(0, evals - fires)) — detection without action is billed
    consumption, invisible in the transcript-only view. None when no
    ledger was supplied."""
    if not ledger_paths:
        return None
    evals: dict[str, int] = {}
    fires: dict[str, int] = {}
    for path in ledger_paths:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                action = row.get("action")
                if action not in (DETECTOR_EVAL_WORD, DETECTOR_FIRED_WORD):
                    continue
                try:
                    det = str((json.loads(row.get("detail") or "{}")
                               ).get("detector") or "unknown")
                except ValueError as exc:
                    # #275: a corrupt detail row is skipped WITH a trace
                    # (rate-limited canonical warn), not silently
                    # default-attributed — "unknown" would pollute the
                    # per-detector accounting this face exists for.
                    warn("rc1_econ_replay",
                         f"ledger row detail unparsable ({exc}); row "
                         f"skipped for detector attribution")
                    continue
                bucket = evals if action == DETECTOR_EVAL_WORD else fires
                bucket[det] = bucket.get(det, 0) + 1
    total_evals = sum(evals.values())
    total_fires = sum(fires.values())
    unactuated = sum(max(0, evals.get(d, 0) - fires.get(d, 0))
                     for d in set(evals) | set(fires))
    return {"detector_eval": total_evals,
            "detector_fired": total_fires,
            "unactuated": unactuated,
            "eval_fire_ratio": total_evals / max(total_fires, 1)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rc1_econ_replay.py",
        description="Replay the rc1 machine:analysis economics audit over "
                    "one transcript JSONL (#801).")
    parser.add_argument("transcript", help="transcript JSONL path")
    parser.add_argument("--ws", default=None,
                        help="optional workspace — also writes the result "
                             "to <ws>/runs/.rc1-econ-replay.json")
    parser.add_argument("--ledger", action="append", default=None,
                        help="workspace ledger JSONL (repeatable) — adds "
                             "the R2c detector consumption accounting "
                             "(eval vs fire vs unactuated) to the output")
    args = parser.parse_args(argv)
    tx = Path(args.transcript)
    if not tx.is_file():
        print(f"ERROR: transcript {tx} is not a file", file=sys.stderr)
        return 2
    result = replay(tx)
    acc = detector_accounting(
        [Path(p) for p in args.ledger] if args.ledger else None)
    if acc is not None:
        result["detector_accounting"] = acc
    print(json.dumps(result, ensure_ascii=False))
    if args.ws:
        out = Path(args.ws) / "runs" / ".rc1-econ-replay.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False),
                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from _boot import force_utf8  # entry UTF-8 boot (_boot)
        force_utf8()
    except ImportError as exc:  # stdlib face stays runnable without the
        # skill boot — but the degradation is traced, never silent (#275).
        warn("rc1_econ_replay",
             f"_boot unavailable ({exc}); stdlib face runs without the "
             f"entry UTF-8 boot")
        sys.stderr.flush()
    sys.exit(main())
