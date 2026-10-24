# -*- coding: utf-8 -*-
"""tests/test_evidence_certify_803.py — the evidence-certification face
(issue 803, the certification inversion).

The production pathology: evidence strength ranked below process
conformance — F009 (byte-exact reproduction 528/528 replay pairs +
fresh-input server acceptance) sat at INFERRED waiting on a
dispatch-cycle formality while a lane=web SCAFFOLD claim with no
evidence class rode a full blind red-team to PROVEN.

The face: a certification row (evidence/cert-<claim>.json, schema
evidence-cert/1) that CARRIES its own replay instruction (command +
fixture references + pinned output sha) and is actually executable —
the pin is certify -> replay -> result byte-consistent. Promotion
eligibility reads EVIDENCE CLASS first: a sealed, replay-consistent
certification of the F009 shape admits ->PROVEN without another
dispatch cycle; a scaffold-only claim with no evidence class can no
longer reach PROVEN via red-team alone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import evidence_certify as ec  # noqa: E402
import lint_facts  # noqa: E402
from register_proven_gate import check_register_transitions  # noqa: E402
from verifier_integrity import resolve_verification  # noqa: E402

CLAIM = "C-001"

REG = (
    "claims:\n"
    "  - id: C-001\n"
    "    status: {s}\n"
    "    statement: synthetic claim for certification tests\n"
    "    {extra}"
)

REPLAY_SCRIPT = (
    "import json, sys\n"
    "print('REPRO-OUTPUT-BYTES', end='')\n"
)

REPLAY_ARTIFACT = {
    "schema": "replay-equivalence/1",
    "claim_id": CLAIM,
    "captured_inputs": ["cap-01"],
    "variables": {"ts": ["1700000000"]},
    "strength": 1,
    "pairs": [
        {"input_id": "cap-01", "inputs": {"ts": "1700000000"},
         "ref_output": "w=abc123", "repro_output": "w=abc123",
         "byte_equal": True, "divergence_offset": None},
    ],
}

FRESH_ARTIFACT = {
    "schema": "fresh-input/1",
    "claim_id": CLAIM,
    "inputs": [
        {"input_id": "fresh-01", "inputs": {"q": "fresh-query"},
         "accepted": True},
    ],
}


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "evidence").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    return ws


def _register(ws: Path, status: str = "PARTIALLY-VERIFIED",
              extra: str = "") -> None:
    tail = f"\n    {extra}" if extra else ""
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        f"  - id: {CLAIM}\n"
        f"    status: {status}\n"
        "    statement: synthetic claim for certification tests\n"
        f"{tail}\n",
        encoding="utf-8")


def _legs(ws: Path, *, script_body: str = REPLAY_SCRIPT) -> None:
    (ws / "evidence" / f"replay-{CLAIM}.json").write_text(
        json.dumps(REPLAY_ARTIFACT, indent=2), encoding="utf-8")
    (ws / "evidence" / f"fresh-{CLAIM}.json").write_text(
        json.dumps(FRESH_ARTIFACT, indent=2), encoding="utf-8")
    (ws / "runs" / f"replay-{CLAIM}.py").write_text(script_body,
                                                    encoding="utf-8")


def _mint(ws: Path) -> dict:
    return ec.mint(ws, CLAIM,
                   byte_exact_artifact=f"evidence/replay-{CLAIM}.json",
                   fresh_input_artifact=f"evidence/fresh-{CLAIM}.json",
                   command=f"python runs/replay-{CLAIM}.py")


def _transition(ws: Path, frm: str = "PARTIALLY-VERIFIED",
                to: str = "PROVEN") -> dict:
    old = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    new = old.replace(f"status: {frm}", f"status: {to}")
    return check_register_transitions(ws, new, old)


# ------------------------------------------------- the certification row

def test_mint_replay_roundtrip_byte_consistent(tmp_path):
    """THE pin: certification line -> replay -> result consistent."""
    ws = _ws(tmp_path)
    _register(ws)
    _legs(ws)
    res = _mint(ws)
    assert res.get("ok") is True, res
    row = ec.read_certification(ws, CLAIM)
    assert row is not None
    assert row["schema"] == ec.CERT_SCHEMA
    assert row["evidence_class"] == ec.CERT_CLASS
    ok, detail = ec.replay(ws, CLAIM)
    assert ok is True, detail


def test_replay_refuses_tampered_expect(tmp_path):
    ws = _ws(tmp_path)
    _register(ws)
    _legs(ws)
    assert _mint(ws)["ok"] is True
    p = ec.cert_path(ws, CLAIM)
    row = json.loads(p.read_text(encoding="utf-8"))
    row["replay"]["expect_sha256"] = "0" * 64
    p.write_text(json.dumps(row), encoding="utf-8")
    ok, detail = ec.replay(ws, CLAIM)
    assert ok is False
    assert "sha" in detail.lower()


def test_admission_refuses_swapped_artifact(tmp_path):
    """The identity chain: the row pins its evidence artifacts' bytes —
    an artifact rewritten after the mint breaks the chain (the trace
    93/7108 identity break, closed)."""
    ws = _ws(tmp_path)
    _register(ws)
    _legs(ws)
    assert _mint(ws)["ok"] is True
    p = ws / "evidence" / f"replay-{CLAIM}.json"
    doc = dict(REPLAY_ARTIFACT)
    doc["pairs"] = [dict(REPLAY_ARTIFACT["pairs"][0],
                         repro_output="w=TAMPERED")]
    doc["pairs"][0]["byte_equal"] = False
    p.write_text(json.dumps(doc), encoding="utf-8")
    ok, why = ec.admission(ws, CLAIM)
    assert ok is False
    assert "identit" in why.lower() or "sha" in why.lower()


def test_mint_refuses_missing_legs(tmp_path):
    ws = _ws(tmp_path)
    _register(ws)
    res = _mint(ws)
    assert res.get("ok") is False
    assert not ec.cert_path(ws, CLAIM).exists()


def test_mint_refuses_unaccepted_fresh_input(tmp_path):
    ws = _ws(tmp_path)
    _register(ws)
    _legs(ws)
    fresh = dict(FRESH_ARTIFACT)
    fresh["inputs"] = [dict(FRESH_ARTIFACT["inputs"][0], accepted=False)]
    (ws / "evidence" / f"fresh-{CLAIM}.json").write_text(
        json.dumps(fresh), encoding="utf-8")
    assert _mint(ws)["ok"] is False


# ------------------------------------- F009 shape promotes on replay ----

def test_f009_shape_admits_proven_without_redteam(tmp_path):
    """The inversion's head: byte-exact + fresh-input accepted promotes
    PROVEN with NO dispatch-cycle records at all — evidence class is
    read first, red-team is not a toll."""
    ws = _ws(tmp_path)
    _register(ws)
    _legs(ws)
    assert _mint(ws)["ok"] is True
    res = _transition(ws)
    assert res["ok"] is True, res["violations"]
    assert res["violations"] == []


def test_admitted_cert_resolves_as_verification_record(tmp_path):
    """The #809/#800 consumption chain: the certification row IS a
    resolvable PASSED verification record — claims_store.apply's
    settle_proven face can cite it without any new semantics."""
    ws = _ws(tmp_path)
    _register(ws)
    _legs(ws)
    assert _mint(ws)["ok"] is True
    ok, word, detail = resolve_verification(
        ws, CLAIM, f"evidence/cert-{CLAIM}.json")
    assert ok is True, detail
    assert word == "passed"


def test_broken_replay_falls_back_to_legacy_legs(tmp_path):
    """A certification that fails its own replay is worse than none —
    admission refuses and the legacy verify/red-team legs stay
    enforced (never a blind bypass)."""
    ws = _ws(tmp_path)
    _register(ws)
    _legs(ws, script_body="print('MUTATED', end='')\n")
    assert _mint(ws)["ok"] is True
    # break the replay AFTER the mint: the pinned expect no longer matches
    (ws / "runs" / f"replay-{CLAIM}.py").write_text(
        "print('OTHER-BYTES', end='')\n", encoding="utf-8")
    ok, _why = ec.admission(ws, CLAIM)
    assert ok is False
    res = _transition(ws)
    assert res["ok"] is False
    assert any("verify-note" in v for v in res["violations"])


def test_no_cert_legacy_legs_unchanged(tmp_path):
    """No certification row: the gate behaves exactly as #819/#825 left
    it (verify-note + red-team + identity, or refusal)."""
    ws = _ws(tmp_path)
    _register(ws)
    res = _transition(ws)
    assert res["ok"] is False
    assert any("C-001" in v for v in res["violations"])


# ------------------------------------ the scaffold inversion pinned dead

def test_scaffold_redteam_alone_refused(tmp_path):
    """THE inversion pinned dead: a scaffold-only claim with no
    evidence class can NO LONGER reach PROVEN via red-team alone."""
    ws = _ws(tmp_path)
    _register(ws, extra="claim_class: scaffold")
    (ws / "runs" / f"2026-10-25-verify-{CLAIM}.md").write_text(
        f"---\nclaim_id: {CLAIM}\n---\n\n## Overall verdict\npasses\n",
        encoding="utf-8")
    (ws / "runs" / f"verify-redteam-{CLAIM}.md").write_text(
        f"---\ntarget: {CLAIM}\n---\n\nRED-TEAM VERDICT: CONFIRMED\n"
        f"claim: {CLAIM}\n\nverifier-identity: rt-worker-1\n",
        encoding="utf-8")
    res = _transition(ws)
    assert res["ok"] is False
    assert any("scaffold" in v.lower() for v in res["violations"])


def test_scaffold_with_evidence_class_admitted(tmp_path):
    """A scaffold claim whose facts DO declare a non-triage evidence
    class is not the inverted shape — the legacy legs decide."""
    ws = _ws(tmp_path)
    _register(ws, extra="claim_class: scaffold")
    (ws / "facts").mkdir()
    (ws / "facts" / "F001-scaffold-ev.md").write_text(
        "---\nid: F001-scaffold-ev\ntype: fact\ntitle: t\n"
        f"status: INFERRED\ncreated: 2026-10-25\nlast_reviewed: 2026-10-25\n"
        f"source: static-decompile\nconfidence: medium\nclaim_id: {CLAIM}\n"
        "boundary_type: observation\npromotion_gate: g\nprovenance:\n"
        "  - {role: decompiled_c, path: evidence/x.json, "
        "content_sha256: " + "a" * 64 + ", credibility: A2}\n"
        "claim: c\nreproduce: r\nexpected: e\nverified: v\n"
        "evidence_class: decompile\n---\n\nbody\n",
        encoding="utf-8")
    (ws / "runs" / f"2026-10-25-verify-{CLAIM}.md").write_text(
        f"---\nclaim_id: {CLAIM}\n---\n\n## Overall verdict\npasses\n",
        encoding="utf-8")
    (ws / "runs" / f"verify-redteam-{CLAIM}.md").write_text(
        f"---\ntarget: {CLAIM}\n---\n\nRED-TEAM VERDICT: CONFIRMED\n"
        f"claim: {CLAIM}\n\nverifier-identity: rt-worker-1\n",
        encoding="utf-8")
    res = _transition(ws)
    assert res["ok"] is True, res["violations"]


def test_plain_claim_redteam_path_unchanged(tmp_path):
    """Non-scaffold claims keep the #819 shape verbatim (no evidence
    class needed when the claim is not scaffold)."""
    ws = _ws(tmp_path)
    _register(ws)
    (ws / "runs" / f"2026-10-25-verify-{CLAIM}.md").write_text(
        f"---\nclaim_id: {CLAIM}\n---\n\n## Overall verdict\npasses\n",
        encoding="utf-8")
    (ws / "runs" / f"verify-redteam-{CLAIM}.md").write_text(
        f"---\ntarget: {CLAIM}\n---\n\nRED-TEAM VERDICT: CONFIRMED\n"
        f"claim: {CLAIM}\n\nverifier-identity: rt-worker-1\n",
        encoding="utf-8")
    assert _transition(ws)["ok"] is True


# ------------------------------------------- web frontmatter contract ---

WEB_FACT = (
    "---\n"
    "id: F001-web-slim\n"
    "type: fact\n"
    "title: w parameter reproduces byte-exact\n"
    "status: PROVEN\n"
    "source: fresh-input\n"
    f"claim_id: {CLAIM}\n"
    "---\n"
    "\nbody\n"
)


def _task_spec(ws: Path, lane: str | None) -> None:
    doc = "lane: %s\n" % lane if lane else ""
    (ws / "task_spec.yaml").write_text(doc, encoding="utf-8")


def test_web_lane_slim_contract_lints_clean(tmp_path):
    """Pin 3: the web fact frontmatter contract is <=6 mandatory
    fields — a 6-field web fact with a web-native source lints clean
    (no malware-schema ceremony errors)."""
    ws = _ws(tmp_path)
    _task_spec(ws, "web")
    (ws / "facts").mkdir()
    (ws / "facts" / "F001-web-slim.md").write_text(WEB_FACT,
                                                   encoding="utf-8")
    errors, _warnings = lint_facts.lint_workspace(ws)
    assert errors == [], errors


def test_default_lane_keeps_full_contract(tmp_path):
    """The 12-mandatory malware contract is untouched off the web
    lane: the same slim fact carries MISSING_* errors there."""
    ws = _ws(tmp_path)
    _task_spec(ws, "malware")
    (ws / "facts").mkdir()
    (ws / "facts" / "F001-web-slim.md").write_text(WEB_FACT,
                                                   encoding="utf-8")
    errors, _warnings = lint_facts.lint_workspace(ws)
    codes = {c for _s, c, _m in errors}
    assert {"MISSING_CREATED", "MISSING_PROVENANCE",
            "MISSING_BOUNDARY_TYPE"} <= codes, codes


def test_web_source_enum_registered(tmp_path):
    """The web-native source enum, registered in ONE place and honored
    by the status x source matrix on the web lane."""
    assert ec.WEB_SOURCE_ENUM == ("capture", "replay", "fresh-input",
                                  "offline-execution")
    ws = _ws(tmp_path)
    _task_spec(ws, "web")
    (ws / "facts").mkdir()
    (ws / "facts" / "F001-web-slim.md").write_text(
        WEB_FACT.replace("status: PROVEN", "status: PROVEN")
                .replace("source: fresh-input", "source: offline-execution"),
        encoding="utf-8")
    errors, _warnings = lint_facts.lint_workspace(ws)
    assert not any("SOURCE" in c for _s, c, _m in errors), errors


def test_web_source_illegal_off_lane(tmp_path):
    """Off the web lane the web-native sources are NOT in the enum —
    the lane contract does not leak into the malware projection."""
    ws = _ws(tmp_path)
    (ws / "facts").mkdir()
    (ws / "facts" / "F001-web-slim.md").write_text(WEB_FACT,
                                                   encoding="utf-8")
    errors, _warnings = lint_facts.lint_workspace(ws)
    assert any("BAD_SOURCE_ENUM" in c for _s, c, _m in errors), errors
