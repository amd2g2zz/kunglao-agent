# -*- coding: utf-8 -*-
"""Issue 202 (+ addendum): toolchain gate proactive probing + ownership tiers.

Field-reported failures are normative:

  1. The gate dumped `claude mcp add` / `adb shell resetprop` / frida bring-up
     onto the user — those are AGENT-DO actions (same machine, agent-owned
     CLI/device access). Escalation to the user happens ONLY on genuine
     failure, with the error attached.
  2. The decompiler face gated on LOCAL idat64 while the task declared the
     ida-pro-vm MCP lane — the face must be LANE-CONDITIONAL: MCP lane checks
     registration + reachability and NEVER a local IDA install/license;
     the local lane probes IDA (ordered ladder: PATH -> mdfind -> find bundle
     sweep -> brew cask -> known dirs) then Ghidra; neither -> exit-8
     PendingDecision CHOICE (the only user touchpoint, and it is a choice).
  3. Addendum blind spot: an installed IDA inside a `.app` bundle
     (`IDA Professional 9.0.app/Contents/MacOS/idat64`) was reported missing
     because probes only knew `/Applications/IDA Pro*/idabin` shapes.

Every check carries an owner class: agent_do / human_only / lane_conditional.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import platform_paths  # pytest.ini pythonpath = . hooks scripts tools
import toolchain as tc

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


# ---------- hermetic helpers (pattern: tests/test_toolchain.py) ----------


def _isolated_registry(tmp_path: Path, servers: dict | None = None) -> Path:
    """Empty/user-scripted MCP registry via the documented test override."""
    reg = tmp_path / "isolated-claude.json"
    reg.write_text(json.dumps({"mcpServers": servers or {}}),
                   encoding="utf-8")
    return reg


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Hostile probe env: empty PATH, no GHIDRA_HOME/VM host, empty registry,
    agent-do write attempts OFF unless a test opts in."""
    empty = tmp_path / "empty-bin-202"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
    monkeypatch.delenv("KUNGLAO_AGENT_DO", raising=False)
    monkeypatch.delenv("KUNGLAO_MCP_AUTO_REGISTER", raising=False)
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON",
                       str(_isolated_registry(tmp_path)))
    return empty


@pytest.fixture
def ws(tmp_path) -> Path:
    w = tmp_path / "ws-202"
    w.mkdir()
    return w


def _listener() -> tuple[socket.socket, int]:
    srv = socket.create_server(("127.0.0.1", 0))
    return srv, srv.getsockname()[1]


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen in name blocks import)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_gate_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kunglao_init_gate_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- 1. ownership tiers ----------


class TestOwnershipTiers:
    def test_owner_tier_mapping(self):
        """Every check name maps to an owner class: agent-do is the default;
        rooting/VM/credentials are human-only; the decompiler face is
        lane-conditional."""
        assert tc.owner_for("mcp:sequential-thinking") is tc.OwnerTier.AGENT_DO
        assert tc.owner_for("mcp:ida-pro-vm") is tc.OwnerTier.AGENT_DO
        assert tc.owner_for("adb") is tc.OwnerTier.AGENT_DO
        assert tc.owner_for("debug_flag") is tc.OwnerTier.AGENT_DO
        assert tc.owner_for("frida_server") is tc.OwnerTier.AGENT_DO
        assert tc.owner_for("android_server") is tc.OwnerTier.AGENT_DO
        assert tc.owner_for("pefile") is tc.OwnerTier.AGENT_DO
        assert tc.owner_for("device_root") is tc.OwnerTier.HUMAN_ONLY
        assert tc.owner_for("vm_reachable") is tc.OwnerTier.HUMAN_ONLY
        assert tc.owner_for("remote_debugger") is tc.OwnerTier.HUMAN_ONLY
        assert tc.owner_for("decompiler") is tc.OwnerTier.LANE_CONDITIONAL
        assert tc.owner_for("ghidra") is tc.OwnerTier.LANE_CONDITIONAL
        assert tc.owner_for("ida") is tc.OwnerTier.LANE_CONDITIONAL

    def test_every_report_item_carries_owner(self, clean_env, ws, monkeypatch,
                                             tmp_path):
        """A full windows + android report stamps an owner on EVERY item, and
        --json exposes it (machine channel for the init-worker relay)."""
        monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(_isolated_registry(
            tmp_path, {"ghidra": {}, "sequential-thinking": {}})))
        for project_type in ("windows", "android"):
            report = tc.check(ws, project_type)
            assert report.items, project_type
            for item in report.items:
                assert isinstance(item.owner, tc.OwnerTier), (project_type,
                                                              item)

    def test_owner_rides_json_output(self, clean_env, ws, tmp_path,
                                     monkeypatch):
        monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(_isolated_registry(
            tmp_path, {"ghidra": {}, "sequential-thinking": {}})))
        report = tc.check(ws, "windows")
        data = json.loads(tc.format_json(report))
        by_name = {c["name"]: c for c in data["checks"]}
        assert by_name["decompiler"]["owner"] == "lane_conditional"
        assert by_name["vm_reachable"]["owner"] == "human_only"
        assert by_name["mcp:sequential-thinking"]["owner"] == "agent_do"


# ---------- 2. decompiler probe ladder (local lane) ----------


