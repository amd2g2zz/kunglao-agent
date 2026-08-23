# -*- coding: utf-8 -*-
"""Tests for issue #450 — env manifest: environment facts single source.

The five scattered environment fact families (VM identity / IP discovery /
snapshot semantics / VPMC / guest-exec channel differences) plus the
deployment layout conventions live in ONE machine-readable carrier
(<workspace>/env-facts.yaml — renamed from env-facts.yaml by the
governance decision of 2026-08-19 after review F1: that name collided
with the #478 deployment ledger) with ONE loading point:

  * load_manifest: absent -> None; garbage / unreadable / non-mapping /
    #478 ledger shape -> ValueError fail-closed (#449 M2 mirror);
  * resolve: priority workspace manifest > #449 Requirements derivation
    (consumed, not modified) > conservative default;
  * layout_conventions: hook hot path — garbage never raises, falls back to
    the pre-#450 literals (byte-identical backward-compat anchor);
  * the layout literals in dispatch_gate._resolve_workspace /
    convergence_check._resolve_ws / lib_kunglao.iter_worker_states are read
    from the manifest — absent manifest keeps behavior byte-identical;
  * `--render` emits the env documentation section (needs_vm / identity /
    IP policy / snapshot / VPMC / channel), garbage -> RC_MANIFEST_DEFECT;
  * `--probe` discovers via vmrun (seam _subprocess_run), merges without
    clobbering user fields, and fails OPEN (guidance, exit 0) when vmrun
    is unavailable — but refuses to overwrite a garbage manifest;
  * F1 collision defense: #478 ledger content is never consumed at either
    filename, probe never rewrites the ledger, init rerun never clears
    recorded env facts (three-way data preservation);
  * kunglao-init's CLAUDE.md "VM required" line is conditionalized per the
    resolved needs_vm (the #449 leftover); with no manifest and no
    task_spec the rendered text is byte-identical (golden anchor).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# lib_kunglao by path under the repo's unique-name convention (bare
# `import lib_kunglao` is ambiguous: scripts/lib_kunglao.py shares it).
_PROTOCOL_NAME = "lib_kunglao_hooks"


def _load_protocol():
    lib = sys.modules.get(_PROTOCOL_NAME)
    if lib is None:
        spec = importlib.util.spec_from_file_location(
            _PROTOCOL_NAME, ROOT / "hooks" / "lib_kunglao.py")
        lib = importlib.util.module_from_spec(spec)
        sys.modules[_PROTOCOL_NAME] = lib
        spec.loader.exec_module(lib)
    return lib


def _load_init_module():
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_env_manifest", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_manifest(ws: Path, data: dict) -> Path:
    p = ws / "env-facts.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


def _write_static_only_task_spec(ws: Path) -> Path:
    p = ws / "task_spec.yaml"
    p.write_text(yaml.safe_dump({"constraints": {"dynamic_re": "forbidden"}},
                                sort_keys=False), encoding="utf-8")
    return p


def _make_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


# ---------- 1. module + layout defaults (pre-#450 literal anchor) ----------

def test_layout_defaults_are_pre450_literals():
    """DEFAULT_LAYOUT IS the set of literals the consumers hardcoded before
    #450 — the backward-compatibility anchor. Changing any of these strings
    changes discovery behavior for manifest-less workspaces."""
    import env_manifest as em
    assert em.DEFAULT_LAYOUT.workspace_dir == "malware-analysis-workspace"
    assert em.DEFAULT_LAYOUT.claim_register == "claim-register.yaml"
    assert em.DEFAULT_LAYOUT.worker_worktree_glob == ".wt-*"
    assert em.DEFAULT_LAYOUT.worker_worktree_marker == ".kunglao-worktree"
    assert em.DEFAULT_LAYOUT.runs_dir == "runs"


def test_conservative_default_manifest():
    """The default manifest is conservative: VM required, no invented
    identity, DHCP live-discovery policy (cached IPs forbidden — #450
    design direction), no channel preference. No concrete paths/IPs."""
    import env_manifest as em
    m = em.DEFAULT_MANIFEST
    assert m.needs_vm is True
    assert "conservative" in m.basis.lower() or "default" in m.basis.lower()
    assert m.vm.vmx_path is None
    assert m.vm.ip_discovery == "live-dhcp"
    assert m.vm.vpmc_compatible is None
    assert m.vm.snapshot.autologin is None
    assert m.vm.snapshot.rollback_fix is None
    assert m.guest_channel.preferred is None
    assert m.layout == em.DEFAULT_LAYOUT
    assert m.source == "default"


# ---------- 2. load_manifest: single loading point, fail-closed ----------

def test_load_manifest_absent_returns_none(tmp_path):
    import env_manifest as em
    assert em.load_manifest(_make_ws(tmp_path)) is None


def test_load_manifest_garbage_raises_valueerror(tmp_path):
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-facts.yaml").write_text("{{{ not yaml", encoding="utf-8")
    with pytest.raises(ValueError):
        em.load_manifest(ws)


def test_load_manifest_non_mapping_raises_valueerror(tmp_path):
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-facts.yaml").write_text("- just\n- a\n- list\n",
                                          encoding="utf-8")
    with pytest.raises(ValueError):
        em.load_manifest(ws)


def test_load_manifest_unreadable_fails_closed(tmp_path, monkeypatch):
    """#449 M2 mirror: a present-but-unreadable manifest (Windows share
    lock / ACL PermissionError) takes the SAME fail-closed path as garbage
    — ValueError, never a bare PermissionError traceback."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-facts.yaml").write_text("version: 1\n", encoding="utf-8")
    real_read_text = Path.read_text

    def denied_read_text(self, *args, **kwargs):
        if self.name == "env-facts.yaml":
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied_read_text)
    with pytest.raises(ValueError) as ei:
        em.load_manifest(ws)
    assert "unreadable" in str(ei.value), ei.value


