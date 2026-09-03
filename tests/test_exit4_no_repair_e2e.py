#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_exit4_no_repair_e2e.py — #565 DoD 9 end-to-end regression.

Contract (DoD 9 / #448 / #565): when `kunglao-init` exits with
RC_TOOLCHAIN_REFUSE=4 (HARD-FAIL refusal, human must install), the system
MUST NOT trigger any subsequent repair action in the agent's next turn —
specifically:
  - `proxy_repair` (forbidden action name)
  - `continue_silently` (forbidden action name)
  - any `env_repair_l1` actor emit that would represent an automatic
    orchestrator-led repair after a human-event refusal

#565 closes the gap between the unit test
(test_error_response.py:176-188 — pure classifier contract) and a real
tmp-workspace integration regression: drive the actual `kunglao-init.py`
subprocess, deterministically force exit 4 via a monkey-patched toolchain
report, and verify nothing in the resulting state or log path looks like
a repair attempt.

TDD discipline: this file is RED → GREEN with no implementation changes
required (the contract is already enforced by error_response.py + the
existing init refusal flow); the test only asserts the contract holds
end-to-end in an external workspace.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import error_response as er  # noqa: E402
from error_response import (  # noqa: E402
    Response,
    classify_init_exit,
)
import env_repair_l1  # noqa: E402
from _factories import seed_bins


PY311 = sys.executable  # venv python (>= floor); #457 hard pin broke the 3.10 job

# #794: behavioral env vars scrubbed from every child env _run builds
# (same list/policy as test_v012_milestone_audit.py::_BEHAVIORAL_ENV_VARS).
_BEHAVIORAL_ENV_VARS = (
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",  # kunglao-init #276 Phase-0 gate
)


# ---------- #565 DoD 9: contract (library-level, deterministic) ----------

class TestContractExit4BlocksRepair:
    """Mirror test_error_response.py:176-188, extended to also assert that
    env_repair_l1 REPAIRS keys are NOT in the allowed_actions set —
    i.e. the classifier explicitly disallows every concrete repair shape.
    """

    def test_classify_init_exit_4_returns_stop(self) -> None:
        c = classify_init_exit(4)
        assert c.response is Response.STOP, (
            "DoD 9 broken: init exit 4 MUST STOP the agent"
        )

    def test_classify_init_exit_4_forbids_proxy_repair(self) -> None:
        c = classify_init_exit(4)
        assert "proxy_repair" in c.forbidden_actions, (
            "DoD 9 broken: 'proxy_repair' MUST be forbidden on HUMAN-EVENT-REFUSE"
        )
        assert "continue_silently" in c.forbidden_actions, (
            "DoD 9 broken: 'continue_silently' MUST be forbidden on HUMAN-EVENT-REFUSE"
        )

    def test_classify_init_exit_4_excludes_concrete_repairs_from_allowed(
        self,
    ) -> None:
        """Every env_repair_l1 REPAIR key is a concrete repair shape — none
        of them may appear in allowed_actions for an exit-4 refusal.
        """
        c = classify_init_exit(4)
        # Repair names are e.g. "adb-reconnect", "vm-rediscover", "mcp-rehandshake".
        # We assert that none of them, nor any "proxy_repair_*" pattern,
        # nor any obvious repair verbs, appear in allowed_actions.
        forbidden_verbs = {"repair", "fix", "patch", "reconnect", "rediscover",
                           "rehandshake", "install"}
        for action in c.allowed_actions:
            for verb in forbidden_verbs:
                assert verb not in action.lower(), (
                    f"DoD 9 broken: action {action!r} on HUMAN-EVENT-REFUSE "
                    f"looks like a repair verb ({verb!r}) — "
                    "init exit 4 must NEVER auto-repair"
                )


# ---------- #565 DoD 9: external-site replay (subprocess, tmp workspace) ---

def _build_fake_toolchain_wrapper(tmp_path: Path, ws: Path) -> Path:
    """Write a Python wrapper that pre-imports a fake `toolchain` module
    BEFORE `kunglao-init` runs. The fake forces `toolchain.check(...)` to
    return a synthetic HARD-fail ToolchainReport, deterministically producing
    RC_TOOLCHAIN_REFUSE=4 — no real tool availability required.

    Why a wrapper instead of mocking in-process:
      - The wrapper runs REAL `kunglao_init.main([...])` end-to-end.
      - It runs in a separate Python process (subprocess.run), so the
        workspace state is exactly what an external caller would observe.
      - The monkey-patch is scoped to the wrapper; the real `toolchain.py`
        is untouched.
    """
    wrapper = tmp_path / "_drive_init_with_fake_toolchain.py"
    wrapper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        # Real modules that toolchain.py imports at load time must keep
        # working. We import them before swapping toolchain so transitive
        # imports still resolve.
        "import init_state\n"
        "import mcp_probe\n"
        # Build the fake module. MagicMock attribute access returns a Mock,
        # so `tc.Status.FAIL` evaluates to a Mock that compares equal to
        # itself (identity) — sufficient for kunglao_init's comparisons.
        "from unittest.mock import MagicMock\n"
        "fake = MagicMock(name='fake_toolchain')\n"
        "fake_checkresult = MagicMock(name='fake_CheckResult')\n"
        "fake_checkresult.side_effect = lambda **kw: MagicMock(**kw)\n"
        "fake.CheckResult = fake_checkresult\n"
        "fake.FIXES = {}\n"
        "fake.next_action_for = lambda item: None\n"
        # Status / Tier sentinels — kunglao-init compares by identity.
        "fake.Status = MagicMock(name='Status')\n"
        "fake.Status.FAIL = object()\n"
        "fake.Status.PASS = object()\n"
        "fake.Status.WARN = object()\n"
        "fake.Tier = MagicMock(name='Tier')\n"
        "fake.Tier.HARD = object()\n"
        "fake.Tier.WARN = object()\n"
        "fake.ProbeTier = MagicMock(name='ProbeTier')\n"
        "fake.ProbeTier.PRESENCE = object()\n"
        "fake.ProbeTier.CAPABILITY = object()\n"
        # Forge a ToolchainReport whose overall_status is FAIL and contains
        # exactly one HARD item — enough to drive refuse_toolchain → exit 4.
        "fake_report = MagicMock(name='ToolchainReport')\n"
        "fake_report.project_type = 'linux'\n"
        "fake_report.overall_status = fake.Status.FAIL\n"
        "hard_item = MagicMock(name='hard_item')\n"
        "hard_item.name = 'forced_hard_fail'\n"
        "hard_item.status = fake.Status.FAIL\n"
        "hard_item.tier = fake.Tier.HARD\n"
        "hard_item.detail = 'forced for #565 DoD 9 regression'\n"
        "hard_item.fix = None\n"
        "fake_report.items = [hard_item]\n"
        "fake.check = MagicMock(return_value=fake_report)\n"
        "sys.modules['toolchain'] = fake\n"
        # Load kunglao-init.py as a module — the file name has a dash so
        # we use importlib.spec_from_file_location to bypass Python's
        # identifier-only import rule.
        "import importlib.util\n"
        f"_spec = importlib.util.spec_from_file_location("
        f"'kunglao_init', {str(SCRIPTS / 'kunglao-init.py')!r})\n"
        "kunglao_init = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(kunglao_init)\n"
        f"sys.exit(kunglao_init.main([{str(ws)!r}, '--type', 'linux', "
        "'--host-exec-protection', 'enabled', '--no-hooks', '--assume-yes']))\n",
        encoding="utf-8",
    )
    return wrapper


