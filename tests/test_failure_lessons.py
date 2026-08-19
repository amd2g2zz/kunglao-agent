# -*- coding: utf-8 -*-
"""Tests for failure-lessons (#41) — outcome field on --record + lessons library.

RED phase of the failure-lessons change (GitHub #41). These tests pin the
contract before implementation:

- record_analysis() accepts optional outcome/what_happened, validating them,
  and preserves the prior entry's fields when only outcome is supplied at
  claim closure (no clobber of the failure-time analysis).
- aggregate_lessons() emits one lessons/lesson-<slug>.md per failure
  signature (method + assumption + claim topic); ONLY closed-loop outcomes
  enter the library (PROVEN/VERIFIED, or NEGATIVE that survived red-team via
  a ledger OUTCOME row checker=red-team result=CONFIRMED — #35); everything
  else goes to the /reflect human queue file (JSON array, claim_id|reason
  dedup). Idempotent re-runs.
- BLOCKED check output includes up to 3 similar lessons retrieved by plain
  keyword overlap (no embeddings); --search mode reuses the same scoring.
- analyses/ format stays backward-compatible: scan_workspace BLOCKED set is
  identical with or without the new fields.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import failure_analysis_gate as fag  # noqa: E402
import yaml  # noqa: E402


# ---------- helpers ----------

def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _claim(cid: str, attempts: int = 3, statement: str = "sample does X") -> dict:
    return {"id": cid, "status": "OPEN", "boundary_type": "positive_observation",
            "evidence_tier_attempted": 1, "promotion_attempts": attempts,
            "depends_on": [], "statement": statement}


def _analysis_path(ws: Path, cid: str) -> Path:
    return ws / "analyses" / f"failure-{cid}.yaml"


def _record(ws: Path, cid: str, **kwargs) -> dict:
    """Function-level --record (same args as the CLI flags).

    #495 contract migration: every record now carries the three failure
    artifacts + provenance. Defaults keep this file's original assertions
    (outcome handling / aggregation / retrieval) testing what they always
    tested, under the new unblock contract.
    """
    return fag.record_analysis(
        ws, cid,
        kwargs.get("assumption", ""), kwargs.get("validity", ""),
        kwargs.get("next_method", ""), kwargs.get("outcome"),
        kwargs.get("what_happened"),
        validated_capability=kwargs.get("capability", "bridge works"),
        identified_obstacle=kwargs.get("obstacle", "vm blocked it"),
        source=kwargs.get("source", "lesson-hit"))


def _write_ledger_redteam(ws: Path, cid: str, result: str = "CONFIRMED") -> None:
    row = {"type": "outcome", "ts": "2026-08-11T00:00:00Z",
           "claim_id": cid, "result": result, "checker": "red-team"}
    with open(ws / fag.LEDGER_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _queue_items(queue_path: Path) -> list:
    if not queue_path.exists():
        return []
    return json.loads(queue_path.read_text(encoding="utf-8"))


# ---------- record: outcome fields ----------

def test_record_outcome_writes_fields_and_preserves_prior(tmp_path):
    """Claim closure: --record --outcome --what-happened adds both fields and
    preserves the failure-time analysis (assumption/validity/next_method)."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=3)])
    r1 = _record(ws, "C-1", assumption="grep sees IOCs", validity="not-justified",
                 next_method="runtime Frida hook")
    assert r1["recorded"] is True
    prior_analyzed_at = r1["entry"]["analyzed_at"]

    # Act — closure-time call with ONLY outcome + what_happened
    r2 = _record(ws, "C-1", outcome="PROVEN", what_happened="Frida caught NtCreateThreadEx")

    # Assert
    assert r2["recorded"] is True
    entry = r2["entry"]
    assert entry["outcome"] == "PROVEN"
    assert entry["what_happened"] == "Frida caught NtCreateThreadEx"
    assert entry["method_assumption"] == "grep sees IOCs"      # preserved
    assert entry["assumption_validity"] == "not-justified"     # preserved
    assert entry["next_method"] == "runtime Frida hook"        # preserved
    assert entry["analyzed_at"] == prior_analyzed_at           # preserved
    assert entry["covers_attempt"] == 3