class TestIdaProbeLadder:
    def _seed_bundle(self, root: Path) -> Path:
        """`IDA Professional 9.0.app/Contents/MacOS/idat64` — the field-
        evidenced blind spot (addendum): canonical-dir shapes miss it."""
        bin_dir = root / "IDA Professional 9.0.app" / "Contents" / "MacOS"
        bin_dir.mkdir(parents=True)
        idat = bin_dir / "idat64"
        idat.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        idat.chmod(0o755)
        return idat

    def test_bundle_layout_missed_by_canonical_found_by_ladder(
            self, tmp_path):
        """Acceptance (addendum): a seeded fake `.app` bundle layout that the
        canonical-dir probe misses and the new strategy finds."""
        apps = tmp_path / "Applications"
        apps.mkdir()
        idat = self._seed_bundle(apps)
        # The OLD canonical shape (`IDA Pro*/idabin`) must NOT match — this
        # is the exact blind spot from the field report.
        old_shape = tc._probe_ida_via_known_dirs(
            patterns=(str(apps / "IDA Pro*"
                          / "idabin" / "idat64*"),))
        assert old_shape is None, (
            "canonical-dir shape must miss the bundle layout "
            "(that miss is the field-reported defect)")
        path, strategy = tc._probe_local_ida(app_dirs=(apps,))
        assert path == idat, (path, strategy)
        assert strategy, "the ladder must record which strategy hit"

    def test_mdfind_first_hit_wins_and_short_circuits(self, tmp_path,
                                                      monkeypatch):
        """Ordered ladder, first hit wins: a mdfind hit ends the ladder —
        find/brew/known-dirs are never invoked."""
        apps = tmp_path / "apps-mdfind"
        apps.mkdir()
        hit = apps / "somewhere" / "idat64"
        hit.parent.mkdir(parents=True)
        hit.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hit.chmod(0o755)
        calls: list[list[str]] = []

        def fake_run(args, timeout=10):
            calls.append(list(args))
            if args[:1] == ["mdfind"]:
                return 0, f"{hit}\n", ""
            return 1, "", ""

        monkeypatch.setattr(tc, "_run_cmd", fake_run)
        monkeypatch.setattr(tc, "_shutil_which", lambda name: None)
        path, strategy = tc._probe_local_ida(app_dirs=(apps,))
        assert path == hit
        assert "mdfind" in strategy
        assert not any(a[:1] == ["brew"] for a in calls), calls
        assert not any(a[:1] == ["find"] for a in calls), calls

    def test_mdfind_missing_falls_through_to_find_sweep(self, tmp_path,
                                                        monkeypatch):
        """Addendum: missing mdfind / no Spotlight index falls through to the
        find sweep with the bundle patterns."""
        apps = tmp_path / "apps-fallthrough"
        apps.mkdir()
        idat = self._seed_bundle(apps)

        def fake_run(args, timeout=10):
            if args[:1] == ["mdfind"]:
                return 1, "", "mdfind: command not found"
            return 1, "", ""

        monkeypatch.setattr(tc, "_run_cmd", fake_run)
        monkeypatch.setattr(tc, "_shutil_which", lambda name: None)
        path, strategy = tc._probe_local_ida(app_dirs=(apps,))
        assert path == idat
        assert "find" in strategy or "sweep" in strategy

    def test_brew_cask_strategy(self, tmp_path, monkeypatch):
        """brew list --cask | grep -i ida hit resolves through the cask
        prefix (Caskroom layout) to the bundle idat64."""
        cask_root = tmp_path / "Caskroom" / "ida-professional" / "9.0"
        idat = self._seed_bundle(cask_root)
        brew = tmp_path / "brew"

        def fake_run(args, timeout=10):
            if str(args[0]).endswith("brew") and args[1:2] == ["list"]:
                return 0, "ghidra\nida-professional\n", ""
            if str(args[0]).endswith("brew") and args[1:2] == ["--prefix"]:
                return 0, str(cask_root), ""
            return 1, "", ""

        monkeypatch.setattr(tc, "_run_cmd", fake_run)
        monkeypatch.setattr(tc, "_shutil_which",
                            lambda name: str(brew) if name == "brew" else None)
        path, strategy = tc._probe_local_ida(app_dirs=(tmp_path / "nope",))
        assert path == idat
        assert "brew" in strategy

    def test_known_dir_sweep_covers_bundle_and_cross_platform_shapes(self):
        """The known-dir sweep defaults include the macOS bundle layout and
        the Windows/Linux equivalents (an /opt form and a Program Files
        drive-letter form)."""
        import inspect
        src = inspect.getsource(tc._probe_ida_via_known_dirs)
        blob = src + repr(tc._IDA_KNOWN_DIR_PATTERNS)
        assert "Contents/MacOS" in blob or "Contents\\MacOS" in blob
        assert "/opt/ida" in blob
        assert "IDA*" in blob
        assert "ida64" in blob or "idat64" in blob

    def test_ghidra_fallback_dirs(self, tmp_path, monkeypatch):
        """No IDA anywhere -> Ghidra probe: GHIDRA_HOME, /opt/ghidra*,
        /usr/local/ghidra*, ~/ghidra*, brew prefix — first hit passes."""
        home = tmp_path / "home"
        gdir = home / "ghidra_11.3.1_PUBLIC"
        support = gdir / "support"
        support.mkdir(parents=True)
        headless = support / platform_paths.analyze_headless_name()
        headless.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        headless.chmod(0o755)

        def fake_run(args, timeout=10):
            if args[:1] == ["brew"]:
                return 1, "", ""
            return 1, "", ""

        monkeypatch.setattr(tc, "_run_cmd", fake_run)
        monkeypatch.setattr(tc, "_shutil_which", lambda name: None)
        monkeypatch.delenv("GHIDRA_HOME", raising=False)
        found = tc._probe_ghidra(search_dirs=(home,))
        assert found == headless, found


