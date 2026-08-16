# -*- coding: utf-8 -*-
"""tests/test_route_capability.py — issue #278 P4-b: scripts/route_capability.py contract.

Deterministic feature→capability router (same family as priority.py /
feature_probe.py / tool-search.py). Inputs: feature_probe JSON (via
--features-file or inline --features), claim context (--claim <id> [--register]
or --claim-text), optional --workspace for state reads. Output: JSON/text
{recommendation: {chain, confidence, alternatives}, rationale}. The router
creates NO new state files (#352 removed the --list-recipes catalog surface —
zero runtime consumers).

Confidence formula (documented in the script docstring): max fired rule
strength + 0.05 per claim/feature corroboration, capped 0.95; exact-signal
0.9, structural 0.7-0.8, weak 0.6, tool-search fallback fixed 0.4.

Exit codes: 0 ok, 2 usage, 3 missing inputs.

All features fixtures are synthetic dicts in feature_probe output shape —
no binary fixtures on disk (same approach as test_feature_probe.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "route_capability.py"

X86 = {"machine": "AMD64", "overlay": False, "entropy": 5.0,
       "string_density": 0.2, "import_hints": []}
ARM = {"machine": "ARM64", "overlay": False, "entropy": 3.0,
       "string_density": 0.1, "import_hints": []}
NEUTRAL = {"machine": "ARM64", "overlay": False, "entropy": 1.0,
           "string_density": 0.0, "import_hints": []}


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, timeout=60,
    )


def route_json(*args):
    r = run_cli(*args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def write_register(tmp_path: Path, statement: str) -> Path:
    p = tmp_path / "claim-register.yaml"
    p.write_text(
        "claims:\n- id: C-1\n  status: OPEN\n"
        f"  statement: {statement}\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# routing rules
# ---------------------------------------------------------------------------

def test_x86_decrypt_claim_routes_crypto_decode():
    out = route_json("--features", json.dumps(X86),
                     "--claim-text", "decrypt the payload layer", "--json")
    chain = out["recommendation"]["chain"]
    assert "crypto-tool" in chain
    assert out["recommendation"]["confidence"] >= 0.6
    assert out["rationale"]


def test_go_markers_and_iat_intent():
    feats = dict(ARM, import_hints=["go.buildinfo", "runtime.main"])
    out = route_json("--features", json.dumps(feats),
                     "--claim-text", "recover iat", "--json")
    chain = out["recommendation"]["chain"]
    assert "languages:go" in chain
    assert any("iat" in r for r in out["rationale"])


def test_no_signals_falls_back_to_tool_search():
    out = route_json("--features", json.dumps(NEUTRAL),
                     "--claim-text", "analyze the file", "--json")
    assert out["recommendation"]["confidence"] == 0.4
    assert any("fallback" in r for r in out["rationale"])


def test_deterministic_two_runs_identical():
    args = ["--features", json.dumps(X86), "--claim-text", "decrypt", "--json"]
    a = run_cli(*args)
    b = run_cli(*args)
    assert a.returncode == b.returncode == 0
    assert a.stdout == b.stdout


# ---------------------------------------------------------------------------
# input plumbing
# ---------------------------------------------------------------------------

def test_features_file_input(tmp_path):
    p = tmp_path / "features.json"
    p.write_text(json.dumps(X86), encoding="utf-8")
    out = route_json("--features-file", str(p), "--claim-text", "decrypt",
                     "--json")
    assert "crypto-tool" in out["recommendation"]["chain"]


def test_claim_from_register(tmp_path):
    reg = write_register(tmp_path, "decrypt the payload")
    out = route_json("--features", json.dumps(X86), "--claim", "C-1",
                     "--register", str(reg), "--json")
    assert "crypto-tool" in out["recommendation"]["chain"]


# ---------------------------------------------------------------------------
# exit codes
# ---------------------------------------------------------------------------

def test_usage_conflicting_claim_inputs_exit_2():
    r = run_cli("--features", json.dumps(X86), "--claim", "C-1",
                "--claim-text", "decrypt")
    assert r.returncode == 2


def test_usage_missing_features_exit_2():
    r = run_cli("--claim-text", "decrypt")
    assert r.returncode == 2


def test_usage_invalid_inline_json_exit_2():
    r = run_cli("--features", "{not json", "--claim-text", "decrypt")
    assert r.returncode == 2


def test_missing_features_file_exit_3(tmp_path):
    r = run_cli("--features-file", str(tmp_path / "nope.json"),
                "--claim-text", "decrypt")
    assert r.returncode == 3


def test_missing_register_exit_3(tmp_path):
    r = run_cli("--features", json.dumps(X86), "--claim", "C-1",
                "--register", str(tmp_path / "nope.yaml"))
    assert r.returncode == 3


def test_unknown_claim_exit_3(tmp_path):
    reg = write_register(tmp_path, "decrypt")
    r = run_cli("--features", json.dumps(X86), "--claim", "C-99",
                "--register", str(reg))
    assert r.returncode == 3


# ---------------------------------------------------------------------------
# issue #310: agent_type — specialist routing (mechanical trigger table)
# ---------------------------------------------------------------------------
# The trigger table is parsed from the `triggers:` frontmatter of each
# agents/*.md file (zero drift: the table lives with the agent definition).
# Selection is deterministic: first specialist in pipeline_order whose intent
# regexes match the claim text (no exclude hit) OR whose feature conditions
# match the sample features wins; none -> agent_type null (kunglao-worker).

def test_agent_type_go_features_route_go_symbols():
    feats = dict(ARM, import_hints=["go.buildinfo", "runtime.main"])
    out = route_json("--features", json.dumps(feats),
                     "--claim-text", "analyze the binary", "--json")
    assert out["agent_type"] == "go-symbols"
    assert out["agent_rationale"]


def test_agent_type_die_language_go_routes_go_symbols():
    out = route_json("--features", json.dumps({"language": "Go"}),
                     "--claim-text", "identify functions", "--json")
    assert out["agent_type"] == "go-symbols"


def test_agent_type_decompile_claim_routes_ghidra_light():
    out = route_json("--features", json.dumps(X86),
                     "--claim-text", "decompile and disassemble main", "--json")
    assert out["agent_type"] == "ghidra-light"


def test_agent_type_dotnet_decompile_not_ghidra_light():
    # ghidra-light trigger excludes .NET — the intent regex must not match.
    out = route_json("--features", json.dumps(X86),
                     "--claim-text", "decompile the .NET assembly", "--json")
    assert out["agent_type"] != "ghidra-light"


def test_agent_type_strings_claim_routes_floss_filter():
    out = route_json("--features", json.dumps(X86),
                     "--claim-text", "extract strings from the sample", "--json")
    assert out["agent_type"] == "floss-filter"


def test_agent_type_packer_hints_route_pefile_signature():
    feats = dict(ARM, import_hints=["upx0", "upx1"])
    out = route_json("--features", json.dumps(feats),
                     "--claim-text", "analyze the file", "--json")
    assert out["agent_type"] == "pefile-signature"


def test_agent_type_verdict_claim_routes_verdict_scorer():
    out = route_json("--features", json.dumps(X86),
                     "--claim-text", "produce the final verdict", "--json")
    assert out["agent_type"] == "verdict-scorer"


def test_agent_type_no_signal_is_null():
    out = route_json("--features", json.dumps(NEUTRAL),
                     "--claim-text", "analyze the file", "--json")
    assert out["agent_type"] is None


def test_agent_type_go_intent_precedes_ghidra():
    # "decompile the Go binary" matches both go-symbols and ghidra-light intent
    # — pipeline_order prefers symbol recovery first (unstrip precedes decompile).
    out = route_json("--features", json.dumps(X86),
                     "--claim-text", "decompile the Go binary", "--json")
    assert out["agent_type"] == "go-symbols"


def test_specialist_table_parsed_from_agents_dir():
    """#310: the mechanical table comes from the agents/*.md frontmatter —
    every table entry must exist as an agents/*.md file, and all five claim
    specialists must be present (zero drift, statically derived)."""
    import route_capability
    agents_dir = ROOT / "agents"
    table = route_capability.load_specialist_table(agents_dir)
    md_names = {p.stem for p in agents_dir.glob("*.md")}
    names = {e["name"] for e in table}
    assert names <= md_names, f"table names missing from agents/: {names - md_names}"
    expected = {"ghidra-light", "go-symbols", "floss-filter",
                "pefile-signature", "verdict-scorer"}
    assert expected <= names, f"specialists missing from table: {expected - names}"
    for e in table:
        assert isinstance(e.get("pipeline_order"), int), e["name"]
        assert e.get("intent", {}).get("must_any"), e["name"]


# ---------------------------------------------------------------------------
# #352: --list-recipes catalog surface removed (absence guard)
# ---------------------------------------------------------------------------

def test_list_recipes_flag_removed():
    """#352: the recipe catalog surface is gone — the flag must not exist."""
    r = run_cli("--list-recipes", "--json")
    assert r.returncode == 2  # argparse: unrecognized argument