def test_record_outcome_validation(tmp_path):
    """Bad outcome value / outcome-without-what-happened / what-happened-
    without-outcome are all rejected with no file written."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1")])

    # Act + Assert
    assert _record(ws, "C-1", outcome="MAYBE", what_happened="x")["recorded"] is False
    assert _record(ws, "C-1", outcome="PROVEN")["recorded"] is False
    assert _record(ws, "C-1", what_happened="x")["recorded"] is False
    # lowercase outcome is normalized (valid) — on top of a proper baseline
    r = _record(ws, "C-1", assumption="a", validity="not-justified",
                next_method="b", outcome="verified", what_happened="ok")
    assert r["recorded"] is True
    assert r["entry"]["outcome"] == "VERIFIED"
    # a rejected call must not have written a file
    assert _record(ws, "C-2", outcome="MAYBE", what_happened="x")["recorded"] is False
    assert not _analysis_path(ws, "C-2").exists()


def test_record_legacy_fields_unchanged(tmp_path):
    """A record without outcome flags produces exactly the #495 field set:
    the six legacy fields keep their names/positions, plus the transducer
    fields (artifacts / provenance / ladder trace); outcome stays absent."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1")])

    # Act
    r = _record(ws, "C-1", assumption="a", validity="justified-adequate", next_method="adequate")

    # Assert
    assert set(r["entry"].keys()) == {
        "claim", "covers_attempt", "method_assumption",
        "assumption_validity", "next_method",
        "next_method_source",               # #495 provenance
        "validated_capability", "identified_obstacle",   # #495 artifacts
        "method_ladder_query", "candidates",             # #495 ladder trace
        "analyzed_at"}
    assert "outcome" not in r["entry"]


# ---------- aggregate: closed-loop gate ----------

def test_lessons_proven_writes_lesson_file(tmp_path):
    """Closing a claim as PROVEN -> one lesson-*.md in the (tmp) library,
    named by failure signature."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", statement="detect C2 protocol")])
    _record(ws, "C-1", assumption="static grep finds IOC", validity="not-justified",
            next_method="runtime frida hook", outcome="PROVEN",
            what_happened="frida caught the runtime-built IOC")
    lib = tmp_path / "lib"

    # Act
    res = fag.aggregate_lessons(ws, library=lib, reflect_queue=tmp_path / "q.json")

    # Assert
    assert res["lessons_written"] == 1
    files = list(lib.glob("lesson-*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["method_assumption"] == "static grep finds IOC"
    assert fm["next_method"] == "runtime frida hook"
    assert "detect c2 protocol" in fm["claim_topic"].lower()
    assert fm["outcome"] == "PROVEN"
    assert "frida caught the runtime-built IOC" in text


def test_lessons_negative_needs_redteam_confirm(tmp_path):
    """NEGATIVE enters the library ONLY when the ledger has a red-team
    CONFIRMED OUTCOME row (#35); otherwise it goes to the /reflect queue."""
    # Arrange — survived red-team
    ws1 = tmp_path / "ws1"
    ws1.mkdir()
    _write_register(ws1, [_claim("C-2", statement="no network protocol")])
    _record(ws1, "C-2", assumption="static import table shows nothing",
            validity="justified-adequate", next_method="method was adequate",
            outcome="NEGATIVE", what_happened="no network syscalls across 3 methods")
    _write_ledger_redteam(ws1, "C-2", "CONFIRMED")

    # Act
    res = fag.aggregate_lessons(ws1, library=tmp_path / "lib1", reflect_queue=tmp_path / "q1.json")

    # Assert — in library
    assert res["lessons_written"] == 1
    assert len(list((tmp_path / "lib1").glob("lesson-*.md"))) == 1
    assert _queue_items(tmp_path / "q1.json") == []

    # Arrange — did NOT survive (no red-team row)
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    _write_register(ws2, [_claim("C-3", statement="no network protocol")])
    _record(ws2, "C-3", assumption="static import table shows nothing",
            validity="justified-adequate", next_method="method was adequate",
            outcome="NEGATIVE", what_happened="no network syscalls")
    q2 = tmp_path / "q2.json"

    # Act
    res2 = fag.aggregate_lessons(ws2, library=tmp_path / "lib2", reflect_queue=q2)

    # Assert — /reflect queue, not library
    assert res2["lessons_written"] == 0
    assert len(list((tmp_path / "lib2").glob("lesson-*.md"))) == 0
    items = _queue_items(q2)
    assert len(items) == 1
    assert items[0]["claim_id"] == "C-3"
    assert items[0]["reason"] == "negative-unverified"
    assert items[0]["type"] == "failure-lesson-candidate"


def test_lessons_refuted_and_no_outcome_go_to_queue(tmp_path):
    """REFUTED and no-outcome entries produce NO lesson file; both go to the
    /reflect queue with distinct reasons; re-runs are idempotent."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-4", statement="persistence via registry"),
                         _claim("C-5", statement="C2 over tls")])
    _record(ws, "C-4", assumption="run key in hive", validity="not-justified",
            next_method="frida hook RegSetValueEx", outcome="REFUTED",
            what_happened="no persistence code at all")
    _record(ws, "C-5", assumption="tls handshake visible", validity="not-justified",
            next_method="strace openssl calls")  # no outcome — never closed
    lib = tmp_path / "lib"
    q = tmp_path / "q.json"

    # Act
    res = fag.aggregate_lessons(ws, library=lib, reflect_queue=q)

    # Assert — no lessons, two queue items with distinct reasons
    assert res["lessons_written"] == 0
    assert len(list(lib.glob("lesson-*.md"))) == 0
    items = _queue_items(q)
    reasons = sorted(i["reason"] for i in items)
    assert reasons == ["no-outcome", "refuted"]
    assert {i["claim_id"] for i in items} == {"C-4", "C-5"}

    # Act — re-run
    res2 = fag.aggregate_lessons(ws, library=lib, reflect_queue=q)

    # Assert — idempotent: no new queue items
    assert res2["queue_added"] == 0
    assert len(_queue_items(q)) == 2


def test_lessons_group_and_dedup(tmp_path):
    """Same-signature claims group into ONE lesson file listing both sources;
    re-running writes nothing new."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-6", statement="decrypt config blob"),
                         _claim("C-7", statement="decrypt config blob")])
    for cid in ("C-6", "C-7"):
        _record(ws, cid, assumption="config is xor-encrypted", validity="not-justified",
                next_method="find decryption loop in main", outcome="VERIFIED",
                what_happened=f"{cid}: byte loop found and reproduced")
    lib = tmp_path / "lib"

    # Act
    res = fag.aggregate_lessons(ws, library=lib, reflect_queue=tmp_path / "q.json")

    # Assert — one file, two sources
    assert res["lessons_written"] == 1
    files = list(lib.glob("lesson-*.md"))
    assert len(files) == 1
    fm = yaml.safe_load(files[0].read_text(encoding="utf-8").split("---", 2)[1])
    assert set(fm["sources"]) == {"C-6", "C-7"}

    # Act — re-run
    res2 = fag.aggregate_lessons(ws, library=lib, reflect_queue=tmp_path / "q.json")

    # Assert — idempotent
    assert res2["lessons_written"] == 0
    assert res2["lessons_skipped"] == 1
    assert len(list(lib.glob("lesson-*.md"))) == 1


