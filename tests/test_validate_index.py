# -*- coding: utf-8 -*-
"""RED tests for issue #283 — tools/_INDEX.yaml machine-contract validator.

Pins the tools/_INDEX.yaml contract to a machine validator (tools/validate_index.py):

- name:        unique, non-empty (lowercase kebab-case)
- category:    one of crypto|static|ghidra|dynamic|pipeline|aux
- capability:  "<domain>:<operation>" tag (e.g. crypto:decode), non-empty
- tier:        T1|T2|T3   (static tool / emulation / VM-dynamic)
- cost_tier:   probe|cheap|deep
- input_output: non-empty input→output contract (str or {input, output})
- when_not:    optional — when NOT to use the tool

Validator contract:
- exit 0 = pass, exit 1 = fail with an error list (gate-callable).

RED phase: tools/validate_index.py does not exist yet, so every code test below
fails; the empty-index and CLI tests fail at import/collection until the module
lands.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
VALIDATOR = TOOLS / "validate_index.py"
INDEX_YAML = TOOLS / "_INDEX.yaml"

sys.path.insert(0, str(TOOLS))
import validate_index as vi  # noqa: E402


# ---------- helpers ----------

def _valid_entry() -> dict:
    """A fully-valid tool entry."""
    return {
        "name": "chacha-string-layer",
        "category": "crypto",
        "capability": "crypto:decode",
        "tier": "T1",
        "cost_tier": "cheap",
        "input_output": {"input": "密文字节串", "output": "明文层"},
        "when_not": "非 ChaCha 流加密时不用",
    }


def _errors(data) -> list[str]:
    """Run the pure validator over a YAML-parsed payload."""
    return vi.validate_index(data)


def _run_cli(index_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(index_path)],
        # tools emit UTF-8 (#317 unified stdout); decode as UTF-8, not the
        # GBK locale default, or multi-byte chars crash the reader thread
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )


# ---------- pass cases ----------

class TestPass:
    def test_empty_index_passes(self) -> None:
        """Initial skeleton (`tools: []`) must pass."""
        assert _errors({"tools": []}) == []

    def test_empty_file_passes(self) -> None:
        """A null/empty YAML payload is treated as an empty index."""
        assert _errors(None) == []

    def test_missing_tools_key_treated_empty(self) -> None:
        """No `tools` key at all → empty index (initial skeleton tolerance)."""
        assert _errors({"schema": "tools-index/1"}) == []

    def test_valid_entry_passes(self) -> None:
        assert _errors({"tools": [_valid_entry()]}) == []

    def test_valid_multiple_distinct_names(self) -> None:
        data = {"tools": [
            _valid_entry(),
            {**_valid_entry(), "name": "floss", "category": "static",
             "capability": "static:strings"},
        ]}
        assert _errors(data) == []

    def test_when_not_optional(self) -> None:
        entry = _valid_entry()
        del entry["when_not"]
        assert _errors({"tools": [entry]}) == []

    def test_cli_exit_zero_on_valid_file(self, tmp) -> None:
        idx = tmp / "index.yaml"
        idx.write_text("tools: []\n", encoding="utf-8")
        r = _run_cli(idx)
        assert r.returncode == 0, r.stderr


# ---------- fail cases ----------

class TestFail:
    @pytest.mark.parametrize("field", [
        "name", "category", "capability", "tier", "cost_tier", "input_output",
    ])
    def test_missing_required_field_fails(self, field: str) -> None:
        entry = _valid_entry()
        del entry[field]
        errs = _errors({"tools": [entry]})
        assert errs, f"expected error for missing field: {field}"

    def test_empty_name_fails(self) -> None:
        entry = _valid_entry()
        entry["name"] = ""
        assert _errors({"tools": [entry]})

    def test_duplicate_name_fails(self) -> None:
        a = _valid_entry()
        b = {**_valid_entry(), "category": "static", "capability": "static:strings"}
        assert a["name"] == b["name"]  # same name, different category
        errs = _errors({"tools": [a, b]})
        assert any("name" in e and "duplicate" in e.lower() for e in errs), errs

    @pytest.mark.parametrize("bad", ["cryptography", "Crypto", "re", "", "unknown"])
    def test_invalid_category_fails(self, bad: str) -> None:
        entry = _valid_entry()
        entry["category"] = bad
        assert _errors({"tools": [entry]})

    @pytest.mark.parametrize("bad", ["T0", "t1", "T4", "T", ""])
    def test_invalid_tier_fails(self, bad: str) -> None:
        entry = _valid_entry()
        entry["tier"] = bad
        assert _errors({"tools": [entry]})

    @pytest.mark.parametrize("bad", ["free", "CHEAP", "ultra-deep", "x", ""])
    def test_invalid_cost_tier_fails(self, bad: str) -> None:
        entry = _valid_entry()
        entry["cost_tier"] = bad
        assert _errors({"tools": [entry]})

    @pytest.mark.parametrize("bad", ["", "   ", {}, {"input": ""}])
    def test_empty_input_output_fails(self, bad) -> None:
        entry = _valid_entry()
        entry["input_output"] = bad
        assert _errors({"tools": [entry]})

    def test_capability_must_be_domain_operation(self) -> None:
        entry = _valid_entry()
        entry["capability"] = "decodestrings"
        assert _errors({"tools": [entry]})

    def test_empty_capability_fails(self) -> None:
        entry = _valid_entry()
        entry["capability"] = ""
        assert _errors({"tools": [entry]})

    def test_entry_not_a_dict_fails(self) -> None:
        assert _errors({"tools": ["chacha-string-layer"]})

    def test_tools_not_a_list_fails(self) -> None:
        assert _errors({"tools": "chacha-string-layer"})

    def test_cli_exit_one_on_invalid_file(self, tmp) -> None:
        idx = tmp / "index.yaml"
        idx.write_text(
            "tools:\n  - name: a\n    category: bad\n    tier: T9\n    cost_tier: free\n"
            "    input_output: ''\n",
            encoding="utf-8")
        r = _run_cli(idx)
        assert r.returncode == 1, r.stdout
        assert "error" in r.stderr.lower()

    def test_cli_exit_one_on_malformed_yaml(self, tmp) -> None:
        idx = tmp / "index.yaml"
        idx.write_text("tools:\n  - name: [unclosed\n", encoding="utf-8")
        r = _run_cli(idx)
        assert r.returncode == 1, r.stdout
        assert r.stderr  # an error list / parse message is printed
