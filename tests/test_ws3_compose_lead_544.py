# -*- coding: utf-8 -*-
"""tests/test_ws3_compose_lead_544.py — WS3 (#544) RED-first pins: the
below-n_min compose path emits the seeded lead instead of silence.

EXP-WS3-A honesty framing (experiments/exp-ws3-calibration.md,
read-only): Spearman ρ = −0.3714 (n=6, 44 transitions) → BETA_SEED_CAP
= 0.5. The lead REPLACES SILENCE below the evidence threshold; it does
not claim signal — everything else in `_silent_sections` (policy
constants, empty cards/focus, budget hint) stays byte-identical, and a
missing/corrupt prior file degrades to exactly the old full silence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (SCRIPTS,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import rollout_ledger as rl  # noqa: E402
import state_signature as sigmod  # noqa: E402
from rlvr import compose  # noqa: E402
from rlvr import priors as rl_priors  # noqa: E402

SPEC = {
    "goal_verbatim": "recover the license key derivation and prove it by "
                     "replay harness equivalence",
    "success_criterion": "a standalone client replays every captured "
                         "(input -> plaintext) pair byte-exact",
    "verification_method": "reproduction",
    "lane": "static",
    "project_type": "linux",
}
FAMILIES = ["replay-harness-verification", "static-decompile"]
LEAD_FAMILY = "replay-harness-verification"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    import yaml

    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump(SPEC, sort_keys=True), encoding="utf-8")
    return ws


def _seed(ws: Path) -> dict:
    return rl_priors.seed_intake_prior(ws, families=FAMILIES)


def _sig(type_: str, value, source: str = "oracle",
         ts: str = "2026-09-29T00:00:00Z") -> dict:
    return {"type": type_, "source": source, "value": value, "ts": ts}


def _ok_row(ws: Path, rid: str, family: str) -> None:
    out = rl.record(ws, kind="task", anchor=rid.split("/", 1)[-1],
                    signals=[_sig("method_family", family, source="envelope"),
                             _sig("oracle_verdict", "PASS")],
                    rollout_id=rid)
    assert out.get("appended") is True, out
    out = rl.settle(ws, rid, {"reward": 1.0, "band": "SETTLED_GREEN",
                              "rule_id": "unit-test", "evidence_refs": [rid]})
    assert out.get("appended") is True, out


# ------------------------------------------------- the no-longer-silent path

def test_below_nmin_emits_the_seeded_lead(tmp_path):
    """Deliverable 2: the evidence_count < n_min branch emits the seeded
    method_lead read from runs/llm-prior.json (the highest
    alpha/(alpha+beta) family) instead of null."""
    ws = _ws(tmp_path)
    doc = _seed(ws)
    _ok_row(ws, "task/solo", "static-decompile")  # 1 settled row < n_min 2
    obj = compose.compose(ws, tick=1)

    assert obj["dispatch"]["method_lead"] == rl_priors.intake_prior_lead(doc)
    assert obj["dispatch"]["method_lead"] == LEAD_FAMILY
    # everything else in the silent sections stays identical: the policy
    # constants still render, cards/focus/anti-hints stay empty
    assert obj["dispatch"]["anti_hints"] == []
    assert obj["loop"]["ping_policy"] == compose.PING_POLICY
    assert obj["loop"]["stall_rules"] == list(compose.STALL_RULES)
    assert obj["loop"]["monitor_focus"] == []
    assert obj["hooks"]["cards"] == []
    assert obj["amendments"] == []
    assert compose.validate_strategy(obj) == []


def test_below_nmin_without_prior_file_is_exactly_the_old_silence(
        tmp_path):
    """Fail-open: no llm-prior.json => exactly the old `_silent_sections`
    output (method_lead None)."""
    ws = _ws(tmp_path)
    _ok_row(ws, "task/solo", "static-decompile")
    obj = compose.compose(ws, tick=1)
    assert obj["dispatch"]["method_lead"] is None
    assert obj["dispatch"] == compose._silent_sections(
        sigmod.snapshot(ws))["dispatch"]
    assert obj["hooks"]["cards"] == []
    assert compose.validate_strategy(obj) == []


def test_below_nmin_corrupt_prior_file_degrades_to_silence(tmp_path):
    ws = _ws(tmp_path)
    _seed(ws)
    _ok_row(ws, "task/solo", "static-decompile")
    (ws / "runs" / "llm-prior.json").write_text(
        "(((( not json", encoding="utf-8")
    obj = compose.compose(ws, tick=1)
    assert obj["dispatch"]["method_lead"] is None


def test_below_nmin_wrong_schema_prior_degrades_to_silence(tmp_path):
    ws = _ws(tmp_path)
    _seed(ws)
    _ok_row(ws, "task/solo", "static-decompile")
    (ws / "runs" / "llm-prior.json").write_text(
        json.dumps({"schema": "llm-prior/7", "families": {}}),
        encoding="utf-8")
    obj = compose.compose(ws, tick=1)
    assert obj["dispatch"]["method_lead"] is None


def test_below_nmin_seeded_compose_is_deterministic(tmp_path):
    """The determinism wall: same workspace state (including the prior
    file) => identical rendered sections => identical content_hash."""
    ws = _ws(tmp_path)
    _seed(ws)
    _ok_row(ws, "task/solo", "static-decompile")
    obj1 = compose.compose(ws, tick=1)
    obj2 = compose.compose(ws, tick=2)
    assert obj1["content_hash"] == obj2["content_hash"]
    assert obj1["dispatch"]["method_lead"] == LEAD_FAMILY


def test_warm_path_lead_still_comes_from_the_store(tmp_path):
    """At or above n_min the seeded prior is out of the picture: the
    store's lead wins (the seed is a cold-start face only)."""
    ws = _ws(tmp_path)
    _seed(ws)
    _ok_row(ws, "task/ok-1", "static-decompile")
    _ok_row(ws, "task/ok-2", "static-decompile")
    store = compose.load_store(ws)
    obj = compose.compose(ws, tick=1, store=store)
    assert obj["dispatch"]["method_lead"] == "static-decompile"
    assert obj["dispatch"]["method_lead"] != LEAD_FAMILY


def test_seam_renders_the_seeded_lead(tmp_path):
    """The seeded lead flows through the consumer seam: the
    below-n_min strategy's dispatch-lead section names the family."""
    import strategy_sections

    ws = _ws(tmp_path)
    _seed(ws)
    obj = compose.compose(ws, tick=1)
    out = compose.write_strategy(ws, obj)
    assert out["written"] is True
    seam = json.loads(
        (ws / "runs" / "round-strategy.json").read_text(encoding="utf-8"))
    titles = {s["title"] for s in seam["sections"]}
    assert "dispatch-lead" in titles
    body = next(s for s in seam["sections"]
                if s["title"] == "dispatch-lead")["body"]
    assert LEAD_FAMILY in body
    assert strategy_sections.render(ws) != ""


def test_cold_seam_without_prior_still_renders_nothing(tmp_path):
    import strategy_sections

    ws = _ws(tmp_path)
    compose.write_strategy(ws, compose.compose(ws, tick=1))
    seam = json.loads(
        (ws / "runs" / "round-strategy.json").read_text(encoding="utf-8"))
    assert seam["sections"] == []
    assert strategy_sections.render(ws) == ""


def test_n_min_default_is_unchanged(tmp_path):
    """Hyperparameter discipline: DEFAULT_N_MIN stays 2 (no new knobs —
    BETA_SEED_CAP is the only WS3 constant)."""
    assert compose.DEFAULT_N_MIN == 2