class TestDecompilerLaneConditional:
    def _task_spec(self, port: int | None = None) -> dict:
        tools: dict = {"decompiler_lane": "mcp"}
        if port is not None:
            tools["mcp_servers"] = [{
                "name": "ida-pro-vm", "transport": "http",
                "url": f"http://127.0.0.1:{port}",
            }]
        return {"constraints": {"dynamic_re": "forbidden"}, "tools": tools}

    def test_requirements_parse_lane_and_mcp(self):
        reqs = tc.requirements_from_task_spec(self._task_spec(13337))
        assert reqs.decompiler_lane == "mcp"
        assert reqs.required_mcp[0].name == "ida-pro-vm"
        assert reqs.required_mcp[0].transport == "http"
        assert reqs.required_mcp[0].url == "http://127.0.0.1:13337"
        # absent field stays conservative None
        assert tc.requirements_from_task_spec(
            {"constraints": {}}).decompiler_lane is None

    def test_mcp_lane_task_passes_with_no_local_ida(
            self, clean_env, ws, monkeypatch):
        """Acceptance: a task declaring the ida-pro-vm MCP lane passes the
        decompiler face with NO local IDA — and the local ladder is never
        even consulted (never a local install/license demand)."""
        srv, port = _listener()
        with srv:
            monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(_isolated_registry(
                ws.parent, {"ida-pro-vm": {}, "sequential-thinking": {}})))
            monkeypatch.setattr(
                tc, "_probe_local_ida",
                lambda *a, **k: pytest.fail(
                    "local IDA ladder must not run on the MCP lane"))
            monkeypatch.setattr(
                tc, "_probe_ghidra",
                lambda *a, **k: pytest.fail(
                    "Ghidra fallback must not run on the MCP lane"))
            report = tc.check(ws, "windows",
                              task_spec=self._task_spec(port))
        decomp = next(i for i in report.items if i.name == "decompiler")
        assert decomp.status is tc.Status.PASS, decomp
        assert "ida-pro-vm" in decomp.detail
        assert "reachable" in decomp.detail
        blob = json.dumps(tc.format_json(report))
        assert "install IDA" not in blob

    def test_mcp_lane_registered_but_dead_endpoint_fails_with_error(
            self, clean_env, ws):
        """Registered but unreachable endpoint -> FAIL carrying the connect
        error (escalate only genuine failures, error attached)."""
        # port 1 on 127.0.0.1: nothing listens (connect refused, fast)
        report = tc.check(ws, "windows", task_spec=self._task_spec(1))
        decomp = next(i for i in report.items if i.name == "decompiler")
        assert decomp.status is tc.Status.FAIL, decomp
        assert "ida-pro-vm" in decomp.detail
        assert decomp.fix and "install IDA" not in decomp.fix
        assert decomp.owner is tc.OwnerTier.LANE_CONDITIONAL

    def test_mcp_lane_missing_server_agent_registers_it(
            self, clean_env, ws, monkeypatch, tmp_path):
        """AGENT-DO: a missing ida-pro-vm on the MCP lane is registered by
        the gate itself (claude mcp add --transport http with the task_spec
        url) and re-verified — the user is never handed the command."""
        srv, port = _listener()
        fake_bin = tmp_path / "claude-bin-c"
        fake_bin.mkdir()
        (fake_bin / "claude").write_text("#!/bin/sh\nexit 0\n",
                                         encoding="utf-8")
        (fake_bin / "claude").chmod(0o755)
        monkeypatch.setenv("PATH", str(fake_bin))
        reg = _isolated_registry(ws.parent)  # NOT registered yet
        monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(reg))
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        attempts: list[list[str]] = []

        def fake_attempt(argv):
            attempts.append(list(argv))
            data = json.loads(reg.read_text(encoding="utf-8"))
            data.setdefault("mcpServers", {})["ida-pro-vm"] = {
                "type": "http", "url": f"http://127.0.0.1:{port}"}
            reg.write_text(json.dumps(data), encoding="utf-8")
            return True, ""

        monkeypatch.setattr(tc, "_attempt_mcp_register", fake_attempt)
        with srv:
            report = tc.check(ws, "windows", task_spec=self._task_spec(port))
        assert attempts, "the gate must attempt the registration itself"
        assert attempts[0][:4] == ["claude", "mcp", "add", "--transport"]
        assert "ida-pro-vm" in attempts[0]
        assert f"http://127.0.0.1:{port}" in attempts[0]
        decomp = next(i for i in report.items if i.name == "decompiler")
        assert decomp.status is tc.Status.PASS, decomp

    def test_local_lane_uses_probe_ladder_not_mcp(
            self, clean_env, ws, tmp_path, monkeypatch):
        """lane=local: a seeded bundle idat64 PASSES the face (wired path),
        even with no MCP registered at all."""
        apps = tmp_path / "apps-local"
        apps.mkdir()
        bin_dir = apps / "IDA Professional 9.0.app" / "Contents" / "MacOS"
        bin_dir.mkdir(parents=True)
        idat = bin_dir / "idat64"
        idat.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        idat.chmod(0o755)

        def fake_run(args, timeout=10):
            return 1, "", ""  # mdfind/brew absent in the probe env

        monkeypatch.setattr(tc, "_run_cmd", fake_run)
        monkeypatch.setattr(tc, "_probe_local_ida",
                            lambda app_dirs=None: (
                                idat, "find-sweep(bundle:.app/Contents/MacOS)"))
        report = tc.check(ws, "windows", task_spec={
            "constraints": {"dynamic_re": "forbidden"},
            "tools": {"decompiler_lane": "local"}})
        ida = next(i for i in report.items if i.name == "ida")
        assert ida.status is tc.Status.PASS, ida
        assert str(idat) in ida.detail
        assert "PATH" in ida.detail  # wiring/export record

    def test_neither_found_pending_choice_item(
            self, clean_env, ws):
        """Neither IDA nor Ghidra nor MCP -> the decompiler FAIL carries the
        exit-8 CHOICE (three options), never a plain blocker dump."""
        report = tc.check(ws, "windows", task_spec={
            "constraints": {"dynamic_re": "forbidden"},
            "tools": {"mcp_servers": []}})
        decomp = next(i for i in report.items if i.name == "decompiler")
        assert decomp.status is tc.Status.FAIL, decomp
        assert decomp.pending_decision is not None
        pd = decomp.pending_decision
        assert pd.kind == "choice"
        assert pd.decision_id == "decompiler_lane"
        assert set(pd.options) == {
            "install-local-ida", "install-ghidra", "skip-decompiler-lane"}

    def test_main_emits_exit8_pending_doc_when_sole_blocker(
            self, tmp_path, ws):
        """toolchain.py CLI: the choice doc prints as the pending JSON doc and
        the process exits 8 — the ONLY user touchpoint, and a choice."""
        fake_bin = tmp_path / "fb-202"
        fake_bin.mkdir()
        for name in ("pefile", "die", "floss", "uv"):
            stub = fake_bin / name
            # pure /bin/sh: the hostile PATH has no python3 for a python shebang
            stub.write_text(
                "#!/bin/sh\nfor a in \"$@\"; do case \"$a\" in "
                "--version|*) echo \"$0 version 1.0\";; esac; break; done\n"
                "exit 0\n", encoding="utf-8")
            stub.chmod(0o755)
        (ws / "task_spec.yaml").write_text(
            "constraints:\n  dynamic_re: forbidden\ntools:\n"
            "  mcp_servers: []\n", encoding="utf-8")
        (ws.parent / "empty-202.json").write_text("{}", encoding="utf-8")
        env = {k: v for k, v in os.environ.items()
               if k not in ("GHIDRA_HOME", "KUNGLAO_VM_HOST",
                            "KUNGLAO_CLAUDE_JSON", "KUNGLAO_AGENT_DO")}
        env["PATH"] = str(fake_bin)
        env["KUNGLAO_CLAUDE_JSON"] = str(ws.parent / "empty-202.json")
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "toolchain.py"), str(ws),
             "--type", "windows", "--json"],
            capture_output=True, text=True, timeout=120, env=env,
            errors="replace")
        assert r.returncode == 8, f"{r.returncode}: {r.stdout}{r.stderr}"
        doc = json.loads(r.stdout)
        assert doc["flow"] == "toolchain"
        ids = [d["decision_id"] for d in doc["decisions"]]
        assert "decompiler_lane" in ids
        choice = next(d for d in doc["decisions"]
                      if d["decision_id"] == "decompiler_lane")
        assert choice["kind"] == "choice"

    def test_mixed_hard_fail_keeps_exit1_with_choice_attached(
            self, clean_env, ws, tmp_path, monkeypatch):
        """A pending choice never masks a real blocker: with another HARD
        FAIL present the report still exits 1 (the choice rides in JSON)."""
        report = tc.check(ws, "windows", task_spec={
            "constraints": {"dynamic_re": "allowed"},
            "tools": {"mcp_servers": []}})
        decomp = next(i for i in report.items if i.name == "decompiler")
        assert decomp.pending_decision is not None
        assert report.exit_code == 1
        data = json.loads(tc.format_json(report))
        by_name = {c["name"]: c for c in data["checks"]}
        assert by_name["decompiler"]["pending_decision"]["decision_id"] \
            == "decompiler_lane"


