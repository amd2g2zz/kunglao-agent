# -*- coding: utf-8 -*-
"""tests/test_tool_search.py — issue #278 P4-a: tools/tool-search.py CLI contract.

Deterministic catalog query over tools/_INDEX.yaml (zero LLM, zero network):
  --capability <domain:op>     exact or prefix match on the capability tag
  --tier T1|T2|T3              exact tier match
  --cost-max probe|cheap|deep  budget filter: probe < cheap < deep (inclusive)
  --json                       JSON output {count, tools: [...]}

Exit codes: 0 = ok (matches, or valid query with no match), 2 = usage error,
3 = index missing/unreadable.

Expectations below are PINNED to the real tools/_INDEX.yaml content
(36 entries total: 7 deep / 24 cheap / 5 probe, all tier T1; growth from
fix/278-static-1c, PR-1c static CLIs, #315 yara pair, #322 sanitize-text,
#306 c-normalize + opaque-pred, #427 rust-dep-strings, #692 android
providers jadx/baksmali-xref/apkid-prescan/gitnexus-query/dexdc-decompile,
#728 web labs wakaru-unbundle/webcrack-deobfuscate). If the index
grows, update these pins deliberately.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "tool-search.py"

DEEP_TOOLS = {"ghidra-recon", "ghidra-decompile-functions", "ghidra-scan-pointer"}
CHEAP_GHIDRA = {"ghidra-vtable-struct", "ghidra-evidence-annotations"}


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
    )


def parse_json(r):
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# --capability: exact + prefix
# ---------------------------------------------------------------------------

def test_capability_exact_returns_crypto_tool():
    r = run_cli("--capability", "crypto:decode", "--json")
    assert r.returncode == 0, r.stderr
    out = parse_json(r)
    assert out["count"] == 1
    assert out["tools"][0]["name"] == "crypto-tool"
    assert out["tools"][0]["capability"] == "crypto:decode"
    assert out["tools"][0]["cost_tier"] == "cheap"


def test_capability_prefix_matches_domain():
    r = run_cli("--capability", "ghidra", "--json")
    assert r.returncode == 0, r.stderr
    out = parse_json(r)
    assert out["count"] == 6  # 6 since #866-b (ghidra_diff registration)
    assert all(t["capability"].startswith("ghidra:") for t in out["tools"])


# ---------------------------------------------------------------------------
# --tier: exact match; empty result is a valid query (exit 0)
# ---------------------------------------------------------------------------

def test_tier_t3_returns_empty_exit_zero():
    r = run_cli("--tier", "T3", "--json")
    assert r.returncode == 0, r.stderr
    out = parse_json(r)
    assert out == {"count": 0, "tools": []}


def test_tier_t1_returns_all_entries():
    r = run_cli("--tier", "T1", "--json")
    assert r.returncode == 0, r.stderr
    out = parse_json(r)
    assert out["count"] == 39  # 39 since #46 (ida-decompile, T1); 38 since #866-b (ghidra_diff); 37 since #884 (jsvmp-triage); 36 since #728


# ---------------------------------------------------------------------------
# --cost-max: budget semantics probe < cheap < deep (inclusive)
# ---------------------------------------------------------------------------

def test_cost_max_cheap_excludes_deep():
    r = run_cli("--cost-max", "cheap", "--json")
    assert r.returncode == 0, r.stderr
    out = parse_json(r)
    assert out["count"] == 31  # 31 since #46 (ida-decompile, cheap); 30 since #884 (jsvmp-triage, cheap); 29 since #728
    assert all(t["cost_tier"] in ("probe", "cheap") for t in out["tools"])
    names = {t["name"] for t in out["tools"]}
    assert not (names & DEEP_TOOLS)


def test_cost_max_probe_returns_only_probe():
    r = run_cli("--cost-max", "probe", "--json")
    assert r.returncode == 0, r.stderr
    out = parse_json(r)
    assert out["count"] == 5
    assert {t["name"] for t in out["tools"]} == \
        {"die-probe", "measure-cold-start", "opaque-pred", "sanitize-text", "yara-gen"}


# ---------------------------------------------------------------------------
# Combined filters: AND semantics
# ---------------------------------------------------------------------------

def test_combined_filters_are_and():
    r = run_cli("--capability", "ghidra", "--cost-max", "cheap",
                "--tier", "T1", "--json")
    assert r.returncode == 0, r.stderr
    out = parse_json(r)
    assert {t["name"] for t in out["tools"]} == CHEAP_GHIDRA


# ---------------------------------------------------------------------------
# Usage errors → exit 2
# ---------------------------------------------------------------------------

def test_unknown_flag_usage_error():
    r = run_cli("--bogus")
    assert r.returncode == 2


def test_invalid_tier_usage_error():
    r = run_cli("--tier", "T9")
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# Missing index → exit 3
# ---------------------------------------------------------------------------

def test_missing_index_exit_three(tmp_path):
    missing = tmp_path / "no-such-index.yaml"
    r = run_cli(str(missing))
    assert r.returncode == 3
    assert "no-such-index" in r.stderr or "not found" in r.stderr


# ---------------------------------------------------------------------------
# --json shape + text mode + determinism
# ---------------------------------------------------------------------------

def test_json_entry_keys():
    r = run_cli("--capability", "crypto:decode", "--json")
    out = parse_json(r)
    entry = out["tools"][0]
    for key in ("name", "category", "capability", "tier", "cost_tier",
                "input_output"):
        assert key in entry, f"missing key {key!r}: {entry}"


def test_text_mode_compact_and_empty():
    r = run_cli("--capability", "crypto:decode")
    assert r.returncode == 0
    assert "crypto-tool" in r.stdout
    assert "crypto:decode" in r.stdout
    # valid query, no match → empty output, exit 0
    r2 = run_cli("--tier", "T3")
    assert r2.returncode == 0
    assert r2.stdout == ""


def test_determinism_two_runs_identical():
    args = ("--capability", "ghidra", "--cost-max", "cheap", "--json")
    r1 = run_cli(*args)
    r2 = run_cli(*args)
    assert r1.returncode == r2.returncode == 0
    assert r1.stdout == r2.stdout
