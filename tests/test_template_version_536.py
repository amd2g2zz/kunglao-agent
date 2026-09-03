# -*- coding: utf-8 -*-
"""#536 version stamp: writer + verifier + upgrade cross-check.

Three carriers must stay in sync (CLAUDE.md, facts/_INDEX.md,
claim-register.yaml). The verifier returns per-carrier faults; the comment
line form is part of the contract (YAML-legal, update_index-stable).
Version authority = pyproject.toml (receipt-checked pair), NOT a third file.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import template_version as tv  # noqa: E402
from _factories import seed_bins


def test_skill_version_is_semver_and_matches_pyproject() -> None:
    v = tv.read_skill_version()
    parts = v.split(".")
    assert len(parts) == 3, f"{v!r} is not semver"
    assert all(p.isdigit() for p in parts), f"{v!r} is not numeric semver"
    # single source: pyproject [project].version (release_receipt agreement)
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{v}"' in text


def test_stamp_line_is_yaml_comment_form() -> None:
    # comment form is load-bearing: legal YAML + update_index preserves `#`
    assert tv.stamp_line("0.1.2").startswith("# ")
    assert tv.STAMP_KEY in tv.stamp_line("0.1.2")


def test_stamp_writer_marks_all_three_locations(tmp_path: Path) -> None:
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# workspace\n", encoding="utf-8")
    written = tv.stamp_workspace(tmp_path, version="0.1.2")
    assert set(written) == {"CLAUDE.md", "facts/_INDEX.md", "claim-register.yaml"}
    assert tv.stamp_line("0.1.2") in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert tv.stamp_line("0.1.2") in (tmp_path / "facts" / "_INDEX.md").read_text(encoding="utf-8")
    assert tv.stamp_line("0.1.2") in (tmp_path / "claim-register.yaml").read_text(encoding="utf-8")


def test_stamp_writer_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# workspace\n", encoding="utf-8")
    tv.stamp_workspace(tmp_path, version="0.1.2")
    assert tv.stamp_workspace(tmp_path, version="0.1.2") == []
    # refresh replaces in place, never stacks
    tv.stamp_workspace(tmp_path, version="0.1.3")
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.count(tv.STAMP_KEY) == 1
    assert tv.stamp_line("0.1.3") in claude


def test_stamp_writer_skips_missing_files(tmp_path: Path) -> None:
    # init owns scaffolding — stamp_workspace never creates carriers
    (tmp_path / "CLAUDE.md").write_text("# ws\n", encoding="utf-8")
    written = tv.stamp_workspace(tmp_path, version="0.1.2")
    assert written == ["CLAUDE.md"]


def test_verify_detects_missing_stamp(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# no stamp\n", encoding="utf-8")
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    faults = tv.verify_stamps(tmp_path, expected="0.1.2")
    assert faults == {"CLAUDE.md": "missing",
                      "facts/_INDEX.md": "missing",
                      "claim-register.yaml": "missing"}


def test_verify_detects_mismatch(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(tv.stamp_line("0.0.1") + "\n", encoding="utf-8")
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "_INDEX.md").write_text(tv.stamp_line("0.1.2") + "\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(tv.stamp_line("0.1.2") + "\n", encoding="utf-8")
    faults = tv.verify_stamps(tmp_path, expected="0.1.2")
    assert faults == {"CLAUDE.md": "mismatch:0.0.1"}


def test_verify_clean_when_stamped(tmp_path: Path) -> None:
    tv.stamp_workspace(tmp_path, version="0.1.2")  # no carriers exist → noop
    (tmp_path / "CLAUDE.md").write_text(tv.stamp_line("0.1.2") + "\n", encoding="utf-8")
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "_INDEX.md").write_text(tv.stamp_line("0.1.2") + "\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(tv.stamp_line("0.1.2") + "\nclaims: []\n", encoding="utf-8")
    assert tv.verify_stamps(tmp_path, expected="0.1.2") == {}


def test_stamp_line_survives_update_index_rewrite(tmp_path: Path) -> None:
    """update_index._write preserves `#` comments — the stamp must survive a
    row upsert without being duplicated."""
    sys.path.insert(0, str(ROOT / "tools" / "_lib"))
    import update_index  # scripts on path above
    idx = tmp_path / "_INDEX.md"
    idx.write_text(tv.stamp_line("0.1.2") + "\n# _INDEX\n", encoding="utf-8")
    update_index.upsert(idx, "F-1", "OPEN", "C-1", "first fact")
    text = idx.read_text(encoding="utf-8")
    assert tv.STAMP_RE.search(text), "stamp lost on update_index rewrite"
    m = tv.STAMP_RE.search(text)
    assert m and m.group(1) == "0.1.2"


def test_upgrade_warning_behind(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(tv.stamp_line("0.1.0") + "\n", encoding="utf-8")
    msg = tv.upgrade_warning(tmp_path, skill_version="0.2.0")
    assert msg is not None and "0.1.0" in msg and "0.2.0" in msg


def test_upgrade_warning_silent_when_equal_or_newer(tmp_path: Path) -> None:
    for ws_v in ("0.2.0", "0.3.0"):
        (tmp_path / "CLAUDE.md").write_text(tv.stamp_line(ws_v) + "\n", encoding="utf-8")
        assert tv.upgrade_warning(tmp_path, skill_version="0.2.0") is None


def test_upgrade_warning_silent_without_stamp(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# no stamp\n", encoding="utf-8")
    assert tv.upgrade_warning(tmp_path, skill_version="0.2.0") is None


# =====================================================================
# end-to-end: a real init run stamps all three carriers, no state drift
# =====================================================================

def _load_init():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_536", ROOT / "scripts" / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_init_stamps_all_three_carriers(tmp_path: Path) -> None:
    """Umbrella rule: init WRITES. A real CLI run lands the stamp on
    CLAUDE.md / facts/_INDEX.md / claim-register.yaml, and the recorded
    state_hash still matches (the stamp is inside the hashed content from
    the start — no spurious drift WARNING on the next resume)."""
    import os
    import subprocess
    ws = tmp_path / "ws"
    seed_bins(ws, payload=b"MZ\x90\x00" + b"\x00" * 64)
    env = {k: v for k, v in os.environ.items()
           if k != "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"}
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "kunglao-init.py"), str(ws),
         "--skip-toolchain", "--host-exec-protection", "enabled", "--type", "windows", "--no-mcp", "--no-hooks",
         "--profile-root", str(tmp_path / "profile-root")],
        capture_output=True, text=True, timeout=120, env=env,
        errors="replace")
    assert r.returncode == 0, f"init failed: {r.stderr}"
    v = tv.read_skill_version()
    for rel in ("CLAUDE.md", "facts/_INDEX.md", "claim-register.yaml"):
        text = (ws / rel).read_text(encoding="utf-8")
        assert tv.stamp_line(v) in text, f"{rel} missing the stamp:\n{text[:200]}"
    assert tv.verify_stamps(ws) == {}
    # state_hash self-consistency: recorded marker hash == recomputed
    reg_text = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    init_mod = _load_init()
    recorded = init_mod.extract_hash(reg_text)
    assert recorded is not None
    assert init_mod.compute_state_hash(ws) == recorded, \
        "stamp introduction drifted the state_hash (resume would WARN)"
    # the register stays YAML-parseable with the stamp comment
    import yaml
    data = yaml.safe_load(reg_text)
    assert isinstance(data.get("claims"), list) and len(data["claims"]) >= 3

