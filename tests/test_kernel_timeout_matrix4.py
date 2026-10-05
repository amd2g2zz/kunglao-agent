# -*- coding: utf-8 -*-
"""matrix4 K1-wiring pins: the Luby restart schedule actually reaches
the subprocess timeout.

matrix4 field evidence (wt1/wpl, dev d177a391): every worker act hit
the FLAT 1800s face timeout (three timeouts per run) and the
idle-circuit-breaker ended both runs with PROVEN 3-4 + OPEN 1 — the
Luby helper shipped with zero production callers; the schedule never
reached the face. matrix2's own baseline says 28-36-minute acts are
normal, so the ladder must START at today's flat behavior and GROW on
retries (base default 1800): 1800/1800/3600/1800/1800/3600/7200...

The fast-discovery shape (base 300, doomed acts die in 5 minutes)
stays env-selectable pending Kaplan-Meier hazard data — the design
contract's intended feed (issue tracker lives in the PR, not code). Shipping it blind would kill healthy
1000s-class acts (matrix4 asl's C-005 ran 1012s to completion).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import checkpoints as cp       # noqa: E402
from e2e import llm_faces, model       # noqa: E402


def test_luby_base_defaults_to_flat_parity(monkeypatch):
    """Attempt 0 equals today's flat act timeout (1800) — the ladder
    grows from parity, never shrinks below it."""
    monkeypatch.delenv("KUNGLAO_LUBY_BASE_S", raising=False)
    monkeypatch.delenv("KUNGLAO_E2E_ACT_TIMEOUT_S", raising=False)
    import importlib
    importlib.reload(cp)
    assert cp.LUBY_BASE_S == 1800, cp.LUBY_BASE_S
    assert cp._luby_timeout_s(0) == 1800
    assert cp._luby_timeout_s(2) == 3600


class _CapturingRunner:
    """Records the timeout kwarg the face hands to the subprocess."""

    def __init__(self):
        self.seen: list[int | None] = []

    def run(self, cmd, cwd=None, timeout=None, **_):
        self.seen.append(timeout)
        return model.CmdOutcome(0, "", "")

    def py_cmd(self, *a, **k):
        return list(a)


def test_face_honors_per_request_timeout(tmp_path):
    runner = _CapturingRunner()
    face = llm_faces.AutoLlmFace(runner, tmp_path)
    (tmp_path / "p.md").write_text("go", encoding="utf-8")
    req = model.DispatchRequest(
        claim="C-004", workspace=str(tmp_path),
        prompt_file=str(tmp_path / "p.md"), run_id="r", timeout_s=3600)
    face.run_dispatch(req)
    assert runner.seen and runner.seen[0] == 3600, runner.seen


def test_launch_dispatch_passes_the_ladder(tmp_path, monkeypatch):
    """The runner-side launch computes luby(attempt) per claim-key and
    rides it on the request; a re-dispatch after timeout climbs."""
    monkeypatch.setattr(cp, "LUBY_BASE_S", 1800)
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n  - id: C-004\n    status: OPEN\n", encoding="utf-8")

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.ws = tmp_path
    ctx.repo = ROOT          # real repo: the launch loads rlvr.q_cells
    ctx.attempts = {}
    ctx.state = model.RunState(
        run_id="r", unit="u", family="f", repo=str(tmp_path),
        task_dir=str(tmp_path), ws=str(tmp_path),
        evidence_dir=str(tmp_path), budget_seconds=9999,
        llm_mode="auto", started_ts="", started_monotonic=0.0,
        anchors={})
    ctx.face = llm_faces.AutoLlmFace(_CapturingRunner(), tmp_path)

    seen = []

    def _fake_launch(req, *a, **k):
        seen.append(req.timeout_s)
        return None

    monkeypatch.setattr(ctx.face, "launch_dispatch", _fake_launch)
    # two launches of the same claim: attempt 0 then attempt 1
    cp._launch_dispatch(ctx, "C-004", set())
    cp._launch_dispatch(ctx, "C-004", set())
    assert seen == [1800, 1800], seen
    # third launch climbs the ladder
    cp._launch_dispatch(ctx, "C-004", set())
    assert seen[-1] == 3600, seen
