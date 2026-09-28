# -*- coding: utf-8 -*-
"""e2e.cli — the runner's command-line face.

  uv run --project . python scripts/e2e/run.py --unit py-derive-v1 \
      [--budget-seconds 14400] [--ws-root /tmp/e2e] [--repo <path>] \
      [--dry-llm | --auto-llm] [--resume <run-id>] [--json]

Orchestrator-act subcommands (the open-loop shape; require --resume):

  --emit-dispatch <claim> <prompt-file>   mint a dispatch-request file
  --record-fact <fact-file>               ingest an act's fact into the WS
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from e2e import checkpoints, evidence, model

MODE_FLAGS = {"--dry-llm": "dry", "--auto-llm": "auto"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/e2e/run.py",
        description="Gold-standard E2E acceptance harness: init -> analysis "
                    "-> open loop -> oracle, per the dogfood runbook.")
    parser.add_argument("--unit", default="py-derive-v1",
                        help="eval unit id under eval/v1/tasks/ (default: "
                             "%(default)s)")
    parser.add_argument("--repo", default=None,
                        help="E2E repo checkout (default: the checkout "
                             "running this script)")
    parser.add_argument("--budget-seconds", type=int,
                        default=model.DEFAULT_BUDGET_SECONDS,
                        help="wall budget for the run (default: 4h)")
    parser.add_argument("--ws-root", default="/tmp/e2e",
                        help="workspace root (NEVER inside the repo)")
    parser.add_argument("--lane", default="algorithm")
    parser.add_argument("--type", dest="type_", default="linux")
    parser.add_argument("--dry-llm", action="store_true",
                        help="scripted LLM acts (pipeline testing; no "
                             "network, no LLM)")
    parser.add_argument("--auto-llm", action="store_true",
                        help="headless claude execution per dispatch act "
                             "(real LLM, fully automatic)")
    parser.add_argument("--resume", default=None, metavar="RUN_ID",
                        help="resume a run under runs/e2e/ (PASS "
                             "checkpoints skipped via their evidence)")
    parser.add_argument("--json", action="store_true",
                        help="print the final report JSON to stdout")
    parser.add_argument("--tick-wait-seconds", type=int,
                        default=model.TICK_WAIT_SECONDS_DEFAULT,
                        help="wait between ticks (default: the honest 5m; "
                             "the scripts honor no override)")
    parser.add_argument("--max-ticks", type=int, default=60,
                        help="C6 loop safety cap (BLOCKED beyond this)")
    parser.add_argument("--emit-dispatch", nargs=2,
                        metavar=("CLAIM", "PROMPT_FILE"),
                        help="orchestrator act: mint a dispatch-request "
                             "file (requires --resume)")
    parser.add_argument("--record-fact", nargs=1, metavar="FACT_FILE",
                        help="orchestrator act: ingest a fact file into "
                             "the run's workspace (requires --resume)")
    return parser


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _emit_dispatch(args, repo: Path) -> int:
    run_dir = evidence.resolve_run_dir(repo, args.resume)
    state = evidence.load_run_state(run_dir)
    if state is None:
        print(f"ERROR: no run-state in {run_dir}", file=sys.stderr)
        return 2
    claim, prompt_file = args.emit_dispatch
    request = model.DispatchRequest(
        claim=claim, workspace=state.ws, prompt_file=prompt_file,
        run_id=state.run_id)
    record = checkpoints.llm_faces.OrchestratorFace(run_dir)
    act = record.dispatch_act(request)
    print(json.dumps(act.to_dict(), indent=2, sort_keys=True))
    return model.EXIT_OK


def _record_fact(args, repo: Path) -> int:
    run_dir = evidence.resolve_run_dir(repo, args.resume)
    state = evidence.load_run_state(run_dir)
    if state is None:
        print(f"ERROR: no run-state in {run_dir}", file=sys.stderr)
        return 2
    fact_src = Path(args.record_fact[0])
    if not fact_src.is_file():
        print(f"ERROR: fact file not found: {fact_src}", file=sys.stderr)
        return 2
    facts_dir = Path(state.ws) / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    dst = facts_dir / fact_src.name
    shutil.copy2(fact_src, dst)
    ingest = run_dir / "ingested-facts.jsonl"
    with ingest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"fact": str(dst), "ts": model.utc_now()},
                            sort_keys=True) + "\n")
    print(json.dumps({"recorded": str(dst)}, sort_keys=True))
    return model.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve() if args.repo else _repo_root()
    if args.dry_llm and args.auto_llm:
        print("ERROR: --dry-llm and --auto-llm are mutually exclusive",
              file=sys.stderr)
        return 2
    mode = "dry" if args.dry_llm else ("auto" if args.auto_llm
                                       else "orchestrator")
    if args.emit_dispatch or args.record_fact:
        if not args.resume:
            print("ERROR: --emit-dispatch/--record-fact require --resume",
                  file=sys.stderr)
            return 2
        if args.emit_dispatch:
            return _emit_dispatch(args, repo)
        return _record_fact(args, repo)

    run_id = args.resume
    if run_id and not (evidence.evidence_root(repo) / run_id).is_dir():
        print(f"ERROR: no such run to resume: {run_id}", file=sys.stderr)
        return 2
    pipeline_args = model.PipelineArgs(
        unit=args.unit, repo=repo, ws_root=Path(args.ws_root),
        budget_seconds=args.budget_seconds, llm_mode=mode,
        tick_wait_seconds=args.tick_wait_seconds, run_id=run_id,
        lane=args.lane, type_=args.type_, max_ticks=args.max_ticks)
    if not args.json:
        return checkpoints.run_pipeline(pipeline_args)
    sink: list[dict] = []
    rc = checkpoints.run_pipeline(pipeline_args, report_sink=sink)
    if sink:
        print(json.dumps(sink[0], indent=2, sort_keys=True,
                         ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
