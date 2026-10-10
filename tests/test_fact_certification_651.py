# -*- coding: utf-8 -*-
"""tests/test_fact_certification_651.py — the fact-certification gate
(issue 651, findings 4-L2/L3 + the 5-F4 reward side).

The farm being closed: Φ's fact dimension counted a fact as verified
iff its frontmatter `status` said PROVEN/VERIFIED (worker-written at
creation), and `_facts_citing` was a claim-id substring scan over the
first 2000 chars — two junk files with `status: VERIFIED` farmed
positive reward through facts_citing → credit → phi_delta → posterior →
store row.

The gate: a terminal fact status is honored only when REGISTER-BACKED
(every claim the fact cites is PROVEN in claim-register.yaml — the
promotion gate is the only sanctioned writer of that status, ws_yaml
single-writer + the claims-count wall). Static inflation cancels inside
ΔΦ (potential-based shaping); the farmable shape is precisely the
premature self-declared terminal status, which register-backing refuses.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import lint_facts  # noqa: E402
from rlvr import state  # noqa: E402
from e2e import checkpoints, llm_faces, model  # noqa: E402
from test_e2e_runner import (  # noqa: E402
    ANCHORS, DERIVE_PY, FakeClock, ScriptedRunner, TASK_YAML)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    return ws


def _register(ws: Path, claim: str = "C-005", status: str =
              "PARTIALLY-VERIFIED") -> None:
    (ws / "claim-register.yaml").write_text(
        f"claims:\n  - id: {claim}\n    status: {status}\n"
        "    question: q\n", encoding="utf-8")


_SHA = "b" * 64

CLEAN_HEAD = (
    "id: {fid}\ntype: fact\ntitle: t\n"
    "created: 2026-10-11\nlast_reviewed: 2026-10-11\n"
    "boundary_type: confirmed\npromotion_gate:\n"
    "provenance:\n"
    "  - role: public_doc\n"
    "    path: facts/{fid}.md\n"
    f"    content_sha256: {{sha}}\n"
    "    credibility: B2\n"
    "claim: claim statement text\n"
    "reproduce: cmd\nexpected: out\nverified: pending\n")


def _fact(fm_status: str, source: str, confidence: str,
          claim_ref: str = "claim_id: C-005",
          fid: str = "F001-decrypt-key") -> str:
    head = CLEAN_HEAD.format(fid=fid, sha=_SHA)
    return (f"---\n{head}{claim_ref}\nstatus: {fm_status}\n"
            f"source: {source}\nconfidence: {confidence}\n---\n\n"
            "body\n\n## Code excerpt\n\nmov eax, 1\n")


def _errors(defects: list) -> list[str]:
    return [str(d[1]) for d in defects if d[0] == "error"]


# ------------------------------------------------- the certification gate

def test_promotion_backed_terminal_certifies(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PROVEN")
    fm = lint_facts.parse_frontmatter(_fact("PROVEN", "public-osint",
                                            "high"))[0]
    proven = lint_facts.read_register_proven(ws)
    assert proven == {"C-005"}
    assert _errors(lint_facts.certification_defects(
        fm, "body", proven, {"F001"})) == []


def test_fabricated_terminal_is_refused(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PARTIALLY-VERIFIED")   # the settle-time shape
    fm = lint_facts.parse_frontmatter(_fact("VERIFIED", "dynamic-trace",
                                            "high"))[0]
    defects = lint_facts.certification_defects(
        fm, "body", lint_facts.read_register_proven(ws), {"F001"})
    assert any("register" in str(d) for d in defects)


def test_claim_less_terminal_is_uncertifiable(tmp_path) -> None:
    fm = lint_facts.parse_frontmatter(
        _fact("PROVEN", "dynamic-trace", "high", claim_ref=""))[0]
    defects = lint_facts.certification_defects(fm, "body", {"C-005"},
                                               {"F001"})
    assert any("citation" in str(d) or "cite" in str(d) for d in defects)


def test_non_terminal_carries_no_certification_defect(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PARTIALLY-VERIFIED")
    fm = lint_facts.parse_frontmatter(_fact("INFERRED", "inference",
                                            "medium"))[0]
    errs = _errors(lint_facts.certification_defects(
        fm, "body", lint_facts.read_register_proven(ws), {"F001"}))
    assert not any("register" in e for e in errs)


def test_grammar_errors_disqualify(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PROVEN")
    fm = lint_facts.parse_frontmatter(
        "---\nstatus: PROVEN\nclaim_id: C-005\n---\n\nbody\n")[0]
    errs = _errors(lint_facts.certification_defects(
        fm, "body", {"C-005"}, {"F001"}))
    assert errs, "a grammar-broken fact is uncertified regardless"


def test_read_register_proven_tolerant(tmp_path) -> None:
    ws = _ws(tmp_path)
    assert lint_facts.read_register_proven(ws) == set()
    _register(ws, status="PROVEN")
    (ws / "claim-register.yaml").write_text("::{ broken", encoding="utf-8")
    assert lint_facts.read_register_proven(ws) == set()


# ------------------------------------------------------- fact_face ----

def test_fact_face_junk_verified_not_counted(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PARTIALLY-VERIFIED")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        _fact("VERIFIED", "dynamic-trace", "high"), encoding="utf-8")
    (ws / "facts" / "F002-second.md").write_text(
        _fact("VERIFIED", "dynamic-trace", "high",
              fid="F002-second"), encoding="utf-8")
    face = state.fact_face(ws)
    assert face["count"] == 2
    assert face["verified"] == 0, "fabricated terminals are not verified"


def test_fact_face_promotion_lights_the_dim(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PROVEN")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        _fact("PROVEN", "dynamic-trace", "high"), encoding="utf-8")
    face = state.fact_face(ws)
    assert face["verified"] == 1


def test_fact_face_claim_less_terminal_not_verified(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PROVEN")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        _fact("PROVEN", "dynamic-trace", "high", claim_ref=""),
        encoding="utf-8")
    assert state.fact_face(ws)["verified"] == 0


def test_fact_face_junk_file_counts_toward_presence_only(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PARTIALLY-VERIFIED")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        "junk prose mentioning C-005\n", encoding="utf-8")
    face = state.fact_face(ws)
    assert face == {"count": 1, "verified": 0}


# ---------------------------------------------------- _facts_citing ----

def test_facts_citing_exact_citation_counts(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PARTIALLY-VERIFIED")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        _fact("INFERRED", "inference", "medium"), encoding="utf-8")
    assert checkpoints._facts_citing(ws, "C-005") == 1


def test_facts_citing_body_mention_counts_nothing(tmp_path) -> None:
    """The retired substring scan: a body mention without a frontmatter
    citation never counts."""
    ws = _ws(tmp_path)
    _register(ws, status="PARTIALLY-VERIFIED")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        _fact("INFERRED", "inference", "medium",
              claim_ref="claim_id: C-009") + "\nsee also C-005\n",
        encoding="utf-8")
    assert checkpoints._facts_citing(ws, "C-005") == 0


def test_facts_citing_fabricated_terminal_excluded(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PARTIALLY-VERIFIED")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        _fact("VERIFIED", "dynamic-trace", "high"), encoding="utf-8")
    assert checkpoints._facts_citing(ws, "C-005") == 0


def test_facts_citing_plural_citation_counts(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-005\n    status: PARTIALLY-VERIFIED\n"
        "    question: q\n  - id: C-006\n    status: OPEN\n"
        "    question: q2\n", encoding="utf-8")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        _fact("INFERRED", "inference", "medium",
              claim_ref="claim_id: C-005\nclaim_ids: [C-005, C-006]"),
            encoding="utf-8")
    assert checkpoints._facts_citing(ws, "C-005") == 1


def test_facts_citing_junk_file_counts_nothing(tmp_path) -> None:
    ws = _ws(tmp_path)
    _register(ws, status="PARTIALLY-VERIFIED")
    (ws / "facts" / "F001-decrypt-key.md").write_text(
        "---\nstatus: VERIFIED\nclaim_id: C-005\n---\njunk\n",
        encoding="utf-8")
    assert checkpoints._facts_citing(ws, "C-005") == 0


# ------------------------------------------ the farming-chain closure ----

_JUNK_FACT = ("---\nstatus: VERIFIED\nclaim_id: C-005\n---\n"
              "junk body mentioning C-005\n")


@pytest.fixture()
def stub_repo(tmp_path):
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/smoke/py-derive-v1"
    (task / "target").mkdir(parents=True)
    (task / "target/derive.py").write_text(DERIVE_PY, encoding="utf-8")
    (task / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (repo / "scripts").mkdir()
    return repo


def _make_ctx(stub_repo, tmp_path, ws_name: str):
    ws = tmp_path / ws_name
    ev_dir = tmp_path / f"{ws_name}-ev"
    ws.mkdir()
    (ws / "runs").mkdir()
    (ws / "facts").mkdir()
    state = model.RunState(
        run_id="a1", unit="py-derive-v1", family="smoke",
        repo=str(stub_repo),
        task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
        ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=10_000,
        llm_mode="auto", started_ts="t", started_monotonic=0.0,
        anchors=dict(ANCHORS))
    return checkpoints.RunContext(
        state=state, runner=ScriptedRunner(),
        face=llm_faces.face_for("auto", ScriptedRunner(), ev_dir),
        clock=FakeClock(), sleep_fn=lambda _s: None), ws


def _seed_dispatch(ctx, ws, claim: str = "C-005") -> None:
    (ws / "claim-register.yaml").write_text(
        f"claims:\n  - id: {claim}\n    status: PARTIALLY-VERIFIED\n"
        "    question: q\n", encoding="utf-8")
    qc = checkpoints._load_repo_module(ctx.repo, "rlvr.q_cells")
    out = qc.record_dispatch_observation(
        str(ws), "the dispatch prompt text",
        envelope_meta={"method_family": "smoke",
                       "action_type": "dispatch",
                       **checkpoints._DISPATCH_ARM_CONTEXT},
        claim=claim, fingerprint=None)
    assert out.get("appended"), out


def _run_settle(ctx, ws, claim: str = "C-005") -> dict:
    from rlvr import incremental_reward as ir
    ir.record_launch(str(ws), claim, "smoke", phi=0.0)
    act = types.SimpleNamespace(outcome="DISPATCHED",
                                detail={"duration_ms": 1000},
                                mode="dispatch")
    checkpoints._settle_dispatch_outcome(ctx, claim, act, attempt_id="")
    rows = [json.loads(line) for line in
            (ws / "runs" / "transitions.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows, "the transition row must land"
    return rows[-1]


def _store_rows(store_dir: Path) -> list[dict]:
    p = Path(store_dir) / "posterior-store.jsonl"
    if not p.is_file():
        return []
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_farming_chain_nets_zero(stub_repo, tmp_path, monkeypatch) -> None:
    """The audit's two-junk-files farm, driven through the REAL settle
    path: the credit equals the no-facts baseline, the store row carries
    facts_citing 0, and the banked observation matches the no-facts
    run."""
    junk_store = tmp_path / "junk-store"
    base_store = tmp_path / "base-store"
    junk_store.mkdir()
    base_store.mkdir()

    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(junk_store))
    junk_ctx, junk_ws = _make_ctx(stub_repo, tmp_path, "junk-ws")
    _seed_dispatch(junk_ctx, junk_ws)
    (junk_ws / "facts" / "F001-decrypt-key.md").write_text(
        _JUNK_FACT, encoding="utf-8")
    (junk_ws / "facts" / "F002-second-key.md").write_text(
        _JUNK_FACT.replace("F002-second-key", "F001-decrypt-key"),
        encoding="utf-8")
    junk_row = _run_settle(junk_ctx, junk_ws)

    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(base_store))
    base_ctx, base_ws = _make_ctx(stub_repo, tmp_path, "base-ws")
    _seed_dispatch(base_ctx, base_ws)
    base_row = _run_settle(base_ctx, base_ws)

    # the credit: the junk facts contribute NOTHING (0.5 == the
    # no-facts success), where the old substring scan banked 1.0
    assert junk_row["r_settle"] == 0.5
    assert base_row["r_settle"] == 0.5
    assert junk_row["r_settle"] == base_row["r_settle"]
    # the potential shape: no junk lift rides phi_delta either
    assert junk_row["phi_before"] == base_row["phi_before"]
    assert junk_row["s_prime_phi"] == base_row["s_prime_phi"]
    # the store row: facts_citing 0, credit identical to the baseline
    junk_rows = [r for r in _store_rows(junk_store)
                 if (r.get("provenance") or {}).get("dispatch_id")
                 == "C-005"]
    base_rows = [r for r in _store_rows(base_store)
                 if (r.get("provenance") or {}).get("dispatch_id")
                 == "C-005"]
    assert junk_rows and junk_rows[-1]["facts_citing"] == 0
    assert junk_rows[-1]["credit"] == base_rows[-1]["credit"]
