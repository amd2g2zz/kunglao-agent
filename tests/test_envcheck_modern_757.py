# -*- coding: utf-8 -*-
"""Tests for issue #757 — env_check 现代化 (F1-F6).

Sections map 1:1 to the task split (each task = one commit):
  T5  channel enum gains `mcp` (toolchain + init_channel_default)
  T4  runtime channel derivation in env_check (read-only; no disk writes)
  T1  type/channel-aware checklist (vm_reachability per channel, typed ghidra)
  T2  mcp_registered check (per-type口径)
  T3  blocking/degraded grading + gate third check paths

Contract basis:
  - #698 design D3/D4 (needs x channel matrix; probe semantics per backend)
  - #757 user rulings 2026-08-27: "web 不需要任何控制通道，可能有新类型就是
    MCP，web 只要求浏览器可以通" and "KUNGLAO_VM_HOST 只适用于 windows"
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import toolchain as tc  # pytest.ini pythonpath = . hooks scripts tools
import init_channel_default as icd
import platform_paths  # noqa: F401 — mirrors test_env_check imports


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

def _channel_env(monkeypatch: pytest.MonkeyPatch, **kw: str) -> None:
    """Pin the whole #698 env surface (absent keys deleted — test order proof)."""
    for var in ("KUNGLAO_CHANNEL", "KUNGLAO_VM_HOST", "KUNGLAO_DOCKER_CONTAINER"):
        monkeypatch.delenv(var, raising=False)
    for var, val in kw.items():
        monkeypatch.setenv(var, val)


def _marker_type(ws: Path, ptype: str) -> None:
    """Write the #625 primary init marker with project_type=<ptype>."""
    from init_state import write_init_marker
    write_init_marker(ws, state_hash="abc", project_type=ptype, seed_count=0)


