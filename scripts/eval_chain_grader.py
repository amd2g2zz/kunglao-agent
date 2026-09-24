#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_chain_grader.py — the dense per-layer grader (#370).

Scores ONE chain unit against ONE analysis workspace: the workspace's
layer artifacts are checked against the unit's ground-truth checkpoint
ops (mechanical, byte/execution level — same oracle discipline as the
final answer face) and the score is LAYERS-COMPLETED (0..N), not a
binary pass — the experiment signal upgrades from binary to dense for
these units.

Checkpoint ops (each mechanically verified):
  digest   sha256(artifact) == recorded        (byte-exact peels:
           payload unpack, decrypted config)
  exec     the artifact runs under its toolchain and reproduces the
           shared probe rows byte-exact (restored core; junk-strip
           survival; rotation lanes included in the rows)
  markers  the artifact text cites the required evidence values
           (true-path branch condition, gate trip predicate)
  clean    the artifact text carries none of the forbidden junk
           markers (the stripped reference form)

A layer is completed iff ALL its ops pass; dense score = completed/N.
Skip face: an exec op whose toolchain is absent degrades to SKIP —
the run verdict is SKIP when there are no hard failures (never a
false FAIL), and the score counts only mechanically verified layers.

Output: METRIC layers_completed / layers_total / dense_score, the
kunglao-eval-chain-scores/1 evidence JSON, VERDICT PASS|FAIL|SKIP|REFUSED.
Exit: 0 PASS · 1 FAIL · 2 refusal · 3 SKIP.

stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import eval_chain as ch
import eval_dataset as ds

SCHEMA_SCORES = ch.SCHEMA_SCORES

RC_PASS, RC_FAIL, RC_REFUSED, RC_SKIP = 0, 1, 2, 3

_PY_HARNESS = '''"""kunglao-eval chain probe harness (py face)."""
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("cand", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for row in json.load(open(sys.argv[2], encoding="utf-8")):
    out = mod.derive(row["payload"], row.get("lane", 0))
    print(json.dumps({"i": row["i"], "out": out}))
'''

_JS_HARNESS = '''// kunglao-eval chain probe harness (js face).
const fs = require('fs');
const m = require(require('path').resolve(process.argv[2]));
const rows = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
for (const r of rows)
  console.log(JSON.stringify({ i: r.i,
    out: m.derive({ payload: r.payload, lane: r.lane }) }));
'''