def test_load_manifest_non_utf8_fails_closed(tmp_path):
    """B9-type bypass: non-UTF-8 bytes must stay inside the ValueError
    family (UnicodeDecodeError IS a ValueError — pinned as contract)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-facts.yaml").write_bytes(b"\xff\xfe\x00garbage\x80\x81")
    with pytest.raises(ValueError):
        em.load_manifest(ws)


# ---------- 2b. F1: #478 deploy-ledger collision defense ----------

_DEPLOY_LEDGER = {
    "generated": "2026-08-19T12:00:00Z",
    "project_type": "windows",
    "components": [{"name": "hooks", "status": "deployed"}],
}


def _write_ledger(ws: Path, name: str) -> Path:
    p = ws / name
    p.write_text(yaml.safe_dump(_DEPLOY_LEDGER, sort_keys=False),
                 encoding="utf-8")
    return p


def test_ledger_shape_at_facts_name_rejected(tmp_path):
    """Ledger content copied INTO env-facts.yaml is a stop event with
    guidance — never consumed (pre-fix it resolved with the bogus
    source: manifest-file)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_ledger(ws, "env-facts.yaml")
    with pytest.raises(ValueError) as ei:
        em.load_manifest(ws)
    assert "ledger" in str(ei.value).lower()
    assert "env-facts.yaml" in str(ei.value)  # guidance names the carrier


def test_ledger_at_legacy_name_rejected_never_consumed(tmp_path):
    """F1 core: every init'd workspace carries env-manifest.yaml (the
    #478 deploy ledger). load_manifest must reject it with guidance, not
    parse it as a manifest."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_ledger(ws, "env-manifest.yaml")
    with pytest.raises(ValueError) as ei:
        em.load_manifest(ws)
    assert "ledger" in str(ei.value).lower()
    assert "env-manifest.yaml" in str(ei.value)


def test_cli_ledger_at_legacy_name_exits_defect(tmp_path, capsys):
    """Strict surface end-to-end: resolve/CLI on a ledger-bearing
    workspace exits RC_MANIFEST_DEFECT and the error says where facts
    belong (the old failure mode was exit 0 with an invented source)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_ledger(ws, "env-manifest.yaml")
    rc = em.main([str(ws), "--json"])
    assert rc == em.RC_MANIFEST_DEFECT
    err = capsys.readouterr().err
    assert "ledger" in err.lower()
    assert "env-facts.yaml" in err


def test_legacy_valid_manifest_still_loads(tmp_path):
    """A version-carrying manifest written under the pre-rename name
    (branch-era file) still resolves — the fallback is for facts, the
    rejection is for ledger content only."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-manifest.yaml").write_text(
        yaml.safe_dump({"version": 1, "needs_vm": False}, sort_keys=False),
        encoding="utf-8")
    m = em.resolve(ws)
    assert m.source == "manifest-file"
    assert m.needs_vm is False


def test_new_name_wins_over_legacy_facts_file(tmp_path):
    """env-facts.yaml outranks a same-dir legacy file — migration is a
    copy-forward, not an ambiguity."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-manifest.yaml").write_text(
        yaml.safe_dump({"version": 1, "needs_vm": True}, sort_keys=False),
        encoding="utf-8")
    _write_manifest(ws, {"version": 1, "needs_vm": False})
    m = em.resolve(ws)
    assert m.needs_vm is False
    assert m.source == "manifest-file"


