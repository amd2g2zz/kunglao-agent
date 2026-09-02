# -*- coding: utf-8 -*-
"""RED tests for issue #283 — tools/_INDEX.yaml machine-contract validator.

Pins the tools/_INDEX.yaml contract to a machine validator (tools/validate_index.py):

- name:        unique, non-empty (lowercase kebab-case)
- category:    one of crypto|static|ghidra|dynamic|auxiliary|pipelines
               (#340: category id == tools/<category>/ directory name; the
               legacy ids aux/pipeline were renamed auxiliary/pipelines)
- capability:  "<domain>:<operation>" tag (e.g. crypto:decode), non-empty
- tier:        T1|T2|T3   (static tool / emulation / VM-dynamic)
- cost_tier:   probe|cheap|deep
- input_output: non-empty input→output contract (str or {input, output})
- description: non-empty English one-liner (15-40 chars: what it does + when
               to choose it) — issue #356 W1 (agent tool selection aid)
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
    """A fully-valid tool entry with full annotation block."""
    return {
        "name": "chacha-string-layer",
        "category": "crypto",
        "capability": "crypto:decode",
        "tier": "T1",
        "cost_tier": "cheap",
        "input_output": {"input": "密文字节串", "output": "明文层"},
        "description": "Decodes ChaCha layers; pick for byte-exact verify",
        "when_not": "非 ChaCha 流加密时不用",
        # #729: all annotated entries need provider block
        "provider": "chacha-tool",
        "produces": ["crypto:decode"],
        "requires": [],
        "cost_hint": {"mem_gb": 0.1, "time": "cheap"},
        "quality": {"crypto:decode": "high"},
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
             "capability": "android:java-source",
             "provider": "floss-provider",
             "produces": ["android:java-source"],
             "quality": {"android:java-source": "high"}},
        ]}
        assert _errors(data) == []

    def test_when_not_optional(self) -> None:
        entry = _valid_entry()
        del entry["when_not"]
        assert _errors({"tools": [entry]}) == []

    @pytest.mark.parametrize("category", [
        "crypto", "static", "ghidra", "dynamic", "auxiliary", "pipelines",
    ])
    def test_every_category_id_passes(self, category: str) -> None:
        """#340: category ids == directory names — full enum must validate."""
        entry = _valid_entry()
        entry["category"] = category
        assert _errors({"tools": [entry]}) == []

    @pytest.mark.parametrize("legacy", ["aux", "pipeline"])
    def test_legacy_category_ids_fail(self, legacy: str) -> None:
        """#340 renamed aux→auxiliary / pipeline→pipelines: the legacy ids
        must be rejected so the id==dirname alignment cannot drift back."""
        entry = _valid_entry()
        entry["category"] = legacy
        errs = _errors({"tools": [entry]})
        assert any("'category'" in e for e in errs), errs

    def test_cli_exit_zero_on_valid_file(self, tmp) -> None:
        idx = tmp / "index.yaml"
        idx.write_text("tools: []\n", encoding="utf-8")
        r = _run_cli(idx)
        assert r.returncode == 0, r.stderr


# ---------- fail cases ----------

