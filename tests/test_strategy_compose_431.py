# -*- coding: utf-8 -*-
"""tests/test_strategy_compose_431.py — dynamic context injection pipeline.

Covers the compose single-point (scripts/rlvr/compose.py) against the
round-strategy/1 seam contract (kernel plan tasks W2-T3 / issue 431, fed by
the strategy-object spec in issue 429):

  - strategy object shape validation (four sections + provenance fields)
  - cold-start silence (below the evidence threshold nothing is injected)
  - mint gate: verbatim raw-sample splicing rejected, methodology legal
  - gamma-decay fade ordering (decayed backing loses retrieval rank)
  - staleness: re-derive refreshes the window, orphan cards fade out of
    injection while their files stay on disk (fade, never delete)
  - dedup: unchanged rendered sections keep one content hash and the
    write face skips
  - the contradiction simulation: settling evidence that contradicts the
    current method lead changes the next injection, and the changed lines
    cite the new ledger rows
  - segment discipline pin: card text can never enter the constitution
    segment (render faces reject it; the SessionStart entry has no card path)
  - the YAML seam: both artifact families load as plain YAML with their
    declared schema strings

All fixtures are SYNTHETIC (privacy rule). The store seam is REAL since
issue 462 W3 (rlvr.strategy_store.PosteriorStrategyStore over the landed
q_cells/posteriors faces) — most learned-state touchpoints exercise the
real chain; the explicit _Store stub survives for targeted
scheduling/ranking pins.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
for _p in (SCRIPTS,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import rollout_ledger as rl  # noqa: E402
import state_signature as sigmod  # noqa: E402
from rlvr import compose  # noqa: E402


# ---------------------------------------------------------------- fixtures

def _sig(type_: str, value, source: str = "oracle",
         ts: str = "2026-09-29T00:00:00Z") -> dict:
    return {"type": type_, "source": source, "value": value, "ts": ts}


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _record(ws: Path, rid: str, signals: list[dict]) -> None:
    out = rl.record(ws, kind="task", anchor=rid.split("/", 1)[-1],
                    signals=signals, rollout_id=rid)
    assert out.get("appended") is True, out


def _settle(ws: Path, rid: str, band: str, reward: float) -> None:
    out = rl.settle(ws, rid, {"reward": reward, "band": band,
                              "rule_id": "unit-test", "evidence_refs": [rid]})
    assert out.get("appended") is True, out


def _ok_row(ws: Path, rid: str, family: str) -> None:
    """One settled success rollout for a method family."""
    _record(ws, rid, [_sig("method_family", family, source="envelope"),
                      _sig("oracle_verdict", "PASS")])
    _settle(ws, rid, "SETTLED_GREEN", 1.0)


def _dead_row(ws: Path, rid: str, family: str) -> None:
    """One settled failed rollout (the dead-path card source, issue 391)."""
    _record(ws, rid, [_sig("method_family", family, source="envelope"),
                      _sig("oracle_verdict", "FAIL")])
    _settle(ws, rid, "SETTLED_RED", 0.0)


class _Store:
    """Explicit stub of the compose.StrategyStore protocol seam."""

    def __init__(self, lead=None, weights=None, cell_count=None):
        self.lead = lead
        self.weights = dict(weights or {})
        self.cell_count_value = cell_count

    def method_lead(self, state_fingerprint: str):
        return self.lead

    def decayed_weight(self, row_id: str) -> float:
        return float(self.weights.get(row_id, 1.0))

    def cell_count(self, state_fingerprint: str):
        return self.cell_count_value


def _scheduled_by_kind(cards: list[dict], kind: str) -> list[dict]:
    return [c for c in cards if c["kind"] == kind]


# ------------------------------------------------------------- shape pin

def test_strategy_object_shape_validates(tmp_path):
    ws = _ws(tmp_path)
    _ok_row(ws, "task/ok-1", "method-a")
    _ok_row(ws, "task/ok-2", "method-a")
    store = _Store(lead="method-a", cell_count=2)
    obj = compose.compose(ws, tick=1, store=store)

    assert compose.validate_strategy(obj) == []
    assert obj["schema"] == "round-strategy/1"
    assert obj["tick"] == 1
    assert obj["state_fingerprint"] == sigmod.signature_hash(
        sigmod.snapshot(ws))
    # provenance: composed_from is the sorted consumed-row id set
    assert obj["composed_from"] == ["task/ok-1", "task/ok-2"]
    # the four issue-429 outlets, exactly
    assert set(obj["dispatch"]) == {"method_lead", "anti_hints", "budget_hint"}
    assert set(obj["loop"]) == {"monitor_focus", "ping_policy", "stall_rules"}
    assert set(obj["hooks"]) == {"cards"}
    assert obj["amendments"] == []  # mechanical v1: schema reserves the shape
    assert obj["dispatch"]["method_lead"] == "method-a"

    # determinism: same evidence, later tick -> identical rendered sections
    obj2 = compose.compose(ws, tick=2, store=store)
    assert obj2["content_hash"] == obj["content_hash"]

    # the linter rejects corruption (including any constitution-side key)
    assert compose.validate_strategy(dict(obj, schema="round-strategy/9"))
    mutilated = json.loads(json.dumps(obj))
    mutilated["dispatch"].pop("method_lead")
    assert compose.validate_strategy(mutilated)
    assert compose.validate_strategy(dict(obj, constitution="leak"))
    bad_amendment = dict(obj, amendments=[{"param": "x", "value": 1}])
    assert compose.validate_strategy(bad_amendment)


# ------------------------------------------------------ cold-start silence

def test_cold_start_injects_nothing(tmp_path):
    ws = _ws(tmp_path)
    obj = compose.compose(ws, tick=1)  # no store: identity fallback, no rows
    assert obj["dispatch"]["method_lead"] is None
    assert obj["dispatch"]["anti_hints"] == []
    assert obj["hooks"]["cards"] == []
    assert obj["composed_from"] == []
    assert compose.validate_strategy(obj) == []

    # one settled row is still below the default threshold: whole-object
    # silence (no lead either — cold start is silence, not noise)
    _ok_row(ws, "task/solo", "method-a")
    warm_store = _Store(lead="method-a")
    obj2 = compose.compose(ws, tick=2, store=warm_store)
    assert obj2["hooks"]["cards"] == []
    assert obj2["dispatch"]["method_lead"] is None

    # the store can supply the cell population explicitly
    obj3 = compose.compose(ws, tick=3, store=_Store(lead="method-a",
                                                    cell_count=2))
    assert obj3["dispatch"]["method_lead"] == "method-a"


# ------------------------------------------------------------- mint gate

def test_mint_gate_rejects_verbatim_splice_and_passes_methodology(tmp_path):
    ws = _ws(tmp_path)
    raw = ("the license key constant is derived from the mutated sha256 "
           "iv schedule")
    _record(ws, "task/raw-1",
            [_sig("sample_bytes", raw, source="probe"),
             _sig("method_family", "mod-crypto", source="envelope")])
    _settle(ws, "task/raw-1", "SETTLED_RED", 0.0)
    rows = rl.settled(ws, kind="task")

    common = dict(kind="dead_path", scope_fingerprint="abcdef12",
                  method_family="mod-crypto", backing_refs=["task/raw-1"],
                  minted_tick=1, minted_settlements=1)

    # twelve-word verbatim run against the row's sample field: REJECT
    with pytest.raises(compose.MintGateError):
        compose.mint_card(text=f"note: {raw}", backing_rows=rows, **common)

    # boundary: an eleven-word run is still methodology-shaped
    eleven = " ".join(raw.split()[:11])
    card = compose.mint_card(text=f"avoid: {eleven}", backing_rows=rows,
                             **common)
    assert card["id"].startswith("abcdef12-dead_path-")

    # paraphrase (methodology transcription): mint legal
    legal = compose.mint_card(
        text="re-derive the schedule from constants instead of replaying "
             "the recorded derivation path", backing_rows=rows, **common)
    assert legal["content_hash"]

    # split provenance: six words from row A plus six from row B never
    # forms a twelve-word run against any SINGLE row
    _record(ws, "task/raw-2",
            [_sig("sample_bytes",
                  "wrapper prints the digest then exits", source="probe")])
    _settle(ws, "task/raw-2", "SETTLED_RED", 0.0)
    rows2 = rl.settled(ws, kind="task")
    split = compose.mint_card(
        text="the license key constant is derived from the mutated "
             "wrapper prints the digest then exits",
        backing_rows=rows2,
        kind="dead_path", scope_fingerprint="abcdef12",
        method_family="mod-crypto", backing_refs=["task/raw-1", "task/raw-2"],
        minted_tick=1, minted_settlements=2)
    assert split["backing_refs"] == ["task/raw-1", "task/raw-2"]

    # the pure face names the offending row
    assert compose.mint_gate_violation(f"note: {raw}", rows) == "task/raw-1"


def test_card_identity_is_content_addressed(tmp_path):
    base = dict(kind="dead_path", scope_fingerprint="abcdef12",
                method_family="mod-crypto", text="a methodology sentence",
                backing_refs=["task/x-1"], minted_tick=1,
                minted_settlements=1)
    c1 = compose.mint_card(**base)
    c2 = compose.mint_card(**base)
    assert c1["id"] == c2["id"]
    assert c1["content_hash"] == c2["content_hash"]
    c3 = compose.mint_card(**dict(base, text="a different methodology"))
    assert c3["id"] != c1["id"]


# --------------------------------------------------------- gamma decay

def test_gamma_decay_fade_ordering(tmp_path):
    ws = _ws(tmp_path)
    _ok_row(ws, "task/fresh-1", "method-fresh")
    _ok_row(ws, "task/fresh-2", "method-fresh")
    _dead_row(ws, "task/old-1", "method-stale")
    store = _Store(weights={"task/fresh-1": 1.0, "task/fresh-2": 1.0,
                            "task/old-1": 0.25}, cell_count=3)
    compose.refresh_cards(ws, tick=3)
    cards = compose.load_cards(ws)
    fresh = _scheduled_by_kind(cards, "success_recipe")
    stale = _scheduled_by_kind(cards, "dead_path")
    assert len(fresh) == 1 and len(stale) == 1

    rank_fresh = compose.card_rank(fresh[0], store)
    rank_stale = compose.card_rank(stale[0], store)
    assert rank_fresh == 2.0 and rank_stale == 0.25

    scheduled = compose.schedule_cards(cards, store, settled_total=3, top_k=1)
    assert [c["id"] for c in scheduled] == [fresh[0]["id"]]

    # fully decayed backing fades below the still-fresh card
    store.weights = {"task/fresh-1": 0.0, "task/fresh-2": 0.0,
                     "task/old-1": 1.0}
    faded = compose.schedule_cards(cards, store, settled_total=3, top_k=1)
    assert [c["id"] for c in faded] == [stale[0]["id"]]

    # identity fallback weights every row 1.0 (gamma of one)
    identity = compose.IdentityStore()
    assert compose.card_rank(fresh[0], identity) == 2.0


# ------------------------------------------------------------ staleness

def test_staleness_rederive_refreshes_and_orphans_fade(tmp_path):
    ws = _ws(tmp_path)
    fp = sigmod.signature_hash(sigmod.snapshot(ws))
    _ok_row(ws, "task/base-1", "method-a")
    _ok_row(ws, "task/base-2", "method-a")

    hand = compose.mint_card(kind="dead_path", scope_fingerprint=fp,
                             method_family="method-x",
                             text="hand-written methodology for family x",
                             backing_refs=["task/base-1"],
                             minted_tick=1, minted_settlements=2,
                             evidence_window=5)
    ghost = compose.mint_card(kind="dead_path", scope_fingerprint=fp,
                              method_family="method-ghost",
                              text="methodology with no live backing family",
                              backing_refs=["task/base-2"],
                              minted_tick=1, minted_settlements=2,
                              evidence_window=5)
    compose.save_card(ws, hand)
    compose.save_card(ws, ghost)

    assert not compose.is_stale(hand, settled_total=2)
    assert compose.is_stale(hand, settled_total=8)  # 6 settlements > window 5

    # grow the ledger past the window; the hand card's family still has
    # live rows, so re-derivation produces a fresh template card that
    # supersedes the stale hand card
    _dead_row(ws, "task/x-dead-1", "method-x")
    _dead_row(ws, "task/x-dead-2", "method-x")
    _dead_row(ws, "task/x-dead-3", "method-x")
    _dead_row(ws, "task/x-dead-4", "method-x")
    _dead_row(ws, "task/x-dead-5", "method-x")
    _dead_row(ws, "task/x-dead-6", "method-x")
    report = compose.refresh_cards(ws, tick=9)
    total = len(rl.settled(ws))
    assert total == 8

    cards = compose.load_cards(ws)
    derived = [c for c in cards
               if c["method_family"] == "method-x"
               and c["kind"] == "dead_path"
               and c["id"] != hand["id"]]
    assert len(derived) == 1
    assert report["superseded"] >= 1
    superseded = [c for c in cards if c["id"] == hand["id"]][0]
    assert superseded["superseded_by"] == derived[0]["id"]

    store = _Store(cell_count=total)
    scheduled = compose.schedule_cards(cards, store, settled_total=total,
                                       top_k=8)
    scheduled_ids = {c["id"] for c in scheduled}
    assert derived[0]["id"] in scheduled_ids   # fresh re-derivation injects
    assert hand["id"] not in scheduled_ids     # superseded card never injects

    # the ghost family has no live rows: never re-derived, so once stale it
    # fades out of injection while its file STAYS on disk (fade, not delete)
    assert compose.is_stale(ghost, settled_total=total)
    assert ghost["id"] not in scheduled_ids
    assert (ws / "runs" / "strategy-cards" / f"{ghost['id']}.yaml").exists()


# ---------------------------------------------------------------- dedup

def test_unchanged_content_hash_skips_write(tmp_path):
    ws = _ws(tmp_path)
    _ok_row(ws, "task/ok-1", "method-a")
    _ok_row(ws, "task/ok-2", "method-a")
    store = _Store(lead="method-a", cell_count=2)

    obj1 = compose.compose(ws, tick=1, store=store)
    first = compose.write_strategy(ws, obj1)
    assert first["written"] is True and first["changed"] is True

    obj2 = compose.compose(ws, tick=2, store=store)
    assert obj2["content_hash"] == obj1["content_hash"]
    second = compose.write_strategy(ws, obj2)
    assert second["written"] is False and second["changed"] is False
    assert second["reason"] == "unchanged"

    ticks = list((ws / "runs" / "round-strategy").glob("tick-*.yaml"))
    assert len(ticks) == 1

    # changed evidence -> changed hash -> the write lands
    _dead_row(ws, "task/dead-x", "method-a")
    store.lead = "method-b"
    obj3 = compose.compose(ws, tick=3, store=store)
    assert obj3["content_hash"] != obj1["content_hash"]
    third = compose.write_strategy(ws, obj3)
    assert third["written"] is True and third["changed"] is True


# ------------------------------------------------- contradiction simulation

def test_contradicting_settlement_changes_next_injection(tmp_path):
    """The acceptance gold line: injected content CHANGES with evidence.

    A stub store favors method-a while the ledger holds only successes;
    a contradicting FAIL settlement lands; the next composition leads
    with the alternative family, injects the dead-path card, and the
    changed lines cite the new ledger row.
    """
    ws = _ws(tmp_path)
    _ok_row(ws, "task/ok-1", "method-a")
    _ok_row(ws, "task/ok-2", "method-a")
    store = _Store(lead="method-a",
                   weights={"task/ok-1": 1.0, "task/ok-2": 1.0})

    obj1 = compose.compose(ws, tick=1, store=store)
    assert obj1["dispatch"]["method_lead"] == "method-a"
    cards1 = set(obj1["hooks"]["cards"])
    first = compose.write_strategy(ws, obj1)
    assert first["changed"] is True

    # the contradiction: the favored family just failed on a new unit
    _dead_row(ws, "task/dead-1", "method-a")
    store.lead = "method-b"

    obj2 = compose.compose(ws, tick=2, store=store)
    assert obj2["dispatch"]["method_lead"] == "method-b"
    assert set(obj2["hooks"]["cards"]) != cards1
    assert "task/dead-1" in obj2["composed_from"]

    # every changed line carries its ledger attribution
    anti = "\n".join(obj2["dispatch"]["anti_hints"])
    assert "dead_path" in anti
    assert "task/dead-1" in anti

    second = compose.write_strategy(ws, obj2)
    assert second["written"] is True and second["changed"] is True

    # and the whole chain validates against the seam schema
    assert compose.validate_strategy(obj2) == []


# --------------------------------------------------- segment discipline

def test_constitution_segment_stays_card_free(tmp_path):
    ws = _ws(tmp_path)
    _ok_row(ws, "task/ok-1", "method-a")
    _ok_row(ws, "task/ok-2", "method-a")
    card = compose.mint_card(kind="success_recipe",
                             scope_fingerprint="abcdef12",
                             method_family="method-a",
                             text="prefer the steady family at this scope",
                             backing_refs=["task/ok-1"],
                             minted_tick=1, minted_settlements=2)

    # the render face hard-rejects the constitution segment
    with pytest.raises(compose.SegmentError):
        compose.render_card_block(card, segment=compose.SEGMENT_CONSTITUTION)
    assert compose.render_card_block(
        card, segment=compose.SEGMENT_STRATEGY).startswith("[success_recipe]")

    # a composed object can never grow a constitution-side key: the
    # validator enforces the exact section set
    obj = compose.compose(ws, tick=1, store=_Store(lead="method-a",
                                                   cell_count=2))
    assert compose.validate_strategy(dict(obj, constitution="leak"))
    assert "constitution" not in obj

    # static pin on the local SessionStart entry: it has no compose import
    # and no card-library path, so nothing can flow cards into a
    # constitution face through it
    source = (HOOKS / "session_start.py").read_text(encoding="utf-8")
    assert "rlvr" not in source
    assert "strategy-cards" not in source
    assert "compose" not in source


# ------------------------------------------------------------- YAML seam

def test_round_strategy_yaml_seam(tmp_path):
    """The consumer-facing seam: plain YAML both artifact families."""
    ws = _ws(tmp_path)
    _ok_row(ws, "task/ok-1", "method-a")
    _ok_row(ws, "task/ok-2", "method-a")
    _dead_row(ws, "task/dead-1", "method-a")
    store = _Store(lead="method-a", cell_count=3)

    obj = compose.compose(ws, tick=1, store=store)
    out = compose.write_strategy(ws, obj)
    assert out["written"] is True

    doc = yaml.safe_load(out["path"].read_text(encoding="utf-8"))
    assert doc["schema"] == "round-strategy/1"
    assert set(doc) >= {"tick", "state_fingerprint", "composed_from",
                        "content_hash", "dispatch", "loop", "hooks",
                        "amendments"}
    assert doc["dispatch"]["method_lead"] == "method-a"

    cards = compose.load_cards(ws)
    assert cards, "expected accumulated cards"
    for card in cards:
        path = ws / "runs" / "strategy-cards" / f"{card['id']}.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert raw["schema"] == "card/1"
        assert set(raw) >= {"id", "kind", "scope_fingerprint",
                            "method_family", "text", "backing_refs",
                            "minted_tick", "evidence_window",
                            "superseded_by", "content_hash"}
        assert raw["kind"] in compose.CARD_KINDS
        assert raw["superseded_by"] is None

    # the read face returns the latest strategy for resume continuity
    latest = compose.read_strategy(ws)
    assert latest is not None and latest["content_hash"] == obj["content_hash"]


# ------------------------------------------------- store seam: the real face

def test_load_store_returns_the_posterior_store(tmp_path):
    """W3 (#462): the store seam is REAL — load_store returns the
    PosteriorStrategyStore over the landed posterior/q-cell faces, never
    a silent fake-policy fallback."""
    from rlvr.strategy_store import PosteriorStrategyStore
    store = compose.load_store(tmp_path)
    assert isinstance(store, PosteriorStrategyStore)
    # cold workspace, no q-cell log: the seam's documented fallback face
    # (None cell count -> compose falls back to the settled-ledger total)
    assert store.method_lead("abcdabcdabcd") is None
    assert store.decayed_weight("task/whatever") == 1.0
    assert store.cell_count("abcdabcdabcd") is None


def test_load_store_silent_identity_degrade_stays_closed():
    """The stale-import tripwire (issue 462 W3 acceptance): if the store
    import ever goes stale again, load_store must FAIL LOUDLY — the
    silent IdentityStore degrade (method_lead=None, unit weights) was the
    defect this wiring closes. AST-based: docstring prose may explain the
    closed defect; the CODE may never reference the fallback again."""
    import ast as _ast
    tree = _ast.parse(
        (SCRIPTS / "rlvr" / "compose.py").read_text(encoding="utf-8"))
    body = None
    for node in _ast.walk(tree):
        if isinstance(node, _ast.FunctionDef) \
                and node.name == "load_store":
            body = node
            break
    assert body is not None, "load_store vanished from compose.py"
    names = {n.id for n in _ast.walk(body) if isinstance(n, _ast.Name)}
    names |= {n.attr for n in _ast.walk(body)
              if isinstance(n, _ast.Attribute)}
    assert "IdentityStore" not in names, \
        "load_store silently degrades to IdentityStore again"
    assert "PosteriorsStore" not in names, \
        "load_store points at a nonexistent store face again"


def test_posterior_store_method_lead_and_cells_follow_evidence(tmp_path):
    """The real store's learned faces on a seeded workspace: settled rows
    declaring one family + banked q-cell rows make the lead and the cell
    population real (no stub in sight)."""
    from rlvr import q_cells
    ws = _ws(tmp_path)
    _ok_row(ws, "task/lead-1", "static-decompile")
    _ok_row(ws, "task/lead-2", "static-decompile")
    fp = sigmod.signature_hash(sigmod.snapshot(ws))
    q_cells.append_observation(ws, fp, "static-decompile", None,
                               source="dispatch", claim="tr-m1-d1")
    q_cells.observe(ws, fp, "static-decompile", 1.0)
    store = compose.load_store(ws)
    assert store.cell_count(fp) == 2
    # the only proposal channel face: the sample degenerates to it
    assert store.method_lead(fp) == "static-decompile"
    # another state carries no cell mass of its own (state-conditioned)
    assert store.cell_count("ffffffffffff") == 0


def test_posterior_store_decayed_weight_fades_old_rows(tmp_path):
    ws = _ws(tmp_path)
    # settled() orders by (ts, rollout_id): zzz sorts LAST, so it is the
    # stream's freshest end (weight 1.0); aaa sits one settlement back
    _ok_row(ws, "task/aaa-old", "method-a")
    _ok_row(ws, "task/zzz-new", "method-a")
    store = compose.load_store(ws)
    w_new = store.decayed_weight("task/zzz-new")
    w_old = store.decayed_weight("task/aaa-old")
    assert w_new == 1.0
    assert 0.0 < w_old < 1.0  # γ-decayed under the shipped DTS schedule
    # foreign ids keep the unit weight (no invented decay for unknown rows)
    assert store.decayed_weight("task/not-in-ledger") == 1.0


def test_prior_channel_counts_proposals_never_outcomes(tmp_path):
    """Review follow-up (W3 MEDIUM): the P_LLM proposal prior counts the
    two PROPOSAL faces only — dispatch rows and settled method_family
    signals. Settlement-source q-cell rows are OUTCOME data; counting
    them would skew the prior toward dispatch-heavy families."""
    from rlvr import q_cells
    ws = _ws(tmp_path)
    fp = sigmod.signature_hash(sigmod.snapshot(ws))
    # one declared proposal: static-decompile
    q_cells.append_observation(ws, fp, "static-decompile", None,
                               source="dispatch", claim="tr-m1-d1")
    # five settlement rows for another family: OUTCOME data, no proposal
    for _ in range(5):
        q_cells.observe(ws, fp, "dynamic-trace", 0.0)
    store = compose.load_store(ws)
    prior = store._proposal_prior()
    assert prior == {"static-decompile": 1.0}
    assert store.method_lead(fp) == "static-decompile"


def test_prior_channel_intersects_the_registered_vocabulary(tmp_path):
    """462 design-review MEDIUM-3: the PRODUCTION prior gets the same
    registry intersect the W4 sampler face has — a retired token must
    never ride the prior into the loop prompt (the lead is advisory,
    but steering declarations the fail-closed #432 gate rejects is the
    lockstep hazard in advisory form)."""
    from rlvr import q_cells
    ws = _ws(tmp_path)
    fp = sigmod.signature_hash(sigmod.snapshot(ws))
    # a retired token's declarations (recorded while registered)
    q_cells.append_observation(ws, fp, "zz-retired-token", None,
                               source="dispatch")
    q_cells.append_observation(ws, fp, "static-decompile", None,
                               source="dispatch")
    store = compose.load_store(ws)
    prior = store._proposal_prior()
    assert prior == {"static-decompile": 1.0}, \
        "retired tokens never ride the production prior"
    assert store.method_lead(fp) == "static-decompile"


# --------------------------------------------- the consumer seam (462 W2)

def test_write_strategy_emits_the_sections_seam(tmp_path):
    """W2 (#462): the producer/consumer seam is ALIGNED — write_strategy
    emits ``runs/round-strategy.json`` shaped
    ``{schema, round, sections:[{title, body}]}`` (the shape the live
    loop-prompt seam reads), derived deterministically from the versioned
    strategy object. The tick files stay the reconstructable ledger."""
    ws = _ws(tmp_path)
    _ok_row(ws, "task/s1", "static-decompile")
    _ok_row(ws, "task/s2", "static-decompile")
    # budget telemetry present: the budget line rides the lead section
    # (advisory context for the lead decision — the warm branch)
    (ws / "cost_events.jsonl").write_text(
        json.dumps({"cost_usd": 0.5}) + "\n", encoding="utf-8")
    obj = compose.compose(ws, tick=1)  # the REAL store (W3) — no stub
    compose.write_strategy(ws, obj)
    seam_path = ws / "runs" / "round-strategy.json"
    seam = json.loads(seam_path.read_text(encoding="utf-8"))
    assert seam["schema"] == "round-strategy/1"
    assert seam["round"] == 1
    assert seam["sections"], "non-empty sections"
    for sec in seam["sections"]:
        assert set(sec) == {"title", "body"}
        assert sec["body"].strip()
    titles = {s["title"] for s in seam["sections"]}
    assert "dispatch-lead" in titles
    # the live loop-prompt seam renders REAL strategy content now
    import strategy_sections
    rendered = strategy_sections.render(ws)
    assert rendered != ""
    assert "round-strategy" in rendered
    assert "method lead" in rendered
    assert "budget:" in rendered
    assert strategy_sections.pointer(ws) == "runs/round-strategy.json"


def test_seam_is_deterministic_and_self_healing(tmp_path):
    """Same strategy object -> byte-identical seam file (the round field
    is part of the seam's identity: it names the round the strategy is
    in force for); a DELETED or CORRUPT (including non-UTF-8 — the W2
    review MEDIUM-1 case) seam is re-emitted byte-exact by the next
    write_strategy call, which must never raise on the seam face."""
    import strategy_sections
    ws = _ws(tmp_path)
    _ok_row(ws, "task/s1", "static-decompile")
    _ok_row(ws, "task/s2", "static-decompile")
    obj1 = compose.compose(ws, tick=1)
    compose.write_strategy(ws, obj1)
    seam_path = ws / "runs" / "round-strategy.json"
    first = seam_path.read_bytes()
    compose.write_strategy(ws, obj1)
    assert seam_path.read_bytes() == first
    # deleted -> re-emitted
    seam_path.unlink()
    compose.write_strategy(ws, obj1)
    assert seam_path.read_bytes() == first
    # corrupt (non-UTF-8 bytes) -> repaired, never raised (the tick write
    # dedups unchanged, but the seam face still heals itself)
    seam_path.write_bytes(b"\xff\xfe broken \xff")
    compose.write_strategy(ws, obj1)
    assert seam_path.read_bytes() == first
    assert strategy_sections.render(ws) != ""


def test_workguard_guidance_renders_the_composed_strategy(tmp_path):
    """The W2 acceptance integration pin: the WORKGUARD turn-exit
    guidance (the live loop-prompt dynamic face) renders non-empty
    strategy sections produced by the REAL compose chain."""
    import workguard
    ws = _ws(tmp_path)
    _ok_row(ws, "task/s1", "static-decompile")
    _ok_row(ws, "task/s2", "static-decompile")
    compose.write_strategy(ws, compose.compose(ws, tick=1))
    result = {"claims": [{"id": "C-1", "why": workguard.WHY_DISPATCHABLE}],
              "walls": [], "active_workers": []}
    guidance = workguard.turn_exit_guidance(Path(ws), result)
    assert "WORKGUARD" in guidance
    assert "<round-strategy" in guidance
    assert "method lead" in guidance


def test_cold_seam_renders_nothing_cleanly(tmp_path):
    """A silent (below-threshold) strategy still emits the seam FILE, but
    with empty bodies — and the consumers render NOTHING (no headers, no
    placeholder noise; the pre-existing seam contract). UNCONDITIONAL:
    budget telemetry present does not break the cold-start silence (the
    W2 review MEDIUM-2 case — budget_hint is advisory context for a
    lead; a lead-less strategy renders nothing)."""
    import strategy_sections
    ws = _ws(tmp_path)
    compose.write_strategy(ws, compose.compose(ws, tick=1))
    seam = json.loads(
        (ws / "runs" / "round-strategy.json").read_text(encoding="utf-8"))
    assert seam["sections"] == []
    assert strategy_sections.render(ws) == ""
    assert strategy_sections.pointer(ws) == "runs/round-strategy.json"
    # the same cold silence holds with budget telemetry on the workspace
    # (the REAL telemetry face: state.COST_EVENTS_REL, ws root)
    (ws / "cost_events.jsonl").write_text(
        json.dumps({"cost_usd": 0.1}) + "\n", encoding="utf-8")
    compose.write_strategy(ws, compose.compose(ws, tick=2))
    seam2 = json.loads(
        (ws / "runs" / "round-strategy.json").read_text(encoding="utf-8"))
    assert seam2["sections"] == [], \
        "budget telemetry must not break the cold-start silence"
    assert strategy_sections.render(ws) == ""


def test_injection_changes_with_evidence_across_two_runs(tmp_path):
    """The #429 §9 central clause, mechanically demonstrated through the
    REAL chain end to end (settled evidence -> card library -> store ->
    compose -> seam): two decision events with different evidence produce
    VISIBLY different injected content, every changed line citing its
    backing ledger row."""
    import strategy_sections
    ws = _ws(tmp_path)
    # run 1: two green rounds of method-a — the injection prefers it
    _ok_row(ws, "task/r1-a", "static-decompile")
    _ok_row(ws, "task/r1-b", "static-decompile")
    obj1 = compose.compose(ws, tick=1)
    compose.write_strategy(ws, obj1)
    seam1 = (ws / "runs" / "round-strategy.json").read_text(encoding="utf-8")
    rendered1 = strategy_sections.render(ws)
    assert "static-decompile" in rendered1
    assert "dead path" not in rendered1

    # run 2: the environment contradicted the favored family — method-a
    # just FAILED on a new unit (a settled red row citing the new unit)
    _dead_row(ws, "task/r2-dead", "static-decompile")
    obj2 = compose.compose(ws, tick=2)
    compose.write_strategy(ws, obj2)
    seam2 = (ws / "runs" / "round-strategy.json").read_text(encoding="utf-8")
    rendered2 = strategy_sections.render(ws)
    # the injected content CHANGED, and the change is attributable
    assert seam2 != seam1
    assert "dead path" in rendered2
    assert "task/r2-dead" in rendered2
    assert "task/r2-dead" in obj2["composed_from"]
    assert obj2["hooks"]["cards"] != obj1["hooks"]["cards"]


# ------------------------------- the live store seam (candidate fallback)

def _store_root(tmp_path, monkeypatch, rows) -> Path:
    """An isolated posterior store holding the given rows (the conftest
    autouse fixture already isolates the env; this points it at rows)."""
    from rlvr import strategy_store
    root = tmp_path / "posterior-store"
    root.mkdir()
    (root / strategy_store.STORE_REL).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setenv(strategy_store.STORE_ENV, str(root))
    return root


def _store_row(ws_id, family, arm_key=None, credit=0.9):
    return {"schema": "posterior-store/1", "ts": "2026-10-01T00:00:00Z",
            "workspace_id": ws_id,
            "arm_key": arm_key or f"{family}|facts_snapshot|none|1",
            "method_family": family, "feature_key": "none",
            "fingerprint": "fp000011112222", "status": "ROUND_CREDIT",
            "credit": credit, "censored": False, "facts_citing": 2,
            "propensity": None, "phi_delta": None,
            "provenance": {"dispatch_id": f"C-{family}"}}


def test_method_lead_falls_back_to_the_cross_task_store(tmp_path,
                                                        monkeypatch):
    """A workspace with no proposal of its own still draws: the cross-task
    store's families carry the candidate set, so the live store write is
    read back through the one sampler instead of dead-ending on empty
    material."""
    ws = _ws(tmp_path)  # no q-cell rows, no settled rows: no proposals
    _store_root(tmp_path, monkeypatch,
                [_store_row("other-ws", "static-decompile")])
    store = compose.load_store(ws)
    assert store._proposal_prior() == {}, "no local proposal channel"
    assert store.method_lead("abcdabcdabcd") == "static-decompile"


def test_store_fallback_filters_unregistered_and_refutation_rows(
        tmp_path, monkeypatch):
    """The fallback candidate channel holds the same two walls as the
    local prior: a retired/unknown token never rides it, and the
    refutation fold's own rows (its arm key) are never proposals."""
    ws = _ws(tmp_path)
    _store_root(tmp_path, monkeypatch, [
        _store_row("other-ws", "zz-retired-token"),
        _store_row("other-ws", "verify", arm_key="refutation"),
    ])
    store = compose.load_store(ws)
    assert store.method_lead("abcdabcdabcd") is None, \
        "no registered method-arm candidate exists in the store"


def test_store_arm_constant_matches_the_refutation_fold():
    """Drift pin: the fallback channel's exclusion key mirrors the
    refutation fold's store arm — a rename on either side fails here."""
    from rlvr import refutation_fold
    from rlvr import strategy_store
    assert strategy_store._REFUTATION_ARM == refutation_fold.STORE_ARM


def test_evidence_gate_reads_the_live_ledger_when_the_cell_is_empty(
        tmp_path):
    """The live starvation shape: q-cell rows exist at OTHER signatures
    (the state moved) while settled rows fill the ledger — the gate must
    fall back to the ledger evidence base and let the lead sample, not
    read 0-at-this-signature as total silence."""
    from rlvr import q_cells
    ws = _ws(tmp_path)
    _ok_row(ws, "task/ok-1", "static-decompile")
    _ok_row(ws, "task/ok-2", "static-decompile")
    q_cells.append_observation(ws, "deadbeef0000", "static-decompile", 1.0,
                               source="settlement", claim="C-9")
    store = compose.load_store(ws)
    fp = sigmod.signature_hash(sigmod.snapshot(ws))
    assert store.cell_count(fp) == 0, "no cell at the current signature"
    obj = compose.compose(ws, tick=1, store=store)
    assert obj["dispatch"]["method_lead"] == "static-decompile"
