# -*- coding: utf-8 -*-
"""Tests for issue #455 — analysis-target alignment, intake step 0.

TDD RED phase: every test here fails before the #455 implementation lands
(decision_pending missing; kunglao-init still sniffs-first-file, still has
input() sites, still hard-requires workspace).

Checkbox map (issue #455 acceptance):
  1  no --type + non-interactive -> structured pending list, fail-closed
  2  multi-file bins/ -> explicit target required (no sort-order pick)
  3  MSI + APK detected as containers, contents listed, type never guessed
  4  android target triggers zero VMware/VBox/9876/1337 checks
  5  zero-arg invocation has a defined interaction order (no bare argparse)
  6  scripts contain zero input() call sites
  7  CLAUDE.md render consumes task_spec (vm_detonation + scope out)
  8  the #449 intake chain slot exercised end-to-end once
"""
from __future__ import annotations

import ast
import json
import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# #455 exit code: undecided intake item -> pending list on stdout, fail-closed.
RC_PENDING_DECISIONS = 8
RC_ERROR = 1
RC_OK = 0


# ---------- workspace fixtures ----------

@pytest.fixture
def init_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "runs").mkdir()
    return ws


def _make_pe(ws: Path, name: str) -> Path:
    p = ws / "bins" / name
    p.write_bytes(b"MZ\x90\x00" + b"\x00" * 128)
    return p


def _make_apk_zip(ws: Path, name: str = "sample.apk") -> Path:
    """Real zip APK fixture: classes.dex FIRST (so the magic+marker head check
    sees it), plus an embedded native .so."""
    p = ws / "bins" / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("classes.dex", b"dex\n035\x00" + b"\x00" * 64)
        z.writestr("lib/arm64-v8a/libx.so", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64)
    return p


def _cfb_entry(name: str, obj_type: int) -> bytes:
    """One 128-byte CFB directory entry (flat listing: no sibling tree)."""
    e = bytearray(128)
    name_bytes = name.encode("utf-16-le")
    e[0:len(name_bytes)] = name_bytes
    struct.pack_into("<H", e, 64, len(name_bytes) + 2)  # name len incl. null
    e[66] = obj_type        # 0=unused 1=storage 2=stream 5=root
    e[67] = 1               # color: black
    struct.pack_into("<I", e, 68, 0xFFFFFFFF)  # left sibling: NOSTREAM
    struct.pack_into("<I", e, 72, 0xFFFFFFFF)  # right sibling: NOSTREAM
    struct.pack_into("<I", e, 76, 0xFFFFFFFF)  # child: NOSTREAM
    struct.pack_into("<I", e, 108, 0xFFFFFFFE)  # start sector: ENDOFCHAIN
    return bytes(e)


def _make_msi(ws: Path, streams: tuple[str, ...] = ("Alpha", "Beta"),
              name: str = "sample.msi") -> Path:
    """Minimal parseable CFBF container (512-byte sectors): header + 1 FAT
    sector + 1 directory sector carrying the given stream names.

    Sector layout: 0 = FAT (FAT[0]=FATSECT, FAT[1]=ENDOFCHAIN),
    1 = directory (root + streams). The parser only needs the directory
    chain, so stream payloads are omitted (names-level listing is the #455
    contract).
    """
    header = bytearray(512)
    header[0:8] = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"  # CFBF signature
    struct.pack_into("<H", header, 0x1C, 0xFFFE)        # byte order
    struct.pack_into("<H", header, 0x1E, 9)             # sector shift: 512
    struct.pack_into("<H", header, 0x20, 6)             # mini sector shift
    struct.pack_into("<I", header, 0x2C, 1)             # 1 FAT sector
    struct.pack_into("<I", header, 0x30, 1)             # first dir sector
    struct.pack_into("<I", header, 0x38, 4096)          # mini cutoff
    struct.pack_into("<I", header, 0x3C, 0xFFFFFFFE)    # first miniFAT: none
    struct.pack_into("<I", header, 0x44, 0xFFFFFFFE)    # first DIFAT: none
    struct.pack_into("<I", header, 0x48, 0)             # DIFAT count: 0
    struct.pack_into("<I", header, 0x4C, 0)             # DIFAT[0] = sector 0
    for i in range(1, 109):
        struct.pack_into("<I", header, 0x4C + 4 * i, 0xFFFFFFFF)

    fat = bytearray(512)
    struct.pack_into("<I", fat, 0, 0xFFFFFFFD)          # sector 0 = FATSECT
    struct.pack_into("<I", fat, 4, 0xFFFFFFFE)          # sector 1 chain end

    entries = [_cfb_entry("Root Entry", 5)]
    entries += [_cfb_entry(n, 2) for n in streams]
    while len(entries) < 4:                              # fill the sector
        entries.append(bytes(128))
    directory = b"".join(entries)

    p = ws / "bins" / name
    p.write_bytes(bytes(header) + bytes(fat) + directory)
    return p


