# -*- coding: utf-8 -*-
"""online-distillation wiring + fixture e2e (the full chain, dry mode).

What this file pins, per the online-distillation spec:
  - the three audit words ride BOTH vocabularies and the 17-field row
    shape holds (e2e stream + production emit vocabulary);
  - the dry LLM face answers a kunglao-distill dispatch by staging a
    REAL report + a REAL parameter-recovery candidate;
  - the e2e tick step fires the whole chain on a genuine miss:
    marker -> budget -> act -> validated report -> oracle on the
    anchored bytes -> run-local landing -> complete audit trail;
  - the negative: no marker anywhere means no distill act at all;
  - the fixture sample is a GENUINE shelf miss (the parameter sweep
    over the registered crypto algorithms never recovers it);
  - the production SubagentStop closure stamps the trigger + emits the
    production trigger row, fail-open;
  - the worker documentation names the run-local tool shelf.

The fixture lives in tests/fixtures/distill-458/ (generator + sample +
expected digests); zero real-sample bytes anywhere.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "distill-458"
for p in (str(SCRIPTS),):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import audit, checkpoints, llm_faces, model  # noqa: E402
import online_distill as od  # noqa: E402

ANCHORS = {
    "goal_verbatim": "Recover the transform and decode target/blob.bin.",
    "success_criterion": "The decoded plaintext matches the expected digest.",
    "verification_method": "reproduction",
}


def _mk_ctx(tmp_path: Path, mode: str = "dry"):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    ev_dir = tmp_path / "ev"
    ev_dir.mkdir(parents=True, exist_ok=True)
    state = model.RunState(
        run_id="r1", unit="distill-fixture", family="smoke",
        repo=str(ROOT), task_dir=str(ROOT / "eval/v1/tasks/smoke"),
        ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
        llm_mode=mode, started_ts="t", started_monotonic=0.0,
        anchors=dict(ANCHORS))
    runner = llm_faces.CommandRunner(ROOT)
    face = llm_faces.face_for(mode, runner, ev_dir)
    return checkpoints.RunContext(
        state=state, runner=runner, face=face,
        clock=_FakeClock(), sleep_fn=lambda _s: None)


class _FakeClock:
    def monotonic(self) -> float:
        return 0.0


def _stage_fixture_ws(ws: Path) -> None:
    """The fixture workspace: sample under bins/ + a fresh shelf-miss
    marker (exactly what a real worker that read the whole tool index
    would leave behind)."""
    (ws / "bins").mkdir(exist_ok=True)
    (ws / "bins" / "blob.bin").write_bytes(
        (FIXTURE / "sample.blob").read_bytes())
    (ws / "runs" / "worker-status-C-004.md").write_text(
        "# worker status\nstatus: BLOCKED\n"
        "shelf-miss: crypto:decode sample=bins/blob.bin\n",
        encoding="utf-8")


def _audit_rows(ws: Path) -> list[dict]:
    path = audit.audit_path(ws)
    assert path.is_file(), f"missing unified audit stream: {path}"
    return [json.loads(ln) for ln
            in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------


class TestDistillVocabulary:
    def test_three_words_in_e2e_vocabulary_and_category(self):
        for word in ("distill_attempt", "distill_result",
                     "candidate_landed"):
            assert word in audit.AUDIT_ACTIONS
        assert "distill" in audit.CATEGORIES
        assert audit._category("distill_attempt") == "distill"
        assert audit._category("candidate_landed") == "distill"

    def test_three_words_in_production_emit_vocabulary(self):
        import event_taxonomy
        for word in ("distill_attempt", "distill_result",
                     "candidate_landed"):
            assert word in event_taxonomy.EMIT_ACTIONS

    def test_emitter_rows_carry_the_17_field_schema(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert audit.emit_distill_attempt(
            str(ws), "attempt-1", phase="dispatched",
            trigger={"kind": "shelf-miss", "token": "crypto:decode"},
            budget={"per_run_used": 1})
        (row,) = _audit_rows(ws)
        assert len(row) == 17
        assert row["action"] == "distill_attempt"
        assert set(row) == {
            "ts", "actor", "action", "claim", "tool", "artifact",
            "duration_ms", "exit", "detail", "arm", "epoch",
            "hypothesis_ref", "matched_rule", "trace_id", "version",
            "channel", "null_reasons"}
        detail = json.loads(row["detail"])
        assert detail["phase"] == "dispatched"
        assert detail["trigger"]["token"] == "crypto:decode"

    def test_result_and_landed_emitters(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert audit.emit_distill_result(
            str(ws), "attempt-1", validated=True, violations=[],
            hops=0, oracle={"satisfied": True})
        assert audit.emit_candidate_landed(
            str(ws), "attempt-1", "transform-recover",
            tool_path="tools-local/transform-recover.py")
        rows = _audit_rows(ws)
        assert [r["action"] for r in rows] == ["distill_result",
                                               "candidate_landed"]
        assert rows[1]["tool"] == "tools-local/transform-recover.py"


# ---------------------------------------------------------------------------
# dry-face distill responder
# ---------------------------------------------------------------------------


class TestDryDistillFace:
    def test_distill_dispatch_stages_report_and_candidate(self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        req = model.DispatchRequest(
            claim="distill-attempt-1", workspace=str(ctx.ws),
            prompt_file=str(tmp_path / "ev" / "p.md"), run_id="r1",
            agent="kunglao-distill",
            tools=("Read", "Grep", "Glob", "Bash", "WebSearch"))
        act = ctx.face.dispatch_act(req)
        assert act.outcome == "DISPATCHED"
        attempt_dir = ctx.ws / od.REPORTS_DIRNAME / "attempt-1"
        report = json.loads(
            (attempt_dir / "report.json").read_text(encoding="utf-8"))
        assert report["schema"] == od.REPORT_SCHEMA
        assert report["sources"], "dry distill report cites sources"
        assert report["methods"]
        cand = report["candidates"][0]
        assert (attempt_dir / cand["file"]).is_file()

    def test_normal_claim_dispatch_does_not_stage_distill_report(
            self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        req = model.DispatchRequest(
            claim="C-004", workspace=str(ctx.ws),
            prompt_file=str(tmp_path / "ev" / "p.md"), run_id="r1")
        ctx.face.dispatch_act(req)
        assert not (ctx.ws / od.REPORTS_DIRNAME).exists()


# ---------------------------------------------------------------------------
# auto-face rack derivation (byte-compatibility + the distill rack)
# ---------------------------------------------------------------------------


class TestAutoFaceRack:
    def _auto_ctx(self, tmp_path):
        return _mk_ctx(tmp_path, mode="auto")

    def _command_of(self, ctx, req) -> list:
        from test_e2e_runner import ScriptedRunner  # noqa: PLC0415
        recorded: list[list] = []

        class _Capture(ScriptedRunner):
            def run(self, cmd, cwd=None, timeout=None):
                recorded.append([str(c) for c in cmd])
                return model.CmdOutcome(rc=0, stdout="{}", stderr="")

        ctx.runner = _Capture()
        ctx.face.runner = ctx.runner
        req.prompt_file.parent.mkdir(parents=True, exist_ok=True)
        req.prompt_file.write_text("prompt\n", encoding="utf-8")
        ctx.face.run_dispatch(req)
        return recorded[0]

    @staticmethod
    def _rack_of_command(cmd: list) -> str:
        return cmd[cmd.index("--allowedTools") + 1]

    def test_request_without_tools_keeps_the_default_rack(self, tmp_path):
        """The historical shape (no explicit tools — the dataclass
        default) MUST keep the exact historical rack; a naive
        verbatim-derivation would degrade every pre-existing auto act."""
        ctx = self._auto_ctx(tmp_path)
        req = model.DispatchRequest(
            claim="C-004", workspace=str(ctx.ws),
            prompt_file=Path(ctx.state.evidence_dir) / "p.md",
            run_id="r1")
        cmd = self._command_of(ctx, req)
        assert self._rack_of_command(cmd) == ",".join(llm_faces.DEFAULT_RACK)

    def test_distill_rack_rides_verbatim(self, tmp_path):
        ctx = self._auto_ctx(tmp_path)
        rack = ("Read", "Grep", "Glob", "Bash", "WebSearch")
        req = model.DispatchRequest(
            claim="distill-attempt-1", workspace=str(ctx.ws),
            prompt_file=Path(ctx.state.evidence_dir) / "p.md",
            run_id="r1", agent="kunglao-distill", tools=rack)
        cmd = self._command_of(ctx, req)
        got = self._rack_of_command(cmd)
        assert got == ",".join(rack)
        assert "WebSearch" in got


# ---------------------------------------------------------------------------
# the full fixture chain through the tick step
# ---------------------------------------------------------------------------


class TestFixtureChainE2E:
    def test_full_chain_miss_to_landing(self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        _stage_fixture_ws(ctx.ws)
        detail: dict = {}
        checkpoints._maybe_distill(ctx, detail)
        # landing: the tool exists run-local with its manifest
        tool = ctx.ws / "tools-local" / "transform-recover.py"
        assert tool.is_file(), "candidate must land in tools-local"
        manifest = json.loads(
            (ctx.ws / "tools-local" / "transform-recover.manifest.json")
            .read_text(encoding="utf-8"))
        assert manifest["oracle"]["satisfied"] is True
        assert manifest["oracle"]["sample_sha256"] == hashlib.sha256(
            (FIXTURE / "sample.blob").read_bytes()).hexdigest()
        # audit trail: exactly one of each distill word for the attempt
        rows = _audit_rows(ctx.ws)
        actions = [r["action"] for r in rows]
        assert actions.count("distill_attempt") == 1
        assert actions.count("distill_result") == 1
        assert actions.count("candidate_landed") == 1
        attempt_row = next(r for r in rows
                           if r["action"] == "distill_attempt")
        assert json.loads(attempt_row["detail"])["phase"] == "dispatched"
        # ledger: the act + hops debited, landed counted
        state = od.ledger_state(ctx.ws)
        assert state["per_run_used"] == 1
        assert state["global"]["acts"] == 1
        assert state["global"]["landed"] == 1

    def test_second_marker_same_token_no_second_act(self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        _stage_fixture_ws(ctx.ws)
        checkpoints._maybe_distill(ctx, {})
        rows_before = len(_audit_rows(ctx.ws))
        checkpoints._maybe_distill(ctx, {})
        rows = _audit_rows(ctx.ws)
        assert [r["action"] for r in rows].count("distill_attempt") == 1
        assert len(rows) == rows_before
        assert od.ledger_state(ctx.ws)["per_run_used"] == 1

    def test_no_marker_no_distill_act(self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        # an ordinary workspace: worker statuses, no markers anywhere
        (ctx.ws / "runs" / "worker-status-C-004.md").write_text(
            "# worker status\nstatus: DONE\n", encoding="utf-8")
        detail: dict = {}
        checkpoints._maybe_distill(ctx, detail)
        assert not (ctx.ws / "tools-local").exists()
        assert not audit.audit_path(ctx.ws).is_file() or \
            not [r for r in _audit_rows(ctx.ws)
                 if r["action"].startswith(("distill_", "candidate_"))]
        assert od.ledger_state(ctx.ws)["per_run_used"] == 0

    def test_exhausted_budget_refuses_without_act(self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        _stage_fixture_ws(ctx.ws)
        # burn the whole per-run budget first
        od.reserve_act(ctx.ws, "other:cap", source_file="runs/x.md")
        od.reserve_act(ctx.ws, "other:cap2", source_file="runs/y.md")
        checkpoints._maybe_distill(ctx, {})
        rows = _audit_rows(ctx.ws)
        refusals = [r for r in rows if r["action"] == "distill_result"
                    and json.loads(r["detail"]).get("phase") == "refused"]
        assert refusals, "a refused trigger must record its refusal row"
        assert not (ctx.ws / "tools-local").exists()


# ---------------------------------------------------------------------------
# the loop wiring: the tick step runs inside _loop_one_tick
# ---------------------------------------------------------------------------


class _ScriptedRunner(llm_faces.CommandRunner):
    def __init__(self, decisions: list[str]):
        super().__init__(ROOT)
        self.decisions = list(decisions)

    def run(self, cmd, cwd=None, timeout=None):
        argv = " ".join(str(c) for c in cmd)
        if "heartbeat_tick.py" in argv:
            return model.CmdOutcome(rc=0, stdout="{}", stderr="")
        if "convergence_check.py" in argv:
            decision = self.decisions.pop(0) if self.decisions else "CONVERGED"
            return model.CmdOutcome(
                rc=0, stdout=json.dumps({"decision": decision}), stderr="")
        raise AssertionError(f"unscripted command: {argv}")


class TestLoopWiring:
    def test_tick_runs_the_distill_step(self, tmp_path, monkeypatch):
        ctx = _mk_ctx(tmp_path)
        ctx.runner = _ScriptedRunner(["SATURATED"])
        calls: list = []
        monkeypatch.setattr(
            checkpoints, "_maybe_distill",
            lambda c, d: calls.append(c))
        detail: dict = {"ticks": 1}
        flow, terminal, _ms = checkpoints._loop_one_tick(
            ctx, set(), detail, 0, 0)
        assert flow == "continue" and terminal is None
        assert len(calls) == 1, "the tick must run the distill step"


# ---------------------------------------------------------------------------
# the genuine-miss pin
# ---------------------------------------------------------------------------


class TestGenuineMissPin:
    def test_no_registered_crypto_algorithm_recovers_the_fixture(self):
        """The fixture's premise is honest: sweeping the registered
        crypto algorithms' small parameter spaces never recovers the
        expected plaintext. The fixture transform is periodic-XOR (8)
        composed with a modular position add, forward — position-local;
        xor-add is backward data-chained, rolling-xor is 32-bit state
        chained, go-byte-transform permutes positions (reversal +
        pair-swap) before its position xor; chacha/lzss/lzma/rsa/
        va-to-off are different capability classes entirely. The sweep
        proves no accidental small-parameter hit; the class argument
        covers the unsearchable remainder."""
        sys.path.insert(0, str(ROOT / "tools" / "crypto"))
        import algorithms as alg  # noqa: PLC0415

        cipher = (FIXTURE / "sample.blob").read_bytes()
        expected = json.loads(
            (FIXTURE / "expected.json").read_text(encoding="utf-8"))
        magic = expected["magic"].encode("ascii")
        digest = expected["plain_sha256"]

        def recovered(out: bytes) -> bool:
            return (hashlib.sha256(out).hexdigest() == digest
                    or out.startswith(magic))

        for k in range(256):  # xor-add: full key space, both directions
            assert not recovered(alg.xor_add_stream(cipher, key=k))
            assert not recovered(alg.xor_add_inverse(cipher, key=k))
        for seed in range(2048):  # rolling-xor: pinned sample sweep
            assert not recovered(alg.rolling_xor(cipher, seed))
        for key in (0, 1, 7, 42, 0x100, 0xFFFF, 0x12345678):
            for mode in ("forward", "inverse"):
                assert not recovered(
                    alg.go_byte_transform(cipher, key, mode=mode))


# ---------------------------------------------------------------------------
# the production closure face
# ---------------------------------------------------------------------------


class TestProductionClosureTrigger:
    def _payload(self, ws: Path) -> dict:
        return {"cwd": str(ws), "session_id": "s1",
                "transcript_path": str(ws / "t.jsonl")}

    def test_closure_stamps_trigger_and_row(self, tmp_path, capsys):
        sys.path.insert(0, str(ROOT / "hooks"))
        import round_closure  # noqa: PLC0415
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / ".hook_state.json").write_text("{}", encoding="utf-8")
        (ws / "runs" / "worker-status-C-1.md").write_text(
            "status: DONE\nshelf-miss: crypto:decode\n", encoding="utf-8")
        rc = round_closure.main_with_payload(self._payload(ws))
        capsys.readouterr()
        assert rc == 0
        stamp = ws / "runs" / "distill-trigger.json"
        assert stamp.is_file()
        doc = json.loads(stamp.read_text(encoding="utf-8"))
        assert doc["triggers"]
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs
        rows = [json.loads(ln) for ln in
                logs[-1].read_text(encoding="utf-8").splitlines() if ln]
        sig = [r for r in rows if r.get("action") == "distill_attempt"]
        assert sig, rows
        assert json.loads(sig[-1]["detail"])["phase"] == "triggered"

    def test_closure_without_marker_stamps_nothing(self, tmp_path, capsys):
        sys.path.insert(0, str(ROOT / "hooks"))
        import round_closure  # noqa: PLC0415
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "worker-status-C-1.md").write_text(
            "status: DONE\n", encoding="utf-8")
        rc = round_closure.main_with_payload(self._payload(ws))
        capsys.readouterr()
        assert rc == 0
        assert not (ws / "runs" / "distill-trigger.json").is_file()

    def test_closure_fail_open_on_scan_failure(self, tmp_path, capsys,
                                               monkeypatch):
        sys.path.insert(0, str(ROOT / "hooks"))
        import round_closure  # noqa: PLC0415
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / ".hook_state.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            "online_distill.scan_triggers",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        rc = round_closure.main_with_payload(self._payload(ws))
        out = capsys.readouterr()
        assert rc == 0
        # the closure row still lands and the failure is one loud warn
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "the closure event row must still land"
        rows = [json.loads(ln) for ln in
                logs[-1].read_text(encoding="utf-8").splitlines() if ln]
        assert any(r.get("action") == "lifecycle_completed" for r in rows)
        assert "round_closure_distill" in (out.err + out.out)


# ---------------------------------------------------------------------------
# documentation pins
# ---------------------------------------------------------------------------


class TestDocPins:
    def test_worker_doc_names_tools_local(self):
        doc = (ROOT / "agents" / "kunglao-worker.md").read_text(
            encoding="utf-8")
        assert "tools-local" in doc

    def test_skill_doc_documents_distill_protocol(self):
        doc = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
            encoding="utf-8")
        assert "distill" in doc.lower()