def test_layout_conventions_ignores_legacy_ledger(tmp_path, capsys):
    """Hot path: the legacy ledger is not a manifest candidate — default
    layout, no per-dispatch warning (byte-identical pre-#450 discovery)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_ledger(ws, "env-manifest.yaml")
    assert em.layout_conventions(ws) == em.DEFAULT_LAYOUT
    assert capsys.readouterr().err == ""


def test_probe_never_rewrites_deploy_ledger(tmp_path, monkeypatch):
    """F1 repro (review: probe injected version/vm/guest_channel INTO the
    ledger and rewrote it). Post-rename probe owns env-facts.yaml only —
    ledger bytes identical, discovered facts land in the new file."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    ledger = _write_ledger(ws, "env-manifest.yaml")
    ledger_before = ledger.read_text(encoding="utf-8")
    monkeypatch.setattr(em, "_shutil_which", lambda n: "C:/vmrun.exe")
    monkeypatch.setattr(em, "_subprocess_run", _fake_run_ok)
    rc = em.main([str(ws), "--probe"])
    assert rc == 0
    assert ledger.read_text(encoding="utf-8") == ledger_before
    written = yaml.safe_load((ws / "env-facts.yaml")
                             .read_text(encoding="utf-8"))
    assert written["vm"]["vmx_path"] == "C:\\vms-tmp\\win10x64\\vm.vmx"
    assert written["vm"]["snapshot"]["name"] == "analysis-ready"


def test_init_redeploy_preserves_env_facts(tmp_path, monkeypatch):
    """F1 repro (review: init rerun cleared every probe-recorded fact via
    deploy_env's whole-file ledger rewrite). Separate files now:
    deploy_env rewrites its ledger, env-facts.yaml bytes unchanged —
    three-way data preservation (init ledger / env facts / task_spec
    stay independent)."""
    monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "0")
    mod = _load_init_module()
    ws = tmp_path / "ws"
    ws.mkdir()
    facts = ("version: 1\n"
             "vm:\n"
             "  vmx_path: C:/vms-tmp/win10x64/vm.vmx\n"
             "  snapshot:\n"
             "    name: analysis-ready\n")
    facts_file = ws / "env-facts.yaml"
    facts_file.write_text(facts, encoding="utf-8")
    mod.deploy_env(ws, project_type="windows")
    assert (ws / "env-manifest.yaml").exists()  # init wrote its ledger
    assert facts_file.read_text(encoding="utf-8") == facts
    mod.deploy_env(ws, project_type="windows")  # rerun rewrites the ledger
    assert facts_file.read_text(encoding="utf-8") == facts


# ---------- 3. resolve: priority chain ----------

def test_resolve_manifest_file_wins_over_task_spec(tmp_path):
    """Priority 1: an explicit needs_vm in the manifest file beats the
    task_spec derivation (user/probe-written facts outrank inference)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_static_only_task_spec(ws)  # would derive needs_vm=False
    _write_manifest(ws, {"version": 1, "needs_vm": True})
    m = em.resolve(ws)
    assert m.needs_vm is True
    assert m.source == "manifest-file"


def test_resolve_task_spec_used_when_manifest_silent_on_needs_vm(tmp_path):
    """A manifest that does NOT answer needs_vm (probe never writes it)
    falls through to the #449 derivation — a probe-written default file
    must not re-harden a static-only workspace."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_static_only_task_spec(ws)
    _write_manifest(ws, {"version": 1})  # no needs_vm key
    m = em.resolve(ws)
    assert m.needs_vm is False
    assert m.source == "task-spec"
    assert "dynamic_re" in m.basis


def test_resolve_task_spec_when_no_manifest(tmp_path):
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_static_only_task_spec(ws)
    m = em.resolve(ws)
    assert m.needs_vm is False
    assert m.source == "task-spec"


def test_resolve_garbage_manifest_raises(tmp_path):
    """The strict fail-closed surface: resolve propagates load_manifest's
    ValueError — render/CLI treat garbage as a stop event (D2)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-facts.yaml").write_text("{{{{", encoding="utf-8")
    with pytest.raises(ValueError):
        em.resolve(ws)


def test_resolve_non_bool_needs_vm_rejected(tmp_path):
    """F4: needs_vm present-but-non-bool raises — the raise branch had no
    dedicated test. 'yes'/1/[] never silently coerce to a bool answer
    (isinstance(1, bool) is False, so YAML ints are rejected too)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_manifest(ws, {"version": 1, "needs_vm": "yes"})
    with pytest.raises(ValueError) as ei:
        em.resolve(ws)
    assert "needs_vm" in str(ei.value)
    assert "boolean" in str(ei.value)
    _write_manifest(ws, {"version": 1, "needs_vm": 1})
    with pytest.raises(ValueError):
        em.resolve(ws)


