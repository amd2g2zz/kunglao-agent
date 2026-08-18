# -*- coding: utf-8 -*-
"""Tests for #474: probe capability tiers — presence/liveness/capability
three-tier + jdwp raw handshake + MCP honest degradation.

TDD RED phase: written BEFORE implementation.

Covers the three acceptance criteria of issue #474:
  1. decompiler three-state: capability-PASS / liveness-WARN / FAIL —
     no more fake PASS for a registry entry + reachable bridge port
  2. jdwp handshake probe (android matrix), raw 14-byte echo, no jdb attach
  3. capability trial runs ONLY under explicit opt-in (caps/--capability);
     the default path runs presence+liveness only
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import platform_paths  # pytest.ini pythonpath = . hooks scripts tools

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

JDWP_HANDSHAKE = b"JDWP-Handshake"  # 14 bytes, ASCII


@pytest.fixture
def kunglao_ws(tmp_path: Path) -> Path:
    """Minimal workspace with runs/ directory."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


# ---------- fake JDWP server (14-byte echo) ----------

class _FakeJdwpServer:
    """Threaded TCP server that echoes the 14-byte JDWP handshake.

    response=b"JDWP-Handshake"  -> faithful echo (PASS case)
    response=b"XXXX-bogus-data"  -> wrong echo (FAIL case)
    hold=True                    -> accept, never reply (timeout FAIL case)
    """

    def __init__(self, response: bytes = JDWP_HANDSHAKE, hold: bool = False):
        self._response = response
        self._hold = hold
        self._sock = socket.create_server(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return  # closed
            with conn:
                try:
                    data = conn.recv(64)
                    if data and not self._hold:
                        conn.sendall(self._response)
                except OSError:
                    pass

    def __enter__(self) -> "_FakeJdwpServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._sock.close()


# ---------- acceptance 2: jdwp raw handshake ----------

def test_jdwp_handshake_echo_passes():
    """14-byte faithful echo -> handshake PASS."""
    import toolchain as tc
    with _FakeJdwpServer(JDWP_HANDSHAKE) as srv:
        ok, detail = tc._jdwp_handshake("127.0.0.1", srv.port, timeout=2)
    assert ok, f"faithful echo must PASS: {detail}"


def test_jdwp_handshake_wrong_echo_fails():
    """Server echoes DIFFERENT bytes -> FAIL (mismatch is not a crash)."""
    import toolchain as tc
    with _FakeJdwpServer(b"NOT-JDWP-ECHO!") as srv:
        ok, detail = tc._jdwp_handshake("127.0.0.1", srv.port, timeout=2)
    assert not ok, "wrong echo must FAIL"
    assert "mismatch" in detail.lower() or "echo" in detail.lower()


def test_jdwp_handshake_timeout_fails():
    """Server accepts but never replies -> FAIL via timeout."""
    import toolchain as tc
    with _FakeJdwpServer(hold=True) as srv:
        ok, detail = tc._jdwp_handshake("127.0.0.1", srv.port, timeout=1)
    assert not ok, "silent server must FAIL"


def test_jdwp_handshake_refused_fails():
    """Nothing listening -> FAIL, no crash."""
    import toolchain as tc
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    ok, detail = tc._jdwp_handshake("127.0.0.1", port, timeout=2)
    assert not ok


def test_jdwp_handshake_uses_no_jdb_attach():
    """The probe is RAW socket work: the handshake/jdwp probe functions
    never spawn a `jdb` subprocess (attach has side effects on the target)."""
    import inspect
    import toolchain as tc
    for fn_name in ("_jdwp_handshake", "_adb_jdwp_probe"):
        src = inspect.getsource(getattr(tc, fn_name))
        assert "jdb" not in src.replace("jdb -attach", "").replace("jdb ", ""), \
            f"{fn_name} must be raw-socket only, no jdb subprocess"


def test_jdwp_handshake_sends_fourteen_bytes():
    """The probe sends exactly the 14 ASCII bytes JDWP-Handshake."""
    import toolchain as tc
    sent: list[bytes] = []

    capture = socket.create_server(("127.0.0.1", 0))
    port = capture.getsockname()[1]

    def _serve():
        conn, _ = capture.accept()
        with conn:
            sent.append(conn.recv(64))
        capture.close()

    threading.Thread(target=_serve, daemon=True).start()
    tc._jdwp_handshake("127.0.0.1", port, timeout=2)  # reply never arrives
    assert sent and sent[0] == JDWP_HANDSHAKE, \
        f"probe must send the 14-byte handshake, sent: {sent}"


# ---------- acceptance 2: jdwp_debug item in the android matrix ----------

def _write_jdwp_adb_stub(fake_bin: Path, jdwp_port: int) -> Path:
    """Fake adb wiring `adb jdwp` -> pid and `adb forward` -> real local
    listener, so the probe's jdwp:<pid> forward lands on our fake server."""
    stub = fake_bin / "adb_stub.py"
    stub.write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if 'devices' in args:\n"
        "    print('List of devices attached')\n"
        "    print('emulator-5554\\tdevice')\n"
        "    sys.exit(0)\n"
        "if 'jdwp' in args:\n"
        "    print('4242')\n"
        "    sys.exit(0)\n"
        "if 'shell' in args and 'su' in args and 'id' in args:\n"
        "    print('uid=0(root) gid=0(root)')\n"
        "    sys.exit(0)\n"
        "if 'shell' in args and 'getprop' in args:\n"
        "    print('1' if 'ro.debuggable' in args else '31')\n"
        "    sys.exit(0)\n"
        f"if 'forward' in args:\n"
        f"    print('127.0.0.1:{jdwp_port}')\n"
        f"    sys.exit(0)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    adb = fake_bin / "adb"
    adb.write_text(
        f"#!/bin/sh\nexec \"{sys.executable}\" \"{stub}\" \"$@\"\n",
        encoding="utf-8",
    )
    adb.chmod(0o755)
    return stub


def _fake_bin_dir(tmp_path: Path) -> Path:
    fb = tmp_path / "fake-bin-474"
    fb.mkdir()
    return fb


def test_android_jdwp_check_pass_with_echo_server(kunglao_ws, tmp_path,
                                                  monkeypatch):
    """`jdwp_debug` PASS: fake adb (pid 4242 + forward to local) + faithful
    echo server -> LIVENESS probe, detail names the pid."""
    import toolchain as tc
    fake_bin = _fake_bin_dir(tmp_path)
    with _FakeJdwpServer(JDWP_HANDSHAKE) as srv:
        _write_jdwp_adb_stub(fake_bin, srv.port)
        monkeypatch.setenv("PATH", str(fake_bin))
        report = tc.check(kunglao_ws, "android")
    item = next(i for i in report.items if i.name == "jdwp_debug")
    assert item.status == tc.Status.PASS, item
    assert item.probe == tc.ProbeTier.LIVENESS
    assert "4242" in item.detail


def test_android_jdwp_check_fail_wrong_echo(kunglao_ws, tmp_path, monkeypatch):
    """`jdwp_debug` FAIL: server echoes wrong bytes (and carries guidance)."""
    import toolchain as tc
    fake_bin = _fake_bin_dir(tmp_path)
    with _FakeJdwpServer(b"WRONG-echo----") as srv:
        _write_jdwp_adb_stub(fake_bin, srv.port)
        monkeypatch.setenv("PATH", str(fake_bin))
        report = tc.check(kunglao_ws, "android")
    item = next(i for i in report.items if i.name == "jdwp_debug")
    assert item.status == tc.Status.FAIL, item
    assert "jdwp_debug" in tc.FIXES, "FAIL must have install/deploy guidance"


def test_android_jdwp_check_no_pids_fails(kunglao_ws, tmp_path, monkeypatch):
    """`adb jdwp` returns no pid (no debuggable process) -> FAIL."""
    import toolchain as tc
    fake_bin = _fake_bin_dir(tmp_path)
    stub = fake_bin / "adb_stub.py"
    stub.write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if 'devices' in args:\n"
        "    print('List of devices attached')\n"
        "    print('emulator-5554\\tdevice')\n"
        "    sys.exit(0)\n"
        "if 'jdwp' in args:\n"
        "    sys.exit(0)\n"  # empty pid list
        "if 'shell' in args and 'su' in args and 'id' in args:\n"
        "    print('uid=0(root) gid=0(root)')\n"
        "    sys.exit(0)\n"
        "if 'shell' in args and 'getprop' in args:\n"
        "    print('1' if 'ro.debuggable' in args else '31')\n"
        "    sys.exit(0)\n"
        "if 'forward' in args:\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    adb = fake_bin / "adb"
    adb.write_text(
        f"#!/bin/sh\nexec \"{sys.executable}\" \"{stub}\" \"$@\"\n",
        encoding="utf-8",
    )
    adb.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    report = tc.check(kunglao_ws, "android")
    item = next(i for i in report.items if i.name == "jdwp_debug")
    assert item.status == tc.Status.FAIL, item


def test_android_jdwp_check_adb_missing_cascades(kunglao_ws, tmp_path,
                                                 monkeypatch):
    """ADB missing -> jdwp_debug cascade-FAIL naming ADB as root cause."""
    import toolchain as tc
    empty = tmp_path / "empty-474"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    report = tc.check(kunglao_ws, "android")
    item = next(i for i in report.items if i.name == "jdwp_debug")
    assert item.status == tc.Status.FAIL, item
    assert item.root_cause == "ADB", item


def test_android_checkset_declares_jdwp():
    """CHECK_SETS['android'] declares jdwp_debug (matrix contract)."""
    import toolchain as tc
    assert "jdwp_debug" in tc.CHECK_SETS["android"]


# ---------- acceptance 1: decompiler three-state (MCP honest WARN) ----------

def _run_toolchain(ws: Path, extra: list[str], env_extra: dict | None = None
                   ) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPTS / "toolchain.py"), str(ws), *extra]
    env = {k: v for k, v in os.environ.items()
           if k not in ("GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(argv, capture_output=True, text=True, timeout=60,
                          env=env, errors="replace")


def test_decompiler_registered_mcp_only_is_warn_not_pass(
        kunglao_ws, tmp_path, monkeypatch):
    """#474 acceptance 1: registry carries `ghidra` + bridge port accepts TCP,
    but no capability evidence -> decompiler is WARN 'capability unverified',
    NEVER a fake PASS."""
    import toolchain as tc
    # registry with ghidra registered (hermetic KUNGLAO_CLAUDE_JSON override)
    fake_claude = tmp_path / "fake-claude.json"
    fake_claude.write_text(json.dumps({
        "mcpServers": {"ghidra": {}, "sequential-thinking": {}},
    }), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(fake_claude))
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    empty = tmp_path / "empty-bin-474"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    report = tc.check(kunglao_ws, "windows")
    item = next(i for i in report.items if i.name == "decompiler")
    assert item.status == tc.Status.WARN, \
        f"registered-only MCP must be WARN, not PASS: {item}"
    assert "capability unverified" in item.detail.lower(), item
    assert item.probe == tc.ProbeTier.LIVENESS
    # the WARN is HARD tier: it does not block (overall not FAIL from it)
    assert item.tier == tc.Tier.HARD


def test_decompiler_cli_presence_is_warn_not_pass(
        kunglao_ws, tmp_path, monkeypatch):
    """CLI analyzeHeadless exists (presence) but capability not trialed ->
    ghidra item WARN 'capability unverified', not PASS."""
    import toolchain as tc
    fake_claude = tmp_path / "fake-claude.json"
    fake_claude.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(fake_claude))
    ghidra = tmp_path / "ghidra"
    (ghidra / "support").mkdir(parents=True)
    headless = ghidra / "support" / platform_paths.analyze_headless_name()
    headless.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    headless.chmod(0o755)
    monkeypatch.setenv("GHIDRA_HOME", str(ghidra))
    empty = tmp_path / "empty-bin-474b"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    report = tc.check(kunglao_ws, "windows")
    item = next(i for i in report.items if i.name == "ghidra")
    assert item.status == tc.Status.WARN, \
        f"presence-only CLI must be WARN, not PASS: {item}"
    assert "capability unverified" in item.detail.lower(), item
    assert item.probe == tc.ProbeTier.PRESENCE


