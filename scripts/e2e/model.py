# -*- coding: utf-8 -*-
"""e2e.model — data structures + adjudication tables for the E2E runner.

Pure data + pure functions only (no subprocess, no filesystem writes
beyond staging); everything here is unit-pinned by tests/test_e2e_runner.py.

Data structures (the design contract, stated first):
  CmdOutcome        one subprocess execution (rc/stdout/stderr/timeout).
  CheckpointResult  one checkpoint's adjudication + evidence envelope.
  RunState          the run identity: paths, budget clock, anchors, steps.
  DispatchRequest   the machine-readable dispatch file (v1 envelope).
  PipelineArgs      CLI-facing pipeline configuration (dataclass config).
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from harness_common import utc_now_z as utc_now  # #863 Family F: single source

# ---------------------------------------------------------------------------
# exit codes (spec: 0/2/3/4). NOTE: 2 is dual-used — argparse's own usage-
# error exit (cli.py usage errors ride it too); 1 is unused.
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_CHECKPOINT_FAIL = 2
EXIT_BLOCKED = 3
EXIT_BUDGET_PARTIAL = 4

#: Runbook stop conditions: 4h wall budget for the analysis phase.
DEFAULT_BUDGET_SECONDS = 14_400

#: C5 needs >= 2 consecutive ticks; interval is 5m (liveness_policy
#: TICK_INTERVAL_DEFAULT_MIN). The scripts expose NO test/override hook
#: for the interval, so the honest default is the real 5m wait ONCE —
#: never longer. Pipelines may lower it (dry-llm tests use 0).
TICK_WAIT_SECONDS_DEFAULT = 300

#: stdout/stderr evidence tails (bytes) kept per checkpoint.
TAIL_CHARS = 4_000

CONTAMINATION_NAMES = ("ground_truth.json", "checker.py",
                       "reference.py", "reference_candidate.py")

#: Answer-equivalent file NAMES (the checker's self-check / ground-truth
#: sources). Checker-side only — never staged into the E2E
#: workspace; the checker invokes them harness-side from the REPO tree.
ANSWER_FILE_NAMES = frozenset({"reference.py", "reference_candidate.py"})

#: The REAL #880 settlement action. register_proven_gate.emit_settlements
#: emits kunglao_log rows with action="claim_settled" (actor
#: "hook:write_guard"; consumed as claim_settled by mechanism_scheduler /
#: terminal_settlement / backtrack_loop). The runbook's "#880
#: action=settlement" sentence does not match the repo — the productization
#: matches the REPO, not the runbook (review F2).
SETTLEMENT_ACTION = "claim_settled"

# ---------------------------------------------------------------------------
# adjudication table — step id -> expected rc set (the runbook's
# "Expected:" lines, one row each). Anything outside the set is FAIL;
#: rows with classified stop semantics live in *_STOP_RC below.
# ---------------------------------------------------------------------------

EXPECTED_RC: dict[str, frozenset[int]] = {
    # C1 init: pending exit 8, resolved exit 0
    "C1-init-pending": frozenset({8}),
    "C1-init-resolved": frozenset({0}),
    # C2 hooks wire-up + selfcheck
    "C2-hooks": frozenset({0}),
    # C3 heartbeat-on / loop-registered / first tick
    "C3-heartbeat": frozenset({0}),
    # C4 kunglao check-stale
    "C4-entry": frozenset({0}),
    # C5 second tick then `kunglao analysis`
    "C5-second-tick": frozenset({0}),
    "C5-analysis": frozenset({0}),
    # C6 pre: goal-op validate / env_check / decide DISPATCH / rank
    "C6-goal-op": frozenset({0}),
    "C6-env-check": frozenset({0}),
    "C6-dispatch": frozenset({1}),  # convergence_check EXIT_DISPATCH
    "C6-pre": frozenset({0}),
    # C6 loop per-tick: tick + convergence_check (decision-dependent)
    "C6-loop": frozenset({0, 1, 2, 3}),  # tick 0; decide DISPATCH..SATURATED
    # C7 completion: CONVERGED decide + completion_gate
    "C7-convergence": frozenset({0}),
    "C7-completion": frozenset({0}),
    # ORACLE: replay checker
    "ORACLE": frozenset({0}),
}

#: C5 analysis-entry stop rcs (kunglao analysis: 5 stale / 6 heartbeat
#: dead / 7 anchors missing) — classified STOP, reported BLOCKED.
ANALYSIS_STOP_RC: dict[int, str] = {
    5: "stale-workspace",
    6: "heartbeat-verify-failed",
    7: "intake-answers-missing",
}

#: C1 exit-4 HARD toolchain failure — runbook: STOP, capture stderr.
INIT_STOP_RC: dict[int, str] = {4: "toolchain-hard-fail"}

PASS, FAIL, BLOCKED, SKIP = "PASS", "FAIL", "BLOCKED", "SKIP"

#: The ordered pipeline steps (checkpoint, name); step id = Cn-name,
#: except the gold-standard oracle which keeps its bare name.
CHECKPOINT_STEPS: tuple[tuple[str, str], ...] = (
    ("C1", "init"), ("C2", "hooks"), ("C3", "heartbeat"), ("C4", "entry"),
    ("C5", "analysis"), ("C6", "pre"), ("C6", "loop"), ("C7", "completion"),
    ("ORACLE", "oracle"),
)


def step_id(checkpoint: str, name: str) -> str:
    """Evidence-file stem for a checkpoint (ORACLE keeps its bare name)."""
    return checkpoint if checkpoint == "ORACLE" else f"{checkpoint}-{name}"


def adjudicate(step_id_: str, rc: int) -> str:
    """PASS when rc is in the step's expected set; classified BLOCKED for
    the runbook's stop rcs; FAIL otherwise. Unknown steps KeyError loudly
    (a step outside the runbook is a spec drift, never a silent default)."""
    if step_id_ not in EXPECTED_RC:
        raise KeyError(f"unknown checkpoint step {step_id_!r}")
    if rc in EXPECTED_RC[step_id_]:
        return PASS
    if step_id_ == "C5-analysis" and rc in ANALYSIS_STOP_RC:
        return BLOCKED
    if step_id_.startswith("C1-init") and rc in INIT_STOP_RC:
        return BLOCKED
    return FAIL


def classify_analysis_rc(rc: int) -> str | None:
    """Runbook C5 stop classification, or None when rc is not a stop rc."""
    return ANALYSIS_STOP_RC.get(rc)


def classify_init_stop_rc(rc: int) -> str | None:
    return INIT_STOP_RC.get(rc)


# ---------------------------------------------------------------------------
# task anchors (C1 resolve answers, used VERBATIM)
# ---------------------------------------------------------------------------


class AnchorError(Exception):
    """task.yaml is missing a required oracle anchor — refuse to run."""


ANCHOR_KEYS = ("goal_verbatim", "success_criterion", "verification_method")


def load_anchors(task_yaml: Path) -> dict[str, str]:
    """Read the three oracle anchors from the eval unit's task.yaml.

    Used VERBATIM in C1 resolve answers and in the C6 goal-op fill —
    any missing/empty anchor is a hard error (AnchorError), never a
    silent default."""
    import yaml  # local import: yaml is a repo dependency, keep module lean

    doc = yaml.safe_load(Path(task_yaml).read_text(encoding="utf-8")) or {}
    anchors = doc.get("anchors") or {}
    missing = [k for k in ANCHOR_KEYS if not str(anchors.get(k) or "").strip()]
    if missing:
        raise AnchorError(
            f"{task_yaml}: missing required anchor(s): {', '.join(missing)}")
    return {k: str(anchors[k]).strip() for k in ANCHOR_KEYS}


def synthesize_answers(pending_ids: list[str], anchors: dict[str, str],
                       lane: str, type_: str) -> tuple[dict[str, str], list[str]]:
    """Build the --resolve answers for every pending decision id.

    Anchor decisions answer VERBATIM from task.yaml; the lane/type
    alignment decisions re-supply the CLI flags (rehearsal finding #1:
    flags are NOT persisted across re-entries). Decision ids the runner
    has no rule for come back in `unmapped` — the driver reports BLOCKED
    instead of guessing."""
    answers: dict[str, str] = {}
    unmapped: list[str] = []
    for decision_id in pending_ids:
        if decision_id in ANCHOR_KEYS:
            answers[decision_id] = anchors[decision_id]
        elif decision_id in ("lane",):
            answers[decision_id] = lane
        elif decision_id in ("type", "project_type", "target_type"):
            answers[decision_id] = type_
        else:
            unmapped.append(decision_id)
    return answers, unmapped


# ---------------------------------------------------------------------------
# workspace staging + contamination guard (runbook fixed-path rules)
# ---------------------------------------------------------------------------


def scaffold_material(task_dir: Path) -> list[str]:
    """The unit's task.yaml-declared analysis material:
    workspace_scaffold.files minus the checker's answer sources (the
    declared self_check_candidate plus any answer-equivalent name).

    A unit with no declared files, or whose every declared file is an
    answer source, has NO analysis material — AnchorError, never an
    empty mount."""
    import yaml  # local import: yaml is a repo dependency, keep module lean

    task_yaml = Path(task_dir) / "task.yaml"
    doc = yaml.safe_load(task_yaml.read_text(encoding="utf-8")) or {}
    files = (doc.get("workspace_scaffold") or {}).get("files") or []
    self_check = str(((doc.get("checker") or {})
                      .get("self_check_candidate")) or "")
    material = [f for f in files
                if f != self_check and Path(f).name not in ANSWER_FILE_NAMES]
    if not material:
        raise AnchorError(
            f"{task_yaml}: workspace_scaffold.files declares no analysis "
            "material (empty, or answer sources only)")
    return material


def stage_workspace(task_dir: Path, ws: Path) -> Path:
    """Material mount: copy ONLY the unit's task.yaml-declared analysis
    material (workspace_scaffold.files) into WS, preserving relative
    paths. Answer sources (reference.py = the checker's self-check
    candidate) never stage — the checker invokes them harness-side
    from the REPO tree; its default --candidate is its own unit dir.

    WS lives OUTSIDE the repo (never inside it). ground_truth.json and
    checker.py stay out of the workspace — the checker is resolved from
    the REPO tree at C7 (rehearsal finding #3). A declared file missing
    from the task unit is a loud FileNotFoundError — never a partial
    silent stage."""
    task_dir = Path(task_dir)
    ws = Path(ws)
    for rel in scaffold_material(task_dir):
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(task_dir / rel, dst)
    return ws


def check_contamination(ws: Path) -> list[str]:
    """Return every contamination violation under WS (path strings).

    ground_truth.json / checker.py / reference.py /
    reference_candidate.py must never exist anywhere inside the
    workspace — as file OR directory — in any nesting (the answer sources
    are checker-side, invoked from the REPO tree)."""
    ws = Path(ws)
    violations: list[str] = []
    if not ws.is_dir():
        return violations
    for path in sorted(ws.rglob("*")):
        if path.name in CONTAMINATION_NAMES:
            violations.append(str(path))
    return violations


def resolve_candidate(ws: Path, task_yaml: Path) -> Path:
    """The oracle face's replay candidate: the unit's OWN declaration
    (task.yaml checker.candidate, ws-relative) when present, else the
    smoke-rehearsal default artifacts/derive_reimpl.py. matrix4b G3:
    the combat units' contract is a ws-root client.py — the hardcoded
    rehearsal shape sent finished work to a no-candidate BLOCK."""
    import yaml  # local import: yaml is a repo dependency, keep lean
    try:
        doc = yaml.safe_load(Path(task_yaml).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        doc = {}
    declared = ((doc.get("checker") or {}).get("candidate")
                if isinstance(doc.get("checker"), dict) else None)
    if isinstance(declared, str) and declared.strip():
        return Path(ws) / declared.strip().lstrip("/")
    return Path(ws) / "artifacts" / "derive_reimpl.py"


def resolve_checker(repo: Path, family: str, unit: str) -> Path | None:
    """Checker path resolved from the REPO tree (never a /tmp copy)."""
    checker = Path(repo) / "eval/v1/tasks" / family / unit / "checker.py"
    return checker if checker.is_file() else None


def scan_settlement_rows(ws: Path) -> dict:
    """Count #880 settlement rows in WS/runs/logs/kunglao-*.jsonl.

    Matches the REAL emitter's action value (SETTLEMENT_ACTION =
    "claim_settled" — register_proven_gate.emit_settlements →
    kunglao_log.emit); deterministic file order, malformed lines skipped
    without silent swallowing (counted in parse_errors)."""
    ws = Path(ws)
    files: list[str] = []
    rows = 0
    parse_errors = 0
    log_dir = ws / "runs" / "logs"
    if not log_dir.is_dir():
        return {"rows": rows, "files": files, "parse_errors": parse_errors}
    for path in sorted(log_dir.glob("kunglao-*.jsonl")):
        files.append(str(path))
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                parse_errors += 1
                continue
            if isinstance(row, dict) and row.get("action") == SETTLEMENT_ACTION:
                rows += 1
    return {"rows": rows, "files": files, "parse_errors": parse_errors}


def parse_checker_output(stdout: str) -> dict:
    """Parse the REAL eval_checker stdout (scripts/eval_checker.py run()
    tail): ``METRIC <n>=<v>`` lines (eval_dataset.metric_line), optional
    ``FAILURE code=... detail=...`` lines, then terminal ``EVIDENCE
    <path>`` and ``VERDICT <v>`` lines. NO JSON object is printed on
    stdout — the metrics/verdict dict lands in the evidence FILE only
    (review F1). The LAST VERDICT line wins (terminal emission order)."""
    metrics: dict = {}
    failures: list[str] = []
    evidence_path: str | None = None
    verdict: str | None = None
    for raw in (stdout or "").splitlines():
        line = raw.strip()
        if line.startswith("METRIC ") and "=" in line:
            name, _, value = line[len("METRIC "):].partition("=")
            if not name:
                continue
            try:
                metrics[name] = (float(value) if any(c in value for c in ".eE")
                                 else int(value))
            except ValueError:
                metrics[name] = value
        elif line.startswith("FAILURE "):
            failures.append(line)
        elif line.startswith("EVIDENCE ") and evidence_path is None:
            evidence_path = line.split(None, 1)[1].strip()
        elif line.startswith("VERDICT "):
            verdict = line.split(None, 1)[1].strip()
    return {"verdict": verdict, "evidence_path": evidence_path,
            "metrics": metrics, "failures": failures}


def load_min_pair_ratio(task_yaml: Path) -> float:
    """The task's required min_pair_ratio (checker.thresholds in the eval
    unit's task.yaml; default 1.0 — the gold-standard acceptance)."""
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(Path(task_yaml).read_text(encoding="utf-8")) or {}
    thresholds = ((doc.get("checker") or {}).get("thresholds") or {})
    try:
        return float(thresholds.get("min_pair_ratio", 1.0))
    except (TypeError, ValueError):
        return 1.0


