#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_canonical_chain_752.py — hook teleport chain (#752).

Issue #752 (D-class field finding): the #269 ruling modeled only two states
(canonical vs worktree), so a LONG-LIVED dev co-install
(`~/.claude/skills/kunglao-agent-dev`) running --wire-up teleported all 12
hook commands back at the stale 0.1.2 production install, while the
post-write selfcheck validated against the very variable it had just been
handed (self-certifying loop).

Acceptance pinned here:

  AC1 (D4)   durable-install resolution: any `~/.claude/skills/<name>/`
             install (production OR long-lived dev co-install OR an
             arbitrarily renamed install) teleports to ITSELF; only
             non-skills locations fall back to the canonical production
             install. Dual-install coexistence: dev wires workspace-B fully
             into dev, production wires workspace-A fully into production,
             neither leaks — and NO artifact may depend on the literal
             'kunglao-agent' name (rename-invariance).
  AC2 (D4+)  selfcheck shape leg derives its expectation independently;
             a caller handing it a matching-but-wrong hook_dir must FAIL.
  AC3 (D5)   residual scavenger: mixed-state (--project OLD + script NEW)
             and full v0.1.2-state workspaces, re-wired, leave ALL 12
             commands at the executing root with old-root refcount == 0.
  AC4 (D6)   upgrade end-step install-reference sweep reports + rewires
             stale references on stderr without touching exit codes; the
             already-current fast path sweeps too; dry-run writes nothing.

All HOME / install-location simulations are monkeypatch-only (tmp_path) —
the real ~/.claude tree is NEVER touched.
"""
from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import hook_activation  # noqa: E402
import wire_up_settings  # noqa: E402

WIRE_UP_HOOK_FILES = wire_up_settings.WIRE_UP_HOOK_FILES
WIRE_UP_ENTRIES = len(WIRE_UP_HOOK_FILES) + len(
    wire_up_settings.DOUBLE_REGISTERED_HOOKS & WIRE_UP_HOOK_FILES)


# ---------------------------------------------------------------- helpers

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Path.home() -> tmp home with an empty ~/.claude/skills tree."""
    home = tmp_path / "fake-home"
    (home / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)
    return home


def _install_at(skills_root: Path, name: str) -> Path:
    """Materialize a minimal durable install skeleton under skills/<name>/
    (dirs only — no real code needed: resolution is path-shaped)."""
    pkg = skills_root / name
    (pkg / "scripts").mkdir(parents=True)
    (pkg / "hooks").mkdir(parents=True)
    return pkg


def _exec_from(monkeypatch, package_root: Path) -> None:
    """Patch hook_activation's module location so the REAL repo checkout
    masquerades as an install rooted elsewhere (monkeypatch-only — the
    actual file never moves)."""
    monkeypatch.setattr(
        hook_activation, "__file__",
        str(package_root / "scripts" / "hook_activation.py"))


def _commands(settings_path: Path) -> list[str]:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    return [str(h.get("command", ""))
            for entries in settings.get("hooks", {}).values()
            for e in entries
            for h in e.get("hooks", [])]


def _wire(ws: Path) -> Path:
    rc_marker = ws / ".claude" / "settings.json"
    hook_activation.register_hooks(workspace=ws)
    return rc_marker


# ===========================================================================
# AC1 (D4) — durable-install resolution + rename-invariance + coexistence
# ===========================================================================

def test_dev_coinstall_resolves_to_itself(fake_home, monkeypatch):
    """The user ruling behind #752: a dev co-install is a LONG-LIVED DURABLE
    INSTALL, not a worktree — it teleports to ITSELF."""
    prod = _install_at(fake_home / ".claude" / "skills", "kunglao-agent")
    dev = _install_at(fake_home / ".claude" / "skills", "kunglao-agent-dev")
    assert prod.exists() and dev.exists()
    _exec_from(monkeypatch, dev)
    assert hook_activation.canonical_install_root() == dev