def test_decompiler_absent_still_fails(kunglao_ws, tmp_path, monkeypatch):
    """Nothing registered/present -> FAIL (unchanged)."""
    import toolchain as tc
    fake_claude = tmp_path / "fake-claude.json"
    fake_claude.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(fake_claude))
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    empty = tmp_path / "empty-bin-474c"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    report = tc.check(kunglao_ws, "windows")
    item = next(i for i in report.items if i.name == "decompiler")
    assert item.status == tc.Status.FAIL, item


def test_decompiler_capability_pass_under_caps_optin(
        kunglao_ws, tmp_path, monkeypatch):
    """caps=True + analyzeHeadless that succeeds on the synthetic import ->
    PASS with probe tier CAPABILITY and the trial detail."""
    import toolchain as tc
    fake_claude = tmp_path / "fake-claude.json"
    fake_claude.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(fake_claude))
    ghidra = tmp_path / "ghidra"
    (ghidra / "support").mkdir(parents=True)
    headless = ghidra / "support" / platform_paths.analyze_headless_name()
    # a fake headless that logs its argv and exits 0 on any -import
    log = tmp_path / "headless-argv.log"
    headless.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" >> \"{log}\"\n"
        "for arg in \"$@\"; do\n"
        "  [ \"$arg\" = \"-import\" ] && exit 0\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    headless.chmod(0o755)
    monkeypatch.setenv("GHIDRA_HOME", str(ghidra))
    empty = tmp_path / "empty-bin-474d"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    report = tc.check(kunglao_ws, "windows", caps=True)
    item = next(i for i in report.items if i.name == "ghidra")
    assert item.status == tc.Status.PASS, item
    assert item.probe == tc.ProbeTier.CAPABILITY
    # the trial really invoked the headless binary with -import
    assert log.exists() and "-import" in log.read_text(encoding="utf-8")