# ---------------------------------------------------------------------------
# data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CmdOutcome:
    """One subprocess execution. timed_out keeps timeouts honest: rc is
    -1 and the adjudication FAILs — never a silent retry."""
    rc: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class CheckpointResult:
    """One checkpoint's adjudication + evidence envelope (the on-disk
    schema: runs/e2e/<runid>/<step>.json)."""
    checkpoint: str          # "C1".."C7" | "ORACLE"
    name: str                # "init", "hooks", ... | "oracle"
    status: str              # PASS | FAIL | BLOCKED | SKIP
    rc: int | None
    stdout_tail: str
    stderr_tail: str
    duration_ms: int
    evidence_paths: list[str]
    ts: str
    detail: dict = field(default_factory=dict)

    @property
    def step(self) -> str:
        return step_id(self.checkpoint, self.name)

    def to_dict(self) -> dict:
        out = {
            "checkpoint": self.checkpoint, "name": self.name,
            "step": self.step, "status": self.status, "rc": self.rc,
            "stdout_tail": self.stdout_tail, "stderr_tail": self.stderr_tail,
            "duration_ms": self.duration_ms,
            "evidence_paths": list(self.evidence_paths), "ts": self.ts,
            "detail": self.detail,
        }
        return out

    @classmethod
    def from_dict(cls, doc: dict) -> "CheckpointResult":
        return cls(
            checkpoint=doc["checkpoint"], name=doc["name"],
            status=doc["status"], rc=doc.get("rc"),
            stdout_tail=doc.get("stdout_tail", ""),
            stderr_tail=doc.get("stderr_tail", ""),
            duration_ms=int(doc.get("duration_ms", 0)),
            evidence_paths=list(doc.get("evidence_paths", [])),
            ts=doc.get("ts", ""), detail=dict(doc.get("detail", {})))


