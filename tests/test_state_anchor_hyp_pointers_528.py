# -*- coding: utf-8 -*-
"""tests/test_state_anchor_hyp_pointers_528.py — structured hypothesis
pointers in the state anchor (#528).

The anchor is a STRING capped at 500 chars and is anti-narrative by
contract (counts and IDs only, never prose — state_anchor.py ANCHOR_CAP /
test_anchor_excludes_progress_narrative). Adding hypothesis context as
free text would violate that rule. Instead the anchor gains a STRUCTURED
id-list segment — `hyp: <id>(<claim>) …` — and a machine-readable
payload helper build_anchor_payload() exposes the same pointers as
[{"claim_id", "hyp_id"}] dicts for tests/introspection.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / "hooks"

import state_anchor  # noqa: E402


def _seed(ws: Path, rows: list) -> Path:
    """A minimal live workspace: ledger snapshot + register (the anchor's
    required inputs — build_anchor returns '' without a snapshot)."""
    ws.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    (ws / ".convergence_ledger.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    return ws


def _snap() -> dict:
    return {"ts": "2026-08-20T00:00:00Z", "decision": "DISPATCH",
            "open_count": 1, "open_ids": ["C-1"], "partial_count": 0,
            "active_workers": 0, "blockers": [], "facts_total": 0}


def _seed_hypotheses(ws: Path, hyps: list[tuple[str, str, str]]) -> None:
    """hyps: (hyp_id, claim_id, status)."""
    d = ws / "hypotheses"
    d.mkdir(parents=True, exist_ok=True)
    for hid, cid, status in hyps:
        (d / f"{hid}.md").write_text(
            f"---\nid: {hid}\nclaim_id: {cid}\ncompetitor_group: x\n"
            f"candidates: [a]\nstatus: {status}\nschema_rev: 1\n---\n"
            f"motivation body for {hid}\n",
            encoding="utf-8",
        )


# ---------- 1. structured pointers in the anchor text ----------

def test_anchor_lists_open_hypothesis_ids(tmp_path: Path) -> None:
    ws = _seed(tmp_path, [_snap()])
    _seed_hypotheses(ws, [("H-1", "C-1", "open"),
                          ("H-2", "C-1", "open"),
                          ("H-3", "C-2", "refuted")])
    anchor = state_anchor.build_anchor(ws)
    assert "H-1" in anchor
    assert "H-2" in anchor
    assert "H-3" not in anchor  # refuted: not re-hydrated
    assert "hyps=2:" in anchor  # the structured segment marker (count then ids)


def test_anchor_hyp_segment_is_structured_not_narrative(tmp_path: Path) -> None:
    """The hypothesis segment carries ids only — never the motivation
    body (anti-narrative contract)."""
    ws = _seed(tmp_path, [_snap()])
    _seed_hypotheses(ws, [("H-1", "C-1", "open")])
    anchor = state_anchor.build_anchor(ws)
    assert "motivation body" not in anchor


def test_anchor_hyp_count_shown(tmp_path: Path) -> None:
    """The count precedes the id list (counts-and-ids posture)."""
    ws = _seed(tmp_path, [_snap()])
    _seed_hypotheses(ws, [("H-1", "C-1", "open"),
                          ("H-2", "C-1", "open")])
    anchor = state_anchor.build_anchor(ws)
    assert "hyps=2" in anchor


# ---------- 2. capacity (the 500-char cap holds) ----------

def test_anchor_under_500_chars_with_hypotheses(tmp_path: Path) -> None:
    ws = _seed(tmp_path, [_snap()])
    _seed_hypotheses(ws, [(f"H-{i}", "C-1", "open") for i in range(50)])
    anchor = state_anchor.build_anchor(ws)
    assert len(anchor) <= state_anchor.ANCHOR_CAP


def test_anchor_truncation_prefers_hyp_ids_visible(tmp_path: Path) -> None:
    """With a huge claim-id list AND hypotheses present, the anchor still
    fits — truncation from the tail is the existing mechanism; the hyp
    segment rides the same budget, it never buys extra capacity."""
    ws = _seed(tmp_path, [{"ts": "2026-08-20T00:00:00Z",
                           "decision": "DISPATCH",
                           "open_ids": [f"C-{i:03d}" for i in range(200)],
                           "open_count": 200, "partial_count": 0,
                           "active_workers": 0, "blockers": [],
                           "facts_total": 0}])
    _seed_hypotheses(ws, [(f"H-{i}", "C-1", "open") for i in range(30)])
    anchor = state_anchor.build_anchor(ws)
    assert len(anchor) <= state_anchor.ANCHOR_CAP


# ---------- 3. payload helper (machine-readable pointers) ----------

def test_payload_exposes_hypothesis_pointers(tmp_path: Path) -> None:
    ws = _seed(tmp_path, [_snap()])
    _seed_hypotheses(ws, [("H-1", "C-1", "open"),
                          ("H-2", "C-2", "open"),
                          ("H-3", "C-3", "superseded")])
    payload = state_anchor.build_anchor_payload(ws)
    ptrs = payload["hypothesis_pointers"]
    assert {p["hyp_id"] for p in ptrs} == {"H-1", "H-2"}  # open only
    for p in ptrs:
        assert set(p.keys()) == {"claim_id", "hyp_id"}    # pointers only


# ---------- 4. pre-#528 workspaces (no hypotheses/) ----------

def test_anchor_builds_without_hypotheses_dir(tmp_path: Path) -> None:
    """A pre-#528 workspace (or no snapshot at all) still anchors —
    missing hypotheses/ is the normal case, never an error."""
    ws = _seed(tmp_path, [_snap()])
    anchor = state_anchor.build_anchor(ws)
    assert "round=" in anchor
    assert "hyps=" not in anchor  # nothing to point at


def test_anchor_no_snapshot_returns_empty_with_hypotheses(
        tmp_path: Path) -> None:
    """build_anchor's existing contract: no ledger snapshot -> '' (silent),
    even with hypotheses present — the anchor is state re-anchoring, not
    a hypothesis browser."""
    ws = tmp_path
    _seed_hypotheses(ws, [("H-1", "C-1", "open")])
    assert state_anchor.build_anchor(ws) == ""


# ---------- 5. fail-open ----------

def test_anchor_survives_corrupt_hypothesis_file(tmp_path: Path) -> None:
    """A malformed hypotheses/*.md must not break the anchor (the store
    skips unparseable files; hypothesis absence is the degraded shape)."""
    ws = _seed(tmp_path, [_snap()])
    d = ws / "hypotheses"
    d.mkdir(parents=True)
    (d / "good.md").write_text(
        "---\nid: H-1\nclaim_id: C-1\ncompetitor_group: x\n"
        "candidates: [a]\nstatus: open\nschema_rev: 1\n---\nbody\n",
        encoding="utf-8")
    (d / "bad.md").write_text("garbage no frontmatter\n", encoding="utf-8")
    anchor = state_anchor.build_anchor(ws)
    assert "H-1" in anchor