def _run(*args: str, cwd: Path | None = None,
         env: dict | None = None,
         timeout: int = 60) -> subprocess.CompletedProcess:
    """Deterministic child env, same contract as
    tests/test_v012_milestone_audit.py::_run_cli (#794): behavioral vars
    (#276 AGENT_TEAMS gate — with it truthy the gate exits 3 before the
    forced RC_TOOLCHAIN_REFUSE=4 this file pins) are scrubbed AFTER the env=
    merge; UTF-8 forced on both pipe sides (encoding= explicit — bare
    text=True locale-decodes strictly, the #457 GBK family)."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    for behavioral_var in _BEHAVIORAL_ENV_VARS:
        full_env.pop(behavioral_var, None)
    full_env.setdefault("PYTHONUTF8", "1")
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        [PY311, *args],
        cwd=str(cwd or REPO_ROOT),
        env=full_env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def test_replay_init_exit4_no_repair_in_tmp_workspace(tmp_path: Path) -> None:
    """External-site replay: drive real `kunglao_init.main` to RC_TOOLCHAIN_REFUSE=4
    via a forced toolchain HARD-fail; verify the resulting tmp workspace
    shows NO evidence of a follow-up repair attempt.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    # bins/ sample (a real placeholder; init refuses empty bins/ with exit 5
    # before reaching the toolchain check, so we need at least one sample).
    # init refuses empty bins/ with exit 5, so seed one sample.
    seed_bins(ws, payload=b"\x00\x01\x02")

    wrapper = _build_fake_toolchain_wrapper(tmp_path, ws)
    proc = _run(str(wrapper), cwd=tmp_path, timeout=60)

    # 1. Init MUST refuse with RC_TOOLCHAIN_REFUSE=4.
    assert proc.returncode == 4, (
        f"init did not exit 4 (RC_TOOLCHAIN_REFUSE): rc={proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )

    # 2. The tmp workspace MUST NOT have an [initialized] marker written
    #    (refusal contract: zero scaffold).
    reg = ws / "claim-register.yaml"
    if reg.exists():
        text = reg.read_text(encoding="utf-8", errors="replace")
        assert "[initialized]" not in text, (
            f"init refused but [initialized] marker was written — "
            f"refusal contract violated:\n{text}"
        )

    # 3. Scan runs/logs/kunglao-*.jsonl for any repair-action emits that
    #    would represent a follow-up repair triggered after the refusal.
    logs_dir = ws / "runs" / "logs"
    repair_actor_emits: list[str] = []
    if logs_dir.exists():
        for log_path in logs_dir.glob("kunglao-*.jsonl"):
            for line in log_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Forbidden emit shapes (DoD 9 = no auto-repair on exit 4):
                forbidden = {
                    "proxy_repair",
                    "continue_silently",
                    "repair_dispatch",
                }
                actor = (ev.get("actor") or "").lower()
                action = (ev.get("action") or "").lower()
                detail = (ev.get("detail") or "").lower()
                if (action in forbidden
                    or any(v in action for v in forbidden)
                    or "env_repair_l1" in actor
                    or "proxy_repair" in detail):
                    repair_actor_emits.append(
                        f"{log_path.name}: {ev}"
                    )

    assert not repair_actor_emits, (
        "DoD 9 broken: init exit 4 was followed by a repair-action emit:\n"
        + "\n".join(repair_actor_emits)
    )

    # 4. Cross-check the classifier contract holds in the same scenario
    #    the subprocess just exercised (defence in depth: if the subprocess
    #    monkey-patch regressed, the library contract still pins the truth).
    c = classify_init_exit(proc.returncode)
    assert c.response is Response.STOP
    assert "proxy_repair" in c.forbidden_actions
    assert "continue_silently" in c.forbidden_actions


def test_replay_init_exit4_env_repair_keys_excluded_from_allowed(
    tmp_path: Path,
) -> None:
    """#565 extension: every concrete env_repair_l1 REPAIR key (the real
    orchestrator repair surface) MUST be absent from classify_init_exit(4)'s
    allowed_actions. This pins the contract that an exit-4 refusal
    specifically forbids the actual repair verbs the orchestrator knows.
    """
    repair_keys = set(env_repair_l1.REPAIRS.keys())
    assert repair_keys, "env_repair_l1.REPAIRS unexpectedly empty"

    c = classify_init_exit(4)
    allowed = set(c.allowed_actions)

    # None of the repair keys nor their "proxy_<key>" variants appear in allowed.
    bad_overlap = set()
    for rk in repair_keys:
        if rk in allowed:
            bad_overlap.add(rk)
        if f"proxy_{rk}" in allowed:
            bad_overlap.add(f"proxy_{rk}")

    assert not bad_overlap, (
        f"DoD 9 broken: init exit 4 allowed_actions include repair keys: "
        f"{bad_overlap}; allowed={allowed}"
    )


# ---------- #565 DoD 9: gate / opt-out / idempotency smoke --------------

class TestDoD9Smoke:
    """Cheap, deterministic smoke checks that pin the #565 contract without
    subprocess. If these break, the broader test_error_response.py suite
    will too — but having them colocated with the e2e file documents the
    DoD 9 intent at a glance.
    """

    def test_charter_state_surfaces_must_stop(self) -> None:
        c = classify_init_exit(4)
        assert "must-stop" in c.charter_state

    def test_response_table_exit_4_is_stop(self) -> None:
        # Pull from the response-map table directly to catch silent drift.
        from error_response import _RESPONSE_MAP
        assert _RESPONSE_MAP[er.ErrorClass.HUMAN_EVENT_REFUSE] is Response.STOP


if __name__ == "__main__":
    sys.exit(0)