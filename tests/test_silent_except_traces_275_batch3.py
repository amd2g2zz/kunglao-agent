# -*- coding: utf-8 -*-
"""tests/test_silent_except_traces_275_batch3.py — issue 275 batch 3: the
file-family cleanup ends the ledger. Every remaining silent-swallow except
handler in scripts/ and hooks/ now leaves exactly ONE trace: function-level
handlers emit a rate-limited stderr WARN naming the module, operation and
reason (the batch-2 helper shape, itself a mirror of the issue 276
zero-output recorder warn); import-time lifeline handlers record a
module-level _IMPORT_DEGRADED sidecar entry instead — hook-embedded
importers must keep stderr empty (token-zero).

Policy (issue 275): fail-open keeps its never-raise/never-change-the-verdict
behavior, but silence is telemetry by omission. A comment alone never
satisfies the AST gate; the runtime trace does.

These tests pin, per family sample and repo-wide:
  - the gate end-state: zero silent handlers across scripts/ + hooks/, and
    the ratchet ledger shrunk to an empty file map;
  - every converted file carries the per-module rate-limited warn helper;
  - the WARN fires ONCE on repeat failures with the same reason and again
    when the operation or the reason changes;
  - on injected failure the surrounding behavior is UNCHANGED vs the
    pre-change shape (same return value, same state, never raises);
  - import-time lifeline modules trace their wired-emit failure the same
    way (fresh module load, one WARN, import still succeeds).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
BASELINE = SCRIPTS / "silent_except_baseline.yaml"
for p in (str(ROOT), str(SCRIPTS), str(HOOKS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import silent_except_lint as sel  # noqa: E402
import kunglao_log as kl  # noqa: E402
import mechanism_scheduler as ms  # noqa: E402


def _load_hook_by_path():
    """Load hooks/heartbeat_touch.py by resolved path: it is a
    pre-existing hooks/scripts shared-name twin, and sys.modules history
    from earlier test modules must not choose the tested artifact."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "heartbeat_touch_275b3", HOOKS / "heartbeat_touch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# The marker comment the mechanical conversion embedded in every converted
# module; the set of files carrying it must equal the batch-3 inventory.
B3_MARKER = "# issue " + "275 batch-3"
B3_FILE_COUNT = 82


def _batch3_files() -> list[Path]:
    out = []
    for base in (SCRIPTS, HOOKS):
        for path in sorted(base.rglob("*.py")):
            if B3_MARKER in path.read_text(encoding="utf-8"):
                out.append(path)
    return out


@pytest.fixture
def fresh_warn(monkeypatch):
    """Fresh rate-limit state per test so WARN assertions are per-test."""
    for mod in (kl, ms):
        monkeypatch.setattr(mod, "_WARN_LAST", {}, raising=False)
    yield


# ------------------------------------------------------------- gate faces

def test_zero_silent_handlers_across_scripts_and_hooks():
    counts, structural = sel.scan_counts(ROOT)
    assert not structural
    debt = {rel: n for rel, n in counts.items() if n}
    assert not debt, f"silent handlers remain: {debt}"


def test_ratchet_ledger_ends_with_an_empty_file_map():
    doc = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    assert doc["files"] == {}, "zero-count entries must be deleted"


def test_every_converted_file_carries_the_rate_limited_helper():
    files = _batch3_files()
    assert len(files) == B3_FILE_COUNT, (
        f"expected {B3_FILE_COUNT} converted files, found {len(files)}: "
        f"{[f.relative_to(ROOT).as_posix() for f in files]}")
    for path in files:
        src = path.read_text(encoding="utf-8")
        has_warn = "def warn(" in src and "file=sys.stderr" in src
        # issue 292: the helper may instead be the shared-home binding —
        # `warn = make_warn("<tag>")` from scripts/_scriptlib.py — which
        # replaced the private copies (the trace contract is unchanged,
        # pinned by tests/test_shared_primitives_292.py).
        has_binding = "warn = make_warn(" in src \
            and "from _scriptlib import" in src
        has_sidecar = "_IMPORT_DEGRADED: list[str] = []" in src \
            and "_IMPORT_DEGRADED.append(" in src
        assert has_warn or has_binding or has_sidecar, path
        assert ("_WARN_LAST" in src) or ("_B3_WARN_LAST" in src) \
            or has_binding or has_sidecar, path


# ------------------------------------------------------------ helper shape

def test_warn_names_module_op_reason(capsys, fresh_warn):
    kl.warn("op_x", "ValueError: boom")
    err = capsys.readouterr().err
    assert ("[kunglao-agent] kunglao_log WARN (fail-open): "
            "op_x: ValueError: boom") in err


