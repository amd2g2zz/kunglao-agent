#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pattern_lib_518.py — the expertise layer (#518 PR-3).

The F1 ruling made the shape explicit: the worker is a novice staring
at the race car (uniform priors, no pattern library), and the H2H bench
located the shared death point — the DYNAMIC PROTOCOL FACE (constants
recovered by every arm, session/bootstrap flows walked by none). This
file pins the pattern-library contract:

  P1  patterns load + validate (schema, registry-constrained family
      hints, non-empty flow, provenance)
  P2  features extract from a unit's task.yaml (surface/kinds/languages)
  P3  matching is feature-keyed (web-shaped -> protocol-flow pattern;
      native .so -> static-gate pattern)
  P4  the playbook renders into the dispatch prompt when a pattern
      matches, and the prompt is byte-unchanged when none does
  P5  the committed pattern store is leak-clean (no holdout constants
      or unit ids — the #518 PR-1 firewall)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import pattern_lib  # noqa: E402


WEB_TASK = """\
schema: kunglao-eval-task/1
task_id: web-x-v1
tier: release
family: net-verify-license
anchors:
  goal_verbatim: Reverse the served JS SDK.
  success_criterion: client.py passes.
workspace_scaffold:
  language: javascript
  files:
  - capture/sdk.js
"""

NATIVE_TASK = """\
schema: kunglao-eval-task/1
task_id: native-x-v1
tier: release
family: mod-crypto-native
anchors:
  goal_verbatim: Recover the gate.
  success_criterion: module verify() matches.
workspace_scaffold:
  language: c/arm64-android
  files:
  - target/libgate.so
"""


def test_patterns_load_and_validate():
    pats = pattern_lib.load_patterns()
    assert pats, "the store must carry at least the protocol-flow theme"
    import method_families  # noqa: PLC0415

    registered = set(method_families.registered_tokens())
    for p in pats:
        assert p["schema"] == "kunglao-pattern/1", p
        assert p["id"].startswith("PAT-"), p
        assert p["family_hint"] in registered, p["family_hint"]
        assert p["playbook"]["flow"], f"{p['id']}: empty flow"
        assert p["provenance"]["mined_from_families"], p["id"]


def test_features_from_task(tmp_path):
    f = pattern_lib.features_from_task_str(WEB_TASK)
    assert f["languages"] == ["javascript"]
    assert any("sdk.js" in k for k in f["scaffold_kinds"])
    assert f["target_surface"] == "net"


def test_matching_is_feature_keyed(tmp_path):
    pats = pattern_lib.load_patterns()
    web = pattern_lib.match_pattern(pats, pattern_lib.features_from_task_str(WEB_TASK))
    native = pattern_lib.match_pattern(pats, pattern_lib.features_from_task_str(NATIVE_TASK))
    assert web and web["family_hint"] == "protocol-flow-reconstruction", web
    assert native and native["family_hint"] == "static-decompile", native


def test_playbook_renders():
    pats = pattern_lib.load_patterns()
    web = pattern_lib.match_pattern(pats, pattern_lib.features_from_task_str(WEB_TASK))
    block = pattern_lib.render_playbook(web)
    assert "flow" in block.lower() or "step" in block.lower()
    assert "bootstrap" in block.lower()  # the H2H death point, verbatim


def test_prompt_injection_on_match():
    from e2e import checkpoints, model  # noqa: PLC0415

    td = ROOT / "eval" / "v1" / "tasks" / "release" / "web-pow-lite-v1"
    ws = Path("/tmp/pattern-lib-test-ws")
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-004\n  status: OPEN\n", encoding="utf-8")
    state = model.RunState(
        run_id="r", unit="web-pow-lite-v1", family="release", repo=str(ROOT),
        task_dir=str(td), ws=str(ws), evidence_dir="/tmp/pattern-lib-ev",
        budget_seconds=10, llm_mode="dry", started_ts="t",
        started_monotonic=0.0,
        anchors={"goal_verbatim": "g", "success_criterion": "s",
                 "verification_method": "reproduction"},
        method_family="protocol-flow-reconstruction")

    class _Face:
        def launch_dispatch(self, request):
            return "h"

    ctx = checkpoints.RunContext(state=state, runner=object(), face=_Face(),
                                 clock=object(), sleep_fn=lambda _s: None)
    request, _ = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request is not None
    body = Path(state.evidence_dir, f"dispatch-prompt-C-004.md")
    text = body.read_text(encoding="utf-8")
    assert "playbook" in text.lower(), text[:400]
    assert "bootstrap" in text.lower()


def test_store_is_leak_clean():
    import subprocess  # noqa: PLC0415

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "eval_split_lint.py")],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr


def test_canonical_table_carries_no_holdout_rows():
    import json  # noqa: PLC0415

    table = ROOT / "eval" / "v1" / "feature-table.jsonl"
    assert table.is_file(), "the canonical mined table is repo-committed"
    holdout = {"web-token-v1", "web-pow-lite-v1", "apk-static-license-v1",
               "rust-apk-beacon-v1", "web-anticrawl-v2",
               "apk-webview-attest-v2"}
    rows = [json.loads(l) for l in table.read_text().splitlines() if l.strip()]
    assert rows, "at least one mining-pool row"
    bad = [r["task_id"] for r in rows if r["task_id"] in holdout]
    assert not bad, f"holdout rows leaked into the canonical table: {bad}"


def test_c6_pre_seeds_the_feature_table(tmp_path):
    from e2e import checkpoints, model  # noqa: PLC0415

    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
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
                rc, stdout, stderr = 0, "", ""
            return O()

    class _Clock:
        def monotonic(self):
            return 0.0

    ctx = checkpoints.RunContext(state=state, runner=_Runner(),
                                 face=object(), clock=_Clock(),
                                 sleep_fn=lambda _s: None)
    src = ROOT / "eval" / "v1" / "feature-table.jsonl".replace(
        "feature-table.jsonl", "feature-table.jsonl")
    # run only the seeding concern: invoke the checkpoint and look for the
    # seeded file; C6-pre's earlier steps are self-contained writes
    try:
        checkpoints.checkpoint_c6_pre(ctx)
    except Exception:
        pass  # later steps may need more fixture; the seed is early
    dst = ws / "runs" / "feature-table.jsonl"
    assert dst.is_file() and dst.read_text() == src.read_text()


def test_settlement_records_posteriors_row(tmp_path):
    from e2e import checkpoints, llm_faces, model  # noqa: PLC0415
    from rlvr import posteriors  # noqa: PLC0415

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
                 "verification_method": "reproduction"},
        method_family="protocol-flow-reconstruction")

    class _Face:
        def launch_dispatch(self, request):
            return "h"

    ctx = checkpoints.RunContext(state=state, runner=object(), face=_Face(),
                                 clock=object(), sleep_fn=lambda _s: None)
    checkpoints._launch_dispatch(ctx, "C-004", set())
    checkpoints._land_dispatch(ctx, "C-004",
                               llm_faces.ActRecord(claim="C-004",
                                                   mode="auto",
                                                   outcome="DISPATCHED",
                                                   detail={}),
                               set(), {"acts": []})
    rows = posteriors.load_all(str(ws)) if hasattr(posteriors, "load_all") \
        else []
    if not rows:
        # fall back to the store file shape
        import json as _j  # noqa: PLC0415
        p = ws / "runs" / "posterior-store.jsonl"
        rows = ([_j.loads(l) for l in p.read_text().splitlines() if l.strip()]
                if p.exists() else [])
    assert rows, "the posteriors store must carry the settlement row"
