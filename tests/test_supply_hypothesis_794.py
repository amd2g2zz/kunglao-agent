#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_supply_hypothesis_794.py — #794 P1 supply side.

Claim birth = hypothesis birth (the supply discipline): every code-level
claim mint path files >= 1 OPEN hypothesis linked to the newborn claim, so
the exploration layer can never stay empty while claims flow (the
production shape: 51job 8 claims / ctf-1 10 claims -> zero H-* files).

Pins:
  1. the split fan-out (mint_split_claims) stubs every minted sub-claim;
  2. the obstacle promotion (failure_analysis_gate) stubs the new claim;
  3. the stub primitive is idempotent, claim-linked, and pq-bound when the
     claim answers a primary question;
  4. both mint modules stay off the hypothesis-writer offender list (the
     static writer pin — they must import the bridge, not raw-write).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

import claim_granularity as cg  # noqa: E402

# ---------- fixtures (same shapes as test_claim_granularity_241) ----------


def _write_reg(ws: Path, claims: list[dict]) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True,
                       sort_keys=False), encoding="utf-8")


def _load_reg(ws: Path) -> dict:
    return yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}


def _parent_claim(cid: str = "C-001") -> dict:
    return {
        "id": cid,
        "status": "OPEN",
        "boundary_type": "task",
        "evidence_tier_attempted": 0,
        "promotion_attempts": 0,
        "statement": "Reverse white-box crypto core - safeEncrypt whitebox VM",
        "answers_question": "q1",
    }


def _static(i: int) -> str:
    return f"static pass {i}: disasm the .rela.dyn array with ghidra"


def _dynamic(i: int) -> str:
    return f"dynamic pass {i}: frida attach and trace the VM dispatch loop"


def _network(i: int) -> str:
    return ("network pass {i}: replay the captured web-session traffic "
            "from the pcap").format(i=i)


def _plan(steps: list[str], prefix: str = "goal: reverse the core\n") -> str:
    body = "".join(f"{i}. {s}\n" for i, s in enumerate(steps, 1))
    return f"{prefix}steps:\n{body}fallback: rerun with logs\n"


def _monolithic_12() -> str:
    return _plan([_static(i) for i in range(1, 5)]
                 + [_dynamic(i) for i in range(1, 5)]
                 + [_network(i) for i in range(1, 5)])


def _seed_plan(ws: Path, text: str, name: str = "plan-C001.md") -> None:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "runs" / name).write_text(text, encoding="utf-8")


def _hypotheses(ws: Path) -> list[dict]:
    """Parsed frontmatter of every hypotheses/H-*.md (tolerant split)."""
    hyp_dir = ws / "hypotheses"
    if not hyp_dir.is_dir():
        return []
    out = []
    for p in sorted(hyp_dir.glob("H-*.md")):
        text = p.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        fm = text.split("---\n", 2)[1]
        row = {}
        for ln in fm.splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                row[k.strip()] = v.strip()
        out.append(row)
    return out


# ---------- 1. the split fan-out stubs every minted sub-claim ----------

def test_split_mint_files_hypothesis_stub_per_sub_claim(tmp_path):
    ws = tmp_path / "ws"
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _monolithic_12())
    r = cg.mint_split_claims(ws, "C-001")
    assert r["refused"] is None, r
    assert r["minted"], "a monolithic plan must split into sub-claims"
    hyps = _hypotheses(ws)
    assert hyps, "RED (#794): the split mint left the hypothesis layer empty"
    sub_ids = {row["id"] for row in r["minted"]}
    stub_claim_ids = {h.get("claim_id") for h in hyps}
    assert sub_ids <= stub_claim_ids, (
        f"every minted sub-claim needs a stub: {sub_ids} vs {hyps}")
    for h in hyps:
        if h.get("claim_id") in sub_ids:
            assert h.get("status") == "open", h
            cands = str(h.get("candidates") or "")
            assert cands not in ("", "[]"), (
                f"a birth stub carries >= 1 candidate: {h}")


def test_split_stub_is_pq_bound_when_parent_answers_a_question(tmp_path):
    ws = tmp_path / "ws"
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _monolithic_12())
    r = cg.mint_split_claims(ws, "C-001")
    assert r["refused"] is None, r
    hyps = _hypotheses(ws)
    assert hyps
    # pq-bound: body marker pq:q1 so the #109 admission face sees the stub
    bodies = [p.read_text(encoding="utf-8")
              for p in sorted((ws / "hypotheses").glob("H-*.md"))]
    assert any("pq:q1" in b for b in bodies), bodies


# ---------- 2. the obstacle promotion stubs the new claim ----------

def test_obstacle_promotion_files_hypothesis_stub(tmp_path):
    import failure_analysis_gate as fag
    ws = tmp_path / "ws"
    claims = [_parent_claim("C-001")]
    reg = {"claims": claims}
    _write_reg(ws, claims)
    r = fag._promote_obstacle_claim(ws, "C-001", "frida attach blocked by "
                                    "anti-debug ptrace guard",
                                    claims[0], claims, reg,
                                    obstacle_class="anti-debug")
    assert r["created"] is True and r["id"], r
    new_id = r["id"]
    # persist what the real caller persists (the record path writes reg)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    hyps = _hypotheses(ws)
    assert hyps, "RED (#794): obstacle promotion left hypotheses/ empty"
    assert any(h.get("claim_id") == new_id for h in hyps), hyps
    for h in hyps:
        if h.get("claim_id") == new_id:
            assert h.get("status") == "open", h


# ---------- 3. the stub primitive: idempotent, linked, bound ----------

def test_ensure_claim_stub_is_idempotent_and_linked(tmp_path):
    from hypothesis_bridge import ensure_claim_stub
    from hypothesis_store import HypothesisStore
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    h1 = ensure_claim_stub(ws, claim_id="C-009", statement="recover the "
                           "header mac", qid="q2")
    h2 = ensure_claim_stub(ws, claim_id="C-009", statement="recover the "
                           "header mac", qid="q2")
    assert h1.id == h2.id, "the stub must be idempotent per claim"
    store = HypothesisStore(ws / "hypotheses")
    all_h = store.list_all()
    assert len(all_h) == 1, all_h
    assert all_h[0].claim_id == "C-009"
    assert all_h[0].status == "open"
    assert any(str(c).strip() for c in all_h[0].candidates), all_h[0]
    assert "pq:q2" in (all_h[0].body or "")


def test_mint_modules_stay_off_the_writer_offender_list():
    """The static writer pin: claim_granularity and failure_analysis_gate
    write hypotheses/ only THROUGH the bridge (a real import line)."""
    from hypothesis_bridge import writer_scan_offenders
    scripts_dir = Path(cg.__file__).resolve().parent
    offenders = writer_scan_offenders(scripts_dir)
    bad = [o for o in offenders
           if o.split("/", 1)[-1] in ("claim_granularity.py",
                                      "failure_analysis_gate.py")]
    assert not bad, bad