def _mk_ws(tmp_path: Path, ptype: str | None = "windows") -> Path:
    """Minimal initialized workspace: claim-register + runs/ + analysis_state +
    primary marker (#625). Template version stamp via template_version so
    env_check's template_version row does not drift-warn."""
    import template_version
    stamp = template_version.stamp_line(template_version.read_skill_version())
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    reg_line = f"{stamp}\n# [initialized] state_hash=abc seeds=0\nclaims:\n" if ptype else ""
    if reg_line:
        (ws / "claim-register.yaml").write_text(reg_line, encoding="utf-8")
    lines = ["agent_teams_flag=0"]
    if ptype:
        lines.append(f"project_type={ptype}")
    (ws / "analysis_state.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(stamp + "\n# _INDEX\n", encoding="utf-8")
    (ws / "CLAUDE.md").write_text(stamp + "\n# workspace\n", encoding="utf-8")
    if ptype:
        _marker_type(ws, ptype)
    return ws


# ===========================================================================
# T5 — channel enum gains `mcp`
# ===========================================================================

class TestT5ChannelEnumMcp:
    def test_backend_mcp_is_legal_no_note(self, monkeypatch):
        _channel_env(monkeypatch, KUNGLAO_CHANNEL="mcp")
        assert tc._channel_backend() == ("mcp", None)

    def test_unset_still_vmr_byte_identical(self, monkeypatch):
        _channel_env(monkeypatch)
        backend, note = tc._channel_backend()
        assert (backend, note) == ("vmr", None), \
            "#698 byte_identical pin: unset must stay vmr untouched"

    def test_unknown_falls_back_with_named_value(self, monkeypatch):
        _channel_env(monkeypatch, KUNGLAO_CHANNEL="carrier-pigeon")
        backend, note = tc._channel_backend()
        assert backend == "vmr"
        assert "carrier-pigeon" in (note or "")

    def test_init_channel_default_explicit_mcp_first_class(self, monkeypatch):
        _channel_env(monkeypatch, KUNGLAO_CHANNEL="mcp")
        dec = icd.resolve_init_channel(Path("/tmp"))
        assert dec.selected == "mcp"
        assert dec.defaulted_to_local is False
        assert dec.warn_reason == "", \
            "explicit mcp is a first-class choice like explicit local — no warn"

    def test_dynamic_task_via_mcp_hard_rejects_zero_probes(self, monkeypatch):
        """mcp carries no desktop exec control plane (#698 D9 fail-closed):
        a needs_vm task through the mcp backend must HARD-fail both items with
        switch guidance and spawn ZERO subprocess/TCP probes."""
        _channel_env(monkeypatch, KUNGLAO_CHANNEL="mcp")

        def _no_probe(*a, **k):  # any probe attempt fails the test
            raise AssertionError("mcp dynamic reject must not probe")

        monkeypatch.setattr(tc, "_run_cmd", _no_probe)
        monkeypatch.setattr(tc, "_tcp_connect", _no_probe)
        report = tc.ToolchainReport(project_type="windows")
        reqs = tc.Requirements(needs_vm=True,
                               basis="task_spec requests dynamic RE")
        tc._check_dynamic_channel(report, reqs)
        names = {i.name: i for i in report.items}
        assert {"vm_reachable", "remote_debugger"} <= set(names)
        for item in names.values():
            assert item.status == tc.Status.FAIL and item.tier == tc.Tier.HARD
            assert "ssh" in item.detail or "vmr" in item.detail, item.detail

    def test_static_task_via_mcp_zero_probes_warn(self, monkeypatch):
        """static-only task + mcp → the generic zero-probe WARN row (D3 row 1)."""
        _channel_env(monkeypatch, KUNGLAO_CHANNEL="mcp")

        def _no_probe(*a, **k):
            raise AssertionError("static-only task must not probe")

        monkeypatch.setattr(tc, "_run_cmd", _no_probe)
        monkeypatch.setattr(tc, "_tcp_connect", _no_probe)
        report = tc.ToolchainReport(project_type="windows")
        reqs = tc.Requirements(needs_vm=False,
                               basis="task_spec constraints.dynamic_re=forbidden (static-only)")
        tc._check_dynamic_channel(report, reqs)
        vm = next(i for i in report.items if i.name == "vm_reachable")
        assert vm.status == tc.Status.WARN and vm.tier == tc.Tier.WARN


# ===========================================================================
# T4 — runtime channel derivation in env_check (READ-ONLY; no disk writes)
# ===========================================================================

class TestT4ChannelDerivation:
    def test_explicit_env_wins_over_records(self, monkeypatch, tmp_path):
        """Live environment beats persisted records (#698 变量跟通道走)."""
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "local"}}), encoding="utf-8")
        monkeypatch.setenv("KUNGLAO_CHANNEL", "ssh")
        import env_check
        ctx = env_check._workspace_context(ws)
        assert ctx["channel"] == "ssh"
        assert ctx["channel_source"] == "env"

    def test_dotenv_fills_when_env_unset(self, monkeypatch, tmp_path):
        ws = _mk_ws(tmp_path, "windows")
        (ws / ".env").write_text("KUNGLAO_CHANNEL=docker\n", encoding="utf-8")
        monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
        import env_check
        ctx = env_check._workspace_context(ws)
        assert ctx["channel"] == "docker"
        assert ctx["channel_source"] == ".env"

    def test_init_report_block_used_when_no_explicit(self, monkeypatch, tmp_path):
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "adb"}}), encoding="utf-8")
        monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
        import env_check
        ctx = env_check._workspace_context(ws)
        assert ctx["channel"] == "adb"
        assert ctx["channel_source"] == ".init-report.json"

    def test_analysis_state_line_used_when_no_report(self, monkeypatch, tmp_path):
        ws = _mk_ws(tmp_path, "windows")
        state = ws / "analysis_state.txt"
        state.write_text(state.read_text(encoding="utf-8")
                         + "KUNGLAO_CHANNEL=vmr\n", encoding="utf-8")
        monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
        import env_check
        ctx = env_check._workspace_context(ws)
        assert ctx["channel"] == "vmr"
        assert ctx["channel_source"] == "analysis_state.txt"

    def test_no_record_derives_readonly(self, monkeypatch, tmp_path):
        """Nothing recorded -> runtime resolution; result must NOT touch disk
        (persisting is #755's upgrade item) and the report marks it derived."""
        import env_check
        ws = _mk_ws(tmp_path, "windows")

        calls = []

        def _fake_resolver(_ws):
            calls.append(_ws)
            return icd.ChannelDecision(
                selected="local", defaulted_to_local=True,
                probes={"vmr": "unset"}, warn_reason="all remote channels down")

        monkeypatch.setattr(env_check, "resolve_runtime_channel", _fake_resolver)
        before = sorted(str(p.relative_to(ws)) for p in ws.rglob("*"))
        ctx = env_check._workspace_context(ws)
        after = sorted(str(p.relative_to(ws)) for p in ws.rglob("*"))
        assert before == after, "derivation must never write disk (#757/#755 split)"
        assert calls == [ws], "resolver must receive the workspace"
        assert ctx["channel"] == "local"
        assert "derived" in ctx["channel_source"]
        assert "upgrade" in ctx["channel_source"]

    def test_unknown_record_value_falls_back_vmr_with_note(self, monkeypatch, tmp_path):
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "carrier-pigeon"}}),
            encoding="utf-8")
        monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
        import env_check
        ctx = env_check._workspace_context(ws)
        assert ctx["channel"] == "vmr"
        assert "carrier-pigeon" in ctx["channel_note"]

    def test_web_type_forces_mcp_face(self, monkeypatch, tmp_path):
        """用户裁决 2026-08-27: web 不需要任何控制通道 — recorded command
        channels are noise for web, whichever carrier they rode in on."""
        monkeypatch.setenv("KUNGLAO_CHANNEL", "ssh")  # even a LIVE env yields
        ws = _mk_ws(tmp_path, "web")
        state = ws / "analysis_state.txt"
        state.write_text("agent_teams_flag=0\nproject_type=web\n"
                         "KUNGLAO_CHANNEL=docker\n", encoding="utf-8")
        import env_check
        ctx = env_check._workspace_context(ws)
        assert ctx["channel"] == "mcp"
        assert ctx["project_type"] == "web"
        assert "ssh" in ctx["channel_note"], \
            "the ignored live record should be named in the note"

    def test_web_type_ignores_state_file_docker_default(self, monkeypatch, tmp_path):
        """#728 wrote KUNGLAO_CHANNEL=docker into web analysis_state.txt —
        per the ruling that record is noise for the web face too."""
        ws = _mk_ws(tmp_path, "web")
        state = ws / "analysis_state.txt"
        state.write_text("agent_teams_flag=0\nproject_type=web\n"
                         "KUNGLAO_CHANNEL=docker\n", encoding="utf-8")
        monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
        import env_check
        ctx = env_check._workspace_context(ws)
        assert ctx["channel"] == "mcp"
        assert "docker" in ctx["channel_note"], \
            "the ignored #728 docker default should be named in the note"


