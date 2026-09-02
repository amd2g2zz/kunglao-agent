# -*- coding: utf-8 -*-
"""tests/test_workspace_carriers_538.py — issue #538 carrier-contract locks.

Three anchored surfaces:

1. docs/workspace-manifest.md exists and enumerates the audit carrier set
   (item 1: the carrier table cannot drift from the implemented set without
   this failing).
2. scripts/kunglao-init.py SCAFFOLD_DIRS covers every contract DIRECTORY row
   (items 1+3: eager scaffold; runs/logs/ included per C-3) and ships a
   self-describing stub per agent-facing carrier (notes/ analyses/
   evidence/ hypotheses/ scratch/).
3. task_spec_snapshot.yaml is gone from the scaffold (item 4, C-4): the
   forever-3B stub misled handoff; resume (#466) handles absence.

Also locks the #530 tombstones this branch must not resurrect
(failure-registry.yaml stays out; progress.txt stays out of SCAFFOLD_FILES).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "workspace-manifest.md"
SCRIPTS = ROOT / "scripts"
INIT = SCRIPTS / "kunglao-init.py"

# Every directory row of the carrier contract (docs/workspace-manifest.md).
CONTRACT_DIRS = (
    "facts",
    "notes",
    "analyses",
    "evidence",
    "blockers",
    "runs",
    "runs/logs",
    "hypotheses",
    "scratch",
)

# Every agent-facing carrier that must ship a self-describing stub ("this
# file was created by init; <carrier> is for ..."). hypotheses/ ships a stub
# NOW (#528 has not landed); when #528 lands its writer takes over and the
# stub text is #528's to own.
STUB_CARRIERS = ("notes", "analyses", "evidence", "hypotheses", "scratch")


def _load_init():
    name = "kunglao_init_538"
    if name in sys.modules:
        return sys.modules[name]
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, INIT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# =====================================================================
# 1 — the contract doc
# =====================================================================

def test_workspace_manifest_doc_exists():
    assert DOC.is_file(), (
        f"{DOC} missing; create the carrier-contract doc per #538 item 1")


def test_workspace_manifest_doc_lists_carriers():
    text = DOC.read_text(encoding="utf-8")
    required = list(CONTRACT_DIRS) + [
        "claim-register.yaml",
        "facts/_INDEX.md",
        ".workspace-manifest.json",
    ]
    # Carrier rows carry the trailing-slash dir form (`facts/`) in the doc.
    missing = [r for r in required
               if f"`{r}/`" not in text and f"`{r}`" not in text]
    assert not missing, f"workspace-manifest.md missing carrier rows: {missing}"


# =====================================================================
# 2 — eager scaffold (SCAFFOLD_DIRS is the single source in init)
# =====================================================================

def test_scaffold_dirs_covers_every_contract_dir():
    mod = _load_init()
    missing = [d for d in CONTRACT_DIRS if d not in mod.SCAFFOLD_DIRS]
    assert not missing, (
        f"SCAFFOLD_DIRS missing contract rows: {missing} "
        f"(current: {mod.SCAFFOLD_DIRS}). Per #538 item 1/3 every docs/"
        "workspace-manifest.md directory row must be eagerly scaffolded.")


def test_scaffold_dirs_no_stray_dirs():
    mod = _load_init()
    stray = [d for d in mod.SCAFFOLD_DIRS if d not in CONTRACT_DIRS]
    assert not stray, (
        f"SCAFFOLD_DIRS carries non-contract rows: {stray} — add them to "
        "docs/workspace-manifest.md first (the doc is the contract).")


def _run_init_cli(ws: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in __import__("os").environ.items()
           if k != "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"}
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(INIT), str(ws), "--skip-toolchain",
         "--type", "windows", "--no-mcp", "--no-hooks",
         "--profile-root", str(tmp_path / "profile-root")],
        capture_output=True, text=True, timeout=120, env=env, errors="replace")


def test_init_creates_every_contract_dir(tmp_path):
    """End-to-end: a real init run materializes every contract directory."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    seed_bins(ws)
    r = _run_init_cli(ws, tmp_path)
    assert r.returncode == 0, f"init failed: {r.stderr}"
    missing = [d for d in CONTRACT_DIRS if not (ws / d).is_dir()]
    assert not missing, f"init did not eagerly scaffold: {missing}"