def test_resolve_manifest_data_fields(tmp_path):
    """All five fact families round-trip from the file (data, not code)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_manifest(ws, {
        "version": 1,
        "vm": {
            "vmx_path": "C:/vms-tmp/win10x64/vm.vmx",
            "ip_discovery": "live-dhcp",
            "snapshot": {"name": "analysis-ready", "autologin": False,
                         "rollback_fix": "fix-login-state.cmd"},
            "vpmc_compatible": False,
            "frida_start": "Desktop/frida-server.exe -l 0.0.0.0:1337",
        },
        "guest_channel": {
            "preferred": "runScriptInGuest",
            "notes": "runProgramInGuest hangs under legacy Tools 12416",
        },
        "layout": {"workspace_dir": "malws"},
    })
    m = em.resolve(ws)
    assert m.vm.vmx_path == "C:/vms-tmp/win10x64/vm.vmx"
    assert m.vm.snapshot.name == "analysis-ready"
    assert m.vm.snapshot.autologin is False
    assert m.vm.snapshot.rollback_fix == "fix-login-state.cmd"
    assert m.vm.vpmc_compatible is False
    assert m.vm.frida_start == "Desktop/frida-server.exe -l 0.0.0.0:1337"
    assert m.guest_channel.preferred == "runScriptInGuest"
    assert "12416" in m.guest_channel.notes
    # layout merges per-field over the defaults
    assert m.layout.workspace_dir == "malws"
    assert m.layout.claim_register == "claim-register.yaml"
    assert m.layout.runs_dir == "runs"


def test_resolve_garbage_layout_field_rejected(tmp_path):
    """A layout field that is present but empty/garbage is a defect, not a
    silent fallback to default (fail-closed on invented-or-missing names
    would silently change discovery)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_manifest(ws, {"version": 1, "layout": {"workspace_dir": ""}})
    with pytest.raises(ValueError):
        em.resolve(ws)


def test_resolve_non_string_ip_discovery_rejected(tmp_path):
    """F3: ip_discovery present-but-non-string (e.g. [cached]) used to be
    silently str()-coerced to "['cached']" — now rejected in the same
    fail-closed family as the other vm field type checks."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_manifest(ws, {"version": 1, "vm": {"ip_discovery": ["cached"]}})
    with pytest.raises(ValueError) as ei:
        em.resolve(ws)
    assert "ip_discovery" in str(ei.value)
    assert "string" in str(ei.value)


def test_ip_discovery_custom_policy_string_preserved(tmp_path):
    """Only the silent coercion is rejected, not custom policies: a
    non-default string ip_discovery is DATA and round-trips verbatim."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_manifest(ws, {"version": 1,
                         "vm": {"ip_discovery": "static-dns-via-esx"}})
    m = em.resolve(ws)
    assert m.vm.ip_discovery == "static-dns-via-esx"


# ---------- 4. layout_conventions: hot path never raises ----------

def test_layout_conventions_absent_manifest_is_default(tmp_path):
    import env_manifest as em
    layout = em.layout_conventions(_make_ws(tmp_path))
    assert layout == em.DEFAULT_LAYOUT