# ---------- CLI harness ----------

def _run_init(ws: Path | None, extra: list[str] | None = None,
              flag: str | None = "0",
              profile_root: Path | None = None) -> subprocess.CompletedProcess:
    """Run kunglao-init hermetically (NON-INTERACTIVE: no stdin channel is
    provided — #455 behavior must not depend on stdin at all)."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py")]
    if ws is not None:
        argv.append(str(ws))
    argv += list(extra or [])
    if profile_root is None:
        profile_root = (ws.parent if ws is not None else Path(".")) / "profile-root"
    argv += ["--profile-root", str(profile_root)]
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env["PYTHONIOENCODING"] = "utf-8"
    if flag is not None:
        env[FLAG_NAME] = flag
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


def _pending(result: subprocess.CompletedProcess) -> dict:
    """Parse the pending-decision JSON document from stdout (machine channel;
    human guidance lives on stderr)."""
    return json.loads(result.stdout)


def _write_answers(tmp_path: Path, name: str, payload: dict) -> Path:
    f = tmp_path / name
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


# ---------- checkbox 1: no --type non-interactive -> pending, fail-closed ----

def test_no_type_noninteractive_pending_fail_closed(init_ws: Path):
    """PE sample, no --type, no --resolve: sniff is NOT adopted — a
    structured pending list is printed, exit 8, zero scaffold."""
    _make_pe(init_ws, "sample.exe")
    r = _run_init(init_ws, ["--skip-toolchain"])
    assert r.returncode == RC_PENDING_DECISIONS, \
        f"undecided type must exit {RC_PENDING_DECISIONS}: {r.stdout}{r.stderr}"
    pending = _pending(r)
    ids = [d["decision_id"] for d in pending["decisions"]]
    assert "type" in ids, f"pending list lacks a type decision: {pending}"
    type_dec = next(d for d in pending["decisions"] if d["decision_id"] == "type")
    # #760: macos joins the labs pair (#728 web precedent)
    assert type_dec["options"] == ["windows", "linux", "android", "web", "macos"]
    assert type_dec["default"] is None, "sniffed type must not become a default"
    assert type_dec["context"].get("suggested_type") == "windows", \
        "sniff suggestion rides in context only"
    # fail-closed: nothing written
    assert not (init_ws / "analysis_state.txt").exists()
    assert not (init_ws / "claim-register.yaml").exists()
    assert not (init_ws / "CLAUDE.md").exists()


def test_resolve_type_completes_init(init_ws: Path, tmp_path: Path):
    """--resolve answers re-entry: {"type": "windows"} unblocks init."""
    _make_pe(init_ws, "sample.exe")
    answers = _write_answers(tmp_path, "a-type.json", {"type": "windows"})
    r = _run_init(init_ws, ["--skip-toolchain", "--resolve", str(answers)])
    assert r.returncode == RC_OK, f"{r.stdout}{r.stderr}"
    assert "project_type=windows" in (init_ws / "analysis_state.txt").read_text(
        encoding="utf-8")


# ---------- checkbox 2: multi-file target must be explicit ----------

def test_multi_file_requires_target_decision(init_ws: Path):
    """>1 file in bins/ and no target: pending target decision with BOTH
    names as options and NO default — the sorted-first-file pick is gone."""
    _make_pe(init_ws, "a_first.exe")
    _make_pe(init_ws, "z_target.exe")
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows"])
    assert r.returncode == RC_PENDING_DECISIONS, \
        f"multi-file without target must pend: {r.stdout}{r.stderr}"
    pending = _pending(r)
    target_dec = next(d for d in pending["decisions"] if d["decision_id"] == "target")
    assert sorted(target_dec["options"]) == ["a_first.exe", "z_target.exe"]
    assert target_dec["default"] is None


def test_multi_file_resolve_beats_sort_order(init_ws: Path, tmp_path: Path):
    """Resolved target z_target.exe (NOT the sorted-first a_first.exe) drives
    the seed claim + CLAUDE.md sample path (sort-order arbitrariness test)."""
    _make_pe(init_ws, "a_first.exe")
    _make_pe(init_ws, "z_target.exe")
    answers = _write_answers(tmp_path, "a-target.json",
                             {"target": "z_target.exe"})
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows",
                            "--resolve", str(answers)])
    assert r.returncode == RC_OK, f"{r.stdout}{r.stderr}"
    reg = (init_ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "z_target.exe" in reg, "C-001 must reference the ALIGNED target"
    assert "a_first.exe" not in reg
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "bins/z_target.exe" in claude


def test_multi_file_explicit_target_flag(init_ws: Path):
    """--target explicit flag: same as resolve, no pending."""
    _make_pe(init_ws, "a_first.exe")
    _make_pe(init_ws, "z_target.exe")
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows",
                            "--target", "z_target.exe"])
    assert r.returncode == RC_OK, f"{r.stdout}{r.stderr}"
    assert "z_target.exe" in (init_ws / "claim-register.yaml").read_text(
        encoding="utf-8")


def test_single_file_target_unique_no_pending(init_ws: Path):
    """Exactly one file: the target is the unique file (no ambiguity, no
    pending target decision) — --type explicit still completes."""
    _make_pe(init_ws, "only.exe")
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows"])
    assert r.returncode == RC_OK, f"{r.stdout}{r.stderr}"


def test_resolve_unknown_target_fails_closed(init_ws: Path, tmp_path: Path):
    """Answers naming a file not in bins/: RC_ERROR=1 (fail-closed)."""
    _make_pe(init_ws, "only.exe")
    answers = _write_answers(tmp_path, "a-bad.json", {"target": "nope.exe"})
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows",
                            "--resolve", str(answers)])
    assert r.returncode == RC_ERROR, f"{r.stdout}{r.stderr}"


def test_resolve_corrupt_answers_fails_closed(init_ws: Path, tmp_path: Path):
    answers = tmp_path / "a-broken.json"
    answers.write_text("{ not json", encoding="utf-8")
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows",
                            "--resolve", str(answers)])
    assert r.returncode == RC_ERROR, f"{r.stdout}{r.stderr}"


# ---------- checkbox 3: containers detected, listed, type not guessed -------

def test_msi_detected_as_container_with_inventory(init_ws: Path):
    """CFBF magic -> kind msi; contents listed in a target_object decision;
    type already decided via --type so ONLY the object pends."""
    _make_msi(init_ws, streams=("Alpha", "Beta"))
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows"])
    assert r.returncode == RC_PENDING_DECISIONS, \
        f"container object must pend: {r.stdout}{r.stderr}"
    pending = _pending(r)
    obj = next(d for d in pending["decisions"]
               if d["decision_id"] == "target_object")
    assert "Alpha" in obj["options"] and "Beta" in obj["options"]
    assert "__container__" in obj["options"]
    assert obj["context"].get("kind") == "msi"


def _make_msi_v4(ws: Path, streams: tuple[str, ...] = ("fil594F", "fil4905"),
                 storages: tuple[str, ...] = ("EncryptedPayload",),
                 name: str = "sample.msi") -> Path:
    """Minimal CFBF **version 4** container (4096-byte sectors) — the layout
    of every real-world MSI the review measured (HIGH-1).

    MS-CFB places sector N at (N+1)*sector_size: the 512-byte header heads
    the file and bytes [512, sector_size) are padding. Only for 512-byte
    sectors does 512+N*sector_size coincide with the spec.

    Sector map (forces the spec base to matter): 0 = FAT (at 4096),
    1-2 = unallocated zeros, 3 = zero directory sector, 4 = directory with
    the real entries. A 512+N*sector_size base reads the HEADER as the FAT
    and its directory windows land in zeros/header padding — the 512-byte
    tail overlap with each spec window contains only zero entries.
    """
    sector_size = 4096
    header = bytearray(512)
    header[0:8] = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"  # CFBF signature
    struct.pack_into("<H", header, 0x1A, 4)             # major version: 4
    struct.pack_into("<H", header, 0x1C, 0xFFFE)        # byte order
    struct.pack_into("<H", header, 0x1E, 12)            # sector shift: 4096
    struct.pack_into("<H", header, 0x20, 6)             # mini sector shift
    struct.pack_into("<I", header, 0x2C, 1)             # 1 FAT sector
    struct.pack_into("<I", header, 0x30, 3)             # first dir sector = 3
    struct.pack_into("<I", header, 0x38, 4096)          # mini cutoff
    struct.pack_into("<I", header, 0x3C, 0xFFFFFFFE)    # first miniFAT: none
    struct.pack_into("<I", header, 0x44, 0xFFFFFFFE)    # first DIFAT: none
    struct.pack_into("<I", header, 0x48, 0)             # DIFAT count: 0
    struct.pack_into("<I", header, 0x4C, 0)             # DIFAT[0] = sector 0
    for i in range(1, 109):
        struct.pack_into("<I", header, 0x4C + 4 * i, 0xFFFFFFFF)

    fat = bytearray(sector_size)
    struct.pack_into("<I", fat, 0, 0xFFFFFFFD)          # sector 0 = FATSECT
    struct.pack_into("<I", fat, 4, 0xFFFFFFFF)          # sector 1 = FREESECT
    struct.pack_into("<I", fat, 8, 0xFFFFFFFF)          # sector 2 = FREESECT
    struct.pack_into("<I", fat, 12, 4)                  # sector 3 -> 4 (dir chain)
    struct.pack_into("<I", fat, 16, 0xFFFFFFFE)         # sector 4 chain end

    entries = [_cfb_entry("Root Entry", 5)]
    entries += [_cfb_entry(n, 1) for n in storages]     # storages (type 1)
    entries += [_cfb_entry(n, 2) for n in streams]      # streams (type 2)
    while len(entries) < sector_size // 128:            # fill the sector
        entries.append(bytes(128))
    directory = b"".join(entries)

    p = ws / "bins" / name
    # sector N at (N+1)*4096: FAT 0@4096, zeros 1-2, dir 3 (zeros)@16384,
    # dir 4 (entries)@20480
    p.write_bytes(bytes(header) + bytes(sector_size - 512)
                  + bytes(fat) + bytes(sector_size)      # sector 1: zeros
                  + bytes(sector_size) + bytes(sector_size)  # 2-3: zeros
                  + directory)                           # sector 4: entries
    return p


def test_msi_v4_sector_base_spec_offsets(init_ws: Path):
    """REVIEW HIGH-1: real MSIs are CFB v4/4096. MS-CFB places sector N at
    (N+1)*sector_size; a 512+N*sector_size base lands mid-FAT/padding, reads
    garbage directory entries, and silently presents a misaligned inventory
    as legit options. The v4 fixture must yield the REAL stream names."""
    _make_msi_v4(init_ws, streams=("fil594F", "fil4905"),
                 storages=("EncryptedPayload",))
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows"])
    assert r.returncode == RC_PENDING_DECISIONS, \
        f"container object must pend: {r.stdout}{r.stderr}"
    obj = next(d for d in _pending(r)["decisions"]
               if d["decision_id"] == "target_object")
    assert "fil594F" in obj["options"] and "fil4905" in obj["options"], \
        f"v4/4096 streams missing (misaligned inventory): {obj['options']}"
    assert obj["context"]["contents_full"] == ["fil594F", "fil4905"], \
        f"contents_full must carry the full v4 stream inventory: {obj['context']}"


def test_msi_inventory_excludes_structural_entries(init_ws: Path):
    """REVIEW LOW-4: storages (type 1) and the root entry (type 5) are
    container STRUCTURE, not embedded objects — they must never appear as
    target_object options (both the v3 and v4 fixtures pin this)."""
    _make_msi(init_ws, streams=("Alpha", "Beta"))
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows"])
    assert r.returncode == RC_PENDING_DECISIONS, f"{r.stdout}{r.stderr}"
    obj = next(d for d in _pending(r)["decisions"]
               if d["decision_id"] == "target_object")
    assert "Root Entry" not in obj["options"], \
        f"root entry is structure, not a target option: {obj['options']}"
    assert "Alpha" in obj["options"] and "Beta" in obj["options"]
    assert obj["options"][-1] == "__container__"


def test_apk_container_type_never_guessed(init_ws: Path):
    """APK (zip) is a container: contents listed, and the type decision has
    NO default even though the old sniffer would have said 'android'."""
    _make_apk_zip(init_ws)
    r = _run_init(init_ws, ["--skip-toolchain"])
    assert r.returncode == RC_PENDING_DECISIONS, f"{r.stdout}{r.stderr}"
    pending = _pending(r)
    obj = next(d for d in pending["decisions"]
               if d["decision_id"] == "target_object")
    assert "classes.dex" in obj["options"]
    assert any(o.endswith("libx.so") for o in obj["options"])
    assert "__container__" in obj["options"]
    assert obj["context"].get("kind") == "apk"
    type_dec = next(d for d in pending["decisions"] if d["decision_id"] == "type")
    assert type_dec["default"] is None, "container type must not be guessed"


def test_container_object_choice_persisted(init_ws: Path, tmp_path: Path):
    """Resolved target_object lands in analysis_state.txt
    (analysis_target_object=...) so the container layering survives init."""
    _make_apk_zip(init_ws)
    answers = _write_answers(tmp_path, "a-obj.json",
                             {"target_object": "classes.dex", "type": "android"})
    r = _run_init(init_ws, ["--skip-toolchain", "--resolve", str(answers)])
    assert r.returncode == RC_OK, f"{r.stdout}{r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "analysis_target_object=classes.dex" in state
    assert "project_type=android" in state


# ---------- checkbox 4: android never touches the VMware/VBox channel -------

def _stub_toolchain_probes(monkeypatch):
    """Hermetic toolchain.check: no real binaries, no real MCP registry, and
    a counting _tcp_connect seam (the VMware/VBox channel probe)."""
    import toolchain
    calls = {"tcp_connect": 0}

    def _count_tcp(host, port, timeout=2):
        calls["tcp_connect"] += 1
        return False, f"{port}: stubbed"

    monkeypatch.setattr(toolchain, "_shutil_which", lambda name: None)
    monkeypatch.setattr(toolchain, "_run_cmd",
                        lambda args, timeout=10: (1, "", "stubbed"))
    monkeypatch.setattr(toolchain, "_tcp_connect", _count_tcp)
    monkeypatch.setattr(toolchain.mcp_probe, "check_mcp",
                        lambda ws, t: [])
    monkeypatch.setattr(toolchain.mcp_probe, "registered_names",
                        lambda *a, **k: set())
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
    return toolchain, calls


def test_android_checkset_declared_without_vm_channel():
    """The type->check-set table exists and carries the explicit negative
    declaration: android NEVER includes vm_reachable / remote_debugger."""
    import toolchain
    assert hasattr(toolchain, "CHECK_SETS"), "CHECK_SETS declaration missing"
    android = toolchain.CHECK_SETS["android"]
    assert "vm_reachable" not in android
    assert "remote_debugger" not in android
    assert "vm_reachable" in toolchain.CHECK_SETS["windows"]
    assert "vm_reachable" in toolchain.CHECK_SETS["linux"]
    never = getattr(toolchain, "NEVER_CHECKS", {})
    assert never.get("android") == {"vm_reachable", "remote_debugger"} or \
        set(never.get("android", ())) == {"vm_reachable", "remote_debugger"}


def test_android_report_zero_vm_channel_probes(init_ws: Path, monkeypatch):
    """Regression: an android toolchain report has NO vm_reachable /
    remote_debugger items and makes ZERO _tcp_connect calls (the mechanical
    9876/1337 VMware/VBox statement)."""
    toolchain, calls = _stub_toolchain_probes(monkeypatch)
    report = toolchain.check(init_ws, "android")
    names = {i.name for i in report.items}
    assert "vm_reachable" not in names, \
        f"android contract must not contain vm_reachable: {sorted(names)}"
    assert "remote_debugger" not in names, \
        f"android contract must not contain remote_debugger: {sorted(names)}"
    assert calls["tcp_connect"] == 0, "android path must not TCP-probe a VM host"
    assert names <= set(toolchain.CHECK_SETS["android"])


def test_windows_report_still_probes_vm_channel(init_ws: Path, monkeypatch):
    """The negative declaration did not shrink the other contracts: the
    windows report still carries the vm_reachable item."""
    toolchain, calls = _stub_toolchain_probes(monkeypatch)
    report = toolchain.check(init_ws, "windows")
    names = {i.name for i in report.items}
    assert "vm_reachable" in names


# ---------- checkbox 5: zero-arg invocation has a defined order -------------

def test_zero_arg_pending_workspace_first(tmp_path: Path):
    """No arguments at all: NOT a bare argparse error — a pending list whose
    FIRST decision is the workspace, with the interaction order in guidance."""
    r = _run_init(None, [], profile_root=tmp_path / "profile-root")
    assert r.returncode == RC_PENDING_DECISIONS, \
        f"zero-arg must exit {RC_PENDING_DECISIONS}, got {r.returncode}: {r.stdout}{r.stderr}"
    assert "usage:" not in r.stdout, "no bare argparse usage dump on stdout"
    pending = _pending(r)
    first = pending["decisions"][0]
    assert first["decision_id"] == "workspace"
    guidance = pending["guidance"]
    # the defined intake order: path -> target -> type -> requirements (#449)
    assert "target" in guidance and "type" in guidance


def test_zero_arg_resolve_workspace_continues(tmp_path: Path):
    """The workspace answer re-enters the flow and reaches the next pending
    round (target/type) — the chain is walkable."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "runs").mkdir()
    _make_pe(ws, "sample.exe")
    answers = _write_answers(tmp_path, "a-ws.json", {"workspace": str(ws)})
    r = _run_init(None, ["--skip-toolchain", "--resolve", str(answers)],
                  profile_root=tmp_path / "profile-root")
    assert r.returncode == RC_PENDING_DECISIONS, f"{r.stdout}{r.stderr}"
    ids = [d["decision_id"] for d in _pending(r)["decisions"]]
    assert "type" in ids


