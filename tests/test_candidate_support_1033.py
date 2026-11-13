"""Synthetic regression for retaining evidence-backed method candidates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import worker_budget_sinks as sinks
from rlvr import priors, q_cells, strategy_store


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "case"
    (ws / "runs").mkdir(parents=True)
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "isolated"))
    (ws / "task_spec.yaml").write_text(
        "family: native-signature\nlane: binary\n"
        "verification_method: replay-evidence\n"
        "constraints:\n  dynamic_re: allowed\n"
        "primary_questions:\n  - id: PQ1\n    q: derive the result\n"
        "    candidates: [static-decompile, dynamic-trace]\n",
        encoding="utf-8",
    )
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n    answers_question: PQ1\n",
        encoding="utf-8",
    )
    assert priors.seed_intake_prior(
        ws, families=["static-decompile", "dynamic-trace"])
    return ws


def _prompt(family: str, reason: str | None = None) -> str:
    env = {"version": 1, "claim": "C-001", "tier": 1,
           "tools": ["grep"], "agent": "kunglao-worker",
           "method_family": family}
    suffix = f"\nagent-reasoning: {reason}" if reason else ""
    return (json.dumps({"kunglao_dispatch": env})
            + "\nfacts-snapshot: 0 facts" + suffix)


def test_pending_first_dispatch_preserves_intake_pivot(workspace: Path):
    prior, source = strategy_store.PosteriorStrategyStore(
        workspace).proposal_prior_labeled()
    assert source == "llm_prior" and prior["dynamic-trace"] > 0
    assert q_cells.append_observation(
        workspace, "aaaaaaaaaaaa", "static-decompile", None,
        source="dispatch", claim="C-001", dispatch_id="dispatch-1",
        arm_key_col=q_cells.arm_key("static-decompile", "facts_snapshot", "none", 1),
    )["appended"]
    view = strategy_store.reconcile_declaration(workspace, "dynamic-trace")
    rc, family, _ = sinks._method_family_gate(
        {"workspace": str(workspace)},
        _prompt("dynamic-trace", "new evidence requires an independent observation"),
        "C-001", "kunglao-worker", 1, ["grep"])
    assert rc is None, (view, rc)
    assert family == "dynamic-trace"


def test_host_runs_supported_pivot_in_mock_worker(workspace: Path, monkeypatch):
    import random
    import time

    from e2e import checkpoints, llm_faces, model

    assert q_cells.append_observation(
        workspace, "aaaaaaaaaaaa", "static-decompile", None,
        source="dispatch", claim="C-first", dispatch_id="dispatch-1",
        arm_key_col=q_cells.arm_key("static-decompile", "facts_snapshot", "none", 1),
    )["appended"]
    monkeypatch.setattr(q_cells, "q_cells_seed_state",
                        lambda _ws: (random.Random(3), 0))
    received = []

    class MockWorkerRunner:
        def run(self, command, cwd=None, timeout=None):
            received.append((command[2], cwd))
            return model.CmdOutcome(rc=0, stdout='{"result":"STATUS: DONE"}', stderr="")

    runner = MockWorkerRunner()
    state = model.RunState(
        run_id="synthetic", unit="synthetic", family="synthetic",
        repo=str(Path(__file__).resolve().parents[1]), task_dir=str(workspace),
        ws=str(workspace), evidence_dir=str(workspace / "evidence"),
        budget_seconds=60, llm_mode="auto", started_ts="t",
        started_monotonic=0.0, anchors={},
    )
    face = llm_faces.AutoLlmFace(runner, Path(state.evidence_dir))
    ctx = checkpoints.RunContext(state=state, runner=runner, face=face,
                                 clock=time, sleep_fn=lambda _: None)
    req, handle = checkpoints._launch_dispatch(ctx, "C-001", set())
    assert req is not None
    act = face.run_dispatch(req, handle)
    assert act.outcome == "DISPATCHED"
    assert len(received) == 1 and received[0][1] == str(workspace)
    envelope = json.loads(received[0][0].splitlines()[0])["kunglao_dispatch"]
    assert envelope["method_family"] == "dynamic-trace"


def test_settled_history_retains_intake_and_replay_is_deterministic(workspace: Path):
    assert q_cells.append_observation(
        workspace, "aaaaaaaaaaaa", "static-decompile", None,
        source="dispatch", claim="C-first", dispatch_id="dispatch-1",
        arm_key_col=q_cells.arm_key("static-decompile", "facts_snapshot", "none", 1),
    )["appended"]
    assert q_cells.observe_settlement(workspace, "C-first", 0.8)["matched"]
    store = strategy_store.PosteriorStrategyStore(workspace)
    first = store.method_sample("aaaaaaaaaaaa")
    second = store.method_sample("aaaaaaaaaaaa")
    assert first == second
    assert set(first["candidates"]) == {"static-decompile", "dynamic-trace"}
    assert first["candidates"]["dynamic-trace"]["weight"] > 0


def test_reasoned_override_records_conditional_and_unknown_behavior(workspace: Path):
    from rlvr import state

    fp = state.signature_hash(state.snapshot(workspace))
    store = strategy_store.PosteriorStrategyStore(workspace)
    sample = store.method_sample(fp)
    actual = ({"static-decompile", "dynamic-trace"} - {sample["family"]}).pop()
    view = strategy_store.reconcile_declaration(workspace, actual)
    rc, family, gated = sinks._method_family_gate(
        {"workspace": str(workspace)}, _prompt(actual, "new independent evidence"),
        "C-001", "kunglao-worker", 1, ["grep"])
    assert rc is None and family == actual
    assert view["propensity"] is None
    assert view["probability_source"] == "unknown"
    assert view["conditional_sampler_weight"] > 0
    assert set(view["candidates"]) == {"static-decompile", "dynamic-trace"}
    assert "llm_prior" in view["candidate_sources"][actual]
    out = q_cells.record_dispatch_observation(
        workspace, _prompt(actual, "new independent evidence"),
        envelope_meta={"method_family": actual}, claim="C-001",
        sampler_view=gated)
    assert out["appended"]
    row = q_cells.dispatch_rows(workspace)[-1]
    assert row["method_family"] == actual
    assert row["sampled_family"] == sample["family"]
    assert row["override_reason"] == "new independent evidence"
    assert row["propensity"] is None
    assert row["probability_source"] == "unknown"
    assert set(row["candidates"]) == {"static-decompile", "dynamic-trace"}
    assert "llm_prior" in row["candidate_sources"][actual]


def test_dynamic_permission_revoked_before_dispatch(workspace: Path):
    spec = workspace / "task_spec.yaml"
    spec.write_text(spec.read_text().replace("dynamic_re: allowed",
                                             "dynamic_re: forbidden"))
    store = strategy_store.PosteriorStrategyStore(workspace)
    sample = store.method_sample("aaaaaaaaaaaa")
    assert "dynamic-trace" not in sample["candidates"]
    rc, _, _ = sinks._method_family_gate(
        {"workspace": str(workspace)}, _prompt("dynamic-trace", "reason"),
        "C-001", "kunglao-worker", 1, ["grep"])
    assert rc == 2


def test_no_intake_or_current_evidence_is_a_real_gap(tmp_path: Path, monkeypatch):
    ws = tmp_path / "empty"
    ws.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "isolated"))
    assert strategy_store.PosteriorStrategyStore(ws).method_sample("aaaaaaaaaaaa") is None


def test_admitted_discovery_is_revalidated_at_every_decision(workspace: Path):
    from rlvr import expansion

    family = "synthetic-discovery"
    ranked = expansion.admit([{"id": "h1", "family": family, "p_llm": 0.3,
                                "policy": 0.0, "features": {"lane": "test"}}], [])
    doc = expansion.record_receipt(workspace, {"obstacle_count": 3},
                                   ranked, ["h1"])
    assert expansion.register_admitted(workspace, doc) == [family]
    store = strategy_store.PosteriorStrategyStore(workspace)
    receipt = store.method_sample("aaaaaaaaaaaa")
    assert family in receipt["candidates"]
    assert "expansion" in receipt["candidate_sources"][family]
    (workspace / "runs" / "expansion" / f'{doc["receipt"]}.json').unlink()
    assert family not in store.method_sample("aaaaaaaaaaaa")["candidates"]


def test_host_does_not_record_guessed_behavior_probability(workspace: Path):
    import time

    from e2e import checkpoints, llm_faces, model
    from rlvr import policy_compare

    class MockWorkerRunner:
        def run(self, command, cwd=None, timeout=None):
            return model.CmdOutcome(rc=0, stdout='{"result":"STATUS: DONE"}', stderr="")

    runner = MockWorkerRunner()
    state = model.RunState(
        run_id="synthetic", unit="synthetic", family="synthetic",
        repo=str(Path(__file__).resolve().parents[1]), task_dir=str(workspace),
        ws=str(workspace), evidence_dir=str(workspace / "evidence"),
        budget_seconds=60, llm_mode="auto", started_ts="t",
        started_monotonic=0.0, anchors={})
    face = llm_faces.AutoLlmFace(runner, Path(state.evidence_dir))
    ctx = checkpoints.RunContext(state=state, runner=runner, face=face,
                                 clock=time, sleep_fn=lambda _: None)
    state.method_family = "static-decompile"
    req, handle = checkpoints._launch_dispatch(ctx, "C-001", set())
    assert req is not None
    face.run_dispatch(req, handle)
    envs = policy_compare._audit_envelopes(workspace)
    assert envs and envs[-1]["propensity"] is None


def test_case_learning_reweights_supported_family_without_adding_support(workspace: Path):
    import posteriors_case
    import yaml

    (workspace / "oracle" / "cases").mkdir(parents=True)
    (workspace / "oracle" / "cases" / "case-1.yaml").write_text(yaml.safe_dump({
        "id": "case-1", "status": "active", "target_pq": "PQ1",
        "update_map": {"green_up": ["H-1"], "red_up": []}}))
    (workspace / "hypotheses").mkdir()
    (workspace / "hypotheses" / "H-1.md").write_text(
        "---\nid: H-1\nclaim_id: C-first\ncompetitor_group: pq-PQ1\n"
        "candidates: [x]\nstatus: open\nschema_rev: 1\n---\nbody\n")
    q_cells.append_observation(workspace, "aaaaaaaaaaaa", "static-decompile",
                               None, source="dispatch", claim="C-first")
    store = strategy_store.PosteriorStrategyStore(workspace)
    before, _ = store.proposal_prior_labeled()
    led = posteriors_case.PosteriorLedger.load(workspace)
    led.cases["case-1"] = posteriors_case.CasePosterior("case-1", alpha=2, beta=1)
    led.save(workspace)
    after, _ = store.proposal_prior_labeled()
    assert after["static-decompile"] > before["static-decompile"]
    sample = store.method_sample("aaaaaaaaaaaa")
    assert "case_weight" in sample["candidate_sources"]["static-decompile"]


def test_cross_task_learning_warms_only_current_support(workspace: Path, tmp_path: Path):
    donor = tmp_path / "donor"
    donor.mkdir()
    strategy_store.append_store_row(donor, method_family="static-decompile",
                                    status="DONE", credit=1.0,
                                    arm_key="static-decompile|facts_snapshot|none|1")
    strategy_store.append_store_row(donor, method_family="obfuscation-peeling",
                                    status="DONE", credit=1.0,
                                    arm_key="obfuscation-peeling|facts_snapshot|none|1")
    receipt = strategy_store.PosteriorStrategyStore(workspace).method_sample("aaaaaaaaaaaa")
    assert receipt["candidates"]["static-decompile"]["posterior_store"]["rows"] == 1
    assert "obfuscation-peeling" not in receipt["candidates"]


@pytest.mark.parametrize("contents", [None, "{invalid: [yaml"])
def test_unknown_dynamic_authorization_is_not_support(workspace: Path, contents):
    spec = workspace / "task_spec.yaml"
    if contents is None:
        spec.unlink()
    else:
        spec.write_text(contents)
    sample = strategy_store.PosteriorStrategyStore(workspace).method_sample("aaaaaaaaaaaa")
    assert "dynamic-trace" not in sample["candidates"]
    rc, _, _ = sinks._method_family_gate(
        {"workspace": str(workspace)}, _prompt("dynamic-trace", "reason"),
        "C-001", "kunglao-worker", 1, ["grep"])
    assert rc == 2


def test_absent_intake_preserves_valid_history_fallback(tmp_path: Path, monkeypatch):
    ws = tmp_path / 'legacy'
    ws.mkdir()
    monkeypatch.setenv('KUNGLAO_POSTERIOR_STORE', str(tmp_path / 'isolated'))
    q_cells.append_observation(ws, 'aaaaaaaaaaaa', 'static-decompile', None,
                               source='dispatch')
    receipt = strategy_store.PosteriorStrategyStore(ws).method_sample('aaaaaaaaaaaa')
    assert receipt is not None
    assert receipt['family'] == 'static-decompile'
    assert receipt['candidate_sources']['static-decompile'] == ['history']


def test_corrupt_intake_does_not_activate_history_fallback(workspace: Path):
    (workspace / priors.SEED_REL).write_text('{invalid json')
    q_cells.append_observation(workspace, 'aaaaaaaaaaaa', 'static-decompile', None,
                               source='dispatch')
    assert strategy_store.PosteriorStrategyStore(workspace).method_sample('aaaaaaaaaaaa') is None
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt('static-decompile', 'reason'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc == 2


def test_uniform_host_probability_remains_known(workspace: Path, monkeypatch):
    from e2e import checkpoints

    monkeypatch.setenv('KUNGLAO_SCHEDULER', 'uniform')
    family, receipt = checkpoints._sample_envelope_family(workspace)
    checkpoints._stamp_ope_propensity(None, receipt, False, family, None)
    assert receipt['propensity'] == 1 / len(receipt['candidates'])
    assert receipt['probability_source'] == 'uniform_exact'


@pytest.mark.parametrize('settled', [False, True])
def test_multiround_host_executes_newly_evidenced_registered_method(
        workspace: Path, monkeypatch, settled):
    import random
    import time

    from e2e import checkpoints, llm_faces, model
    from rlvr import expansion

    priors.seed_intake_prior(workspace, families=['static-decompile'])
    monkeypatch.setattr(q_cells, 'q_cells_seed_state',
                        lambda _ws: (random.Random(3), 0))
    received = []

    class GatedWorker:
        def run(self, command, cwd=None, timeout=None):
            prompt = command[2]
            env = json.loads(prompt.splitlines()[0])['kunglao_dispatch']
            rc, family, _ = sinks._method_family_gate(
                {'workspace': str(workspace)}, prompt, 'C-001',
                'kunglao-worker', 1, env['tools'])
            assert rc is None, (family, prompt)
            received.append(env['method_family'])
            return model.CmdOutcome(rc=0, stdout='{"result":"STATUS: DONE"}', stderr='')

    worker = GatedWorker()
    run_state = model.RunState(
        run_id='pivot', unit='synthetic', family='synthetic',
        repo=str(Path(__file__).resolve().parents[1]), task_dir=str(workspace),
        ws=str(workspace), evidence_dir=str(workspace / 'evidence'),
        budget_seconds=60, llm_mode='auto', started_ts='t',
        started_monotonic=0.0, anchors={})
    face = llm_faces.AutoLlmFace(worker, Path(run_state.evidence_dir))
    ctx = checkpoints.RunContext(state=run_state, runner=worker, face=face,
                                 clock=time, sleep_fn=lambda _: None)
    first, handle = checkpoints._launch_dispatch(ctx, 'C-001', set())
    assert first is not None and first.method_family == 'static-decompile'
    face.run_dispatch(first, handle)
    if settled:
        assert q_cells.observe_settlement(workspace, 'C-001', 0.8)['matched']

    evidence = workspace / 'evidence' / 'observed-pair.json'
    evidence.write_text('{"input":"synthetic-a","output":"synthetic-b"}')
    ranked = expansion.admit([{
        'id': 'h-stage-2', 'family': 'dynamic-trace', 'p_llm': 0.4,
        'features': {'stage': 'observe-live'}}], [])
    doc = expansion.record_receipt(
        workspace, {'stage': 'observe-live', 'evidence': [str(evidence)]},
        ranked, ['h-stage-2'])
    sample = strategy_store.PosteriorStrategyStore(workspace).method_sample('aaaaaaaaaaaa')
    assert sample['candidates']['dynamic-trace']['weight'] > 0
    assert f"expansion_receipt:{doc['receipt']}" in sample['candidate_sources']['dynamic-trace']
    second, handle = checkpoints._launch_dispatch(ctx, 'C-001', set())
    assert second is not None and second.method_family == 'dynamic-trace'
    # The host-selected family reaches the gate without a fabricated override.
    face.run_dispatch(second, handle)
    assert received == ['static-decompile', 'dynamic-trace']
    assert q_cells.dispatch_rows(workspace)[-1]['method_family'] == 'dynamic-trace'


def test_declared_override_requires_caller_rationale(workspace: Path, monkeypatch):
    import random
    import time

    from e2e import checkpoints, llm_faces, model

    monkeypatch.setattr(q_cells, 'q_cells_seed_state',
                        lambda _ws: (random.Random(3), 0))
    sampled, _ = checkpoints._sample_envelope_family(workspace)
    actual = ({'static-decompile', 'dynamic-trace'} - {sampled}).pop()

    class Runner:
        def run(self, *args, **kwargs):
            return model.CmdOutcome(rc=0, stdout='{"result":"STATUS: DONE"}', stderr='')

    runner = Runner()
    run_state = model.RunState(
        run_id='override', unit='synthetic', family='synthetic',
        repo=str(Path(__file__).resolve().parents[1]), task_dir=str(workspace),
        ws=str(workspace), evidence_dir=str(workspace / 'evidence'),
        budget_seconds=60, llm_mode='auto', started_ts='t',
        started_monotonic=0.0, anchors={})
    run_state.method_family = actual
    face = llm_faces.AutoLlmFace(runner, Path(run_state.evidence_dir))
    ctx = checkpoints.RunContext(state=run_state, runner=runner, face=face,
                                 clock=time, sleep_fn=lambda _: None)
    request, _ = checkpoints._launch_dispatch(ctx, 'C-001', set())
    prompt = Path(request.prompt_file).read_text(encoding='utf-8')
    view = strategy_store.reconcile_declaration(workspace, actual)
    assert view['deviates'] and view['supported']
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, prompt, 'C-001',
        'kunglao-worker', 1, ['grep', 'python3'])
    assert rc == 2
    # The live orchestrator supplies this line in the Agent prompt. The
    # checkpoint harness has no caller rationale input and does not add it.
    reasoned = prompt + '\nagent-reasoning: observed evidence requires independent observation\n'
    rc, family, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, reasoned, 'C-001',
        'kunglao-worker', 1, ['grep', 'python3'])
    assert rc is None and family == actual


def test_missing_reason_cannot_override_current_sample(workspace: Path):
    from rlvr import state

    fp = state.signature_hash(state.snapshot(workspace))
    sampled = strategy_store.PosteriorStrategyStore(workspace).method_sample(fp)['family']
    other = ({'static-decompile', 'dynamic-trace'} - {sampled}).pop()
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt(other), 'C-001',
        'kunglao-worker', 1, ['grep'])
    assert rc == 2


def test_other_escape_preserves_validation_without_adding_mass(workspace: Path):
    before = strategy_store.PosteriorStrategyStore(workspace).method_sample('aaaaaaaaaaaa')
    rc, family, view = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt('other(custom recorded-pair derivation)'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc is None and family == 'other(custom recorded-pair derivation)'
    assert view['propensity'] is None
    assert view['supported'] is False
    assert view['candidates'] == before['candidates']
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt('other()'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc == 2


def test_invalid_expansion_token_never_receives_mass(workspace: Path):
    from rlvr import expansion

    bad = 'invalid_token!'
    ranked = expansion.admit([{'id': 'bad', 'family': bad, 'p_llm': 0.5,
                                'features': {'stage': 'different'}}], [])
    doc = expansion.record_receipt(workspace, {'obstacle_count': 2}, ranked, ['bad'])
    assert expansion.register_admitted(workspace, doc) == []
    receipt = strategy_store.PosteriorStrategyStore(workspace).method_sample('aaaaaaaaaaaa')
    assert bad not in receipt['candidates']
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt(bad, 'a reason'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc == 2


def test_actual_unavailable_tool_is_rejected_at_dispatch_boundary(workspace: Path):
    from datetime import datetime, timezone

    import dispatch_gate

    (workspace / 'runs' / 'env-state.json').write_text(json.dumps({
        'ts': datetime.now(timezone.utc).isoformat(),
        'per_capability': {'frida_server': {'status': 'fail',
                                          'detail': 'synthetic connection refused'}}}))
    prompt = _prompt('dynamic-trace', 'live observation')
    envelope = json.loads(prompt.splitlines()[0])
    envelope['kunglao_dispatch']['tools'] = ['frida']
    prompt = json.dumps(envelope) + '\nfacts-snapshot: 0 facts\n'
    assert dispatch_gate._lane_capability_gate(workspace, 'C-001', prompt) == 2


def test_duplicate_expansion_admission_does_not_duplicate_weight(workspace: Path):
    from rlvr import expansion

    ranked = expansion.admit([{'id': 'h1', 'family': 'dynamic-trace', 'p_llm': 0.4,
                                'features': {'stage': 'different'}}], [])
    doc = expansion.record_receipt(workspace, {}, ranked, ['h1'])
    before = strategy_store.PosteriorStrategyStore(workspace).proposal_prior_labeled()
    expansion.record_receipt(workspace, {}, ranked, ['h1'])
    after = strategy_store.PosteriorStrategyStore(workspace).proposal_prior_labeled()
    assert before == after
    (workspace / 'runs' / 'expansion' / f"{doc['receipt']}.json").write_text('{corrupt')
    assert strategy_store.PosteriorStrategyStore(workspace).proposal_prior_labeled() == after


def test_host_observation_records_its_actual_draw(workspace: Path, monkeypatch):
    import time

    from e2e import checkpoints, llm_faces, model

    class Worker:
        def run(self, command, cwd=None, timeout=None):
            return model.CmdOutcome(rc=0, stdout='{"result":"STATUS: DONE"}', stderr='')

    worker = Worker()
    run_state = model.RunState(
        run_id='attribution', unit='synthetic', family='synthetic',
        repo=str(Path(__file__).resolve().parents[1]), task_dir=str(workspace),
        ws=str(workspace), evidence_dir=str(workspace / 'evidence'),
        budget_seconds=60, llm_mode='auto', started_ts='t',
        started_monotonic=0.0, anchors={})
    face = llm_faces.AutoLlmFace(worker, Path(run_state.evidence_dir))
    ctx = checkpoints.RunContext(state=run_state, runner=worker, face=face,
                                 clock=time, sleep_fn=lambda _: None)
    # The host has its own keyed draw; a separate, unkeyed production
    # reconciliation cannot stand in for the decision it actually made.
    monkeypatch.setattr(strategy_store, 'reconcile_declaration',
                        lambda *_: {'sampled_family': 'unrelated-draw',
                                    'propensity': None})
    request, _ = checkpoints._launch_dispatch(ctx, 'C-001', set())
    row = q_cells.dispatch_rows(workspace)[-1]
    assert row['sampled_family'] == request.method_family
    assert row['conditional_sampler_weight'] > 0
    assert row['candidate_sources'][request.method_family]
    assert 'family_override' not in row


def test_unreadable_history_does_not_erase_valid_current_support(workspace: Path, monkeypatch):
    def unreadable(_self):
        raise OSError('synthetic unreadable history')

    monkeypatch.setattr(strategy_store.PosteriorStrategyStore, '_proposal_prior', unreadable)
    receipt = strategy_store.PosteriorStrategyStore(workspace).method_sample('aaaaaaaaaaaa')
    assert set(receipt['candidates']) == {'static-decompile', 'dynamic-trace'}
    assert all('history_weight' not in sources
               for sources in receipt['candidate_sources'].values())


def test_deleted_intake_cannot_restore_history_support(workspace: Path):
    q_cells.append_observation(workspace, 'aaaaaaaaaaaa', 'dynamic-trace', None,
                               source='dispatch')
    (workspace / priors.SEED_REL).unlink()
    assert strategy_store.PosteriorStrategyStore(workspace).method_sample('aaaaaaaaaaaa') is None
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt('dynamic-trace', 'new evidence'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc == 2


def test_tiny_positive_support_survives_receipt_precision(workspace: Path):
    path = workspace / priors.SEED_REL
    doc = json.loads(path.read_text())
    doc['families']['dynamic-trace'].update(alpha=1e-9, beta=1.0)
    path.write_text(json.dumps(doc))
    view = strategy_store.reconcile_declaration(workspace, 'dynamic-trace')
    assert view['supported'] is True
    assert view['conditional_sampler_weight'] > 0
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt('dynamic-trace', 'independent observation'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc is None


@pytest.mark.parametrize('independent_intake', [False, True])
def test_expansion_evidence_withdrawal_removes_only_its_source(workspace: Path, independent_intake):
    from rlvr import expansion

    if not independent_intake:
        priors.seed_intake_prior(workspace, families=['static-decompile'])
    evidence = workspace / 'observed-pair.json'
    evidence.write_text('{"input":"a","output":"b"}')
    ranked = expansion.admit([{'id': 'h1', 'family': 'dynamic-trace', 'p_llm': 0.4,
                                'features': {'stage': 'observe-live'}}], [])
    expansion.record_receipt(workspace, {'evidence': ['observed-pair.json']}, ranked, ['h1'])
    store = strategy_store.PosteriorStrategyStore(workspace)
    assert 'expansion' in store.method_sample('aaaaaaaaaaaa')['candidate_sources']['dynamic-trace']
    evidence.unlink()
    after = store.method_sample('aaaaaaaaaaaa')
    sources = after['candidate_sources'].get('dynamic-trace', [])
    assert 'expansion' not in sources
    assert not any(source.startswith('expansion_receipt:') for source in sources)
    assert ('dynamic-trace' in after['candidates']) is independent_intake
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt('dynamic-trace', 'independent observation'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc is None if independent_intake else rc == 2


def test_support_marker_failure_prevents_source_publication(tmp_path: Path, monkeypatch):
    from rlvr import expansion

    ws = tmp_path / 'case'
    ws.mkdir()
    (ws / 'task_spec.yaml').write_text('family: static-replay\n')
    original_touch = Path.touch

    def deny_marker(path, *args, **kwargs):
        if path == ws / priors.SUPPORT_MODE_REL:
            raise OSError('synthetic marker write denied')
        return original_touch(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'touch', deny_marker)
    assert priors.seed_intake_prior(ws, families=['static-decompile']) == {}
    assert not (ws / priors.SEED_REL).exists()
    with pytest.raises(OSError, match='marker write denied'):
        expansion.record_receipt(ws, {}, [], [])
    assert not list((ws / expansion.RECEIPT_DIR).glob('E-*.json'))


def test_malformed_expansion_path_cannot_bypass_support_gate(workspace: Path):
    from rlvr import expansion

    priors.seed_intake_prior(workspace, families=['static-decompile'])
    expansion.record_receipt(workspace, {'evidence': ['bad\x00path']}, [], [])
    view = strategy_store.reconcile_declaration(workspace, 'dynamic-trace')
    assert view['supported'] is False
    assert view['sampled_family'] == 'static-decompile'
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt('dynamic-trace', 'reason'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc == 2


@pytest.mark.parametrize('evidence_mode', [True, False])
def test_reconcile_error_preserves_current_mode_boundary(workspace: Path, monkeypatch, evidence_mode):
    if not evidence_mode:
        (workspace / priors.SEED_REL).unlink()
        (workspace / priors.SUPPORT_MODE_REL).unlink()

    def broken_sample(*_args, **_kwargs):
        raise ValueError('synthetic sampler failure')

    monkeypatch.setattr(strategy_store.PosteriorStrategyStore, 'method_sample', broken_sample)
    view = strategy_store.reconcile_declaration(workspace, 'static-decompile')
    if evidence_mode:
        assert view['supported'] is False
        assert view['support_error'] == 'ValueError'
    else:
        assert 'supported' not in view
    rc, _, _ = sinks._method_family_gate(
        {'workspace': str(workspace)}, _prompt('static-decompile', 'reason'),
        'C-001', 'kunglao-worker', 1, ['grep'])
    assert rc == 2 if evidence_mode else rc is None
