# -*- coding: utf-8 -*-
"""test_specialist_registry.py — specialist agent routing tests (#135)."""
from __future__ import annotations
import re
import yaml
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "references" / "specialist-registry.yaml"


def load_registry():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def route(text: str, specialists: list) -> str:
    """First-match routing: returns specialist name for given text."""
    for spec in specialists:
        if spec.get("fallback"):
            continue
        triggers = spec.get("triggers", {})
        must_any = triggers.get("must_any", [])
        exclude = triggers.get("exclude", [])
        if not must_any:
            continue
        matched = any(re.search(p, text, re.IGNORECASE) for p in must_any)
        excluded = any(re.search(p, text, re.IGNORECASE) for p in exclude)
        if matched and not excluded:
            return spec["name"]
    # fallback
    for spec in specialists:
        if spec.get("fallback"):
            return spec["name"]
    return "kunglao-worker"


class TestPositiveRouting:
    def test_go_routes_to_go_symbols(self):
        specs = load_registry()["specialists"]
        assert route("Analyze this Go binary for functions", specs) == "go-symbols"

    def test_pe_signature_routes_to_pefile(self):
        specs = load_registry()["specialists"]
        assert route("Extract PE signature and Authenticode info", specs) == "pefile-signature"

    def test_strings_routes_to_floss(self):
        specs = load_registry()["specialists"]
        assert route("Run strings and floss analysis on sample", specs) == "floss-filter"

    def test_decompile_routes_to_ghidra(self):
        specs = load_registry()["specialists"]
        assert route("Decompile and disassemble main function", specs) == "ghidra-light"


class TestNegativeRouting:
    def test_rust_not_go_symbols(self):
        specs = load_registry()["specialists"]
        result = route("Analyze this Rust binary", specs)
        assert result != "go-symbols"

    def test_dotnet_not_ghidra(self):
        specs = load_registry()["specialists"]
        result = route("Decompile .NET assembly", specs)
        assert result != "ghidra-light"

    def test_unknown_falls_back(self):
        specs = load_registry()["specialists"]
        assert route("Some random text with no keywords", specs) == "kunglao-worker"
