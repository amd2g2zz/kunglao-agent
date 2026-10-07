# -*- coding: utf-8 -*-
"""e2e.checkpoints — the C1→C7 + ORACLE checkpoint engine (driver).

Encodes the runbook (.claude/e2e-runbook-source.md) exactly:
  C1  init (pending exit 8 → answers verbatim → --resolve WITH the
      lane/type flags repeated — rehearsal finding #1)
  C2  hooks wire-up + mechanical import sweep
  C3  heartbeat on + loop-registered + first tick (no module_emit
      degradation; runs/.heartbeat.json must exist)
  C4  entry via the registered `kunglao check-stale` console script
  C5  >= 2 consecutive ticks (real 5m wait ONCE) then `kunglao analysis`
  C6  Phase-0 goal-operationalization (rehearsal finding #2), intake
      enrichment, claim registration, env_check, decide DISPATCH, rank
  C6  per-tick dispatch loop via the configured LLM face
  C7  promotion (register_proven_gate), verdict, CONVERGED,
      completion_gate, settlement rows
  ORACLE  replay checker from the REPO tree (finding #3), VERDICT PASS +
      min_pair_ratio 1.0 = the run's final verdict

No silent degradation: every step's outcome lands in structured
evidence; the first failure stops the pipeline (recorded, never retried).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from e2e import audit, evidence, llm_faces, model
from e2e.runtime import (  # noqa: F401 — re-exported seams (patch points)
    IMPORT_ERRORS, RunContext, budget_ok as _guard_budget,
    family_of, new_run_id, parse_decision as _decide,
    promote_claims, ranked_claims as _ranked_claims,
    record_result as _record, resolve_task_dir,
    resume_plan, tail as _tail, top_claim as _top_claim,
    _load_repo_module,
)
import kunglao_log  # #472: the canonical warn
from ws_yaml import canonical_dump as _canonical_dump  # #524 AD3 (spec-unreadable trace)

#: #459: max dispatch acts launched CONCURRENTLY per tick wave. The acts
#: are independent `claude -p` processes in one workspace; the loop is
#: sequential Python, so the `dispatched` set is mutated only in the main
#: thread (launch + landing) — pool threads never touch it.
MAX_PARALLEL_DISPATCH = 3


def _max_parallel_dispatch() -> int:
    """The wave bound, overridable via KUNGLAO_E2E_MAX_PARALLEL (read at
    call time so tests/CI can pin it per run). Floor 1 — a 0/garbage value
    never yields an empty wave by accident; unparseable falls back to the
    module default."""
    raw = os.environ.get("KUNGLAO_E2E_MAX_PARALLEL", "")
    try:
        n = int(raw)
    except ValueError:
        return MAX_PARALLEL_DISPATCH
    return max(1, n)

# ---------------------------------------------------------------------------
# C6 pre-registration payload (runbook C6-pre-1..3, verbatim templates)
# ---------------------------------------------------------------------------

# #456 bug-3: claims generated from the unit's task.yaml anchors.
_DEFAULT_PQ = (
    {"id": "pq-1",
     "question": "What are the three derivation parameters of "
                 "target/derive.py?"},
    {"id": "pq-2",
     "question": "Does a re-implemented derive() reproduce every "
                 "published and checker-minted probe output exactly?"},
)
_DEFAULT_CLAIMS = (
    {"id": "C-004",
     "statement": "target/derive.py implements a 64-bit derivation whose "
                  "three parameters (initial offset, multiply prime, fold "
                  "multiplier) are recoverable from the target source + "
                  "probe outputs.",
     "answers_question": "pq-1", "boundary_type": "numeric",
     "promotion_gate": "all three constants re-derived from evidence and "
                       "byte-confirmed by the replay checker",
     "status": "OPEN", "source": "static_re"},
    {"id": "C-005",
     "statement": "A re-implementation of derive() reproduces every "
                  "published and checker-minted probe output exactly.",
     "answers_question": "pq-2", "boundary_type": "confirmed",
     "status": "OPEN", "source": "synthesis"},
)

PRIMARY_QUESTIONS: tuple[dict, ...] = _DEFAULT_PQ
CLAIM_APPENDS: tuple[dict, ...] = _DEFAULT_CLAIMS


def _resolve_claims(task_spec: Path) -> None:
    """#456 bug-3: resolve PQ/CLAIMS from the unit's task.yaml anchors.
    Falls back to the py-derive-v1 shape when anchors are absent.

    #472: the fallback faces are distinguished — spec-ABSENT and
    anchors-ABSENT are the silent legitimate faces (no anchors to
    read); spec-UNREADABLE (exists but corrupt, or not a mapping)
    leaves ONE rate-limited warn so a corrupt spec is never
    indistinguishable from an absent anchor."""
    global PRIMARY_QUESTIONS, CLAIM_APPENDS
    if not task_spec.is_file():
        # absent spec: the documented anchors-absent-adjacent fallback
        # face — silent (nothing to read is not corruption)
        PRIMARY_QUESTIONS = _DEFAULT_PQ
        CLAIM_APPENDS = _DEFAULT_CLAIMS
        return
    try:
        import yaml as _yaml
        spec = _yaml.safe_load(task_spec.read_text(encoding="utf-8"))
        if not isinstance(spec, dict):
            # empty/null/list-shaped spec: restore defaults — a reused
            # process must not leak the previous unit's resolved claims
            kunglao_log.warn(
                "e2e.resolve_claims",
                f"spec not a mapping ({type(spec).__name__}), "
                f"defaults restored: {task_spec}")
            PRIMARY_QUESTIONS = _DEFAULT_PQ
            CLAIM_APPENDS = _DEFAULT_CLAIMS
            return
        anchors = spec.get("anchors") or {}
        # #456 bug-3 (round-4 lesson): kunglao-init writes the oracle
        # anchors at the TOP LEVEL of task_spec.yaml; the nested anchors{}
        # shape is the C1 answers file. Read both — top level wins, so a
        # beacon workspace never falls back to the py-derive defaults.
        goal = (str(spec.get("goal_verbatim", "")).strip()
                or str(anchors.get("goal_verbatim", "")).strip())
        criterion = (str(spec.get("success_criterion", "")).strip()
                     or str(anchors.get("success_criterion", "")).strip())
        if not goal:
            PRIMARY_QUESTIONS = _DEFAULT_PQ
            CLAIM_APPENDS = _DEFAULT_CLAIMS
            return
        task_id = str(spec.get("task_id", "unknown"))
        PRIMARY_QUESTIONS = (
            {"id": "pq-1",
             "question": f"What approach resolves: {goal[:180]}?"},
            {"id": "pq-2",
             "question": f"Does the result satisfy: {criterion[:180]}?"},
        )
        CLAIM_APPENDS = (
            {"id": "C-004",
             "statement": f"The target for {task_id} is characterizable; "
                          f"its key parameters are recoverable from the "
                          f"workspace material.",
             "answers_question": "pq-1", "boundary_type": "analysis",
             "promotion_gate": "parameters derived from evidence and "
                               "confirmed by the checker",
             "status": "OPEN", "source": "static_re"},
            {"id": "C-005",
             "statement": f"A re-implementation for {task_id} satisfies "
                          f"the success criterion.",
             "answers_question": "pq-2", "boundary_type": "confirmed",
             "status": "OPEN", "source": "synthesis"},
        )
    except Exception as exc:  # never-raise resolver: ANY failure restores defaults
        # #472: the restore is silent NO LONGER — a corrupt spec left
        # one rate-limited trace (anchors-absent above stays silent:
        # that fallback is the documented #456 behavior, not a defect)
        kunglao_log.warn(
            "e2e.resolve_claims",
            f"spec unreadable, defaults restored: "
            f"{type(exc).__name__}: {exc}")
        PRIMARY_QUESTIONS = _DEFAULT_PQ
        CLAIM_APPENDS = _DEFAULT_CLAIMS


def build_goal_op_doc(anchors: dict[str, str]) -> dict:
    """goal-operationalization.yaml instantiated FROM the task's verbatim
    anchors (runbook C6-pre-1 template, values exactly as rehearsed)."""
    return {
        "schema": "goal-operationalization/1",
        "goal_verbatim": anchors["goal_verbatim"],
        "deliverables": [
            "Re-implementation of derive(data: bytes) -> int committed in "
            "the workspace (artifacts/derive_reimpl.py) reproducing the "
            "reference outputs",
            "The three derivation parameters recorded as numeric facts "
            "with evidence",
        ],
        "acceptance": [
            "eval checker VERDICT PASS on the re-implementation "
            "(min_pair_ratio 1.0)",
            "byte-exact reproduction of all 12 published + "
            "checker-minted probes",
        ],
        "not_done": [
            "a re-implementation matching only the two __main__ probe "
            "strings does not count as done",
            "parameters asserted without a fact file + evidence pointer "
            "do not count as done",
        ],
        "diff_vs_verbatim": [
            "analysis material is the constructed eval target "
            "(target/derive.py), not a live binary sample",
        ],
        "generalization": "required",
        "probe_cases": [
            "checker-minted probes (12, never captured) — fresh-input "
            "master oracle",
            "published pairs 0-11 — replay verification ladder",
        ],
        "declared_ts": model.utc_now(),
        "oracle_behavior_acknowledged": True,
    }


# ---------------------------------------------------------------------------
# checkpoints
# ---------------------------------------------------------------------------


def _hook_sweep(ctx: RunContext) -> list[dict]:
    """C2 mechanical sweep: every hook command in WS/.claude/settings.json
    runs once in a throwaway cwd; stderr must be free of import errors."""
    settings = ctx.ws / ".claude" / "settings.json"
    if not settings.is_file():
        raise FileNotFoundError("hooks not deployed: missing WS/.claude/settings.json")
    doc = json.loads(settings.read_text(encoding="utf-8"))
    commands: list[str] = []
    hooks = doc.get("hooks") or {}
    for event in sorted(hooks):
        entries = hooks[event]
        if isinstance(entries, dict):
            entries = [entries]
        for entry in entries if isinstance(entries, list) else []:
            for h in entry.get("hooks") or []:
                cmd = h.get("command")
                if cmd:
                    commands.append(cmd)
    sweep: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="e2e-hooksweep-") as tmp:
        throwaway = Path(tmp)
        for cmd in sorted(set(commands)):
            outcome, duration_ms = ctx.cmd(["sh", "-c", cmd],
                                           cwd=throwaway, timeout=60)
            dirty = [e for e in IMPORT_ERRORS if e in outcome.stderr]
            sweep.append({"command": cmd, "rc": outcome.rc,
                          "import_errors": dirty,
                          "stderr_tail": _tail(outcome.stderr),
                          "duration_ms": duration_ms})
    return sweep


def _staged_entry(task_dir: Path) -> str | None:
    """#460 intake battery: the task's declared analysis entry
    (task.yaml workspace_scaffold.entry), the battery's probe subject on
    the e2e face. Tolerant — a task without a declared entry runs no
    battery (explicit, never a raise)."""
    import yaml  # noqa: PLC0415 — lazy (C1-only; a hard repo dep)

    try:
        doc = yaml.safe_load(
            (Path(task_dir) / "task.yaml").read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(doc, dict):
        return None
    entry = (doc.get("workspace_scaffold") or {}).get("entry") \
        if isinstance(doc.get("workspace_scaffold"), dict) else None
    return str(entry) if isinstance(entry, str) and entry.strip() else None


def checkpoint_c1(ctx: RunContext) -> model.CheckpointResult:
    """C1 init: pending(exit 8) → resolve(verbatim anchors, flags
    repeated) → exit 0. Sub-step rcs ride detail."""
    out_a, ms_a = ctx.py("kunglao-init.py", str(ctx.ws),
                         "--lane", ctx.state.lane, "--type", ctx.state.type_)
    status_a = model.adjudicate("C1-init-pending", out_a.rc)
    detail: dict = {"sub_pending_rc": out_a.rc,
                    "sub_pending_status": status_a}
    if status_a != model.PASS:
        reason = (model.classify_init_stop_rc(out_a.rc)
                  or model.classify_analysis_rc(out_a.rc))
        detail["stop_class"] = reason or "unexpected-rc"
        return _record(ctx, "C1", "init", status_a, out_a.rc, out_a, ms_a,
                       detail)
    pending = model.parse_last_json(out_a.stdout) or {}
    ids = [str(d.get("decision_id"))
           for d in pending.get("decisions") or []
           if isinstance(d, dict) and d.get("decision_id")]
    answers, unmapped = model.synthesize_answers(
        ids, ctx.state.anchors, lane=ctx.state.lane, type_=ctx.state.type_)
    detail["pending_ids"] = ids
    detail["unmapped_ids"] = unmapped
    if unmapped:
        return _record(ctx, "C1", "init", model.BLOCKED, out_a.rc, out_a,
                       ms_a, {**detail,
                              "stop_class": "unmapped-decision-ids"})
    answers_path = Path(ctx.state.evidence_dir) / "c1-answers.json"
    answers_path.parent.mkdir(parents=True, exist_ok=True)
    answers_path.write_text(
        json.dumps(answers, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n", encoding="utf-8")
    # rehearsal finding #1: repeat --lane/--type on the --resolve re-entry
    out_c, ms_c = ctx.py("kunglao-init.py", str(ctx.ws),
                         "--lane", ctx.state.lane, "--type", ctx.state.type_,
                         "--resolve", str(answers_path))
    status_c = model.adjudicate("C1-init-resolved", out_c.rc)
    detail.update({"sub_resolve_rc": out_c.rc,
                   "sub_resolve_status": status_c,
                   "answers_file": str(answers_path),
                   "scaffolded": sorted(
                       p.name for p in ctx.ws.glob("*") if p.is_file())})
    # #460 intake probe battery (the instrument face): after the
    # resolved init, run die-probe + apkid-prescan over the STAGED
    # entry — probe features exist from run #1, feeding the mined
    # feature table (the EX-5 re-evaluation substrate). An instrument:
    # the sub-step rc rides the detail and NEVER changes the C1 verdict.
    total_ms = ms_a + ms_c
    if status_c == model.PASS:
        entry = _staged_entry(Path(ctx.state.task_dir))
        if entry is not None:
            out_b, ms_b = ctx.py("intake_battery.py", str(ctx.ws), entry)
            total_ms += ms_b
            detail.update({"sub_battery_rc": out_b.rc,
                           "battery_ms": ms_b,
                           "battery_entry": entry})
        else:
            detail["battery_skipped"] = "no declared workspace entry"
    final = model.PASS if (status_a == model.PASS and
                           status_c == model.PASS) else (
        model.BLOCKED if model.BLOCKED in (status_a, status_c)
        else model.FAIL)
    return _record(ctx, "C1", "init", final, out_c.rc, out_c,
                   total_ms, detail, [answers_path])


def checkpoint_c2(ctx: RunContext) -> model.CheckpointResult:
    out, ms = ctx.py("hook_activation.py", str(ctx.ws), "--wire-up")
    status = model.adjudicate("C2-hooks", out.rc)
    selfcheck_ok = "PASS" in out.stdout
    if status == model.PASS and not selfcheck_ok:
        status = model.FAIL
    try:
        sweep = _hook_sweep(ctx)
    except FileNotFoundError as exc:
        return _record(ctx, "C2", "hooks", model.BLOCKED, out.rc, out, ms,
                       {"error": str(exc), "stop_class": "hooks-not-deployed"})
    sweep_clean = all(not s["import_errors"] for s in sweep)
    if status == model.PASS and not sweep_clean:
        status = model.FAIL
    return _record(ctx, "C2", "hooks", status, out.rc, out, ms,
                   {"selfcheck_pass_lines": selfcheck_ok,
                    "sweep": sweep, "sweep_clean": sweep_clean})


def checkpoint_c3(ctx: RunContext) -> model.CheckpointResult:
    total_ms = 0
    outs: list[tuple[str, model.CmdOutcome]] = []
    for args in (("--heartbeat-on",),
                 ("--heartbeat-on", "--loop-registered",)):
        out, ms = ctx.py("hook_activation.py", str(ctx.ws), *args)
        total_ms += ms
        outs.append((args[-1], out))
        if model.adjudicate("C3-heartbeat", out.rc) != model.PASS:
            return _record(ctx, "C3", "heartbeat", model.FAIL, out.rc, out,
                           total_ms, {"failed_step": args[-1]})
    out_tick, ms = ctx.py("heartbeat_tick.py", str(ctx.ws))
    total_ms += ms
    degraded = [e for e in ("module_emit", "NameError")
                if e in out_tick.stderr]
    hb_file = ctx.ws / "runs" / ".heartbeat.json"
    # #450: a FIRST tick legitimately returns rc=1 with the
    # waiting-for-second-tick continuity reason (#415 semantics: entry
    # needs >=2 ticks; continuity is adjudicated at C5 after the second
    # tick). The reason lives in the TICK REPORT ARTIFACT
    # (ws/runs/.heartbeat-tick.json -> heartbeat.stderr), NOT the tick
    # process's own stderr (the child's stderr is captured into the
    # report, never forwarded — reviewer-450-1's decisive finding).
    waiting_second = False
    tick_report = ctx.ws / "runs" / ".heartbeat-tick.json"
    if out_tick.rc == 1 and tick_report.is_file():
        try:
            import json as _json
            _hb = _json.loads(
                tick_report.read_text(encoding="utf-8")).get("heartbeat", {})
            waiting_second = (
                _hb.get("rc") == 1
                and "wait for the SECOND tick" in (_hb.get("stderr") or ""))
        except (OSError, ValueError):
            waiting_second = False
    ok = ((model.adjudicate("C3-heartbeat", out_tick.rc) == model.PASS
           or waiting_second)
          and not degraded and hb_file.is_file())
    return _record(ctx, "C3", "heartbeat",
                   model.PASS if ok else model.FAIL, out_tick.rc, out_tick,
                   total_ms,
                   {"degraded_markers": degraded,
                    "waiting_second_tick": waiting_second,
                    "heartbeat_state": str(hb_file),
                    "heartbeat_state_exists": hb_file.is_file(),
                    "steps": [a for a, _ in outs]})


def checkpoint_c4(ctx: RunContext) -> model.CheckpointResult:
    out, ms = ctx.console("check-stale")
    status = model.adjudicate("C4-entry", out.rc)
    envelope = model.parse_last_json(out.stdout) or {}
    if status == model.PASS and envelope.get("status") != "current":
        status = model.FAIL
    return _record(ctx, "C4", "entry", status, out.rc, out, ms,
                   {"envelope": envelope})


def checkpoint_c5(ctx: RunContext) -> model.CheckpointResult:
    # honest 5m wait ONCE for the second tick (no script-side override
    # hook exists in liveness_policy — see TICK_WAIT_SECONDS_DEFAULT)
    ctx.sleep_fn(ctx.state.tick_wait_seconds)
    out_tick, ms = ctx.py("heartbeat_tick.py", str(ctx.ws))
    tick_status = model.adjudicate("C5-second-tick", out_tick.rc)
    if tick_status != model.PASS:
        return _record(ctx, "C5", "analysis", model.FAIL, out_tick.rc,
                       out_tick, ms, {"failed_step": "second-tick"})
    out, ms2 = ctx.console("analysis")
    status = model.adjudicate("C5-analysis", out.rc)
    stop = model.classify_analysis_rc(out.rc)
    return _record(ctx, "C5", "analysis", status, out.rc, out, ms + ms2,
                   {"stop_class": stop or ("none" if status == model.PASS
                                           else "unexpected-rc"),
                    "second_tick_rc": out_tick.rc})


def checkpoint_c6_pre(ctx: RunContext) -> model.CheckpointResult:
    import yaml

    total_ms = 0
    detail: dict = {}
    # C6-pre-1: goal-operationalization FROM the verbatim anchors
    doc = build_goal_op_doc(ctx.state.anchors)
    goal_op = ctx.ws / "goal-operationalization.yaml"
    goal_op.write_text(
        _canonical_dump(doc),
        encoding="utf-8")
    out_g, ms_g = ctx.py("goal_operationalization.py", str(goal_op))
    total_ms += ms_g
    status_g = model.adjudicate("C6-goal-op", out_g.rc)
    detail["goal_op_status"] = status_g
    if status_g != model.PASS:
        return _record(ctx, "C6", "pre", model.FAIL, out_g.rc, out_g,
                       total_ms, detail, [goal_op])
    # C6-pre-2: primary_questions into task_spec.yaml
    spec_path = ctx.ws / "task_spec.yaml"
    spec = (yaml.safe_load(spec_path.read_text(encoding="utf-8"))
            if spec_path.is_file() else None) or {}
    existing = {q.get("id") for q in (spec.get("primary_questions") or [])}
    spec.setdefault("primary_questions", [])
    _resolve_claims(ctx.ws / "task_spec.yaml")
    for question in PRIMARY_QUESTIONS:
        if question["id"] not in existing:
            spec["primary_questions"].append(dict(question))
    spec_path.write_text(
        _canonical_dump(spec),
        encoding="utf-8")
    _merge_unit_tools(ctx.ws, Path(ctx.state.task_dir) / "task.yaml")
    ctx.mcp_prefixes = tuple(_arm_mcp_supply(
        ctx, Path(ctx.state.task_dir) / "task.yaml"))
    # C6-pre-3: claims C-004/C-005 into claim-register.yaml
    register = ctx.ws / "claim-register.yaml"
    reg_doc = (yaml.safe_load(register.read_text(encoding="utf-8"))
               if register.is_file() else None) or {}
    reg_ids = {str(c.get("id")) for c in reg_doc.get("claims") or []}
    reg_doc.setdefault("claims", [])
    for claim in CLAIM_APPENDS:
        if claim["id"] not in reg_ids:
            reg_doc["claims"].append(dict(claim))
    register.write_text(
        _canonical_dump(reg_doc), encoding="utf-8")
    # C6-pre-4 mechanical: env_check → OVERALL=PASS; decide → DISPATCH
    out_e, ms_e = ctx.py("env_check.py", str(ctx.ws))
    total_ms += ms_e
    status_e = model.adjudicate("C6-env-check", out_e.rc)
    overall_ok = "OVERALL: PASS" in out_e.stdout or "OVERALL=PASS" in out_e.stdout
    detail.update({"env_check_status": status_e,
                   "env_overall_pass": overall_ok})
    if status_e != model.PASS or not overall_ok:
        return _record(ctx, "C6", "pre", model.FAIL, out_e.rc, out_e,
                       total_ms, detail, [goal_op, register, spec_path])
    out_d, ms_d = ctx.py("convergence_check.py", str(ctx.ws), "--json")
    total_ms += ms_d
    status_d = model.adjudicate("C6-dispatch", out_d.rc)
    decision, _doc = _decide(out_d)
    detail.update({"decide_status": status_d, "decision": decision})
    audit.emit_convergence_decision(str(ctx.ws), decision, rc=out_d.rc)
    if status_d != model.PASS or decision not in ("DISPATCH",
                                                  "DISPATCH_VERIFIER"):
        return _record(ctx, "C6", "pre",
                       model.BLOCKED if status_d == model.PASS else model.FAIL,
                       out_d.rc, out_d, total_ms, detail,
                       [goal_op, register, spec_path])
    out_p, ms_p = ctx.py("priority_ratio.py", str(ctx.ws), "--json")
    total_ms += ms_p
    top = _top_claim(out_p)
    detail.update({"priority_top_claim": top})
    if not top and _no_open_claims(ctx):
        # the machine's delivery face: all claims closed, PQs PROVEN —
        # no dispatchables is the terminal state, not a ranking failure
        detail["delivered"] = True
        return _record(ctx, "C6", "pre", model.PASS, 0, None, total_ms,
                       detail, [goal_op, register, spec_path])
    ok = model.adjudicate("C6-pre", out_p.rc) == model.PASS and bool(top)
    return _record(ctx, "C6", "pre", model.PASS if ok else model.FAIL,
                   out_p.rc, out_p, total_ms, detail,
                   [goal_op, register, spec_path])


def _rank_dispatchable(ctx: RunContext) -> tuple[list[str],
                                                  model.CmdOutcome | None, int]:
    """#459: ALL dispatchable claims in rank order (the tick dispatches up
    to max-parallel of them). Returns (claims, failed_outcome, ms);
    failed_outcome is set when ranking failed or produced nothing."""
    out, ms = ctx.py("priority_ratio.py", str(ctx.ws), "--json")
    ok = model.adjudicate("C6-loop", out.rc) == model.PASS
    claims = _ranked_claims(out) if ok else []
    return claims, (None if ok and claims else out), ms


# #539 WS1 / #545 WS2: the dispatch arm context — the recipe/verif/tier
# the launch face records on every envelope (ONE source for the dispatch
# meta and the sampler's arm_context so the keyed read matches the keyed
# write exactly).
_DISPATCH_ARM_CONTEXT = {"context_recipe": "facts_snapshot",
                         "verification_mode": "none", "tier": 1}


def _pooled_or_flat(store, counts: dict[str, int],
                    ws: str) -> dict[str, float]:
    """#524 item 5: settled dispatch rows feed the META-ARM hierarchical
    pool (strong shrinkage + fingerprint tempering); the declaration
    counts remain the no-outcome / pooling-failure face."""
    settled_rows = [r for r in store.observations()
                    if isinstance(r, dict) and r.get("credit") is not None]
    try:
        from rlvr import meta_arms as _ma
        fp = _ma.env_fingerprint(ws)
        # #523 G2 K2: the settled filter wraps the pool — extreme
        # posteriors floor to the exploration minimum (zero-info skip)
        pooled = _settled_filtered_prior(settled_rows, sorted(counts), fp)
        return {fam: pooled.get(fam, float(counts[fam]))
                for fam in sorted(counts)}
    except Exception:  # noqa: BLE001 — pooling is an upgrade, not a gate
        return {fam: float(n) for fam, n in sorted(counts.items())}


def _cold_seed_prior(ws, registered: list[str]) -> dict[str, float]:
    """WS3 (#544): a fresh workspace's first dispatch rides the
    intake-seeded proposal means instead of the flat 1.0 face when a
    FULL-coverage llm-prior/1 doc exists; partial coverage or any read
    failure fails open to the historical uniform face (the determinism
    wall keeps the wall)."""
    prior = {fam: 1.0 for fam in registered}
    try:
        from rlvr import priors as _p3
        seeded = _p3.intake_prior_weights(ws, allowed=registered)
        if seeded:
            prior = {fam: float(seeded[fam]) for fam in registered}
    except Exception as exc:  # noqa: BLE001 — fail-open, but loud (#275)
        from kunglao_log import warn
        warn("e2e.cold_seed_prior",
             f"{type(exc).__name__}: {exc} (fail-open: uniform proposal)")
    return prior


def _sampler_extras(ws, prior: dict) -> dict:
    """The #460/#461/#545 optional sampler kwargs, each fail-open to its
    pre-wiring shape (a broken extra never breaks the loop): the
    predict-before-try feature prior (flag-gated), the option-death
    verdicts, the cross-task warm-start pools (#545), and the keyed
    consumption arm context (#545 — the same recipe/verif/tier the
    dispatch meta records, so the keyed read matches the keyed write)."""
    kwargs: dict = {}
    try:
        from rlvr import feature_prior as _fp
        if _fp.enabled():
            features = _fp.features_from_workspace(ws)
            if features:
                kwargs = {"features": features,
                          "feature_table": _fp.default_table_path(ws)}
    except Exception as _exc:  # noqa: BLE001 — fail-open at the seam
        kunglao_log.warn("e2e.feature_prior",
                         f"{type(_exc).__name__}: {_exc}")
    try:
        from rlvr import termination as _t461
        _death = _t461.verdicts(ws, prior.keys())
    except Exception as _exc:  # noqa: BLE001 — fail-open at the seam
        kunglao_log.warn("e2e.termination", f"{type(_exc).__name__}: {_exc}")
        _death = {}
    if _death:
        kwargs["death"] = _death
    try:
        from rlvr import strategy_store as _ss
        pools = _ss.warm_pools(ws, prior.keys())
        if pools:
            kwargs["warm_pools"] = pools
    except Exception as _exc:  # noqa: BLE001 — fail-open at the seam
        kunglao_log.warn("e2e.warm_pools", f"{type(_exc).__name__}: {_exc}")
    kwargs["arm_context"] = dict(_DISPATCH_ARM_CONTEXT)
    return kwargs


def _sample_envelope_family(ws, require_family: str | None = None
                            ) -> tuple[str, dict | None]:
    """Kernel W4 (issue 462): DTS call site 2 at envelope synthesis.

    The P_LLM x Q draw (``rlvr.q_cells.sample_method_family``) picks the
    envelope's method_family when the run declares none: candidates are
    the workspace's DECLARED families — q-cell DISPATCH rows only (the
    shared proposal-channel definition: outcome data never enters any
    prior; the e2e face reads no settled ledger), INTERSECTED with the
    #432 registry: a retired token must never ride the prior again, or
    the fail-closed vocabulary gate would lockstep-reject every dispatch
    in the workspace — with a share prior; a workspace with no declaration
    history proposes uniformly over the registered vocabulary (the mined
    proposal set). rng = ``q_cells_seed_state`` — the sample moves when
    evidence moves or the round advances (#251; a re-dispatched claim
    therefore re-samples — recorded decision, the #251 contract), never
    on a wall clock. Day one the posteriors are the wide Beta(1,1) and
    the draw degenerates to the pure proposal prior; banked credits (the
    W5 settlement feed) make Q the learned adjustment. Fail-open: any
    sampler failure leaves the envelope undeclared (the byte-compatible
    v1 shape) and returns no receipt — a broken kernel must never break
    the dispatch loop.

    #545 WS2: the cross-task posterior store's LAMBDA-tempered anchor
    pools ride the sampler (warm start — a second workspace on a known
    family starts non-flat), and ``arm_context`` keys the cell read at
    the 4-dim arm_key (keyed consumption — the same recipe/verif/tier
    the dispatch meta below records). ``require_family`` injects a
    declared family into the candidates at the mean proposal share
    (never zero — the declared proposal is the strongest proposal
    signal) so the declared-ride receipt names every candidate with its
    P_LLM weight."""
    try:
        import method_families
        from rlvr import q_cells
        from rlvr import state as rlvr_state
        store = q_cells.default_store(ws)
        registered = sorted(method_families.registered_tokens())
        counts: dict[str, int] = {}
        for row in store.observations():
            if not isinstance(row, dict) \
                    or str(row.get("source") or "") != "dispatch":
                continue  # outcome rows never enter any prior
            fam = str(row.get("method_family") or "").strip()
            if fam and fam in registered:
                counts[fam] = counts.get(fam, 0) + 1
        if counts:
            prior = _pooled_or_flat(store, counts, str(ws))
        else:
            if not registered:
                return "", None
            prior = _cold_seed_prior(ws, registered)
        if require_family and require_family not in prior:
            vals = list(prior.values())
            prior[require_family] = (sum(vals) / len(vals)) if vals else 1.0
        rng, _round = q_cells.q_cells_seed_state(ws)
        kwargs = _sampler_extras(ws, prior)
        receipt = q_cells.sample_method_family(
            rlvr_state.snapshot(ws), prior, store, rng=rng, **kwargs)
        return str(receipt["family"]), receipt
    except Exception as exc:  # noqa: BLE001 — telemetry, never the loop
        from kunglao_log import warn  # canonical warn: rate-limited
        warn("e2e.envelope_sampler",
             f"{type(exc).__name__}: {exc} (fail-open: envelope left "
             f"undeclared)")
        return "", None


def _launch_dispatch(ctx: RunContext, claim: str, dispatched: set[str]
                     ) -> tuple[model.DispatchRequest | None, object]:
    """Launch phase (#459) — MAIN THREAD ONLY: mark the claim, mint the
    prompt + envelope, emit method_family, and emit the ATTEMPT row (via
    the face, so every wave's attempts land in launch order before any
    act executes). Returns (request, face_handle); request None = the
    claim is already in flight from an earlier tick."""
    if claim in dispatched:
        return None, None
    dispatched.add(claim)
    # K1 wiring (matrix4): the per-key attempt ladder — every launch
    # of this claim-key climbs one rung of the Luby sequence, so a
    # timed-out re-dispatch earns MORE room, not the same ceiling.
    attempt = ctx.attempts.get(claim, 0)
    ctx.attempts[claim] = attempt + 1
    ladder_timeout_s = _luby_timeout_s(attempt)
    # kernel-facing hook (audit §4): the envelope's method_family is the
    # declared proposal when the run carries one, else the DTS-sampled
    # draw (W4, issue 462) — the sampled family rides the envelope AND
    # the stream records it with its sampler receipt.
    method_family = getattr(ctx.state, "method_family", "") or ""
    declared = bool(method_family)
    receipt: dict | None = None
    if not method_family:
        method_family, receipt = _sample_envelope_family(ctx.ws)
    else:
        # #545 WS2: a declared family no longer skips the sampler
        # silently — the score face still runs (the receipt's candidates
        # carry every candidate with its P_LLM weight, the declared
        # family injected at the mean share), the DECLARED family wins
        # the envelope, and the receipt records propensity 1.0 (the
        # declared proposal IS the behavior policy: deterministic, so
        # π = 1 is the correct OPE re-weighting). The sampler's own draw
        # is advisory here — the run's declaration is the decision.
        _mf, receipt = _sample_envelope_family(
            ctx.ws, require_family=method_family)
        if declared and receipt is None:
            # the sampler is down — the minimal honest record still
            # rides: π = 1.0 and the declared candidate, never an
            # envelope-less OPE gap
            receipt = {"family": method_family, "declared": True,
                       "candidates": {method_family: {
                           "p_llm": 1.0, "alpha": 1.0, "beta": 1.0,
                           "theta": 1.0, "weight": 1.0}}}
    # #539 WS1: the v2 action tuple — action_type dispatch (the worker
    # act), context recipe = the facts-snapshot assembly this prompt
    # actually ships, verification_mode none (verification is a SEPARATE
    # act, never bundled into the maker)
    dispatch_meta: dict = {
        "version": 2, "claim": claim,
        "tools": ["grep", "python3"],
        "agent": "kunglao-worker",
        "action_type": "dispatch",
        **_DISPATCH_ARM_CONTEXT}
    if method_family:
        dispatch_meta["method_family"] = method_family
    prompt_file = Path(ctx.state.evidence_dir) / f"dispatch-prompt-{claim}.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(
        json.dumps({"kunglao_dispatch": dispatch_meta})
        + f"\n\nfacts-snapshot: {ctx.ws}/facts\nclaim: {claim}\n\n"
        "worker contract (from #473 live evidence rounds 5-7A):\n"
        "1. Pin facts INCREMENTALLY — the moment a finding is established "
        "(mapped structure, a constant with partial verification, decoded "
        "case semantics) write facts/F<NNN>.md with boundary_type: "
        "positive_observation. Do NOT batch facts at the end; final numeric "
        "claims UPGRADE earlier facts rather than waiting for full "
        "verification. An act that times out with zero facts is a failed "
        "act.\n"
        "2. End your final message with a line 'STATUS: DONE' (or 'STATUS: "
        "BLOCKED' with the reason) so the orchestrator parses your outcome "
        "precisely.\n"
        f"3. ACT BUDGET: this act is KILLED at {ladder_timeout_s}s — no "
        "extension, no in-act retry (the subprocess cap is external). "
        "Schedule accordingly: pin each fact the moment it is established, "
        "write the deliverable before 70% of the budget, and END with "
        "STATUS: DONE (or STATUS: BLOCKED + reason) well before the cap. "
        "An act killed at the cap banks zero facts credit.\n",
        encoding="utf-8")
    # #518 PR-2 (RC6, W1): open the pending q-cell observation at the
    # dispatch ALLOW-tail seam — the sampler's fold gets its dispatch
    # row and the settlement gets its match target. Fail-open telemetry:
    # the audit verdict found every envelope frozen at Beta(1,1) because
    # this write site was never wired (architect audit 2026-10-04).
    try:
        from rlvr import meta_arms as _ma
        _fp = _ma.env_fingerprint(str(ctx.ws), Path(ctx.repo))
    except Exception:  # noqa: BLE001 — telemetry never breaks dispatch
        _fp = None
    qc_mod = _load_repo_module(ctx.repo, "rlvr.q_cells")
    qc_mod.record_dispatch_observation(
        str(ctx.ws), prompt_file.read_text(encoding="utf-8"),
        envelope_meta=({"method_family": method_family,
                        "action_type": "dispatch",
                        **_DISPATCH_ARM_CONTEXT}
                       if method_family else None),
        claim=claim, fingerprint=_fp)
    # #524 item 1 + #545 WS2: the propensity rides the receipt — the
    # DR-OPE record. SAMPLER receipts carry the MC propensity; a
    # DECLARED proposal is the behavior policy itself (deterministic —
    # π = 1.0, correctly re-weighted for OPE), no longer an envelope-less
    # skip.
    try:
        if method_family and receipt is not None:
            if declared:
                receipt["propensity"] = 1.0
                receipt["declared"] = True
            else:
                from rlvr import meta_arms as _ma2
                _rows = [r for r in qc_mod.JSONLQStore(
                    str(ctx.ws)).observations() if isinstance(r, dict)]
                _fams = sorted({str(r.get("method_family")) for r in _rows
                                if r.get("method_family")} | {method_family})
                receipt["propensity"] = round(_ma2.mc_propensity(
                    _rows, method_family, _fams), 4)
            if _fp:
                receipt["fingerprint"] = _fp
    except Exception as exc:  # noqa: BLE001 — bonus, never a gate
        kunglao_log.warn("e2e.propensity", f"{type(exc).__name__}: {exc}")
    # the emit rides AFTER the propensity block: the receipt mutation
    # post-emit never reached the durable audit row (the round-1 G3
    # envelopes carry candidates but no propensity — the DR-OPE record
    # face was silently broken)
    if method_family:
        audit.emit_method_family(str(ctx.ws), claim, method_family,
                                 envelope=receipt)
    try:
        ir2 = _load_repo_module(ctx.repo, "rlvr.incremental_reward")
        ir2.record_launch(str(ctx.ws), claim,
                          action_key=method_family or "unattributed",
                          propensity=(receipt or {}).get("propensity"))
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks dispatch
        kunglao_log.warn("e2e.record_launch", f"{type(exc).__name__}: {exc}")
    request = model.DispatchRequest(
        claim=claim, workspace=str(ctx.ws),
        prompt_file=str(prompt_file), run_id=ctx.state.run_id,
        method_family=method_family or None,
        timeout_s=ladder_timeout_s,
        mcp_prefixes=getattr(ctx, "mcp_prefixes", ()) or ())
    return request, ctx.face.launch_dispatch(request)


def _land_dispatch(ctx: RunContext, claim: str, act: object,
                   dispatched: set[str], detail: dict) -> None:
    """Landing phase (#459) — MAIN THREAD ONLY: record the act + per-act
    rollback. #456 bug-2: a BLOCKED/TIMEOUT/ERROR act frees THAT claim
    only — without the discard the loop skips re-dispatch forever and
    only the idle circuit-breaker can end the run (round-3/round-4 fate).
    A timeout on one act never touches the other claims of the wave."""
    ctx.acts.append(act.to_dict())
    detail["acts"].append(act.to_dict())
    if act.outcome in ("BLOCKED", "TIMEOUT", "ERROR"):
        dispatched.discard(claim)
    # #523 G2 K4 (RC3): a SETTLED act releases its in-flight key whether
    # the promotion later succeeds or not — the settlement itself is the
    # completion signal (the success-forever key pinned re-decisions to a
    # silent no-op, burning budget in the P2 stall shape). The plain and
    # the V: forms both release; re-dispatch remains possible, the pin is
    # gone.
    _settle_dispatch_outcome(ctx, claim, act)
    if act.outcome == "DISPATCHED":
        dispatched.discard(claim)
        dispatched.discard("V:" + claim)


def _facts_citing(ws, claim: str) -> int:
    """Fact files whose frontmatter cites `claim` (claim_id / claim_ids)
    — the fact-production signal for the continuous credit. Cheap
    substring scan; malformed files count as 0 (fail-open)."""
    try:
        n = 0
        for f in (Path(ws) / "facts").glob("*.md"):
            try:
                head = f.read_text(encoding="utf-8",
                                   errors="replace")[:2000]
            except OSError:
                continue
            if str(claim) in head:
                n += 1
        return n
    except OSError:
        return 0


def _settle_dispatch_outcome(ctx: RunContext, claim: str,
                             act: object) -> None:
    """#518 PR-2 (RC6, W2+W3): bank the act's outcome credit into the
    q cell its dispatch opened, and feed a TIMEOUT act to the obstacles
    registry (the termination floor's input — repeat-offender families
    decay with zero sampler changes). Credit is the per-act ladder's
    v1 shape: DISPATCHED=1.0, every failure class=0.0 (the #433 ladder
    refinement rides the promotion path, not here). Telemetry posture:
    fail-open, never an exception into the landing path."""
    try:
        qc = _load_repo_module(ctx.repo, "rlvr.q_cells")
        # #524 item 2: continuous credit — binary floor + fact-production
        # signal (hindsight: a failed act that produced retained facts
        # banks partial credit; a success with zero facts banks only
        # half). Cost (duration_ms) is already in the dispatch_result
        # audit row — normalization happens at analysis time, the banked
        # value stays in [0,1].
        _n_facts = _facts_citing(ctx.ws, claim)
        _bin = 1.0 if act.outcome == "DISPATCHED" else 0.0
        credit = min(1.0, _bin * 0.5 + 0.5 * min(1.0, _n_facts / 2.0))
        # #539 PR-1: the transition row — s from the launch stash, Φ(s′)
        # computed now, r_incr = ALPHA·ΔΦ − LAMBDA·cost, r_settle = the
        # ladder credit above. The cost face: duration_ms rides the act's
        # audit row; wall seconds serve when it is absent.
        t_row = None
        try:
            ir = _load_repo_module(ctx.repo, "rlvr.incremental_reward")
            # G3-matrix fix: ActRecord carries duration in DETAIL
            # (claim/mode/outcome/detail) — the first wiring read a
            # phantom act.duration_ms and every TIMEOUT row banked
            # r_incr=0.0 instead of the -cost term
            _dur_ms = (act.detail or {}).get("duration_ms") \
                if isinstance(act.detail, dict) else None
            t_row = ir.append_transition(
                str(ctx.ws), claim, str(act.outcome),
                status=str(getattr(act, "mode", "") or ""),
                facts=_n_facts,
                seconds=float(_dur_ms or 0) / 1000.0,
                r_settle=credit)
        except Exception as exc:  # noqa: BLE001 — telemetry
            kunglao_log.warn("e2e.transition",
                             f"{type(exc).__name__}: {exc}")

        def _phi_delta_of(row) -> float | None:
            """Φ(s′) − Φ(s) off the captured transition row — the #548
            tiebreaker's one carried field (the store row keeps one
            field; no new machinery)."""
            try:
                return round(float(row.get("s_prime_phi"))
                             - float(row.get("phi_before")), 6)
            except (TypeError, ValueError, AttributeError):
                return None

        _phi_delta = _phi_delta_of(t_row)
        res = qc.observe_settlement(str(ctx.ws), claim, credit,
                                    phi_delta=_phi_delta)
        if res.get("matched") and res.get("appended"):
            # #524 item 3: censoring made visible — a TIMEOUT is
            # right-censored (unknown-not-failed), recorded on the
            # settlement row for KM analysis; the arm posterior still
            # counts it as failure (time is cost — expert-adjudicated)
            audit.emit_posterior_update(
                str(ctx.ws), str(res.get("method_family") or claim),
                {"credit": credit,
                 "censored": act.outcome == "TIMEOUT",
                 "facts_citing": _n_facts})
            # #545 WS2: the cross-task store row — keyed by the
            # dispatch's arm_key, holdout-filtered BEFORE append
            # (strategy_store.append_store_row), fail-open telemetry
            # (a store failure never breaks settlement)
            try:
                _ss = _load_repo_module(ctx.repo, "rlvr.strategy_store")
                _ss.append_store_row(
                    str(ctx.ws),
                    method_family=str(res.get("method_family") or ""),
                    status=str(act.outcome),
                    credit=credit,
                    censored=act.outcome == "TIMEOUT",
                    facts_citing=_n_facts,
                    propensity=(t_row or {}).get("propensity"),
                    phi_delta=_phi_delta,
                    dispatch_id=claim,
                    arm_key=res.get("arm_key"),
                    fingerprint=res.get("fingerprint"))
            except Exception as exc:  # noqa: BLE001 — telemetry
                kunglao_log.warn("e2e.posterior_store",
                                 f"{type(exc).__name__}: {exc}")
        if act.outcome == "TIMEOUT":
            fam = str(res.get("method_family") or "unattributed")
            # evidence = the act's own execution record: the obstacles
            # validator demands a probe-execution marker (command/rc/
            # output), and a timed-out act genuinely has one
            ev_rel = f"runs/act-timeout-{claim}.md"
            ev_path = ctx.ws / ev_rel
            ev_path.parent.mkdir(parents=True, exist_ok=True)
            ev_path.write_text(
                f"command: claude -p dispatch-prompt-{claim}.md\n"
                f"exit=124 (timeout, CLAUDE_ACT_TIMEOUT_S exceeded)\n"
                f"observed: outcome={act.outcome} family={fam} "
                f"detail={json.dumps(act.detail, ensure_ascii=False)[:400]}\n",
                encoding="utf-8")
            _load_repo_module(ctx.repo, "rlvr.obstacles").record(
                str(ctx.ws), kind="other",
                cause=f"act-timeout: CLAUDE_ACT_TIMEOUT_S exceeded on "
                      f"{claim} (family {fam})",
                evidence_path=ev_rel,
                method_family=fam, claim=claim)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        from kunglao_log import warn  # noqa: PLC0415
        warn("_settle_dispatch_outcome", f"{type(exc).__name__}: {exc}")


def _posterior_drift_check(ctx: RunContext) -> None:
    """#518 PR-2 (W4): the frozen-posterior alarm — the open-loop
    signature the combat matrix exhibited silently (alpha=beta=1.0
    across every envelope). The q-cell store DEDUPES dispatch rows by
    (signature, family), so the honest signal is: the audit stream has
    seen >=3 kernel dispatch events (method_family_recorded) while the
    store has banked zero settlements. Named audit row, never an
    exception."""
    try:
        qc = _load_repo_module(ctx.repo, "rlvr.q_cells")
        obs = [r for r in qc.JSONLQStore(str(ctx.ws)).observations()
               if isinstance(r, dict)]
        settled = sum(1 for r in obs if r.get("credit") is not None)
        kernel_events = int(
            (audit.read_stats(str(ctx.ws)).get("categories") or {})
            .get("kernel", 0))
        if kernel_events >= 3 and settled == 0:
            audit.emit(str(ctx.ws), "orchestrator", "posterior_frozen",
                       detail={"kernel_events": kernel_events,
                               "settled": 0})
    except Exception as exc:  # noqa: BLE001 — alarm, never the producer
        from kunglao_log import warn  # noqa: PLC0415
        warn("_posterior_drift_check", f"{type(exc).__name__}: {exc}")


def _run_dispatch_act(ctx: RunContext, claim: str, dispatched: set[str],
                      detail: dict) -> model.CheckpointResult | None:
    """Synchronous single-act path (the pre-#459 seam the rollback tests
    pin): launch → execute → land in the caller's thread. Returns a
    terminal CheckpointResult on failure, None on success."""
    request, handle = _launch_dispatch(ctx, claim, dispatched)
    if request is None:
        return None  # already emitted; wait for the act to land
    act = ctx.face.run_dispatch(request, handle)
    _land_dispatch(ctx, claim, act, dispatched, detail)
    return None


def _dispatch_wave(ctx: RunContext, claims: list[str],
                   dispatched: set[str], detail: dict) -> None:
    """#459: launch up to max-parallel not-yet-dispatched acts (rank
    order), then WAIT for the whole wave to land and record each outcome.

    Budget guard is GLOBAL (#459 acceptance): it is consulted before
    EVERY launch — exhausted stops launching new acts but never abandons
    the already-launched in-flight ones (they still land + record). The
    `dispatched` set is mutated only here, in the main thread."""
    launched: list[tuple[model.DispatchRequest, object]] = []
    for claim in claims:
        if len(launched) >= _max_parallel_dispatch():
            break
        if not _guard_budget(ctx):
            break
        request, handle = _launch_dispatch(ctx, claim, dispatched)
        if request is not None:
            launched.append((request, handle))
    if not launched:
        return
    acts = llm_faces.run_dispatch_parallel(ctx.face, launched)
    for act in acts:  # landing order; ActRecord.claim correlates 1:1
        _land_dispatch(ctx, act.claim, act, dispatched, detail)


def _partial_claim_ids(ctx: RunContext) -> list:
    """#508: the DISPATCH_VERIFIER decision's own evidence — the claims
    whose facts are still awaiting verification. The probe counted those
    partials (that is WHY it decided DISPATCH_VERIFIER); the priority
    ranking skips PARKed claims, so the partials themselves are the
    verifier target source. Reuses the repo probe's partial set; the
    claim column is content-matched (F-token + C-token), order-preserving
    dedup. Fail-open: any error yields [] (the honest FAIL stands)."""
    try:
        cc = _load_repo_module(Path(ctx.repo), "convergence_check")
        partials = {str(p.get("fact")) for p in
                    cc._partial_facts(Path(ctx.ws))}
    except Exception:  # noqa: BLE001 — fail-open at the seam
        return []
    if not partials:
        return []
    idx = Path(ctx.ws) / "facts" / "_INDEX.md"
    if not idx.is_file():
        return []
    out: list = []
    for line in idx.read_text(encoding="utf-8",
                              errors="replace").splitlines():
        if "|" not in line:
            continue
        parts = [q.strip() for q in line.split("|") if q.strip()]
        fid = next((q for q in parts if re.match(r"F\d{3}", q)), None)
        if fid is None or not any(fid == p or p.startswith(fid)
                                  for p in partials):
            continue
        claim = next((q for q in parts
                      if re.fullmatch(r"C-\d{1,4}[a-z]?", q)), None)
        if claim and claim not in out:
            out.append(claim)
    return out


def _record_verify_launch(ctx: RunContext, claim: str,
                          variant: str) -> None:
    """#550: verify/red-team acts enter the SMDP ledger — the launch
    stash is action-type-scoped (never clobbers a pending dispatch
    stash for the same claim). Fail-open telemetry."""
    try:
        ir = _load_repo_module(ctx.repo, "rlvr.incremental_reward")
        ir.record_launch(str(ctx.ws), claim,
                         action_key=("verify:redteam"
                                     if variant == "redteam" else "verify"),
                         action_type="verify", variant=variant)
    except Exception as exc:  # noqa: BLE001 — telemetry, but loud (#275)
        kunglao_log.warn("e2e.verify_launch",
                         f"{type(exc).__name__}: {exc}")


def _record_verify_settle(ctx: RunContext, claim: str, act, variant: str,
                          verdict: str = "") -> None:
    """#550: close the verify/red-team transition — r_settle banks the
    verdict's credit (verified/CONFIRMED => 1.0, else 0.0); the Φ move
    from newly verified facts rides r_incr unchanged. Fail-open."""
    try:
        ir = _load_repo_module(ctx.repo, "rlvr.incremental_reward")
        _dur_ms = (act.detail or {}).get("duration_ms") \
            if isinstance(act.detail, dict) else None
        ir.append_transition(
            str(ctx.ws), claim, str(act.outcome), status=variant,
            facts=_facts_citing(ctx.ws, claim),
            seconds=float(_dur_ms or 0) / 1000.0,
            r_settle=ir.verify_credit(verdict),
            action_type="verify", variant=variant)
    except Exception as exc:  # noqa: BLE001 — telemetry, but loud (#275)
        kunglao_log.warn("e2e.verify_settle",
                         f"{type(exc).__name__}: {exc}")


def _run_verifier_act(ctx: RunContext, claim: str, dispatched: set[str],
                       detail: dict) -> model.CheckpointResult | None:
    """#484: DISPATCH_VERIFIER decisions finally act — a verifier face for
    the claim (maker-checker: verify, never make). Same rollback semantics
    as worker acts; single act (verification is light, no wave)."""
    vkey = f"V:{claim}"
    if vkey in dispatched:
        return None  # already verifying; wait for the act to land
    dispatched.add(vkey)
    prompt_file = Path(ctx.state.evidence_dir) / f"dispatch-prompt-V-{claim}.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(
        json.dumps({"kunglao_dispatch": {
            "version": 2, "claim": claim, "tier": 1,
            "agent": "kunglao-verifier",
            "action_type": "verify",
            "context_recipe": "facts_snapshot",
            "verification_mode": "replay_probe"}})
        + f"\n\nfacts-snapshot: {ctx.ws}/facts\nclaim: {claim}\n\n"
        "VERIFIER contract (maker-checker #484): you VERIFY, you never "
        "make. Read the claim's facts and artifacts, run the workspace's "
        "verification faces (replay_equivalence, oracle probes, byte-exact "
        "comparisons). When the claim answers a primary question under a "
        "reproduction-verified task, the controlled-comparison artifact "
        "MUST land as evidence/replay-<claim>.json (schema "
        "replay-equivalence/1, one matched pair minimum) — the engine's "
        "convergence face scans exactly that name; any other filename "
        "starves the reproduction gate. Write runs/verification-"
        f"{claim}.md with a frontmatter verdict (verified|refuted) plus "
        "evidence citations (file:line). NEVER write facts/F*.md. If a "
        "state file must change, mutate it ONLY via `python3 "
        "scripts/ws_yaml.py set|del <file> <dotted.path> <value>` — "
        "claim-register.yaml is single-writer (#516) and direct writes "
        "(cat/sed/python-open/Edit/Write) are refused by the write guard. "
        "End with STATUS: DONE or STATUS: BLOCKED.\n"
        f"ACT BUDGET: this act is KILLED at {llm_faces.CLAUDE_ACT_TIMEOUT_S}s "
        "— verify ONLY (never expand scope), write the verification file "
        "before 70% of the budget, and END before the cap. A verifier "
        "killed at the cap leaves the claim unverified and the loop "
        "blocked.\n",
        encoding="utf-8")
    request = model.DispatchRequest(
        claim=claim, workspace=str(ctx.ws),
        prompt_file=str(prompt_file), run_id=ctx.state.run_id,
        method_family=getattr(ctx.state, "method_family", "") or None)
    _record_verify_launch(ctx, claim, "verify")
    act = ctx.face.dispatch_act(request)
    ctx.acts.append(act.to_dict())
    detail["acts"].append(act.to_dict())
    if act.outcome in ("BLOCKED", "TIMEOUT", "ERROR"):
        _record_verify_settle(ctx, claim, act, "verify", verdict="")
        dispatched.discard(vkey)
        return None
    # verification landed → land the gate-conformant verify-note (#501:
    # the act's own record name, verification-<claim>.md, is invisible to
    # the gate's artifact matching), then attempt promotion through the
    # repo gate; a refusal is honest progress info, never fatal (#819
    # fail-closed)
    _land_verify_note(ctx, claim)
    _v = ""
    try:
        _note = (ctx.ws / "runs" / f"verification-{claim}.md"
                 ).read_text(encoding="utf-8", errors="replace")
        _m = re.search(r"^verdict:\s*(\S+)", _note, re.M)
        if _m:
            _v = _m.group(1)
    except OSError as exc:  # loud per #275 — a missing note settles 0.0
        kunglao_log.warn("e2e.verify_verdict",
                         f"{type(exc).__name__}: {exc} (settling 0.0)")
    _record_verify_settle(ctx, claim, act, "verify", verdict=_v)
    promote = promote_claims(ctx.repo, ctx.ws, [claim])
    detail.setdefault("promotions", []).append(
        {claim: promote.get("ok"), "promoted": promote.get("promoted"),
         "violations": promote.get("violations")})
    _maybe_redteam(ctx, claim, promote, dispatched, detail)
    return None


def _land_verify_note(ctx: RunContext, claim: str) -> None:
    """#501: mirror the act's verification record into the gate-conformant
    verify-note (runs/<claim>-verify-note.md). Honest mapping: verdict
    verified → Overall verdict passes; anything else (refuted/absent)
    writes no passes — no note at all without a record."""
    note = Path(ctx.ws) / "runs" / f"{claim}-verify-note.md"
    if (Path(ctx.ws) / "runs" / f"verify-redteam-{claim}.md").is_file():
        # #501 review MEDIUM: a landed red-team artifact must keep its
        # provenance order (gate: rt_m >= note_m). Rewriting the note on
        # resume would poison every subsequent promotion attempt — keep
        # the existing note instead.
        if note.is_file():
            return
    record = Path(ctx.ws) / "runs" / f"verification-{claim}.md"
    try:
        text = record.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    m = re.search(r"^verdict:\s*(\S+)", text, re.M)
    if m is None:
        return
    verdict = m.group(1).strip().lower()
    outcome = "passes" if verdict == "verified" else verdict
    note_text = (f"---\nclaim_id: {claim}\n"
            f"verifier-identity: e2e-verifier-act-{ctx.state.run_id}\n"
            f"record: runs/verification-{claim}.md\n---\n\n"
            f"# {claim} verify-note (mirror of the verifier act record)\n\n"
            f"The verifier act wrote verdict `{verdict}`; this note is the\n"
            f"gate-conformant mirror (identity distinct from any red-team\n"
            f"act by construction).\n\n## Overall verdict\n{outcome}\n")
    note.write_text(note_text, encoding="utf-8")


def _maybe_redteam(ctx: RunContext, claim: str, promote: dict,
                   dispatched: set[str], detail: dict) -> None:
    """#501: when promotion refused SOLELY for the missing red-team, fire
    the blind red-team act and retry promotion through the repo gate. A
    REFUTED verdict never promotes (#819) — the refutation rides the
    promotion trail instead."""
    violations = promote.get("violations") or []
    # trigger on BOTH the never-ran face AND the provenance-order face —
    # a resumed run may have an artifact that predates a rewritten note;
    # re-dispatching the act re-lands it with a fresh mtime (self-heal)
    needs_rt = promote.get("ok") is False and any(
        ("red-team" in str(v) and "never ran" in str(v))
        or ("predates" in str(v) and "redteam record" in str(v))
        for v in violations)
    if not needs_rt:
        return
    rtkey = f"RT:{claim}"
    if rtkey in dispatched:
        return
    dispatched.add(rtkey)
    prompt_file = (Path(ctx.state.evidence_dir)
                   / f"dispatch-prompt-RT-{claim}.md")
    prompt_file.write_text(
        json.dumps({"kunglao_dispatch": {
            "version": 1, "claim": claim, "tier": 1,
            "agent": "kunglao-redteam"}})
        + f"\n\nclaim: {claim}\n\n"
        "RED-TEAM contract (maker-checker #819): you are the ATTACKER — "
        "REFUTE the claim by deriving the answer independently from raw "
        "evidence. BLIND: never read facts/, notes/, verify-notes, or "
        f"runs/verification-{claim}.md. Construct your own adversarial "
        "inputs, compare byte-exact against the ground-truth artifacts, "
        "and report every divergence. WRITE the artifact "
        f"runs/verify-redteam-{claim}.md with: frontmatter "
        f"`claim: {claim}` and `verifier-identity: redteam-act-"
        f"{ctx.state.run_id}`, your attack narrative, and a final line "
        "`RED-TEAM VERDICT: CONFIRMED` (attacked, failed to refute) or "
        "`RED-TEAM VERDICT: REFUTED` or `RED-TEAM VERDICT: "
        "UNVERIFIED-WITH-GAP`. End with STATUS: DONE or STATUS: BLOCKED.\n",
        encoding="utf-8")
    request = model.DispatchRequest(
        claim=claim, workspace=str(ctx.ws),
        prompt_file=str(prompt_file), run_id=ctx.state.run_id,
        agent="kunglao-redteam",
        method_family=getattr(ctx.state, "method_family", "") or None)
    _record_verify_launch(ctx, claim, "redteam")
    act = ctx.face.dispatch_act(request)
    ctx.acts.append(act.to_dict())
    detail["acts"].append(act.to_dict())
    if act.outcome in ("BLOCKED", "TIMEOUT", "ERROR"):
        _record_verify_settle(ctx, claim, act, "redteam", verdict="")
        dispatched.discard(rtkey)
        return
    artifact = Path(ctx.ws) / "runs" / f"verify-redteam-{claim}.md"
    if not artifact.is_file():
        _record_verify_settle(ctx, claim, act, "redteam", verdict="")
        detail.setdefault("promotions", []).append(
            {claim: False, "redteam": "artifact-missing"})
        return
    retry = promote_claims(ctx.repo, ctx.ws, [claim])
    row = {claim: retry.get("ok"), "promoted": retry.get("promoted"),
           "violations": retry.get("violations")}
    # one read, one parse: the verdict feeds both the failure row and
    # the #550 settle credit (CONFIRMED banks 1.0)
    art = artifact.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"RED-TEAM VERDICT\s*[:\-]?\s*(\S+)", art,
                  re.IGNORECASE)
    verdict = m.group(1) if m else ""
    if retry.get("ok") is False:
        row["redteam"] = verdict or "unparsed"
    _record_verify_settle(ctx, claim, act, "redteam", verdict=verdict)
    detail.setdefault("promotions", []).append(row)


_STOP_DECISIONS = {"BLOCKED": "convergence-blocked", "PARK": "parked"}

# ---- #523 G2 K1: Luby restart schedule (Luby/Sinclair/Zuckerman 1993) ----
# The universal restart sequence 1,1,2,1,1,2,4,... replaces the fixed
# act timeout (the P1 death). Base unit reads the env so CI can pin
# it. The default is flat-parity 1800 (matrix4 wt1/wpl: matrix2's own
# baseline says 28-36min acts are normal — the ladder GROWS from
# today's behavior, 1800/1800/3600/7200..., never shrinks below it);
# the fast-discovery base stays env-selectable pending Kaplan-Meier
# hazard data (the intended feed per the design contract).
LUBY_BASE_S = int(os.environ.get("KUNGLAO_LUBY_BASE_S", "1800"))


def _luby_units(n: int) -> int:
    """The nth unit of the universal restart sequence (0-indexed):
    1,1,2,1,1,2,4,... — the classic SAT-solver formulation (Luby,
    Sinclair & Zuckerman 1993) mapped through luby(i) with i = n+1."""
    def _luby(i: int) -> int:
        for k in range(1, 30):
            if i == (1 << k) - 1:
                return 1 << (k - 1)
        k = 1
        while True:
            if (1 << (k - 1)) <= i < (1 << k) - 1:
                return _luby(i - (1 << (k - 1)) + 1)
            k += 1
    return _luby(n + 1)


def _luby_timeout_s(retry_count: int) -> int:
    """The act timeout for a claim's nth attempt: Luby(n) * base."""
    return _luby_units(max(0, retry_count)) * LUBY_BASE_S


def _maybe_expand(ctx: RunContext, dispatched: set[str],
                  detail: dict) -> None:
    """#546 WS4 wiring: the discovery-layer move. When the workspace's
    obstacle evidence reaches EXPAND_OBSTACLE_K and a tried family is
    termination-dead (BOTH sanctioned faces — the state snapshot's
    obstacle digest + the termination verdicts; rlvr.obstacles is
    never imported, the 396 freeze wall holds), spend ONE act per run
    generating novel attack hypotheses OUTSIDE the failed set. The
    frozen model generates (runs/expansion-hypotheses.json, schema
    expansion-hypotheses/1); rlvr.expansion.admit adjudicates
    (feature-keyed novelty — a renamed dead arm never spends the move);
    the receipt lands runs/expansion/E-<n>.json. The capability face:
    fail-open, never breaks the loop. Registry admission (making an
    admitted novel arm DISPATCHABLE through the #432 vocabulary gate)
    is the named next face on #546 — this move generates, adjudicates,
    and records; it does not yet mint registry tokens."""
    try:
        ex = _load_repo_module(ctx.repo, "rlvr.expansion")
        st = _load_repo_module(ctx.repo, "rlvr.state")
        term = _load_repo_module(ctx.repo, "rlvr.termination")
        import method_families

        snap = st.snapshot(str(ctx.ws))
        fams = sorted(method_families.registered_tokens())
        death = term.verdicts(str(ctx.ws), fams) if fams else {}
        trig = ex.trigger(snap, death)
        if trig is None:
            return
        if "EXPAND" in dispatched:
            return  # one discovery move per run (the budget face)
        dispatched.add("EXPAND")
        prompt_file = (Path(ctx.state.evidence_dir)
                       / "dispatch-prompt-EXPAND.md")
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(
            json.dumps({"kunglao_dispatch": {
                "version": 2, "claim": "EXPANSION", "tier": 1,
                "agent": "kunglao-worker",
                "action_type": "expand",
                "context_recipe": "facts_snapshot",
                "verification_mode": "none"}})
            + "\n\ndiscovery contract (#546): the tried families have "
            "collapsed. Generate "
            + str(ex.EXPAND_HYPOTHESES_N)
            + " NOVEL attack hypotheses that are NOT retries of the "
            "failed set under a new name — different mechanism, "
            "different feature shape. WRITE runs/expansion-hypotheses."
            "json (schema expansion-hypotheses/1): "
            '{\"hypotheses\": [{\"id\": \"h-1\", \"family\": '
            '\"your-novel-family-name\", \"features\": '
            "{\"lane\": \"...\", \"project_type\": \"...\", "
            "\"target_kind\": {\"language\": \"...\", "
            "\"entry_suffix\": \"...\"}}, "
            '\"p_llm\": 0.0}]}'  # the feature-table/1 vocabulary
            + " — one line of attack narrative per hypothesis. "
            "ACT BUDGET: this act is KILLED at "
            f"{llm_faces.CLAUDE_ACT_TIMEOUT_S}s — the hypotheses file "
            "lands before 70% of the budget. End with STATUS: DONE or "
            "STATUS: BLOCKED.\n",
            encoding="utf-8")
        request = model.DispatchRequest(
            claim="EXPANSION", workspace=str(ctx.ws),
            prompt_file=str(prompt_file), run_id=ctx.state.run_id,
            agent="kunglao-worker",
            method_family=getattr(ctx.state, "method_family", "") or None)
        audit.emit(str(ctx.ws), "orchestrator", "expansion_move",
                   claim="EXPANSION", detail={
                       "trigger": trig,
                       "collapsed_arms": trig["collapsed_arms"]})
        act = ctx.face.dispatch_act(request)
        ctx.acts.append(act.to_dict())
        detail["acts"].append(act.to_dict())
        if act.outcome in ("BLOCKED", "TIMEOUT", "ERROR"):
            dispatched.discard("EXPAND")  # a failed move may retry once
            return
        # adjudicate what the model generated, against the workspace's
        # own tried context (the anti-renaming wall: a hypothesis with
        # this instance's feature shape is a retry, novelty 0)
        fp: dict = {}
        try:
            from rlvr import feature_prior as _fpl
            fp = _fpl.features_from_workspace(str(ctx.ws)) or {}
        except Exception:  # noqa: BLE001 — fail-open at the seam
            fp = {}
        hyp_path = ctx.ws / "runs" / "expansion-hypotheses.json"
        try:
            doc = json.loads(hyp_path.read_text(encoding="utf-8"))
            hyps = doc.get("hypotheses") if isinstance(doc, dict) else None
            hyps = hyps if isinstance(hyps, list) else []
        except (OSError, ValueError):
            hyps = []
        if not hyps:
            kunglao_log.warn("e2e.expand_hypotheses", "no usable file")
            return
        ranked = ex.admit(hyps, [fp] if fp else [])
        ex.record_receipt(str(ctx.ws), trig, ranked,
                          [r["id"] for r in ranked])
        audit.emit(str(ctx.ws), "orchestrator", "expansion_result",
                   claim="EXPANSION",
                   detail={"admitted": [r["id"] for r in ranked],
                           "considered": len(hyps)})
        detail.setdefault("expansion", []).append(
            {"trigger": trig, "admitted": [r["id"] for r in ranked]})
    except Exception as exc:  # noqa: BLE001 — capability, never the loop
        kunglao_log.warn("e2e.maybe_expand",
                         f"{type(exc).__name__}: {exc}")


def _maybe_distill(ctx: RunContext, detail: dict) -> None:
    """Online distillation tick step: scan the workspace for miss
    signals (the worker's shelf-miss marker / an unknown-format probe
    failure), and when one fires with budget remaining, run ONE
    bounded distillation act through the LLM faces DIRECTLY (never
    _launch_dispatch — the kernel envelope sampler is not a consumer
    distillation may acquire), validate the act's report, run its
    candidates against the anchored sample bytes, and land satisfied
    candidates in the run-local tool shelf. At most one act per tick;
    every refusal/rejection lands its row; a scan failure is a
    rate-limited warn (the loop never breaks on the capability)."""
    # the engine (single source); resolve from the repo tree like every
    # runtime repo-module import (twin-resolution guard — no bare-path insert)
    od = _load_repo_module(ctx.repo, "online_distill")

    try:
        triggers = od.scan_triggers(ctx.ws)
    except Exception as exc:  # noqa: BLE001 — capability, never the loop
        from kunglao_log import warn
        warn("e2e.distill_scan", f"{type(exc).__name__}: {exc}")
        return
    if not triggers:
        return
    ws = ctx.ws
    trigger = triggers[0]
    state_before = od.ledger_state(ws)
    receipt = od.reserve_act(ws, trigger.token,
                             source_file=trigger.source_file,
                             sample_hint=trigger.sample_hint)
    trigger_detail = {"kind": trigger.kind, "token": trigger.token,
                      "sample_hint": trigger.sample_hint,
                      "source_file": trigger.source_file}
    if receipt is None:
        audit.emit_distill_result(
            str(ws), "attempt-refused", validated=False, phase="refused",
            refusal_reason=od.refuse_reason(ws, trigger.token),
            oracle=None, trigger_token=trigger.token)
        detail.setdefault("distill", []).append(
            {"trigger": trigger_detail, "refused": True})
        return
    attempt = receipt["attempt"]
    audit.emit_distill_attempt(
        str(ws), attempt, phase="dispatched", trigger=trigger_detail,
        budget={"per_run_used": receipt["per_run_used"],
                "per_run_budget": receipt["per_run_budget"],
                "hops_remaining": (int(state_before["hops_budget"])
                                   - int(state_before["hops_used"]))})
    # the act STARTS with formulation (issue 487): enumerate the problem
    # from the environment snapshot + obstacles, retrieve per facet,
    # record
    # the coverage matrix. Fail-open rider: a formulation failure is one
    # rate-limited warn and the act proceeds unformulated.
    form_doc: dict | None = None
    try:
        qf = _load_repo_module(ctx.repo, "query_formulation")
        form_doc = qf.formulate_and_retrieve(ws, trigger,
                                             repo=Path(ctx.repo))
    except Exception as exc:  # noqa: BLE001 — capability, never the loop
        from kunglao_log import warn
        warn("e2e.distill_formulate", f"{type(exc).__name__}: {exc}")
    # the audit face of the matrix: per-facet verdict + hit paths (the
    # full scored matrix rides the dispatch prompt); the tick detail
    # carries the compact formulation beside it (design: formulation +
    # coverage)
    coverage_detail = None
    formulation_detail = None
    if form_doc:
        _cov = form_doc.get("coverage") or {}
        coverage_detail = {
            "corpus": _cov.get("corpus"),
            "summary": _cov.get("summary"),
            "facets": [
                {"kind": f.get("kind"), "face": f.get("face"),
                 "query": f.get("query"), "verdict": f.get("verdict"),
                 "hits": [h.get("path") for h in f.get("hits") or []]}
                for f in _cov.get("facets") or []],
        }
        formulation_detail = [
            {"kind": f.get("kind"), "face": f.get("face"),
             "query": f.get("query")}
            for f in (form_doc.get("formulation") or {}).get("facets")
            or []]
    # mint the prompt + envelope (reserved non-register claim space)
    prompt_file = Path(ctx.state.evidence_dir) / f"dispatch-prompt-{attempt}.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(
        json.dumps({"kunglao_dispatch": {
            "version": 1, "claim": f"distill-{attempt}", "tier": 1,
            "tools": ["Read", "Grep", "Glob", "Bash", "WebSearch"],
            "agent": "kunglao-distill"}})
        + f"\ntoken: {trigger.token}\n"
        + (f"sample: {trigger.sample_hint}\n"
           if trigger.sample_hint else "")
        + ("\nProblem formulation (#487): retrieve PER FACET below — "
           "hit cards are validated starting points; corpus-lack facets "
           "are the web-face priorities.\n"
           + json.dumps({"facets": form_doc["formulation"]["facets"],
                         "coverage": form_doc["coverage"]},
                        sort_keys=True, ensure_ascii=False) + "\n"
           if form_doc else "")
        + "\nDistillation act: retrieve from the local re-library first"
          " (references/re-library/), then the web face (URL + access"
          " date recorded; never directly proven). Extract METHODS"
          " (methodology-first), discard case specifics. Recursive case"
          " expansion: depth <= 1, breadth <= 3, every hop budgeted."
          " Write runs/distill-candidates/" + attempt + "/report.json"
          " (schema distill-report/1) with candidates + their oracle"
          " declarations.\n",
        encoding="utf-8")
    request = model.DispatchRequest(
        claim=f"distill-{attempt}", workspace=str(ws),
        prompt_file=str(prompt_file), run_id=ctx.state.run_id,
        agent="kunglao-distill",
        tools=("Read", "Grep", "Glob", "Bash", "WebSearch"))
    # synchronous single-act chain, faces DIRECT (no sampler ride)
    request_launched = ctx.face.launch_dispatch(request)
    act = ctx.face.run_dispatch(request, request_launched)
    ctx.acts.append(act.to_dict())
    # validate the act's report
    attempt_dir = ws / od.REPORTS_DIRNAME / attempt
    report = od._read_json(attempt_dir / "report.json")
    if not isinstance(report, dict):
        audit.emit_distill_result(
            str(ws), attempt, validated=False,
            violations=["report missing or unreadable"], hops=0,
            coverage=coverage_detail)
        detail.setdefault("distill", []).append(
            {"attempt": attempt, "validated": False,
             "formulation": formulation_detail,
             "coverage": coverage_detail})
        return
    ok, violations = od.validate_report(ctx.repo, ws, report)
    hops = len(report.get("hops") or [])
    if not ok:
        audit.emit_distill_result(
            str(ws), attempt, validated=False, violations=violations,
            hops=0, coverage=coverage_detail)
        detail.setdefault("distill", []).append(
            {"attempt": attempt, "validated": False,
             "violations": violations, "formulation": formulation_detail,
             "coverage": coverage_detail})
        return
    od.commit_hops(ws, report)
    sample, source = od.resolve_sample(ws, trigger)
    oracle_out: dict = {"satisfied": False, "sample_source": source}
    if sample is not None:
        import hashlib
        sample_sha = hashlib.sha256(sample.read_bytes()).hexdigest()
        landed: list[str] = []
        for cand in report.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            decl = cand.get("oracle") or {}
            expect_rc, marker = od._expect_of(decl)
            outcome = od.run_candidate(
                attempt_dir / f"{cand.get('name')}.py", sample,
                expect_rc=expect_rc, expect_stdout_contains=marker)
            outcome["sample_sha256"] = sample_sha
            outcome["sample_source"] = source
            oracle_out = outcome
            got = od.land_candidate(ws, attempt_dir, report,
                                    str(cand.get("name")), outcome)
            if got:
                landed.append(str(got[0]))
                audit.emit_candidate_landed(
                    str(ws), attempt, str(cand.get("name")),
                    tool_path=str(got[0].relative_to(ws)),
                    capability=str(cand.get("capability") or ""))
    audit.emit_distill_result(
        str(ws), attempt, validated=True, violations=[], hops=hops,
        oracle=oracle_out, coverage=coverage_detail)
    detail.setdefault("distill", []).append(
        {"attempt": attempt, "validated": True, "hops": hops,
         "sample_source": source, "formulation": formulation_detail,
         "coverage": coverage_detail})


def _verdict_prompt(ctx: RunContext) -> str:
    """#513: the verdict act's full contract — inputs, schema skeleton,
    output path. A bare one-liner produced no file (combat wt1:
    BLOCKED verdict-missing with all claims PROVEN)."""
    ws = str(ctx.ws)
    return (
        "You are the verdict-scorer. Working directory is the analysis "
        f"workspace {ws}.\n"
        "READ these inputs:\n"
        f"- {ws}/task_spec.yaml (primary_questions[])\n"
        f"- {ws}/claim-register.yaml (claims: status, answers_question)\n"
        f"- {ws}/facts/_INDEX.md and the fact files it names\n"
        "\n"
        "WRITE the file "
        f"{ws}/evidence/verdict.json with EXACTLY this JSON shape:\n"
        "{\n"
        '  "_meta": {"source": "verdict-scorer", "schema_version": "v11", '
        '"queried_at": "<ISO8601>", "methodology": '
        '"task_spec.primary_questions coverage + fact-citation '
        'validity"},\n'
        '  "sample_sha256": "<sha256 of the workspace target if '
        'present, else null>",\n'
        '  "analysis_verdict": {\n'
        '    "complete": <true iff EVERY primary_question answered>,\n'
        '    "correct": <false if any contradiction>,\n'
        '    "primary_questions": [{"id": "<pq-id>", "answered": <bool>, '
        '"cited_fact": "<F-id>", "confidence_band": "<band>", "gap": '
        '<null|str>}],\n'
        '    "unresolved": [<unanswered pq-ids>],\n'
        '    "contradictions": [],\n'
        '    "degraded": []},\n'
        '  "self_audit": {"evidence_strength": "<strong|mixed|weak>", '
        '"ignored_evidence": [], "open_questions": []}}\n'
        "\n"
        "Rules: a question is answered only by a PROVEN claim linked via "
        "answers_question citing a real fact id; do not invent evidence; "
        "unanswered questions go to unresolved[] with a gap string.\n"
        "Use the Write tool to create the file, then reply done.")


def _verdict_face(ctx: RunContext, detail: dict,
                  tick_wait_seconds: int) -> model.CheckpointResult | None:
    """Post-loop verdict act per mode (dry/auto write it; orchestrator
    waits for the external verdict-scorer act). Terminal result on miss."""
    if ctx.face.mode == "dry":
        act = ctx.face.verdict_act(ctx.ws)
    elif ctx.face.mode == "auto":
        act = ctx.face.verdict_act(
            ctx.ws, prompt=_verdict_prompt(ctx))
    else:
        deadline = ctx.clock.monotonic() + max(
            0.0, ctx.state.budget_remaining_seconds())
        ready = ctx.face.wait_verdict(
            ctx.ws,
            poll_seconds=min(30.0, max(1.0, tick_wait_seconds or 5)),
            deadline=deadline, sleep_fn=ctx.sleep_fn)
        if not ready:
            return _record(ctx, "C6", "loop", model.BLOCKED, None, None, 0,
                           {**detail, "stop_class": "verdict-never-landed"})
        return None
    ctx.acts.append(act.to_dict())
    detail["acts"].append(act.to_dict())
    return None


def _tick_prelude(ctx: RunContext, detail: dict, total_ms: int):
    """Budget guard + heartbeat tick + adjudication; returns
    (terminal_or_None, tick_outcome, total_ms)."""
    if not _guard_budget(ctx):
        return (_record(ctx, "C6", "loop", model.BLOCKED, None,
                        None, total_ms,
                        {**detail, "stop_class": "budget-exhausted"}),
                None, total_ms)
    out_tick, ms = ctx.py("heartbeat_tick.py", str(ctx.ws))
    total_ms += ms
    if out_tick.rc == 2:
        return (_record(ctx, "C6", "loop", model.BLOCKED, 2,
                        out_tick, total_ms,
                        {**detail, "stop_class": "idle-circuit-breaker"}),
                None, total_ms)
    if model.adjudicate("C6-loop", out_tick.rc) != model.PASS:
        return (_record(ctx, "C6", "loop", model.FAIL,
                        out_tick.rc, out_tick, total_ms,
                        {**detail, "failed_step": "tick"}), None, total_ms)
    return None, out_tick, total_ms


def _no_open_claims(ctx: RunContext) -> bool:
    """Delivery-face test (robust): the register holds no OPEN claims.
    Deterministic register read — never a stdout-substring guess."""
    import yaml as _yaml
    reg = ctx.ws / "claim-register.yaml"
    try:
        doc = _yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return False
    for c in doc.get("claims") or []:
        if str(c.get("status", "")).upper() in ("OPEN", "PARK",
                                                "PARTIALLY-VERIFIED",
                                                "STAMP", "UNVERIFIED"):
            return False
    return bool(doc.get("claims"))


def _crashed_loud_stop(ctx: RunContext, detail: dict, decision,
                       out_d, total_ms: int) -> bool:
    """#482: a crashing convergence face must never spin silently —
    N consecutive CRASHED ticks (env KUNGLAO_CRASHED_STOP_N, default 3)
    stop the run with the stderr tail surfaced. Returns True and parks
    the terminal CheckpointResult on detail when the stop fires."""
    if decision != "CRASHED":
        detail["consecutive_crashed"] = 0
        return False
    n = int(detail.get("consecutive_crashed", 0)) + 1
    detail["consecutive_crashed"] = n
    limit = int(os.environ.get("KUNGLAO_CRASHED_STOP_N", "3"))
    if n < limit:
        return False
    detail["_crashed_terminal"] = _record(
        ctx, "C6", "loop", model.BLOCKED, out_d.rc, out_d, total_ms,
        {**{k: v for k, v in detail.items() if k != "_crashed_terminal"},
         "stop_class": "convergence-crashed", "crashed_ticks": n,
         "stderr_tail": (out_d.stderr or "")[-400:]})
    return True


def _dispatch_targets(ctx: RunContext,
                      decision: str | None) -> tuple[list,
                                                     object | None, int]:
    """#459 + #508: the tick's dispatch targets. The priority ranking
    first; for a DISPATCH_VERIFIER decision whose ranking came back
    empty, the partial facts' claims are the targets (PARKed claims are
    unrankable, but the decision was made FOR those partials)."""
    claims, failed, ms = _rank_dispatchable(ctx)
    if decision == "DISPATCH_VERIFIER" and not claims:
        derived = _partial_claim_ids(ctx)
        if derived:
            return derived, None, ms  # the empty ranking is satisfied
    return claims, failed, ms




def _settled_filtered_prior(rows: list[dict], families: list[str],
                            current_fp: str | None = None
                            ) -> dict[str, float]:
    """#523 G2 K2 — the DAPO zero-information skip at proposal time:
    meta-arms whose pooled posterior is settled (p >= 0.9 success or
    p <= 0.1) are floored to the exploration minimum; the proposal mass
    moves to the unproven arms. Reuses meta_arms pooling (one
    implementation)."""
    try:
        from rlvr import meta_arms as _ma
        pooled = _ma.hierarchical_prior(rows, families, current_fp)
        out = {}
        for fam, w in pooled.items():
            if w >= 0.9 or w <= 0.1:
                out[fam] = 0.05  # ARM_FLOOR: revivable, never removed
            else:
                out[fam] = w
        return out
    except Exception:  # noqa: BLE001 — filter degrades to the pool
        from rlvr import meta_arms as _ma
        return _ma.hierarchical_prior(rows, families, current_fp)


# ---- K3: vocabulary-immune computed flow ----


def _arm_mcp_supply(ctx: RunContext, task_yaml: "Path"
                    ) -> list[str]:
    """MCP arming: a unit's tools.mcp_servers {name: url} declaration
    reaches the WORKER, not just the gate — the server lands in
    ws/.mcp.json (the gate's workspace surface), the sudo-free
    approval flag flips (a workspace-scope registration without
    enableAllProjectMcpServers hangs pending-approval forever), and
    the tool prefixes return to ride the act rack. No declaration:
    nothing changes."""
    import yaml as _y
    try:
        doc = _y.safe_load(Path(task_yaml).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return []
    servers = ((doc.get("tools") or {}).get("mcp_servers")
               if isinstance(doc.get("tools"), dict) else None)
    if not isinstance(servers, dict) or not servers:
        return []
    ws = Path(ctx.ws)
    mcp_path = ws / ".mcp.json"
    try:
        mcp_doc = _y.safe_load(mcp_path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        mcp_doc = {}
    entries = mcp_doc.get("mcpServers") or {}
    prefixes: list[str] = []
    for name, url in servers.items():
        if isinstance(url, str) and url.strip():
            entries[str(name)] = {"type": "http", "url": url.strip()}
            prefixes.append("mcp__" + str(name))
    mcp_doc["mcpServers"] = entries
    mcp_path.write_text(json.dumps(mcp_doc, indent=2, sort_keys=True),
                        encoding="utf-8")
    set_path = ws / ".claude" / "settings.json"
    set_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(set_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    settings["enableAllProjectMcpServers"] = True
    set_path.write_text(json.dumps(settings, indent=2, sort_keys=True),
                        encoding="utf-8")
    return sorted(prefixes)


def _merge_unit_tools(ws, task_yaml: "Path") -> None:
    """Toolchain parity: the unit's task.yaml tools declaration lands
    in the workspace task_spec (the product file the env gates read).
    A unit without a tools section changes nothing."""
    import yaml as _y
    try:
        doc = _y.safe_load(Path(task_yaml).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return
    tools = doc.get("tools") if isinstance(doc, dict) else None
    if not isinstance(tools, dict) or not tools:
        return
    spec_path = Path(ws) / "task_spec.yaml"
    try:
        spec = _y.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        spec = {}
    merged = {**(spec.get("tools") or {}), **tools}
    spec["tools"] = merged
    spec_path.write_text(_canonical_dump(spec), encoding="utf-8")


def _open_claim_count(ctx: RunContext) -> int:
    """The register's open (non-terminal) claim count — the computed
    delivery check's single source (mirrors _no_open_claims but returns
    the count for observability)."""
    try:
        import yaml as _y
        reg = _y.safe_load(
            (ctx.ws / "claim-register.yaml").read_text(encoding="utf-8"))
        claims = (reg or {}).get("claims") or []
        # DEFERRED is a decline, not actionable work (matrix4 wac: the
        # engine ranked it unprioritized and BLOCKED with zero OPEN
        # claims) — it does not keep a register open.
        return sum(1 for c in claims if str(c.get("status", "")
                   ).upper() not in
                   ("PROVEN", "REFUTED", "CLOSED", "DEFERRED"))
    except (OSError, ValueError):
        return -1  # unreadable = unknown, NOT zero (fail-closed read)


def _kernel_flow_for_decision(decision: str | None, *, all_open: bool
                              ) -> str:
    """#523 G2 K3 — every decision string maps to a COMPUTED flow; the
    P4/AD1 death class (SATURATED/INVALID falling through to an eternal
    sleep) cannot recur. Known vocabulary routes as before; unknown or
    terminal-sounding words fall to the delivery check:
    no open claims -> deliver; open claims -> wait."""
    if decision == "CONVERGED":
        return "break"
    if decision in ("DISPATCH", "DISPATCH_VERIFIER"):
        return "dispatch"
    # matrix4 root (asl/wac/awa): a stop word over a SETTLED register
    # is a DELIVERY — three units died 5/5-PROVEN one gate short of the
    # verdict because BLOCKED terminated before the computed check ran.
    # Stop words only stop when open work remains that cannot proceed.
    if decision in _STOP_DECISIONS:
        return "deliver" if not all_open else "stop"
    # SATURATED / INVALID / None-tick / anything the vocabulary grows
    # tomorrow: the computed delivery check decides (never the spin)
    return "deliver" if not all_open else "wait"



def _kernel_pre_dispatch(ctx, decision, out_d, detail, total_ms,
                         tick_wait_seconds):
    """#523 G2 K3: map the convergence decision to a computed flow
    BEFORE any dispatch branch. Returns None when the tick should
    proceed to dispatch; otherwise the (flow, terminal, total_ms) the
    tick must return."""
    flow_k = _kernel_flow_for_decision(
        decision, all_open=bool(_open_claim_count(ctx)))
    if flow_k == "stop":
        stop_class = _STOP_DECISIONS.get(decision or "",
                                         "convergence-" + str(decision))
        return ("stop", _record(ctx, "C6", "loop", model.BLOCKED,
                                out_d.rc, out_d, total_ms,
                                {**detail, "stop_class": stop_class}),
                total_ms)
    if flow_k == "deliver":
        return "break", None, total_ms  # computed delivery -> verdict
    if flow_k == "wait":
        # unknown decision + open claims: an observable wait, never a
        # silent spin — the drift alarm and the tick cap still bound it.
        # The distill capability still runs (a wait is not a reason to
        # starve the online-learning side — #458's contract)
        audit.emit(str(ctx.ws), "orchestrator", "kernel_wait",
                   detail={"decision": str(decision),
                           "tick": detail.get("ticks")})
        _maybe_distill(ctx, detail)
        _posterior_drift_check(ctx)
        ctx.sleep_fn(tick_wait_seconds)
        return "continue", None, total_ms
    return None


def _loop_one_tick(ctx: RunContext, dispatched: set[str], detail: dict,
                   tick_wait_seconds: int, total_ms: int
                   ) -> tuple[str, model.CheckpointResult | None, int]:
    """One tick cycle: tick -> decide -> act.

    Returns (flow, terminal_result, total_ms): flow is 'continue' or
    'break' (CONVERGED); terminal_result is set only when the loop must
    stop with a recorded outcome (FAIL/BLOCKED)."""
    terminal, out_tick, total_ms = _tick_prelude(ctx, detail, total_ms)
    if terminal is not None:
        return "stop", terminal, total_ms
    out_d, ms = ctx.py("convergence_check.py", str(ctx.ws), "--json")
    total_ms += ms
    decision, _doc = _decide(out_d)
    detail["decision"] = decision
    audit.emit_convergence_decision(str(ctx.ws), decision,
                                    tick=detail.get("ticks"), rc=out_d.rc)
    if decision == "CONVERGED":
        return "break", None, total_ms
    if _crashed_loud_stop(ctx, detail, decision, out_d, total_ms):
        return ("stop", detail.pop("_crashed_terminal"), total_ms)
    # #523 G2 K3: the computed flow replaces the string-switch — every
    # decision word maps through the kernel (P4/AD1 spin impossible)
    pre = _kernel_pre_dispatch(ctx, decision, out_d, detail, total_ms,
                               tick_wait_seconds)
    if pre is not None:
        return pre
    if decision in ("DISPATCH", "DISPATCH_VERIFIER"):
        claims, failed, ms = _dispatch_targets(ctx, decision)
        total_ms += ms
        if not claims and _no_open_claims(ctx):
            return "break", None, total_ms  # delivery face -> verdict
        if failed is not None or not claims:
            return ("stop", _record(
                ctx, "C6", "loop", model.FAIL,
                failed.rc if failed else None, failed, total_ms,
                {**detail, "failed_step": "priority_ratio"}), total_ms)
        if decision == "DISPATCH_VERIFIER":
            terminal = _run_verifier_act(ctx, claims[0], dispatched, detail)
            if terminal is not None:
                return "stop", terminal, total_ms
        elif decision == "DISPATCH":
            # #459: dispatch up to max-parallel acts concurrently (launch
            # all, wait for all); rollback + budget guard stay per-act /
            # global inside the wave.
            _dispatch_wave(ctx, claims, dispatched, detail)
    elif decision is None:
        return ("stop", _record(ctx, "C6", "loop", model.FAIL, out_d.rc,
                                out_d, total_ms,
                                {**detail, "failed_step": "decide-parse"}),
                total_ms)
    # online distillation tick step: one bounded act per tick when a
    # miss signal fires with budget (a capability, never the loop)
    _maybe_distill(ctx, detail)
    # #546 WS4: the discovery move — obstacles stacked + arms collapsed
    # => one expand act per run (a capability, never the loop)
    _maybe_expand(ctx, dispatched, detail)
    # #518 PR-2 (W4): the frozen-posterior alarm rides every tick tail
    _posterior_drift_check(ctx)
    ctx.sleep_fn(tick_wait_seconds)
    return "continue", None, total_ms


def checkpoint_c6_loop(ctx: RunContext, tick_wait_seconds: int,
                       max_ticks: int) -> model.CheckpointResult:
    """Per-tick loop (C6/C7 driver contract): tick → decide → act."""
    total_ms = 0
    detail: dict = {"acts": [], "ticks": 0, "decision": None}
    dispatched: set[str] = set()
    converged = False
    for tick in range(1, max_ticks + 1):
        detail["ticks"] = tick
        flow, terminal, total_ms = _loop_one_tick(
            ctx, dispatched, detail, tick_wait_seconds, total_ms)
        if terminal is not None:
            return terminal
        if flow == "break":
            converged = True
            break
    if not converged:
        return _record(ctx, "C6", "loop", model.BLOCKED, None, None,
                       total_ms, {**detail, "stop_class": "loop-exhausted"})
    # acts landed → verdict face, then promotion through the repo gate
    terminal = _verdict_face(ctx, detail, tick_wait_seconds)
    if terminal is not None:
        terminal.duration_ms += total_ms
        return terminal
    promote = promote_claims(ctx.repo, ctx.ws,
                             [c["id"] for c in CLAIM_APPENDS])
    detail["promotion"] = promote
    if not promote.get("ok"):
        # F3: the gate refused the →PROVEN transitions — the register was
        # NOT written; FAIL with the violations in evidence (never a
        # ceremonial pass over an unwaived violation).
        return _record(ctx, "C6", "loop", model.FAIL, None, None, total_ms,
                       {**detail, "failed_step": "promote-gate"})
    verdict_file = ctx.ws / "evidence" / "verdict.json"
    if not verdict_file.is_file():
        return _record(ctx, "C6", "loop", model.BLOCKED, None, None,
                       total_ms, {**detail,
                                  "stop_class": "verdict-missing"})
    return _record(ctx, "C6", "loop", model.PASS, 0, None, total_ms, detail)


def checkpoint_c7(ctx: RunContext) -> model.CheckpointResult:
    total_ms = 0
    out_d, ms = ctx.py("convergence_check.py", str(ctx.ws), "--json")
    total_ms += ms
    status_d = model.adjudicate("C7-convergence", out_d.rc)
    decision, _doc = _decide(out_d)
    audit.emit_convergence_decision(str(ctx.ws), decision, rc=out_d.rc)
    if status_d != model.PASS or decision != "CONVERGED":
        return _record(ctx, "C7", "completion",
                       model.BLOCKED if decision else model.FAIL,
                       out_d.rc, out_d, total_ms,
                       {"decision": decision, "failed_step": "convergence"})
    out_g, ms = ctx.py("completion_gate.py", str(ctx.ws / "task-oracle.yaml"))
    total_ms += ms
    status_g = model.adjudicate("C7-completion", out_g.rc)
    if status_g != model.PASS:
        return _record(ctx, "C7", "completion", status_g, out_g.rc, out_g,
                       total_ms, {"failed_step": "completion_gate"})
    # F2: the REAL #880 rows carry action="claim_settled"
    # (register_proven_gate.emit_settlements -> kunglao_log.emit); the
    # runbook's "action=settlement" does not match the repo.
    scan = model.scan_settlement_rows(ctx.ws)
    ok = scan["rows"] >= 1
    return _record(ctx, "C7", "completion",
                   model.PASS if ok else model.FAIL, out_g.rc, out_g,
                   total_ms, {"settlement_rows": scan["rows"],
                              "settlement_action": model.SETTLEMENT_ACTION,
                              "settlement_files": scan["files"],
                              "parse_errors": scan["parse_errors"]},
                   scan["files"])


def checkpoint_oracle(ctx: RunContext) -> model.CheckpointResult:
    """The gold standard: replay checker from the REPO tree (never a /tmp
    copy — rehearsal finding #3).

    Parses the checker's REAL stdout emission (METRIC / EVIDENCE / VERDICT
    text lines — no JSON on stdout, review F1); the observed replay pair
    ratio is derived from the evidence FILE the checker writes
    (faces.replay matched/count). Acceptance = VERDICT PASS + rc 0 +
    observed ratio >= the task's required min_pair_ratio; a missing or
    unreadable evidence file FAILs (the checker always writes it — no
    vacuous pass)."""
    candidate = model.resolve_candidate(
        ctx.ws, Path(ctx.state.task_dir) / "task.yaml")
    if not candidate.is_file():
        return _record(ctx, "ORACLE", "oracle", model.BLOCKED, None, None,
                       0, {"stop_class": "no-candidate",
                           "expected": str(candidate)},
                       [candidate])
    checker = model.resolve_checker(
        ctx.repo, family_of(Path(ctx.state.task_dir)), ctx.state.unit)
    if checker is None:
        return _record(ctx, "ORACLE", "oracle", model.BLOCKED, None, None,
                       0, {"stop_class": "checker-not-in-repo-tree"})
    cmd = ["uv", "run", "--project", str(ctx.repo), "python",
           str(checker), "--candidate", str(candidate)]
    out, ms = ctx.cmd(cmd, timeout=900)
    status = model.adjudicate("ORACLE", out.rc)
    parsed = model.parse_checker_output(out.stdout)
    verdict = parsed["verdict"] or ""
    detail: dict = {
        "verdict": verdict, "metrics": parsed["metrics"],
        "failures": parsed["failures"],
        "checker": str(checker), "candidate": str(candidate),
        "eval_evidence": parsed["evidence_path"],
        "eval_evidence_note": "repo-local, gitignored, never committed",
    }
    # observed pair ratio from the checker's evidence file (F1)
    evidence_error = None
    pairs = None
    ratio = None
    if parsed["evidence_path"]:
        ev = Path(parsed["evidence_path"])
        if not ev.is_absolute():
            ev = ctx.repo / ev
        try:
            doc = json.loads(ev.read_text(encoding="utf-8"))
            replay = ((doc.get("faces") or {}).get("replay") or {})
            matched, count = replay.get("matched"), replay.get("count")
            if isinstance(matched, int) and isinstance(count, int) \
                    and count > 0:
                pairs = {"matched": matched, "count": count}
                ratio = matched / count
            detail["eval_evidence_abs"] = str(ev)
        except (OSError, ValueError) as exc:
            evidence_error = f"{type(exc).__name__}: {exc}"
    else:
        evidence_error = "no EVIDENCE line on checker stdout"
    if evidence_error:
        detail["evidence_error"] = evidence_error
        status = model.FAIL  # no vacuous pass without the evidence file
    required = model.load_min_pair_ratio(
        Path(ctx.state.task_dir) / "task.yaml")
    detail["min_pair_ratio_required"] = required
    detail["min_pair_ratio"] = ratio if ratio is not None else required
    detail["pairs"] = pairs
    if status == model.PASS:
        if verdict != "PASS" or ratio is None or ratio < required:
            status = model.FAIL
    # contamination guard re-checked at the oracle boundary
    violations = model.check_contamination(ctx.ws)
    if violations:
        status = model.FAIL
    detail["contamination_violations"] = violations
    return _record(ctx, "ORACLE", "oracle", status, out.rc, out, ms,
                   detail, [candidate, checker])


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def _resume_hygiene(plan, state) -> None:
    """#482: a resumed run resets the stale no-op streak."""
    if plan and any(step == "RUN" for step in plan.values()):
        _reset_noop_breaker(state)


def _final_verdict_of(evidence_dir: Path):
    oracle_doc = (evidence.load_checkpoint(evidence_dir, "ORACLE")
                  or {}).get("detail", {})
    return ({"verdict": oracle_doc.get("verdict"),
             "min_pair_ratio": oracle_doc.get("min_pair_ratio")}
            if oracle_doc else None)


def _reset_noop_breaker(state) -> None:
    """#482: a resumed workspace is not a stalled one — the persisted
    no-op streak belongs to the previous (ended) run."""
    try:
        import json as _json
        nb = Path(state.ws) / "runs" / ".heartbeat-noop.json"
        if nb.is_file():
            doc = _json.loads(nb.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("count"):
                doc["count"] = 0
                nb.write_text(_json.dumps(doc), encoding="utf-8")
    except (OSError, ValueError) as exc:
        # non-silent per #275: the fallback itself must stay visible
        import sys as _sys
        print(f"e2e: noop-breaker reset skipped: "
              f"{type(exc).__name__}", file=_sys.stderr)


def run_pipeline(args: model.PipelineArgs, cmd_runner=None, clock=None,
                 sleep_fn=None, report_sink: list | None = None) -> int:
    """Execute the runbook pipeline; returns the process exit code.

    report_sink: optional list that receives the final report dict (the
    CLI's --json face prints it instead of the human summary)."""
    repo = Path(args.repo).resolve()
    task_dir = resolve_task_dir(repo, args.unit)
    anchors = model.load_anchors(task_dir / "task.yaml")
    run_id = args.run_id or new_run_id()
    evidence_dir = evidence.evidence_root(repo) / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ws_root = Path(args.ws_root)
    ws = ws_root / f"e2e-ws-{run_id.split('e2e-')[-1]}"
    runner = cmd_runner or llm_faces.CommandRunner(repo)
    clock = clock or _MonotonicClock()
    sleep_fn = sleep_fn or time.sleep
    state = model.RunState(
        run_id=run_id, unit=args.unit, family=family_of(task_dir),
        repo=str(repo), task_dir=str(task_dir), ws=str(ws),
        ws_root=str(ws_root), evidence_dir=str(evidence_dir),
        budget_seconds=args.budget_seconds, llm_mode=args.llm_mode,
        started_ts=model.utc_now(), started_monotonic=clock.monotonic(),
        anchors=anchors, lane=args.lane, type_=args.type_,
        tick_wait_seconds=args.tick_wait_seconds, max_ticks=args.max_ticks)
    face = llm_faces.face_for(args.llm_mode, runner, evidence_dir)
    ctx = RunContext(state=state, runner=runner, face=face,
                     clock=clock, sleep_fn=sleep_fn)

    # workspace staging: material mount OUTSIDE the repo, ONLY the
    # target source; ground_truth/checker stay out (contamination rule)
    model.stage_workspace(task_dir, ws)
    violations = model.check_contamination(ws)
    if violations:
        state.steps["C0-stage"] = model.FAIL
        print(f"CONTAMINATION at staging: {violations}")
        return _abort_contaminated(ctx, evidence_dir, report_sink)
    results: list[model.CheckpointResult] = []
    exit_code = model.EXIT_OK
    final_status = "ALL-PASS"

    def finalize(code: int, status: str) -> int:
        state.total_duration_ms = sum(r.duration_ms for r in results)
        state.budget_consumed_seconds = max(
            state.budget_consumed_seconds,
            clock.monotonic() - state.started_monotonic)
        final_verdict = _final_verdict_of(evidence_dir)
        _harvest_scripts(ctx)  # #477: once per finalize; cages itself
        report = evidence.build_report(
            state, results, final_status=status, exit_code=code,
            final_verdict=final_verdict)
        (evidence_dir / evidence.REPORT_FILE).write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n", encoding="utf-8")
        evidence.write_run_state(evidence_dir, state)
        if report_sink is not None:
            report_sink.append(report)
        else:
            print(evidence.render_summary(report))
        return code

    if not _guard_budget(ctx):
        return finalize(model.EXIT_BUDGET_PARTIAL, "PARTIAL")

    plan = resume_plan(evidence_dir)
    _resume_hygiene(plan, state)
    steps: list[tuple[str, str, object]] = [
        ("C1", "init", lambda: checkpoint_c1(ctx)),
        ("C2", "hooks", lambda: checkpoint_c2(ctx)),
        ("C3", "heartbeat", lambda: checkpoint_c3(ctx)),
        ("C4", "entry", lambda: checkpoint_c4(ctx)),
        ("C5", "analysis", lambda: checkpoint_c5(ctx)),
        ("C6", "pre", lambda: checkpoint_c6_pre(ctx)),
        ("C6", "loop", lambda: checkpoint_c6_loop(
            ctx, args.tick_wait_seconds, args.max_ticks)),
        ("C7", "completion", lambda: checkpoint_c7(ctx)),
        ("ORACLE", "oracle", lambda: checkpoint_oracle(ctx)),
    ]
    for checkpoint, name, fn in steps:
        sid = model.step_id(checkpoint, name)
        if plan.get(sid) == "SKIP":
            doc = evidence.load_checkpoint(evidence_dir, sid) or {}
            skipped = model.CheckpointResult.from_dict(
                {**doc, "status": model.SKIP})
            results.append(skipped)
            state.steps[sid] = model.SKIP
            print(f"[{sid}] SKIP (evidence-anchored resume)")
            continue
        if not _guard_budget(ctx):
            exit_code = model.EXIT_BUDGET_PARTIAL
            final_status = "PARTIAL"
            break
        print(f"[{sid}] RUN")
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 — #472 step cage: a
            # raising step is converted to a FAIL CheckpointResult via
            # the canonical _record seam (evidence file + exactly one
            # audit row), then the loop's FAIL handling applies and
            # finalize() still writes the report — the harness's
            # product IS the report; a crash must not lose it. The
            # error text rides the per-step evidence detail (the
            # emit_checkpoint detail contract is exactly-those-keys —
            # pinned by TestUnifiedAuditTrail — so it does NOT join the
            # audit row; rc=None matches the BLOCKED precedent).
            # BaseException (operator interrupts) still propagates.
            result = _record(ctx, checkpoint, name, model.FAIL, None,
                             None, 0,
                             {"failed_step": name,
                              "error": f"{type(exc).__name__}: {exc}"})
        results.append(result)
        state.steps[sid] = result.status
        if result.status == model.FAIL:
            exit_code = model.EXIT_CHECKPOINT_FAIL
            final_status = "FAIL"
            break
        if result.status == model.BLOCKED:
            # F4: the runbook's budget stop is an honest PARTIAL wherever
            # it fires — mid-loop included (was BLOCKED/3 there).
            if result.detail.get("stop_class") == "budget-exhausted":
                exit_code = model.EXIT_BUDGET_PARTIAL
                final_status = "PARTIAL"
            else:
                exit_code = model.EXIT_BLOCKED
                final_status = "BLOCKED"
            break
    return finalize(exit_code, final_status)


def _make_clock():
    return _MonotonicClock()


class _MonotonicClock:
    def monotonic(self) -> float:
        return time.monotonic()


def _abort_contaminated(ctx: RunContext, evidence_dir: Path,
                        report_sink: list | None) -> int:
    """Contamination at staging: fail-closed with an empty-report
    evidence trail (no checkpoint runs on a dirty workspace)."""
    state = ctx.state
    state.budget_consumed_seconds = max(
        state.budget_consumed_seconds,
        ctx.clock.monotonic() - state.started_monotonic)
    report = evidence.build_report(
        state, [], final_status="FAIL",
        exit_code=model.EXIT_CHECKPOINT_FAIL, final_verdict=None)
    (Path(evidence_dir) / evidence.REPORT_FILE).write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n", encoding="utf-8")
    evidence.write_run_state(Path(evidence_dir), state)
    if report_sink is not None:
        report_sink.append(report)
    else:
        print(evidence.render_summary(report))
    return model.EXIT_CHECKPOINT_FAIL


def _harvest_scripts(ctx: RunContext) -> dict | None:
    """#477: the post-run workspace script harvest, hosted at finalize —
    sweep worker scripts, classify by success trace, verify against the
    sample, land candidates into tools-local/ (never the global shelf),
    and emit the audit rows. Fail-open: a raising engine never breaks
    finalize (the optional capability must not cost the report)."""
    import script_harvest  # repo-top module; cheap import, fail-open
    try:
        result = script_harvest.run_harvest(
            Path(ctx.ws), since_epoch=0.0)
        if not (result.get("swept") or []):
            return result  # nothing swept -> no rows at all (#477 spec)
        audit.emit_harvest_scan(
            str(ctx.ws), swept=len(result.get("swept") or []),
            candidates=len(result.get("candidates") or []),
            skipped=len(result.get("skipped") or []),
            archived=len(result.get("archived") or []),
            playbook=(result.get("playbook")
                      and "runs/harvest-playbook.json") or None)
        for cand in (result.get("landed") or []):
            audit.emit_script_harvested(
                str(ctx.ws), cand.get("name") or "",
                script=cand.get("script") or "",
                signals=cand.get("signals") or {},
                facts=cand.get("facts") or [])
        for cand in (result.get("archived") or []):
            audit.emit_script_harvested(
                str(ctx.ws), cand.get("name") or "",
                script=cand.get("script") or "",
                signals={}, facts=[])
        for cand in (result.get("landed") or []):
            name = cand.get("name") or ""
            audit.emit_harvest_landed(
                str(ctx.ws), name,
                tool_path=f"tools-local/{name}.py")
        return result
    except Exception:  # noqa: BLE001 — the harvest never breaks finalize
        try:
            kunglao_log.warn("e2e_harvest",
                             "harvest engine raised; skipped")
        except Exception as exc:  # noqa: BLE001 — the warn fallback too
            import sys as _sys
            print(f"e2e: harvest engine raised: {type(exc).__name__}",
                  file=_sys.stderr)
        return None