def test_agent_facing_carriers_ship_self_describing_stubs(tmp_path):
    """Each agent-facing carrier carries a README explaining what it is for
    (the self-describing stub, #538 item 1)."""
    mod = _load_init()
    stubs = getattr(mod, "CARRIER_READMES", None)
    assert stubs, "kunglao-init.py missing CARRIER_READMES (the stub table)"
    for carrier in STUB_CARRIERS:
        assert carrier in stubs, (
            f"CARRIER_READMES missing stub for {carrier!r} "
            f"(present: {sorted(stubs)})")
    ws = tmp_path / "ws"
    ws.mkdir()
    mod.scaffold(ws)
    for carrier in STUB_CARRIERS:
        readme = ws / carrier / "README.md"
        assert readme.is_file(), f"{carrier}/README.md stub missing post-scaffold"


def test_scratch_stub_declares_free_zone():
    """C-5: scratch/README.md must declare the free-zone semantics."""
    mod = _load_init()
    text = mod.CARRIER_READMES["scratch"]
    assert "free-zone" in text, (
        "scratch/ stub must declare itself the free-zone (non-contract "
        "artifacts) per #538 item 6")


def test_init_idempotent_reinit_preserves_user_carriers(tmp_path):
    """Umbrella #9 hard rule: re-init must not destroy user data. A note a
    worker wrote into notes/ and an evidence artifact must survive a re-run
    of the scaffold function (stub files never clobber non-empty ones)."""
    mod = _load_init()
    ws = tmp_path / "ws"
    ws.mkdir()
    mod.scaffold(ws)
    note = ws / "notes" / "n1.md"
    note.write_text(
        "---\nid: n1\nclaim_id: C-001\nverify_status: passes\n---\n",
        encoding="utf-8")
    cap = ws / "evidence" / "capture.txt"
    cap.write_text("raw evidence\n", encoding="utf-8")
    mod.scaffold(ws)  # re-init
    assert note.read_text(encoding="utf-8").startswith("---"), \
        "re-scaffold clobbered a user note (idempotency violation, #9)"
    assert cap.read_text(encoding="utf-8") == "raw evidence\n", \
        "re-scaffold clobbered evidence content (idempotency violation, #9)"


# =====================================================================
# 3 — workspace manifest writer (#538 item 2, consumed by kunglao-resume #466)
# =====================================================================

MANIFEST_LIB = ROOT / "tools" / "_lib" / "workspace_manifest.py"


def _load_manifest_module():
    name = "workspace_manifest_538"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, MANIFEST_LIB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_manifest_lib_exists_and_writes(tmp_path):
    assert MANIFEST_LIB.is_file(), (
        f"{MANIFEST_LIB} missing; #538 item 2 (resume diff source)")
    mod = _load_manifest_module()
    out = mod.write_manifest(tmp_path)
    assert out.is_file(), "manifest file not written"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_rev"] == "v1"
    paths = {c["path"] for c in data["carriers"]}
    for d in CONTRACT_DIRS:
        assert d in paths, f"manifest carriers missing {d!r}"
    assert mod.read_manifest(out)["schema_rev"] == "v1"


def test_manifest_diff_reports_missing(tmp_path):
    mod = _load_manifest_module()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes").mkdir()          # carrier present at snapshot time
    (ws / "scratch").mkdir()
    mod.write_manifest(ws)
    shutil.rmtree(ws / "notes")     # carrier lost post-init (#466 case)
    snap = mod.read_manifest(ws / mod.MANIFEST_NAME)
    diff = mod.diff_manifest(ws, snap)
    assert diff["missing"] == ["notes"], f"diff missed notes/: {diff}"


def test_manifest_scratch_drift_is_informational(tmp_path):
    """scratch/ is free-zone: its disappearance is reported under
    free_zone_missing, NOT as a contract-missing alarm."""
    mod = _load_manifest_module()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "scratch").mkdir()
    mod.write_manifest(ws)
    shutil.rmtree(ws / "scratch")
    snap = mod.read_manifest(ws / mod.MANIFEST_NAME)
    diff = mod.diff_manifest(ws, snap)
    assert diff["free_zone_missing"] == ["scratch"], diff
    assert diff["missing"] == [], diff


def test_scaffold_writes_manifest(tmp_path):
    """init's scaffold phase writes the manifest (resume consumes it)."""
    mod = _load_init()
    ws = tmp_path / "ws"
    ws.mkdir()
    mod.scaffold(ws)
    assert (ws / ".workspace-manifest.json").is_file(), (
        "scaffold did not write .workspace-manifest.json (#538 item 2)")