def test_layout_conventions_garbage_never_raises(tmp_path, capsys):
    """dispatch_gate runs this on EVERY Agent dispatch — garbage must not
    crash the gate. Conservative = the pre-#450 literals + one visible
    warning (fail-open posture for layout; the strict surface is
    load_manifest/render, D2)."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-facts.yaml").write_text("\tbroken: [", encoding="utf-8")
    layout = em.layout_conventions(ws)  # must NOT raise
    assert layout == em.DEFAULT_LAYOUT
    err = capsys.readouterr().err
    assert "env-facts" in err


# ---------- 5. consumer wiring: literal收敛 (backward-compat anchor) ----------

def test_dispatch_resolve_workspace_default_layout(tmp_path):
    """Absent manifest: dispatch_gate._resolve_workspace behaves exactly as
    pre-#450 (cwd/malware-analysis-workspace first, then cwd, gated on
    claim-register.yaml)."""
    from dispatch_gate import _resolve_workspace
    parent = tmp_path / "run"
    ws = parent / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    assert _resolve_workspace({"cwd": str(parent)}) == ws
    # non-workspace dir -> None (silent, pre-#450 behavior)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _resolve_workspace({"cwd": str(empty)}) is None


def test_dispatch_resolve_workspace_custom_layout(tmp_path):
    """A manifest layout override changes WHERE the gate looks for the
    workspace — the literal is a manifest reference now (#450 AC 4)."""
    from dispatch_gate import _resolve_workspace
    parent = tmp_path / "run"
    parent.mkdir()
    _write_manifest(parent / "malware-analysis-workspace",
                    {"version": 1, "layout": {"workspace_dir": "malws",
                                              "claim_register": "claims.yaml"}})
    ws = parent / "malws"
    ws.mkdir()
    (ws / "claims.yaml").write_text("claims: []\n", encoding="utf-8")
    assert _resolve_workspace({"cwd": str(parent)}) == ws


def test_convergence_resolve_ws_default_layout(tmp_path, monkeypatch):
    from convergence_check import _resolve_ws
    parent = tmp_path / "run"
    ws = parent / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    monkeypatch.chdir(parent)
    assert _resolve_ws(None) == ws
    # no register in sight -> cwd itself (pre-#450 behavior)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert _resolve_ws(None) == empty


def test_convergence_resolve_ws_custom_layout(tmp_path, monkeypatch):
    from convergence_check import _resolve_ws
    parent = tmp_path / "run"
    parent.mkdir()
    _write_manifest(parent / "malware-analysis-workspace",
                    {"version": 1, "layout": {"workspace_dir": "malws"}})
    ws = parent / "malws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    monkeypatch.chdir(parent)
    assert _resolve_ws(None) == ws


def test_worktree_scan_custom_layout(tmp_path):
    """lib_kunglao.iter_worker_states: the .wt-* glob, the workspace dir
    name and the runs dir all come from the layout — an override redirects
    the scan (absent manifest: byte-identical default, pinned by the
    existing test_worktree_marker.py)."""
    lib = _load_protocol()
    parent = tmp_path / "run"
    ws = parent / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write_manifest(ws, {"version": 1,
                         "layout": {"worker_worktree_glob": ".worker-*",
                                    "workspace_dir": "malws",
                                    "runs_dir": "runz"}})
    # default-glob worktree must NOT be scanned under the override
    old_wt = parent / ".wt-old" / "malws" / "runz"
    old_wt.mkdir(parents=True)
    (old_wt / "worker-status-a.md").write_text(
        "status: in-progress\n", encoding="utf-8")
    # custom-glob worktree IS scanned
    new_wt = parent / ".worker-new" / "malws" / "runz"
    new_wt.mkdir(parents=True)
    (parent / ".worker-new" / ".kunglao-worktree").write_text(
        "active", encoding="utf-8")
    (new_wt / "worker-status-b.md").write_text(
        "status: in-progress\n", encoding="utf-8")
    states = lib.iter_worker_states(ws)
    files = {Path(s["file"]).name for s in states}
    assert "worker-status-b.md" in files
    assert "worker-status-a.md" not in files


def test_worktree_scan_default_layout_unchanged(tmp_path):
    """Absent manifest: the default .wt-*/malware-analysis-workspace/runs
    scan targets are unchanged (pre-#450 behavior, re-anchored here because
    #450 touches this function)."""
    lib = _load_protocol()
    parent = tmp_path / "run"
    ws = parent / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    wt = parent / ".wt-real" / "malware-analysis-workspace" / "runs"
    wt.mkdir(parents=True)
    (parent / ".wt-real" / ".kunglao-worktree").write_text("active",
                                                           encoding="utf-8")
    (wt / "worker-status-c.md").write_text("status: in-progress\n",
                                           encoding="utf-8")
    states = lib.iter_worker_states(ws)
    assert any(Path(s["file"]).name == "worker-status-c.md" for s in states)


# ---------- 6. --render: env documentation section ----------

def test_render_default_conservative_section(tmp_path, capsys):
    """No manifest, no task_spec: the section states VM REQUIRED with the
    conservative basis, DHCP live-discovery, unknown-identity guidance that
    names the probe entry point — honest absence, never invented facts."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    rc = em.main([str(ws), "--render"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "REQUIRED" in out
    assert "live" in out.lower() and "dhcp" in out.lower()
    assert "--probe" in out  # guidance to discover
    # the five fact families all appear
    for fam in ("Snapshot", "VPMC", "channel", "VM"):
        assert fam.lower() in out.lower()


def test_render_static_only_task_spec(tmp_path, capsys):
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_static_only_task_spec(ws)
    rc = em.main([str(ws), "--render"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "NOT REQUIRED" in out
    assert "dynamic_re" in out  # the basis is cited


def test_render_manifest_data(tmp_path, capsys):
    """Manifest data lands in the section verbatim (values from data, not
    code) — including the snapshot semantics and the channel difference."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_manifest(ws, {
        "version": 1,
        "vm": {"vmx_path": "C:/vms-tmp/w10/vm.vmx",
               "snapshot": {"name": "analysis-ready", "autologin": False,
                            "rollback_fix": "fix-login-state.cmd"},
               "vpmc_compatible": False},
        "guest_channel": {"preferred": "runScriptInGuest",
                          "notes": "runProgramInGuest hangs (legacy Tools)"},
    })
    rc = em.main([str(ws), "--render"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "C:/vms-tmp/w10/vm.vmx" in out
    assert "analysis-ready" in out
    assert "fix-login-state.cmd" in out
    assert "autologin" in out.lower()
    assert "runScriptInGuest" in out


def test_cli_render_garbage_manifest_exits_defect(tmp_path, capsys):
    """Strict surface: garbage manifest is a STOP event for rendering —
    exit RC_MANIFEST_DEFECT with the filename, no invented section."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    (ws / "env-facts.yaml").write_text(": : :", encoding="utf-8")
    rc = em.main([str(ws), "--render"])
    assert rc == em.RC_MANIFEST_DEFECT
    assert "env-facts.yaml" in capsys.readouterr().err


def test_cli_json_summary_default(tmp_path, capsys):
    import env_manifest as em
    ws = _make_ws(tmp_path)
    rc = em.main([str(ws), "--json"])
    assert rc == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert data["source"] == "default"
    assert data["needs_vm"] is True


# ---------- 7. --probe: minimal discovery entry (fail-open) ----------

_VMRUN_LIST_OUT = (
    "Total running VMs: 1\r\nC:\\vms-tmp\\win10x64\\vm.vmx\r\n")
_VMRUN_SNAP_OUT = "Total snapshots: 2\r\nanalysis-ready\r\nbase\r\n"


def _fake_run_ok(args, **kwargs):
    """Seam stub: vmrun list / listSnapshots succeed, checkToolsState
    reports Tools running."""
    import subprocess

    class R:
        returncode = 0
        stdout = (_VMRUN_LIST_OUT if args[1:2] == ["list"]
                  else _VMRUN_SNAP_OUT if args[1:2] == ["listSnapshots"]
                  else "running\n")  # checkToolsState
        stderr = ""
    return R()


def test_probe_discovers_and_writes_manifest(tmp_path, monkeypatch, capsys):
    import env_manifest as em
    ws = _make_ws(tmp_path)
    monkeypatch.setattr(em, "_shutil_which", lambda n: "C:/vmrun.exe")
    monkeypatch.setattr(em, "_subprocess_run", _fake_run_ok)
    rc = em.main([str(ws), "--probe"])
    assert rc == 0
    written = yaml.safe_load((ws / "env-facts.yaml")
                             .read_text(encoding="utf-8"))
    assert written["vm"]["vmx_path"] == "C:\\vms-tmp\\win10x64\\vm.vmx"
    assert written["vm"]["snapshot"]["name"] == "analysis-ready"
    assert "needs_vm" not in written  # probe never answers the requirement
    assert "running" in written["guest_channel"]["notes"]


def test_probe_merges_without_clobbering_user_fields(tmp_path, monkeypatch):
    """User/probe-written facts have priority 1: probe fills the gaps, it
    does not overwrite what the user already recorded."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    _write_manifest(ws, {
        "version": 1,
        "vm": {"vpmc_compatible": False,
               "snapshot": {"autologin": False,
                            "rollback_fix": "fix-login-state.cmd"}},
        "guest_channel": {"preferred": "runScriptInGuest"},
    })
    monkeypatch.setattr(em, "_shutil_which", lambda n: "C:/vmrun.exe")
    monkeypatch.setattr(em, "_subprocess_run", _fake_run_ok)
    rc = em.main([str(ws), "--probe"])
    assert rc == 0
    written = yaml.safe_load((ws / "env-facts.yaml")
                             .read_text(encoding="utf-8"))
    assert written["vm"]["vpmc_compatible"] is False        # preserved
    assert written["vm"]["snapshot"]["rollback_fix"] == "fix-login-state.cmd"
    assert written["guest_channel"]["preferred"] == "runScriptInGuest"
    assert written["vm"]["vmx_path"]                        # discovered
    assert written["vm"]["snapshot"]["name"] == "analysis-ready"


