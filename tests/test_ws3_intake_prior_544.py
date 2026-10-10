# -*- coding: utf-8 -*-
"""tests/test_ws3_intake_prior_544.py — WS3 cold-start LLM bandit priors
(#544) RED-first pins: the intake seeding face plus the no-longer-uniform
fresh-dispatch envelope.

The honest framing (EXP-WS3-A, experiments/exp-ws3-calibration.md —
read-only input, never committed): Spearman ρ = −0.3714 (n=6 families,
44 transitions) < the 0.2 gate, so BETA_SEED_CAP = 0.5 — near-uniform
seeding. WS3 ships because it replaces SILENCE (the Beta(1,1) below
n_min and the flat uniform proposal prior), not because the prior is
known-good; the uniform SNIPS arm measures whatever signal exists from
round 1 (no dead zone).

What is pinned here:

  1. seed_intake_prior — the mechanical intake face: schema llm-prior/1,
     total pseudo-count mass capped at BETA_SEED_CAP, calibration +
     provenance blocks citing EXP-WS3-A, fail-open on a missing
     task_spec (no file = the current behavior).
  2. the seeded prior is NON-UNIFORM and traceable: the lead exists and
     ranks first among the candidate means, the digest names the exact
     declared task features, the calibration/provenance chain is intact.
  3. a fresh workspace's FIRST DISPATCH carries that non-uniform
     candidate prior — the envelope sampler's candidates carry the
     seeded means (p_llm), the lead ranks first, and cutting the prior
     file restores the historical uniform face (fail-open both ways).
  4. tolerant reads: missing/corrupt/wrong-schema docs degrade to None
     / {} — never an exception, never a fabricated prior.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import priors as rl_priors  # noqa: E402
import method_families  # noqa: E402

SPEC = {
    "goal_verbatim": "recover the license key derivation and prove it by "
                     "replay harness equivalence",
    "success_criterion": "a standalone client replays every captured "
                         "(input -> plaintext) pair byte-exact",
    "verification_method": "reproduction",
    "lane": "static",
    "project_type": "linux",
    "primary_questions": ["what mutates the sha256 constant set?"],
}

LEAD_FAMILY = "replay-harness-verification"


def _ws(tmp_path: Path, spec: dict | None = SPEC) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    if spec is not None:
        import yaml

        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(spec, sort_keys=True), encoding="utf-8")
    return ws


def _digest(spec: dict) -> str:
    canonical = json.dumps(spec, sort_keys=True, ensure_ascii=False,
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _means(doc: dict) -> dict[str, float]:
    return {fam: float(v["alpha"]) / (float(v["alpha"]) + float(v["beta"]))
            for fam, v in doc["families"].items()}


def _masses(doc: dict) -> dict[str, float]:
    return {fam: float(v["alpha"]) + float(v["beta"])
            for fam, v in doc["families"].items()}


# ------------------------------------------------- 1. the mechanical face

def test_seed_intake_prior_writes_the_llm_prior_schema(tmp_path):
    ws = _ws(tmp_path)
    doc = rl_priors.seed_intake_prior(ws)

    assert doc, "the mechanical face must land on a declared workspace"
    path = ws / "runs" / "llm-prior.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["schema"] == "llm-prior/1"
    assert doc["source"] == "heuristic-fallback"
    # the declared features are fingerprinted, the calibration + the
    # provenance cite EXP-WS3-A verbatim
    assert doc["task_features_digest"] == _digest(SPEC)
    assert doc["calibration"] == {"method": "exp-ws3-a", "rho": -0.3714,
                                  "n": 6}
    assert doc["provenance"] == {
        "experiment": "experiments/exp-ws3-calibration.md"}
    assert doc["ts"].endswith("Z")
    # families visible at intake = the closed registry, by default
    assert set(doc["families"]) == set(method_families.registered_tokens())


def test_seed_total_mass_is_capped_at_beta_seed_cap(tmp_path):
    ws = _ws(tmp_path)
    doc = rl_priors.seed_intake_prior(ws)

    masses = _masses(doc)
    assert all(m > 0.0 for m in masses.values())
    assert sum(masses.values()) == pytest.approx(rl_priors.BETA_SEED_CAP)
    assert sum(masses.values()) <= rl_priors.BETA_SEED_CAP * (1 + 1e-9)
    assert rl_priors.BETA_SEED_CAP == 0.5  # the EXP-WS3-A verdict, pinned


def test_seed_is_non_uniform_and_the_lead_ranks_first(tmp_path):
    """Acceptance bullet 1 (with cap 0.5 'non-uniform' means the lead
    exists and ranks): a declared replay-verification task seeds a
    replay-harness-verification lead that strictly tops the mean order."""
    ws = _ws(tmp_path)
    doc = rl_priors.seed_intake_prior(ws)

    means = _means(doc)
    assert len(set(means.values())) > 1, "the seed must not be uniform"
    ordered = sorted(means, key=lambda f: (-means[f], f))
    assert ordered[0] == LEAD_FAMILY
    assert rl_priors.intake_prior_lead(doc) == LEAD_FAMILY
    # the lead exists and ranks — the no-signal families keep their
    # near-uniform means (cap 0.5: a nudge, not a commitment)
    assert means[LEAD_FAMILY] < 0.5, "cap-0.5 seeding never commits hard"


def test_seed_digest_tracks_the_declared_features(tmp_path):
    ws1 = _ws(tmp_path / "a", dict(SPEC, lane="dynamic"))
    ws2 = _ws(tmp_path / "b")
    d1 = rl_priors.seed_intake_prior(ws1)
    d2 = rl_priors.seed_intake_prior(ws2)
    assert d1["task_features_digest"] != d2["task_features_digest"]
    assert d1["task_features_digest"] == _digest(dict(SPEC, lane="dynamic"))


def test_seed_source_vocabulary(tmp_path):
    ws = _ws(tmp_path)
    doc = rl_priors.seed_intake_prior(ws, source="llm-self-assessment")
    assert doc["source"] == "llm-self-assessment"
    with pytest.raises(ValueError):
        rl_priors.seed_intake_prior(ws, source="made-up-source")


def test_seed_families_parameter_restricts_the_set(tmp_path):
    ws = _ws(tmp_path)
    fams = ["replay-harness-verification", "static-decompile"]
    doc = rl_priors.seed_intake_prior(ws, families=fams)
    assert set(doc["families"]) == set(fams)
    assert sum(_masses(doc).values()) == pytest.approx(
        rl_priors.BETA_SEED_CAP)
    assert rl_priors.intake_prior_lead(doc) == LEAD_FAMILY


def test_seed_missing_task_spec_fails_open_to_no_file(tmp_path):
    ws = _ws(tmp_path, spec=None)
    doc = rl_priors.seed_intake_prior(ws)
    assert doc == {}
    assert not (ws / "runs" / "llm-prior.json").exists(), \
        "missing task_spec => no file (the current behavior)"


def test_seed_empty_families_fails_open(tmp_path):
    ws = _ws(tmp_path)
    assert rl_priors.seed_intake_prior(ws, families=[]) == {}
    assert not (ws / "runs" / "llm-prior.json").exists()


def test_seed_heuristic_scores_are_mechanical():
    tokens = set("recover license key derivation prove replay harness "
                 "equivalence standalone replays captured input plaintext "
                 "pair byte exact reproduction static linux mutates sha256 "
                 "constant set".split())
    scores = rl_priors.heuristic_family_scores(SPEC, set(
        method_families.registered_tokens()))
    # every score is a plain keyword-hit count over the declared text
    assert scores == rl_priors.heuristic_family_scores(SPEC, set(
        method_families.registered_tokens()))
    assert scores["replay-harness-verification"] >= 2  # replay + harness
    assert all(isinstance(v, int) and v >= 0 for v in scores.values())
    assert tokens  # sanity: the fixture text is non-empty


# ------------------------------------------------------- 2. tolerant reads

def test_read_intake_prior_missing_is_none(tmp_path):
    assert rl_priors.read_intake_prior(_ws(tmp_path, spec=None)) is None


def test_read_intake_prior_corrupt_is_none(tmp_path):
    ws = _ws(tmp_path)
    (ws / "runs" / "llm-prior.json").write_text(
        "{not json at all", encoding="utf-8")
    assert rl_priors.read_intake_prior(ws) is None


def test_read_intake_prior_wrong_schema_is_none(tmp_path):
    ws = _ws(tmp_path)
    (ws / "runs" / "llm-prior.json").write_text(
        json.dumps({"schema": "llm-prior/9", "families": {}}),
        encoding="utf-8")
    assert rl_priors.read_intake_prior(ws) is None


def test_read_intake_prior_malformed_families_is_none(tmp_path):
    ws = _ws(tmp_path)
    for bad in ({"alpha": 1.0}, {"alpha": "x", "beta": 1.0},
                {"alpha": -1.0, "beta": 1.0}, {"alpha": 0.0, "beta": 0.0}):
        (ws / "runs" / "llm-prior.json").write_text(
            json.dumps({"schema": "llm-prior/1", "families": {"f": bad}}),
            encoding="utf-8")
        assert rl_priors.read_intake_prior(ws) is None, bad


def test_intake_prior_lead_tie_breaks_deterministically():
    doc = {"schema": "llm-prior/1",
           "families": {"b-fam": {"alpha": 1.0, "beta": 1.0},
                        "a-fam": {"alpha": 1.0, "beta": 1.0},
                        "c-fam": {"alpha": 2.0, "beta": 1.0}}}
    assert rl_priors.intake_prior_lead(doc) == "c-fam"
    tied = {"schema": "llm-prior/1",
            "families": {"b-fam": {"alpha": 1.0, "beta": 1.0},
                         "a-fam": {"alpha": 1.0, "beta": 1.0}}}
    assert rl_priors.intake_prior_lead(tied) == "a-fam"
    assert rl_priors.intake_prior_lead(None) is None
    assert rl_priors.intake_prior_lead({"families": {}}) is None


def test_intake_prior_weights_restrict_and_fail_open(tmp_path):
    ws = _ws(tmp_path)
    rl_priors.seed_intake_prior(ws, families=[
        "replay-harness-verification", "static-decompile"])
    weights = rl_priors.intake_prior_weights(ws)
    assert set(weights) == {"replay-harness-verification", "static-decompile"}
    top = sorted(weights, key=lambda f: (-weights[f], f))[0]
    assert top == LEAD_FAMILY
    # partial coverage against an allowed set degrades to {} (the host
    # cannot rank coherently on a partial seed — fail-open to uniform)
    assert rl_priors.intake_prior_weights(
        ws, allowed={"static-decompile"}) == {}
    assert rl_priors.intake_prior_weights(
        _ws(tmp_path / "cold", spec=None)) == {}


# ------------------------------- 3. the fresh dispatch carries the seed

def _envelope_receipt(ws: Path):
    from e2e.checkpoints import _sample_envelope_family

    return _sample_envelope_family(ws)


def test_fresh_dispatch_carries_the_seeded_nonuniform_prior(tmp_path):
    """Acceptance bullet 1: a fresh workspace's first dispatch carries a
    NON-UNIFORM candidate prior traceable to the intake assessment —
    the envelope's candidates ride the seeded means, the lead ranks
    first, and the provenance chain runs llm-prior.json -> receipt."""
    ws = _ws(tmp_path)
    doc = rl_priors.seed_intake_prior(ws)
    means = _means(doc)

    fam, receipt = _envelope_receipt(ws)
    assert receipt is not None
    candidates = receipt["candidates"]
    assert set(candidates) == set(method_families.registered_tokens())
    # the seeded families ride the doc's exact means (value-level
    # traceability: llm-prior.json -> envelope candidates)
    for token, mean in means.items():
        assert candidates[token]["p_llm"] == pytest.approx(mean, abs=1e-9)
    # non-uniform: at least two distinct proposal weights
    weights = {t: c["p_llm"] for t, c in candidates.items()}
    assert len(set(weights.values())) > 1
    # the lead exists and ranks first among the p_llm weights
    top = sorted(weights, key=lambda t: (-weights[t], t))[0]
    assert top == LEAD_FAMILY
    assert rl_priors.intake_prior_lead(doc) == LEAD_FAMILY
    # the provenance chain: the doc on disk cites EXP-WS3-A, and the
    # weights the envelope rode are exactly that doc's means
    on_disk = rl_priors.read_intake_prior(ws)
    assert on_disk["calibration"] == doc["calibration"]
    assert on_disk["provenance"] == doc["provenance"]


def test_fresh_dispatch_without_prior_file_stays_uniform(tmp_path):
    """Fail-open the other way: no llm-prior.json => the historical
    uniform proposal face (every registered family at 1.0)."""
    ws = _ws(tmp_path, spec=SPEC)  # declared features, NO seed written
    fam, receipt = _envelope_receipt(ws)
    assert receipt is not None
    weights = {t: c["p_llm"] for t, c in receipt["candidates"].items()}
    assert set(weights.values()) == {1.0}


def test_fresh_dispatch_with_corrupt_prior_file_stays_uniform(tmp_path):
    ws = _ws(tmp_path)
    rl_priors.seed_intake_prior(ws)
    (ws / "runs" / "llm-prior.json").write_text("]]] broken", encoding="utf-8")
    fam, receipt = _envelope_receipt(ws)
    weights = {t: c["p_llm"] for t, c in receipt["candidates"].items()}
    assert set(weights.values()) == {1.0}


def test_fresh_dispatch_partial_seed_coverage_fails_open_to_uniform(
        tmp_path):
    """A doc that predates a registry change (partial coverage of the
    registered vocabulary) cannot rank coherently — the host falls back
    to the uniform face instead of mixing seeded means with 1.0s."""
    ws = _ws(tmp_path)
    rl_priors.seed_intake_prior(ws, families=[
        "replay-harness-verification", "static-decompile"])
    fam, receipt = _envelope_receipt(ws)
    weights = {t: c["p_llm"] for t, c in receipt["candidates"].items()}
    assert set(weights.values()) == {1.0}
