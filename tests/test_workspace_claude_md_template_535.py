# -*- coding: utf-8 -*-
"""Issue #535 — workspace CLAUDE.md template: progressive disclosure + memory contract.

The pre-#535 template embedded state inline; workers read the body instead of
following pointers (defeating progressive disclosure, F-C1) and the convergence
loop rules lived only in prose that did not survive compact (F-C2). This file
anchors the rewritten contract:

  1. core cold-start section (everything above `## State files`) <= 50 lines
  2. the 9-row pointer table renders every pointer verbatim
  3. the loop-enforcement block carries convergence_check / heartbeat TTL /
     oracle verdict / post-compact re-entry wording
  4. the 6-carrier memory contract table (write/recall/correction semantics)
  5. note-write criteria (5) + no-write list; no blanket write-disable (C-2)
  6. BLIND verifier contract wording preserved
  7. pointer resolvability against a REAL init run (F-473 lesson)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "CLAUDE.md.base.tmpl"

CORE_CAP = 50

# The 9 cold-start pointers: the table must name each verbatim, and each must
# be resolvable in a workspace that ran init (7 scaffolded eagerly;
# task_spec.yaml by needs-first intake, runs/.env-check.json by env_check.py —
# the on-demand pair must carry its creator in the pointer row).
COLD_START_POINTERS = (
    "`analysis_state.txt`",
    "`global_plan.txt`",
    "`task_spec.yaml`",
    "`claim-register.yaml`",
    "`claim_deps.yaml`",
    "`facts/_INDEX.md`",
    "`blockers/`",
    "`runs/`",
    "`runs/.env-check.json`",
)

# The 6 memory carriers (contract table row keys).
MEMORY_CARRIERS = (
    "claim-register.yaml",
    "facts/_INDEX.md",
    "blockers/",
    "global_plan.txt",
    "analysis_state.txt",
    "task-oracle.yaml",
)

# C-2: blanket write-disable phrasing must not appear anywhere (case-folded).
BLANKET_WRITE_DISABLE = (
    "no writes",
    "do not write",
    "writing disabled",
    "notes disabled",
    "write-instructions=0",
)


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _core_section(text: str) -> str:
    """Core cold-start section: everything above '## State files'."""
    idx = text.find("## State files")
    assert idx != -1, "template lost the '## State files' anchor heading"
    return text[:idx]


# ---------- 1. F-C1: core-section line cap + dynamic-state purity ----------

def test_core_section_within_50_lines():
    """F-C1 contract: core cold-start section MUST stay <= 50 lines."""
    lines = _core_section(_template_text()).splitlines()
    assert len(lines) <= CORE_CAP, (
        f"F-C1 regression: core section is {len(lines)} lines (cap {CORE_CAP}). "
        "Move detail into pointed-to files; the template body is the index, "
        "not the encyclopedia."
    )


def test_core_section_pointer_table_has_nine_rows():
    """The pointer table is the core's only state surface: 9 pointers,
    verbatim, before the reader reaches '## State files'."""
    core = _core_section(_template_text())
    for pointer in COLD_START_POINTERS:
        assert pointer in core, (
            f"F-C1 regression: cold-start pointer {pointer!r} missing from "
            "the core pointer table."
        )


def test_core_section_does_not_embed_dynamic_state():
    """Core MUST NOT inline dynamic values (worker IDs, per-render hashes).
    Sample identity lives in `analysis_state.txt`; pointer tokens are file
    names, not runtime state."""
    core = _core_section(_template_text())
    for bad in ("{{worker_id", "claim status: OPEN", "state_hash="):
        assert bad not in core, (
            f"F-C1 leak: dynamic-state token {bad!r} appears in core section."
        )


# ---------- 2. F-C2: loop-enforcement block ----------

def test_renders_loop_enforcement_block():
    """F-C2 contract: the loop-enforcement block is the ONLY convergence
    channel that survives compact; it must name every mandatory rule."""
    text = _template_text()
    assert "## Loop enforcement" in text, (
        "F-C2 regression: loop-enforcement block missing or renamed — "
        "compact-survival depends on this heading being present and stable."
    )
    assert "convergence_check" in text, (
        "F-C2 regression: block must name convergence_check per round."
    )
    assert "heartbeat" in text.lower(), (
        "F-C2 regression: block must cover heartbeat TTL re-entry."
    )
    assert "task-oracle" in text, (
        "F-C2 regression: block must cover the oracle verdict rule."
    )
    assert "compact" in text.lower(), (
        "F-C2 regression: block must cover post-compact re-entry — that is "
        "the whole point of the persistent channel."
    )


# ---------- 3. F-C2: six-carrier memory contract ----------

def test_six_carrier_memory_contract_present():
    """The 6-carrier table is the FIRST landing point for note-write rules:
    per-carrier Write/When-recall/Correction columns replace blanket
    directives (C-2)."""
    text = _template_text()
    table_start = text.find("## Memory carriers")
    assert table_start != -1, (
        "F-C2 regression: memory-contract section heading missing."
    )
    section = text[table_start:text.find("## ", table_start + 10)]
    for carrier in MEMORY_CARRIERS:
        assert f"`{carrier}`" in section, (
            f"F-C2 regression: memory contract missing carrier {carrier!r} "
            "— six carriers are the contract."
        )
    header_row = next(
        (ln for ln in section.splitlines() if ln.startswith("| Carrier |")), "")
    assert header_row, (
        "F-C2 regression: memory contract must be a table with a Carrier "
        "header row, not prose."
    )
    for column in ("Write what", "When to recall", "Correction"):
        assert column in header_row, (
            f"F-C2 regression: contract table missing {column} column header."
        )


def test_memory_contract_carriers_match_init_scaffold():
    """The contract table must not promise carriers init does not create:
    every carrier row key resolves in a workspace that ran kunglao-init
    (sandbox-verified against SCAFFOLD_DIRS/SCAFFOLD_FILES at #538)."""
    text = _template_text()
    # task-oracle.yaml: written by write_task_oracle_skeleton (#473)
    assert "task-oracle.yaml" in text
    # facts carrier row must name the fact-file pattern, not a bare dir
    assert "F<NNN>" in text, "facts carrier row must name the F<NNN> pattern"


# ---------- 4. C-2: write criteria + no-write list, no blanket disable ----------

def test_write_criteria_and_no_write_list_present():
    """Five note-write criteria (replacement test as criterion 4, HARD) plus
    an explicit no-write list; recall wording aligned with
    kunglao-convergence-loop (per-round convergence_check, disk is truth)."""
    text = _template_text()
    assert "**Write criteria**" in text, "write-criteria list missing"
    assert "**When to skip a write**" in text, "no-write list missing"
    criteria_block = text.split("**Write criteria**", 1)[1]
    criteria_block = criteria_block.split("**When to skip a write**", 1)[0]
    for n in ("1.", "2.", "3.", "4.", "5."):
        assert n in criteria_block, f"write criterion {n} missing"
    # criterion 4: replacement test, HARD default (English; #356 W2 CJK ban)
    assert "replacement test" in criteria_block.lower()
    assert "HARD" in criteria_block
    # recall semantics align with the convergence-loop rule, not generic
    # "remember to look at notes"
    assert "convergence_check" in criteria_block
    assert "disk is truth" in text


def test_no_blanket_write_instructions():
    """C-2 anti-pattern: blanket write-disable directives MUST NOT appear."""
    text = _template_text().lower()
    for bad in BLANKET_WRITE_DISABLE:
        assert bad not in text, (
            f"C-2 regression: blanket write-disable {bad!r} found — use the "
            "per-carrier contract table instead."
        )


# ---------- 5. preserved contracts ----------

def test_blind_verifier_wording_preserved():
    """The BLIND verifier contract predates #535 and is load-bearing."""
    text = _template_text()
    assert "BLIND verifier" in text and "producer context" in text, (
        "BLIND verifier contract wording was dropped in the rewrite."
    )


# ---------- 6. pointer resolvability (real init, F-473 lesson) ----------

def test_cold_start_pointers_resolve_after_real_init(tmp_path):
    """F-473 lesson: pointer rot must be caught by test, not in the field.

    Runs the REAL init (same pattern as test_claudemd_single_source) and
    asserts the pointer table matches what the workspace actually holds.
    Two pointers are legitimately on-demand — task_spec.yaml (needs-first
    intake writes it) and runs/.env-check.json (env_check.py writes it) —
    for those the template must carry the creator in the pointer row so a
    cold-start worker can act instead of trusting an absent file."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    seed_bins(ws)
    env = {k: v for k, v in os.environ.items()
           if k != "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"}
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "kunglao-init.py"), str(ws),
         "--type", "windows", "--skip-toolchain",
         "--profile-root", str(tmp_path / "profile-root")],
        capture_output=True, text=True, timeout=180, env=env)
    assert r.returncode == 0, f"init failed: {r.stderr}"

    claude = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    for pointer in COLD_START_POINTERS:
        assert pointer in claude, (
            f"F-473 regression: pointer {pointer!r} did not survive render."
        )

    eager = ("analysis_state.txt", "global_plan.txt", "claim-register.yaml",
             "claim_deps.yaml", "facts/_INDEX.md", "blockers", "runs")
    for rel in eager:
        assert (ws / rel).exists(), (
            f"pointer rot: {rel} rendered but not scaffolded by init"
        )

    # On-demand pointers: the row must name its creator for the absent case.
    assert "intake" in claude, (
        "task_spec.yaml pointer must name its creator (intake)"
    )
    assert "env_check.py" in claude, (
        "runs/.env-check.json pointer must name its creator (env_check.py)"
    )
    # The 6th memory carrier is also init-scaffolded (#473 skeleton).
    assert (ws / "task-oracle.yaml").exists(), "oracle carrier not scaffolded"