def test_renamed_coinstall_resolves_to_itself(fake_home, monkeypatch):
    """Rename-invariance: the predicate must be parent-shape-based — ANY
    name under ~/.claude/skills/ is durable. No 'kunglao-agent' literal."""
    odd = _install_at(fake_home / ".claude" / "skills",
                      "kunglao-agent-turbo-nightly")
    _exec_from(monkeypatch, odd)
    assert hook_activation.canonical_install_root() == odd


def test_repo_checkout_falls_back_to_production(fake_home, monkeypatch):
    """Non-skills locations keep the #269/#228 fallback: a repo checkout or
    .wt-* worktree must never bind hook commands to itself."""
    skills = fake_home / ".claude" / "skills"
    _install_at(skills, "kunglao-agent")
    for elsewhere in (
            fake_home.parent / "repo-checkout" / "kunglao-agent-pkg",
            fake_home / ".claude" / ".wt-fix-123" / "kunglao-agent"):
        elsewhere.mkdir(parents=True, exist_ok=True)
        _exec_from(monkeypatch, elsewhere)
        assert hook_activation.canonical_install_root() == \
            skills / "kunglao-agent", f"ephemeral {elsewhere} must fall back"


def test_production_install_is_self(fake_home, monkeypatch):
    prod = _install_at(fake_home / ".claude" / "skills", "kunglao-agent")
    _exec_from(monkeypatch, prod)
    assert hook_activation.canonical_install_root() == prod


def test_dual_coexist_wiring_never_crosses(fake_home, monkeypatch):
    """Dual-install coexistence: dev wires workspace-B entirely into dev;
    production wires workspace-A entirely into production; neither set of
    commands references the other install — nor any literal install name
    outside its own root (rename-invariance at the artifact level)."""
    skills = fake_home / ".claude" / "skills"
    prod = _install_at(skills, "kunglao-agent")
    dev = _install_at(skills, "kunglao-agent-dev")

    ws_b = fake_home.parent / "ws-B"
    ws_b.mkdir(parents=True)
    _exec_from(monkeypatch, dev)
    _wire(ws_b)
    cmds_b = _commands(ws_b / ".claude" / "settings.json")
    assert len(cmds_b) == WIRE_UP_ENTRIES
    for c in cmds_b:
        assert c.startswith(f"PYTHONUTF8=1 uv run --project {dev.as_posix()} "), c
        assert f"{dev.as_posix()}/" in c and f"{prod.as_posix()}/" not in c, c

    ws_a = fake_home.parent / "ws-A"
    ws_a.mkdir()
    _exec_from(monkeypatch, prod)
    _wire(ws_a)
    cmds_a = _commands(ws_a / ".claude" / "settings.json")
    assert len(cmds_a) == WIRE_UP_ENTRIES
    for c in cmds_a:
        assert c.startswith(f"PYTHONUTF8=1 uv run --project {prod.as_posix()} "), c
        assert f"{prod.as_posix()}/" in c and f"{dev.as_posix()}/" not in c, c


def test_wireup_artifacts_are_rename_invariant(fake_home, monkeypatch):
    """No wired artifact may carry a hardcoded 'kunglao-agent' literal-path
    dependency: run the whole face as an oddly-named install and require
    the (non-)presence proof directly."""
    odd = _install_at(fake_home / ".claude" / "skills", "some-renamed-build")
    ws = fake_home.parent / "ws-odd"
    ws.mkdir(parents=True)
    _exec_from(monkeypatch, odd)
    target = _wire(ws)
    blob = target.read_text(encoding="utf-8")
    assert '"kunglao-agent"' not in blob
    assert f"{odd.as_posix()}" in blob, "commands must carry the own root"
    assert "/kunglao-agent/" not in blob, \
        "no literal kunglao-agent path segment may survive a renamed install"


# ===========================================================================
# AC2 (D4+) — selfcheck shape leg derives independently of the caller
# ===========================================================================

