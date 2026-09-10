# -*- coding: utf-8 -*-
"""Issue 208 — task-lane routing: the task TYPE is a declared intake answer.

Symptom the lane field kills: task_spec.yaml was parameterized, but the
runtime baked ONE lane into the substrate — a malware binary under
bins/<sha>, RC_NO_SAMPLE when bins/ is empty, and an RE toolchain
(IDA/Ghidra/frida/unidbg/pefile) as the only gate. A user pointing the
system at a pure algorithm-RE task (protocol, codec, data transform — no
binary sample to hash) hit the malware scaffolding on init.

Contract pinned here:
  1. lane vocabulary is single-source (scripts/lane_spec.py) and covers
     malware | algorithm | protocol | web | data | app
  2. a fresh workspace that declares NOTHING (no lane, no task contract,
     no sample) is ASKED for the lane through the exit-8 pending-decision
     channel — no default, zero scaffold
  3. --resolve carries the answer; the declared lane persists into
     task_spec.yaml and wins on every later run (no re-ask)
  4. a legacy task_spec WITHOUT a lane field defaults to current
     (malware) behavior — byte-identical render, sample seed claims kept
  5. lane=malware keeps RC_NO_SAMPLE=5 on an empty bins/ (unchanged)
  6. an invalid lane answer fails closed (RC_ERROR), never a guessed lane
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _factories import seed_bins, seed_oracle_anchors  # noqa: E402

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
RC_OK = 0
RC_ERROR = 1
RC_NO_SAMPLE = 5
RC_PENDING_DECISIONS = 8

# The issue's enum, in the issue's order (ui/ask order follows it).
LANES = ("malware", "algorithm", "protocol", "web", "data", "app")

ANCHOR_ANSWERS = {
    "goal_verbatim": "recover the config decryption routine",
    "success_criterion": "a standalone client replays every captured "
                         "(input -> plaintext) pair byte-exact",
    "verification_method": "reproduction",
}


# --------------------------------------------------------------- harness

def _run_init(ws: Path, extra: list[str] | None = None,
              timeout: int = 300) -> subprocess.CompletedProcess:
    """Hermetic init run: toolchain skipped, profile writes pinned to a
    temp root, agent-teams flag forced off (the outer session may be
    contaminated)."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            "--skip-toolchain", *extra,
            "--profile-root", str(ws.parent / "profile-root")]
    if not any(a.startswith("--host-exec-protection") for a in argv):
        # non-interactive tests answer the host-exec ask explicitly
        argv += ["--host-exec-protection", "enabled"]
    env = dict(os.environ)
    env[FLAG_NAME] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(argv, capture_output=True, text=True, env=env,
                          timeout=timeout, cwd=str(ROOT), errors="replace")


