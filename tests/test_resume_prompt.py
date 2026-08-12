"""TDD RED — fired-predicate resume prompt (issue #45, RECOVER layer, F4).

RED contract: `scripts/external_kicker.py::build_resume_prompt(ws, *,
max_chars, max_open_claims) -> str` must be assembled from FIRED PREDICATES
over logged mechanical state — ledger last SNAPSHOT row, claim-register OPEN
/ PARTIALLY-VERIFIED claims, facts/_INDEX.md PARTIAL facts, in-progress
worker-status-*.md files — and must NEVER read progress.txt /
analysis_state.txt narrative.

All I/O is SYNTHETIC: pytest tmp_path workspaces only. The real workspace
(D:/works/samples/2026-07-01) is never read or written; no claude process is
spawned (the kick test uses dry_run=True).
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()
    return ws


def _ledger(ws: Path, rows: list[dict]) -> None:
    with open(ws / ".convergence_ledger.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _snapshot(ts: str, decision: str, open_ids: list, *,
              blockers: list | None = None, active_workers: int = 0,
              facts_total: int = 0) -> dict:
    return {"ts": ts, "decision": decision, "open_count": len(open_ids),
            "open_ids": open_ids, "partial_count": 0,
            "active_workers": active_workers,
            "blockers": blockers or [], "facts_total": facts_total}


def _register(ws: Path, claims: list[dict]) -> None:
    lines = ["claims:"]
    for c in claims:
        lines.append(f"- id: {c['id']}")
        for k, v in c.items():
            if k == "id":
                continue
            lines.append(f"  {k}: {v}")
    (ws / "claim-register.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- import: module must exist for any test to run ----------

def test_build_resume_prompt_importable():
    from external_kicker import build_resume_prompt  # noqa: F401
    assert callable(build_resume_prompt)


# ---------- RED 1: fired predicate from ledger last snapshot ----------

def test_prompt_contains_ledger_last_open_ids(tmp_path):
    ws = _ws(tmp_path)
    _ledger(ws, [
        _snapshot("2026-08-11T00:00:00Z", "DISPATCH", ["C-999"]),
        _snapshot("2026-08-11T00:05:00Z", "DISPATCH", ["C-201", "C-003"]),
    ])
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws)
    # ledger last-row open_ids are fired predicates — they MUST appear
    assert "C-201" in prompt
    assert "C-003" in prompt
    # round number = count of SNAPSHOT rows; decision echoed
    assert "你正在收敛循环第 2 轮" in prompt
    assert "DISPATCH" in prompt


# ---------- RED 2: narrative exclusion (never read progress.txt) ----------

def test_prompt_excludes_progress_narrative(tmp_path):
    ws = _ws(tmp_path)
    _ledger(ws, [_snapshot("2026-08-11T00:05:00Z", "DISPATCH", ["C-007"])])
    (ws / "progress.txt").write_text(
        "我正在分析 C-007，接下来准备做 VM detonation…", encoding="utf-8")
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws)
    assert "我正在分析 C-007" not in prompt


# ---------- RED 3: no open claims -> CONVERGED directive, not empty ----------

def test_prompt_converged_directive_when_no_open_claims(tmp_path):
    ws = _ws(tmp_path)
    _ledger(ws, [_snapshot("2026-08-11T00:05:00Z", "CONVERGED", [])])
    _register(ws, [{"id": "C-001", "status": "PROVEN"}])
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws)
    assert prompt
    assert "CONVERGED, verify report" in prompt


# ---------- RED 4: all blocker ids listed ----------

def test_prompt_lists_all_blockers(tmp_path):
    ws = _ws(tmp_path)
    _ledger(ws, [_snapshot("2026-08-11T00:05:00Z", "BLOCKED", [],
                           blockers=["B-01", "B-02"])])
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws)
    assert "B-01" in prompt
    assert "B-02" in prompt


# ---------- RED 5: partial facts + in-progress workers surfaced ----------

def test_prompt_surfaces_partial_facts_and_workers(tmp_path):
    ws = _ws(tmp_path)
    _ledger(ws, [_snapshot("2026-08-11T00:05:00Z", "DISPATCH_VERIFIER",
                           ["C-318"], active_workers=1)])
    facts = ws / "facts"
    facts.mkdir()
    (facts / "_INDEX.md").write_text(
        "F042 | PARTIAL | C-318 | 0 data pointers to blob VA range\n",
        encoding="utf-8")
    (ws / "runs" / "worker-status-C301.md").write_text(
        "[ts] step: analyzing | status: in-progress\n", encoding="utf-8")
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws)
    assert "F042" in prompt
    assert "C301" in prompt


# ---------- RED 6/7: length cap + priority-ordered truncation ----------

def _twenty_claims() -> list[dict]:
    claims = [{"id": "C-PRIMARY", "status": "OPEN", "answers_question": "q1"}]
    claims += [{"id": f"C-{i:03d}", "status": "OPEN"} for i in range(1, 20)]
    return claims


def test_prompt_truncates_claims_by_priority(tmp_path):
    ws = _ws(tmp_path)
    _register(ws, _twenty_claims())
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws, max_open_claims=5)
    # the primary-answering claim must survive truncation
    assert "C-PRIMARY" in prompt
    # the lowest-priority claim is dropped
    assert "C-019" not in prompt
    # explicit marker tells the fresh session the list is a top-N
    assert "truncated by priority" in prompt
    # the claims line lists exactly 5 ids
    claims_line = next(l for l in prompt.splitlines()
                       if l.startswith("当前 open claims"))
    import re
    assert len(re.findall(r"C-[A-Z\d]+", claims_line)) == 5


def test_prompt_obeys_char_cap(tmp_path):
    ws = _ws(tmp_path)
    _register(ws, _twenty_claims())
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws, max_chars=500)
    assert len(prompt) <= 500
    assert "truncated by priority" in prompt


# ---------- RED 8/9: robustness — missing / malformed state ----------

def test_prompt_missing_ledger_still_builds(tmp_path):
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-777", "status": "OPEN"}])
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws)
    assert prompt
    assert "C-777" in prompt
    assert "你正在收敛循环第 0 轮" in prompt


def test_prompt_skips_malformed_ledger_lines(tmp_path):
    ws = _ws(tmp_path)
    with open(ws / ".convergence_ledger.jsonl", "w", encoding="utf-8") as f:
        f.write("not-json{\n")
        f.write(json.dumps(_snapshot("2026-08-11T00:05:00Z", "DISPATCH",
                                     ["C-555"]), ensure_ascii=False) + "\n")
    from external_kicker import build_resume_prompt
    prompt = build_resume_prompt(ws)
    assert "C-555" in prompt
    assert "你正在收敛循环第 1 轮" in prompt


# ---------- RED 10: the kick stages the resume prompt ----------

def test_kick_stages_resume_prompt(tmp_path):
    ws = _ws(tmp_path)
    _ledger(ws, [_snapshot("2026-08-11T00:05:00Z", "DISPATCH", ["C-201"])])
    from external_kicker import tick
    rc = tick(ws, dry_run=True)
    assert rc == 0
    prompt_file = ws / "runs" / ".kicker-prompt.txt"
    assert prompt_file.exists()
    text = prompt_file.read_text(encoding="utf-8")
    assert text.startswith("你正在收敛循环第")
    assert "C-201" in text