def _write_at(root: Path, ws: Path, hook_file: str = "env_check_gate.py",
              matcher: str = "Agent") -> Path:
    """A settings.json whose single kunglao command points into `root`."""
    target = ws / ".claude" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    skill_root = root.parent
    target.write_text(json.dumps({
        "hooks": {"PreToolUse": [{"matcher": matcher, "hooks": [
            {"type": "command",
             "command": f"PYTHONUTF8=1 uv run --project {skill_root.as_posix()} "
                        f"{(root / hook_file).as_posix()}"}]}]}}),
        encoding="utf-8")
    return target


def test_selfcheck_fails_stale_canonical_commands(fake_home, monkeypatch):
    """THE #752 mismatch made real: the file's commands teleport to the
    stale production install while the module executes from the dev
    co-install. Default derivation must FAIL it — no variables involved."""
    skills = fake_home / ".claude" / "skills"
    prod = _install_at(skills, "kunglao-agent")
    dev = _install_at(skills, "kunglao-agent-dev")
    _exec_from(monkeypatch, dev)
    ws = fake_home.parent / "ws-stale"
    ws.mkdir(parents=True)
    target = _write_at(prod / "hooks", ws)
    result = hook_activation.selfcheck_registration(
        target, expected_files={"env_check_gate.py"}, workspace=ws,
        layer="project")
    assert result["ok"] is False
    assert any("shape" in m and str(prod) in m
               for m in result["mismatches"]), result["mismatches"]


def test_selfcheck_ignores_a_lying_caller_hook_dir(fake_home, monkeypatch):
    """The self-certifying loop of #752, killed outright: the caller hands
    in the SAME wrong dir the bad file matches — the verdict must still be
    FAIL because the expectation is recomputed from the executing install,
    never taken from the parameter."""
    skills = fake_home / ".claude" / "skills"
    prod = _install_at(skills, "kunglao-agent")
    dev = _install_at(skills, "kunglao-agent-dev")
    _exec_from(monkeypatch, dev)
    ws = fake_home.parent / "ws-liar"
    ws.mkdir(parents=True)
    target = _write_at(prod / "hooks", ws)
    result = hook_activation.selfcheck_registration(
        target, expected_files={"env_check_gate.py"},
        hook_dir=prod / "hooks",  # the lie: matches the file, not reality
        workspace=ws, layer="project")
    assert result["ok"] is False, (
        "a caller-supplied hook_dir must never certify itself: "
        f"{result}")


def test_register_hooks_does_not_forward_hook_dir(fake_home, monkeypatch,
                                                  tmp_path):
    """Writer/checker separation at the callsite: register_hooks must no
    longer hand its own variable to the checker."""
    dev = _install_at(fake_home / ".claude" / "skills", "kunglao-agent-dev")
    _exec_from(monkeypatch, dev)
    seen: dict = {}

    real_selfcheck = hook_activation.selfcheck_registration

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real_selfcheck(*args, **kwargs)

    monkeypatch.setattr(hook_activation, "selfcheck_registration", spy)
    ws = fake_home.parent / "ws-spy"
    ws.mkdir(parents=True)
    hook_activation.register_hooks(workspace=ws)
    assert "hook_dir" not in seen, \
        f"register_hooks must derive, not forward: {seen.keys()}"


# ===========================================================================
# AC3 (D5) — residual scavenger: re-wire leaves zero stale references
# ===========================================================================

PROD_NAME = "kunglao-agent"


def _dual_installs(fake_home):
    skills = fake_home / ".claude" / "skills"
    prod = _install_at(skills, PROD_NAME)
    dev = _install_at(skills, "kunglao-agent-dev")
    return prod, dev


