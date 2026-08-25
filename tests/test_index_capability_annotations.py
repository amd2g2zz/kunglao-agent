# -*- coding: utf-8 -*-
"""RED tests for issue #692 WP1 — capability-provider annotations lint.

Pins the annotation block contract onto tools/validate_index.py (#283's
validator, extended per design.md D1):

  produces:   non-empty list of "<domain>:<operation>" tags; superset of
              `capability`
  requires:   list of tokens from the closed vocabulary (design D2)
  cost_hint:  {mem_gb: number >= 0, time: probe|cheap|deep}
  quality:    map {capability-tag: high|mid|floor}, keys == produces
  provider:   unique across entries (one entry per provider)

The block is opt-in: an entry WITHOUT `provider` never raises annotation
errors (the 30 legacy entries stay untouched — "no behavior change").

Plus the shipped-index contract: the Android providers jadx / baksmali /
apkid / gitnexus are registered with well-formed annotations.

RED phase: validate_index.py has no annotation checks and tools/_INDEX.yaml
has no provider entries, so every test below fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import validate_index as vi  # noqa: E402

import yaml  # noqa: E402


# ---------- helpers ----------

def _valid_entry(**over) -> dict:
    """A fully-valid LEGACY entry (no annotations)."""
    entry = {
        "name": "some-tool",
        "category": "static",
        "capability": "static:disasm",
        "tier": "T1",
        "cost_tier": "cheap",
        "input_output": {"input": "bytes", "output": "listing"},
        "description": "Generic static disasm helper",
    }
    entry.update(over)
    return entry


def _valid_provider_entry(**over) -> dict:
    """A fully-valid annotated provider entry (design D1 shape)."""
    entry = _valid_entry(
        name="provider-x",
        capability="android:java-source",
        description="Android java source provider X",
        produces=["android:java-source"],
        requires=["dex"],
        cost_hint={"mem_gb": 1.0, "time": "deep"},
        quality={"android:java-source": "high"},
        provider="x",
    )
    entry.update(over)
    return entry


def _errors_for(entry) -> list[str]:
    return vi.validate_index({"tools": [entry]})


# ---------- D1.1: annotation block completeness + well-formedness ----------

def test_provider_entry_missing_annotation_field_is_rejected():
    for missing in ("produces", "requires", "cost_hint", "quality"):
        entry = _valid_provider_entry()
        del entry[missing]
        errs = _errors_for(entry)
        assert any(missing in e for e in errs), (
            f"missing {missing!r} must be reported; got {errs}")


def test_provides_must_be_nonempty_tag_list():
    errs = _errors_for(_valid_provider_entry(produces=[]))
    assert any("produces" in e for e in errs)
    errs = _errors_for(_valid_provider_entry(produces="android:java-source"))
    assert any("produces" in e for e in errs)
    errs = _errors_for(_valid_provider_entry(produces=["notatag"]))
    assert any("produces" in e for e in errs)


def test_requires_must_use_closed_vocabulary():
    errs = _errors_for(_valid_provider_entry(requires=["made_up_token"]))
    assert any("requires" in e for e in errs)
    # known token from the D2 table passes
    assert _errors_for(_valid_provider_entry(
        requires=["dex", "mem_budget_ok"])) == []


def test_cost_hint_must_be_well_formed():
    assert _errors_for(_valid_provider_entry(
        cost_hint={"mem_gb": -1, "time": "deep"}))
    assert _errors_for(_valid_provider_entry(
        cost_hint={"mem_gb": 1.0, "time": "instant"}))
    assert _errors_for(_valid_provider_entry(cost_hint={"mem_gb": 1.0}))


def test_quality_must_be_per_capability_tier_map():
    errs = _errors_for(_valid_provider_entry(quality="high"))
    assert any("quality" in e for e in errs)  # plain string is not the map shape
    errs = _errors_for(_valid_provider_entry(quality={"android:java-source": "best"}))
    assert any("quality" in e for e in errs)
    errs = _errors_for(_valid_provider_entry(
        quality={"android:bytecode-truth": "high"}))
    assert any("quality" in e for e in errs)  # key must be a produced capability
    for good in ("high", "mid", "floor"):
        assert _errors_for(_valid_provider_entry(
            quality={"android:java-source": good})) == []


# ---------- D1.2: capability must be a member of produces ----------

def test_capability_must_be_member_of_produces():
    errs = _errors_for(_valid_provider_entry(
        capability="android:bytecode-truth",
        produces=["android:java-source"]))
    assert any("produces" in e for e in errs)


# ---------- D1.3: provider unique across entries ----------

def test_duplicate_provider_is_rejected():
    data = {"tools": [_valid_provider_entry(),
                      _valid_provider_entry(name="provider-x-2")]}
    errs = vi.validate_index(data)
    assert any("provider" in e for e in errs)


# ---------- opt-in: legacy entries unaffected ----------

def test_entry_without_provider_never_raises_annotation_errors():
    assert _errors_for(_valid_entry()) == []


def test_legacy_shipped_index_still_validates():
    """The validator must stay green on the shipped index BEFORE any
    annotation lands (the block is opt-in) — pinning 'no behavior change'."""
    data = yaml.safe_load((TOOLS / "_INDEX.yaml").read_text(encoding="utf-8"))
    assert vi.validate_index(data) == []


# ---------- shipped index: the Android providers are registered ----------

def _shipped_providers() -> dict[str, dict]:
    data = yaml.safe_load((TOOLS / "_INDEX.yaml").read_text(encoding="utf-8"))
    return {t.get("provider"): t for t in data["tools"] if t.get("provider")}


def test_shipped_index_registers_android_providers():
    providers = _shipped_providers()
    for expected in ("jadx", "baksmali", "apkid", "gitnexus"):
        assert expected in providers, (
            f"provider {expected!r} missing from shipped _INDEX.yaml")


def test_shipped_provider_annotations_are_well_formed():
    data = yaml.safe_load((TOOLS / "_INDEX.yaml").read_text(encoding="utf-8"))
    assert vi.validate_index(data) == [], "shipped index must pass its own lint"


def test_jadx_mem_budget_precondition_demoted_to_provider_annotation():
    """#670's mem gate becomes a PROVIDER precondition (design D2): the jadx
    entry requires the mem_budget_ok token — not a pipeline stage."""
    jadx = _shipped_providers()["jadx"]
    assert "android:java-source" in jadx["produces"]
    assert "mem_budget_ok" in jadx["requires"]


def test_gitnexus_declares_semantic_query():
    gitnexus = _shipped_providers()["gitnexus"]
    assert "android:semantic-query" in gitnexus["produces"]
    assert "gitnexus_index" in gitnexus["requires"]


def test_baksmali_declares_bytecode_truth():
    baksmali = _shipped_providers()["baksmali"]
    assert "android:bytecode-truth" in baksmali["produces"]
    assert baksmali["quality"]["android:bytecode-truth"] == "high"  # sole 1:1
    assert baksmali["quality"]["android:java-source"] == "floor"  # fallback
