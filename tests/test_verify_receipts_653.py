# -*- coding: utf-8 -*-
"""tests/test_verify_receipts_653.py — the verify-stage re-run receipt
contract (issue 653, the 5-F1 hybrid ruling).

Finding 5-F1: the V-dispatch hands the verifier the maker's own fact
files, so a maker who plants a wrong reproduce script with a matching
wrong recorded output gets its error faithfully re-derived and
confirmed — nothing distinguished "re-ran it myself" from "trusted the
maker's recorded output". The hybrid ruling lands two mechanical faces:

  1. the V-dispatch mandates a re-run receipt block (`re-run:` / `rc:` /
     `out-sha:`) per relied-upon command and states the distrust rule;
  2. the landing gate refuses a `verdict: verified` note without at
     least one well-formed receipt: ONE warn, the verdict settles as
     absent (0.0 credit), prediction settlement is skipped, and the
     promotion attempt is replaced by a recorded refusal. `refuted` is
     exempt (it banks no success credit).

Also pinned: the engine-built V prompt is sibling-free (exactly the
target claim id — the priming channel is shut at the engine; the
orchestrator-narration channel is the named residual).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from e2e import checkpoints, llm_faces, model  # noqa: E402
from rlvr import prediction_ledger as pl  # noqa: E402
from test_e2e_runner import (  # noqa: E402
    ANCHORS, DERIVE_PY, FakeClock, ScriptedRunner, TASK_YAML)

SHA = "a" * 64


@pytest.fixture()
def stub_repo(tmp_path):
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/smoke/py-derive-v1"
    (task / "target").mkdir(parents=True)
    (task / "target/derive.py").write_text(DERIVE_PY, encoding="utf-8")
    (task / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (repo / "scripts").mkdir()
    return repo


@pytest.fixture()
def ctx(stub_repo, tmp_path):
    ws = tmp_path / "ws"
    ev_dir = tmp_path / "ev"
    ws.mkdir()
    (ws / "runs").mkdir()
    state = model.RunState(
        run_id="a1", unit="py-derive-v1", family="smoke",
        repo=str(stub_repo),
        task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
        ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=10_000,
        llm_mode="auto", started_ts="t", started_monotonic=0.0,
        anchors=dict(ANCHORS))
    runner = ScriptedRunner()
    return checkpoints.RunContext(
        state=state, runner=runner,
        face=llm_faces.face_for("auto", runner, ev_dir),
        clock=FakeClock(), sleep_fn=lambda _s: None)


def _note(receipt: bool = True, verdict: str = "verified") -> str:
    parts = [f"---\nclaim: C-005\nverdict: {verdict}\n---\n\n"]
    if receipt:
        parts += ["re-run: uv run python target/derive.py\n",
                  "rc: 0\n",
                  f"out-sha: {SHA}\n\n"]
    parts += ["replay face, byte-exact against the pin\n"]
    return "".join(parts)


def _plant_note(ctx, text: str, claim: str = "C-005") -> None:
    (Path(ctx.ws) / "runs" / f"verification-{claim}.md").write_text(
        text, encoding="utf-8")


def _register_pending(ws, claim: str = "C-005") -> None:
    row = pl.register(ws, claim, "the function resolves under the patch",
                      "byte-exact", actor="worker-x")
    assert row is not None


def _rows(ws: Path) -> list[dict]:
    p = Path(ws) / "runs" / "transitions.jsonl"
    if not p.is_file():
        return []
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------- the landing gate ----

def test_verified_without_receipt_is_refused(ctx, monkeypatch) -> None:
    _plant_note(ctx, _note(receipt=False))
    _register_pending(ctx.ws)
    calls: list[list] = []
    monkeypatch.setattr(checkpoints, "promote_claims",
                        lambda *a, **kw: calls.append(list(a)) or {})
    detail: dict = {"acts": []}
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), detail)
    rows = _rows(ctx.ws)
    assert rows, "the transition still lands (honest telemetry)"
    assert rows[-1]["r_settle"] == 0.0, "the refused note banks nothing"
    assert calls == [], "promotion is never attempted on a refused note"
    promotions = detail.get("promotions") or []
    assert promotions and promotions[0].get("violations"), \
        "the refusal names the receipt gate"
    statuses = [r.get("status") for r in pl.read_ledger(ctx.ws)]
    assert statuses == [pl.STATUS_PENDING], \
        "a refused note never settles predictions"


def test_verified_with_receipt_settles_and_promotes(ctx, monkeypatch) -> None:
    _plant_note(ctx, _note(receipt=True))
    _register_pending(ctx.ws)
    calls: list[list] = []
    monkeypatch.setattr(checkpoints, "promote_claims",
                        lambda *a, **kw: calls.append(list(a)) or {"ok": True})
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    rows = _rows(ctx.ws)
    assert rows[-1]["r_settle"] == 1.0
    assert len(calls) == 1, "a receipt-carrying verification promotes"
    settled = [r for r in pl.read_ledger(ctx.ws)
               if r.get("status") == pl.STATUS_CONFIRMED]
    assert settled, "the attributed prediction settles on honest evidence"


def test_malformed_receipt_counts_as_absent(ctx, monkeypatch) -> None:
    bad = _note(receipt=True).replace("rc: 0", "rc: zero")
    _plant_note(ctx, bad)
    calls: list[list] = []
    monkeypatch.setattr(checkpoints, "promote_claims",
                        lambda *a, **kw: calls.append(list(a)) or {})
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    assert _rows(ctx.ws)[-1]["r_settle"] == 0.0
    assert calls == []


def test_short_out_sha_counts_as_absent(ctx, monkeypatch) -> None:
    bad = _note(receipt=True).replace("a" * 64, "a" * 32)
    _plant_note(ctx, bad)
    calls: list[list] = []
    monkeypatch.setattr(checkpoints, "promote_claims",
                        lambda *a, **kw: calls.append(list(a)) or {})
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    assert _rows(ctx.ws)[-1]["r_settle"] == 0.0
    assert calls == []


def test_refuted_verdict_is_exempt_from_receipts(ctx, monkeypatch) -> None:
    _plant_note(ctx, _note(receipt=False, verdict="refuted"))
    calls: list[list] = []
    monkeypatch.setattr(checkpoints, "promote_claims",
                        lambda *a, **kw: calls.append(list(a)) or {})
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    row = _rows(ctx.ws)[-1]
    assert row["r_settle"] == 0.0     # refutation banks no success credit
    assert len(calls) == 1, "the receipt gate does not tax refutations"


# --------------------------------------------- the dispatch contract ----

def test_v_prompt_carries_the_re_run_contract() -> None:
    text = checkpoints._verifier_dispatch_text(
        "C-005", "stamp-token", 1799, "/tmp/ws/facts")
    assert "re-run:" in text and "rc:" in text and "out-sha:" in text
    assert "never copy" in text.lower()
    assert "recorded output" in text.lower()
    assert "verify-stamp: stamp-token" in text
    assert "ACT BUDGET" in text


def test_v_prompt_is_sibling_free() -> None:
    text = checkpoints._verifier_dispatch_text(
        "C-005", "stamp-token", 1799, "/tmp/ws/facts")
    ids = set()
    import re
    for m in re.finditer(r"\bC-\d+\b", text):
        ids.add(m.group(0))
    assert ids == {"C-005"}, f"the V prompt must name only its claim, got {ids}"


def test_v_prompt_pins_receipts_to_verified() -> None:
    text = checkpoints._verifier_dispatch_text(
        "C-005", "stamp-token", 1799, "/tmp/ws/facts")
    assert "verified" in text and "receipt" in text.lower()
