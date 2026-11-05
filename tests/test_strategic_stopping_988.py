# -*- coding: utf-8 -*-
"""Strategic action, route ledger, and externally checkable stopping.

Pins the three faces the episode-disposition algebra needed to become
operational:

  - ``rlvr.strategic_action`` records FIGHT / BYPASS / INVEST with its
    propensity through the unified experience ledger; an episode with no
    recorded action reads as SURRENDER (the classifier's fall-through).
  - ``rlvr.route_ledger`` owns ``runs/rt-tests/<claim>/routes.json``:
    declared routes come from the per-claim-kind ``routes:`` section of
    ``references/schemas/machine_check_map.yaml``, every attempt carries a
    machine command + a content-addressed artifact, and the fixed
    ``ROUTE_ATTEMPT_BUDGET`` bounds the attempts. A missing, partial,
    budget-mismatched or non-reproducible ledger can never yield
    ATTEMPTED_EXHAUSTED.
  - ``rlvr.stopping.may_terminate`` is the pure externally-checkable stop
    checker: only ledger coverage / corroborated session-bound wall /
    spent budget return True; surrogate signals (stagnation, early-failure
    prediction, effort heuristics) never do.

The end-to-end case closes the chain: route attempts -> strategic action ->
stop check -> ``disposition.build_row`` -> ``write_row`` (row file + the
unified telemetry mirror + the registered events).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import action_space  # noqa: E402  (the STRATEGIC vocabulary owner)
import kunglao_verify as kv  # noqa: E402
from rlvr import consolidated_ledger, disposition  # noqa: E402
from rlvr import route_ledger, stopping, strategic_action  # noqa: E402

TS = "2026-11-05T12:00:00Z"


# ---------- helpers ----------

def _write_artifact(tmp_path: Path, rel: str, data: bytes) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _machine_cmd() -> str:
    return "sha256sum runs/rt-tests/C-004/attempt-1.txt"


def _artifact_attempt(tmp_path: Path, *, route: str = "disasm_constant_check",
                      rel: str = "runs/rt-tests/C-004/attempt-1.txt",
                      data: bytes = b"4d5a\n", digest: str | None = None
                      ) -> dict:
    _write_artifact(tmp_path, rel, data)
    return {
        "route": route,
        "command": _machine_cmd(),
        "artifact": rel,
        "artifact_sha256": digest if digest is not None else _sha(data),
    }


def _ledger(tmp_path: Path, attempts: list[dict], *,
            claim: str = "C-004", claim_kind: str = "static_constant",
            declared: list[str] | None = None,
            extra: dict | None = None) -> dict:
    doc = {
        "schema": route_ledger.SCHEMA,
        "claim": claim,
        "claim_kind": claim_kind,
        "declared_routes": (declared if declared is not None
                            else list(route_ledger.declared_routes(
                                claim_kind))),
        "attempts": attempts,
    }
    if extra:
        doc.update(extra)
    path = route_ledger.ledger_path(tmp_path, claim)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def _auth_scope() -> dict:
    return {"targets": ["target.example"],
            "authorization_ref": "ticket-988"}


# ---------- strategic action: vocabulary + propensity ----------

def test_strategic_vocabulary_comes_from_action_space():
    """The words are the action_space STRATEGIC level, not a copy."""
    specs = action_space.actions_of(action_space.STRATEGIC)
    expected = tuple(sorted(s.name.split(".", 1)[1].upper() for s in specs))
    assert tuple(sorted(strategic_action.STRATEGIC_ACTIONS)) == expected
    assert set(strategic_action.STRATEGIC_ACTIONS) == {"FIGHT", "BYPASS",
                                                       "INVEST"}
    # the classifier's contract holds the same three words
    assert tuple(strategic_action.STRATEGIC_ACTIONS) == \
        disposition.STRATEGIC_ACTIONS


def test_record_writes_strategic_action_row_with_propensity(tmp_path):
    result = strategic_action.record(
        tmp_path, episode_id="ep-1", claim="C-004", action="FIGHT",
        propensity=0.62, ts=TS)

    row = result["row"]
    assert row["schema"] == "strategic-action/1"
    assert row["action"] == "FIGHT"
    assert row["propensity"] == 0.62
    assert result["appended"] is True

    rows = consolidated_ledger.read(
        tmp_path, "experience", schema_prefix="strategic-action/")
    assert rows == [row]


def test_record_requires_propensity_in_unit_interval():
    for bad in (-0.01, 1.01, "0.5", True, None):
        with pytest.raises(strategic_action.StrategicActionError):
            strategic_action.build_row(
                episode_id="ep-1", claim="C-004", action="FIGHT",
                propensity=bad, ts=TS)


def test_record_rejects_unknown_action():
    with pytest.raises(strategic_action.StrategicActionError):
        strategic_action.build_row(
            episode_id="ep-1", claim="C-004", action="GIVE_UP",
            propensity=0.5, ts=TS)


def test_absence_of_action_maps_to_surrender():
    assert strategic_action.effective_action(None) == "SURRENDER"
    assert strategic_action.effective_action("BYPASS") == "BYPASS"
    with pytest.raises(strategic_action.StrategicActionError):
        strategic_action.effective_action("PANIC")


def test_identical_replay_is_idempotent_divergent_is_refused(tmp_path):
    first = strategic_action.record(
        tmp_path, episode_id="ep-1", claim="C-004", action="INVEST",
        propensity=0.4, ts=TS)
    again = strategic_action.record(
        tmp_path, episode_id="ep-1", claim="C-004", action="INVEST",
        propensity=0.4, ts=TS)
    assert first["appended"] is True
    assert again["appended"] is False
    assert len(strategic_action.read(tmp_path)) == 1

    with pytest.raises(strategic_action.StrategicActionError):
        strategic_action.record(
            tmp_path, episode_id="ep-1", claim="C-004", action="FIGHT",
            propensity=0.9, ts=TS)


def test_disposition_fields_carry_the_action_and_propensity(tmp_path):
    row = strategic_action.record(
        tmp_path, episode_id="ep-1", claim="C-004", action="BYPASS",
        propensity=0.25, ts=TS)["row"]
    assert strategic_action.disposition_fields(row) == {
        "strategic_action": "BYPASS", "propensity": 0.25}


# ---------- stopping: the external-evidence matrix ----------

def test_stopping_accepts_complete_route_ledger():
    ledger = {"routes": ["r1", "r2"], "attempted": ["r1", "r2"],
              "budget": route_ledger.ROUTE_ATTEMPT_BUDGET,
              "budget_exhausted": False}
    assert stopping.may_terminate({"ledger": ledger}) is True


def test_stopping_accepts_corroborated_session_bound_wall():
    wall = {"session_bound": True, "corroborated": True}
    assert stopping.may_terminate({"wall": wall}) is True


def test_stopping_accepts_spent_budget():
    assert stopping.may_terminate(
        {"budget": {"spent": 7200, "limit": 7200}}) is True
    assert stopping.may_terminate(
        {"budget": {"spent": 7300, "limit": 7200}}) is True


def test_stopping_rejects_partial_evidence():
    assert stopping.may_terminate({"budget": {"spent": 7199,
                                              "limit": 7200}}) is False
    assert stopping.may_terminate(
        {"wall": {"session_bound": True, "corroborated": False}}) is False
    assert stopping.may_terminate(
        {"wall": {"session_bound": False, "corroborated": True}}) is False
    assert stopping.may_terminate(
        {"ledger": {"routes": ["r1", "r2"], "attempted": ["r1"],
                    "budget": 3, "budget_exhausted": False}}) is False


@pytest.mark.parametrize("signal", sorted(stopping.SURROGATE_SIGNALS))
def test_stopping_rejects_every_surrogate_signal(signal):
    """A surrogate alone never terminates, however it is spelled."""
    assert stopping.may_terminate({signal: True}) is False
    assert stopping.may_terminate(
        {signal: {"score": 0.99, "fired": True}}) is False


def test_stopping_rejects_surrogates_even_when_combined():
    record = {signal: True for signal in stopping.SURROGATE_SIGNALS}
    assert stopping.may_terminate(record) is False


def test_stopping_fails_closed_on_malformed_records():
    for bad in (None, [], "stop", 42):
        assert stopping.may_terminate(bad) is False


def test_stopping_reports_which_external_legs_paid():
    assert stopping.stop_reasons({"wall": {"session_bound": True,
                                           "corroborated": True}}) == ("wall",)
    assert stopping.stop_reasons({"stagnation": True}) == ()


# ---------- route ledger: the map contract ----------

def test_every_claim_kind_declares_routes():
    route_map = route_ledger.route_map()
    assert route_map, "machine_check_map.yaml must carry a routes: section"
    kinds = kv.load_machine_check_map().get("claim_kinds") or {}
    assert set(route_map) == set(kinds), (
        "routes: must be keyed on exactly the declared claim_kinds")
    for kind, routes in route_map.items():
        assert routes, f"claim kind {kind!r} has no declared route"


def test_unknown_claim_kind_fails_closed():
    with pytest.raises(route_ledger.RouteLedgerError):
        route_ledger.declared_routes("no_such_kind")


def test_missing_ledger_cannot_claim_exhaustion(tmp_path):
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["routes"] == []
    assert result["budget_exhausted"] is False
    verdict = disposition.classify_episode({
        "authorized": True, "ledger": result, "oracle_pass": False,
        "act_outcomes": [], "session": {}, "completion_claimed": False})
    assert verdict["disposition"] == "SURRENDER"


def test_declared_routes_mismatch_fails_closed(tmp_path):
    _ledger(tmp_path, [_artifact_attempt(tmp_path)], declared=["r1", "r2"])
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["routes"] == []
    assert result["budget_exhausted"] is False
    assert any("declared" in err for err in result["errors"])


def test_partial_ledger_is_not_exhausted(tmp_path):
    # the ledger declares the map's routes but no attempt has landed yet
    _ledger(tmp_path, [])
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["routes"] == ["disasm_constant_check"]
    assert result["attempted"] == []
    assert result["budget_exhausted"] is False
    assert disposition.classify_episode({
        "authorized": True, "ledger": result, "oracle_pass": False,
        "act_outcomes": [], "session": {}, "completion_claimed": False}
    )["disposition"] == "SURRENDER"


def test_complete_reproducible_ledger_is_exhausted(tmp_path):
    _ledger(tmp_path, [_artifact_attempt(tmp_path)])
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["routes"] == ["disasm_constant_check"]
    assert result["attempted"] == ["disasm_constant_check"]
    assert result["budget_exhausted"] is False
    assert disposition.classify_episode({
        "authorized": True, "ledger": result, "oracle_pass": False,
        "act_outcomes": [], "session": {}, "completion_claimed": False}
    )["disposition"] == "ATTEMPTED_EXHAUSTED"


def test_tampered_artifact_breaks_reproducibility(tmp_path):
    attempt = _artifact_attempt(tmp_path, digest="0" * 64)
    _ledger(tmp_path, [attempt])
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["attempted"] == []
    assert result["budget_exhausted"] is False
    assert any("reproduc" in err for err in result["errors"])


def test_missing_artifact_breaks_reproducibility(tmp_path):
    attempt = _artifact_attempt(tmp_path)
    (tmp_path / attempt["artifact"]).unlink()
    _ledger(tmp_path, [attempt])
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["attempted"] == []


def test_prose_command_is_not_a_machine_route_attempt(tmp_path):
    attempt = _artifact_attempt(tmp_path)
    attempt["command"] = "I looked at the decompiler and it looks right"
    _ledger(tmp_path, [attempt])
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["attempted"] == []


def test_budget_field_mismatch_fails_closed(tmp_path):
    _ledger(tmp_path, [_artifact_attempt(tmp_path)],
            extra={"budget": route_ledger.ROUTE_ATTEMPT_BUDGET + 1})
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["routes"] == []
    assert result["budget_exhausted"] is False
    assert any("budget" in err for err in result["errors"])


def test_attempts_beyond_the_budget_fail_closed(tmp_path):
    attempts = [
        _artifact_attempt(tmp_path, rel=f"runs/rt-tests/C-004/attempt-{i}.txt",
                          data=f"out-{i}".encode())
        for i in range(route_ledger.ROUTE_ATTEMPT_BUDGET + 1)
    ]
    _ledger(tmp_path, attempts)
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["routes"] == []
    assert result["budget_exhausted"] is False


def test_spent_budget_is_exhaustion(tmp_path):
    # the fixed budget spent across reproducible attempts: the budget leg
    # pays even when the attempts do not cover a multi-route declaration
    attempts = [
        _artifact_attempt(tmp_path, rel=f"runs/rt-tests/C-004/a{i}.txt",
                          data=f"x{i}".encode())
        for i in range(route_ledger.ROUTE_ATTEMPT_BUDGET)
    ]
    _ledger(tmp_path, attempts)
    result = route_ledger.classify(tmp_path, "C-004")
    assert result["budget_exhausted"] is True
    assert disposition.classify_episode({
        "authorized": True, "ledger": result, "oracle_pass": False,
        "act_outcomes": [], "session": {}, "completion_claimed": False}
    )["disposition"] == "ATTEMPTED_EXHAUSTED"


def test_record_attempt_writes_declared_ledger_and_sha(tmp_path):
    data = b"4d5a\n"
    artifact = _write_artifact(tmp_path, "runs/rt-tests/C-004/attempt-1.txt",
                               data)
    written = route_ledger.record_attempt(
        tmp_path, claim="C-004", claim_kind="static_constant",
        route="disasm_constant_check", command=_machine_cmd(),
        artifact=artifact)
    assert written["declared_routes"] == ["disasm_constant_check"]
    assert written["attempts"][0]["artifact_sha256"] == _sha(data)

    result = route_ledger.classify(tmp_path, "C-004")
    assert result["attempted"] == ["disasm_constant_check"]


def test_record_attempt_rejects_undeclared_route(tmp_path):
    artifact = _write_artifact(tmp_path, "runs/rt-tests/C-004/attempt-1.txt",
                               b"4d5a\n")
    with pytest.raises(route_ledger.RouteLedgerError):
        route_ledger.record_attempt(
            tmp_path, claim="C-004", claim_kind="static_constant",
            route="make_it_up", command=_machine_cmd(), artifact=artifact)


def test_record_attempt_refuses_past_the_fixed_budget(tmp_path):
    for i in range(route_ledger.ROUTE_ATTEMPT_BUDGET):
        artifact = _write_artifact(
            tmp_path, f"runs/rt-tests/C-004/a{i}.txt", f"x{i}".encode())
        route_ledger.record_attempt(
            tmp_path, claim="C-004", claim_kind="static_constant",
            route="disasm_constant_check", command=_machine_cmd(),
            artifact=artifact)
    artifact = _write_artifact(tmp_path, "runs/rt-tests/C-004/extra.txt",
                               b"extra")
    with pytest.raises(route_ledger.RouteLedgerError):
        route_ledger.record_attempt(
            tmp_path, claim="C-004", claim_kind="static_constant",
            route="disasm_constant_check", command=_machine_cmd(),
            artifact=artifact)


# ---------- end-to-end: disposition chain ----------

def _episode_record(tmp_path: Path, *, ledger: dict,
                    strategic: dict | None) -> dict:
    record = {
        "claim": "C-004",
        "authorized": True,
        "authorization": _auth_scope(),
        "target": "target.example",
        "authorization_ref": "ticket-988",
        "oracle_pass": False,
        "wall": None,
        "ledger": ledger,
        "route_ledger_ref": "runs/rt-tests/C-004/routes.json",
        "act_outcomes": [],
        "session": {"returncode": None, "timed_out": False,
                    "liveness": None},
        "strategic_action": None,
        "propensity": None,
        "completion_claimed": False,
    }
    if strategic is not None:
        record.update(strategic_action.disposition_fields(strategic))
    return record


def test_e2e_exhausted_chain_persists_the_disposition_row(tmp_path):
    # 1. route attempt: a machine command + a content-addressed artifact
    data = b"4d5a\n"
    artifact = _write_artifact(tmp_path, "runs/rt-tests/C-004/attempt-1.txt",
                               data)
    route_ledger.record_attempt(
        tmp_path, claim="C-004", claim_kind="static_constant",
        route="disasm_constant_check", command=_machine_cmd(),
        artifact=artifact)
    ledger = route_ledger.classify(tmp_path, "C-004")

    # 2. strategic action before termination, with its propensity
    action_row = strategic_action.record(
        tmp_path, episode_id="ep-988", claim="C-004", action="FIGHT",
        propensity=0.7, ts=TS)["row"]

    # 3. the stop check is evidence-backed (ledger coverage, budget unspent)
    assert stopping.may_terminate(
        {"ledger": ledger, "wall": None,
         "budget": {"spent": 60, "limit": 7200}}) is True

    # 4. the classifier reads the same evidence
    record = _episode_record(tmp_path, ledger=ledger, strategic=action_row)
    row = disposition.build_row(record, episode_id="ep-988", ts=TS)
    assert row["disposition"] == "ATTEMPTED_EXHAUSTED"
    assert row["strategic_action"] == "FIGHT"
    assert row["propensity"] == 0.7
    assert row["budget"] == route_ledger.ROUTE_ATTEMPT_BUDGET

    # 5. the row persists (file + telemetry mirror + registered events)
    written = disposition.write_row(tmp_path, record, episode_id="ep-988",
                                    ts=TS)
    assert written["created"] is True
    persisted = json.loads(
        (tmp_path / "runs" / "disposition" / "ep-988.json").read_text(
            encoding="utf-8"))
    assert persisted["disposition"] == "ATTEMPTED_EXHAUSTED"
    telemetry = consolidated_ledger.read(
        tmp_path, "telemetry", schema_prefix="disposition/")
    assert [r for r in telemetry if r["episode_id"] == "ep-988"] == [row]

    events = []
    for path in sorted((tmp_path / "runs" / "logs").glob("kunglao-*.jsonl")):
        events.extend(json.loads(line) for line in
                      path.read_text(encoding="utf-8").splitlines()
                      if line.strip())
    actions = [e.get("action") for e in events]
    assert "disposition_recorded" in actions
    assert "strategic_action_recorded" in actions


def test_e2e_surrender_chain_without_a_recorded_action(tmp_path):
    # no ledger (nothing attempted) and no strategic action recorded
    ledger = route_ledger.classify(tmp_path, "C-004")
    record = _episode_record(tmp_path, ledger=ledger, strategic=None)
    record["route_ledger_ref"] = None

    assert stopping.may_terminate(
        {"ledger": ledger, "wall": None,
         "budget": {"spent": 5, "limit": 7200}}) is False
    row = disposition.build_row(record, episode_id="ep-989", ts=TS)
    assert row["disposition"] == "SURRENDER"
    assert row["strategic_action"] is None
    assert strategic_action.effective_action(row["strategic_action"]) == \
        "SURRENDER"


def test_uncorroborated_wall_refusal_is_surrender_not_censored(tmp_path):
    """A refusal/abandonment without a corroborated wall never censors."""
    record = _episode_record(tmp_path, ledger=route_ledger.classify(
        tmp_path, "C-004"), strategic=None)
    record["route_ledger_ref"] = None
    record["wall"] = {"session_bound": True, "corroborated": False}
    row = disposition.build_row(record, episode_id="ep-990", ts=TS)
    assert row["disposition"] == "SURRENDER"
    assert row["disposition"] != "CENSORED_ENV"


def test_legacy_agent_death_is_failed_not_censored():
    """The evidence-free legacy residual can no longer read as censored."""
    assert disposition.legacy_disposition("agent_death", False) == "FAILED"
    assert disposition.legacy_disposition("censored_env", False) == \
        "CENSORED_ENV"


# ---------- the loop-facing stop site (e2e/checkpoints) ----------

def _loop_ctx(tmp_path: Path, *, tick_rc: int):
    """The minimal RunContext `_tick_prelude` needs (no eval corpus)."""
    from e2e import model
    from e2e.runtime import RunContext

    class _Runner:
        def __init__(self):
            self.calls: list[str] = []

        def py_cmd(self, script, *args):
            self.calls.append(str(script))
            return [str(script), *[str(a) for a in args]]

        def run(self, cmd, cwd=None, timeout=None, **_):
            return model.CmdOutcome(rc=tick_rc, stdout="", stderr="")

    class _Clock:
        def monotonic(self):
            return 1000.0

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    state = model.RunState(
        run_id="r988", unit="py-derive-v1", family="smoke",
        repo=str(tmp_path), task_dir=str(tmp_path), ws=str(ws),
        evidence_dir=str(tmp_path / "ev"), budget_seconds=10_000,
        llm_mode="dry", started_ts="2026-11-05T12:00:00Z",
        started_monotonic=1000.0, anchors={})
    return RunContext(state=state, runner=_Runner(), face=None,
                      clock=_Clock(), sleep_fn=lambda _s: None)


def _audit_actions(ctx) -> list[str]:
    path = ctx.ws / "runs" / "logs" / "e2e-audit.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line).get("action")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_idle_breaker_stop_is_refused_without_external_evidence(tmp_path):
    from e2e import checkpoints

    ctx = _loop_ctx(tmp_path, tick_rc=2)
    detail = {"ticks": 1}
    terminal, out_tick, _ms = checkpoints._tick_prelude(ctx, detail, 0)

    assert terminal is None, "a stagnation surrogate must not terminate"
    assert out_tick.rc == 2
    assert "stop_refused" in _audit_actions(ctx)


def test_idle_breaker_stop_is_allowed_by_complete_route_ledger(tmp_path):
    from e2e import checkpoints, model

    ctx = _loop_ctx(tmp_path, tick_rc=2)
    artifact = _write_artifact(ctx.ws, "runs/rt-tests/C-004/attempt-1.txt",
                               b"4d5a\n")
    route_ledger.record_attempt(
        ctx.ws, claim="C-004", claim_kind="static_constant",
        route="disasm_constant_check", command=_machine_cmd(),
        artifact=artifact)

    terminal, _out_tick, _ms = checkpoints._tick_prelude(
        ctx, {"ticks": 1}, 0)
    assert terminal is not None
    assert terminal.status == model.BLOCKED
    assert terminal.detail["stop_class"] == "idle-circuit-breaker"
    assert terminal.detail["stop_reasons"] == ["ledger"]


def test_budget_exhaustion_remains_a_legitimate_stop(tmp_path):
    from e2e import checkpoints, model

    ctx = _loop_ctx(tmp_path, tick_rc=2)
    # the budget guard still passes (spent < limit); the record's own
    # budget face is what the checker examines — pin it directly here
    ctx.state.budget_consumed_seconds = ctx.state.budget_seconds
    terminal, _out_tick, _ms = checkpoints._tick_prelude(
        ctx, {"ticks": 1}, 0)
    # the guard fires first on a fully spent budget (the legitimate stop)
    assert terminal is not None
    assert terminal.status == model.BLOCKED
    assert terminal.detail["stop_class"] == "budget-exhausted"