def _answers_file(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "answers.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _pending_doc(stdout: str) -> dict:
    """The trailing pending-decision JSON document on stdout."""
    lines = stdout.strip().splitlines()
    parsed: dict | None = None
    for start in range(len(lines)):
        stripped = "\n".join(lines[start:]).strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                continue
    assert parsed is not None, f"no pending-decision JSON in stdout:\n{stdout}"
    return parsed


def _lane_decision(doc: dict) -> dict:
    for d in doc.get("decisions", []):
        if d.get("decision_id") == "lane":
            return d
    raise AssertionError(f"no lane decision in pending doc: {doc}")


def _spec(ws: Path) -> dict:
    return yaml.safe_load((ws / "task_spec.yaml").read_text(encoding="utf-8"))


# ------------------------------------------------- 1. single-source schema

def test_lane_vocabulary_is_single_source():
    """scripts/lane_spec.py owns the lane enum (import is the API)."""
    import lane_spec
    assert tuple(lane_spec.LANES) == LANES
    # the pre-lane contract: an undeclared lane means today's behavior
    assert lane_spec.DEFAULT_LEGACY == "malware"
    for lane in LANES:
        assert lane_spec.material(lane), f"lane {lane} lacks a material line"


def test_template_task_spec_documents_the_lane_field():
    """The shipped task_spec template carries the lane field + enum."""
    text = (ROOT / "templates" / "state" / "task_spec.yaml").read_text(
        encoding="utf-8")
    assert "lane:" in text, "template task_spec.yaml lacks the lane field"
    for lane in LANES:
        assert lane in text, f"template lane enum missing {lane}"


# ------------------------------------------------------ 2. the ask contract

def test_fresh_workspace_without_lane_asks_exit8(tmp_path):
    """Nothing declared (no lane / no task contract / no sample) -> the
    lane question, exit 8, zero scaffold — never a silent malware default."""
    ws = tmp_path / "ws"
    ws.mkdir()
    r = _run_init(ws, ["--type", "windows"])
    assert r.returncode == RC_PENDING_DECISIONS, \
        f"expected the lane ask (8), got {r.returncode}: {r.stdout}{r.stderr}"
    d = _lane_decision(_pending_doc(r.stdout))
    assert d["kind"] == "choice"
    assert tuple(d["options"]) == LANES
    assert d["default"] is None, "the lane is never defaulted (#455 posture)"
    # fail-closed: the ask precedes every scaffold write
    assert not (ws / "claim-register.yaml").exists()
    assert not (ws / "analysis_state.txt").exists()
    assert not (ws / "CLAUDE.md").exists()


def test_resolve_lane_answer_is_accepted_and_persisted(tmp_path):
    """--resolve carries the lane; it lands in task_spec.yaml and the run
    proceeds (no second ask)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    answers = dict(ANCHOR_ANSWERS)
    answers["lane"] = "algorithm"
    f = _answers_file(tmp_path, answers)
    r = _run_init(ws, ["--type", "linux", "--resolve", str(f)])
    assert r.returncode == RC_OK, \
        f"lane=algorithm init failed: {r.returncode}: {r.stdout}{r.stderr}"
    assert _spec(ws)["lane"] == "algorithm"
    assert (ws / "claim-register.yaml").exists()


def test_persisted_lane_wins_on_rerun(tmp_path):
    """The declared lane is the persisted value — a later run never
    re-asks and never flips it back to malware."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text(
        "lane: algorithm\n" + "".join(f"{k}: {v}\n"
                                      for k, v in ANCHOR_ANSWERS.items()),
        encoding="utf-8")
    r = _run_init(ws, ["--type", "linux"])
    assert r.returncode == RC_OK, \
        f"declared lane must not be re-asked: {r.returncode}: {r.stdout}{r.stderr}"
    assert _spec(ws)["lane"] == "algorithm"


def test_invalid_lane_answer_fails_closed(tmp_path):
    """A bad lane answer is refused (RC_ERROR) — never coerced to a lane."""
    ws = tmp_path / "ws"
    ws.mkdir()
    answers = dict(ANCHOR_ANSWERS)
    answers["lane"] = "algorthm"  # typo
    f = _answers_file(tmp_path, answers)
    r = _run_init(ws, ["--type", "linux", "--resolve", str(f)])
    assert r.returncode == RC_ERROR, \
        f"invalid lane must fail closed: {r.returncode}: {r.stdout}{r.stderr}"
    assert not (ws / "claim-register.yaml").exists()
    assert "lane" in (r.stdout + r.stderr).lower()