# =====================================================================
# 4 — task_spec_snapshot.yaml stub deleted (C-4)
# =====================================================================

def test_task_spec_snapshot_stub_removed():
    mod = _load_init()
    assert "task_spec_snapshot.yaml" not in mod.SCAFFOLD_FILES, (
        "SCAFFOLD_FILES still seeds task_spec_snapshot.yaml — the forever-3B "
        "stub was deleted per #538 item 4 (resume handles absence)")


def test_task_spec_snapshot_absent_after_scaffold(tmp_path):
    mod = _load_init()
    ws = tmp_path / "ws"
    ws.mkdir()
    mod.scaffold(ws)
    assert not (ws / "task_spec_snapshot.yaml").exists(), (
        "scaffold wrote task_spec_snapshot.yaml; the stub is deleted (#538 item 4)")


# =====================================================================
# 5 — _INDEX single schema + shared parser (W-5)
# =====================================================================

INDEX_SCHEMA_LIB = ROOT / "tools" / "_lib" / "index_schema.py"


def _load_index_schema():
    name = "index_schema_538"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, INDEX_SCHEMA_LIB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_index_schema_module_exists_and_parses():
    assert INDEX_SCHEMA_LIB.is_file(), (
        f"{INDEX_SCHEMA_LIB} missing; #538 item 5 (single shared parser)")
    mod = _load_index_schema()
    rows = mod.parse_index_text("F001 | PROVEN | C-001 | sample is a PE image\n")
    assert rows[0]["fact_id"] == "F001"
    assert rows[0]["status"] == "PROVEN"
    assert rows[0]["claim_id"] == "C-001"


def test_index_schema_rejects_malformed_status():
    """Audit reproducer: status parsed as 'endpoints-and-auth (login path)'
    — the shared parser must reject free-text in the status column."""
    mod = _load_index_schema()
    bad = "F001 | endpoints-and-auth (login path) | C-001 | x\n"
    with pytest.raises(mod.IndexSchemaError):
        mod.parse_index_text(bad)


def test_update_index_uses_shared_parser():
    _load_init()  # ensures scripts/ on sys.path
    import update_index
    assert hasattr(update_index, "parse_index_text"), (
        "update_index.py must re-export the shared parser "
        "(tools/_lib/index_schema.py) per #538 item 5")
    import index_schema  # same module identity as update_index's import
    assert update_index.IndexSchemaError is index_schema.IndexSchemaError, (
        "update_index.IndexSchemaError must be the shared exception class")


def test_update_index_upsert_rejects_malformed_status(tmp_path):
    """Write-side rejection: upsert refuses a non-canonical status so a
    malformed row can never land on disk (item 5 malformed-line write rejection)."""
    _load_init()
    import update_index
    idx = tmp_path / "_INDEX.md"
    with pytest.raises(update_index.IndexSchemaError):
        update_index.upsert(idx, "F001", "endpoints-and-auth (login path)",
                            "C-001", "x")
    assert not idx.exists(), "rejected upsert must not leave a file behind"


def test_digest_build_uses_shared_parser():
    _load_init()
    import digest_build
    import index_schema  # tools/_lib on sys.path via pytest.ini pythonpath
    assert digest_build._INDEX_SCHEMA is index_schema, (
        "digest_build.py not wired to the shared parser"
        "(tools/_lib/index_schema.py)")


def test_digest_build_fact_index_routes_through_shared_parser(tmp_path):
    """digest_build._facts_index parses via the shared parser: a malformed
    row is an error surface, not a silently mis-typed status."""
    _load_init()
    import digest_build
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text(
        "F001 | endpoints-and-auth (login path) | C-001 | x\n",
        encoding="utf-8")
    with pytest.raises(digest_build.IndexSchemaError):
        digest_build._facts_index(ws)


# =====================================================================
# 6 — #530 tombstones stay dead (this branch must not resurrect them)
# =====================================================================

def test_failure_registry_stays_out_of_scaffold():
    mod = _load_init()
    assert "failure-registry.yaml" not in mod.SCAFFOLD_FILES, (
        "#530 deleted the failure-registry.yaml template; init must not "
        "resurrect it")
    assert "progress.txt" not in mod.SCAFFOLD_FILES, (
        "#530 downgraded progress.txt to a human-only log; it is not "
        "scaffold state")