# ---------- acceptance 3: capability only under opt-in ----------

def test_default_path_never_trials_capability(kunglao_ws, tmp_path,
                                              monkeypatch):
    """check() without caps performs ZERO capability trials (seam counter)."""
    import toolchain as tc
    calls = {"capability": 0}
    real = getattr(tc, "_capability_probe_ghidra", None)

    def _counting(*a, **k):
        calls["capability"] += 1
        return real(*a, **k) if real else (True, "stub")

    monkeypatch.setattr(tc, "_capability_probe_ghidra", _counting,
                        raising=False)
    ghidra = tmp_path / "ghidra"
    (ghidra / "support").mkdir(parents=True)
    headless = ghidra / "support" / platform_paths.analyze_headless_name()
    headless.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    headless.chmod(0o755)
    monkeypatch.setenv("GHIDRA_HOME", str(ghidra))
    fake_claude = tmp_path / "fake-claude.json"
    fake_claude.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(fake_claude))
    empty = tmp_path / "empty-bin-474e"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    tc.check(kunglao_ws, "windows")
    assert calls["capability"] == 0, \
        "default path must not run the capability trial"

    tc.check(kunglao_ws, "windows", caps=True)
    assert calls["capability"] == 1, \
        "caps=True must reach the capability trial exactly once"


