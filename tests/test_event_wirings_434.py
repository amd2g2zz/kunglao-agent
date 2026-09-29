# -*- coding: utf-8 -*-
"""tests/test_event_wirings_434.py — the four missing event wirings.

Issue 434: the event surface had four dead sensors — SubagentStop (round
closure), SessionStart (constitution + strategy resume), PreCompact
(strategy continuity) and UserPromptSubmit (operator observation). All
four go live through the canonical registration entry
(hook_activation.register_hooks) + small hook scripts that match the
deployed hook file shape. Registration tables (registry, canonical writer,
deployed wiring, the two deliberate-subset skip tables) must grow
TOGETHER or the import-time subset validator fails loudly.
"""
from __future__ import annotations

import json
from pathlib import Path

import wire_up_settings  # pythonpath = . hooks scripts

from _factories import write_claims_register, write_hook_state

ROOT = Path(__file__).resolve().parents[1]

# (event, hook file) — the four event wirings this issue adds.
NEW_WIRINGS = {
    "SubagentStop": "round_closure.py",
    "SessionStart": "session_start.py",
    "PreCompact": "compact_continuity.py",
    "UserPromptSubmit": "user_signal_capture.py",
}
# plus the WORKGUARD Stop entry (own suite covers behavior; this file pins
# the REGISTRATION of all five).
STOP_WIRING = ("Stop", "workguard_gate.py")
NEW_HOOK_FILES = frozenset(list(NEW_WIRINGS.values()) + [STOP_WIRING[1]])


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, [{"id": "C-1", "status": "OPEN"}])
    return ws


def _register(ws: Path) -> dict:
    import hook_activation
    hook_activation.register_hooks(workspace=ws)
    target = ws / ".claude" / "settings.json"
    return json.loads(target.read_text(encoding="utf-8"))


def _basenames_under(settings: dict, event: str) -> set:
    out = set()
    for entry in (settings.get("hooks") or {}).get(event) or []:
        for h in entry.get("hooks", []):
            cmd = str(h.get("command", "")).replace("\\", "/")
            out.add(cmd.rsplit("/", 1)[-1])
    return out


class TestRegistrationTables:
    def test_registry_grew_with_the_new_files(self):
        assert NEW_HOOK_FILES <= wire_up_settings.WIRE_UP_HOOK_FILES, (
            "the five new hook files must be registry members "
            f"(missing: {NEW_HOOK_FILES - wire_up_settings.WIRE_UP_HOOK_FILES})")

    def test_deployed_wiring_mirror_carries_the_events(self):
        import hook_activation
        deployed = {(e, m, f) for e, m, f in hook_activation._DEPLOYED_WIRING}
        for event, hf in NEW_WIRINGS.items():
            assert (event, "", hf) in deployed, (
                f"deployed wiring missing {event} -> {hf}")
        assert ("Stop", "", STOP_WIRING[1]) in deployed

    def test_workguard_registered_in_activation_vocabulary(self):
        import hook_activation
        assert "workguard_gate" in hook_activation.ALL_HOOKS

    def test_subset_skip_tables_account_for_new_files(self):
        """hooks_selfcheck + external_kicker pin their file sets to the
        registry via derive_hook_subset — a registry growth without a
        conscious table update raises at import. Both skip tables must
        cover the five new files (deployment gates restored by the full
        wire-up, not the dead-session bootstrap chain)."""
        import hooks_selfcheck
        for f in NEW_HOOK_FILES:
            assert f in hooks_selfcheck._KONG_SKIP_FILES, f
        import external_kicker
        for f in NEW_HOOK_FILES:
            assert f in external_kicker._KICKER_SKIP_FILES, f

    def test_register_hooks_writes_all_four_events(self, tmp_path):
        ws = _mk_ws(tmp_path)
        settings = _register(ws)
        for event, hf in NEW_WIRINGS.items():
            assert hf in _basenames_under(settings, event), (
                f"{event} wiring missing from the canonical write")
        assert STOP_WIRING[1] in _basenames_under(settings, "Stop")

    def test_selfcheck_passes_with_new_files(self, tmp_path):
        """The post-registration self-check (coverage + layer + canonical
        command shape) stays green with the five new files on board."""
        import hook_activation
        ws = _mk_ws(tmp_path)
        hook_activation.register_hooks(workspace=ws)
        target = ws / ".claude" / "settings.json"
        result = hook_activation.selfcheck_registration(
            target, expected_files=wire_up_settings.WIRE_UP_HOOK_FILES,
            workspace=ws, layer="project")
        assert result["ok"] is True, result["mismatches"]