# ---------- 3. MCP face: agent registers required servers itself ----------


class TestMcpAgentDoFace:
    def test_concrete_register_argv(self):
        """Placeholders resolve from the task_spec url; placeholder-free
        templates run verbatim; unresolvable templates return None (never a
        literal `<ida-mcp-url>` reaches a shell)."""
        argv = tc._concrete_register_argv(
            "claude mcp add --transport http ida-pro-vm <ida-mcp-url>",
            url="http://127.0.0.1:13337")
        assert argv == ["claude", "mcp", "add", "--transport", "http",
                        "ida-pro-vm", "http://127.0.0.1:13337"]
        assert tc._concrete_register_argv(
            "claude mcp add --transport http ida-pro-vm <ida-mcp-url>",
            url=None) is None
        assert tc._concrete_register_argv(
            "claude mcp add sequential-thinking -- "
            "npx -y @modelcontextprotocol/server-sequential-thinking",
            url=None) == [
            "claude", "mcp", "add", "sequential-thinking", "--", "npx", "-y",
            "@modelcontextprotocol/server-sequential-thinking"]
        assert tc._concrete_register_argv(
            "claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe",
            url=None) is None

    def test_missing_required_server_attempted_and_reverified(
            self, clean_env, ws, monkeypatch, tmp_path):
        """AGENT-DO MCP face: a missing manifest-required server is
        registered by the gate and re-verified -> PASS (owner agent_do)."""
        fake_bin = tmp_path / "claude-bin-a"
        fake_bin.mkdir()
        (fake_bin / "claude").write_text("#!/bin/sh\nexit 0\n",
                                         encoding="utf-8")
        (fake_bin / "claude").chmod(0o755)
        monkeypatch.setenv("PATH", str(fake_bin))
        reg = _isolated_registry(tmp_path)
        monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(reg))
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")

        def fake_attempt(argv):
            data = json.loads(reg.read_text(encoding="utf-8"))
            data.setdefault("mcpServers", {})["sequential-thinking"] = {}
            reg.write_text(json.dumps(data), encoding="utf-8")
            return True, ""

        monkeypatch.setattr(tc, "_attempt_mcp_register", fake_attempt)
        report = tc.check(ws, "windows")
        item = next(i for i in report.items
                    if i.name == "mcp:sequential-thinking")
        assert item.status is tc.Status.PASS, item
        assert item.owner is tc.OwnerTier.AGENT_DO
        assert "registered by agent" in item.detail

    def test_register_failure_escalates_with_error_attached(
            self, clean_env, ws, monkeypatch, tmp_path):
        fake_bin = tmp_path / "claude-bin-b"
        fake_bin.mkdir()
        (fake_bin / "claude").write_text("#!/bin/sh\nexit 1\n",
                                         encoding="utf-8")
        (fake_bin / "claude").chmod(0o755)
        monkeypatch.setenv("PATH", str(fake_bin))
        reg = _isolated_registry(tmp_path)
        monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(reg))
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        monkeypatch.setattr(
            tc, "_attempt_mcp_register",
            lambda argv: (False, "claude: command failed (rc=1): boom"))
        report = tc.check(ws, "windows")
        item = next(i for i in report.items
                    if i.name == "mcp:sequential-thinking")
        assert item.status is tc.Status.FAIL, item
        assert "boom" in item.detail, "the attempt error must be attached"
        assert item.owner is tc.OwnerTier.AGENT_DO

    def test_register_suppressed_when_disabled_or_override_config(
            self, clean_env, ws, monkeypatch, tmp_path):
        """Read-only contract: no attempt without KUNGLAO_AGENT_DO=1, and
        never when the probe targets an override registry (claude mcp add
        would mutate the REAL config the probe cannot see)."""
        fake_bin = tmp_path / "claude-bin"
        fake_bin.mkdir()
        claude = fake_bin / "claude"
        claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        claude.chmod(0o755)
        monkeypatch.setenv("PATH", str(fake_bin))
        reg = _isolated_registry(tmp_path)
        monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(reg))
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        before = reg.read_text(encoding="utf-8")
        report = tc.check(ws, "windows")
        item = next(i for i in report.items
                    if i.name == "mcp:sequential-thinking")
        assert item.status is tc.Status.FAIL
        assert "override" in item.detail, item.detail
        assert reg.read_text(encoding="utf-8") == before, \
            "the override registry must never be mutated"

        monkeypatch.delenv("KUNGLAO_AGENT_DO")
        report = tc.check(ws, "windows")
        item = next(i for i in report.items
                    if i.name == "mcp:sequential-thinking")
        assert item.status is tc.Status.FAIL
        assert "agent-do disabled" in item.detail


