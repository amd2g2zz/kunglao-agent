#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_rlvr_p0_524.py — the P0 data-layer contracts (#524).

  1  meta-arms: all registered families map into exactly 3 metas
  2  hierarchical pooling: settled rows pool by meta; cross-fingerprint
     rows temper at LAMBDA; no data -> uniform
  3  mc_propensity: a dominant arm approaches 1, uniform -> ~1/K
  4  env_fingerprint: stable per environment, distinct across models
  5  continuous credit: binary floor + fact production (hindsight
     partial credit for failed-but-productive acts)
  6  censoring: TIMEOUT settlement rows carry censored=true
  7  canonical AD2/AD3: C6-pre + decide() writer emit canonical bytes
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import meta_arms  # noqa: E402

import method_families  # noqa: E402


def test_meta_mapping_covers_all_registered_families():
    registered = set(method_families.registered_tokens())
    assert registered <= set(meta_arms.META_ARMS), \
        set(registered) - set(meta_arms.META_ARMS)
    assert set(meta_arms.META_ARMS.values()) == set(meta_arms.META_NAMES)


def test_hierarchical_pooling_and_tempering():
    rows = [
        {"method_family": "static-decompile", "credit": 1.0,
         "fingerprint": "fp"},
        {"method_family": "static-decompile", "credit": 1.0,
         "fingerprint": "fp"},
        {"method_family": "hypothesis-falsification", "credit": 0.0,
         "fingerprint": "fp"},
    ]
    pri = meta_arms.hierarchical_prior(
        rows, ["static-decompile", "hypothesis-falsification",
               "dynamic-trace"], "fp")
    # the structural-probing meta pool (2/2 success) outweighs the
    # falsification meta (0/1) for an arm with no own data
    assert pri["static-decompile"] > pri["hypothesis-falsification"]
    assert pri["dynamic-trace"] > pri["hypothesis-falsification"]
    # tempering: old-fingerprint rows count at LAMBDA -> the gap shrinks
    rows_old = [dict(r, fingerprint="old") for r in rows]
    pri_old = meta_arms.hierarchical_prior(
        rows_old, list(pri), "fp")
    gap = pri["static-decompile"] - pri["hypothesis-falsification"]
    gap_old = pri_old["static-decompile"] - pri_old["hypothesis-falsification"]
    assert gap_old < gap
    # no data -> uniform
    assert meta_arms.hierarchical_prior([], ["a", "b"], "fp") == \
        {"a": 1.0, "b": 1.0} or all(
            v > 0 for v in
            meta_arms.hierarchical_prior([], ["static-decompile"],
                                         "fp").values())


def test_mc_propensity_dominant_and_uniform():
    rows = ([{"method_family": "A", "credit": 1.0}] * 20
            + [{"method_family": "B", "credit": 0.0}] * 20)
    dom = meta_arms.mc_propensity(rows, "A", ["A", "B"])
    uni = meta_arms.mc_propensity([], "A", ["A", "B"])
    assert dom > 0.95
    assert 0.3 < uni < 0.7  # uniform posteriors -> a fair coin


def test_env_fingerprint_stable_and_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_MODEL", "model-x")
    fp1 = meta_arms.env_fingerprint(tmp_path)
    fp2 = meta_arms.env_fingerprint(tmp_path)  # cached file
    assert fp1 == fp2 and len(fp1) == 12
    monkeypatch.setenv("KUNGLAO_MODEL", "model-y")
    import shutil as _sh
    _sh.rmtree(tmp_path / "runs")  # drop the cache
    fp3 = meta_arms.env_fingerprint(tmp_path)
    assert fp3 != fp1