def test_probe_no_vmrun_fails_open_with_guidance(tmp_path, monkeypatch,
                                                 capsys):
    """#450 evidence 3: discovery failure must NOT block — conservative
    defaults + guidance, exit 0, no manifest written."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    monkeypatch.setattr(em, "_shutil_which", lambda n: None)
    rc = em.main([str(ws), "--probe"])
    assert rc == 0
    assert not (ws / "env-facts.yaml").exists()
    out = capsys.readouterr()
    assert "vmrun" in (out.out + out.err).lower()


def test_probe_no_running_vms_fails_open(tmp_path, monkeypatch, capsys):
    import env_manifest as em
    ws = _make_ws(tmp_path)
    monkeypatch.setattr(em, "_shutil_which", lambda n: "C:/vmrun.exe")

    def empty(args, **kwargs):
        class R:
            returncode = 0
            stdout = "Total running VMs: 0\r\n"
            stderr = ""
        return R()

    monkeypatch.setattr(em, "_subprocess_run", empty)
    rc = em.main([str(ws), "--probe"])
    assert rc == 0
    assert not (ws / "env-facts.yaml").exists()
    probe_out = capsys.readouterr().out.lower()
    assert "probe" in probe_out or "guidance" in probe_out


def test_probe_refuses_to_overwrite_garbage_manifest(tmp_path, monkeypatch):
    """User data is never silently rebuilt from garbage — refuse (exit
    RC_MANIFEST_DEFECT), file left untouched."""
    import env_manifest as em
    ws = _make_ws(tmp_path)
    garbage = "{{{ broken"
    (ws / "env-facts.yaml").write_text(garbage, encoding="utf-8")
    monkeypatch.setattr(em, "_shutil_which", lambda n: "C:/vmrun.exe")
    monkeypatch.setattr(em, "_subprocess_run", _fake_run_ok)
    rc = em.main([str(ws), "--probe"])
    assert rc == em.RC_MANIFEST_DEFECT
    assert (ws / "env-facts.yaml").read_text(encoding="utf-8") == garbage


# ---------- 8. kunglao-init CLAUDE.md "VM required" conditionalization ----------

_PAYLOAD = b"MZ\x90\x00" + b"\x00" * 64


def _render_claudemd(mod, tmp_path: Path) -> str:
    import hashlib
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(_PAYLOAD)
    target = mod.write_claudemd(ws, "sample.exe",
                                hashlib.sha256(_PAYLOAD).hexdigest(),
                                project_type="windows")
    assert target is not None
    return target.read_text(encoding="utf-8")


def test_claudemd_static_only_task_spec_conditions_vm_line(tmp_path):
    """#449 leftover closed: a static-only task renders 'VM not required'
    (with the task_spec basis) instead of the unconditional 'VM required'
    line — the CLAUDE.md env section follows env = f(task_spec)."""
    mod = _load_init_module()
    ws_holder = tmp_path / "ws"
    ws_holder.mkdir()
    _write_static_only_task_spec(ws_holder)
    text = _render_claudemd(mod, tmp_path)
    assert "**VM required**" not in text
    assert "VM not required" in text
    assert "dynamic_re" in text  # basis cited


def test_claudemd_no_inputs_keeps_unconditional_line(tmp_path):
    """Backward-compat anchor: no manifest + no task_spec keeps the
    pre-#450 unconditional line (renderer golden byte-identity holds)."""
    mod = _load_init_module()
    text = _render_claudemd(mod, tmp_path)
    assert "- **VM required**:" in text


