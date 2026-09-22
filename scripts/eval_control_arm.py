#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_control_arm.py — bare-LLM control arm + A/B run face (#236).

The capture-refusal incident class needs a CONTROL: what does a BARE LLM
score on the same mechanical oracles the framework arm is graded by? The
bare arm is a PROMPT-ONLY run per smoke task — goal_verbatim +
success_criterion + the task's input surface (the candidate contract and
the observable target source). No claim economy, no gates, no oracle
machinery: the prompt never sees ground truth, thresholds, or the
checker's existence.

Model-call face (T0 finding): the repo's LLM-call convention is the
`claude` CLI in print mode — scripts/bench_runner.py shells
``claude -p <prompt>`` (and scripts/external_kicker.py delivers prompts
to detached ``claude -p``). The live executor below uses exactly that
face; tests inject a stub executor (the executor is a SEAM, the bench
convention — "tests inject a stub instead", bench_runner.py L26).

Arms and surfaces:
  bare-llm    built here: prompt-only via the executor seam, or candidate
              artifacts from a kunglao-eval-candidates/1 manifest
              (externally produced outputs — the numbers lane works even
              without a reachable model face);
  framework   candidate artifacts supplied via a manifest (the full
              framework loop's outputs; the runner's self-check arm stays
              the oracle-liveness face and is deliberately NOT reused as
              the framework arm);
  guess-1ofk  the 1/k arithmetic floor (--baselines, from #299).

Five metrics per arm (the capture-refusal incident lens):
  answer_rate                  primary_question answer rate — a task is
                               answered when the arm produced a gradeable
                               candidate (verdict PASS/FAIL; SKIP/REFUSED
                               is NOT an answer);
  proven_with_evidence_rate    checker VERDICT PASS with archived evidence
                               (the evidence bar, per task);
  premature_closure_rate       claimed-converged tasks (metrics.converged
                               =1) whose checker later FAILs on re-run or
                               on the minted-probe subset;
  false_proven_rate            checker PASS on a candidate that fails the
                               minted-probe subset (#299's anti-digest-
                               table probes decide it);
  budget                       wall seconds (runner summary), per-task
                               ttc sum, tokens where the face provides
                               them (None where unknown — never invented).

Regrade machinery: minted_only_grade() re-runs the candidate through the
checker's own replay face with published pairs stripped — the minted
probe set alone grades it. A full checker re-run (fresh subprocess, the
runner's run_task face) decides the re-run leg of premature closure.

Usage:
  eval_control_arm.py --ab [--manifest M] [--framework-manifest FM]
                      [--live] [--tier smoke] [--tasks id,id]
                      [--baselines] [--out DIR]
  eval_control_arm.py --bare [--manifest M | --live] [...] [--out DIR]

  --ab     one command, both arms: per-arm kunglao-eval-results/1 docs
           plus a kunglao-eval-ab/1 comparison summary and a stdout
           table (#295 evidence-bar shape).
  --live   prompt-only runs through `claude -p` (default: manifest mode;
           without a manifest the arm lands structured SKIP rows).

Exit: 0 run completed (arm FAIL rows are measurements, not run
failures); 2 refusal (unknown task / bad manifest).

stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import eval_dataset as ds
import eval_targets as tg
import eval_checker as chk
import eval_smoke_runner as rnr

SCHEMA_CANDIDATES = "kunglao-eval-candidates/1"
SCHEMA_AB = "kunglao-eval-ab/1"
SCHEMA_BARE_RUN = "kunglao-eval-bare-run/1"

DEFAULT_TIMEOUT_S = 300.0

# candidate artifact suffix per FAMILY (mirrors the checker's
# _validate_candidate map — the authoritative family→suffix contract,
# #332 native families included; candidates are pure-python there)
CAND_SUFFIX = {"go-arx": ".go", "js-sign": ".js", "py-derive": ".py",
               "arm-native-kdf": ".py", "win-pe-kdf": ".py",
               "smc-x86": ".py", "mod-crypto-native": ".py",
               "web-pack-sign": ".js", "net-verify-license": ".js",
               "req-sign": ".js", "mod-crypto-js": ".js"}

# prompt cap for a rendered binary input surface (chars; truncation is
# recorded in the prompt text, never silent)
BINARY_RENDER_CAP = 600_000

RC_OK, RC_REFUSED = 0, 2

_ANSWER_VERDICTS = ("PASS", "FAIL")
_FALSIFIED_VERDICTS = ("FAIL", "REFUSED")


def answer_rate(answered: int, total: int) -> float:
    """primary_question answer rate: gradeable candidates / tier tasks.

    0.0 on an empty denominator — a rate over nothing is 0, never a
    ZeroDivisionError and never invented mass."""
    return answered / total if total else 0.0


def proven_with_evidence_rate(proven: int, total: int) -> float:
    return proven / total if total else 0.0


def premature_closure_rate(premature: int, claimed: int) -> float:
    """Denominator is the CLAIMED mass: of the closures the arm claimed,
    how many were later falsified."""
    return premature / claimed if claimed else 0.0


def false_proven_rate(false_n: int, proven: int) -> float:
    """Denominator is the checker-PASS mass: of the PROVEN verdicts, how
    many collapse under the minted-probe subset."""
    return false_n / proven if proven else 0.0


def is_false_proven(verdict: str, minted: tuple[int, int] | None) -> bool:
    """A checker PASS is FALSE-PROVEN when the candidate fails the
    minted-probe subset. An ungradeable candidate (minted=None: toolchain
    absent) can never be accused."""
    if verdict != "PASS" or minted is None:
        return False
    matched, total = minted
    return bool(total > 0 and matched < total)


def is_premature_closure(claimed_converged: bool, rerun_verdict: str | None,
                         minted: tuple[int, int] | None) -> bool:
    """A claimed-converged task is a PREMATURE CLOSURE when the checker
    later falsifies it — on a fresh full re-run (FAIL/REFUSED) or on the
    minted-probe subset. Never-claimed tasks cannot close prematurely."""
    if not claimed_converged:
        return False
    if rerun_verdict in _FALSIFIED_VERDICTS:
        return True
    if minted is not None:
        matched, total = minted
        if total > 0 and matched < total:
            return True
    return False


# ---------------------------------------------------------- bare prompt
def _cand_suffix(task: dict) -> str:
    """Candidate artifact suffix for the task's family — the literal
    mirror of the checker's _validate_candidate contract (kept in sync by
    the parity test in tests/test_eval_control_arm_236.py)."""
    return CAND_SUFFIX[task["family"]]


def render_binary_surface(path: Path) -> str:
    """Text face of a BINARY target for a prompt-only arm: ELF header +
    section headers + full disassembly + embedded strings — the standard
    static rendering an analyst's tooling produces (the checker's oracle
    face never executes native binaries either). Deterministic subprocess
    rendering; capped, with the truncation recorded in the text."""
    parts: list[str] = []
    for args in (["objdump", "-f", str(path)],
                 ["objdump", "-h", str(path)],
                 ["objdump", "-d", str(path)],
                 ["strings", "-n", "4", str(path)]):
        proc = subprocess.run(args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
        parts.append((proc.stdout or "").strip())
    text = "\n\n".join(p for p in parts if p)
    if len(text) > BINARY_RENDER_CAP:
        text = (text[:BINARY_RENDER_CAP]
                + f"\n[truncated at {BINARY_RENDER_CAP} chars]")
    return text


def build_bare_prompt(tdir: Path, task: dict) -> str:
    """The prompt-only bare-agent surface: anchors + candidate contract +
    the observable input surface (target source; binary targets render
    through objdump/strings). Structurally cannot leak ground truth: this
    function never receives it."""
    ws = task["workspace_scaffold"]
    entry_path = Path(tdir) / ws["entry"]
    try:
        target = entry_path.read_text(encoding="utf-8")
        surface_header = (f"INPUT SURFACE — the reference source "
                          f"({ws['entry']}):")
    except UnicodeDecodeError:
        target = render_binary_surface(entry_path)
        surface_header = (
            f"INPUT SURFACE — text rendering of the binary target "
            f"({ws['entry']}): file/section headers, full disassembly, "
            f"embedded strings:")
    anchors = task["anchors"]
    # the RESPONSE language follows the candidate artifact the checker
    # grades (CAND_SUFFIX), never the target's implementation language —
    # native units ship c/arm64 targets but grade pure-python candidates
    response_lang = {".py": "Python", ".js": "JavaScript",
                     ".go": "Go"}[_cand_suffix(task)]
    return (
        "You are solving a reverse-engineering task cold, with no tools, "
        "no feedback loop, and no second chance: one response, final.\n\n"
        f"GOAL: {anchors['goal_verbatim']}\n\n"
        f"SUCCESS: {anchors['success_criterion']}\n\n"
        f"DELIVERABLE: {ws['candidate_contract']}\n\n"
        f"{surface_header}\n"
        f"{target}\n\n"
        f"Respond with ONLY the complete {response_lang} source file that "
        "fulfills the deliverable. No markdown fences, no commentary, "
        "no explanation — source code only."
    )


def extract_candidate(text: str) -> str:
    """Model responses arrive fence-wrapped more often than not: take the
    first fenced block when present, else the raw text. Empty = refusal."""
    lines = text.splitlines()
    if any(ln.strip().startswith("```") for ln in lines):
        inside: bool = False
        buf: list[str] = []
        for ln in lines:
            if ln.strip().startswith("```"):
                if inside:
                    break
                inside = True
                continue
            if inside:
                buf.append(ln)
        body = "\n".join(buf)
    else:
        body = text
    body = body.strip()
    if not body:
        raise ValueError("empty candidate response (nothing to grade)")
    return body


# ------------------------------------------------------------- manifest
def load_manifest(path: Path, known_ids: set[str]) -> dict[str, str | Path]:
    """kunglao-eval-candidates/1: {"candidates": {task_id: {"text": ...}
    | {"path": ...}, ...}}. Text = externally produced output inline;
    path = artifact on disk. Unknown task ids are refusals, never drops."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA_CANDIDATES or \
            not isinstance(data.get("candidates"), dict):
        raise ValueError(f"bad candidates manifest schema: {path}")
    out: dict[str, str | Path] = {}
    for task_id, spec in data["candidates"].items():
        if task_id not in known_ids:
            raise ValueError(f"manifest names unknown task {task_id!r}")
        if isinstance(spec.get("text"), str):
            out[task_id] = spec["text"]
        elif spec.get("path"):
            out[task_id] = Path(spec["path"])
        else:
            raise ValueError(f"candidate for {task_id!r} needs text or path")
    return out


# ------------------------------------------------------------- regrades
def minted_only_grade(family: str, tdir: Path, gt: dict, candidate: Path,
                      outdir: Path) -> tuple[int, int] | None:
    """Grade the candidate over the MINTED-probe subset only: the
    checker's own replay machinery with published pairs stripped (the
    anti-digest-table face decides false-PROVEN). None = ungradeable
    (toolchain absent) — the metric never accuses without a grade."""
    gt_minted = dict(gt)
    gt_minted["published_pairs"] = []
    toolchain = tg.FAMILIES[family]["toolchain"]
    try:
        matched, count, _ttc, _notes = chk.replay_face(
            family, tdir, gt_minted, candidate, outdir, toolchain)
    except chk.Skip:
        return None
    return matched, count


def rerun_verdict(tdir: Path, candidate: Path, outdir: Path) -> str:
    """Fresh full checker re-run (a new subprocess, the runner's own
    run_task face) — the re-run leg of premature closure."""
    return rnr.run_task(tdir, candidate, outdir)["verdict"]


# ------------------------------------------------------------- executor
def claude_prompt_executor(prompt: str,
                           timeout_s: float = DEFAULT_TIMEOUT_S,
                           claude_bin: str = "claude") -> dict:
    """The live model-call face: `claude -p` (bench_runner convention).
    Prompt-only: no permission modes, no tools, one response."""
    started = time.time()
    try:
        proc = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True, text=True, timeout=timeout_s,
            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"mode": "model", "text": "", "returncode": None,
                "wall_s": round(time.time() - started, 3),
                "timed_out": True, "tokens_in": None, "tokens_out": None,
                "stderr": ""}
    return {"mode": "model", "text": proc.stdout,
            "returncode": proc.returncode,
            "wall_s": round(time.time() - started, 3),
            "timed_out": False,
            "tokens_in": None, "tokens_out": None,
            "stderr": (proc.stderr or "")[-2000:]}


def _executor_record(rec: dict, prompt: str | None,
                     cand_path: Path | None, task_id: str) -> dict:
    return {
        "task_id": task_id,
        "prompt_sha256": (hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                          if prompt else None),
        "candidate_path": str(cand_path) if cand_path else None,
        "executor": rec,
    }


# -------------------------------------------------------- bare-arm driver
def run_bare_arm(tasks: list[str], tier: str, out: Path, *,
                 executor=None, manifest: Path | None = None,
                 baselines: bool = False,
                 arm: str = "bare-llm") -> tuple[int, dict, list[dict]]:
    """One bare-arm pass over the tier. Candidates come from the manifest
    or the executor seam (None executor + None manifest = structured SKIP
    rows — the orchestration still proves out). Returns
    (rc, results_doc, per_task_records)."""
    out = Path(out)
    all_dirs = ds.iter_task_dirs(tier=tier)
    known = {d.name for d in all_dirs}
    unknown = [t for t in tasks if t not in known]
    if unknown:
        print(f"FAILURE code=BAD_TASK detail=unknown task(s): {unknown}")
        return RC_REFUSED, {}, []
    selected = [d for d in all_dirs if not tasks or d.name in tasks]

    manifest_cands: dict[str, str | Path] = {}
    if manifest is not None:
        manifest_cands = load_manifest(manifest, known)

    cand_root = out / "candidates"
    cand_map: dict[str, Path] = {}
    records: list[dict] = []
    for tdir in selected:
        task = ds.load_task(tdir)
        tid = tdir.name
        suffix = _cand_suffix(task)
        prompt: str | None = None
        if tid in manifest_cands:
            source = manifest_cands[tid]
            if isinstance(source, Path):
                rec = {"mode": "manifest", "returncode": 0, "wall_s": 0.0,
                       "timed_out": False, "tokens_in": None,
                       "tokens_out": None, "text": ""}
                cand_path: Path | None = source
            else:
                rec = {"mode": "manifest", "returncode": 0, "wall_s": 0.0,
                       "timed_out": False, "tokens_in": None,
                       "tokens_out": None, "text": ""}
                cand_path = cand_root / tid / f"candidate{suffix}"
                cand_path.parent.mkdir(parents=True, exist_ok=True)
                cand_path.write_text(source, encoding="utf-8")
        elif executor is not None:
            prompt = build_bare_prompt(tdir, task)
            rec = dict(executor(prompt, timeout_s=DEFAULT_TIMEOUT_S))
            rec["mode"] = "model"
            cand_path = None
            try:
                body = extract_candidate(rec.get("text") or "")
                cand_path = cand_root / tid / f"candidate{suffix}"
                cand_path.parent.mkdir(parents=True, exist_ok=True)
                cand_path.write_text(body + "\n", encoding="utf-8")
            except ValueError:
                cand_path = None  # structured SKIP row, never silent
        else:
            rec = {"mode": "none", "returncode": None, "wall_s": 0.0,
                   "timed_out": False, "tokens_in": None,
                   "tokens_out": None, "text": ""}
            cand_path = None
        if cand_path is not None:
            cand_map[tid] = cand_path
        records.append(_executor_record(rec, prompt, cand_path, tid))

    rc, doc = rnr.run_tier([t.name for t in selected], tier, arm,
                           cand_map, baselines, out)

    receipt = {
        "schema": SCHEMA_BARE_RUN,
        "arm": arm,
        "tier": tier,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tasks": records,
    }
    (out / f"bare-run-{time.strftime('%Y%m%dT%H%M%SZ')}-"
            f"{os.getpid() % 100000}.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return rc, doc, records


# ------------------------------------------------------------- metrics
def arm_metrics(doc: dict, rerun: dict[str, str],
                minted: dict[str, tuple[int, int] | None],
                wall_s: float | None = None,
                tokens: tuple[int | None, int | None] | None = None
                ) -> dict:
    """The five-metric block for one arm's results doc. Rates are over
    this arm's tier rows; SKIP/REFUSED rows are not answers; ungradeable
    PASS rows (toolchain absent) are reported, never accused."""
    arm = doc.get("arm", "")
    rows = [r for r in doc.get("rows", []) if r.get("arm") == arm]
    total = len(rows)
    answered = sum(1 for r in rows if r["verdict"] in _ANSWER_VERDICTS)
    proven_rows = [r for r in rows
                   if r["verdict"] == "PASS" and r.get("evidence_ref")]
    claimed = [r for r in rows if r.get("metrics", {}).get("converged") == 1]
    premature_ids = [r["task_id"] for r in claimed
                     if is_premature_closure(True, rerun.get(r["task_id"]),
                                             minted.get(r["task_id"]))]
    false_ids = [r["task_id"] for r in proven_rows
                 if is_false_proven(r["verdict"], minted.get(r["task_id"]))]
    ungraded = [r["task_id"] for r in proven_rows
                if minted.get(r["task_id"]) is None]
    tok_in = tok_out = None
    if tokens is not None:
        tok_in, tok_out = tokens
    return {
        "arm": arm,
        "tasks": total,
        "answer_rate": answer_rate(answered, total),
        "proven_with_evidence_rate":
            proven_with_evidence_rate(len(proven_rows), total),
        "premature_closure_rate": premature_closure_rate(
            len(premature_ids), len(claimed)),
        "false_proven_rate": false_proven_rate(len(false_ids),
                                               len(proven_rows)),
        "premature_tasks": premature_ids,
        "false_proven_tasks": false_ids,
        "ungraded": ungraded,
        "budget": {
            "wall_s": wall_s,
            "ttc_seconds_sum": round(sum(
                r.get("metrics", {}).get("ttc_seconds") or 0
                for r in rows), 3),
            "tokens_in": tok_in,
            "tokens_out": tok_out,
        },
    }


def _materialize_manifest(manifest: Path | None, tier: str,
                          out_root: Path) -> dict[str, Path]:
    """Manifest → on-disk candidate artifacts for one arm (text entries
    are materialized; path entries pass through)."""
    cands: dict[str, Path] = {}
    if manifest is None:
        return cands
    known = {d.name for d in ds.iter_task_dirs(tier=tier)}
    dirs = {d.name: d for d in ds.iter_task_dirs(tier=tier)}
    for tid, source in load_manifest(manifest, known).items():
        if isinstance(source, Path):
            cands[tid] = source
            continue
        suffix = _cand_suffix(ds.load_task(dirs[tid]))
        p = out_root / tid / f"candidate{suffix}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(source, encoding="utf-8")
        cands[tid] = p
    return cands


# ----------------------------------------------------------------- A/B
def run_ab(tasks: list[str], tier: str, out: Path, *,
           bare_manifest: Path | None = None,
           framework_manifest: Path | None = None,
           executor=None, baselines: bool = False) -> tuple[int, dict]:
    """One command, both arms. Per-arm kunglao-eval-results/1 docs land
    under out/<arm>/; the comparison summary (kunglao-eval-ab/1) lands
    under out/. rc 0 unless refusal — FAIL rows are measurements."""
    out = Path(out)
    bare_rc, bare_doc, records = run_bare_arm(
        tasks, tier, out / "bare-llm", executor=executor,
        manifest=bare_manifest, baselines=baselines)
    if bare_rc == RC_REFUSED:
        return RC_REFUSED, {}

    # framework candidates: manifest-sourced artifacts (text entries are
    # materialized so the checker gets a real file)
    fw_cands = _materialize_manifest(framework_manifest, tier,
                                     out / "framework" / "candidates")
    fw_rc, fw_doc = rnr.run_tier(tasks, tier, "framework", fw_cands,
                                 baselines, out / "framework")
    if fw_rc == RC_REFUSED:
        return RC_REFUSED, {}

    def _regrade(doc: dict, cand_of: dict[str, Path],
                 arm_out: Path) -> tuple[dict, dict]:
        rerun: dict[str, str] = {}
        minted: dict[str, tuple[int, int] | None] = {}
        for row in doc.get("rows", []):
            if row.get("arm") != doc.get("arm") or row["verdict"] != "PASS":
                continue
            tid = row["task_id"]
            cand = cand_of.get(tid)
            if cand is None or not Path(cand).is_file():
                minted[tid] = None
                continue
            tdir = ds.resolve_task_dir(tid, tier=tier)
            gt = json.loads((tdir / "ground_truth.json")
                            .read_text(encoding="utf-8"))
            family = ds.load_task(tdir)["family"]
            minted[tid] = minted_only_grade(family, tdir, gt, Path(cand),
                                            arm_out)
            if row.get("metrics", {}).get("converged") == 1:
                rerun[tid] = rerun_verdict(tdir, Path(cand), arm_out)
        return rerun, minted

    bare_cand_of = {r["task_id"]: Path(r["candidate_path"])
                    for r in records if r.get("candidate_path")}
    fw_cand_of = dict(fw_cands)
    bare_rerun, bare_minted = _regrade(bare_doc, bare_cand_of,
                                       out / "bare-llm")
    fw_rerun, fw_minted = _regrade(fw_doc, fw_cand_of, out / "framework")

    def _tokens(records_: list[dict]) -> tuple[int | None, int | None]:
        ins = [r["executor"].get("tokens_in") for r in records_
               if r["executor"].get("tokens_in") is not None]
        outs = [r["executor"].get("tokens_out") for r in records_
                if r["executor"].get("tokens_out") is not None]
        return (sum(ins) if ins else None, sum(outs) if outs else None)

    metrics = {
        "framework": arm_metrics(fw_doc, fw_rerun, fw_minted,
                                 wall_s=fw_doc.get("summary", {})
                                 .get("wall_seconds")),
        "bare-llm": arm_metrics(bare_doc, bare_rerun, bare_minted,
                                wall_s=bare_doc.get("summary", {})
                                .get("wall_seconds"),
                                tokens=_tokens(records)),
    }
    cmp_doc = {
        "schema": SCHEMA_AB,
        "tier": tier,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tasks": sorted({r["task_id"] for r in fw_doc.get("rows", [])
                         if r.get("arm") == "framework"} |
                        {r["task_id"] for r in bare_doc.get("rows", [])
                         if r.get("arm") == "bare-llm"}),
        "arms": metrics,
        "results": {"framework": fw_doc, "bare-llm": bare_doc},
    }
    cmp_path = out / (f"ab-compare-{time.strftime('%Y%m%dT%H%M%SZ')}-"
                      f"{os.getpid() % 100000}.json")
    cmp_path.write_text(json.dumps(cmp_doc, indent=2) + "\n",
                        encoding="utf-8")

    print(f"AB-COMPARE {cmp_path}")
    header = (f"{'arm':<12}{'tasks':>6}{'answer':>8}{'prov+ev':>9}"
              f"{'premature':>11}{'falsePROVEN':>13}{'wall_s':>9}")
    print(header)
    for arm_name in ("framework", "bare-llm"):
        m = metrics[arm_name]
        b = m["budget"]
        print(f"{arm_name:<12}{m['tasks']:>6}{m['answer_rate']:>8.2f}"
              f"{m['proven_with_evidence_rate']:>9.2f}"
              f"{m['premature_closure_rate']:>11.2f}"
              f"{m['false_proven_rate']:>13.2f}"
              f"{(b['wall_s'] if b['wall_s'] is not None else 0):>9.2f}")
    print(f"VERDICT {cmp_doc['schema']}")
    return RC_OK, cmp_doc


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_control_arm.py",
        description="#236 bare-LLM control arm + A/B run face on the "
                    "#299 smoke tier.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ab", action="store_true",
                      help="run BOTH arms and emit the comparison table")
    mode.add_argument("--bare", action="store_true",
                      help="run the bare-LLM arm only")
    ap.add_argument("--tier", default="smoke", choices=sorted(ds.TIERS))
    ap.add_argument("--tasks", default="",
                    help="comma-separated task ids (default: whole tier)")
    ap.add_argument("--manifest", default=None,
                    help="kunglao-eval-candidates/1 manifest with the "
                         "bare arm's candidates (text or path entries)")
    ap.add_argument("--framework-manifest", default=None,
                    help="candidates manifest for the framework arm")
    ap.add_argument("--live", action="store_true",
                    help="prompt-only runs through `claude -p` (the bench "
                         "model-call face) instead of the manifest")
    ap.add_argument("--baselines", action="store_true",
                    help="append the 1/k-guessing floor rows")
    ap.add_argument("--out", default=str(
        ds.EVAL_ROOT.parent / "runs" / "eval-control"),
        help="output dir (default: runs/eval-control/)")
    args = ap.parse_args(argv)

    tasks = [t for t in args.tasks.split(",") if t]
    executor = claude_prompt_executor if args.live else None
    out = Path(args.out)
    try:
        if args.ab:
            rc, _ = run_ab(tasks, args.tier, out,
                           bare_manifest=Path(args.manifest)
                           if args.manifest else None,
                           framework_manifest=Path(args.framework_manifest)
                           if args.framework_manifest else None,
                           executor=executor, baselines=args.baselines)
            return rc
        rc, _doc, _recs = run_bare_arm(tasks, args.tier, out,
                                       executor=executor,
                                       manifest=Path(args.manifest)
                                       if args.manifest else None,
                                       baselines=args.baselines)
        return rc
    except ValueError as exc:
        print(f"FAILURE code=BAD_MANIFEST detail={exc}")
        print("VERDICT REFUSED")
        return RC_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