# ---------- 4. AGENT-DO device face (android) ----------

_ADB_STUB_STATE = """
import json, os, sys
args = sys.argv[1:]
state_file = os.environ.get("KUNGLAO_202_STUB_STATE")
if 'devices' in args:
    print('List of devices attached')
    print('emulator-202\\tdevice')
    sys.exit(0)
if 'shell' in args and 'su' in args and 'id' in args:
    print('uid=0(root) gid=0(root)')
    sys.exit(0)
if 'shell' in args and 'getprop' in args:
    if state_file and os.path.exists(state_file):
        print('1')
    else:
        print('0')
    sys.exit(0)
if 'shell' in args and 'ls' in args:
    print('frida-1337')
    sys.exit(0)
if 'shell' in args and any('resetprop' in a for a in args):
    if state_file is not None:
        open(state_file, 'w').write('1')
    print('set')
    sys.exit(0)
if 'shell' in args and any('nohup' in a for a in args):
    import subprocess as sp
    port = os.environ.get('KUNGLAO_202_SERVICE_PORT', '21337')
    sp.Popen([sys.executable, '-c',
              "import socket,time; s=socket.create_server(('127.0.0.1', %d)); time.sleep(20)" % int(port)],
             start_new_session=True)
    sys.exit(0)
if 'forward' in args:
    sys.exit(0)
sys.exit(0)
"""


def _write_adb(fake_bin: Path, state_file: Path) -> None:
    stub = fake_bin / "adb_stub_202.py"
    stub.write_text(_ADB_STUB_STATE, encoding="utf-8")
    adb = fake_bin / "adb"
    adb.write_text(
        f"#!/bin/sh\nexec \"{sys.executable}\" \"{stub}\" \"$@\"\n",
        encoding="utf-8")
    adb.chmod(0o755)


