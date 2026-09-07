# -*- coding: utf-8 -*-
"""tests/test_case_admission_126.py — #126 oracle case admission integrity.

#108 half C made byte anchors MANDATORY, but they stayed DECLARATIONS, not
RESOLUTIONS: ``evidence_refs: [F999]`` with an invented fact id passes the
lint, nothing ties a case to the hypothesis whose predicted_observation it
realizes, dedup is absent on the case side and textual on the bank side, and
a case can be admitted without any mutation at all. This file pins the
admission-time contract that closes those four openings:

  1. every non-pending evidence_ref RESOLVES to an existing fact-pipeline
     artifact (facts/F*.md or an evidence/ file) under the workspace;
  2. refs pointing into the oracle's own output (runs/ | oracle/, the case
     file itself) are REFUSED — self-anchoring is circular verification;
  3. ``hypothesis_ref`` is required and must exist in the hypothesis store
     (the case names the live competitor-group question it discriminates);
  4. the action signature (declared observation channel, competitor_group
     of the linked hypothesis) is the dedup axis — a second case with an
     identical signature is refused at load;
  5. ``mutations`` must be non-empty at load (the mutation-must-fail flag
     becomes an admission requirement);
  6. case_bank.append_once keys on the action signature, not the free-text
     method: the same action under two tool names banks once and can no
     longer displace other failures-first lessons from the top-5 window.

E3 pre-experiment verdict (scripts/priority_ratio.py reuse check): the
tool-family vocabulary is per-TOOL (frida != ida) and carries no unidbg/
qiling emulator tokens, so it cannot classify
("frida stalker trace", "ida server trace") as the SAME channel. The
observation channel is therefore DECLARED (`channel:` on the case doc);
the bank face reads the channel from the method text through a declared
word-bounded token vocabulary with an ``adhoc:`` fallback so unknown
actions never falsely dedup. Both faces are pure functions.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import case_bank as cb  # noqa: E402  (RED: imports resolve, contract absent)
import oracle_runner as orun  # noqa: E402


# ---------------------------------------------------------------- fixtures

HYP_AUTH = "H-101"    # competitor_group: grp-auth
HYP_MAGIC = "H-102"   # competitor_group: grp-magic


def _write_hypothesis(ws: Path, hyp_id: str, group: str) -> None:
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        "claim_id: C-1\n"
        f"competitor_group: {group}\n"
        "candidates: [AES, ChaCha20]\n"
        "status: open\n"
        "schema_rev: 1\n"
        "---\n"
        "\npq:q1\n\nSeeded scaffold — the case realizes this bet's "
        "predicted_observation.\n",
        encoding="utf-8")


def _mk_ws(tmp_path: Path) -> Path:
    """Workspace whose fact pipeline can answer resolvable refs: facts/F001,
    facts/F002, evidence/die.json, and two live hypotheses."""
    ws = tmp_path / "ws"
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text(
        "# F001\n\nauth_algo pins hmac-sha256 (byte-anchored).\n",
        encoding="utf-8")
    (ws / "facts" / "F002.md").write_text(
        "# F002\n\nmagic pins MZ (byte-anchored).\n", encoding="utf-8")
    (ws / "evidence").mkdir()
    (ws / "evidence" / "die.json").write_text("{}\n", encoding="utf-8")
    _write_hypothesis(ws, HYP_AUTH, "grp-auth")
    _write_hypothesis(ws, HYP_MAGIC, "grp-magic")
    return ws


BASE_CASE = {
    "id": "auth-fields",
    "channel": "device-trace",
    "hypothesis_ref": HYP_AUTH,
    "params": {"user": "alice", "nonce": 10},
    "expected": [
        {"field": "auth_algo", "value": "hmac-sha256",
         "evidence_refs": ["F001"]},
    ],
    "mutations": [{"field": "auth_algo", "kind": "swap"}],
}


def _write_case(ws: Path, case: dict, name: str = "case-00.yaml") -> Path:
    p = ws / "oracle" / "cases" / name
    p.write_text(
        yaml.safe_dump(case, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return p


# --------------------------------------------------- 1. invented refs

def test_invented_evidence_ref_refused(tmp_path: Path) -> None:
    """evidence_refs: [F999] where facts/F999.md does not exist -> REFUSED
    (#126: refs are declarations, not resolutions)."""
    ws = _mk_ws(tmp_path)
    case = copy.deepcopy(BASE_CASE)
    case["expected"][0]["evidence_refs"] = ["F999"]
    _write_case(ws, case)
    with pytest.raises(orun.OracleCaseError, match="F999"):
        orun.load_cases(ws / "oracle" / "cases")


def test_invented_evidence_ref_refused_in_second_case_too(tmp_path: Path) -> None:
    """The resolution lint is per-case, not first-case-only."""
    ws = _mk_ws(tmp_path)
    good = copy.deepcopy(BASE_CASE)
    bad = copy.deepcopy(BASE_CASE)
    bad["id"] = "other-fields"
    bad["channel"] = "emulator-trace"
    bad["expected"][0]["evidence_refs"] = ["F888"]
    _write_case(ws, good, "case-00.yaml")
    _write_case(ws, bad, "case-01.yaml")
    with pytest.raises(orun.OracleCaseError, match="F888"):
        orun.load_cases(ws / "oracle" / "cases")


# --------------------------------------------------- 2. self-anchoring

@pytest.mark.parametrize("ref", [
    "runs/oracle-status.json",        # the run's own verdict file
    "oracle/cases/case-00.yaml",      # the case file itself
])
def test_self_anchoring_ref_refused(tmp_path: Path, ref: str) -> None:
    """A ref pointing at oracle status/output (runs/... or the case file
    itself) is refused — circular verification is the machine channel for a
    100% pass rate (#126)."""
    ws = _mk_ws(tmp_path)
    (ws / "runs").mkdir()
    (ws / "runs" / "oracle-status.json").write_text("{}\n", encoding="utf-8")
    case = copy.deepcopy(BASE_CASE)
    case["expected"][0]["evidence_refs"] = [ref]
    _write_case(ws, case)
    with pytest.raises(orun.OracleCaseError, match="self-anchor"):
        orun.load_cases(ws / "oracle" / "cases")


# --------------------------------------------------- 3. hypothesis_ref

def test_case_without_hypothesis_ref_refused(tmp_path: Path) -> None:
    """No case->hypothesis linkage -> the case discriminates nothing in the
    live competitor field (the trivial-oracle class) -> REFUSED."""
    ws = _mk_ws(tmp_path)
    case = copy.deepcopy(BASE_CASE)
    case.pop("hypothesis_ref")
    _write_case(ws, case)
    with pytest.raises(orun.OracleCaseError, match="hypothesis_ref"):
        orun.load_cases(ws / "oracle" / "cases")


def test_hypothesis_ref_must_exist_in_store(tmp_path: Path) -> None:
    """hypothesis_ref naming a hypothesis the store has never heard of ->
    REFUSED (a link to nothing links nothing)."""
    ws = _mk_ws(tmp_path)
    case = copy.deepcopy(BASE_CASE)
    case["hypothesis_ref"] = "H-999"
    _write_case(ws, case)
    with pytest.raises(orun.OracleCaseError, match="H-999"):
        orun.load_cases(ws / "oracle" / "cases")


# ------------------------------------- 4. action-signature dedup (E3)

def test_e3_channel_verdict_table() -> None:
    """E3 canonical verdict table, bank face:
    ("frida stalker trace", "ida server trace")     -> SAME  (device-trace)
    ("unidbg codehook trace", "frida hook trace")   -> DIFFERENT (emu/dev)
    priority_ratio's tool families are per-TOOL and cannot produce this —
    the channel comes from the declared vocabulary instead."""
    assert orun.action_channel("frida stalker trace") == \
        orun.action_channel("ida server trace")
    assert orun.action_channel("unidbg codehook trace") != \
        orun.action_channel("frida hook trace")


def test_action_signature_is_pure() -> None:
    """The signature is a pure function: same input -> same output, no
    hidden state, and unknown methods never collapse into one bucket."""
    assert orun.action_signature("device-trace", "grp-auth") == \
        orun.action_signature("device-trace", "grp-auth")
    assert orun.action_signature("device-trace", "grp-auth") != \
        orun.action_signature("device-trace", "grp-magic")
    for m in ("device-trace via frida-stalker", "upx-unpack", ""):
        assert orun.action_channel(m) == orun.action_channel(m)
    assert orun.action_channel("upx-unpack") != \
        orun.action_channel("osint-query")


def test_duplicate_signature_second_case_refused(tmp_path: Path) -> None:
    """Two cases in one load with the identical signature (same declared
    channel + same competitor_group) -> the SECOND is refused: marginal
    discriminative power, not text, is the dedup axis."""
    ws = _mk_ws(tmp_path)
    twin = copy.deepcopy(BASE_CASE)
    twin["id"] = "auth-fields-again"
    _write_case(ws, copy.deepcopy(BASE_CASE), "case-00.yaml")
    _write_case(ws, twin, "case-01.yaml")
    with pytest.raises(orun.OracleCaseError, match="auth-fields-again"):
        orun.load_cases(ws / "oracle" / "cases")


def test_distinct_channel_or_group_admits_both(tmp_path: Path) -> None:
    """Different channel (emulator vs device) = NOT a duplicate —
    cross-channel divergence is itself an observation. Same channel with a
    different competitor_group is equally distinct."""
    ws = _mk_ws(tmp_path)
    device = copy.deepcopy(BASE_CASE)
    emulator = copy.deepcopy(BASE_CASE)
    emulator["id"] = "emu-fields"
    emulator["channel"] = "emulator-trace"
    other_group = copy.deepcopy(BASE_CASE)
    other_group["id"] = "magic-fields"
    other_group["hypothesis_ref"] = HYP_MAGIC
    _write_case(ws, device, "case-00.yaml")
    _write_case(ws, emulator, "case-01.yaml")
    _write_case(ws, other_group, "case-02.yaml")
    cases = orun.load_cases(ws / "oracle" / "cases")
    assert [c["id"] for c in cases] == \
        ["auth-fields", "emu-fields", "magic-fields"]


# ---------------------------------------------- 5. mutations at load

@pytest.mark.parametrize("mutations", [None, []])
def test_case_without_mutations_refused(tmp_path: Path,
                                        mutations) -> None:
    """A case that cannot go red under a deliberately wrong implementation
    is a rubber stamp: missing OR empty `mutations` -> REFUSED at load
    (the --mutation flag becomes an admission requirement)."""
    ws = _mk_ws(tmp_path)
    case = copy.deepcopy(BASE_CASE)
    if mutations is None:
        case.pop("mutations")
    else:
        case["mutations"] = mutations
    _write_case(ws, case)
    with pytest.raises(orun.OracleCaseError, match="mutation"):
        orun.load_cases(ws / "oracle" / "cases")


# ------------------------------------------------------ 7. acceptance

def test_fully_armed_case_loads_clean(tmp_path: Path) -> None:
    """Acceptance: resolvable fact refs + a resolvable evidence/ file ref +
    existing hypothesis_ref + >=1 mutation -> loads clean."""
    ws = _mk_ws(tmp_path)
    case = copy.deepcopy(BASE_CASE)
    case["expected"].append(
        {"field": "packer", "value": "UPX", "evidence_refs": ["die.json"]})
    _write_case(ws, case)
    cases = orun.load_cases(ws / "oracle" / "cases")
    assert [c["id"] for c in cases] == ["auth-fields"]
    assert cases[0]["expected"][1]["evidence_refs"] == ["die.json"]
    assert cases[0]["mutations"][0]["field"] == "auth_algo"


# ------------------------------------------ 8. bank-side signature dedup

def _bank_entry(claim_id: str, method: str, roi_class: str = "POSITIVE",
                **kw) -> dict:
    e = {"claim_id": claim_id, "method": method, "roi_class": roi_class,
         "context_tags": ["android"]}
    e.update(kw)
    return e


def test_append_once_dedups_same_signature_different_tool_name(
        tmp_path: Path) -> None:
    """Two entries differing only in the free-text method, SAME signature
    (device-trace via frida-stalker vs ida-server) -> one banked row."""
    first = cb.append_once(tmp_path, _bank_entry(
        "C-1", "device-trace via frida-stalker"))
    second = cb.append_once(tmp_path, _bank_entry(
        "C-1", "device-trace via ida-server"))
    assert first["ok"] is True and first["duplicate"] is False
    assert second["ok"] is True and second["duplicate"] is True
    assert len(cb.read_entries(tmp_path)) == 1


def test_cross_channel_divergence_banks_separately(tmp_path: Path) -> None:
    """emulator vs device channels are DIFFERENT signatures — cross-channel
    divergence is itself an observation, so both rows bank."""
    cb.append_once(tmp_path, _bank_entry(
        "C-1", "device-trace via frida-stalker"))
    res = cb.append_once(tmp_path, _bank_entry(
        "C-1", "emulator-trace via unidbg"))
    assert res["duplicate"] is False
    assert len(cb.read_entries(tmp_path)) == 2


def test_roi_class_still_axes_the_bank_key(tmp_path: Path) -> None:
    """The dedup key stays (claim_id, signature, roi_class): an evolving
    verdict (fails -> passes) still banks a NEW row (#110 face kept)."""
    cb.append_once(tmp_path, _bank_entry(
        "C-1", "device-trace via frida-stalker", "NEGATIVE",
        attribution="wrong trace pass"))
    res = cb.append_once(tmp_path, _bank_entry(
        "C-1", "device-trace via ida-server"))
    assert res["duplicate"] is False
    assert sorted(r["roi_class"] for r in cb.read_entries(tmp_path)) == \
        ["NEGATIVE", "POSITIVE"]


def test_top5_failures_window_not_displaced_by_tool_name_variants(
        tmp_path: Path) -> None:
    """The reason #126 exists: retrieve() is positional, limit=5. A tool-name
    variant of an already-banked action must NOT append a new row — the
    oldest failure stays inside the top-5 failures-first window."""
    methods = ["static-derive via ghidra", "adhoc-scan via apkid",
               "adhoc-hook via xposed", "adhoc-unpack via binwalk",
               "device-trace via frida-stalker"]
    for i, m in enumerate(methods):
        cb.append_once(tmp_path, _bank_entry(
            f"C-{i + 1}", m, "NEGATIVE", attribution=f"why C-{i + 1} failed"))
    res = cb.append_once(tmp_path, _bank_entry(
        "C-5", "device-trace via ida-server", "NEGATIVE",
        attribution="same trace channel, second tool name"))
    assert res["duplicate"] is True
    assert len(cb.read_entries(tmp_path)) == 5
    window = [e["claim_id"] for e in cb.retrieve(tmp_path, [], 5)]
    assert window == ["C-5", "C-4", "C-3", "C-2", "C-1"], \
        "the oldest failure was displaced by a tool-name variant"