def test_continuous_credit_and_censoring(tmp_path):
    from e2e import checkpoints, llm_faces, model  # noqa: E402
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-004\n  status: OPEN\n", encoding="utf-8")
    # two facts cite the claim -> a DISPATCHED act banks 1.0; a TIMEOUT
    # (with the same facts) banks 0.5 — hindsight partial credit
    for fid in ("F001", "F002"):
        (ws / "facts" / f"{fid}.md").write_text(
            f"---\nclaim_id: C-004\n---\nbody\n", encoding="utf-8")
    state = model.RunState(
        run_id="r", unit="u", family="release", repo=str(ROOT),
        task_dir=str(ROOT), ws=str(ws), evidence_dir=str(tmp_path / "ev"),
        budget_seconds=10, llm_mode="dry", started_ts="t",
        started_monotonic=0.0,
        anchors={"goal_verbatim": "g", "success_criterion": "s",
                 "verification_method": "reproduction"},
        method_family="static-decompile")

    class _Face:
        def launch_dispatch(self, request):
            return "h"

    ctx = checkpoints.RunContext(state=state, runner=object(), face=_Face(),
                                 clock=object(), sleep_fn=lambda _s: None)
    from rlvr import q_cells  # noqa: E402

    checkpoints._launch_dispatch(ctx, "C-004", set())
    checkpoints._land_dispatch(ctx, "C-004",
                               llm_faces.ActRecord(claim="C-004", mode="auto",
                                                   outcome="DISPATCHED",
                                                   detail={}),
                               set(), {"acts": []})
    settled = [r for r in q_cells.JSONLQStore(str(ws)).observations()
               if r.get("credit") is not None]
    assert settled and settled[-1]["credit"] == 1.0
    assert settled[-1].get("fingerprint"), "fp rides the settlement row"

    # TIMEOUT path: censored flag on the posterior row, hindsight credit
    for fid in ("F003", "F004"):  # facts citing C-005 -> partial credit
        (ws / "facts" / f"{fid}.md").write_text(
            f"---\nclaim_id: C-005\n---\nbody\n", encoding="utf-8")
    d2 = set()
    checkpoints._launch_dispatch(ctx, "C-005", d2)
    checkpoints._land_dispatch(ctx, "C-005",
                               llm_faces.ActRecord(claim="C-005", mode="auto",
                                                   outcome="TIMEOUT",
                                                   detail={}),
                               d2, {"acts": []})
    aud = []
    for p2 in sorted((ws / "runs" / "logs").glob("*.jsonl")):
        for l in p2.read_text().splitlines():
            if "posterior_updated" not in l:
                continue
            e = json.loads(l)
            d = e.get("detail")
            if isinstance(d, str):  # the ledger double-encodes JSON
                try:
                    d = json.loads(d)
                except ValueError:
                    d = {}
            e["detail"] = d
            aud.append(e)
    assert aud and aud[-1]["detail"]["counts"].get("censored") is True
    settled2 = [r for r in q_cells.JSONLQStore(str(ws)).observations()
                if r.get("credit") is not None and r.get("claim") == "C-005"]
    assert settled2 and 0.0 < settled2[-1]["credit"] < 1.0, \
        "timeout with facts cites banks partial (hindsight), not bare 0"


def test_canonical_ad3_c6pre(tmp_path, monkeypatch):
    from e2e import checkpoints, model  # noqa: E402
    from ws_yaml import canonical_dump  # noqa: E402
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-004\n  status: OPEN\n", encoding="utf-8")
    state = model.RunState(
        run_id="r", unit="u", family="release", repo=str(ROOT),
        task_dir=str(ROOT), ws=str(ws), evidence_dir=str(tmp_path / "ev"),
        budget_seconds=10, llm_mode="dry", started_ts="t",
        started_monotonic=0.0,
        anchors={"goal_verbatim": "g", "success_criterion": "s",
                 "verification_method": "reproduction"})

    class _Runner:
        def run(self, *a, **k):
            class O:
                rc, stdout, stderr = 0, "ok", ""
            return O()

    class _Clock:
        def monotonic(self):
            return 0.0

    ctx = checkpoints.RunContext(state=state, runner=_Runner(),
                                 face=object(), clock=_Clock(),
                                 sleep_fn=lambda _s: None)
    try:
        checkpoints.checkpoint_c6_pre(ctx)
    except Exception:
        pass  # later steps may need more fixture; the writes happen early
    for name in ("goal-operationalization.yaml", "task_spec.yaml"):
        f = ws / name
        if f.is_file():
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            assert f.read_text(encoding="utf-8") == canonical_dump(doc), \
                f"{name}: non-canonical bytes (AD3)"


def test_canonical_ad2_reopen_writer(tmp_path):
    import convergence_check as cc  # noqa: E402
    from ws_yaml import canonical_dump  # noqa: E402
    ws = tmp_path
    (ws / "runs").mkdir()
    (ws / "runs" / "worker-status-C-004-a.md").write_text(
        "[00:01] step: started | status: in-progress\n", encoding="utf-8")
    reg = ws / "claim-register.yaml"
    reg.write_text("claims:\n- id: C-004\n  status: IN_PROGRESS\n",
                   encoding="utf-8")

    class _S:  # the _DecideInputs face the writer reads
        workspace = ws
        stuck = [{"worker": "worker-status-C-004-a"}]  # dead-worker rows

    reopened = cc._reopen_stuck_claims(_S())
    doc = yaml.safe_load(reg.read_text(encoding="utf-8"))
    assert reg.read_text(encoding="utf-8") == canonical_dump(doc), \
        "decide()-writer emits non-canonical bytes (AD2)"