def test_claudemd_manifest_false_needs_vm_conditions_vm_line(tmp_path):
    """Manifest priority 1: an explicit needs_vm=false in env-facts.yaml
    conditions the line even without a task_spec."""
    mod = _load_init_module()
    ws_holder = tmp_path / "ws"
    ws_holder.mkdir()
    _write_manifest(ws_holder, {"version": 1, "needs_vm": False})
    text = _render_claudemd(mod, tmp_path)
    assert "**VM required**" not in text
    assert "VM not required" in text
    assert "env-facts" in text  # basis cites the manifest source


def test_claudemd_manifest_true_needs_vm_keeps_line(tmp_path):
    """Explicit needs_vm=true keeps the unconditional line (needs VM stays
    the documented hard requirement)."""
    mod = _load_init_module()
    ws_holder = tmp_path / "ws"
    ws_holder.mkdir()
    _write_manifest(ws_holder, {"version": 1, "needs_vm": True})
    text = _render_claudemd(mod, tmp_path)
    assert "- **VM required**:" in text


def test_claudemd_garbage_manifest_keeps_unconditional_line(tmp_path, capsys):
    """Garbage manifest on the render path = conservative unconditional
    line + one visible warning (never a crash, never a conditioned line
    based on unreadable facts)."""
    mod = _load_init_module()
    ws_holder = tmp_path / "ws"
    ws_holder.mkdir()
    (ws_holder / "env-facts.yaml").write_text("\t: [", encoding="utf-8")
    text = _render_claudemd(mod, tmp_path)
    assert "- **VM required**:" in text