def test_verify_install_references_flags_mixed_state(fake_home, monkeypatch):
    """The verifier sees a MIXED wiring (--project names the OLD install
    root while the script path already points into the NEW one) and says
    so — this state is what register_hooks must fully clean."""
    prod, dev = _dual_installs(fake_home)
    _exec_from(monkeypatch, dev)
    ws = fake_home.parent / "ws-mixed-detect"
    ws.mkdir(parents=True)
    _write_at(prod / "hooks", ws)  # single env_check_gate command -> prod
    result = hook_activation.verify_install_references(ws)
    assert result["ok"] is False
    assert result["stale_total"] >= 1
    assert ".claude/settings.json" in result["stale"]
    assert any(PROD_NAME in r for r in result["stale"][".claude/settings.json"])


def test_mixed_state_rewire_all_commands_at_executing_root(fake_home,
                                                           monkeypatch):
    """AC3 headline: mixed-state workspace (--project OLD + script path NEW)
    re-wired -> ALL 12 commands point at the executing install root AND the
    old-install reference count is 0 (scanner AND raw-substring greps)."""
    prod, dev = _dual_installs(fake_home)
    _exec_from(monkeypatch, dev)
    ws = fake_home.parent / "ws-mixed"
    ws.mkdir(parents=True)
    # seed: half the files point --project prod with script paths in dev;
    # worker_budget rides BOTH slots in the seed to prove slot-local dedupe
    seeded: dict[str, list] = {}
    for event, files in (
            ("PreToolUse", ("env_check_gate.py", "worker_budget.py",
                            "dispatch_gate.py")),
            ("PostToolUse", ("worker_budget.py", "worker_pulse.py")),
            ("Stop", ("completion_gate.py",))):
        entries = [{"matcher": None if event == "Stop" else "Agent",
                    "hooks": [
                        {"type": "command",
                         "command": f"PYTHONUTF8=1 uv run --project {prod.as_posix()} "
                                    f"{(dev / 'hooks' / f).as_posix()}"}]}
                   for f in files]
        seeded[event] = [{k: v for k, v in e.items() if v is not None}
                         for e in entries]
    target = ws / ".claude" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"hooks": seeded}), encoding="utf-8")
    assert hook_activation.verify_install_references(ws)["ok"] is False

    hook_activation.register_hooks(workspace=ws)

    cmds = _commands(target)
    assert len(cmds) == WIRE_UP_ENTRIES, cmds
    for c in cmds:
        assert c.startswith(f"PYTHONUTF8=1 uv run --project {dev.as_posix()} "), c
        assert f"{(dev / 'hooks').as_posix()}/" in c, c
        assert f"{prod.as_posix()}/" not in f"{c}/".replace(
            f"{prod.as_posix()}-", ""), c  # slash-guarded containment
    blob = target.read_text(encoding="utf-8")
    import install_reference  # noqa: E402
    assert install_reference.ref_count(blob, PROD_NAME) == 0
    assert f"/skills/{PROD_NAME}/" not in blob
    verdict = hook_activation.verify_install_references(ws)
    assert verdict["ok"] is True, verdict


def test_v012_state_rewire_zero_stale_references(fake_home, monkeypatch):
    """Full v0.1.2-state workspace (bare-python legacy entries rooted at the
    production install): one re-wire upgrades every touched slot and leaves
    zero references to the old install anywhere in the file."""
    prod, dev = _dual_installs(fake_home)
    _exec_from(monkeypatch, dev)
    ws = fake_home.parent / "ws-v012"
    ws.mkdir(parents=True)

    def py(hook_file: str) -> dict:
        return {"type": "command",
                "command": f"python {(prod / 'hooks' / hook_file).as_posix()}"}

    legacy = {"hooks": {
        "PreToolUse": [{"matcher": "Agent",
                        "hooks": [py(f) for f in ("env_check_gate.py",
                                                  "worker_budget.py",
                                                  "dispatch_gate.py",
                                                  "recall_inject.py")]},
                       {"matcher": "Bash",
                        "hooks": [py("heartbeat_touch.py")]}],
        "PostToolUse": [{"matcher": "Agent",
                         "hooks": [py(f) for f in ("worker_budget.py",
                                                   "worker_pulse.py",
                                                   "state_anchor.py")]}],
        "Stop": [{"hooks": [py("completion_gate.py")]}],
    }}
    target = ws / ".claude" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(legacy), encoding="utf-8")

    hook_activation.register_hooks(workspace=ws)

    blob = target.read_text(encoding="utf-8")
    assert "python " not in blob.replace("python -", "") or \
        PROD_NAME not in blob, "legacy python entries must be replaced"
    assert f"/skills/{PROD_NAME}/" not in blob
    import install_reference  # noqa: E402
    assert install_reference.ref_count(blob, PROD_NAME) == 0
    cmds = _commands(target)
    assert len(cmds) == WIRE_UP_ENTRIES
    assert hook_activation.verify_install_references(ws)["ok"] is True