def test_invalid_lane_declared_in_spec_fails_closed(tmp_path):
    """A typo'd lane in the contract is a refused contract, not malware."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text(
        "lane: algorthm\n" + "".join(f"{k}: {v}\n"
                                     for k, v in ANCHOR_ANSWERS.items()),
        encoding="utf-8")
    r = _run_init(ws, ["--type", "linux"])
    assert r.returncode == RC_ERROR, \
        f"invalid declared lane must fail closed: {r.returncode}: {r.stdout}{r.stderr}"


# ------------------------------------------- 3. legacy + malware contracts

def test_legacy_spec_without_lane_defaults_to_malware(tmp_path):
    """A lane-less task_spec + a sample under bins/ = today's behavior:
    exit 0, sample seed claims, sample section rendered."""
    ws = tmp_path / "ws"
    seed_bins(ws)
    (ws / "runs").mkdir()
    seed_oracle_anchors(ws)  # legacy contract: anchors, no lane
    r = _run_init(ws, ["--type", "windows"])
    assert r.returncode == RC_OK, \
        f"legacy spec must keep working: {r.returncode}: {r.stdout}{r.stderr}"
    reg = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "Sample artifact identity" in reg, \
        "legacy default must keep the sample identity seed"
    assert "Sample sha256" in reg
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Sample under analysis" in text
    assert "bins/sample.exe" in text


def test_explicit_malware_lane_is_byte_identical_to_legacy(tmp_path):
    """lane=malware renders exactly what the lane-less contract renders."""
    legacy = tmp_path / "legacy"
    seed_bins(legacy)
    (legacy / "runs").mkdir()
    seed_oracle_anchors(legacy)
    r1 = _run_init(legacy, ["--type", "linux"])
    assert r1.returncode == RC_OK, r1.stderr

    explicit = tmp_path / "explicit"
    seed_bins(explicit)
    (explicit / "runs").mkdir()
    seed_oracle_anchors(explicit)
    explicit_answers = dict(ANCHOR_ANSWERS)
    explicit_answers["lane"] = "malware"
    f = _answers_file(tmp_path, explicit_answers)
    r2 = _run_init(explicit, ["--type", "linux", "--resolve", str(f)])
    assert r2.returncode == RC_OK, r2.stderr

    assert (explicit / "CLAUDE.md").read_bytes() == \
        (legacy / "CLAUDE.md").read_bytes(), \
        "lane=malware must render byte-identically to the legacy contract"
    legacy_seeds = _seed_titles(legacy)
    assert _seed_titles(explicit) == legacy_seeds


def _seed_titles(ws: Path) -> list[str]:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
        encoding="utf-8"))
    return [c["title"] for c in reg["claims"]]


def test_malware_lane_keeps_rc_no_sample(tmp_path):
    """lane=malware + empty bins/ -> RC_NO_SAMPLE=5 (current behavior),
    and the prompt names the lane escape for non-binary tasks."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    answers = dict(ANCHOR_ANSWERS)
    answers["lane"] = "malware"
    f = _answers_file(tmp_path, answers)
    r = _run_init(ws, ["--type", "windows", "--resolve", str(f)])
    assert r.returncode == RC_NO_SAMPLE, \
        f"malware lane must keep the no-sample prompt: {r.returncode}: {r.stdout}{r.stderr}"
    assert "place a sample into bins/" in r.stderr
    assert "--lane" in r.stderr, \
        "the no-sample prompt must name the non-binary lane escape"
    assert not (ws / "claim-register.yaml").exists()


# ------------------------------------------- 4. algorithm lane end to end

def _declared_ws(tmp_path: Path, lane: str) -> Path:
    """Workspace whose contract declares the lane; NO bins/ at all."""
    ws = tmp_path / f"ws-{lane}"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text(
        f"lane: {lane}\n" + "".join(f"{k}: {v}\n"
                                    for k, v in ANCHOR_ANSWERS.items()),
        encoding="utf-8")
    return ws


def test_algorithm_lane_init_without_bins_exits_ok(tmp_path):
    """lane=algorithm: no sample required — bins/ absent, exit 0, the
    workspace is initialized (the acceptance's core case)."""
    ws = _declared_ws(tmp_path, "algorithm")
    r = _run_init(ws, ["--type", "linux"])
    assert r.returncode == RC_OK, \
        f"algorithm lane must init without bins/: {r.returncode}: {r.stdout}{r.stderr}"
    assert (ws / "claim-register.yaml").exists()
    assert (ws / "CLAUDE.md").exists()
    assert not (ws / "bins").exists()  # nothing fabricated a sample dir


def test_algorithm_lane_render_is_sample_free(tmp_path):
    """The rendered handbook has NO unresolved placeholder and NO sample
    table — the material block is lane-rendered."""
    import template_render
    ws = _declared_ws(tmp_path, "algorithm")
    r = _run_init(ws, ["--type", "linux"])
    assert r.returncode == RC_OK, r.stderr
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert template_render.leftover_placeholders(text) == [], \
        f"unresolved placeholders survived the lane render: {text[:400]}"
    assert "## Sample under analysis" not in text
    assert "## Analysis material (lane: algorithm)" in text
    assert "bins/unknown" not in text


