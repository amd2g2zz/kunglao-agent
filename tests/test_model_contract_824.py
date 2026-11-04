# -*- coding: utf-8 -*-
"""tests/test_model_contract_824.py — #824 the unified RL model contract.

The axis rewrite (#806, axioms A1-A5) lands its P1 contracts here:

  1. episode schema `episode/1` (rlvr/episode_schema.py) — machine-
     readable frontmatter, summaries ONLY (a raw-log write attempt is
     RED), fail-closed validator;
  2. the pool (rlvr/episode_pool.py) — physical layer `runs/episodes/`
     riding the EXISTING runs/ zone, the three policies as gates:
     WRITE (trust gate x admission policy), READ (three legal phases),
     UPDATE (stats every settlement, retrieved-uncited decay GREEN,
     max-revalue capped, prune by utility not time);
  3. the indexers (rlvr/pool_indexer.py) — value table + playbook view
     as pure DERIVED views (regenerate = identical output, no store);
  4. the reward switch (rlvr/reward_signal.py) — R = completion +
     milestone progress - cost (A1); per-fact credit is structurally
     out of the signal (PE pathology scores ~0) and the trust spine
     gates every milestone/completion verification.

Fixtures are synthetic workspaces; the trust spine is exercised through
the unmodified `verifier_integrity.resolve_verification` (PASSED record
on the canonical surface). Settlement/verifier semantics are only ever
CALLED, never modified (existing-face pins at the bottom).
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HOOKS))

import rlvr.episode_pool as pool  # noqa: E402
import rlvr.episode_schema as es  # noqa: E402
import rlvr.pool_indexer as indexer  # noqa: E402
import rlvr.reward_signal as rs  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402


# ---------------------------------------------------------------- fixtures

def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    return ws


def _pass_verification(ws: Path, claim: str = "C-1") -> Path:
    p = ws / "runs" / f"verification-{claim}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# verification {claim}\n\nverdict: verified\n",
                 encoding="utf-8")
    return p


def _episode(claim: str = "C-1", **over) -> dict:
    doc = {
        "schema": "episode/1",
        "id": f"E-{claim}",
        "claim": claim,
        "created": "2026-10-25T00:00:00Z",
        "updated": "2026-10-25T00:00:00Z",
        "context_features": ["android", "frida"],
        "commits": [
            {"seq": 1, "action": "select", "summary": "picked frida lane"},
            {"seq": 2, "action": "verify", "summary": "byte-exact replay"},
        ],
        "outcome": {"status": "completed", "verified": True,
                    "evidence_ref": ""},
        "cost": {"tokens": 12000.0, "seconds": 720.0},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
        "reusable_fragments": ["frida attach needs the gadget re-pack"],
        "milestones": [
            {"id": "M-1", "desc": "unpack the loader", "verified": True,
             "evidence_ref": ""},
        ],
        "attribution": "",
        "surprise": False,
    }
    doc.update(over)
    return doc


def _write(ws: Path, doc: dict, **kw):
    return pool.write_episode(ws, doc, **kw)


# ------------------------------------------------------------ schema pins

class TestEpisodeSchema:
    def test_valid_episode_validates(self):
        doc = es.validate_episode(_episode())
        assert doc["claim"] == "C-1"
        assert doc["schema"] == "episode/1"

    @pytest.mark.parametrize("mutate,field", [
        ({"schema": "episode/2"}, "schema"),
        ({"id": ""}, "id"),
        ({"context_features": ["", "x"]}, "context_features"),
        ({"context_features": "android"}, "context_features"),
        ({"cost": {"tokens": -1.0, "seconds": 0.0}}, "cost"),
        ({"outcome": {"status": "won", "verified": True}}, "outcome"),
        ({"utility": {"retrievals": 0}}, "utility"),
    ])
    def test_bad_fields_are_red(self, mutate, field):
        bad = _episode(**mutate)
        with pytest.raises(es.EpisodeError) as ei:
            es.validate_episode(bad)
        assert field in str(ei.value)

    def test_unknown_commit_action_red(self):
        bad = _episode()
        bad["commits"][1]["action"] = "wing_it"
        with pytest.raises(es.EpisodeError) as ei:
            es.validate_episode(bad)
        assert "commits" in str(ei.value)

    def test_raw_log_fragment_is_red(self):
        bad = _episode(reusable_fragments=["x" * (es.FRAGMENT_CHAR_MAX + 1)])
        with pytest.raises(es.EpisodeError) as ei:
            es.validate_episode(bad)
        assert "fragment" in str(ei.value).lower()

    def test_body_over_cap_is_red(self):
        with pytest.raises(es.EpisodeError):
            es.validate_episode(_episode(), body="y" * (es.BODY_CHAR_MAX + 1))

    def test_commits_need_summaries_not_logs(self):
        bad = _episode()
        bad["commits"][0]["summary"] = "s" * (es.FRAGMENT_CHAR_MAX + 1)
        with pytest.raises(es.EpisodeError):
            es.validate_episode(bad)

    def test_roundtrip_frontmatter(self, tmp_path):
        ws = _mk_ws(tmp_path)
        p = ws / "episode.md"
        es.write_episode_file(p, _episode(), body="a summary paragraph.\n")
        back, body = es.read_episode_file(p)
        assert back["claim"] == "C-1"
        assert "a summary paragraph" in body


# ---------------------------------------------------------- write-gate pins

class TestWriteGate:
    def test_unverified_outcome_never_enters_pool(self, tmp_path):
        ws = _mk_ws(tmp_path)  # no verification record on disk
        doc = _episode()
        with pytest.raises(pool.WriteRefused) as ei:
            _write(ws, doc)
        assert "verif" in str(ei.value).lower()
        assert not (ws / "runs" / "episodes").exists() or \
            not list((ws / "runs" / "episodes").glob("*.md"))

    def test_verified_terminal_reward_admitted(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws)
        _write(ws, _episode())
        back, _ = es.read_episode_file(
            ws / "runs" / "episodes" / "episode-C-1.md")
        assert back["outcome"]["status"] == "completed"

    def test_clean_attribution_failure_admitted(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws)
        doc = _episode(outcome={"status": "failed", "verified": True,
                                "evidence_ref": ""},
                       attribution="gadget missing on this ROM")
        _write(ws, doc)
        assert (ws / "runs" / "episodes" / "episode-C-1.md").is_file()

    def test_unattributed_nonreward_refused(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws)
        doc = _episode(outcome={"status": "failed", "verified": True,
                                "evidence_ref": ""},
                       attribution="")
        with pytest.raises(pool.WriteRefused):
            _write(ws, doc)

    def test_surprise_event_admitted(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws)
        doc = _episode(outcome={"status": "blocked", "verified": True,
                                "evidence_ref": ""},
                       surprise=True)
        _write(ws, doc)
        assert (ws / "runs" / "episodes" / "episode-C-1.md").is_file()

    def test_zero_reward_non_surprise_refused(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws)
        doc = _episode(outcome={"status": "blocked", "verified": True,
                                "evidence_ref": ""})
        with pytest.raises(pool.WriteRefused):
            _write(ws, doc)

    def test_raw_log_write_attempt_is_red(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws)
        doc = _episode(reusable_fragments=["log" * (es.FRAGMENT_CHAR_MAX // 3
                                                    + 1)])
        with pytest.raises(pool.WriteRefused) as ei:
            _write(ws, doc)
        assert "fragment" in str(ei.value).lower()

    def test_terminal_reward_requires_nonzero(self, tmp_path):
        """A completed episode with an unresolvable completion trust leg
        is refused even when the failure surface would pass — the trust
        gate resolves the OUTCOME evidence, not just any record."""
        ws = _mk_ws(tmp_path)
        doc = _episode(outcome={"status": "completed", "verified": True,
                                "evidence_ref": "runs/nope.md"})
        with pytest.raises(pool.WriteRefused):
            _write(ws, doc)


# ------------------------------------------------------------- read-face pins

class TestReadFace:
    def _pool_with(self, ws: Path, claims: list[str], utils: list[float]):
        for claim in claims:
            _pass_verification(ws, claim)
        for claim, util in zip(claims, utils):
            doc = _episode(claim)
            doc["utility"]["utility"] = util
            _write(ws, doc)

    def test_illegal_phase_refused(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(pool.ReadRefused):
            pool.retrieve(ws, ["android"], phase="mid_execution")

    def test_three_legal_phases(self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._pool_with(ws, ["C-1"], [0.5])
        for phase in ("episode_start", "commit_boundary", "blocked"):
            rows = pool.retrieve(ws, ["android"], phase=phase)
            assert [r["claim"] for r in rows] == ["C-1"]

    def test_ranked_by_utility_deterministic(self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._pool_with(ws, ["C-1", "C-2", "C-3"], [0.2, 0.9, 0.2])
        rows = pool.retrieve(ws, ["android"], phase="episode_start")
        assert [r["claim"] for r in rows] == ["C-2", "C-1", "C-3"]

    def test_retrieval_bumps_counter(self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._pool_with(ws, ["C-1"], [0.5])
        pool.retrieve(ws, ["android"], phase="episode_start")
        doc, _ = es.read_episode_file(
            ws / "runs" / "episodes" / "episode-C-1.md")
        assert doc["utility"]["retrievals"] == 1

    def test_feature_match_filters(self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._pool_with(ws, ["C-1"], [0.5])
        _pass_verification(ws, "C-2")
        doc = _episode("C-2", context_features=["windows", "frida"])
        _write(ws, doc)
        rows = pool.retrieve(ws, ["android"], phase="episode_start")
        assert [r["claim"] for r in rows] == ["C-1"]


# ---------------------------------------------------------- update-policy pins

class TestUpdatePolicy:
    def _two(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws, "C-1")
        _pass_verification(ws, "C-2")
        for c in ("C-1", "C-2"):
            doc = _episode(c)
            doc["utility"] = {"retrievals": 0, "citations": 0,
                              "utility": 0.8}
            _write(ws, doc)
        pool.retrieve(ws, ["android"], phase="episode_start")  # bumps both
        return ws

    def test_retrieved_uncited_decays_green(self, tmp_path):
        ws = self._two(tmp_path)
        pool.update_on_settlement(ws, "C-2", cited=("C-2",))
        a = es.read_episode_file(
            ws / "runs" / "episodes" / "episode-C-1.md")[0]["utility"]
        assert 0.0 < a["utility"] < 0.8, "retrieved-uncited decays"
        # the cited episode gains citation mass
        b = es.read_episode_file(
            ws / "runs" / "episodes" / "episode-C-2.md")[0]["utility"]
        assert b["citations"] == 1
        assert b["utility"] > 0.8

    def test_max_revalue_capped(self, tmp_path):
        ws = self._two(tmp_path)
        for _ in range(10):
            pool.update_on_settlement(ws, "C-2", cited=("C-2",))
        b = es.read_episode_file(
            ws / "runs" / "episodes" / "episode-C-2.md")[0]["utility"]
        assert b["utility"] <= pool.UTILITY_MAX

    def test_prune_by_utility_not_time(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws, "C-1")
        _pass_verification(ws, "C-2")
        old_high = _episode("C-1")  # written FIRST (oldest)
        old_high["utility"]["utility"] = 0.9
        _write(ws, old_high)
        new_low = _episode("C-2")
        new_low["utility"]["utility"] = 0.1
        _write(ws, new_low)
        pool.prune(ws, capacity=1)
        left = sorted(p.name for p in
                      (ws / "runs" / "episodes").glob("episode-*.md"))
        assert left == ["episode-C-1.md"], "utility evicts, never age"


# ------------------------------------------------------------- indexer pins

class TestIndexers:
    def _pool(self, tmp_path):
        ws = _mk_ws(tmp_path)
        a = _episode("C-1")
        a["reward"] = {"completion": 1.0, "milestone_progress": 1.0,
                       "cost_term": 0.5, "r": 1.5}
        _pass_verification(ws, "C-1")
        _write(ws, a)
        b = _episode("C-2", context_features=["windows"])
        b["reward"] = {"completion": 1.0, "milestone_progress": 0.0,
                       "cost_term": 0.25, "r": 0.75}
        _pass_verification(ws, "C-2")
        _write(ws, b)
        return ws

    def test_value_table_deterministic_and_store_free(self, tmp_path):
        ws = self._pool(tmp_path)
        before = sorted(str(p.relative_to(ws)) for p in ws.rglob("*")
                        if p.is_file())
        t1 = indexer.value_table(ws)
        t2 = indexer.value_table(ws)
        proj = lambda t: json.dumps(
            {repr(k): v for k, v in t.items()}, sort_keys=True)
        assert proj(t1) == proj(t2)
        after = sorted(str(p.relative_to(ws)) for p in ws.rglob("*")
                       if p.is_file())
        assert before == after, "a derived view must not write a store"

    def test_value_table_cells(self, tmp_path):
        ws = self._pool(tmp_path)
        table = indexer.value_table(ws)
        key = indexer.cell_key(("android", "frida"), "select")
        assert key in table
        cell = table[key]
        assert cell["n"] == 1
        assert cell["mean_reward"] == pytest.approx(1.5)
        assert 0.0 <= cell["mean_cost"] <= 1.0

    def test_playbook_admits_completed_verified_only(self, tmp_path):
        ws = self._pool(tmp_path)
        _pass_verification(ws, "C-9")
        doc = _episode("C-9", context_features=["android", "frida"])
        doc["outcome"] = {"status": "failed", "verified": True,
                          "evidence_ref": ""}
        doc["attribution"] = "clean"
        _write(ws, doc)
        pb = indexer.playbook_view(ws)
        frags = [f for g in pb for f in g["fragments"]]
        assert "frida attach needs the gadget re-pack" in frags
        assert all(g["context_features"] == sorted(g["context_features"])
                   for g in pb)

    def test_playbook_fragments_deduped(self, tmp_path):
        ws = self._pool(tmp_path)
        c = _episode("C-3")  # same features + same fragment as C-1
        c["reward"] = {"completion": 1.0, "milestone_progress": 0.0,
                       "cost_term": 0.1, "r": 0.9}
        _pass_verification(ws, "C-3")
        _write(ws, c)
        groups = [g for g in indexer.playbook_view(ws)
                  if g["context_features"] == ["android", "frida"]]
        assert len(groups) == 1
        assert groups[0]["fragments"].count(
            "frida attach needs the gadget re-pack") == 1


# -------------------------------------------------------------- reward pins

class TestRewardSignal:
    def test_formula(self):
        r = rs.compute_reward(completion=1.0, milestone_progress=0.5,
                              cost_tokens=0.0, cost_seconds=0.0)
        assert r == pytest.approx(1.0 + 0.5)

    def test_cost_term_drag(self):
        r = rs.compute_reward(completion=1.0, milestone_progress=0.0,
                              cost_tokens=rs.COST_TOKENS_NORM,
                              cost_seconds=0.0)
        assert r == pytest.approx(0.0)  # 1.0 - 1.0 (cost saturated)

    def test_pe_pathology_scores_zero(self):
        """A1: many correct facts, zero task completion => ~0 learning
        signal. The old per-fact credit would score this highly."""
        r = rs.compute_reward(completion=0.0, milestone_progress=0.0,
                              cost_tokens=0.0, cost_seconds=0.0)
        assert r == pytest.approx(0.0)
        assert r <= rs.PATHOLOGY_EPSILON

    def test_fact_credit_structurally_out_of_the_signal(self):
        params = inspect.signature(rs.compute_reward).parameters
        assert not any("fact" in p for p in params)
        src = inspect.getsource(rs.compute_reward)
        assert "step_credit" not in src and "scalar" not in src

    def test_episode_reward_gates_milestones_on_trust(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws, "C-1")
        doc = _episode("C-1", milestones=[
            {"id": "M-1", "desc": "real", "verified": True,
             "evidence_ref": ""},  # canonical record exists -> verified
            {"id": "M-2", "desc": "fake", "verified": True,
             "evidence_ref": "runs/never-verified.md"},
        ])
        progress = rs.milestone_progress(ws, doc["claim"], doc["milestones"])
        assert progress == pytest.approx(0.5)

    def test_completion_requires_trust_resolution(self, tmp_path):
        ws = _mk_ws(tmp_path)
        doc = _episode("C-1",
                       outcome={"status": "completed", "verified": True,
                                "evidence_ref": "runs/absent.md"})
        assert rs.task_completion(ws, doc["claim"], doc["outcome"]) == 0.0

    def test_completion_verified_passes(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws, "C-1")
        doc = _episode("C-1")
        assert rs.task_completion(ws, doc["claim"], doc["outcome"]) == 1.0

    def test_on_settlement_stamps_reward_and_stats(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws, "C-1")
        _write(ws, _episode("C-1"))
        # the settlement receipt through the EXISTING consolidated face
        _append_wire_row(ws, "C-1")
        pool.retrieve(ws, ["android"], phase="episode_start")
        out = rs.on_settlement(ws, "C-1")
        assert out["reward"]["r"] > 0.0
        doc, _ = es.read_episode_file(
            ws / "runs" / "episodes" / "episode-C-1.md")
        assert doc["reward"]["r"] == pytest.approx(out["reward"]["r"])
        assert doc["utility"]["citations"] >= 1

    def test_on_settlement_requires_receipt(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws, "C-1")
        _write(ws, _episode("C-1"))
        with pytest.raises(rs.SettlementMissing):
            rs.on_settlement(ws, "C-1")

    def test_audit_face_reports_mass_without_signal(self, tmp_path):
        ws = _mk_ws(tmp_path)
        doc = _episode("C-1")
        audit = rs.audit_fact_mass(doc)
        assert audit["audit_only"] is True
        assert audit["fragment_count"] >= 1
        # ...while the signal itself stays zero (A1)
        assert rs.compute_reward(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)


# ------------------------------------------------- existing-face mapping pins

class TestExistingFacesUntouched:
    """A2: the mappings (strategy_store -> statistics view, lessons/CBM
    -> playbook view, recall_inject -> read face) are DECLARATIONS this
    card pins as unchanged — P2 does the rewiring."""

    def test_strategy_store_face_intact(self):
        from rlvr import strategy_store  # noqa: PLC0415
        assert callable(strategy_store.PosteriorStrategyStore.method_lead)

    def test_lessons_cbm_face_intact(self):
        import lessons_telemetry  # noqa: PLC0415
        assert callable(lessons_telemetry.record_burn)
        assert callable(lessons_telemetry.compute_utility)

    def test_recall_inject_face_intact(self):
        import recall_inject  # noqa: PLC0415
        assert callable(recall_inject.main)

    def test_pool_writes_no_file_outside_runs_episodes(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _pass_verification(ws)
        _write(ws, _episode())
        pool.retrieve(ws, ["android"], phase="episode_start")
        pool.update_on_settlement(ws, "C-1", cited=("C-1",))
        indexer.value_table(ws)
        indexer.playbook_view(ws)
        stray = [str(p.relative_to(ws)) for p in ws.rglob("*")
                 if p.is_file() and "episodes" not in str(p)
                 and p.name != "claim-register.yaml"
                 and "verification-C-1" not in p.name]
        assert stray == [], f"pool wrote outside runs/episodes: {stray}"


# ----------------------------------------------------------------- helpers

def _append_wire_row(ws: Path, claim: str) -> None:
    """Synthetic settlement receipt in the consolidated settlement file —
    the row shape settlement_wire._wire_row writes (schema
    settlement-wire/1, `settled: true`). The hook READS this face; it
    never mints (settlement semantics untouched)."""
    row = {"schema": "settlement-wire/1",
           "ts": "2026-10-25T00:00:00Z",
           "claim": claim,
           "identity": "settler:synthetic",
           "input_path": f"runs/settlement-input-{claim}.json",
           "verdict_path": f"runs/settlement-verdict-{claim}.json",
           "artifacts": 1,
           "settled": True,
           "reason": "",
           "oracle_verdict": "pass",
           "claim_event": "settle_proven",
           "claim_transition": {"ok": True, "from": "OPEN", "to": "PROVEN",
                                "reason": ""}}
    cl.append(ws, "settlement", row)
