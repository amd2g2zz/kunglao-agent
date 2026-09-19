# -*- coding: utf-8 -*-
"""RED tests for issue 252 — the hypothesis bridge (family <-> claim economy).

Fast tier (tests/_tiers.py FAST_MODULES): pure unit — spawns no
processes, touches no network, runs no nested pytest.

Contract (openspec/changes/issue-252-hypothesis-bridge):

  REQ1  Arms are born as claims: hypothesis candidates mint as OPEN claims
        with `competitor_group: hyp-<H-id>` + `hypothesis_ref` (the
        issue 234 edge-field style) via the NORMAL mint path — TS-samplable
        (priority_ratio.is_open), idempotent by (origin, hypothesis_ref,
        arm_key) marker, and NEVER duplicated as a store candidate string.
  REQ2  The store demotes to the family ledger: state syncs FROM claim
        settlements (the issue 528 transitions unchanged) — any arm positive ->
        family confirmed + competing group hypotheses superseded; all arms
        terminal, none positive -> refuted; wired into claim_migrator,
        guarded (a sync crash never fails the migration).
  REQ3  Candidate-fillers route into families at their existing mint sites
        (issue 234 siblings, issue 250 epistemic claims — no re-mint, no
        double representation); legacy candidate strings are paid by the sweep.
  REQ4  The no-orphan-representation guard: parked candidate strings and
        family claims to nonexistent hypotheses are lint errors; the
        hypotheses-writer allowlist pins the regression shut.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import hypothesis_bridge as hb  # noqa: E402
import hypothesis_store as hstore  # noqa: E402
import kunglao_record  # noqa: E402
import priority_ratio  # noqa: E402
import target_ladder as tl  # noqa: E402


# ---------- helpers ----------

def _write_reg(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _load_reg(ws: Path) -> dict:
    return yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}


def _mk_hyp(ws: Path, hid: str, *, group: str = "", candidates: list | None = None,
            status: str = "open") -> hstore.Hypothesis:
    store = hstore.HypothesisStore(ws / "hypotheses")
    return store.create(hstore.Hypothesis(
        id=hid, claim_id="C-PENDING",
        competitor_group=group or hb.family_group(hid),
        candidates=list(candidates or []), status=status,
        body=f"test family {hid}\n"))


def _pq_scaffold(ws: Path, hid: str, qid: str) -> hstore.Hypothesis:
    """The issue 662/109 shape: marker pq:<qid> in the body, group pq-<qid>."""
    store = hstore.HypothesisStore(ws / "hypotheses")
    return store.create(hstore.Hypothesis(
        id=hid, claim_id="C-PENDING", competitor_group=f"pq-{qid}",
        candidates=[], status="open",
        body=f"pq:{qid}\n\nSeeded scaffold for {qid}.\n"))


# =====================================================================
# REQ1 — arms are born as claims
# =====================================================================

def test_arm_claims_carry_family_linkage(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [{"id": "C-001", "status": "OPEN", "statement": "base"}])
    r = hb.mint_family_arms(ws, "H-001", ["AES under the table", "ChaCha20"])
    assert r["refused"] is None, r
    claims = _load_reg(ws)["claims"]
    arms = [c for c in claims if c.get("competitor_group") == "hyp-H-001"]
    assert len(arms) == 2, claims
    for a in arms:
        assert a["status"] == "OPEN"
        assert a["origin"] == "hypothesis-arm"
        assert a["hypothesis_ref"] == "H-001"
        assert a["arm_key"], "idempotency marker present"
        assert "AES" in a["statement"] or "ChaCha20" in a["statement"]


def test_arm_enters_the_ts_rank_pool(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [{"id": "C-001", "status": "OPEN", "statement": "base"}])
    hb.mint_family_arms(ws, "H-001", ["static dispatch", "dynamic dispatch"])
    claims = _load_reg(ws)["claims"]
    arms = [c for c in claims if c.get("competitor_group") == "hyp-H-001"]
    assert arms and all(priority_ratio.is_open(a) for a in arms)
    ranked = priority_ratio.priority_ratio(claims, {"depends_on": {}},
                                           priority_ratio.EvidenceView.from_workspace(ws))
    ranked_ids = {a.claim_id for a in ranked}
    assert {a["id"] for a in arms} <= ranked_ids, (
        "a minted family arm must be samplable by the TS ranker")


def test_mint_idempotent_by_marker(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [{"id": "C-001", "status": "OPEN", "statement": "base"}])
    first = hb.mint_family_arms(ws, "H-001", ["AES", "ChaCha20"])
    second = hb.mint_family_arms(ws, "H-001", ["AES", "ChaCha20"])
    assert first["refused"] is None and second["refused"] is None
    assert second["minted"] == [], "re-mint must not duplicate"
    arms = [c for c in _load_reg(ws)["claims"]
            if c.get("competitor_group") == "hyp-H-001"]
    assert len(arms) == 2


def test_mint_refuses_missing_family_file(tmp_path):
    ws = tmp_path
    _write_reg(ws, [{"id": "C-001", "status": "OPEN", "statement": "base"}])
    r = hb.mint_family_arms(ws, "H-999", ["AES"])
    assert r["minted"] == [] and r["refused"], "explicit refusal, not silent"


def test_no_duplicate_representation(tmp_path):
    """A minted candidate must NOT also appear as a store candidate string."""
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [{"id": "C-001", "status": "OPEN", "statement": "base"}])
    hb.mint_family_arms(ws, "H-001", ["AES", "ChaCha20"])
    hyp = hstore.HypothesisStore(ws / "hypotheses").get("H-001")
    assert hyp.candidates == [], (
        "the claim is the one representation — no store candidate string")
    # and the sweep pays legacy strings: minted -> cleared
    _mk_hyp(ws, "H-002", candidates=["apkid:packer:BaseAPK"])
    hb.mint_pending_candidates(ws)
    h2 = hstore.HypothesisStore(ws / "hypotheses").get("H-002")
    assert h2.candidates == [], "swept strings leave the store"
    arms = [c for c in _load_reg(ws)["claims"]
            if c.get("competitor_group") == "hyp-H-002"]
    assert len(arms) == 1 and "BaseAPK" in arms[0]["statement"]


def test_sweep_is_idempotent(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001", candidates=["apkid:packer:BaseAPK"])
    _write_reg(ws, [])
    first = hb.mint_pending_candidates(ws)
    second = hb.mint_pending_candidates(ws)
    assert first["minted"] and second["minted"] == []


# =====================================================================
# REQ2 — the family ledger syncs from claim settlements
# =====================================================================

def test_positive_arm_confirms_family_and_supersedes_competitors(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001", group="pq-q1")  # the pq-family holding the arms
    _mk_hyp(ws, "H-002", group="pq-q1")  # competing open scaffold, same group
    _mk_hyp(ws, "H-003", group="pq-q1")
    # family member claims: one PROVEN arm
    _write_reg(ws, [
        {"id": "C-001", "status": "OPEN", "statement": "a",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
        {"id": "C-002", "status": "PROVEN", "statement": "b",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    report = hb.sync_family_ledger(ws)
    store = hstore.HypothesisStore(ws / "hypotheses")
    assert store.get("H-001").status == "confirmed"
    assert store.get("H-001").confirming_fact_id == "C-002"
    assert store.get("H-002").status == "superseded"
    assert store.get("H-002").superseded_by == "H-001"
    assert store.get("H-003").status == "superseded"
    assert "H-001" in report["confirmed"]


def test_all_negative_arms_refute_the_family(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-001", "status": "REFUTED", "statement": "a",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
        {"id": "C-002", "status": "NEGATIVE", "statement": "b",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    hb.sync_family_ledger(ws)
    h = hstore.HypothesisStore(ws / "hypotheses").get("H-001")
    assert h.status == "refuted"
    assert h.refuting_fact_id == "C-001", "deterministic: first negative arm"


def test_mixed_arms_keep_the_family_pending(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-001", "status": "REFUTED", "statement": "a",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
        {"id": "C-002", "status": "OPEN", "statement": "b",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    hb.sync_family_ledger(ws)
    assert hstore.HypothesisStore(ws / "hypotheses").get("H-001").status == "open"


def test_terminal_family_never_rewound(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001", status="superseded")
    _write_reg(ws, [
        {"id": "C-001", "status": "PROVEN", "statement": "a",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    report = hb.sync_family_ledger(ws)  # must not raise
    assert any("H-001" in s for s in report["skipped"])
    assert hstore.HypothesisStore(ws / "hypotheses").get("H-001").status == \
        "superseded"


def test_claim_migrator_settlement_triggers_sync(tmp_path):
    """Integration: the ungated REFUTED settlement path updates the ledger."""
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-001", "status": "OPEN", "statement": "a",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
        {"id": "C-002", "status": "OPEN", "statement": "b",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    ok, msg = kunglao_record.claim_migrator(ws, "C-001", "REFUTED", "orchestrator")
    assert ok, msg
    # one negative arm + one open -> still pending
    assert hstore.HypothesisStore(ws / "hypotheses").get("H-001").status == "open"
    ok, msg = kunglao_record.claim_migrator(ws, "C-002", "REFUTED", "orchestrator")
    assert ok, msg
    # all arms settled, none positive -> family refuted
    h = hstore.HypothesisStore(ws / "hypotheses").get("H-001")
    assert h.status == "refuted" and h.refuting_fact_id in ("C-001", "C-002")


def test_claim_migrator_survives_sync_crash(tmp_path, monkeypatch, capsys):
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-001", "status": "OPEN", "statement": "a",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    def _boom(ws_path):
        raise RuntimeError("ledger offline")
    monkeypatch.setattr(hb, "sync_family_ledger", _boom)
    ok, msg = kunglao_record.claim_migrator(ws, "C-001", "REFUTED", "orchestrator")
    assert ok, "a sync failure must never fail the settlement"
    # review F4: the failure is NOT silent — stderr WARN names the repair
    err = capsys.readouterr().err
    assert "family-ledger sync failed" in err
    assert "--sync" in err


# =====================================================================
# REQ3 — candidate-fillers route into families (existing mint sites)
# =====================================================================

def _obstacle_ws(tmp_path):
    ws = tmp_path
    _write_reg(ws, [{"id": "C-005", "status": "OPEN", "statement": "obstacle",
                     "origin": "failure-obstacle",
                     "obstacle_class": "interception"}])
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    fams = tl.OBSTACLE_CLASS_FAMILIES["interception"][:3]
    (runs / "target-ladder-C-005.yaml").write_text(yaml.safe_dump({
        "obstacle_class": "interception",
        "attempts": [{"level": f"T{i + 1}", "family": f, "action": "try",
                      "outcome": "blocked"} for i, f in enumerate(fams)],
        "inventory": [{"family": f, "tried": f"{f} pass",
                       "failed_because": "pinning"} for f in fams],
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    return ws, fams


def test_target_ladder_siblings_carry_family_linkage(tmp_path):
    ws, _fams = _obstacle_ws(tmp_path)
    r = tl.mint_sibling_claims(ws, "C-005")
    assert r["refused"] is None, r
    siblings = [c for c in _load_reg(ws)["claims"]
                if c.get("origin") == "obstacle-alternative"]
    assert siblings, "siblings minted"
    groups = {s.get("competitor_group") for s in siblings}
    refs = {s.get("hypothesis_ref") for s in siblings}
    assert len(groups) == 1 and len(refs) == 1, "one family per obstacle"
    hid = next(iter(refs))
    assert next(iter(groups)) == hb.family_group(hid)
    hyp = hstore.HypothesisStore(ws / "hypotheses").get(hid)
    assert hyp is not None, "the family hypothesis file exists"
    assert f"obstacle-family:C-005" in hyp.body


def _vmp_ws(tmp_path):
    ws = tmp_path
    ev = ws / "evidence"
    ev.mkdir()
    (ev / "die.json").write_text(
        '{"derived": {"detected_packer": "VMProtect"}}', encoding="utf-8")
    return ws


def test_plan_epistemics_claims_carry_family_linkage(tmp_path):
    import plan_epistemics as pe
    ws = _vmp_ws(tmp_path)
    summary = pe.mint_workspace(ws)
    minted = summary["minted"]
    assert minted, "vmp unknowns minted"
    for c in minted:
        assert c["boundary_type"] == "epistemic", "#250 semantics preserved"
        assert c.get("competitor_group", "").startswith("hyp-"), c
        assert c.get("hypothesis_ref")
    hyp = hstore.HypothesisStore(ws / "hypotheses").get(
        minted[0]["hypothesis_ref"])
    assert hyp is not None
    assert "pq:q_dispatch_mode" in hyp.body, "the #109/#662 binding shape"


def test_plan_epistemics_reuses_the_existing_pq_scaffold(tmp_path):
    import plan_epistemics as pe
    ws = _vmp_ws(tmp_path)
    _pq_scaffold(ws, "H-007", "q_dispatch_mode")
    summary = pe.mint_workspace(ws)
    row = next(c for c in summary["minted"]
               if c["answers_question"] == "q_dispatch_mode")
    assert row["hypothesis_ref"] == "H-007", "no duplicate family scaffold"
    assert hstore.HypothesisStore(ws / "hypotheses").get("H-007") is not None


def test_no_second_family_hypothesis_for_one_unknown(tmp_path):
    import plan_epistemics as pe
    ws = _vmp_ws(tmp_path)
    pe.mint_workspace(ws)
    pe.mint_workspace(ws)  # idempotent end-to-end
    hyps = hstore.HypothesisStore(ws / "hypotheses").list_all()
    markers = [h for h in hyps if "pq:q_dispatch_mode" in h.body]
    assert len(markers) == 1, "one family ledger per question"


# =====================================================================
# review round 1 pins (F2/F3/F4/F5/F6/F7/F8)
# =====================================================================

def test_deferred_only_arms_stay_pending(tmp_path):
    """F2: DEFERRED/STALE-only arms never refute — a deferral is not a
    refutation and refuted is terminal forever."""
    ws = tmp_path
    _mk_hyp(ws, "H-009")
    _write_reg(ws, [
        {"id": "C-001", "status": "DEFERRED", "statement": "a",
         "competitor_group": "hyp-H-009", "hypothesis_ref": "H-009"},
        {"id": "C-002", "status": "STALE", "statement": "b",
         "competitor_group": "hyp-H-009", "hypothesis_ref": "H-009"},
    ])
    report = hb.sync_family_ledger(ws)
    h = hstore.HypothesisStore(ws / "hypotheses").get("H-009")
    assert h.status == "open", "deferred/stale-only stays pending"
    assert h.refuting_fact_id is None
    assert "H-009" in report["pending"]
    assert hb.check_bridge_lint(ws) == [], "no divergence: pending is legit"


def test_refuting_reference_is_negative_only(tmp_path):
    """F2 pin: when a negative arm exists the refuting reference IS that
    arm, never a DEFERRED sibling."""
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-001", "status": "DEFERRED", "statement": "a",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
        {"id": "C-002", "status": "REFUTED", "statement": "b",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    hb.sync_family_ledger(ws)
    h = hstore.HypothesisStore(ws / "hypotheses").get("H-001")
    assert h.status == "refuted"
    assert h.refuting_fact_id == "C-002", "why-was-I-wrong = the negative arm"


def test_losing_arms_retire_on_confirm(tmp_path):
    """F3: on family resolution the losing OPEN arm retires claim-level
    SUPERSEDED (superseded_by = the winning arm) — out of the TS pool."""
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-001", "status": "PROVEN", "statement": "winner",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
        {"id": "C-002", "status": "OPEN", "statement": "loser",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    report = hb.sync_family_ledger(ws)
    reg = _load_reg(ws)
    arms = {c["id"]: c for c in reg["claims"] if c["id"] in ("C-001", "C-002")}
    assert hstore.HypothesisStore(ws / "hypotheses").get("H-001").status == \
        "confirmed"
    assert arms["C-002"]["status"] == "SUPERSEDED", "loser retired"
    assert arms["C-002"]["superseded_by"] == "C-001"
    assert "C-002" in report["retired"]
    assert not priority_ratio.is_open(arms["C-002"]), (
        "a retired arm must leave the TS rank pool")


def test_sibling_arms_retire_on_supersede(tmp_path):
    """F3: when a family confirms, superseded sibling hypotheses' open arms
    retire too — no stale OPEN claims linger on decided questions."""
    ws = tmp_path
    _mk_hyp(ws, "H-001", group="pq-q1")
    _mk_hyp(ws, "H-002", group="pq-q1")
    _write_reg(ws, [
        {"id": "C-001", "status": "PROVEN", "statement": "w",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
        {"id": "C-009", "status": "OPEN", "statement": "sibling arm",
         "competitor_group": "hyp-H-002", "hypothesis_ref": "H-002"},
    ])
    hb.sync_family_ledger(ws)
    arms = {c["id"]: c for c in _load_reg(ws)["claims"]}
    assert hstore.HypothesisStore(ws / "hypotheses").get("H-002").status == \
        "superseded"
    assert arms["C-009"]["status"] == "SUPERSEDED"
    assert arms["C-009"]["superseded_by"] == "C-001"


def test_sync_no_reemit_on_already_confirmed(tmp_path):
    """F5: an already-confirmed family reports 'unchanged' — no duplicate
    confirmed entries/emit spam on subsequent settlements."""
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-001", "status": "PROVEN", "statement": "w",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    first = hb.sync_family_ledger(ws)
    assert first["confirmed"] == ["H-001"]
    second = hb.sync_family_ledger(ws)
    assert second["confirmed"] == [], "no re-emit"
    assert any("already confirmed" in u for u in second["unchanged"])


def test_arm_key_collision_refused(tmp_path):
    """F6b: two distinct candidates sharing the 200-char slug are REFUSED,
    never silently collapsed."""
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [{"id": "C-001", "status": "OPEN", "statement": "base"}])
    base = "A" * 200
    r = hb.mint_family_arms(ws, "H-001", [base + "-one", base + "-two"])
    assert r["refused"] and "arm_key collision" in r["refused"]
    assert r["minted"] == [], "nothing minted on collision"


def test_family_hypothesis_id_grammar():
    """F8: the hyp- namespace requires the H-<digits> grammar."""
    assert hb.family_hypothesis_id("hyp-H-001") == "H-001"
    assert hb.family_hypothesis_id("hyp-H-12") == "H-12"
    assert hb.family_hypothesis_id("hyp-q1") is None
    assert hb.family_hypothesis_id("hyp-X") is None
    assert hb.family_hypothesis_id("hyp-H-") is None
    assert hb.family_hypothesis_id("hyp-H-001-x") is None


def test_namespace_capture_rejected(tmp_path):
    """F8: an external claim naming hyp-<H-id> without the mint-issued
    hypothesis_ref edge field never adjudicates the family and is a lint
    error (E2b)."""
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-EXT", "status": "PROVEN", "statement": "external q_id",
         "competitor_group": "hyp-H-001"},  # no hypothesis_ref — not ours
    ])
    hb.sync_family_ledger(ws)
    assert hstore.HypothesisStore(ws / "hypotheses").get("H-001").status == \
        "open", "unmarked claims never adjudicate a family"
    errs = hb.check_bridge_lint(ws)
    assert any("E2b" in e for e in errs), errs


def test_lint_e3_divergence_and_repair(tmp_path):
    """F4: an OPEN family whose claims derive a verdict the ledger does not
    carry is E3 (the persistent sync-crash detector); the sync repairs it."""
    ws = tmp_path
    _mk_hyp(ws, "H-001")
    _write_reg(ws, [
        {"id": "C-001", "status": "PROVEN", "statement": "w",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
        {"id": "C-002", "status": "OPEN", "statement": "l",
         "competitor_group": "hyp-H-001", "hypothesis_ref": "H-001"},
    ])
    errs = hb.check_bridge_lint(ws)
    assert any("E3" in e for e in errs), "divergence flagged pre-sync"
    hb.sync_family_ledger(ws)
    assert hb.check_bridge_lint(ws) == [], "the sync repairs the divergence"


def test_writer_scan_catches_evasion(tmp_path):
    """F6: the static scan covers hooks/, import-machinery store imports,
    and raw-frontmatter writers; a comment mention does not exempt."""
    fake_scripts = tmp_path / "scripts"
    fake_scripts.mkdir()
    (fake_scripts / "evade_dynamic.py").write_text(
        "import importlib\n"
        "hs = importlib.import_module('hypothesis_store')\n"
        "hs.HypothesisStore(x).create(h)\n", encoding="utf-8")
    (fake_scripts / "evade_raw.py").write_text(
        "p.write_text('schema_rev: 1 — hand-rolled frontmatter')\n",
        encoding="utf-8")
    (fake_scripts / "comment_mention.py").write_text(
        "# minting goes through hypothesis_bridge (see issue 252)\n"
        "from hypothesis_store import HypothesisStore\n"
        "HypothesisStore(p).create(h)\n", encoding="utf-8")
    (fake_scripts / "clean_reader.py").write_text(
        "import hypothesis_store as hs\n"
        "rows = hs.HypothesisStore(ws / 'hypotheses').list_all()\n",
        encoding="utf-8")
    (fake_scripts / "bridge_user.py").write_text(
        "from hypothesis_bridge import mint_family_arms\n"
        "mint_family_arms(ws, 'H-001', ['x'])\n", encoding="utf-8")
    fake_hooks = tmp_path / "hooks"
    fake_hooks.mkdir()
    (fake_hooks / "hook_writer.py").write_text(
        "h = Hypothesis(id='H-9', claim_id='c', competitor_group='g')\n"
        "store.create(h)\n", encoding="utf-8")
    off = hb.writer_scan_offenders(fake_scripts, fake_hooks)
    assert "scripts/evade_dynamic.py" in off
    assert "scripts/evade_raw.py" in off
    assert "scripts/comment_mention.py" in off
    assert "hooks/hook_writer.py" in off
    assert "scripts/clean_reader.py" not in off
    assert "scripts/bridge_user.py" not in off


def test_current_tree_writer_scan_clean():
    """The live tree trips exactly nothing outside the allowlist + bridge."""
    offenders = hb.writer_scan_offenders(ROOT / "scripts", ROOT / "hooks")
    assert offenders == [], offenders


# =====================================================================
# REQ4 — the no-orphan-representation guard
# =====================================================================

def test_guard_names_parked_candidates(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001", candidates=["apkid:packer:BaseAPK"])
    _write_reg(ws, [])
    errs = hb.check_bridge_lint(ws)
    assert errs, "parked strings are an orphan representation"
    assert any("H-001" in e and "BaseAPK" in e for e in errs)


def test_guard_clean_after_sweep(tmp_path):
    ws = tmp_path
    _mk_hyp(ws, "H-001", candidates=["apkid:packer:BaseAPK"])
    _write_reg(ws, [])
    hb.mint_pending_candidates(ws)
    assert hb.check_bridge_lint(ws) == [], "the sweep pays the debt"


def test_guard_names_orphan_family_claim(tmp_path):
    ws = tmp_path
    _write_reg(ws, [{"id": "C-001", "status": "OPEN", "statement": "a",
                     "competitor_group": "hyp-H-999",
                     "hypothesis_ref": "H-999"}])
    errs = hb.check_bridge_lint(ws)
    assert errs and any("H-999" in e for e in errs)


def test_guard_clean_workspace_passes(tmp_path):
    ws = tmp_path
    _pq_scaffold(ws, "H-001", "q1")   # scaffold, candidates=[] — legal
    _write_reg(ws, [{"id": "C-001", "status": "OPEN", "statement": "a"}])
    assert hb.check_bridge_lint(ws) == []


# =====================================================================
# seeder prose contract mechanized
# =====================================================================

def test_scaffold_body_names_the_bridge(tmp_path):
    from hypothesis_seeder import _scaffold_body
    body = _scaffold_body("q1", "model_selection")
    assert "hypothesis_bridge" in body, "the mechanized contract is named"
    assert "orchestrator fills" not in body, "the hope-language is gone"