def test_lessons_missing_analyses_dir_no_crash(tmp_path):
    """Empty workspace: no analyses dir -> 0 written, no queue, no crash."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [])

    # Act
    res = fag.aggregate_lessons(ws, library=tmp_path / "lib", reflect_queue=tmp_path / "q.json")

    # Assert
    assert res["lessons_written"] == 0
    assert res["queue_added"] == 0


# ---------- retrieval: BLOCKED similar lessons + --search ----------

def test_blocked_includes_similar_lessons(tmp_path):
    """A BLOCKED claim's check output carries the top-3 similar lessons from
    the library, best-scoring first; an empty library yields []."""
    # Arrange — library with 4 lessons, 3 of which overlap the claim's topic
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-8", attempts=2, statement="frida attach fails on host vm")])
    lib = tmp_path / "lib"
    lib.mkdir()
    for i, (topic, nm) in enumerate([
            ("frida attach fails", "run frida over tcp"),
            ("frida attach fails", "use frida-server on vm"),
            ("frida attach fails", "x64dbg remote session"),
            ("decrypt config", "find decryption loop")]):
        (lib / f"lesson-aaa{i}.md").write_text(
            f"---\ntype: lesson\noutcome: PROVEN\nclaim_topic: {topic}\n"
            f"next_method: {nm}\nsources: [C-9]\n---\n\n# Lesson\n{topic} {nm}\n",
            encoding="utf-8")

    # Act
    r = fag.check_claim(ws, "C-8", library=lib)

    # Assert — 3 similar lessons, frida-themed, best first
    assert r["state"] == "BLOCKED"
    sim = r.get("similar_lessons") or []
    assert len(sim) == 3
    assert all("frida" in (s.get("claim_topic") or "").lower() for s in sim)
    assert sim[0]["score"] >= sim[1]["score"] >= sim[2]["score"]

    # Assert — scan mode carries them too
    blocked = fag.scan_workspace(ws, library=lib)
    assert len(blocked) == 1
    assert len(blocked[0].get("similar_lessons") or []) == 3

    # Assert — empty library -> [] and BLOCKED state unchanged
    r2 = fag.check_claim(ws, "C-8", library=tmp_path / "nolib")
    assert r2["state"] == "BLOCKED"
    assert r2["similar_lessons"] == []


def test_search_keywords(tmp_path):
    """--search matches lessons by keyword overlap; no overlap -> empty."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "lesson-aaa.md").write_text(
        "---\ntype: lesson\noutcome: PROVEN\nclaim_topic: frida attach\n"
        "next_method: run frida-server on vm\nsources: [C-1]\n---\n\n# Lesson\nfrida attach\n",
        encoding="utf-8")
    (lib / "lesson-bbb.md").write_text(
        "---\ntype: lesson\noutcome: VERIFIED\nclaim_topic: decrypt config\n"
        "next_method: find decryption loop\nsources: [C-2]\n---\n\n# Lesson\ndecrypt config\n",
        encoding="utf-8")

    # Act
    hits = fag.search_lessons("frida vm", library=lib)
    misses = fag.search_lessons("no such keyword", library=lib)

    # Assert
    assert len(hits) == 1
    assert hits[0]["file"] == "lesson-aaa.md"
    assert hits[0]["outcome"] == "PROVEN"
    assert misses == []