@dataclass
class DispatchRequest:
    """Machine-readable dispatch file (the v1 canonical envelope + the
    prompt the orchestrator/agent executes; written by --emit-dispatch
    and by the C6 loop's orchestrator face)."""
    claim: str
    workspace: str
    prompt_file: str
    run_id: str
    schema_version: str = "kunglao_dispatch/1"
    tier: int = 1
    tools: tuple[str, ...] = ("grep", "python3")
    agent: str = "kunglao-worker"
    emitted_ts: str = ""
    # kernel-facing hook (audit §4): set only when the run declares a
    # method family; the envelope gains the key ONLY when set, so the v1
    # canonical envelope stays byte-compatible for current runs.
    method_family: str | None = None
    # matrix4 K1 wiring: the Luby ladder's per-attempt timeout; set
    # only by the C6 loop's launch (never the v1 envelope on disk —
    # serialized ONLY when set, the method_family precedent).
    timeout_s: int | None = None

    def to_dict(self) -> dict:
        emitted_ts = self.emitted_ts or utc_now()
        out = {
            "schema_version": self.schema_version,
            "kunglao_dispatch": {
                "version": 1, "claim": self.claim, "tier": self.tier,
                "tools": list(self.tools), "agent": self.agent,
            },
            "run_id": self.run_id, "claim": self.claim,
            "workspace": self.workspace, "prompt_file": self.prompt_file,
            "tier": self.tier, "tools": list(self.tools),
            "agent": self.agent, "emitted_ts": emitted_ts,
        }
        if self.method_family:
            out["method_family"] = self.method_family
        if self.timeout_s:
            out["timeout_s"] = self.timeout_s
        return out


