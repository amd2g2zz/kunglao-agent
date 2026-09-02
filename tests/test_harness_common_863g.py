# -*- coding: utf-8 -*-
"""#863 Family F — utc_now single-source contract (enforcement test).

Before: 53 utc_now-style definition copies across the repo (issue #863
Open question 2: four auditors reported 7/33/50/20 — recounted at base
4caeb44 as 53 definitions in 4 output shapes, see the Family F Recon in
openspec/changes/issue-863-families/proposal.md). After:
``scripts/harness_common.py`` is the ONE time-stamp source:

  * ``utc_now()``     -> tz-aware UTC datetime          (shape A, 8 copies)
  * ``utc_now_z()``   -> "YYYY-MM-DDTHH:MM:SSZ"          (shapes B+C, 43
    copies — strftime and isoformat+replace spellings are byte-equivalent,
    pinned below)
  * ``utc_now_iso()`` -> "YYYY-MM-DDTHH:MM:SS+00:00"     (shape D, 2 copies —
    the one true textual variant, kept)

Mirrors tests/test_ws_layout_delegation_863c.py (Family C shape):
mechanical confinement scan + wiring markers + identity-level delegation
asserts + util contract pins. No pre-existing enforcement existed (issue
table: "enforcement today: none") — nothing to rewrite, everything to pin.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

UTIL_REL = "scripts/harness_common.py"

# Every former copy site -> the util function its shape maps to.
# (the util itself is NOT listed here — it is the definition point)
WIRING = {
    # shape A: tz-aware datetime (utc_now / _utc_now / _utc_now_dt names)
    "scripts/active_intervention.py": "utc_now",
    "scripts/backtrack_gate.py": "utc_now",
    "scripts/claim_expiry.py": "utc_now",
    "scripts/convergence_check.py": "utc_now",
    "scripts/cost_gate.py": "utc_now",
    "scripts/kunglao_resume.py": "utc_now",
    "scripts/kunglao-monitor.py": "utc_now",
    "scripts/progress_report.py": "utc_now",
    # shapes B+C: Z-suffixed second-precision ISO stamp
    "hooks/heartbeat_touch.py": "utc_now_z",
    "scripts/apkid_scanner.py": "utc_now_z",
    "scripts/ask_for_direction_gate.py": "utc_now_z",
    "scripts/backtrack_loop.py": "utc_now_z",
    "scripts/complete_teardown.py": "utc_now_z",
    "scripts/dead_letter.py": "utc_now_z",
    "scripts/dispatch_context.py": "utc_now_z",
    "scripts/env_check.py": "utc_now_z",
    "scripts/env_repair_l1.py": "utc_now_z",
    "scripts/env_state_probe.py": "utc_now_z",
    "scripts/external_kicker.py": "utc_now_z",
    "scripts/feedback.py": "utc_now_z",
    "scripts/heartbeat.py": "utc_now_z",
    "scripts/heartbeat_tick.py": "utc_now_z",
    "scripts/heartbeat_touch.py": "utc_now_z",
    "scripts/hook_activation.py": "utc_now_z",
    "scripts/hooks_selfcheck.py": "utc_now_z",
    "scripts/infeasible_proposal.py": "utc_now_z",
    "scripts/init_state.py": "utc_now_z",
    "scripts/kunglao-init.py": "utc_now_z",
    "scripts/kunglao-monitor.py": "utc_now_z",
    "scripts/kunglao_log.py": "utc_now_z",
    "scripts/kunglao_record.py": "utc_now_z",
    "scripts/kunglao_verify.py": "utc_now_z",
    "scripts/lessons_telemetry.py": "utc_now_z",
    "scripts/loop_scheduler.py": "utc_now_z",
    "scripts/loop_state.py": "utc_now_z",
    "scripts/mechanism_scheduler.py": "utc_now_z",
    "scripts/mission_ledger.py": "utc_now_z",
    "scripts/plan_drift_detector.py": "utc_now_z",
    "scripts/plan_reviser.py": "utc_now_z",
    "scripts/plan_stages.py": "utc_now_z",
    "scripts/provider_health.py": "utc_now_z",
    "scripts/run_test_matrix.py": "utc_now_z",
    "scripts/stale_blocker_prune.py": "utc_now_z",
    "scripts/statusline_snapshot.py": "utc_now_z",
    "scripts/troubleshooting_gate.py": "utc_now_z",
    "scripts/verify_status_watch.py": "utc_now_z",
    "tools/static/apk_mem_gate.py": "utc_now_z",
    "tools/static/baksmali_index.py": "utc_now_z",
    "tools/static/dexdc_scanner.py": "utc_now_z",
    # shape D: +00:00 offset suffix (the true variant, kept)
    "scripts/failure_analysis_gate.py": "utc_now_iso",
    "scripts/outcome_capture.py": "utc_now_iso",
}
# kunglao-monitor.py carries TWO former defs (utc_now -> utc_now_z,
# _utc_now_dt -> utc_now); dict-of-lists for the per-file old-name check.
FORMER_DEF_NAMES = {
    "scripts/active_intervention.py": ["utc_now"],
    "scripts/backtrack_gate.py": ["utc_now"],
    "scripts/claim_expiry.py": ["utc_now"],
    "scripts/convergence_check.py": ["utc_now"],
    "scripts/cost_gate.py": ["utc_now"],
    "scripts/kunglao_resume.py": ["_utc_now"],
    "scripts/kunglao-monitor.py": ["utc_now", "_utc_now_dt"],
    "scripts/progress_report.py": ["utc_now"],
    "hooks/heartbeat_touch.py": ["utc_now"],
    "scripts/apkid_scanner.py": ["_utc_now"],
    "scripts/ask_for_direction_gate.py": ["utc_now"],
    "scripts/backtrack_loop.py": ["utc_now"],
    "scripts/complete_teardown.py": ["utc_now"],
    "scripts/dead_letter.py": ["utc_now_iso"],
    "scripts/dispatch_context.py": ["_utc_now"],
    "scripts/env_check.py": ["utc_now"],
    "scripts/env_repair_l1.py": ["_utc_now"],
    "scripts/env_state_probe.py": ["_utc_now"],
    "scripts/external_kicker.py": ["utc_now"],
    "scripts/feedback.py": ["utc_now"],
    "scripts/heartbeat.py": ["utc_now"],
    "scripts/heartbeat_tick.py": ["utc_now"],
    "scripts/heartbeat_touch.py": ["utc_now"],
    "scripts/hook_activation.py": ["utc_now"],
    "scripts/hooks_selfcheck.py": ["utc_now"],
    "scripts/infeasible_proposal.py": ["utc_now_iso"],
    "scripts/init_state.py": ["_utc_now"],
    "scripts/kunglao-init.py": ["utc_now"],
    "scripts/kunglao_log.py": ["_utc_now"],
    "scripts/kunglao_record.py": ["utc_now"],
    "scripts/kunglao_verify.py": ["utc_now"],
    "scripts/lessons_telemetry.py": ["_utc_now_iso"],
    "scripts/loop_scheduler.py": ["utc_now"],
    "scripts/loop_state.py": ["utc_now"],
    "scripts/mechanism_scheduler.py": ["utc_now"],
    "scripts/mission_ledger.py": ["_utc_now"],
    "scripts/plan_drift_detector.py": ["utc_now"],
    "scripts/plan_reviser.py": ["utc_now"],
    "scripts/plan_stages.py": ["_utc_now"],
    "scripts/provider_health.py": ["_utc_now"],
    "scripts/run_test_matrix.py": ["utc_now"],
    "scripts/stale_blocker_prune.py": ["utc_now"],
    "scripts/statusline_snapshot.py": ["utc_now"],
    "scripts/troubleshooting_gate.py": ["utc_now"],
    "scripts/verify_status_watch.py": ["_utc_now"],
    "tools/static/apk_mem_gate.py": ["_utc_now"],
    "tools/static/baksmali_index.py": ["_utc_now"],
    "tools/static/dexdc_scanner.py": ["_utc_now"],
    "scripts/failure_analysis_gate.py": ["utc_now_iso"],
    "scripts/outcome_capture.py": ["utc_now_iso"],
}
assert set(WIRING) == set(FORMER_DEF_NAMES), "wiring/name tables must cover the same files"

# The recount grep contract (Recon 口径): a utc_now-style def may exist ONLY
# in the util. `def now_utc` is in the issue's grep face and has zero hits.
STYLE_DEF_RE = re.compile(
    r"^def (?:utc_now|_utc_now|now_utc)(?:_iso|_dt)?\(", re.MULTILINE)


def _repo_python_files():
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("tests/"):        # test files may pin/rebuild freely
            continue
        if rel == UTIL_REL:                 # the definition point itself
            continue
        if rel.startswith((".git", ".review", "openspec/", ".worktrees",
                           ".venv/", "venv/", "actions-runner/")):
            continue
        yield p, rel


# --------------------------------------------------------------------------
# confinement: a utc_now-style def may exist ONLY in the util — the
# `datetime.now(timezone.utc)` stamping logic must never reappear as a def
# in a consumer.
# --------------------------------------------------------------------------

def test_utc_now_defs_confined_to_util():
    offenders = {}
    for p, rel in _repo_python_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        hits = STYLE_DEF_RE.findall(text)
        if hits:
            offenders[rel] = hits
    assert offenders == {}, (
        "utc_now-style definitions are confined to " + UTIL_REL +
        " (#863 Family F); offenders: " + repr(offenders))


# --------------------------------------------------------------------------
# wiring: every former copy site imports the canonical util AND no longer
# carries its former `def` (static half; identity half is below).
# --------------------------------------------------------------------------

def test_utc_now_wiring_is_delegated():
    missing = {}
    for rel, fns in FORMER_DEF_NAMES.items():
        path = ROOT / rel
        if not path.exists():
            missing[rel] = "<file gone>"
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "harness_common" not in text:
            missing[rel] = "harness_common import"
            continue
        leftover = [n for n in fns
                    if re.search(r"^def %s\(" % re.escape(n), text, re.M)]
        if leftover:
            missing[rel] = "former def still present: " + ",".join(leftover)
    assert missing == {}, (
        "every former utc_now copy must delegate to " + UTIL_REL +
        " (#863 Family F); missing wiring: " + repr(missing))


# --------------------------------------------------------------------------
# identity-level delegation: imported consumers must bind the util function
# ITSELF (not a wrapper, not a re-implementation). Sample per shape; the
# hyphenated filenames (kunglao-init/kunglao-monitor) and the hooks bridge
# are pinned by the static wiring test above.
# --------------------------------------------------------------------------

def _import(mod_name: str):
    import importlib
    return importlib.import_module(mod_name)


def test_utc_now_alias_identity():
    import harness_common
    cases = [
        # (module, attribute, util function)
        ("convergence_check", "utc_now", harness_common.utc_now),
        ("progress_report", "utc_now", harness_common.utc_now),
        ("claim_expiry", "utc_now", harness_common.utc_now),
        ("env_check", "utc_now", harness_common.utc_now_z),
        ("heartbeat_tick", "utc_now", harness_common.utc_now_z),
        ("statusline_snapshot", "utc_now", harness_common.utc_now_z),
        ("mission_ledger", "_utc_now", harness_common.utc_now_z),
        ("provider_health", "_utc_now", harness_common.utc_now_z),
        ("dead_letter", "utc_now_iso", harness_common.utc_now_z),
        ("lessons_telemetry", "_utc_now_iso", harness_common.utc_now_z),
        ("outcome_capture", "utc_now_iso", harness_common.utc_now_iso),
    ]
    drifted = {}
    for mod_name, attr, expected in cases:
        got = getattr(_import(mod_name), attr, None)
        if got is not expected:
            drifted[f"{mod_name}.{attr}"] = type(got).__name__
    assert drifted == {}, (
        "aliased utc_now sites must bind the harness_common function itself "
        "(#863 Family F); drifted: " + repr(drifted))


# --------------------------------------------------------------------------
# util contract pins (the exact output shapes the 53 copies produced)
# --------------------------------------------------------------------------

Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_utc_now_returns_tzaware_datetime():
    import harness_common
    now = harness_common.utc_now()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0


def test_utc_now_z_format():
    import harness_common
    assert Z_RE.match(harness_common.utc_now_z()), harness_common.utc_now_z()


def test_utc_now_iso_offset_suffix():
    import harness_common
    out = harness_common.utc_now_iso()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$", out), out


def test_z_paths_byte_equivalent():
    """Behavioral equivalence of the two former Z spellings (shapes B and C):
    for the SAME datetime, strftime("%Y-%m-%dT%H:%M:%SZ") and
    isoformat(timespec="seconds").replace("+00:00", "Z") produce identical
    bytes — which is why 43 copies collapse into one utc_now_z."""
    fixed = datetime(2026, 9, 2, 7, 8, 9, tzinfo=timezone.utc)
    assert fixed.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-09-02T07:08:09Z"
    assert (fixed.isoformat(timespec="seconds").replace("+00:00", "Z")
            == "2026-09-02T07:08:09Z")


def test_hooks_bridge_heartbeat_touch():
    """The hooks-side former copy routes through the #671 scripts-on-path
    authority — no second definition, no bare cross-dir import."""
    text = (ROOT / "hooks" / "heartbeat_touch.py").read_text(
        encoding="utf-8", errors="replace")
    assert "ensure_scripts_path" in text
    assert "harness_common" in text
