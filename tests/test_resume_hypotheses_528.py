# -*- coding: utf-8 -*-
"""tests/test_resume_hypotheses_528.py — restart re-hydration through the
resume brief (#528 work item 2).

The cold-start 9th file is runs/digest.md (cold-start-contract.md). The
fresh session's ENTRY POINT after a crash is the kunglao_resume brief
(#466) — read-only face. The brief therefore surfaces:
  - a runs/digest.md data-age row (is the re-hydration artifact present?)
  - the OPEN hypothesis pointers (what undecided questions re-hydrate)
Fail-open: no hypotheses/ -> empty pointers, brief unchanged in shape.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import kunglao_resume as kr  # noqa: E402


def _armed_ws(tmp_path: Path, with_ledger: bool = True) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: family\n", encoding="utf-8")
    (ws / "facts").mkdir(exist_ok=True)
    if with_ledger:
        (ws / ".convergence_ledger.jsonl").write_text(
            json.dumps({"ts": "2026-08-20T00:00:00Z", "decision": "DISPATCH",
                        "open_count": 1, "open_ids": ["C-1"],
                        "partial_count": 0, "active_workers": 0,
                        "blockers": [], "facts_total": 0}) + "\n",
            encoding="utf-8")
    # heartbeat alive so rc stays RESUMABLE (not the assertion target, but
    # keeps the brief on the happy path)
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps({
        "last_tick_ts": "2026-08-20T00:05:00Z",
        "activity_ts": "2026-08-20T00:05:00Z"}), encoding="utf-8")
    (ws / ".hook_state.json").write_text(json.dumps({
        "expires_at": "2099-01-01T00:00:00Z", "active_hooks": []}),
        encoding="utf-8")
    return ws


def _seed_hyps(ws: Path) -> None:
    d = ws / "hypotheses"
    d.mkdir(parents=True, exist_ok=True)
    (d / "H-1.md").write_text(
        "---\nid: H-1\nclaim_id: C-1\ncompetitor_group: cipher\n"
        "candidates: [AES, ChaCha20]\nstatus: open\nschema_rev: 1\n"
        "---\nmotivation\n", encoding="utf-8")
    (d / "H-2.md").write_text(
        "---\nid: H-2\nclaim_id: C-2\ncompetitor_group: net\n"
        "candidates: [ws]\nstatus: refuted\nrefuting_fact_id: F-1\n"
        "schema_rev: 1\n---\ndead\n", encoding="utf-8")


# ---------- data-age row ----------

def test_brief_carries_digest_row(tmp_path: Path) -> None:
    ws = _armed_ws(tmp_path)
    (ws / "runs" / "digest.md").write_text("## head\n", encoding="utf-8")
    brief = kr.build_brief(ws)
    row = next((r for r in brief["data_age"]
                if r["source"] == "runs/digest.md"), None)
    assert row is not None, "resume brief must surface runs/digest.md (#528)"
    assert row["exists"] is True


def test_brief_flags_missing_digest(tmp_path: Path) -> None:
    ws = _armed_ws(tmp_path)
    brief = kr.build_brief(ws)
    row = next(r for r in brief["data_age"] if r["source"] == "runs/digest.md")
    assert row["exists"] is False
    assert row["flag"] == "missing"


# ---------- open-hypothesis pointers ----------

def test_brief_lists_open_hypothesis_pointers(tmp_path: Path) -> None:
    ws = _armed_ws(tmp_path)
    _seed_hyps(ws)
    brief = kr.build_brief(ws)
    hyps = brief["hypotheses"]
    assert hyps["open_count"] == 1  # H-2 is refuted — not re-hydrated
    assert hyps["pointers"] == [{"claim_id": "C-1", "hyp_id": "H-1"}]


def test_brief_text_renders_hypotheses(tmp_path: Path) -> None:
    ws = _armed_ws(tmp_path)
    _seed_hyps(ws)
    text = kr.render_text(kr.build_brief(ws))
    assert "H-1" in text


def test_brief_text_omits_hypothesis_body(tmp_path: Path) -> None:
    """Pointers only in the brief — the motivation body stays in the
    digest/hypotheses layer (read-on-demand)."""
    ws = _armed_ws(tmp_path)
    _seed_hyps(ws)
    text = kr.render_text(kr.build_brief(ws))
    assert "motivation" not in text


def test_brief_without_hypotheses_dir(tmp_path: Path) -> None:
    """Pre-#528 workspace: no hypotheses/ -> empty pointers, no crash."""
    ws = _armed_ws(tmp_path)
    brief = kr.build_brief(ws)
    assert brief["hypotheses"] == {"open_count": 0, "pointers": []}


def test_brief_corrupt_hypotheses_degrades(tmp_path: Path) -> None:
    """A malformed hypotheses file must not break the brief (fail-open)."""
    ws = _armed_ws(tmp_path)
    d = ws / "hypotheses"
    d.mkdir()
    (d / "garbage.md").write_text("no frontmatter\n", encoding="utf-8")
    brief = kr.build_brief(ws)
    assert brief["hypotheses"]["open_count"] == 0


# ---------- read-only still holds ----------

def test_resume_still_writes_nothing_with_hypotheses(tmp_path: Path) -> None:
    """Adding the hypothesis surface must not break the #466 read-only
    contract (test_resume_is_read_only pins the pre-#528 case)."""
    ws = _armed_ws(tmp_path)
    _seed_hyps(ws)
    before = sorted(str(p.relative_to(ws)) for p in ws.rglob("*"))
    kr.main([str(ws), "--json"])
    after = sorted(str(p.relative_to(ws)) for p in ws.rglob("*"))
    assert before == after