@dataclass
class RunState:
    """The run identity. `started_monotonic` is injectable so unit tests
    drive budget accounting with a fake clock."""
    run_id: str
    unit: str
    family: str
    repo: str
    task_dir: str
    ws: str
    evidence_dir: str
    budget_seconds: int
    llm_mode: str                       # orchestrator | auto | dry
    started_ts: str
    started_monotonic: float
    anchors: dict[str, str]
    ws_root: str = ""
    lane: str = "algorithm"
    type_: str = "linux"
    method_family: str = ""
    tick_wait_seconds: int = TICK_WAIT_SECONDS_DEFAULT
    max_ticks: int = 60
    budget_consumed_seconds: float = 0.0
    steps: dict[str, str] = field(default_factory=dict)
    total_duration_ms: int = 0

    def budget_remaining_seconds(self, now_monotonic: float | None = None) -> float:
        elapsed = (now_monotonic if now_monotonic is not None
                   else self.started_monotonic) - self.started_monotonic
        consumed = max(elapsed, self.budget_consumed_seconds)
        return max(0.0, float(self.budget_seconds) - consumed)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id, "unit": self.unit, "family": self.family,
            "repo": self.repo, "task_dir": self.task_dir, "ws": self.ws,
            "ws_root": self.ws_root, "evidence_dir": self.evidence_dir,
            "budget_seconds": self.budget_seconds,
            "budget_consumed_seconds": self.budget_consumed_seconds,
            "llm_mode": self.llm_mode, "started_ts": self.started_ts,
            "lane": self.lane, "type": self.type_,
            "method_family": self.method_family,
            "tick_wait_seconds": self.tick_wait_seconds,
            "max_ticks": self.max_ticks,
            "anchors": dict(self.anchors), "steps": dict(self.steps),
        }

    @classmethod
    def from_dict(cls, doc: dict) -> "RunState":
        return cls(
            run_id=doc["run_id"], unit=doc["unit"], family=doc["family"],
            repo=doc["repo"], task_dir=doc["task_dir"], ws=doc["ws"],
            evidence_dir=doc["evidence_dir"],
            budget_seconds=int(doc["budget_seconds"]),
            llm_mode=doc["llm_mode"], started_ts=doc["started_ts"],
            started_monotonic=0.0, anchors=dict(doc.get("anchors", {})),
            ws_root=doc.get("ws_root", ""), lane=doc.get("lane", "algorithm"),
            type_=doc.get("type", "linux"),
            method_family=str(doc.get("method_family", "")),
            tick_wait_seconds=int(doc.get("tick_wait_seconds",
                                          TICK_WAIT_SECONDS_DEFAULT)),
            max_ticks=int(doc.get("max_ticks", 60)),
            budget_consumed_seconds=float(
                doc.get("budget_consumed_seconds", 0.0)),
            steps=dict(doc.get("steps", {})))


@dataclass(frozen=True)
class PipelineArgs:
    """CLI-facing pipeline configuration (immutable config object)."""
    unit: str
    repo: Path
    ws_root: Path
    budget_seconds: int = DEFAULT_BUDGET_SECONDS
    llm_mode: str = "orchestrator"      # orchestrator | auto | dry
    tick_wait_seconds: int = TICK_WAIT_SECONDS_DEFAULT
    run_id: str | None = None           # fixed id (tests / --resume)
    lane: str = "algorithm"
    type_: str = "linux"
    max_ticks: int = 60                 # loop safety: never spin forever


def parse_last_json(text: str) -> dict | None:
    """Parse the last JSON object printed on a script's stdout (scripts
    may print human lines before the machine face)."""
    for chunk in reversed(_json_chunks(text)):
        try:
            doc = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    return None


def _json_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    chunks.append(text[start:i + 1])
    return chunks