class TestRoundClosure:
    def _payload(self, ws: Path) -> dict:
        return {"cwd": str(ws),
                "session_id": "sess-7",
                "transcript_path": str(ws / "transcript.jsonl")}

    def test_registered_and_runs_lands_closure_row(self, tmp_path, capsys):
        """SubagentStop appends a closure event row to the ledger: one
        lifecycle_completed row carrying the session identity (the round
        closure feed the between-turns wake topology reads)."""
        import round_closure
        ws = _mk_ws(tmp_path)
        write_hook_state(ws, active_hooks=["completion_gate"])
        rc = round_closure.main_with_payload(self._payload(ws))
        capsys.readouterr()
        assert rc == 0
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "closure event must land in the ledger"
        rows = [json.loads(ln) for ln in
                logs[-1].read_text(encoding="utf-8").splitlines() if ln]
        closed = [r for r in rows
                  if r.get("action") == "lifecycle_completed"]
        assert closed, rows
        assert closed[-1]["actor"].startswith("subagent:"), closed[-1]
        assert "sess-7" in str(closed[-1].get("detail"))

    def test_fail_open_on_bad_payload(self, capsys):
        import round_closure
        assert round_closure.main_with_payload({}) == 0
        capsys.readouterr()

    def test_no_workspace_passes_through(self, tmp_path, capsys):
        import round_closure
        rc = round_closure.main_with_payload({"cwd": str(tmp_path)})
        out = capsys.readouterr().out
        assert rc == 0 and out == ""


class TestKernelRoundClosure462:
    """issues #462 W1+W6: the production round-closure kernel faces.
    Stop(worker) IS the round-closure event (#429 §6) — so the hook now
    hosts what until now fired only from eval_loop_runner: the T2
    unblocking-value queue (build + drain) and the compose single-point
    (one round-strategy object per decision event, versioned)."""

    def _payload(self, ws: Path) -> dict:
        return {"cwd": str(ws), "session_id": "sess-9",
                "transcript_path": str(ws / "transcript.jsonl")}

    def test_round_closure_builds_and_drains_the_t2_queue(
            self, tmp_path, capsys):
        import round_closure
        ws = _mk_ws(tmp_path)  # carries an OPEN claim (C-1)
        write_hook_state(ws, active_hooks=["completion_gate"])
        rc = round_closure.main_with_payload(self._payload(ws))
        capsys.readouterr()
        assert rc == 0
        queue_path = ws / "runs" / "t2-queue.json"
        assert queue_path.is_file(), \
            "production closure must persist the T2 queue (not eval-only)"
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        assert queue["schema"] == "t2-queue/1"
        assert queue["dispatched"], "the closure drains the queue head"
        assert queue["dispatched"][0]["claim_id"] == "C-1"

    def test_round_closure_composes_and_versions_the_strategy(
            self, tmp_path, capsys):
        import round_closure
        import rollout_ledger as rl
        import yaml
        ws = _mk_ws(tmp_path)
        for rid in ("task/k1", "task/k2"):
            rl.record(ws, kind="task", anchor=rid, signals=[
                {"type": "method_family", "source": "envelope",
                 "value": "static-decompile", "ts": "t"}], rollout_id=rid)
            rl.settle(ws, rid, {"reward": 1.0, "band": "SETTLED_GREEN",
                                "rule_id": "unit-test",
                                "evidence_refs": [rid]})
        write_hook_state(ws, active_hooks=["completion_gate"])
        rc = round_closure.main_with_payload(self._payload(ws))
        capsys.readouterr()
        assert rc == 0
        ticks = sorted((ws / "runs" / "round-strategy").glob("tick-*.yaml"))
        assert ticks, "the compose host must version the strategy object"
        obj = yaml.safe_load(ticks[-1].read_text(encoding="utf-8"))
        assert obj["schema"] == "round-strategy/1"
        assert obj["dispatch"]["method_lead"] == "static-decompile"

    def test_kernel_faces_stay_fail_open(self, tmp_path, capsys):
        """A COMPOSE-face failure must never disturb the closure: the
        strategy dir blocked by a file makes write_strategy fail — the
        closure row still lands, the T2 queue still builds+drains, and
        rc stays 0 (each kernel face is caged separately)."""
        import round_closure
        ws = _mk_ws(tmp_path)  # OPEN claim C-1 for the T2 face
        write_hook_state(ws, active_hooks=["completion_gate"])
        # block the compose write face: runs/round-strategy is a FILE
        (ws / "runs" / "round-strategy").write_text("not a dir",
                                                    encoding="utf-8")
        rc = round_closure.main_with_payload(self._payload(ws))
        capsys.readouterr()
        assert rc == 0
        # the closure row still landed (the cage isolates the faces)
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "closure event must still land"
        rows = [json.loads(ln) for ln
                in logs[-1].read_text(encoding="utf-8").splitlines() if ln]
        assert any(r.get("action") == "lifecycle_completed" for r in rows)
        # the T2 face still built + drained (independent cage)
        queue = json.loads(
            (ws / "runs" / "t2-queue.json").read_text(encoding="utf-8"))
        assert queue["dispatched"][0]["claim_id"] == "C-1"