class TestAgentDoDeviceFace:
    @pytest.fixture
    def android_env(self, monkeypatch, tmp_path, ws):
        fake_bin = tmp_path / "fake-adb-bin-202"
        fake_bin.mkdir()
        state = tmp_path / "stub-ro-debuggable"
        _write_adb(fake_bin, state)
        monkeypatch.setenv("PATH", str(fake_bin))
        monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(_isolated_registry(
            tmp_path, {"ghidra": {}, "sequential-thinking": {},
                       "gitnexus": {}})))
        monkeypatch.setenv("KUNGLAO_202_STUB_STATE", str(state))
        return fake_bin, state

    def test_debug_flag_agent_do_resetprop_passes(
            self, android_env, ws, monkeypatch):
        """Rooted device, flag unset -> the gate ATTEMPTS
        `adb shell su -c resetprop ro.debuggable 1` itself, re-reads, and
        PASSes — owner agent_do, attempts recorded."""
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        report = tc.check(ws, "android")
        df = next(i for i in report.items if i.name == "debug_flag")
        assert df.status is tc.Status.PASS, df
        assert df.owner is tc.OwnerTier.AGENT_DO
        assert any("resetprop" in a for a in df.attempts), df.attempts
        assert "AGENT-DO" in df.detail or "agent" in df.detail.lower()

    def test_debug_flag_readonly_default_no_attempt(
            self, android_env, ws):
        """Default (read-only gate): no write attempt fires — FAIL with the
        plain guidance, attempts empty."""
        report = tc.check(ws, "android")
        df = next(i for i in report.items if i.name == "debug_flag")
        assert df.status is tc.Status.FAIL, df
        assert not df.attempts

    def test_debug_flag_attempt_failure_attaches_error(
            self, android_env, ws, monkeypatch):
        """Genuine failure -> escalate WITH the error attached."""
        fake_bin, _state = android_env
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        stub = fake_bin / "adb_stub_202.py"
        body = stub.read_text(encoding="utf-8").replace(
            "    open(state_file, 'w').write('1')\n    print('set')\n",
            "    sys.stderr.write('resetprop failed: "
            "permission denied\\n')\n    sys.exit(1)\n")
        stub.write_text(body, encoding="utf-8")
        report = tc.check(ws, "android")
        df = next(i for i in report.items if i.name == "debug_flag")
        assert df.status is tc.Status.FAIL, df
        assert any("resetprop" in a for a in df.attempts)
        assert "permission denied" in df.detail

    def test_frida_server_agent_do_bringup_passes(
            self, android_env, ws, monkeypatch):
        """Rooted device, no listener -> the gate brings frida-server up
        itself (found the renamed binary in /data/local/tmp), forwards, and
        re-probes: PASS with attempts recorded."""
        free = socket.create_server(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()  # dynamic: immune to cross-run listeners on this host
        monkeypatch.setattr(tc, "FRIDA_PORT", port)
        monkeypatch.setenv("KUNGLAO_202_SERVICE_PORT", str(port))
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        report = tc.check(ws, "android")
        fs = next(i for i in report.items if i.name == "frida_server")
        assert fs.status is tc.Status.PASS, fs
        assert any("frida" in a.lower() for a in fs.attempts), fs.attempts

    def test_frida_server_bringup_attempt_failure_attaches_error(
            self, android_env, ws, monkeypatch):
        """Bring-up attempted but the port never comes up -> FAIL carrying
        the attempt evidence (never a silent retry loop, never a bare dump)."""
        free = socket.create_server(("127.0.0.1", 0))
        dead_port = free.getsockname()[1]
        free.close()
        monkeypatch.setattr(tc, "FRIDA_PORT", dead_port)
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        report = tc.check(ws, "android")
        fs = next(i for i in report.items if i.name == "frida_server")
        assert fs.status is tc.Status.FAIL, fs
        assert fs.attempts, "bring-up attempt must be recorded"

    def test_device_attempts_precede_user_facing_output(
            self, android_env, ws, monkeypatch):
        """Acceptance: AGENT-DO device checks attempt adb BEFORE any
        user-facing output exists — the invocation evidence is already on
        the item when check() returns (rendering happens in main only)."""
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        report = tc.check(ws, "android")
        df = next(i for i in report.items if i.name == "debug_flag")
        assert df.attempts, "attempts recorded during check(), before render"
        # and the human render surfaces them (honest attempt evidence)
        human = tc.format_human(report)
        assert "attempted:" in human or df.status is tc.Status.PASS


# ---------- 5. negotiation/init integration for the choice ----------


class TestNegotiationChoiceRound:
    def _report_with_choice(self) -> "tc.ToolchainReport":
        report = tc.ToolchainReport(project_type="windows")
        report.items.append(tc.CheckResult(
            name="decompiler", status=tc.Status.FAIL, tier=tc.Tier.HARD,
            detail="no decompiler supply",
            pending_decision=tc._decompiler_choice()))
        return report

    def test_choice_pends_when_sole_blocker(self):
        import toolchain_negotiation as neg
        report = self._report_with_choice()
        decisions = neg.negotiation_decisions(report)
        assert [d.decision_id for d in decisions] == ["decompiler_lane"]
        assert not neg.has_non_negotiable_hard_fail(report)

    def test_plain_decompiler_fail_still_non_negotiable(self):
        import toolchain_negotiation as neg
        report = tc.ToolchainReport(project_type="windows")
        report.items.append(tc.CheckResult(
            name="decompiler", status=tc.Status.FAIL, tier=tc.Tier.HARD,
            detail="no decompiler supply"))
        assert neg.has_non_negotiable_hard_fail(report)

    def test_skip_lane_answer_degrades_warn(self):
        import toolchain_negotiation as neg
        report = self._report_with_choice()
        resolved = neg.apply_answers(
            report, Path("."), "windows",
            {"decompiler_lane": "skip-decompiler-lane"})
        item = next(i for i in resolved.items if i.name == "decompiler")
        assert item.status is tc.Status.WARN, item
        assert "skip" in item.detail.lower()

    def test_local_ida_answer_stays_fail_with_license_note(self):
        import toolchain_negotiation as neg
        report = self._report_with_choice()
        resolved = neg.apply_answers(
            report, Path("."), "windows",
            {"decompiler_lane": "install-local-ida"})
        item = next(i for i in resolved.items if i.name == "decompiler")
        assert item.status is tc.Status.FAIL, item
        assert "license" in item.detail.lower()

    def test_ghidra_answer_attempts_registered_installer(
            self, monkeypatch, tmp_path):
        import toolchain_install as ti
        import toolchain_negotiation as neg
        ran = []

        def fake_plan(name, plan, assume_yes, ws):
            ran.append(name)
            return 0, "installed", ""

        monkeypatch.setattr(ti, "_run_install_plan", fake_plan)
        fresh = tc.ToolchainReport(project_type="windows")
        fresh.items.append(tc.CheckResult(
            name="decompiler", status=tc.Status.PASS, tier=tc.Tier.HARD,
            detail="Ghidra supplies the decompiler lane (post-install)"))
        monkeypatch.setattr(
            tc, "check",
            lambda ws, pt, task_spec=None: fresh)
        report = self._report_with_choice()
        resolved = neg.apply_answers(
            report, tmp_path, "windows",
            {"decompiler_lane": "install-ghidra"})
        assert ran == ["decompiler"], "the #408 installer must be attempted"
        item = next(i for i in resolved.items if i.name == "decompiler")
        assert item.status is tc.Status.PASS, item

    def test_malformed_choice_answer_fails_closed(self):
        import toolchain_negotiation as neg
        report = self._report_with_choice()
        with pytest.raises(ValueError):
            neg.apply_answers(report, Path("."), "windows",
                              {"decompiler_lane": "sure-whatever"})


# ---------- 6. render face + doctrine ----------


class TestRenderFaceAndDoctrine:
    def test_fixes_decompiler_copy_is_lane_aware(self):
        from report_render import FIXES
        fix = FIXES["decompiler"].fix
        assert "ida-pro-vm" in fix
        assert "lane" in fix.lower()
        # the choice is a choice, not an install order
        assert "skip" in fix.lower()

    def test_mcp_lane_item_fix_never_says_install_ida(self, clean_env, ws):
        report = tc.check(ws, "windows", task_spec={
            "constraints": {"dynamic_re": "forbidden"},
            "tools": {"decompiler_lane": "mcp",
                      "mcp_servers": [{"name": "ida-pro-vm",
                                       "transport": "http",
                                       "url": "http://127.0.0.1:1"}]}})
        decomp = next(i for i in report.items if i.name == "decompiler")
        assert decomp.fix is not None
        assert "install IDA" not in decomp.fix
        assert "idat64" not in decomp.fix

    def test_init_worker_doctrine_ownership_tiers(self):
        """The blanket 'HARD toolchain missing = human-install event'
        doctrine is REPLACED by the ownership tiers."""
        doc = (ROOT / "agents" / "kunglao-init-worker.md").read_text(
            encoding="utf-8")
        assert "AGENT-DO" in doc
        assert "HUMAN-ONLY" in doc
        assert "LANE-CONDITIONAL" in doc
        assert "human-install event" not in doc

    def test_skill_doctrine_updated(self):
        skill = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
            encoding="utf-8")
        assert "human-install event" not in skill