def test_warn_rate_limits_per_op_until_reason_changes(capsys, fresh_warn):
    kl.warn("op", "r1")
    kl.warn("op", "r1")   # same op + reason -> suppressed
    kl.warn("op2", "r1")  # different op -> fires
    kl.warn("op", "r2")   # reason changed -> fires
    lines = [ln for ln in capsys.readouterr().err.splitlines()
             if "WARN (fail-open)" in ln]
    assert len(lines) == 3


# ------------------------------------------------- behavior-freeze samples

def test_allocate_trace_id_fail_open_warns_and_keeps_contract(
        tmp_path, capsys, fresh_warn):
    """State write blocked (workspace parent is a file): the id is still
    minted, (trace_id, created) shape is unchanged, no partial state file
    is left behind, and the swallow is no longer silent."""
    blocked = tmp_path / "blocker"
    blocked.write_text("not a directory", encoding="utf-8")
    ws = blocked / "ws"

    tid, created = kl.allocate_trace_id(ws, "M-B3")

    err = capsys.readouterr().err
    assert "[kunglao-agent] kunglao_log WARN (fail-open): " \
        "allocate_trace_id:" in err
    assert created is True
    assert kl.validate_trace_id(tid)
    assert not (ws / kl.TRACE_STATE).exists()


def test_mechanism_scheduler_state_write_fail_open_warns(
        tmp_path, capsys, fresh_warn):
    """Same injected failure: the scheduler never raises and never leaves
    a half-written state; the WARN is the single trace."""
    blocked = tmp_path / "blocker"
    blocked.write_text("not a directory", encoding="utf-8")
    ws = blocked / "ws"

    ms._write_state(ws, {"k": 1})

    err = capsys.readouterr().err
    assert "[kunglao-agent] mechanism_scheduler WARN (fail-open): " \
        "_write_state:" in err
    assert not (Path(ws) / ms.STATE_REL).exists()


def test_heartbeat_touch_statusline_degrade_warns_once(
        tmp_path, capsys, fresh_warn, monkeypatch):
    """A broken deployed statusline module degrades exactly as before
    (return None, never raise) and the failure lands on stderr once."""
    ht = _load_hook_by_path()

    def _boom(*a, **k):
        raise RuntimeError("boom")

    ws = tmp_path / "ws"
    deployed = ws / ".claude" / "scripts" / "statusline_snapshot.py"
    deployed.parent.mkdir(parents=True)
    deployed.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(ht, "_WARN_LAST", {})
    monkeypatch.setattr(ht, "load_module_by_path", _boom)

    assert ht._write_statusline_snapshot(ws) is None

    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines()
             if "[kunglao-agent] heartbeat_touch WARN (fail-open): "
             "_write_statusline_snapshot" in ln]
    assert len(lines) == 1


# ------------------------------------------------------ lifeline family

def test_import_time_lifeline_sidecars_and_keeps_stderr_empty(capsys):
    """The module-wired emit lifelines reference a name that does not exist
    at import time; the fresh load must still succeed, keep stderr EMPTY
    (hook-embedded importers are token-zero surfaces) and record the
    swallowed NameError in the module's _IMPORT_DEGRADED sidecar — the
    batch-2 heartbeat_tick precedent (previously a bare pass)."""
    spec = importlib.util.spec_from_file_location(
        "completion_gate_275b3_fresh", SCRIPTS / "completion_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert capsys.readouterr().err == "", \
        "import-time lifelines must stay off stderr (token-zero)"
    assert len(mod._IMPORT_DEGRADED) == 1, mod._IMPORT_DEGRADED
    assert mod._IMPORT_DEGRADED[0].startswith("module: NameError"), \
        mod._IMPORT_DEGRADED[0]


def test_hook_embedded_import_closure_stays_stderr_silent(
        tmp_path, capsys):
    """End-to-end on the touched artifact: hooks/heartbeat_touch.py runs
    its full import closure (wire_up_settings, hook_activation, ...) and
    emits nothing on either stream — the lifeline sidecar arm keeps the
    token-zero contract that the stderr WARN arm broke."""
    ht = _load_hook_by_path()
    (tmp_path / "ws" / "runs").mkdir(parents=True)
    (tmp_path / "ws" / "analysis_state.txt").write_text(
        "# analysis_state\nproject_type=windows\n", encoding="utf-8")
    (tmp_path / "ws" / "claim-register.yaml").write_text(
        "claims: []\n", encoding="utf-8")

    rc = ht.main()

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