class TestUserPromptObservation:
    def test_observation_row_lands(self, tmp_path, capsys):
        """UserPromptSubmit records the operator prompt as an observation
        row (action=operator_observation) — pure recording, NO gating: rc 0
        with empty stdout whatever the prompt says."""
        import user_signal_capture
        ws = _mk_ws(tmp_path)
        write_hook_state(ws, active_hooks=["user_signal_capture"])
        rc = user_signal_capture.main_with_payload(
            {"cwd": str(ws), "prompt": "stop chasing the license path"})
        out = capsys.readouterr().out
        assert rc == 0 and out == ""
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "operator observation row must land"
        rows = [json.loads(ln) for ln in
                logs[-1].read_text(encoding="utf-8").splitlines() if ln]
        obs = [r for r in rows if r.get("action") == "operator_observation"]
        assert obs, rows
        assert "license" in str(obs[-1].get("detail"))

    def test_no_gating_on_any_prompt(self, tmp_path, capsys):
        import user_signal_capture
        ws = _mk_ws(tmp_path)
        write_hook_state(ws, active_hooks=["user_signal_capture"])
        for prompt in ("", "whatever", "[goal] re-pin to vm lane"):
            rc = user_signal_capture.main_with_payload(
                {"cwd": str(ws), "prompt": prompt})
            assert rc == 0
            assert capsys.readouterr().out == ""

    def test_no_workspace_passes_through(self, tmp_path, capsys):
        import user_signal_capture
        rc = user_signal_capture.main_with_payload(
            {"cwd": str(tmp_path), "prompt": "hi"})
        out = capsys.readouterr().out
        assert rc == 0 and out == ""


def test_user_signal_capture_deployed_shape_lands_rows(tmp_path):
    """Deployed-shape regression (reviewer round 2, #434 CI round): the
    hook run via its REGISTERED command form — uv run --project <repo>
    python <repo>/hooks/user_signal_capture.py — must land the
    operator_observation row. sys.path[0] is the hooks dir only in this
    shape; a bare ws_layout import silently no-ops through the main()
    cage (both the #434 observation face AND the #868 ingest face lost).
    """
    import os
    import subprocess

    repo = ROOT
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    payload = {"cwd": str(ws), "prompt": "deployed-shape probe"}
    env = dict(os.environ, PYTHONUTF8="1", CLAUDE_PROJECT_DIR=str(ws))
    proc = subprocess.run(
        ["uv", "run", "--project", str(repo), "python",
         str(repo / "hooks" / "user_signal_capture.py")],
        input=json.dumps(payload), capture_output=True, text=True,
        timeout=120, env=env)
    assert proc.returncode == 0, proc.stderr[-600:]
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows.extend(json.loads(line) for line in
                    p.read_text(encoding="utf-8").splitlines() if line.strip())
    acts = {r.get("action") for r in rows}
    assert "operator_observation" in acts, (
        f"deployed shape lost the observation face: actions={acts}; "
        f"stderr tail: {proc.stderr[-300:]}")