def test_algorithm_lane_seeds_carry_no_sample_claims(tmp_path):
    """No sample claim is seeded for a lane that mounts no sample."""
    ws = _declared_ws(tmp_path, "algorithm")
    r = _run_init(ws, ["--type", "linux"])
    assert r.returncode == RC_OK, r.stderr
    titles = _seed_titles(ws)
    assert titles, "structural seeds missing"
    assert not any("Sample" in t for t in titles), \
        f"sample claims seeded into a non-malware lane: {titles}"
    assert any("lane" in t.lower() for t in titles), titles
    state = (ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "lane=algorithm" in state


def test_algorithm_lane_toolchain_set_is_lane_appropriate(tmp_path):
    """The lane gate probes uv + python + the lane's material — never the
    MCP/RE supply (a codec task is not a binary-RE engagement)."""
    import toolchain
    ws = _declared_ws(tmp_path, "algorithm")
    report = toolchain.check(ws, "linux", lane="algorithm")
    names = [i.name for i in report.items]
    assert names == ["uv", "python", "corpora"], names
    leaked = [n for n in names if n in toolchain.LANE_NEVER_CHECKS]
    assert leaked == [], f"malware-lane items leaked into the lane gate: {leaked}"
    corpora = next(i for i in report.items if i.name == "corpora")
    assert corpora.tier == toolchain.Tier.WARN, \
        "unmounted lane material must not refuse init (WARN contract)"
    assert "algorithm" in corpora.detail


def test_lane_derived_from_task_spec_without_explicit_flag(tmp_path):
    """check() reads the lane from the parsed task_spec — the init call
    shape stays unchanged (the lane is a contract field, not a flag)."""
    import toolchain
    ws = _declared_ws(tmp_path, "algorithm")
    spec = yaml.safe_load((ws / "task_spec.yaml").read_text(encoding="utf-8"))
    report = toolchain.check(ws, "linux", task_spec=spec)
    assert [i.name for i in report.items] == ["uv", "python", "corpora"]


def test_malware_dispatch_is_unchanged_by_the_lane_gate(tmp_path):
    """lane=malware / lane absent -> the per-type check set, untouched."""
    import toolchain
    ws = tmp_path / "ws"
    ws.mkdir()
    legacy = toolchain.check(ws, "macos")
    explicit = toolchain.check(ws, "macos", lane="malware")
    assert [i.name for i in legacy.items] == [i.name for i in explicit.items]
    assert [i.status for i in legacy.items] == [i.status for i in explicit.items]
    # and no lane item exists on the malware path
    assert "corpora" not in [i.name for i in legacy.items]


def test_required_checks_has_no_malware_entry():
    """Single source: the malware lane is absent from the per-lane sets on
    purpose (it keeps the per-type CHECK_SETS dispatch)."""
    import lane_spec
    assert "malware" not in lane_spec.REQUIRED_CHECKS
    for lane in LANES:
        if lane == "malware":
            continue
        assert lane_spec.REQUIRED_CHECKS.get(lane), \
            f"lane {lane} lacks a required-check set"
        assert lane_spec.REQUIRED_CHECKS[lane][:2] == ("uv", "python"), \
            "every lane gate starts from uv + python"


# ------------------------- 5. protocol / web / data / app (documented stubs)

def test_lane_registry_splits_implemented_from_stubs():
    """The stub lanes are declared as such (documented stub, not a promise)."""
    import lane_spec
    assert lane_spec.IMPLEMENTED_LANES == ("malware", "algorithm")
    assert lane_spec.STUB_LANES == ("protocol", "web", "data", "app")
    assert set(lane_spec.IMPLEMENTED_LANES) | set(lane_spec.STUB_LANES) == set(LANES)
    for lane in lane_spec.STUB_LANES:
        assert "stub" in lane_spec.material(lane), \
            f"{lane} material line must declare the stub status"


@pytest.mark.parametrize("lane", ["protocol", "web", "data", "app"])
def test_stub_lane_contract(tmp_path, lane):
    """Per-lane contract: a stub lane initializes without a sample, renders
    no unresolved placeholder and no sample claim, and its toolchain gate is
    uv + python + the lane's material probe (WARN) — never the RE supply."""
    import toolchain
    ws = _declared_ws(tmp_path, lane)
    r = _run_init(ws, ["--type", "linux"])
    assert r.returncode == RC_OK, \
        f"{lane} lane init failed: {r.returncode}: {r.stdout}{r.stderr}"
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "{{" not in text, f"{lane} render left a placeholder"
    assert f"lane: {lane}" in text, f"{lane} lane not named in the render"
    assert "stub" in text, f"{lane} render must disclose the stub status"
    assert not any("Sample" in t for t in _seed_titles(ws)), \
        f"{lane} lane seeded sample claims"
    report = toolchain.check(ws, "linux", lane=lane)
    names = [i.name for i in report.items]
    assert names == ["uv", "python", f"{lane}_material"], names
    assert not [n for n in names if n in toolchain.LANE_NEVER_CHECKS]
    assert report.overall_status != toolchain.Status.FAIL, \
        f"{lane} stub gate must not refuse a clean uv+python host"


@pytest.mark.parametrize("lane", ["protocol", "web", "data", "app"])
def test_stub_lane_check_set_is_documented_in_lane_spec(lane):
    import lane_spec
    assert lane_spec.REQUIRED_CHECKS[lane] == ("uv", "python",
                                               f"{lane}_material")


# ------------------------------ 6. malware-only agents are gated at dispatch

MALWARE_ONLY_AGENTS = ("pefile-signature", "floss-filter", "go-symbols",
                       "ghidra-light", "kunglao-redteam")
LANE_AGNOSTIC_AGENTS = ("kunglao-worker", "kunglao-init-worker",
                        "verdict-scorer", "web-re-worker")


def _write_lane_ws(root: Path, lane: str | None) -> Path:
    """Initialized-looking workspace (the hook's resolver needs the
    claim-register sentinel) whose contract declares `lane`."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    lines = (f"lane: {lane}\n" if lane else "") + "".join(
        f"{k}: {v}\n" for k, v in ANCHOR_ANSWERS.items())
    (ws / "task_spec.yaml").write_text(lines, encoding="utf-8")
    return ws


def _run_dispatch_gate(root: Path, ws: Path, subagent_type: str,
                       prompt: str = "[T1] claim C-1 — test"):
    """Feed hooks/dispatch_gate.py one PreToolUse Agent payload."""
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(ws),
        "tool_input": {"prompt": prompt, "subagent_type": subagent_type},
    })
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(ROOT), errors="replace")


def test_agent_frontmatter_lane_bindings():
    """The five malware-only agents declare `lane: malware`; the
    lane-agnostic executors do not (issue 208 gating data)."""
    for name in MALWARE_ONLY_AGENTS:
        text = (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")
        head = text.split("---", 2)[1]
        assert re.search(r"^lane:\s*malware\b", head, re.M), \
            f"agents/{name}.md must declare lane: malware"
    for name in LANE_AGNOSTIC_AGENTS:
        text = (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")
        head = text.split("---", 2)[1]
        assert not re.search(r"^lane:\s*malware\b", head, re.M), \
            f"agents/{name}.md must not be lane-bound"


def test_hook_lane_enum_matches_lane_spec():
    """The hook repeats the enum (hooks load standalone) — pinned equal."""
    import importlib.util
    import lane_spec
    spec = importlib.util.spec_from_file_location(
        "dispatch_gate_lane_pin", ROOT / "hooks" / "dispatch_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert tuple(mod.LANE_ENUM) == tuple(lane_spec.LANES)
    assert mod.MALWARE_LANE == lane_spec.DEFAULT_LEGACY


@pytest.mark.parametrize("agent", MALWARE_ONLY_AGENTS)
def test_malware_only_agent_refused_on_non_malware_lane(tmp_path, agent):
    """A malware-lane-only agent dispatched into an algorithm workspace is
    REJECTed (rc=2) with a structured message naming agent + lane."""
    ws = _write_lane_ws(tmp_path, "algorithm")
    r = _run_dispatch_gate(tmp_path, ws, agent)
    assert r.returncode == 2, \
        f"{agent} must be refused on lane=algorithm: {r.returncode}: {r.stdout}{r.stderr}"
    assert "lane_routing" in r.stdout + r.stderr
    assert "algorithm" in r.stdout + r.stderr
    assert agent in r.stdout + r.stderr


def test_malware_agent_allowed_on_malware_lane(tmp_path):
    ws = _write_lane_ws(tmp_path, "malware")
    r = _run_dispatch_gate(tmp_path, ws, "ghidra-light")
    assert r.returncode == 0, f"malware lane must allow it: {r.stderr}"


def test_malware_agent_allowed_when_lane_undeclared(tmp_path):
    """Legacy contract (no lane field) = today's behavior — never blocked."""
    ws = _write_lane_ws(tmp_path, None)
    r = _run_dispatch_gate(tmp_path, ws, "ghidra-light")
    assert r.returncode == 0, f"legacy lane-less workspace must pass: {r.stderr}"


def test_lane_agnostic_agent_allowed_on_non_malware_lane(tmp_path):
    ws = _write_lane_ws(tmp_path, "algorithm")
    r = _run_dispatch_gate(tmp_path, ws, "kunglao-worker")
    assert r.returncode == 0, f"kunglao-worker is lane-agnostic: {r.stderr}"


def test_lane_gate_is_pre_activation(tmp_path):
    """The lane binding is a structural routing contract (fires even when
    the hooks are dormant) — the same structural corridor as the tool
    rack and MCP-prefix faces."""
    ws = _write_lane_ws(tmp_path, "data")
    r = _run_dispatch_gate(tmp_path, ws, "pefile-signature")
    assert r.returncode == 2, \
        "lane routing must not wait for hook activation"
