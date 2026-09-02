# -*- coding: utf-8 -*-
"""863-h Family L pins: factories reproduce the inline shapes they replace.

Each golden dict/text is copied from a pre-consolidation inline site, so
factory drift (missing key, changed value) fails here instead of silently
changing what the hooks and scripts under test observe.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from _factories import (DEFAULT_SAMPLE, FAR_FUTURE, seed_bins,
                        write_claims_register, write_hook_state)


# ---------- hook_state shape pins ----------

def test_hook_state_minimal_shape(tmp_path):
    """decision_teeth / dispatch_tools_760 3-key armed shape."""
    write_hook_state(tmp_path, active_hooks=["dispatch_gate"])
    got = json.loads((tmp_path / ".hook_state.json").read_text(encoding="utf-8"))
    assert got == {
        "active_hooks": ["dispatch_gate"],
        "paused_hooks": [],
        "expires_at": FAR_FUTURE,
    }


def test_hook_state_full_shape_dynamic_expiry(tmp_path):
    """completion_gate family 7-key shape with now+30min expiry."""
    write_hook_state(tmp_path, active_hooks=["completion_gate"],
                     ts="2026-08-11T12:00:00Z", tier="none", phase="IDLE",
                     user_override={}, expires_minutes=30)
    got = json.loads((tmp_path / ".hook_state.json").read_text(encoding="utf-8"))
    assert got["ts"] == "2026-08-11T12:00:00Z"
    assert got["tier"] == "none" and got["phase"] == "IDLE"
    assert got["active_hooks"] == ["completion_gate"]
    assert got["paused_hooks"] == [] and got["user_override"] == {}
    exp = got["expires_at"]
    assert exp.endswith("Z") and "T" in exp and ":" in exp
    assert not exp.startswith("2099")


def test_hook_state_contract_null_expiry(tmp_path):
    """dispatch_contract 6-key shape: no ts, expires_at JSON null."""
    write_hook_state(tmp_path, active_hooks=["worker_pulse"],
                     phase="test", tier="none", user_override={},
                     expires_at=None)
    got = json.loads((tmp_path / ".hook_state.json").read_text(encoding="utf-8"))
    assert got == {
        "active_hooks": ["worker_pulse"],
        "paused_hooks": [],
        "expires_at": None,
        "tier": "none",
        "phase": "test",
        "user_override": {},
    }


def test_hook_state_two_key_shape(tmp_path):
    """backtrack_loop 2-key shape: paused_hooks key omitted entirely."""
    stamp = "2026-09-02T00:00:00Z"
    write_hook_state(tmp_path, active_hooks=["dispatch_gate"],
                     paused_hooks=None, expires_at=stamp)
    got = json.loads((tmp_path / ".hook_state.json").read_text(encoding="utf-8"))
    assert got == {"active_hooks": ["dispatch_gate"], "expires_at": stamp}


def test_hook_state_resume_three_key_variant(tmp_path):
    """kunglao_resume armed shape: custom hooks + now-relative expiry."""
    write_hook_state(tmp_path, active_hooks=["worker_budget.py", "dispatch_gate.py"],
                     expires_minutes=10)
    got = json.loads((tmp_path / ".hook_state.json").read_text(encoding="utf-8"))
    assert got["active_hooks"] == ["worker_budget.py", "dispatch_gate.py"]
    assert got["paused_hooks"] == []
    assert got["expires_at"].endswith("Z") and not got["expires_at"].startswith("2099")


# ---------- claim-register dialect pins ----------

CANONICAL_REGISTER = (
    "claims:\n"
    "- id: C-1\n"
    "  status: OPEN\n"
    "  boundary_type: positive_observation\n"
    "  evidence_tier_attempted: 0\n"
    "  promotion_attempts: 0\n"
    "  depends_on: []\n"
)


def test_claims_register_canonical_defaults(tmp_path):
    """defaults=True is byte-identical to the ws_factory f-string dialect."""
    write_claims_register(tmp_path, [{"id": "C-1", "status": "OPEN"}], defaults=True)
    got = (tmp_path / "claim-register.yaml").read_text(encoding="utf-8")
    assert got == CANONICAL_REGISTER


def test_claims_register_canonical_empty(tmp_path):
    """Empty register renders as bare header (decide_schema_routing shape)."""
    write_claims_register(tmp_path, [], defaults=True)
    got = (tmp_path / "claim-register.yaml").read_text(encoding="utf-8")
    assert got == "claims:\n"


def test_claims_register_sparse_parse_equivalent(tmp_path):
    """sparse text dialect parses identically to the yaml.safe_dump dialect.

    The four safe_dump seeders hand-rolled a different byte format; every
    consumer (think_seat / rollup / priority_ratio / convergence_check)
    reads via yaml.safe_load, so parsed equality is the equivalence pin.
    """
    claims = [
        {"id": "C-9", "status": "PROVEN", "answers_question": "q1"},
        {"id": "C-2", "status": "OPEN", "tier": 3,
         "depends_on": ["C-1"], "promotion_attempts": 2},
    ]
    write_claims_register(tmp_path, claims)
    via_factory = yaml.safe_load(
        (tmp_path / "claim-register.yaml").read_text(encoding="utf-8"))
    via_yamldump = yaml.safe_load(yaml.safe_dump({"claims": claims}, allow_unicode=True))
    assert via_factory == {"claims": claims} == via_yamldump


# ---------- bins seed pins ----------

def test_seed_bins_default_payload(tmp_path):
    """Default payload is the 26-file MZ+zero-tail shape, byte-identical."""
    target = seed_bins(tmp_path)
    assert target == tmp_path / "bins" / "sample.exe"
    assert target.read_bytes() == DEFAULT_SAMPLE
    assert target.read_bytes() == b"MZ\x90\x00" + b"\x00" * 64


def test_seed_bins_custom_payload_and_name(tmp_path):
    """exit4 / deploy_lifecycle / v012 audit use the 4-byte placeholder."""
    target = seed_bins(tmp_path, payload=b"\x00\x01\x02")
    assert target.read_bytes() == b"\x00\x01\x02"
    named = seed_bins(tmp_path, name="other.bin", payload=b"AB")
    assert named.read_bytes() == b"AB"


# ---------- conftest thin re-exports delegate to the same functions ----------

def test_conftest_reexports_are_the_factory_functions(hook_state_seed,
                                                      claims_seed, bins_seed):
    from _factories import seed_bins as sb, write_claims_register as wcr
    from _factories import write_hook_state as whs
    assert hook_state_seed is whs
    assert claims_seed is wcr
    assert bins_seed is sb