# ===========================================================================
# T1 — type/channel-aware checklist (vm_reachability per channel, typed ghidra)
# ===========================================================================

class TestT1TypeChannelChecks:
    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch):
        """Shell-exported kunglao vars must not leak into checklist shaping."""
        for var in ("KUNGLAO_CHANNEL", "KUNGLAO_VM_HOST",
                    "KUNGLAO_DOCKER_CONTAINER", "KUNGLAO_VM_SHELL_PORT",
                    "KUNGLAO_FRIDA_PORT", "GHIDRA_HOME"):
            monkeypatch.delenv(var, raising=False)
        yield

    def test_android_no_vm_host_never_emits_vm_row(self, monkeypatch, tmp_path):
        """验收 1: android workspace + KUNGLAO_VM_HOST 未设 → vm_reachability
        不出现（android 动态面是 ADB/设备，不是 VM 通道 — #455 NEVER_CHECKS）。"""
        import env_check
        ws = _mk_ws(tmp_path, "android")
        monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
        monkeypatch.setattr(env_check, "check_venv_sample",
                            lambda w, sha: ("PASS", "stubbed venv"))
        env_check.run(ws)
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        assert "vm_reachability" not in snap["checks"]

    def test_web_emits_no_vm_or_ghidra_row(self, monkeypatch, tmp_path):
        """验收 2: web workspace — 无 vm/ghidra 探测行
        (decompiler trials meaningless for web — #728 design D5 原文)。"""
        import env_check

        def _no_vm_probe(*a, **k):
            raise AssertionError("web must not probe any VM/socket channel")

        monkeypatch.setattr(env_check.socket, "create_connection", _no_vm_probe)
        monkeypatch.setattr(env_check, "check_venv_sample",
                            lambda w, sha: ("PASS", "stubbed venv"))
        ws = _mk_ws(tmp_path, "web")
        rc = env_check.run(ws)
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        assert "vm_reachability" not in snap["checks"]
        assert "ghidra" not in snap["checks"]

    def test_desktop_docker_channel_probes_docker_only(self, monkeypatch, tmp_path):
        """F6 收窄: channel=docker 的 desktop workspace 完全不读
        KUNGLAO_VM_HOST — 探测 argv 是 `docker version`。"""
        import env_check
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "docker"}}), encoding="utf-8")
        seen_cmds: list[list[str]] = []

        def _fake_run(args, timeout=10):
            seen_cmds.append(list(args))
            return 0, "Server Version: 27.0.0", ""

        monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
        monkeypatch.setattr("toolchain._run_cmd", _fake_run)
        # toolchain's own tcp pre-checks are NOT on the docker path; ensure a
        # stray socket call would be visible
        monkeypatch.setattr(env_check.socket, "create_connection",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
        env_check.run(ws)
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        vm = snap["checks"]["vm_reachability"]
        assert vm["status"] == "PASS"
        assert "docker" in vm["detail"].lower()
        assert all(c[0] == "docker" for c in seen_cmds), seen_cmds

    def test_desktop_ssh_channel_delegates_to_toolchain(self, monkeypatch, tmp_path):
        """channel=ssh → toolchain._vm_probe_ssh semantics (BatchMode true),
        KUNGLAO_VM_HOST is the remote HOST name (D4), never 'VM lease'."""
        import env_check
        ws = _mk_ws(tmp_path, "linux")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "ssh"}}), encoding="utf-8")

        def _fake_probe(host):
            return True, f"VM {host} via ssh backend: shell exec ok", "", tc.ProbeTier.CAPABILITY

        monkeypatch.setattr("toolchain._vm_probe_ssh", _fake_probe)
        # ssh's remote HOST NAME (D4) — set both the process env and the
        # module global env_check resolves per-run
        monkeypatch.setenv("KUNGLAO_VM_HOST", "10.0.0.9")
        monkeypatch.setattr(env_check, "VM_HOST", "10.0.0.9")
        env_check.run(ws)
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        vm = snap["checks"]["vm_reachability"]
        assert vm["status"] == "PASS"
        assert "ssh backend" in vm["detail"]

    def test_local_channel_says_static_only(self, monkeypatch, tmp_path):
        """channel=local → no probes, detail carries the static-only wording."""
        import env_check
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "local"}}), encoding="utf-8")

        def _no_probe(*a, **k):
            raise AssertionError("local channel must not probe")

        monkeypatch.setattr("toolchain._tcp_connect", _no_probe)
        monkeypatch.setattr(env_check.socket, "create_connection", _no_probe)
        env_check.run(ws)
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        vm = snap["checks"]["vm_reachability"]
        assert vm["status"] == "FAIL"
        assert "static-only" in vm["detail"]

    def test_vmr_channel_keeps_socket_semantics(self, monkeypatch, tmp_path):
        """channel=vmr → 现 socket 双端口语义原样（byte-parity with legacy）。"""
        import env_check
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "vmr"}}), encoding="utf-8")
        monkeypatch.setattr(env_check, "VM_HOST", "127.0.0.1")
        monkeypatch.setattr(env_check.socket, "create_connection",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
        env_check.run(ws)
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        vm = snap["checks"]["vm_reachability"]
        assert vm["status"] == "FAIL"
        assert "KUNGLAO_VM_HOST" not in vm["detail"], \
            "host WAS set — unset guidance must not appear"
        assert "127.0.0.1" in vm["detail"]

    def test_android_ghidra_row_typed_jadx_baksmali_native_so(self, monkeypatch, tmp_path):
        """android ghidra 行类型化: jadx/baksmali 主判定；native .so 才要求
        decompiler（复用 #756 central-directory 版 _probe_native_so）。"""
        import zipfile
        import env_check

        def _install_faqs(bin_dir: Path, names: tuple[str, ...]) -> str:
            bin_dir.mkdir(parents=True, exist_ok=True)
            for n in names:
                p = bin_dir / n
                p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                p.chmod(0o755)
            return str(bin_dir)

        fake_bin = tmp_path / "bin-android-a"
        monkeypatch.setenv("PATH", _install_faqs(fake_bin, ("jadx", "baksmali")))

        ws = _mk_ws(tmp_path, "android")
        # pure-DEX-ish sample (zip WITHOUT lib/*.so) + ghidra absent everywhere
        bins = ws / "bins"
        bins.mkdir()
        with zipfile.ZipFile(bins / "sample.apk", "w") as zf:
            zf.writestr("classes.dex", b"dex\n" + b"\x00" * 32)
            zf.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00")
        monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
        row = env_check.check_ghidra_typed(ws, "android")
        status, detail = row
        assert status == "PASS", f"pure-DEX + jadx/baksmali present must PASS: {detail}"
        assert "jadx" in detail and "baksmali" in detail

        # native .so inside the APK (central-directory discovery) + still no
        # decompiler anywhere -> FAIL
        with zipfile.ZipFile(bins / "sample.apk", "w") as zf:
            zf.writestr(zipfile.ZipInfo("classes.dex"), bytes(256) * 64)
            zf.writestr("lib/arm64-v8a/libnative.so", b"\x7fELF" + b"\x00" * 16)
        status, detail = env_check.check_ghidra_typed(ws, "android")
        assert status == "FAIL"
        assert ".so" in detail or "decompiler" in detail.lower()

    def test_windows_ghidra_row_keeps_legacy_semantics(self, monkeypatch, tmp_path):
        """desktop 行保持现语义：GHIDRA_HOME 缺失 → FAIL 文案不变样。"""
        import env_check
        ws = _mk_ws(tmp_path, "windows")
        monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
        status, detail = env_check.check_ghidra_typed(ws, "windows")
        assert status == "FAIL"
        assert "GHIDRA_HOME unset" in detail


# ===========================================================================
# T2 — mcp_registered check (per-type 口径)
# ===========================================================================

def _claude_json(monkeypatch, tmp_path: Path, servers: dict) -> Path:
    """Inject an isolated user-level ~/.claude.json (#316 surface 1)."""
    p = tmp_path / "claude.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(p))
    return p


class TestT2McpRegistered:
    def test_web_camoufox_registered_pass(self, monkeypatch, tmp_path):
        import env_check
        ws = _mk_ws(tmp_path, "web")
        _claude_json(monkeypatch, tmp_path,
                     {"camoufox-reverse": {"command": "python"}})
        status, detail = env_check.check_mcp_registered(ws, "web")
        assert status == "PASS"
        assert "camoufox-reverse" in detail

    def test_web_camoufox_missing_fail_names_register_command(
            self, monkeypatch, tmp_path):
        """web 缺 camoufox → FAIL（T3 将其降级为 degraded，不 blocking）。"""
        import env_check
        ws = _mk_ws(tmp_path, "web")
        _claude_json(monkeypatch, tmp_path, {})
        status, detail = env_check.check_mcp_registered(ws, "web")
        assert status == "FAIL"
        assert "camoufox-reverse" in detail
        assert "claude mcp add camoufox-reverse" in detail

    def test_android_no_hard_expectation_info_pass(self, monkeypatch, tmp_path):
        import env_check
        ws = _mk_ws(tmp_path, "android")
        _claude_json(monkeypatch, tmp_path, {})
        status, detail = env_check.check_mcp_registered(ws, "android")
        assert status == "PASS"
        assert "android" in detail.lower()

    def test_desktop_either_decompiler_mcp_warn_unverified(
            self, monkeypatch, tmp_path):
        """#474 同口径: 注册 ≠ capability — 上限就是 WARN unverified。"""
        import env_check
        for i, servers in enumerate((
                {"ghidra": {"command": "b"}},
                {"ida-pro-vm": {"url": "http://x"}},
                {"GHIDRA": {}},  # case-insensitive matching
        ), start=1):
            ws = _mk_ws(tmp_path / f"d{i}", "windows")
            _claude_json(monkeypatch, tmp_path / f"c{i}", servers)
            status, detail = env_check.check_mcp_registered(ws, "windows")
            assert status == "WARN", (servers, detail)
            assert "unverified" in detail.lower()

    def test_desktop_none_registered_fail_with_alternatives(
            self, monkeypatch, tmp_path):
        import env_check
        ws = _mk_ws(tmp_path, "linux")
        _claude_json(monkeypatch, tmp_path, {})
        status, detail = env_check.check_mcp_registered(ws, "linux")
        assert status == "FAIL"
        assert "Ghidra" in detail and "ida-pro-vm" in detail

    def test_workspace_dotjson_surface_counts(self, monkeypatch, tmp_path):
        """workspace <ws>/.mcp.json 是第三注册面（#316）。"""
        import env_check
        ws = _mk_ws(tmp_path, "web")
        _claude_json(monkeypatch, tmp_path, {})
        (ws / ".mcp.json").write_text(
            json.dumps({"mcpServers": {
                "Camoufox-Reverse": {"command": "python"}}}),
            encoding="utf-8")
        status, _detail = env_check.check_mcp_registered(ws, "web")
        assert status == "PASS"

    def test_row_present_for_every_type_in_snapshot(self, monkeypatch, tmp_path):
        """run() 快照对四种类型都带 mcp_registered 行；web 行由隔离的
        claude.json 驱动（无 hermetic 泄漏）。"""
        import env_check
        for i, ptype in enumerate(("web", "android", "windows", "linux")):
            base = tmp_path / f"snap-{i}"
            base.mkdir()
            ws = _mk_ws(base, ptype)
            _claude_json(monkeypatch, base / "cfg-empty",
                         {} if ptype == "web" else {"ghidra": {}})
            monkeypatch.setattr(env_check, "check_venv_sample",
                                lambda w, sha: ("PASS", "stubbed"))
            env_check.run(ws)
            snap = json.loads((ws / "runs" / ".env-check.json")
                              .read_text(encoding="utf-8"))
            assert "mcp_registered" in snap["checks"], ptype


# ===========================================================================
# T3 — blocking/degraded grading + gate third check paths
# ===========================================================================

@pytest.fixture(autouse=True)
def _isolated_claude_json_757(tmp_path_factory, monkeypatch):
    """Suite-wide: isolate ~/.claude.json so MCP registry reads never see the
    real machine config (empty file => desktop/web degraded branches)."""
    root = tmp_path_factory.mktemp("kg757-claude-json")
    p = root / ".claude.json"
    p.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(p))