def test_tilde_claude_md_refs_scanned_and_verifiable(fake_home, monkeypatch):
    """CLAUDE.md carries '~/.claude/skills/<name>/' references (the init
    template face): the scanner reads BOTH prefix classes and the verifier
    reports per-carrier."""
    prod, dev = _dual_installs(fake_home)
    ws = fake_home.parent / "ws-md"
    ws.mkdir(parents=True)
    (ws / "CLAUDE.md").write_text(
        "# ws\nrun `~/.claude/skills/kunglao-agent/scripts/env_check.py .`\n"
        "and `/some/other/.claude/skills/kunglao-agent-dev/tools/x`\nkeep\n",
        encoding="utf-8")
    result = hook_activation.verify_install_references(ws, active_root=dev)
    assert result["ok"] is False
    refs = result["stale"]["CLAUDE.md"]
    # span ends AT the install-name token (the slash stays with whatever
    # follows in the carrier text)
    assert any(r == "~/.claude/skills/kunglao-agent" for r in refs), refs
    # the OTHER active-name reference is NOT stale
    assert not any("kunglao-agent-dev" in r for r in refs)


# ===========================================================================
# AC4 (D6) — kunglao_upgrade end-step install-reference sweep
# ===========================================================================

import importlib.util  # noqa: E402

UG_PATH = SCRIPTS / "kunglao_upgrade.py"


def _load_up():
    spec = importlib.util.spec_from_file_location("kunglao_upgrade", UG_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kunglao_upgrade"] = mod
    spec.loader.exec_module(mod)
    return mod


def _SKILLS_TMP(tmp_path: Path) -> Path:
    """Skills tree for simulated installs — OUTSIDE the workspace so the
    carrier scan never walks it."""
    skills = tmp_path / "skills-tree" / ".claude" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    return skills


# NOTE: installs seeded via _SKILLS_TMP are PATH-shaped fakes for carrier
# seeding; the EXECUTING dev install is created under the redirected home
# by _dev_exec (the durable predicate resolves against Path.home()).


def _dev_exec(monkeypatch, tmp_path: Path) -> Path:
    """Execute-from the dev co-install under _SKILLS_TMP with HOME pointed
    at a tmp fake (the #752 durable predicate keys on
    <HOME>/.claude/skills — without the home redirect this machine's real
    production install would classify every tmp install as ephemeral)."""
    home = tmp_path / "fake-home"
    (home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)
    dev = _install_at(home / ".claude" / "skills", "kunglao-agent-dev")
    monkeypatch.setattr(hook_activation, "__file__",
                        str(dev / "scripts" / "hook_activation.py"))
    return dev


def _seed_stale_carriers(ws: Path, prod: Path) -> None:
    target = ws / ".claude" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"matcher": "Agent", "hooks": [
        {"type": "command",
         "command": f"PYTHONUTF8=1 uv run --project {prod.as_posix()} "
                    f"{(prod / 'hooks' / f).as_posix()}"}]}
        for f in ("env_check_gate.py", "worker_budget.py")]
    target.write_text(json.dumps({"hooks": {"PreToolUse": entries}}),
                      encoding="utf-8")
    (ws / "CLAUDE.md").write_text(
        "# w\nrun `~/.claude/skills/kunglao-agent/scripts/env_check.py .`\n"
        f"alt `/opt/.claude/skills/kunglao-agent/hooks/x`\n",
        encoding="utf-8")


