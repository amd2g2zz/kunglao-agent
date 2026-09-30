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
)

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
    Falls back to the py-derive-v1 shape when anchors are absent."""
    global PRIMARY_QUESTIONS, CLAIM_APPENDS
    try:
        import yaml as _yaml
        spec = _yaml.safe_load(task_spec.read_text(encoding="utf-8"))
        if not isinstance(spec, dict):
            # empty/null/list-shaped spec: restore defaults — a reused
            # process must not leak the previous unit's resolved claims
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
    except Exception:  # never-raise resolver: ANY failure restores defaults
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
    final = model.PASS if (status_a == model.PASS and
                           status_c == model.PASS) else (
        model.BLOCKED if model.BLOCKED in (status_a, status_c)
        else model.FAIL)
    return _record(ctx, "C1", "init", final, out_c.rc, out_c,
                   ms_a + ms_c, detail, [answers_path])


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
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
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
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8")
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
        yaml.safe_dump(reg_doc, sort_keys=False, allow_unicode=True,
                       width=100), encoding="utf-8")
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


def _sample_envelope_family(ws) -> tuple[str, dict | None]:
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
    the dispatch loop."""
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
            prior = {fam: float(n) for fam, n in sorted(counts.items())}
        else:
            if not registered:
                return "", None
            prior = {fam: 1.0 for fam in registered}
        rng, _round = q_cells.q_cells_seed_state(ws)
        # #460 Part B wiring (predict-before-try): thread the live
        # instance features + the mined feature table into call site 2
        # when KUNGLAO_PREDICT_BEFORE_TRY is on — fail-open to the
        # flag-off sampler shape (a broken prior never breaks the loop)
        kwargs: dict = {}
        try:
            from rlvr import feature_prior as _fp
            if _fp.enabled():
                features = _fp.features_from_workspace(ws)
                if features:
                    kwargs = {"features": features,
                              "feature_table": _fp.default_table_path(ws)}
        except Exception:  # noqa: BLE001 — fail-open at the seam
            kwargs = {}
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
    # kernel-facing hook (audit §4): the envelope's method_family is the
    # declared proposal when the run carries one, else the DTS-sampled
    # draw (W4, issue 462) — the sampled family rides the envelope AND
    # the stream records it with its sampler receipt.
    method_family = getattr(ctx.state, "method_family", "") or ""
    receipt: dict | None = None
    if not method_family:
        method_family, receipt = _sample_envelope_family(ctx.ws)
    dispatch_meta: dict = {
        "version": 1, "claim": claim, "tier": 1,
        "tools": ["grep", "python3"],
        "agent": "kunglao-worker"}
    if method_family:
        dispatch_meta["method_family"] = method_family
    prompt_file = Path(ctx.state.evidence_dir) / f"dispatch-prompt-{claim}.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(
        json.dumps({"kunglao_dispatch": dispatch_meta})
        + f"\n\nfacts-snapshot: {ctx.ws}/facts\nclaim: {claim}\n",
        encoding="utf-8")
    if method_family:
        audit.emit_method_family(str(ctx.ws), claim, method_family,
                                 envelope=receipt)
    request = model.DispatchRequest(
        claim=claim, workspace=str(ctx.ws),
        prompt_file=str(prompt_file), run_id=ctx.state.run_id,
        method_family=method_family or None)
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


_STOP_DECISIONS = {"BLOCKED": "convergence-blocked", "PARK": "parked"}


def _verdict_face(ctx: RunContext, detail: dict,
                  tick_wait_seconds: int) -> model.CheckpointResult | None:
    """Post-loop verdict act per mode (dry/auto write it; orchestrator
    waits for the external verdict-scorer act). Terminal result on miss."""
    if ctx.face.mode == "dry":
        act = ctx.face.verdict_act(ctx.ws)
    elif ctx.face.mode == "auto":
        act = ctx.face.verdict_act(
            ctx.ws, prompt="verdict-scorer: write evidence/verdict.json "
                           "per analysis_verdict schema v11")
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


def _loop_one_tick(ctx: RunContext, dispatched: set[str], detail: dict,
                   tick_wait_seconds: int, total_ms: int
                   ) -> tuple[str, model.CheckpointResult | None, int]:
    """One tick cycle: tick -> decide -> act.

    Returns (flow, terminal_result, total_ms): flow is 'continue' or
    'break' (CONVERGED); terminal_result is set only when the loop must
    stop with a recorded outcome (FAIL/BLOCKED)."""
    if not _guard_budget(ctx):
        return ("stop", _record(ctx, "C6", "loop", model.BLOCKED, None,
                                None, total_ms,
                                {**detail, "stop_class": "budget-exhausted"}),
                total_ms)
    out_tick, ms = ctx.py("heartbeat_tick.py", str(ctx.ws))
    total_ms += ms
    if out_tick.rc == 2:
        return ("stop", _record(ctx, "C6", "loop", model.BLOCKED, 2,
                                out_tick, total_ms,
                                {**detail,
                                 "stop_class": "idle-circuit-breaker"}),
                total_ms)
    if model.adjudicate("C6-loop", out_tick.rc) != model.PASS:
        return ("stop", _record(ctx, "C6", "loop", model.FAIL,
                                out_tick.rc, out_tick, total_ms,
                                {**detail, "failed_step": "tick"}), total_ms)
    out_d, ms = ctx.py("convergence_check.py", str(ctx.ws), "--json")
    total_ms += ms
    decision, _doc = _decide(out_d)
    detail["decision"] = decision
    audit.emit_convergence_decision(str(ctx.ws), decision,
                                    tick=detail.get("ticks"), rc=out_d.rc)
    if decision == "CONVERGED":
        return "break", None, total_ms
    stop_class = _STOP_DECISIONS.get(decision or "")
    if stop_class:
        return ("stop", _record(ctx, "C6", "loop", model.BLOCKED,
                                out_d.rc, out_d, total_ms,
                                {**detail, "stop_class": stop_class}),
                total_ms)
    if decision in ("DISPATCH", "DISPATCH_VERIFIER"):
        claims, failed, ms = _rank_dispatchable(ctx)
        total_ms += ms
        if failed is not None or not claims:
            return ("stop", _record(
                ctx, "C6", "loop", model.FAIL,
                failed.rc if failed else None, failed, total_ms,
                {**detail, "failed_step": "priority_ratio"}), total_ms)
        if decision == "DISPATCH":
            # #459: dispatch up to max-parallel acts concurrently (launch
            # all, wait for all); rollback + budget guard stay per-act /
            # global inside the wave.
            _dispatch_wave(ctx, claims, dispatched, detail)
    elif decision is None:
        return ("stop", _record(ctx, "C6", "loop", model.FAIL, out_d.rc,
                                out_d, total_ms,
                                {**detail, "failed_step": "decide-parse"}),
                total_ms)
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
    candidate = ctx.ws / "artifacts" / "derive_reimpl.py"
    if not candidate.is_file():
        return _record(ctx, "ORACLE", "oracle", model.BLOCKED, None, None,
                       0, {"stop_class": "no-candidate"},
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
        oracle_doc = (evidence.load_checkpoint(evidence_dir, "ORACLE")
                      or {}).get("detail", {})
        final_verdict = ({"verdict": oracle_doc.get("verdict"),
                          "min_pair_ratio": oracle_doc.get("min_pair_ratio")}
                         if oracle_doc else None)
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
        result = fn()
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