def _stub_non_fail_checks(env_check, monkeypatch):
    """Force environmental NON-vm checks to PASS so grading assertions stay
    isolated (check_vm itself stays live where a scenario probes it)."""
    monkeypatch.setattr(env_check, "check_venv_sample",
                        lambda w, sha: (True, "stubbed venv"))


class TestT3Grading:
    def test_vm_unreachable_is_degraded_never_blocking(self, monkeypatch, tmp_path):
        """验收核心翻转: channel=vmr + socket 全拒 → vm_reachability 行仍 FAIL
        但 overall=PASS/exit 0，detail 前缀 T3-restricted，进 degraded 列表。"""
        import env_check
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "vmr"}}), encoding="utf-8")

        def _boom(*a, **k):
            raise OSError("refused")

        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
                           raising=False)
        monkeypatch.delenv("GHIDRA_HOME", raising=False)
        monkeypatch.setattr(env_check, "VM_HOST", "127.0.0.1")
        fake_headless = tmp_path / platform_paths.analyze_headless_name()
        fake_headless.write_text("", encoding="utf-8")
        monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", fake_headless)
        monkeypatch.setattr(env_check.socket, "create_connection", _boom)
        _stub_non_fail_checks(env_check, monkeypatch)

        rc = env_check.run(ws)
        assert rc == 0, "a degraded vm failure must not exit nonzero (#757)"
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        vm = snap["checks"]["vm_reachability"]
        assert vm["status"] == "FAIL"
        assert vm["detail"].startswith("T3-restricted:")
        assert vm["blocking"] is False
        assert snap["overall"] == "PASS"
        # mcp_registered ALSO degrades (isolated empty claude.json) — both ride
        assert {"vm_reachability", "mcp_registered"} == set(snap["degraded"])
        # #757 schema: context rides along
        assert snap["context"]["project_type"] == "windows"
        assert snap["context"]["channel"] == "vmr"

    def test_flag_truthy_remains_blocking(self, monkeypatch, tmp_path):
        import env_check
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "local"}}), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.delenv("GHIDRA_HOME", raising=False)
        monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
        _stub_non_fail_checks(env_check, monkeypatch)

        rc = env_check.run(ws)
        assert rc == 1
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        assert snap["overall"] == "FAIL"
        assert snap["checks"]["agent_teams_flag"]["blocking"] is True
        # the local-channel vm FAIL joins degraded in this same run (T2 vm row)
        assert snap["checks"]["vm_reachability"]["blocking"] is False

    def test_every_row_carries_blocking_bool(self, monkeypatch, tmp_path):
        import env_check
        ws = _mk_ws(tmp_path, "windows")
        (ws / "runs" / ".init-report.json").write_text(
            json.dumps({"channel": {"selected": "docker"}}), encoding="utf-8")
        monkeypatch.setattr("toolchain._run_cmd", lambda a, timeout=10: (0, "", ""))
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
                           raising=False)
        _stub_non_fail_checks(env_check, monkeypatch)
        env_check.run(ws)
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        assert snap["checks"], "sanity"
        assert all(isinstance(v.get("blocking"), bool)
                   for v in snap["checks"].values())

    def test_untyped_workspace_gets_conservative_face(self, monkeypatch, tmp_path):
        """project_type 缺失 → desktop 分支保守兜底（不因 type=None 抛错）；
        推导探针被注入替代，测试不触碰真实网络。"""
        import env_check
        ws = _mk_ws(tmp_path, None)
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
                           raising=False)
        _stub_non_fail_checks(env_check, monkeypatch)
        monkeypatch.setattr(env_check, "check_init_complete",
                            lambda w: (True, "stubbed complete"))
        monkeypatch.setattr(
            env_check, "resolve_runtime_channel",
            lambda _w: icd.ChannelDecision(selected="local",
                                           defaulted_to_local=True,
                                           probes={}, warn_reason="test"))
        rc = env_check.run(ws)
        assert rc in (0, 1)