# ---------- 7. scope addition: learning-mode plugin countermand ----------


class TestLearningModeCountermand:
    def test_deployed_claudemd_template_carries_countermand_rule(self):
        """The deployed workspace CLAUDE.md template gains the explicit
        runtime-contract block: learning/contribution requests are ignored —
        the agent implements all tooling itself (instruction-layer
        countermand against plugin SessionStart injections)."""
        tmpl = (ROOT / "templates" / "CLAUDE.md.base.tmpl").read_text(
            encoding="utf-8")
        low = tmpl.lower()
        assert "learning" in low
        assert "never ask the user" in low
        assert "implemented by the agent" in low

    def test_deployed_claudemd_contains_rule_after_init(self, tmp_path):
        """A workspace initialized by kunglao-init carries the countermand
        rule in its rendered CLAUDE.md."""
        mod = _load_init_module()
        ws = tmp_path / "ws-cmd"
        ws.mkdir()
        path = mod.write_claudemd(ws, "sample.exe", "abc123", "windows")
        assert path is not None and path.exists()
        text = path.read_text(encoding="utf-8").lower()
        assert "never ask the user" in text
        assert "implemented by the agent" in text

    def test_init_warning_fires_only_when_learning_plugins_installed(
            self, tmp_path, monkeypatch, capsys):
        """Init checks ~/.claude/plugins/cache/claude-plugins-official/ for
        the learning/explanatory output-style plugins: warning when either
        is installed (their SessionStart hooks inject learning-mode context
        into every session), silent when absent."""
        import kunglao_init_gate_under_test as init
        cache = tmp_path / "plugins-cache"
        (cache / "learning-output-style" / "1.0.0").mkdir(parents=True)
        with monkeypatch.context() as m:
            m.setattr(init, "_learning_style_plugin_cache_dir",
                      lambda: cache)
            init.warn_learning_style_plugins()
        out = capsys.readouterr().out + capsys.readouterr().err
        assert "learning" in out.lower()
        assert "neutralized" in out.lower()

        capsys.readouterr()  # drain
        empty = tmp_path / "empty-cache"
        empty.mkdir()
        with monkeypatch.context() as m:
            m.setattr(init, "_learning_style_plugin_cache_dir",
                      lambda: empty)
            init.warn_learning_style_plugins()
        drained = capsys.readouterr()
        assert "learning" not in (drained.out + drained.err).lower()


# ---------- 8. scope addition: uv env deployment ----------