# ---------- backward compatibility ----------

def test_failure_blocked_parsing_backward_compatible(tmp_path):
    """scan_workspace BLOCKED set is identical with and without the new
    outcome fields — hooks/dispatch_gate._failure_blocked_ids keeps working."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-10", attempts=2),       # no analysis -> BLOCKED
                         _claim("C-11", attempts=2)])      # analysis w/o outcome -> covered
    _record(ws, "C-11", assumption="a", validity="not-justified", next_method="b")
    expected = {"C-10"}

    # Act
    blocked_legacy = {b["claim_id"] for b in fag.scan_workspace(ws)}

    # Assert — baseline
    assert blocked_legacy == expected

    # Act — add outcome fields to C-11's analysis and re-scan
    _record(ws, "C-11", outcome="REFUTED", what_happened="was wrong")
    blocked_new = {b["claim_id"] for b in fag.scan_workspace(ws)}

    # Assert — unchanged: new fields do not alter the gate decision
    assert blocked_new == expected
    assert fag._analysis_covers(fag._load_analysis(ws, "C-11"), _claim("C-11", attempts=2))


# ---------- CLI wiring regression (orchestrator verification) ----------

def test_cli_check_forwards_library_into_blocked_output(tmp_path):
    """The CLI single-claim check MUST forward --library so BLOCKED output
    lists similar lessons.

    Regression: check_claim(workspace, cid) dropped the library kwarg, so
    _print_blocked never surfaced similar_lessons and the acceptance
    criterion 'BLOCKED output contains 3 similar lessons' failed via the CLI even though
    the function-level tests passed."""
    import subprocess
    import sys as _sys

    ws = tmp_path / "ws"
    ws.mkdir()
    lib = tmp_path / "lib"
    lib.mkdir()
    # seed 3 lessons overlapping the BLOCKED claim's topic
    for i in range(3):
        (lib / f"lesson-seed{i}.md").write_text(
            f"---\ntype: lesson\noutcome: PROVEN\nclaim_topic: api on inject path\n"
            f"next_method: static-xref-{i}\nsources: [C-9]\n---\n\n"
            f"# Lesson\napi on inject path variant {i}\n",
            encoding="utf-8")
    _write_register(ws, [_claim("C-50", attempts=3, statement="api on inject path")])

    # Act — run the real CLI, not the functions
    r = subprocess.run([_sys.executable, str(fag.__file__), str(ws), "C-50",
                        "--library", str(lib)],
                       capture_output=True, text=True)

    # Assert — BLOCKED output carries the similar-lessons section
    assert r.returncode == 1
    assert "Similar lessons" in (r.stdout or ""), r.stdout
    assert "api on inject path" in (r.stdout or "")


def test_cli_scan_forwards_library(tmp_path):
    """CLI scan mode forwards --library too (same regression class)."""
    import subprocess
    import sys as _sys

    ws = tmp_path / "ws"
    ws.mkdir()
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "lesson-s.md").write_text(
        "---\ntype: lesson\noutcome: PROVEN\nclaim_topic: api on inject path\n"
        "next_method: static-xref\nsources: [C-9]\n---\n\n# Lesson\napi on inject path\n",
        encoding="utf-8")
    _write_register(ws, [_claim("C-60", attempts=3, statement="api on inject path")])

    # Act — scan mode (no claim_id)
    r = subprocess.run([_sys.executable, str(fag.__file__), str(ws),
                        "--library", str(lib)],
                       capture_output=True, text=True)

    # Assert
    assert r.returncode == 1
    assert "Similar lessons" in (r.stdout or ""), r.stdout