# ---------- gate third check ----------

class TestT3GateThirdCheck:
    def _gate_ws(self, tmp_path: Path) -> Path:
        """Fully initialized kunglao ws shaped for env_check_gate._resolve_workspace."""
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "# [initialized] state_hash=abc seeds=0\nclaims:\n", encoding="utf-8")
        (ws / "analysis_state.txt").write_text(
            "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8")
        return ws

    def _payload(self, ws: Path) -> dict:
        return {"hookEventName": "PreToolUse", "tool_name": "Agent",
                "cwd": str(ws), "tool_input": {"prompt": "[T1] x"}}

    def _write_report(self, ws: Path, *, ago_seconds: int, checks: dict,
                      overall: str | None = None) -> None:
        from datetime import datetime, timedelta, timezone
        ts = (datetime.now(timezone.utc)
              - timedelta(seconds=ago_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
        doc = {"ts": ts, "workspace": str(ws), "checks": checks,
               "overall": overall if overall is not None else (
                   "FAIL" if any(c.get("status") == "FAIL" and c.get("blocking")
                                 for c in checks.values()) else "PASS")}
        (ws / "runs").mkdir(exist_ok=True)
        (ws / "runs" / ".env-check.json").write_text(
            json.dumps(doc), encoding="utf-8")

    @staticmethod
    def _fail(name: str, blocking: bool | None) -> dict:
        row = {"status": "FAIL", "detail": "x"}
        if blocking is not None:
            row["blocking"] = blocking
        return {name: row}

    def test_fresh_blocking_fail_rejects(self, tmp_path):
        from env_check_gate import evaluate, FLAG_NAME
        ws = self._gate_ws(tmp_path)
        self._write_report(ws, ago_seconds=30, checks={
            **self._fail("init_complete", True),
            "agent_teams_flag": {"status": "PASS", "detail": "ok"}})
        rc, stderr, ctx = evaluate(self._payload(ws), environ={FLAG_NAME: ""})
        assert rc == 2
        assert "init_complete" in stderr
        assert ctx and "env-check" in ctx

    def test_stale_report_passes(self, tmp_path):
        from env_check_gate import evaluate, FLAG_NAME
        ws = self._gate_ws(tmp_path)
        self._write_report(ws, ago_seconds=15 * 60, checks=self._fail(
            "init_complete", True))
        rc, stderr, ctx = evaluate(self._payload(ws), environ={FLAG_NAME: ""})
        assert rc == 0 and stderr == "" and ctx is None

    def test_absent_report_passes(self, tmp_path):
        from env_check_gate import evaluate, FLAG_NAME
        ws = self._gate_ws(tmp_path)
        rc, stderr, ctx = evaluate(self._payload(ws), environ={FLAG_NAME: ""})
        assert rc == 0 and stderr == "" and ctx is None

    def test_corrupt_report_passes(self, tmp_path):
        from env_check_gate import evaluate, FLAG_NAME
        ws = self._gate_ws(tmp_path)
        (ws / "runs").mkdir()
        (ws / "runs" / ".env-check.json").write_text("{oops", encoding="utf-8")
        rc, stderr, ctx = evaluate(self._payload(ws), environ={FLAG_NAME: ""})
        assert rc == 0

    def test_legacy_schema_without_blocking_flags_passes(self, tmp_path):
        """adjudication B3: pre-#757 reports carry NO blocking field — gating
        on them would resurrect the VM-unreachable dispatch deadlock."""
        from env_check_gate import evaluate, FLAG_NAME
        ws = self._gate_ws(tmp_path)
        self._write_report(ws, ago_seconds=10, checks={
            "vm_reachability": {"status": "FAIL", "detail": "unreachable"},
        })
        rc, stderr, ctx = evaluate(self._payload(ws), environ={FLAG_NAME: ""})
        assert rc == 0

    def test_degraded_only_report_passes(self, tmp_path):
        from env_check_gate import evaluate, FLAG_NAME
        ws = self._gate_ws(tmp_path)
        self._write_report(ws, ago_seconds=5, checks={
            "vm_reachability": {"status": "FAIL",
                                 "detail": "T3-restricted: x", "blocking": False},
        }, overall="PASS")
        rc, stderr, ctx = evaluate(self._payload(ws), environ={FLAG_NAME: ""})
        assert rc == 0
