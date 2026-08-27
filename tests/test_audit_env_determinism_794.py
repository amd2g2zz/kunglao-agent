# -*- coding: utf-8 -*-
"""tests/test_audit_env_determinism_794.py — #794 pins on the audit subprocess seam.

Issue #794: `tests/test_v012_milestone_audit.py::_run_cli` inherits the parent
shell wholesale (`dict(os.environ)`), so a behavioral env var in whatever
shell launched pytest rewrites the kunglao CLI exit paths the replay suite is
pinning. Proven mechanism (orchestrator attribution comment): with
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in the parent shell, kunglao-init's
#276 Phase-0 gate HARD-REJECTs before the bins logic and the replay tests
"fail" with gate text instead of the pinned diagnostics. Second, unrefuted
leg from the same issue: the capture side used locale strict decode
(`text=True`), the Windows GBK family #457 already fixed elsewhere.

This file pins the seam, not a copy of it: `_run_cli` is imported from the
audit module itself, so the pins cannot drift from the code they guard.
Pins use echo probes (`python -c`) — no heavy fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import test_v012_milestone_audit as audit

ROOT = Path(__file__).resolve().parents[1]

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# Echo probe: the child reports the env values it actually sees, as JSON.
_PROBE = (
    "import json,os;"
    "print(json.dumps({"
    f"'flag': os.environ.get('{FLAG_NAME}'),"
    "'PYTHONUTF8': os.environ.get('PYTHONUTF8'),"
    "'PYTHONIOENCODING': os.environ.get('PYTHONIOENCODING')}))"
)


def _probe_env(run_cli, *, env: dict | None = None) -> dict:
    proc = run_cli(["-c", _PROBE], cwd=ROOT, env=env)
    assert proc.returncode == 0, f"probe failed:\n{proc.stderr!r}"
    return json.loads(proc.stdout)


# ---------- pin A: behavioral vars never reach the child ----------


@pytest.mark.parametrize("via", ["parent-shell", "explicit-env"], ids=str)
def test_794_run_cli_scrubs_behavioral_flag(monkeypatch, via):
    """The #276 flag must not reach the child — neither via the parent shell
    (#794 leak path) nor re-injected through the explicit env= merge."""
    if via == "parent-shell":
        monkeypatch.setenv(FLAG_NAME, "1")
        env = None
    else:
        env = {FLAG_NAME: "1"}
    seen = _probe_env(audit._run_cli, env=env)
    assert seen["flag"] is None, (
        f"behavioral flag leaked into the audit child env (via={via}): "
        f"{seen['flag']!r} — kunglao-init's #276 gate will fire on the "
        f"test's own shell state instead of the pinned behavior"
    )


def test_794_empty_bins_refusal_diagnoses_target_not_gate(tmp_path: Path):
    """Behavioral pin of the verbatim #794 symptom: with the flag forced,
    the empty-bins refusal must still diagnose bins/analysis-target — not
    the #276 gate's HARD REJECT text."""
    proc = audit._run_cli(
        [
            str(ROOT / "scripts" / "kunglao-init.py"),
            str(tmp_path),
            "--skip-toolchain",
            "--no-hooks",
            "--assume-yes",
        ],
        cwd=ROOT,
        env={FLAG_NAME: "1"},
    )
    assert proc.returncode != 0, "empty bins must still be refused"
    combined = ((proc.stderr or "") + (proc.stdout or "")).lower()
    assert "analysis target" in combined or "bins" in combined, (
        "refusal diagnostic lost the bins/analysis-target vocabulary — "
        f"gate/environment text intercepted instead:\n{proc.stderr!r}"
    )


# ---------- pin B: UTF-8 forced IO, both sides of the pipe ----------


def test_794_run_cli_forces_utf8_io_env(monkeypatch):
    """Child side: PYTHONUTF8=1 / PYTHONIOENCODING=utf-8 must be defaulted in
    (delenv'd first so the pin cannot pass vacuously on a host that exports
    them)."""
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    seen = _probe_env(audit._run_cli)
    assert seen["PYTHONUTF8"] == "1", seen
    assert seen["PYTHONIOENCODING"] == "utf-8", seen


def test_794_run_cli_env_param_still_overrides_defaults():
    """The env= override contract is preserved: explicit caller values win
    over the UTF-8 defaults (setdefault semantics)."""
    seen = _probe_env(audit._run_cli, env={"PYTHONUTF8": "0", "PYTHONIOENCODING": "latin-1"})
    assert seen["PYTHONUTF8"] == "0", seen
    assert seen["PYTHONIOENCODING"] == "latin-1", seen


def test_794_capture_side_survives_non_utf8_child_bytes():
    """Capture side: a child emitting latin-1 bytes (explicit override is
    honored) must yield str text attributes that are safely lower()-able and
    in-matchable — locale strict decode (bare text=True) would raise
    UnicodeDecodeError here on any non-latin-1 host (the #794 Windows leg)."""
    proc = audit._run_cli(
        ["-c", "print('\\u00e9-probe-ok')"],
        cwd=ROOT,
        env={"PYTHONIOENCODING": "latin-1"},
    )
    assert isinstance(proc.stdout, str), type(proc.stdout)
    assert proc.returncode == 0, f"child failed:\n{proc.stderr!r}"
    assert "probe-ok" in proc.stdout.lower(), f"payload lost in decode: {proc.stdout!r}"


if __name__ == "__main__":
    sys.exit(0)