def _make_ws(tmp_path: Path, name: str, stamp_version: str | None) -> Path:
    """read_workspace_version reads ONLY the CLAUDE.md stamp (#536 primary
    carrier) — seed carriers + that stamp in one place."""
    prod = _install_at(_SKILLS_TMP(tmp_path), PROD_NAME)
    ws = tmp_path / name
    ws.mkdir()
    _seed_stale_carriers(ws, prod)
    if stamp_version:
        md_path = ws / "CLAUDE.md"
        md_path.write_text(
            f"# kunglao_template_version: {stamp_version}\n"
            + md_path.read_text(encoding="utf-8"), encoding="utf-8")
    body = f"# kunglao_template_version: {stamp_version}\nclaims: []\n" \
        if stamp_version else "claims: []\n"
    (ws / "claim-register.yaml").write_text(body, encoding="utf-8")
    return ws


def _strip_dev(text: str) -> str:
    return text.replace("kunglao-agent-dev", "")


def test_upgrade_rewires_stale_refs_and_reports(tmp_path, monkeypatch,
                                                capsys):
    """Migration-path upgrade ends with an install-reference sweep: every
    stale reference is reported on stderr AND rewritten to the executing
    (dev co-) install; exit code untouched."""
    up = _load_up()
    dev = _dev_exec(monkeypatch, tmp_path)
    ws = _make_ws(tmp_path, "ws", "0.1.2")

    rc = up.main([str(ws)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "install-reference" in err, err
    assert "CLAUDE.md" in err
    settings_after = (ws / ".claude" / "settings.json").read_text(
        encoding="utf-8")
    assert "/kunglao-agent/" not in _strip_dev(settings_after)
    assert f"{dev.as_posix()}/hooks" in settings_after
    md = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"~/.claude/skills/{dev.name}" in md
    assert "~/.claude/skills/kunglao-agent/" not in md.replace(
        f"skills/{dev.name}", "")
    verdict = hook_activation.verify_install_references(ws)
    assert verdict["ok"] is True, verdict


def test_already_current_still_sweeps(tmp_path, monkeypatch, capsys):
    """The affected population stamps CURRENT (mis-wired by a pre-fix tool):
    the early-return fast path must sweep too, never skip."""
    import template_version  # noqa: E402
    cur = template_version.read_skill_version()
    up = _load_up()
    _dev_exec(monkeypatch, tmp_path)
    ws = _make_ws(tmp_path, "ws-cur", cur)
    rc = up.main([str(ws)])
    out = capsys.readouterr()
    assert rc == 0
    assert "already" in out.out.lower()
    settings_after = (ws / ".claude" / "settings.json").read_text(
        encoding="utf-8")
    assert "/kunglao-agent/" not in _strip_dev(settings_after)


def test_dry_run_lists_sweep_but_writes_nothing(tmp_path, monkeypatch,
                                                capsys):
    up = _load_up()
    _dev_exec(monkeypatch, tmp_path)
    ws = _make_ws(tmp_path, "ws-dry", "0.1.2")
    before = {p: p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    rc = up.main([str(ws), "--dry-run"])
    assert rc == 0
    assert "install_reference_scan" in capsys.readouterr().out
    after = {p: p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    assert before == after, "dry-run must not write a single byte"


def test_clean_workspace_gets_no_sweep_noise(tmp_path, monkeypatch, capsys):
    import template_version  # noqa: E402
    cur = template_version.read_skill_version()
    up = _load_up()
    _dev_exec(monkeypatch, tmp_path)
    ws = tmp_path / "ws-clean"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text(
        f"# kunglao_template_version: {cur}\n"
        "# c\nskill at ~/.claude/skills/kunglao-agent-dev\n",
        encoding="utf-8")
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        f"# kunglao_template_version: {cur}\nclaims: []\n", encoding="utf-8")
    pre_md = (ws / "CLAUDE.md").read_bytes()
    assert up.main([str(ws)]) == 0
    captured = capsys.readouterr()
    assert "install-reference" not in captured.err
    assert (ws / "CLAUDE.md").read_bytes() == pre_md


# ===========================================================================
# scope-addition (issue #752 comments) — sweep rename-invariance + sys.path
# ===========================================================================

def test_upgrade_sweep_is_rename_invariant(tmp_path, monkeypatch):
    """Run the whole upgrade face as an oddly-named durable install: every
    rewritten reference lands on THAT name — no 'kunglao-agent' literal may
    appear anywhere in swept artifacts."""
    import template_version  # noqa: E402
    cur = template_version.read_skill_version()
    up = _load_up()
    home = tmp_path / "fake-home"
    (home / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)
    odd = _install_at(home / ".claude" / "skills", "build-xyz-9")
    monkeypatch.setattr(hook_activation, "__file__",
                        str(odd / "scripts" / "hook_activation.py"))
    ws = tmp_path / "ws-odd"
    ws.mkdir()
    prod = _install_at(home / ".claude" / "skills", PROD_NAME)
    _seed_stale_carriers(ws, prod)
    ws_annex = tmp_path / "carriers-late"
    ws_annex.mkdir()
    (ws / "CLAUDE.md").write_text(
        f"# kunglao_template_version: {cur}\n"
        "# w\nsee `~/.claude/skills/kunglao-agent/scripts/tool.py`\n",
        encoding="utf-8")
    (ws / ".claude").mkdir(exist_ok=True)
    (ws / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}),
                                                  encoding="utf-8")
    rc = up.main([str(ws)])
    assert rc == 0
    md = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "kunglao-agent/" not in md.replace("build-xyz-9", ""), md
    assert f"skills/{odd.name}" in md


def test_syspath_multi_install_self_root_resolves_first(tmp_path,
                                                        monkeypatch):
    """Scope-addition #4 (on top of #671 _path_hygiene): with ANOTHER
    install's scripts dir already ahead on sys.path, the #568-faithful
    move-to-front bootstrap must put THIS install's root at [0] so shared
    module names (worker_budget_core et al.) always resolve to the self
    install — the multi-install coexistence guarantee behind the whole
    teleport fix."""
    home = tmp_path / "fake-home"
    skills = home / ".claude" / "skills"
    skills.mkdir(parents=True)
    old = _install_at(skills, PROD_NAME)
    dev = _install_at(skills, "kunglao-agent-dev")
    probe = "kunglao_syspath_probe_752"
    for pkg in (old, dev):
        (pkg / "scripts" / f"{probe}.py").write_text(
            "# boundary probe: which install resolved me?\n", encoding="utf-8")

    old_scripts, dev_scripts = old / "scripts", dev / "scripts"

    from _path_hygiene import ensure_on_path  # hooks sibling (#671 authority)

    snapshot = list(sys.path)
    sys.modules.pop(probe, None)
    try:
        # a stale tool version left ITS root first in line
        sys.path.insert(0, str(old_scripts))
        assert str(old_scripts) == sys.path[0]
        # this process actually executes from the dev co-install:
        monkeypatch.setattr(hook_activation, "__file__",
                            str(dev / "scripts" / "hook_activation.py"))
        exec_dir = pathlib.Path(hook_activation.__file__).parent
        ensure_on_path(exec_dir, front=True)  # order IS load-bearing here

        assert sys.path[0] == str(dev_scripts), (
            "self install root must be FIRST after move-to-front")
        # resolve through sys.path exactly like a sibling import would:
        resolved = next(p for p in sys.path
                        if (pathlib.Path(p) / f"{probe}.py").is_file())
        assert pathlib.Path(resolved) == dev_scripts, resolved
        assert str(old_scripts) in sys.path, \
            "the other install stays reachable (coexistence), just not first"
    finally:
        sys.path[:] = snapshot
        sys.modules.pop(probe, None)