class Refusal(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class SkipOp(Exception):
    pass


def _toolchain(lang: str) -> str:
    if lang == "python3":
        return sys.executable
    import shutil
    path = shutil.which(lang)
    if path is None:
        raise SkipOp(f"{lang} toolchain not available on this machine")
    return path


def load_unit(task_ref: str) -> tuple[Path, dict, dict]:
    """(task_dir, ground_truth, chain block); wrong shapes are loud."""
    try:
        tdir = ds.resolve_task_dir(task_ref, tier=ch.TIER)
    except FileNotFoundError as exc:
        raise Refusal(str(exc)) from exc
    gt_path = tdir / "ground_truth.json"
    if not gt_path.is_file():
        raise Refusal(f"ground truth missing: {gt_path}")
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    chain = gt.get("chain")
    if not isinstance(chain, dict) or not isinstance(chain.get("layers"),
                                                     list):
        raise Refusal(f"{tdir.name}: no chain layer block in ground truth")
    return tdir, gt, chain


def _shared_probes(chain: dict) -> tuple[list[dict], dict[int, str]]:
    """The shared exec rows: probes + checker-side expected outputs."""
    probes = chain.get("probes")
    if not isinstance(probes, list) or not probes:
        raise Refusal("chain block carries no probe rows")
    expected = {p["i"]: p["out"] for p in probes if "out" in p}
    return probes, expected


def _op_digest(ws: Path, op: dict) -> dict:
    path = ws / op["path"]
    if not path.is_file():
        return {"pass": False, "detail": f"missing artifact: {op['path']}"}
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    ok = got == op["sha256"]
    return {"pass": ok,
            "detail": ("digest match" if ok else
                       f"digest mismatch (got {got[:16]}..., want "
                       f"{op['sha256'][:16]}...)")}


def _op_markers(ws: Path, op: dict) -> dict:
    path = ws / op["path"]
    if not path.is_file():
        return {"pass": False, "detail": f"missing artifact: {op['path']}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [m for m in op["markers"] if m not in text]
    ok = not missing
    return {"pass": ok,
            "detail": ("all evidence markers cited" if ok else
                       f"evidence markers missing: {missing}")}


def _op_clean(ws: Path, op: dict) -> dict:
    path = ws / op["path"]
    if not path.is_file():
        return {"pass": False, "detail": f"missing artifact: {op['path']}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    present = [m for m in op["forbidden"] if m in text]
    ok = not present
    return {"pass": ok,
            "detail": ("junk-free" if ok else
                       f"junk markers still present: {present}")}


def _op_probe_run(ws: Path, op: dict, probes: list[dict],
                  expected: dict[int, str]) -> dict:
    """The execution face: the artifact must reproduce the shared probe
    rows byte-exact under its own toolchain."""
    path = ws / op["path"]
    if not path.is_file():
        return {"pass": False, "detail": f"missing artifact: {op['path']}"}
    exe = _toolchain(op["lang"])
    with tempfile.TemporaryDirectory(prefix="chain-op-") as tmp:
        tmp_path = Path(tmp)
        rows_file = tmp_path / "rows.json"
        rows_file.write_text(json.dumps([
            {"i": p["i"], "payload": p["payload"], "lane": p["lane"]}
            for p in probes]), encoding="utf-8")
        if op["lang"] == "node":
            harness = tmp_path / "harness.js"
            harness.write_text(_JS_HARNESS, encoding="utf-8")
            cmd = [exe, str(harness), str(path.resolve()), str(rows_file)]
            stdin_text = None
        elif op["lang"] == "python3":
            harness = tmp_path / "harness.py"
            harness.write_text(_PY_HARNESS, encoding="utf-8")
            cmd = [exe, str(harness), str(path.resolve()), str(rows_file)]
            stdin_text = None
        else:  # go: stdin protocol face (rows on stdin, rows on stdout)
            cmd = [exe, "run", str(path.resolve())]
            stdin_text = "".join(
                json.dumps({"i": p["i"], "payload": p["payload"],
                            "lane": p["lane"]}) + "\n" for p in probes)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=300,
                                  input=stdin_text if stdin_text else None)
        except subprocess.TimeoutExpired:
            return {"pass": False, "detail": "probe run exceeded 300s"}
        if proc.returncode != 0:
            return {"pass": False,
                    "detail": f"artifact run failed: {proc.stderr[-200:]}"}
        got: dict[int, str] = {}
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row.get("i"), int):
                got[row["i"]] = row.get("out")
        matched = sum(1 for p in probes
                      if got.get(p["i"]) == expected.get(p["i"]))
        ok = matched == len(probes)
        return {"pass": ok,
                "detail": f"probe rows {matched}/{len(probes)} reproduce"}


_OPS = {"digest": _op_digest, "markers": _op_markers, "clean": _op_clean}


def grade(task_ref: str, workspace: Path) -> tuple[int, dict]:
    """Grade one unit against one workspace; returns (exit_code, scores)."""
    _tdir, gt, chain = load_unit(task_ref)
    ws = Path(workspace)
    if not ws.is_dir():
        raise Refusal(f"workspace dir not found: {ws}")
    probes, expected = _shared_probes(chain)

    layers_out = []
    failures = 0
    skips = 0
    completed = 0
    for layer in chain["layers"]:
        ops_out = []
        layer_pass = True
        for op in layer["ops"]:
            if op["op"] == "exec":
                try:
                    res = _op_probe_run(ws, op, probes, expected)
                except SkipOp as exc:
                    skips += 1
                    res = {"pass": False, "skip": True, "detail": str(exc)}
            else:
                res = _OPS[op["op"]](ws, op)
            if not res["pass"]:
                layer_pass = False
                if not res.get("skip"):
                    failures += 1
            ops_out.append({"op": op["op"], "path": op["path"], **res})
        if layer_pass:
            completed += 1
        layers_out.append({"id": layer["id"],
                           "mechanisms": layer.get("mechanisms", []),
                           "completed": layer_pass,
                           "ops": ops_out})
    total = len(chain["layers"])

    if failures == 0 and skips:
        verdict, rc = "SKIP", RC_SKIP
    elif failures == 0:
        verdict, rc = "PASS", RC_PASS
    else:
        verdict, rc = "FAIL", RC_FAIL
    scores = {
        "schema": SCHEMA_SCORES,
        "task_id": gt["task_id"],
        "workspace": str(ws),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "layers_completed": completed,
        "layers_total": total,
        "dense_score": round(completed / total, 4) if total else 0.0,
        "hard_failures": failures,
        "skipped_ops": skips,
        "verdict": verdict,
        "layers": layers_out,
    }
    return rc, scores


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_chain_grader.py",
        description="Dense per-layer grader for #370 chain units: scores "
                    "layers-completed (0..N) from the analysis "
                    "workspace's layer artifacts.")
    ap.add_argument("--task", required=True,
                    help="chain task id or task-unit directory")
    ap.add_argument("--workspace", required=True,
                    help="analysis workspace dir (layer_out/ artifacts)")
    ap.add_argument("--out", default=None,
                    help="scores out-dir (default: runs/chain-grades/)")
    args = ap.parse_args(argv)
    try:
        rc, scores = grade(args.task, Path(args.workspace))
    except Refusal as exc:
        print(f"FAILURE code=BAD_TASK detail={exc.detail}")
        print("VERDICT REFUSED")
        return RC_REFUSED
    outdir = (Path(args.out) if args.out
              else ds.EVAL_ROOT.parent / "runs" / "chain-grades")
    outdir.mkdir(parents=True, exist_ok=True)
    ev_path = outdir / (
        f"scores-{scores['task_id']}-{time.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{os.getpid() % 100000}.json")
    ev_path.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
    print(f"METRIC layers_completed={scores['layers_completed']}")
    print(f"METRIC layers_total={scores['layers_total']}")
    print(f"METRIC dense_score={scores['dense_score']}")
    for layer in scores["layers"]:
        if not layer["completed"]:
            for op in layer["ops"]:
                if not op["pass"]:
                    print(f"FAILURE code=LAYER_INCOMPLETE "
                          f"detail=layer {layer['id']}/{op['op']} "
                          f"{op.get('path', '')}: {op['detail']}")
    print(f"EVIDENCE {ev_path}")
    print(f"VERDICT {scores['verdict']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