def test_malformed_flag_still_rc_error(init_ws: Path):
    """Genuinely malformed flags keep the #414 normalization (RC_ERROR=1),
    distinct from the pending exit 8."""
    _make_pe(init_ws, "sample.exe")
    r = _run_init(init_ws, ["--type", "banana"])
    assert r.returncode == RC_ERROR


# ---------- checkbox 6: zero input() call sites in scripts/ -----------------

def test_no_input_calls_in_scripts():
    """AST gate: no scripts/*.py may call input() / builtins.input() — the
    D1-recurrence guard for the #455 architecture (stdin is not a user
    channel; interaction = pending list + --resolve)."""
    offenders: list[str] = []
    for py in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "input":
                offenders.append(f"{py.name}:{node.lineno} input()")
            elif (isinstance(func, ast.Attribute) and func.attr == "input"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "builtins"):
                offenders.append(f"{py.name}:{node.lineno} builtins.input()")
    assert offenders == [], f"interactive input() sites remain: {offenders}"


# ---------- checkbox 7: CLAUDE.md render consumes task_spec -----------------

def _write_task_spec(ws: Path, vm_detonation: str = "forbidden",
                     out: list[str] | None = None) -> None:
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - id: q1\n    q: 'is it family X?'\n"
        "    need: yes_no_with_evidence\n"
        f"scope:\n  in: []\n  out: {out or ['bitcoin_clipper', 'anti_analysis_strings']}\n"
        f"constraints:\n  vm_detonation: {vm_detonation}\n"
        "  time_budget_minutes: 120\n  dynamic_re: forbidden\n"
        "depth: standard\n",
        encoding="utf-8",
    )