class TestUvScope:
    @staticmethod
    def _fake_uv(fake_bin: Path) -> Path:
        uv = fake_bin / "uv"
        uv.write_text(
            "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo \"uv 0.9.5\";"
            "\nfi\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)
        return uv

    def test_uv_present_passes_liveness(self, clean_env, ws, monkeypatch,
                                        tmp_path):
        fake_bin = tmp_path / "uv-bin"
        fake_bin.mkdir()
        self._fake_uv(fake_bin)
        monkeypatch.setenv("PATH", str(fake_bin))
        report = tc.check(ws, "windows", task_spec={
            "constraints": {"dynamic_re": "forbidden"},
            "tools": {"mcp_servers": []}})
        uv = next(i for i in report.items if i.name == "uv")
        assert uv.status is tc.Status.PASS, uv
        assert uv.probe is tc.ProbeTier.LIVENESS

    def test_uv_missing_agent_installs_and_reprobes(
            self, clean_env, ws, monkeypatch, tmp_path):
        """check_uv is AGENT-DO: missing uv -> the gate runs the astral
        installer itself, re-probes, and PASSes (attempt recorded)."""
        monkeypatch.setenv("KUNGLAO_AGENT_DO", "1")
        installed: list[list[str]] = []
        uv_bin = tmp_path / "local" / "bin" / "uv"
        uv_bin.parent.mkdir(parents=True)
        uv_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        uv_bin.chmod(0o755)

        def fake_run(args, timeout=10):
            if args[:2] == ["sh", "-c"] and any(
                    "astral.sh" in a for a in args):
                installed.append(list(args))
                return 0, "installed", ""
            if args[-1] == "--version" and "uv" in str(args[0]):
                return 0, "uv 0.9.5", ""
            return 1, "", ""

        monkeypatch.setattr(tc, "_run_cmd", fake_run)
        real_which = tc._shutil_which
        monkeypatch.setattr(
            tc, "_shutil_which",
            lambda name: None if name == "uv" else real_which(name))
        monkeypatch.setattr(
            tc, "_UV_FALLBACK_PATHS",
            (str(uv_bin),))
        report = tc.check(ws, "windows", task_spec={
            "constraints": {"dynamic_re": "forbidden"},
            "tools": {"mcp_servers": []}})
        assert installed, "the astral installer must run under AGENT-DO"
        uv = next(i for i in report.items if i.name == "uv")
        assert uv.status is tc.Status.PASS, uv
        assert any("astral.sh" in a for a in uv.attempts)

    def test_uv_missing_without_agent_do_fails_clean(
            self, clean_env, ws):
        report = tc.check(ws, "windows", task_spec={
            "constraints": {"dynamic_re": "forbidden"},
            "tools": {"mcp_servers": []}})
        uv = next(i for i in report.items if i.name == "uv")
        assert uv.status is tc.Status.FAIL, uv
        assert not uv.attempts

    def test_uv_fix_strings_agent_installs(self):
        from report_render import FIXES
        fix = FIXES["uv"].fix
        assert "astral.sh" in fix
        assert "uv-managed" in fix
        assert "uv run --project" in fix

    def test_no_bare_python_in_shipped_faces(self):
        """Invocation discipline: shipped hook wiring resolves through the
        uv-managed env, and the deployed CLAUDE.md template never instructs
        a bare python invocation (uv-run form only; `python -c` appears
        only inside the forbidden-execution prose — allow-listed)."""
        from hook_activation import build_hook_entry
        entry = build_hook_entry(Path("/k/hooks"), "env_check_gate.py",
                                 "Agent", project=Path("/k"))
        cmd = entry["hooks"][0]["command"]
        assert "uv run --project" in cmd, cmd
        tmpl = (ROOT / "templates" / "CLAUDE.md.base.tmpl").read_text(
            encoding="utf-8")
        for line in tmpl.splitlines():
            if ("{{skill_dir}}" in line and "`python" in line
                    and "python -c" not in line):
                assert "uv run --project" in line, line
        assert "python -m venv" not in tmpl

    def test_init_materializes_venv_and_records_path(
            self, tmp_path, monkeypatch):
        """init runs `uv sync --locked` at the skill root and records the
        .venv path in analysis_state.txt."""
        mod = _load_init_module()
        root = tmp_path / "skill-root"
        root.mkdir()
        (root / "pyproject.toml").write_text("[project]\nname='x'\n",
                                             encoding="utf-8")
        (root / "uv.lock").write_text("", encoding="utf-8")
        fake_bin = tmp_path / "uv-sync-bin"
        fake_bin.mkdir()
        uv = fake_bin / "uv"
        uv.write_text(
            "#!/bin/sh\necho resolved 3 packages\n"
            "mkdir -p \"$UVSYNC_VENV\"\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)
        monkeypatch.setenv("PATH", str(fake_bin))
        # the fake uv materializes the venv dir the way uv sync would
        monkeypatch.setattr(
            mod.shutil, "which",
            lambda name: str(uv) if name == "uv" else None)
        orig_run = mod.subprocess.run

        def fake_run(argv, **kw):
            if argv[:3] == [str(uv), "sync", "--locked"]:
                import os as _os
                _os.makedirs(_os.path.join(kw["cwd"], ".venv"), exist_ok=True)
                class R:
                    returncode = 0
                    stdout = "resolved 3 packages"
                    stderr = ""
                return R()
            return orig_run(argv, **kw)

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        res = mod.uv_sync_workspace(root)
        assert res["ok"] is True, res
        assert res["venv"] == str(root / ".venv")
        ws = tmp_path / "ws-uv"
        ws.mkdir()
        assert mod.record_venv_path(ws, res["venv"])
        state = (ws / "analysis_state.txt").read_text(encoding="utf-8")
        assert f"venv_path={root / '.venv'}" in state