class TestFail:
    @pytest.mark.parametrize("field", [
        "name", "category", "capability", "tier", "cost_tier", "input_output",
        "description",
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

    # ---------- description contract (#356 W1) ----------

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_empty_description_fails(self, bad: str) -> None:
        """#356 W1: description is required and must be non-blank."""
        entry = _valid_entry()
        entry["description"] = bad
        errs = _errors({"tools": [entry]})
        assert any("description" in e for e in errs), errs

    def test_non_string_description_fails(self) -> None:
        entry = _valid_entry()
        entry["description"] = 42
        errs = _errors({"tools": [entry]})
        assert any("description" in e for e in errs), errs

    def test_duplicate_name_fails(self) -> None:
        a = _valid_entry()
        b = {**_valid_entry(), "category": "static", "capability": "static:strings"}
        assert a["name"] == b["name"]  # same name, different category
        errs = _errors({"tools": [a, b]})
        assert any("name" in e and "duplicate" in e.lower() for e in errs), errs

    # (field, bad_value) — each invalid value must be rejected by the validator.
    INVALID_FIELD_VALUES = [
        ("category", "cryptography"), ("category", "Crypto"), ("category", "re"),
        ("category", ""), ("category", "unknown"),
        ("tier", "T0"), ("tier", "t1"), ("tier", "T4"), ("tier", "T"), ("tier", ""),
        ("cost_tier", "free"), ("cost_tier", "CHEAP"), ("cost_tier", "ultra-deep"),
        ("cost_tier", "x"), ("cost_tier", ""),
        ("input_output", ""), ("input_output", "   "), ("input_output", {}),
        ("input_output", {"input": ""}),
    ]

    def test_invalid_field_values_fail(self) -> None:
        for field, bad in self.INVALID_FIELD_VALUES:
            entry = _valid_entry()
            entry[field] = bad
            assert _errors({"tools": [entry]}), f"field={field!r} value={bad!r} must fail"

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


# ---------- shipped index contract (#356 W1) ----------

class TestShippedIndex:
    """The shipped tools/_INDEX.yaml must satisfy the #356 W1 additions:

    - every entry carries a non-empty description
    - each description is a length-bounded English one-liner
      (15-40 chars: what it does + when to choose it) — guidance, enforced
      loosely: ASCII-only and within [15, 40] characters.
    """

    def test_shipped_index_passes_validator(self) -> None:
        r = _run_cli(INDEX_YAML)
        assert r.returncode == 0, r.stderr

    def test_shipped_every_tool_has_description(self) -> None:
        import yaml
        data = yaml.safe_load(INDEX_YAML.read_text(encoding="utf-8"))
        tools = data.get("tools", [])
        assert tools, "shipped index unexpectedly empty"
        missing = [t.get("name", f"tools[{i}]")
                   for i, t in enumerate(tools)
                   if not (isinstance(t.get("description"), str)
                           and t["description"].strip())]
        assert not missing, f"tools missing description: {missing}"

    def test_shipped_descriptions_english_and_bounded(self) -> None:
        import yaml
        data = yaml.safe_load(INDEX_YAML.read_text(encoding="utf-8"))
        bad = []
        for t in data.get("tools", []):
            d = t.get("description", "")
            if not d.isascii():
                bad.append(f"{t.get('name')}: non-ASCII description {d!r}")
            elif not 15 <= len(d.strip()) <= 40:
                bad.append(f"{t.get('name')}: length {len(d.strip())} outside [15,40]: {d!r}")
        assert not bad, "\n".join(bad)


# ---------- #729 Rule A: annotation gate (LEGACY_UNANNOTATED whitelist) ----------

class TestRuleA_AnnotationGate:
    """Rule A (#729): new entries without a provider block are rejected.
    LEGACY_UNANNOTATED (29 frozen names) get a WARN pass."""

    def test_rule_a_new_entry_without_provider_fails(self) -> None:
        """A brand-new tool entry with no provider block must FAIL."""
        entry = _valid_entry()
        entry["name"] = "brand-new-tool"   # not in LEGACY_UNANNOTATED
        # remove the annotation block that _valid_entry() now carries
        for _field in ("when_not", "provider", "produces", "requires",
                       "cost_hint", "quality"):
            entry.pop(_field, None)
        errs = _errors({"tools": [entry]})
        assert errs, "brand-new-tool should fail: no provider block"
        assert any("provider" in e for e in errs), errs

    def test_rule_a_removed_whitelist_name_without_provider_fails(self) -> None:
        """#863: the LEGACY_UNANNOTATED whitelist is gone — a formerly
        legacy name (crypto-tool) without a provider block now FAILs."""
        entry = _valid_entry()
        entry["name"] = "crypto-tool"      # formerly in LEGACY_UNANNOTATED
        entry["capability"] = "crypto:decode"
        for _field in ("when_not", "provider", "produces", "requires",
                       "cost_hint", "quality"):
            entry.pop(_field, None)   # strip the whole annotation block
        errs = _errors({"tools": [entry]})
        assert any("provider" in e for e in errs), (
            f"formerly-legacy name without provider must fail: {errs}")

    def test_rule_a_annotated_entry_passes(self) -> None:
        """An entry WITH a provider block (even if new) is always fine."""
        entry = _valid_entry()
        entry["name"] = "new-annotated-tool"
        entry["capability"] = "static:strings"
        entry["provider"] = "test-provider"
        entry["produces"] = ["static:strings"]
        entry["requires"] = []
        entry["cost_hint"] = {"mem_gb": 0.5, "time": "cheap"}
        entry["quality"] = {"static:strings": "high"}
        del entry["when_not"]
        errs = _errors({"tools": [entry]})
        # Must NOT have the "no provider block" error
        assert not any("no 'provider' block" in e for e in errs), errs


# ---------- #729 Rule B: CAPABILITY_TAGS closed vocabulary ----------

class TestRuleB_CapabilityTags:
    """Rule B (#729): every produces tag must be in _CAPABILITY_TAGS."""

    def test_rule_b_unknown_produces_tag_fails(self) -> None:
        """A produces tag not in CAPABILITY_TAGS must FAIL."""
        entry = _valid_entry()
        entry["name"] = "unknown-tag-tool"
        entry["capability"] = "unknown:tag"
        entry["provider"] = "test-provider"
        entry["produces"] = ["unknown:tag"]        # not in _CAPABILITY_TAGS
        entry["requires"] = []
        entry["cost_hint"] = {"mem_gb": 0.5, "time": "cheap"}
        entry["quality"] = {"unknown:tag": "high"}
        del entry["when_not"]
        errs = _errors({"tools": [entry]})
        assert errs, "'unknown:tag' should fail: not in CAPABILITY_TAGS"
        assert any("CAPABILITY_TAGS" in e for e in errs), errs

    def test_rule_b_known_produces_tag_passes(self) -> None:
        """A produces tag already in CAPABILITY_TAGS passes."""
        entry = _valid_entry()
        entry["name"] = "android-java-tool"
        entry["capability"] = "android:java-source"
        entry["provider"] = "test-provider"
        entry["produces"] = ["android:java-source"]  # in CAPABILITY_TAGS
        entry["requires"] = []
        entry["cost_hint"] = {"mem_gb": 4.0, "time": "deep"}
        entry["quality"] = {"android:java-source": "high"}
        del entry["when_not"]
        errs = _errors({"tools": [entry]})
        assert not errs, f"'android:java-source' should pass: {errs}"

    def test_shipped_index_all_produces_tags_in_vocabulary(self) -> None:
        """Every produces tag in the shipped index must be in _CAPABILITY_TAGS."""
        import yaml
        data = yaml.safe_load(INDEX_YAML.read_text(encoding="utf-8"))
        from validate_index import _CAPABILITY_TAGS
        unknown: list[str] = []
        for t in data.get("tools", []):
            for tag in t.get("produces", []):
                if tag not in _CAPABILITY_TAGS:
                    unknown.append(f"{t['name']}: {tag}")
        assert not unknown, (
            f"Produces tags not in CAPABILITY_TAGS (add to "
            f"_CAPABILITY_TAGS after deliberate review): {unknown}"
        )