def test_claudemd_carries_task_spec_constraints(init_ws: Path):
    _make_pe(init_ws, "sample.exe")
    _write_task_spec(init_ws)
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows"])
    assert r.returncode == RC_OK, f"{r.stdout}{r.stderr}"
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "vm_detonation: forbidden" in claude, \
        "vm_detonation constraint missing from the workspace contract"
    assert "bitcoin_clipper" in claude, "scope exclusion missing from CLAUDE.md"
    assert "anti_analysis_strings" in claude


def test_claudemd_without_task_spec_omits_section(init_ws: Path):
    _make_pe(init_ws, "sample.exe")
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows"])
    assert r.returncode == RC_OK, f"{r.stdout}{r.stderr}"
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Task constraints" not in claude
    assert "{{" not in claude, "placeholder residue in rendered CLAUDE.md"


def test_claudemd_corrupt_task_spec_fails_closed(init_ws: Path):
    _make_pe(init_ws, "sample.exe")
    (init_ws / "task_spec.yaml").write_text(
        "primary_questions: [unclosed\n  bad: {", encoding="utf-8")
    r = _run_init(init_ws, ["--skip-toolchain", "--type", "windows"])
    assert r.returncode == RC_ERROR, \
        f"corrupt task_spec must fail closed (RC_ERROR): {r.returncode}"
    assert not (init_ws / "claim-register.yaml").exists() or \
        "[initialized]" not in (init_ws / "claim-register.yaml").read_text(
            encoding="utf-8")