# ---------- #477 ④: installed ledger (record_installed) ----------

def _load_env_manifest():
    import env_manifest
    return env_manifest


def test_record_installed_creates_section(tmp_path):
    mod = _load_env_manifest()
    ws = tmp_path / "ws"
    ws.mkdir()
    ok = mod.record_installed(ws, "pefile", "pip", "PASS")
    assert ok is True
    data = yaml.safe_load((ws / "env-facts.yaml").read_text(encoding="utf-8"))
    entry = data["installed"]["pefile"]
    assert entry["manager"] == "pip"
    assert entry["reprobe"] == "PASS"
    assert entry["at"]  # timestamp present
    assert data["version"] == mod.MANIFEST_VERSION


def test_record_installed_merges_preserving_user_fields(tmp_path):
    """User facts survive an install-ledger write (probe's never-clobber
    rule); prior installs of OTHER tools survive too."""
    mod = _load_env_manifest()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "env-facts.yaml").write_text(yaml.safe_dump({
        "version": 1,
        "needs_vm": False,
        "vm": {"vmx_path": "D:/vms/analysis.vmx"},
        "installed": {"floss": {"manager": "pip", "at": "2026-08-19T00:00:00",
                                "reprobe": "PASS"}},
    }, sort_keys=False), encoding="utf-8")
    ok = mod.record_installed(ws, "pefile", "pip", "PASS")
    assert ok is True
    data = yaml.safe_load((ws / "env-facts.yaml").read_text(encoding="utf-8"))
    assert data["needs_vm"] is False
    assert data["vm"]["vmx_path"] == "D:/vms/analysis.vmx"
    assert data["installed"]["floss"]["manager"] == "pip"
    assert data["installed"]["pefile"]["manager"] == "pip"


def test_record_installed_reinstall_updates_entry(tmp_path):
    """Per-tool update-wins: re-installing a tool REPLACES its stale entry
    (unlike the probe gap-filler merge — the ledger records the LATEST
    state of each tool, e.g. after an upgrade)."""
    mod = _load_env_manifest()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "env-facts.yaml").write_text(yaml.safe_dump({
        "version": 1,
        "installed": {"die": {"manager": "choco", "at": "2026-01-01T00:00:00",
                              "reprobe": "PASS"}},
    }, sort_keys=False), encoding="utf-8")
    mod.record_installed(ws, "die", "winget", "PASS", at="2026-08-20T00:00:00")
    data = yaml.safe_load((ws / "env-facts.yaml").read_text(encoding="utf-8"))
    assert data["installed"]["die"] == {
        "manager": "winget", "at": "2026-08-20T00:00:00", "reprobe": "PASS"}


def test_record_installed_refuses_garbage_manifest(tmp_path, capsys):
    """A defective facts file is never overwritten (mirror of --probe's
    refuse-to-clobber); False + stderr guidance, no exception."""
    mod = _load_env_manifest()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "env-facts.yaml").write_text("\t: [", encoding="utf-8")
    ok = mod.record_installed(ws, "pefile", "pip", "PASS")
    assert ok is False
    assert "\t: [" in (ws / "env-facts.yaml").read_text(encoding="utf-8")
    err = capsys.readouterr().err
    assert "refusing" in err.lower() or "ERROR" in err, err


def test_record_installed_non_string_fails_closed(tmp_path):
    mod = _load_env_manifest()
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(ValueError):
        mod.record_installed(ws, 123, "pip", "PASS")
    with pytest.raises(ValueError):
        mod.record_installed(ws, "pefile", "pip", ["PASS"])


def test_installed_section_never_breaks_resolve_or_ledger_detector(
        tmp_path):
    """installed is write-through ledger data: resolve() still works and
    the #478 deploy-ledger shape detector cannot fire (version present)."""
    mod = _load_env_manifest()
    ws = tmp_path / "ws"
    ws.mkdir()
    mod.record_installed(ws, "pefile", "pip", "PASS")
    m = mod.resolve(ws)  # must not raise
    assert m is not None
    raw = mod.load_manifest(ws)
    assert raw is not None and raw["installed"]["pefile"]["manager"] == "pip"
