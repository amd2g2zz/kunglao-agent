# -*- coding: utf-8 -*-
"""Tests for #234 — the target/attack-surface ladder + strategy fan-out.

Fast tier (tests/_tiers.py FAST_MODULES): pure unit — no process spawns,
no network, no nested pytest (the _FAST_BANNED source scan enforces the
same rule). The hook-face wiring lives in
tests/test_obstacle_ladder_integration.py (integration leg).

Contract (issue #234, RED first):

- the third ladder: 3 levels (T1/T2/T3) of mechanism-family rungs per
  obstacle class; levels are mechanism-family distinct BY CONSTRUCTION —
  two same-family rungs make the ladder INVALID; instrument availability
  annotates rungs and never filters them; an unknown obstacle class falls
  back to the generic enumeration (never unwalkable).
- obstacle settlement: an obstacle claim (origin: failure-obstacle) cannot
  settle CONFIRMED (PROVEN) without its target ladder walked + non-empty
  exhaustion inventory + minted strategy siblings — rejected with the NAMED
  TARGET LADDER GATE reason.
- fan-out: each inventory entry auto-registers a sibling claim
  (origin: obstacle-alternative, obstacle_for edge, answers_question
  inherited, real claim_deps.yaml edge) — OPEN, hence in the TS rank pool
  (priority_ratio.is_open). Minting is idempotent.
- 3-strike: dead_letter.record_dispatch_failure increments
  promotion_attempts (the writer #146 said the family lacked) and routes
  the claim to the DLQ at 3 strikes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

import target_ladder as tl  # noqa: E402
import dead_letter as dl  # noqa: E402
import kunglao_record  # noqa: E402
import priority_ratio  # noqa: E402
import worker_budget as wb  # noqa: E402  (the #568 shim; backstop lives in gates)


# ---------- helpers ----------

def _write_reg(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _load_reg(ws: Path) -> dict:
    return yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}


def _write_ladder(ws: Path, claim_id: str, ladder: dict | None) -> None:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f"target-ladder-{claim_id}.yaml"
    if ladder is None:
        return
    p.write_text(yaml.safe_dump(ladder, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")


def _walked_ladder(families: tuple[str, ...] | None = None) -> dict:
    fams = families or tl.OBSTACLE_CLASS_FAMILIES["interception"][:3]
    return {
        "obstacle_class": "interception",
        "attempts": [
            {"level": f"T{i + 1}", "family": fam,
             "action": f"try {fam}", "outcome": "blocked",
             "instrument": "frida unavailable (annotated, not filtering)"}
            for i, fam in enumerate(fams)
        ],
        "inventory": [
            {"family": fam, "tried": f"{fam} pass on the target",
             "failed_because": "pinning rejects the rebuilt artifact"}
            for fam in fams
        ],
    }


# ---------- REQ 1: ladder vocabulary + family distinctness ----------

def test_interception_enumeration_is_the_issue_example():
    assert tl.family_ladder_for("interception") == (
        "hooking", "repackaging", "ca-install", "proxy-interposition")


def test_walked_ladder_has_no_defects():
    ws_ladder = _walked_ladder()
    assert tl.ladder_defects(ws_ladder) == []


def test_missing_levels_are_named():
    ladder = _walked_ladder()
    ladder["attempts"] = ladder["attempts"][:1]  # only T1
    defects = tl.ladder_defects(ladder)
    assert any("T2" in d and "T3" in d for d in defects), defects


def test_same_family_rungs_make_ladder_invalid():
    ladder = _walked_ladder(("hooking", "hooking", "repackaging"))
    defects = tl.ladder_defects(ladder)
    assert any("family-repeat" in d and "hooking" in d for d in defects), defects


def test_unknown_family_for_class_defects():
    ladder = _walked_ladder(("hooking", "repackaging", "memory-imaging"))
    defects = tl.ladder_defects(ladder)
    assert any("memory-imaging" in d for d in defects), defects


def test_unknown_class_falls_back_and_walks():
    assert tl.family_ladder_for("who-knows") == tl.FAMILY_FALLBACK
    assert tl.family_ladder_for(None) == tl.FAMILY_FALLBACK
    ladder = {
        "attempts": [
            {"level": f"T{i + 1}", "family": fam, "action": "a",
             "outcome": "blocked"}
            for i, fam in enumerate(tl.FAMILY_FALLBACK)
        ],
        "inventory": [],
    }
    assert tl.ladder_defects(ladder) == [], tl.ladder_defects(ladder)


def test_instrument_annotation_never_filters():
    """A rung whose instrument is unavailable still counts as walked."""
    ladder = _walked_ladder()
    for a in ladder["attempts"]:
        a["instrument"] = "unavailable"
    assert tl.ladder_defects(ladder) == []


def test_absent_ladder_names_all_levels():
    defects = tl.ladder_defects(None)
    assert any("T1" in d and "T3" in d for d in defects), defects


# ---------- REQ 2: obstacle settlement exhaustion gate ----------

def _obstacle_claim(claim_id: str = "C-005",
                    obstacle_class: str | None = "interception") -> dict:
    claim = {"id": claim_id, "status": "OPEN",
             "origin": "failure-obstacle", "obstacle_for": "C-002",
             "answers_question": "q1",
             "statement": "Obstacle (from C-002): CA pinning"}
    if obstacle_class is not None:
        claim["obstacle_class"] = obstacle_class
    return claim


def test_blocker_silent_for_non_obstacle_claim(tmp_path):
    _write_reg(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    assert tl.settlement_blocker(tmp_path, "C-1") is None


def test_blocker_names_missing_ladder(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    blocker = tl.settlement_blocker(tmp_path, "C-005")
    assert blocker is not None
    assert "TARGET LADDER GATE" in blocker
    assert "T1" in blocker and "T3" in blocker, blocker


def test_blocker_names_empty_inventory(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    ladder = _walked_ladder()
    ladder["inventory"] = []
    _write_ladder(tmp_path, "C-005", ladder)
    blocker = tl.settlement_blocker(tmp_path, "C-005")
    assert blocker is not None and "TARGET LADDER GATE" in blocker
    assert "inventory" in blocker, blocker


def test_blocker_names_unminted_sibling(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    blocker = tl.settlement_blocker(tmp_path, "C-005")
    assert blocker is not None and "TARGET LADDER GATE" in blocker
    assert "--mint C-005" in blocker, blocker


def test_blocker_defects_unpinned_class(tmp_path):
    """F2: no obstacle_class pinned on the claim at promotion -> defect
    (fail-closed) — there is no authoritative enumeration to walk against."""
    _write_reg(tmp_path, [_obstacle_claim(obstacle_class=None)])
    blocker = tl.settlement_blocker(tmp_path, "C-005")
    assert blocker is not None and "TARGET LADDER GATE" in blocker
    assert "not pinned" in blocker, blocker


def test_blocker_defects_artifact_class_missing(tmp_path):
    """F2: the artifact must DECLARE the claim-pinned class."""
    _write_reg(tmp_path, [_obstacle_claim()])
    ladder = _walked_ladder()
    del ladder["obstacle_class"]
    _write_ladder(tmp_path, "C-005", ladder)
    blocker = tl.settlement_blocker(tmp_path, "C-005")
    assert blocker is not None and "TARGET LADDER GATE" in blocker
    assert "declares no obstacle_class" in blocker, blocker


def test_blocker_defects_class_tamper(tmp_path):
    """F2: the artifact author re-declares a DIFFERENT class to walk a
    smaller pool -> mismatch defect; the enumeration stays keyed on the
    claim-pinned class."""
    _write_reg(tmp_path, [_obstacle_claim()])
    ladder = _walked_ladder()
    ladder["obstacle_class"] = "visibility"  # tampered: 3-family pool
    ladder["attempts"] = [
        {"level": f"T{i + 1}", "family": fam, "action": "a", "outcome": "b"}
        for i, fam in enumerate(tl.OBSTACLE_CLASS_FAMILIES["visibility"])
    ]
    ladder["inventory"] = [
        {"family": fam, "tried": "x", "failed_because": "y"}
        for fam in tl.OBSTACLE_CLASS_FAMILIES["visibility"]
    ]
    _write_ladder(tmp_path, "C-005", ladder)
    blocker = tl.settlement_blocker(tmp_path, "C-005")
    assert blocker is not None and "TARGET LADDER GATE" in blocker
    assert "'visibility' != claim-pinned 'interception'" in blocker, blocker


def test_blocker_single_parse_no_reread(tmp_path, monkeypatch):
    """Review r2 MEDIUM (the #237 H1 two-read class): with register_text
    supplied, the sibling checks consume the SAME parsed snapshot — the
    register file is never read a second time (no TOCTOU window)."""
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    tl.mint_sibling_claims(tmp_path, "C-005")
    text = (tmp_path / "claim-register.yaml").read_text(encoding="utf-8")
    calls: list = []

    def _spy(ws):
        calls.append(ws)
        return [], None

    monkeypatch.setattr(tl, "_load_claims", _spy)
    blocker = tl.settlement_blocker(tmp_path, "C-005", register_text=text)
    assert blocker is None
    assert calls == [], "register_text supplied: no file read may happen"


def test_blocker_single_read_without_text(tmp_path, monkeypatch):
    """Without register_text, exactly ONE register read serves the whole
    gate (origin/class lookup AND the sibling checks)."""
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    tl.mint_sibling_claims(tmp_path, "C-005")
    real = tl._load_claims
    calls: list = []

    def _spy(ws):
        calls.append(ws)
        return real(ws)

    monkeypatch.setattr(tl, "_load_claims", _spy)
    blocker = tl.settlement_blocker(tmp_path, "C-005")
    assert blocker is None
    assert len(calls) == 1, calls


def test_blocker_passes_when_walked_and_minted(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    tl.mint_sibling_claims(tmp_path, "C-005")
    assert tl.settlement_blocker(tmp_path, "C-005") is None


# ---------- REQ 3: inventory fans out into sibling claims ----------

def test_mint_registers_siblings_with_linkage_fields(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    (tmp_path / "claim_deps.yaml").write_text("depends_on: {}\n",
                                              encoding="utf-8")
    r = tl.mint_sibling_claims(tmp_path, "C-005")
    assert r["refused"] is None, r
    minted = r["minted"]
    assert len(minted) == 3, minted
    claims = _load_reg(tmp_path)["claims"]
    siblings = [c for c in claims if c.get("origin") == "obstacle-alternative"]
    assert len(siblings) == 3
    for sib in siblings:
        assert sib["status"] == "OPEN"
        assert sib["obstacle_for"] == "C-005"
        assert sib["depends_on"] == ["C-005"]
        assert sib["answers_question"] == "q1", "answers_question inherited"
        assert sib["promotion_attempts"] == 0
        assert sib["ladder_family"] in ("hooking", "repackaging", "ca-install")
        stmt = sib["statement"]
        assert sib["ladder_family"] in stmt, "statement names the family"
        assert "pinning rejects" in stmt, "statement carries failed_because"
    # the real DAG edge landed in claim_deps.yaml
    deps = yaml.safe_load((tmp_path / "claim_deps.yaml").read_text(
        encoding="utf-8"))
    for sib in siblings:
        assert deps["depends_on"][sib["id"]] == ["C-005"]


def test_mint_is_idempotent(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    first = tl.mint_sibling_claims(tmp_path, "C-005")
    second = tl.mint_sibling_claims(tmp_path, "C-005")
    assert len(first["minted"]) == 3 and first["refused"] is None, first
    assert second["minted"] == [] and second["refused"] is None, second
    claims = _load_reg(tmp_path)["claims"]
    assert len([c for c in claims
                if c.get("origin") == "obstacle-alternative"]) == 3


def test_sibling_enters_the_ts_rank_pool(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    tl.mint_sibling_claims(tmp_path, "C-005")
    claims = _load_reg(tmp_path)["claims"]
    siblings = [c for c in claims if c.get("origin") == "obstacle-alternative"]
    assert siblings and all(priority_ratio.is_open(s) for s in siblings), (
        "a minted sibling must be TS-samplable (OPEN, non-terminal)")


def test_mint_without_register_is_explicit_noop(tmp_path):
    r = tl.mint_sibling_claims(tmp_path, "C-005")
    assert r["minted"] == [] and "claim-register" in r["refused"]


# ---------- F3: guarded mint ----------

def test_mint_refuses_nonexistent_parent(tmp_path):
    """F3: a mistyped id must never mint siblings against a ghost parent."""
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    r = tl.mint_sibling_claims(tmp_path, "C-999")
    assert r["minted"] == [] and "C-999 not found" in r["refused"]
    claims = _load_reg(tmp_path)["claims"]
    assert len(claims) == 1, "register untouched"
    assert not (tmp_path / "claim_deps.yaml").exists(), "no DAG pollution"


def test_mint_refuses_non_obstacle_parent(tmp_path):
    _write_reg(tmp_path, [{"id": "C-7", "status": "OPEN",
                           "statement": "regular claim"}])
    _write_ladder(tmp_path, "C-7", _walked_ladder())
    r = tl.mint_sibling_claims(tmp_path, "C-7")
    assert r["minted"] == [] and "failure-obstacle" in r["refused"]


def test_mint_refuses_unwalked_ladder(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", {"obstacle_class": "interception",
                                      "attempts": [], "inventory": [
                                          {"family": "hooking",
                                           "tried": "x",
                                           "failed_because": "y"}]})
    r = tl.mint_sibling_claims(tmp_path, "C-005")
    assert r["minted"] == [] and "not walked-valid" in r["refused"]


# ---------- REQ 4: promotion_attempts live writer + 3-strike DLQ ----------

def test_dispatch_failure_increments(tmp_path):
    _write_reg(tmp_path, [{"id": "C-3", "status": "OPEN",
                           "promotion_attempts": 0}])
    r = dl.record_dispatch_failure(tmp_path, "C-3")
    assert r == {"incremented": True, "claim_id": "C-3", "attempts": 1}
    claim = next(c for c in _load_reg(tmp_path)["claims"]
                 if c["id"] == "C-3")
    assert claim["promotion_attempts"] == 1


def test_dispatch_failure_noops_terminal(tmp_path):
    _write_reg(tmp_path, [{"id": "C-3", "status": "REFUTED",
                           "promotion_attempts": 2}])
    r = dl.record_dispatch_failure(tmp_path, "C-3")
    assert r["incremented"] is False and "terminal" in r["reason"]
    claim = next(c for c in _load_reg(tmp_path)["claims"]
                 if c["id"] == "C-3")
    assert claim["promotion_attempts"] == 2, "terminal claim must not accrue"


def test_dispatch_failure_names_missing_claim(tmp_path):
    _write_reg(tmp_path, [])
    r = dl.record_dispatch_failure(tmp_path, "C-404")
    assert r["incremented"] is False and "C-404" in r["reason"]


def test_three_strikes_escalate_must_ask_not_dead(tmp_path):
    """F6: strike 3 routes to the charter MUST-ASK lane — the claim keeps
    its non-terminal status (the ask gate's find_ladder_exhaustion sees
    pa>=3 and HARD_PAUSEs); DEAD stays an explicit --mark decision."""
    _write_reg(tmp_path, [{"id": "C-3", "status": "OPEN",
                           "promotion_attempts": 0}])
    for _ in range(2):
        r = dl.record_dispatch_failure(tmp_path, "C-3")
        assert r["incremented"] is True and "must_ask" not in r
    third = dl.record_dispatch_failure(tmp_path, "C-3")
    assert third["attempts"] == dl.DLQ_ATTEMPTS
    assert third.get("must_ask", {}).get("escalated") is True, third
    claim = next(c for c in _load_reg(tmp_path)["claims"]
                 if c["id"] == "C-3")
    assert claim["status"] == "OPEN", "must-ask must not flip the status"
    assert claim["promotion_attempts"] == 3
    artifact = tmp_path / "blockers" / "must-ask-C-3.md"
    assert artifact.exists(), "the must-ask blocker artifact must exist"
    assert "must-ask" in artifact.read_text(encoding="utf-8")
    assert not (tmp_path / "blockers" / "dead-letter-C-3.md").exists()


def test_strike3_escalation_failure_never_raises(tmp_path, capsys):
    """Review r2 LOW: record_dispatch_failure never raises — an OSError
    shape on the escalation artifact write (here: blockers/ exists as a
    FILE, so mkdir raises FileExistsError) warns and reports
    must_ask.escalated=False; the strike still counts."""
    (tmp_path / "blockers").write_text("not a directory\n", encoding="utf-8")
    _write_reg(tmp_path, [{"id": "C-3", "status": "OPEN",
                           "promotion_attempts": 2}])
    r = dl.record_dispatch_failure(tmp_path, "C-3")  # must not raise
    assert r["incremented"] is True and r["attempts"] == 3
    assert r["must_ask"]["escalated"] is False
    assert "artifact write failed" in r["must_ask"]["reason"]
    assert "WARN" in capsys.readouterr().err
    claim = next(c for c in _load_reg(tmp_path)["claims"]
                 if c["id"] == "C-3")
    assert claim["status"] == "OPEN" and claim["promotion_attempts"] == 3


def test_strike3_keeps_claim_in_ask_lane(tmp_path):
    """F6: find_ladder_exhaustion's pa>=3 precondition stays reachable —
    the claim the strikes accrued on is the one the ask gate will name."""
    from ask_for_direction_gate import LADDER_EXHAUSTION_MIN_ATTEMPTS
    assert dl.DLQ_ATTEMPTS == LADDER_EXHAUSTION_MIN_ATTEMPTS


# ---------- settlement gate wired into claim_migrator ----------

def test_claim_migrator_rejects_confirmed_without_ladder(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    ok, msg = kunglao_record.claim_migrator(
        tmp_path, "C-005", "PROVEN", "orchestrator")
    assert ok is False
    assert "TARGET LADDER GATE" in msg, msg
    claim = next(c for c in _load_reg(tmp_path)["claims"]
                 if c["id"] == "C-005")
    assert claim["status"] == "OPEN", "register must stay unmodified"


def test_claim_migrator_gate_passes_walked_obstacle(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    _write_ladder(tmp_path, "C-005", _walked_ladder())
    tl.mint_sibling_claims(tmp_path, "C-005")
    ok, msg = kunglao_record.claim_migrator(
        tmp_path, "C-005", "PROVEN", "orchestrator")
    assert "TARGET LADDER GATE" not in msg, (
        f"walked + minted obstacle must pass the ladder gate: {msg}")


def test_claim_migrator_refuted_stays_ungated(tmp_path):
    _write_reg(tmp_path, [_obstacle_claim()])
    ok, msg = kunglao_record.claim_migrator(
        tmp_path, "C-005", "REFUTED", "orchestrator")
    assert ok is True, msg
    assert "TARGET LADDER GATE" not in msg, msg
    claim = next(c for c in _load_reg(tmp_path)["claims"]
                 if c["id"] == "C-005")
    assert claim["status"] == "REFUTED"


def test_non_obstacle_proven_bypasses_the_gate(tmp_path):
    _write_reg(tmp_path, [{"id": "C-9", "status": "OPEN",
                           "statement": "regular claim"}])
    ok, msg = kunglao_record.claim_migrator(
        tmp_path, "C-9", "PROVEN", "orchestrator")
    assert "TARGET LADDER GATE" not in msg, msg


# ---------- F1: the hook-side backstop closes the direct-edit lane ----------

def _edits_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    _write_reg(ws, [_obstacle_claim("C-005")])
    return ws


def test_backstop_rejects_register_edit_bypass(tmp_path):
    """F1: OPEN -> PROVEN by DIRECT register edit, no ladder — the hook
    backstop (built for exactly this bypass class, #15/#78) must name the
    TARGET LADDER GATE among the violations."""
    ws = _edits_ws(tmp_path)
    reg = ws / "claim-register.yaml"
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        "status: OPEN", "status: PROVEN"), encoding="utf-8")
    ok, reason = wb.compare_register_change_proven_gate(
        reg, {"C-005": "OPEN"}, "orchestrator", ws / "facts")
    assert ok is False
    assert "TARGET LADDER GATE" in reason, reason


def test_backstop_ladder_reason_absent_when_walked(tmp_path):
    """F1: with the ladder walked + inventory + minted siblings, the ladder
    violation disappears from the backstop reason (other PROVEN
    requirements may still fire — the ladder gate itself passed)."""
    ws = _edits_ws(tmp_path)
    _write_ladder(ws, "C-005", _walked_ladder())
    tl.mint_sibling_claims(ws, "C-005")
    reg = ws / "claim-register.yaml"
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        "status: OPEN", "status: PROVEN"), encoding="utf-8")
    ok, reason = wb.compare_register_change_proven_gate(
        reg, {"C-005": "OPEN"}, "orchestrator", ws / "facts")
    assert "TARGET LADDER GATE" not in reason, reason
