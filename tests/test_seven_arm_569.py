# -*- coding: utf-8 -*-
"""tests/test_seven_arm_569.py — the seven-arm matrix pins (issue #569):
B2 same-cost multi-sampling + B3 harness-without-learning.

The five-arm WS5 matrix cannot say WHERE its value comes from. The two
added arms decompose it:

  B2  cc-multisample   bare CC sampled N times at the kunglao arms'
                       total budget — the "is it just more sampling?"
                       rebuttal arm (pass@k at equal cost);
  B3  kunglao-uniform  the full loop with the scheduler face frozen:
                       KUNGLAO_SCHEDULER=uniform flattens the envelope
                       sampler's prior to 1.0 everywhere and starves the
                       draw of every learned input (settled cells, warm
                       pools, feature tables, death verdicts), so the
                       selection is exchangeable-uniform over the
                       registered vocabulary. B4-B3 isolates the
                       LEARNING's value; B3-B0 isolates the
                       ARCHITECTURE's value.

Pins:

  1. UNIFORM SCHEDULER — the flat face: candidates all p_llm 1.0, the
     cell posterior stays the day-one Beta(1,1) even when a warm store
     and local dispatch rows would make it non-flat, no learned receipt
     block rides, the receipt carries scheduler "uniform", and the
     propensity is recorded as exactly 1/K (OPE needs it — an
     exchangeable draw's marginal action probability IS 1/K). The
     declared family still wins with pi = 1.0. Any other scheduler
     value leaves the learned face byte-identical.
  2. B2 REGISTRY — the sampling protocol validates (mode/samples/
     budget_each), refuses on loop arms and on any same-cost violation
     (N x budget_each must equal the matrix budget), and the launcher
     strips KUNGLAO_SCHEDULER from the ambient shell like every other
     ablation face.
  3. DRY-RUN B2 — a multi-sample arm expands to N child rows per unit,
     each capped at budget_each, sample run dirs s0..s{N-1}.
  4. READOUT — B2 cells aggregate pass@k over samples at summed (equal)
     cost, and the report renders the three decompositions
     (learning_value = B4-B3, architecture_value = B3-B0, sampling_check
     = B4 vs B2@equal-cost) with the paired/bootstrap honest-stats note;
     missing arms are named, never invented.

Pure Python + tmp_path fixtures — no sessions, no corpus, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import checkpoints, model  # noqa: E402
from rlvr import strategy_store  # noqa: E402
import method_families  # noqa: E402

FAM_WARM = "kdf-chain-reconstruction"   # store rows -> non-flat when live
FAM_COLD = "obfuscation-peeling"        # no store rows


# ---- shared helpers --------------------------------------------------------

def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-004\n  status: OPEN\n", encoding="utf-8")
    return ws


def _seed_warm_store(monkeypatch, tmp_path: Path, n: int = 4) -> Path:
    """A posterior store whose rows make FAM_WARM non-flat at read."""
    root = tmp_path / "posterior-store"
    root.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(root))
    for i in range(1, n + 1):
        strategy_store.append_row({
            "schema": strategy_store.STORE_SCHEMA,
            "ts": "2026-10-08T00:00:00Z",
            "workspace_id": "ws-donor",
            "arm_key": f"{FAM_WARM}|facts_snapshot|none|1",
            "method_family": FAM_WARM,
            "feature_key": "none",
            "fingerprint": "fp000011112222",
            "status": "TIMEOUT",
            "credit": 0.0,
            "censored": True,
            "facts_citing": 2,
            "propensity": 1.0,
            "phi_delta": None,
            "provenance": {"dispatch_id": f"C-{i:03d}"},
        })
    return root


def _seed_local_dispatch_rows(ws: Path, warm: int = 5, cold: int = 1) -> None:
    """Local q-cell dispatch rows (proposal-channel only, credit=None):
    an unbalanced count face so the live pooled prior is non-flat."""
    log = ws / "runs" / "q-cell-log.jsonl"
    rows = ([{"source": "dispatch", "method_family": FAM_WARM}
             for _ in range(warm)]
            + [{"source": "dispatch", "method_family": FAM_COLD}
               for _ in range(cold)])
    log.write_text("".join(json.dumps(r) + "\n" for r in rows),
                   encoding="utf-8")


def _ctx(ws: Path, declared: str):
    state = model.RunState(
        run_id="r", unit="u", family="release", repo=str(ROOT),
        task_dir=str(ROOT), ws=str(ws),
        evidence_dir=str(ws.parent / "ev"),
        budget_seconds=10, llm_mode="dry", started_ts="t",
        started_monotonic=0.0,
        anchors={"goal_verbatim": "g", "success_criterion": "s",
                 "verification_method": "reproduction"},
        method_family=declared)
    face = type("_Face", (), {"launch_dispatch": staticmethod(
        lambda request: "h")})()
    return checkpoints.RunContext(state=state, runner=object(), face=face,
                                  clock=object(), sleep_fn=lambda _s: None)


def _envelopes(ws: Path) -> list[dict]:
    out = []
    p = ws / "runs" / "logs" / "e2e-audit.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if "method_family_recorded" not in line:
            continue
        e = json.loads(line)
        d = e.get("detail")
        if isinstance(d, str):
            d = json.loads(d)
        out.append(d)
    return out


# ---- 1. the uniform scheduler face (B3) ------------------------------------

def test_uniform_scheduler_flattens_prior_and_posterior(
        tmp_path, monkeypatch):
    """The flat face under maximal learned pressure: a warm store AND an
    unbalanced local dispatch history, and the receipt still rides the
    day-one flat shape — every candidate p_llm 1.0, every posterior the
    wide Beta(1,1), no learned receipt block, the scheduler marker on."""
    ws = _ws(tmp_path)
    _seed_warm_store(monkeypatch, tmp_path)
    _seed_local_dispatch_rows(ws)
    monkeypatch.setenv("KUNGLAO_SCHEDULER", "uniform")
    family, receipt = checkpoints._sample_envelope_family(ws)
    assert family in method_families.registered_tokens()
    assert receipt["scheduler"] == "uniform"
    cands = receipt["candidates"]
    assert set(cands) == set(method_families.registered_tokens())
    k = len(cands)
    for cand in cands.values():
        assert cand["p_llm"] == 1.0, "the prior is flat: 1.0 everywhere"
        assert cand["alpha"] == 1.0 and cand["beta"] == 1.0, \
            "the draw stays at the day-one Beta(1,1) — no learned mass"
    assert "posterior_store" not in cands[FAM_WARM], \
        "the warm pool never reaches the uniform draw"
    assert "feature_prior" not in cands[FAM_WARM]
    assert "death" not in cands[FAM_WARM]
    assert k == len(method_families.registered_tokens())


def test_learned_face_is_nonflat_without_the_env(tmp_path, monkeypatch):
    """The contrast pin: the SAME workspace without the env shows the
    learned shape (non-flat pooled prior, warm anchor mass) — the flat
    receipt above is the scheduler's doing, not an accident of the
    fixture."""
    ws = _ws(tmp_path)
    _seed_warm_store(monkeypatch, tmp_path)
    _seed_local_dispatch_rows(ws)
    _fam, receipt = checkpoints._sample_envelope_family(ws)
    cands = receipt["candidates"]
    assert any(c["p_llm"] != 1.0 for c in cands.values()), \
        "the live prior is the pooled face, never the flat 1.0 dict"
    assert cands[FAM_WARM]["alpha"] + cands[FAM_WARM]["beta"] > 2.0, \
        "the warm store borrows anchor mass on the learned face"
    assert receipt.get("scheduler") != "uniform"


def test_any_other_scheduler_value_keeps_the_learned_face(
        tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    _seed_warm_store(monkeypatch, tmp_path)
    _seed_local_dispatch_rows(ws)
    monkeypatch.setenv("KUNGLAO_SCHEDULER", "dts")
    _fam, receipt = checkpoints._sample_envelope_family(ws)
    cands = receipt["candidates"]
    assert cands[FAM_WARM]["alpha"] + cands[FAM_WARM]["beta"] > 2.0
    assert receipt.get("scheduler") != "uniform"


def test_uniform_scheduler_records_the_uniform_propensity(
        tmp_path, monkeypatch):
    """End-to-end undeclared dispatch under the uniform face: the
    envelope records propensity 1/K — the exchangeable draw's marginal
    action probability, the OPE raw material."""
    ws = _ws(tmp_path)
    _seed_warm_store(monkeypatch, tmp_path)
    monkeypatch.setenv("KUNGLAO_SCHEDULER", "uniform")
    ctx = _ctx(ws, "")
    request, _handle = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request.method_family, "the uniform draw still picks a family"
    receipt = _envelopes(ws)[-1]["envelope"]
    k = len(receipt["candidates"])
    assert k == len(method_families.registered_tokens())
    assert receipt["scheduler"] == "uniform"
    assert receipt["propensity"] == round(1.0 / k, 4), \
        "uniform policy: pi = 1/K, recorded for OPE"
    assert not receipt.get("declared")


def test_declared_family_still_wins_under_the_uniform_scheduler(
        tmp_path, monkeypatch):
    """A declared proposal is the behavior policy itself — even under
    the uniform scheduler the declaration wins and pi = 1.0."""
    ws = _ws(tmp_path)
    _seed_warm_store(monkeypatch, tmp_path)
    monkeypatch.setenv("KUNGLAO_SCHEDULER", "uniform")
    ctx = _ctx(ws, FAM_COLD)
    request, _handle = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request.method_family == FAM_COLD
    receipt = _envelopes(ws)[-1]["envelope"]
    assert receipt["propensity"] == 1.0
    assert receipt.get("declared") is True
    assert FAM_COLD in (receipt["candidates"] or {})