# ---------- checkbox 8: the #449 intake chain slot, walked once -------------

def test_intake_chain_zero_arg_to_android_report(tmp_path: Path, monkeypatch):
    """Full chain in one test (the #449 rehearsal slot):
    zero-arg pending(workspace) -> resolve workspace -> pending(target_object,
    type) -> place task_spec (requirements step) -> resolve -> init OK ->
    CLAUDE.md carries task_spec constraints -> android toolchain report with
    zero VM-channel items."""
    ws = tmp_path / "chain-ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "runs").mkdir()
    _make_apk_zip(ws)

    # step 0: zero-arg -> pending workspace
    r0 = _run_init(None, [], profile_root=tmp_path / "profile-root")
    assert r0.returncode == RC_PENDING_DECISIONS
    assert _pending(r0)["decisions"][0]["decision_id"] == "workspace"

    # step 1: workspace resolved -> next pending round (target_object + type)
    a1 = _write_answers(tmp_path, "chain-1.json", {"workspace": str(ws)})
    r1 = _run_init(None, ["--skip-toolchain", "--resolve", str(a1)],
                   profile_root=tmp_path / "profile-root")
    assert r1.returncode == RC_PENDING_DECISIONS, f"{r1.stdout}{r1.stderr}"
    ids1 = [d["decision_id"] for d in _pending(r1)["decisions"]]
    assert "target_object" in ids1 and "type" in ids1

    # step 2 (requirements slot, #449's): task_spec lands in the workspace
    _write_task_spec(ws, vm_detonation="forbidden", out=["network_exfil"])

    # step 3: target_object + type resolved -> init completes (the workspace
    # answer rides along in the same answers file)
    a2 = _write_answers(tmp_path, "chain-2.json",
                        {"workspace": str(ws), "target_object": "classes.dex",
                         "type": "android"})
    r2 = _run_init(None, ["--skip-toolchain", "--resolve", str(a2)],
                   profile_root=tmp_path / "profile-root")
    assert r2.returncode == RC_OK, f"{r2.stdout}{r2.stderr}"
    claude = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "vm_detonation: forbidden" in claude
    assert "network_exfil" in claude

    # step 4: env contract — android report with zero VM-channel checks
    toolchain, calls = _stub_toolchain_probes(monkeypatch)
    report = toolchain.check(ws, "android")
    names = {i.name for i in report.items}
    assert "vm_reachable" not in names and "remote_debugger" not in names
    assert calls["tcp_connect"] == 0