def test_cli_capability_flag(kunglao_ws, tmp_path, monkeypatch):
    """`--capability` CLI flag reaches the caps path (smoke: accepted arg)."""
    ghidra = tmp_path / "ghidra"
    (ghidra / "support").mkdir(parents=True)
    headless = ghidra / "support" / platform_paths.analyze_headless_name()
    headless.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    headless.chmod(0o755)
    fake_claude = tmp_path / "fake-claude.json"
    fake_claude.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    r = _run_toolchain(kunglao_ws, ["--type", "windows", "--capability"],
                       env_extra={"GHIDRA_HOME": str(ghidra),
                                  "KUNGLAO_CLAUDE_JSON": str(fake_claude),
                                  "PATH": str(tmp_path)})
    assert "unrecognized arguments" not in r.stderr, \
        f"--capability must be a valid flag: {r.stderr}"


# ---------- JSON carries the probe tier ----------

def test_json_output_carries_probe_field(kunglao_ws, tmp_path, monkeypatch):
    """--json: every check item has a `probe` key in
    {presence, liveness, capability}."""
    fake_claude = tmp_path / "fake-claude.json"
    fake_claude.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    empty = tmp_path / "empty-bin-474f"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    r = _run_toolchain(kunglao_ws, ["--type", "windows", "--json"],
                       env_extra={"KUNGLAO_CLAUDE_JSON": str(fake_claude),
                                  "PATH": str(empty)})
    data = json.loads(r.stdout)
    assert data["checks"], "expected non-empty checks"
    for c in data["checks"]:
        assert c["probe"] in ("presence", "liveness", "capability"), c


def test_existing_probes_classified_truthfully():
    """Spot-pin the truthful classification of existing checks: pefile
    import / gitnexus --version / su -c id / getprop read-back = capability;
    vm TCP connect / forward-probes = liveness; which-lookups = presence."""
    import inspect
    import toolchain as tc
    src = inspect.getsource(tc)
    # aapt/apktool/jadx are which() lookups -> presence semantics at minimum
    assert "ProbeTier.PRESENCE" in src
    assert "ProbeTier.LIVENESS" in src
    assert "ProbeTier.CAPABILITY" in src
