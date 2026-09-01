# -*- coding: utf-8 -*-
"""Tests for the failure→knowledge transducer (#495) — three artifacts +
obstacle promotion + method-ladder + provenance.

RED phase of issue #495. These tests pin the contract before implementation
(mirror of tests/test_failure_lessons.py style):

- record_analysis() accepts validated_capability / identified_obstacle /
  source; the analysis entry carries them (three failure artifacts — the
  third artifact is the promoted obstacle claim itself).
- identified_obstacle auto-promotes a NEW claim into claim-register.yaml
  (status OPEN, depends_on -> failed claim, answers_question inherited,
  origin=failure-obstacle marker) AND writes a real dependency edge into
  claim_deps.yaml — the flat DAG grows a node. Idempotent on re-record.
- recording a failure runs the lessons ladder automatically (same
  _score_lessons interface as --search): hits land in the entry's
  candidates field, the query string in method_ladder_query (auditable);
  a failing search NEVER blocks the record (fail-open).
- --source provenance is mandatory: missing or non-enum → record rejected;
  source=novel-hypothesis additionally requires non-empty candidates.
- coverage semantics tightened (reuses the BLOCKED state machine): an
  analysis without validated_capability/identified_obstacle does NOT cover
  the failed attempt — trajectory-1 unit replay: two transient failures +
  a death-declaration analysis (no artifacts) stays BLOCKED, i.e. no
  re-dispatch, no NEGATIVE conclusion; recording the artifacts unblocks.
"""
from __future__ import annotations

import subprocess
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


def _claim(cid: str, attempts: int = 2, statement: str = "sample does X",
           **extra) -> dict:
    c = {"id": cid, "status": "OPEN", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 1, "promotion_attempts": attempts,
         "depends_on": [], "statement": statement}
    c.update(extra)
    return c


def _record(ws: Path, cid: str, **kw) -> dict:
    """Function-level --record (same args as the CLI flags, #495 additions)."""
    return fag.record_analysis(
        ws, cid, kw.get("assumption", ""), kw.get("validity", ""),
        kw.get("next_method", ""), kw.get("outcome"), kw.get("what_happened"),
        validated_capability=kw.get("capability"),
        identified_obstacle=kw.get("obstacle"),
        source=kw.get("source"), library=kw.get("library"))


def _seed_lesson(lib: Path, name: str, topic: str, body: str) -> None:
    lib.mkdir(parents=True, exist_ok=True)
    (lib / name).write_text(
        f"---\ntype: lesson\noutcome: PROVEN\nclaim_topic: {topic}\n"
        f"next_method: switch to listen mode\nsources: [C-9]\n---\n\n"
        f"# Lesson\n{topic} {body}\n",
        encoding="utf-8")


def _register_ids(ws: Path) -> list:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    return [c.get("id") for c in reg.get("claims") or []]


def _promoted(ws: Path, parent_cid: str) -> dict | None:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    return next((c for c in reg.get("claims") or []
                 if c.get("obstacle_for") == parent_cid
                 and c.get("origin") == "failure-obstacle"), None)


# ---------- feature 1: three artifacts + obstacle promotion ----------

def test_record_three_artifacts_written(tmp_path):
    """--record with capability/obstacle/source lands all three in the
    analysis entry; a closure backfill preserves them (no clobber)."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    lib = tmp_path / "lib"          # empty library -> ladder runs, no hits
    lib.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2)])

    # Act — failure-time record with the three artifacts
    r = _record(ws, "C-1", assumption="spawn keeps app alive to trigger badger.a",
                validity="not-justified", next_method="switch to listen mode",
                capability="frida JNI bridge works (NewByteArray called)",
                obstacle="spawn times out under SELinux policy on the VM",
                source="lesson-hit", library=lib)

    # Assert
    assert r["recorded"] is True
    entry = r["entry"]
    assert entry["validated_capability"] == "frida JNI bridge works (NewByteArray called)"
    assert entry["identified_obstacle"] == "spawn times out under SELinux policy on the VM"
    assert entry["next_method_source"] == "lesson-hit"
    on_disk = yaml.safe_load(
        (ws / "analyses" / "failure-C-1.yaml").read_text(encoding="utf-8"))
    assert on_disk["validated_capability"] == entry["validated_capability"]
    assert on_disk["identified_obstacle"] == entry["identified_obstacle"]

    # Act — closure-only backfill must preserve the artifacts
    r2 = _record(ws, "C-1", outcome="REFUTED", what_happened="listen mode caught it")

    # Assert
    assert r2["recorded"] is True
    assert r2["entry"]["validated_capability"] == entry["validated_capability"]
    assert r2["entry"]["identified_obstacle"] == entry["identified_obstacle"]
    assert r2["entry"]["next_method_source"] == "lesson-hit"


def test_obstacle_promoted_to_claim_grows_dag(tmp_path):
    """identified_obstacle promotes a NEW claim: OPEN, depends_on the failed
    claim, answers_question inherited, origin marker set — and a REAL edge
    appears in claim_deps.yaml (flat DAG grows a node)."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    _write_register(ws, [_claim("C-1", attempts=2, statement="app calls badger.a",
                                answers_question="q-c2-protocol")])

    # Act
    r = _record(ws, "C-1", assumption="spawn triggers badger.a",
                validity="not-justified", next_method="switch to listen mode",
                capability="frida JNI bridge works",
                obstacle="spawn times out under SELinux",
                source="lesson-hit")

    # Assert — register grew a node with the right shape
    new = _promoted(ws, "C-1")
    assert new is not None, f"no promoted claim; register={_register_ids(ws)}"
    assert new["status"] == "OPEN"
    assert new["depends_on"] == ["C-1"]
    assert new["answers_question"] == "q-c2-protocol"      # value context inherited
    assert new["promotion_attempts"] == 0                   # fresh frontier
    assert new["promoted_from"] == "analyses/failure-C-1.yaml"
    assert "SELinux" in (new.get("statement") or "")
    assert new["id"] not in ("C-1",)

    # Assert — the REAL dependency edge landed in claim_deps.yaml
    deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8"))
    assert deps["depends_on"].get(new["id"]) == ["C-1"]

    # Assert — the record result surfaces the promotion
    assert r.get("obstacle_claim", {}).get("id") == new["id"]

    # Arrange — zero-padded id style follows the register's width
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    _write_register(ws2, [_claim("C-007", attempts=1)])
    # Act
    _record(ws2, "C-007", assumption="a", validity="not-justified",
            next_method="b", capability="c", obstacle="spawn blocked", source="web-hit")
    # Assert
    new2 = _promoted(ws2, "C-007")
    assert new2 is not None
    assert new2["id"] == "C-008"


def test_obstacle_promotion_idempotent(tmp_path):
    """Re-recording (same attempt or a later one) never creates a second
    promoted claim, and the claim_deps edge stays single."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2)])
    _record(ws, "C-1", assumption="a", validity="not-justified",
            next_method="b", capability="c", obstacle="spawn times out",
            source="lesson-hit")
    first = _promoted(ws, "C-1")
    assert first is not None

    # Act — same claim, re-record with reworded obstacle (attempt advanced)
    _record(ws, "C-1", assumption="a2", validity="not-justified",
            next_method="b2", capability="c2",
            obstacle="spawn times out (still, after fix attempt)", source="lesson-hit")

    # Assert — one promoted claim, same id, edge still single
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    marked = [c for c in reg["claims"] if c.get("obstacle_for") == "C-1"]
    assert len(marked) == 1
    assert marked[0]["id"] == first["id"]
    deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8"))
    assert deps["depends_on"].get(first["id"]) == ["C-1"]


def test_capability_without_obstacle_records_but_stays_blocked(tmp_path):
    """A record carrying capability but NO obstacle is allowed (partial),
    triggers no promotion, and does NOT unblock — either artifact missing
    means the failure was not fully transduced."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2)])

    # Act
    r = _record(ws, "C-1", assumption="a", validity="not-justified",
                next_method="b", capability="c", source="lesson-hit")

    # Assert
    assert r["recorded"] is True
    assert _promoted(ws, "C-1") is None                    # no obstacle -> no node
    assert {b["claim_id"] for b in fag.scan_workspace(ws)} == {"C-1"}   # still BLOCKED


# ---------- feature 2: method-ladder rung 1 (lessons) ----------

def test_record_runs_lessons_ladder_into_candidates(tmp_path):
    """Recording a failure auto-searches the lessons library with the
    obstacle+assumption signature; hits land in candidates, the query in
    method_ladder_query — auditable ladder trace."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    lib = tmp_path / "lib"
    _seed_lesson(lib, "lesson-aaa.md", "spawn timeout on android",
                 "spawn selinux timeout listen")
    _write_register(ws, [_claim("C-1", attempts=2)])

    # Act
    r = _record(ws, "C-1", assumption="spawn keeps the app alive",
                validity="not-justified", next_method="switch to listen mode",
                capability="frida bridge works",
                obstacle="spawn times out under selinux", source="lesson-hit",
                library=lib)

    # Assert
    entry = r["entry"]
    cands = entry.get("candidates") or []
    assert len(cands) == 1
    assert cands[0]["file"] == "lesson-aaa.md"
    assert "selinux" in entry["method_ladder_query"]
    assert "spawn" in entry["method_ladder_query"]


def test_ladder_fail_open_on_search_error(tmp_path, monkeypatch):
    """A crashing lessons search NEVER blocks the record (fail-open):
    candidates end up empty, recorded stays True."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2)])

    def _boom(query, library, limit=3):
        raise OSError("library disk gone")

    monkeypatch.setattr(fag, "_score_lessons", _boom)

    # Act
    r = _record(ws, "C-1", assumption="a", validity="not-justified",
                next_method="b", capability="c", obstacle="o", source="web-hit")

    # Assert
    assert r["recorded"] is True
    assert r["entry"]["candidates"] == []


# ---------- feature 3: provenance ----------

def test_source_required_to_record(tmp_path):
    """No --source (and no prior to inherit) -> record rejected, no file."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2)])

    # Act
    r = _record(ws, "C-1", assumption="a", validity="not-justified",
                next_method="b", capability="c", obstacle="o")

    # Assert
    assert r["recorded"] is False
    assert "--source" in r["reason"]
    assert not (ws / "analyses" / "failure-C-1.yaml").exists()


def test_source_invalid_enum_rejected(tmp_path):
    """source outside the 4-value enum -> rejected (normalized lowercase is
    accepted)."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2)])

    # Act + Assert — bad enum
    r = _record(ws, "C-1", assumption="a", validity="not-justified",
                next_method="b", capability="c", obstacle="o", source="guess")
    assert r["recorded"] is False
    assert "lesson-hit" in r["reason"]        # reason lists the legal values

    # Act + Assert — normalized casing is fine
    r2 = _record(ws, "C-1", assumption="a", validity="not-justified",
                 next_method="b", capability="c", obstacle="o", source="WEB-HIT")
    assert r2["recorded"] is True
    assert r2["entry"]["next_method_source"] == "web-hit"


def test_novel_hypothesis_requires_candidates(tmp_path):
    """source=novel-hypothesis is rejected while the ladder recorded no
    candidates; allowed once the ladder has a hit."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    empty_lib = tmp_path / "empty"
    empty_lib.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2)])

    # Act — empty ladder trace
    r = _record(ws, "C-1", assumption="a", validity="not-justified",
                next_method="b", capability="c", obstacle="spawn selinux",
                source="novel-hypothesis", library=empty_lib)

    # Assert
    assert r["recorded"] is False
    assert "novel" in r["reason"].lower()

    # Act — ladder has a hit now
    lib = tmp_path / "lib"
    _seed_lesson(lib, "lesson-hit1.md", "spawn timeout", "spawn selinux timeout")
    r2 = _record(ws, "C-1", assumption="a", validity="not-justified",
                 next_method="b", capability="c", obstacle="spawn selinux",
                 source="novel-hypothesis", library=lib)

    # Assert
    assert r2["recorded"] is True
    assert r2["entry"]["next_method_source"] == "novel-hypothesis"


# ---------- feature 4: BLOCKED semantics (trajectory-1 unit replay) ----------

def test_transient_failures_without_artifacts_stay_blocked(tmp_path):
    """Trajectory-1 replay (behavior equivalence class, not verbatim): two
    transient failures + a death-declaration analysis (3 questions answered,
    NO artifacts) stays BLOCKED — no re-dispatch, no NEGATIVE conclusion.
    Recording the three artifacts is what unblocks."""
    # Arrange — two transient failures, then a death-declaration analysis
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2,
                                statement="app calls badger.a under real Context")])
    adir = ws / "analyses"
    adir.mkdir()
    (adir / "failure-C-1.yaml").write_text(
        "claim: C-1\n"
        "covers_attempt: 2\n"
        "method_assumption: spawn mode keeps the app alive long enough\n"
        "assumption_validity: justified-adequate\n"
        "next_method: method was adequate\n"
        "analyzed_at: 2026-08-19T00:00:00+00:00\n",
        encoding="utf-8")

    # Act — the old contract would call this covered; #495 must not
    blocked = fag.scan_workspace(ws)

    # Assert — death declaration without artifacts does not unblock
    assert len(blocked) == 1
    assert blocked[0]["claim_id"] == "C-1"
    assert blocked[0]["state"] == "BLOCKED"

    # Act — transduce the failure properly (three artifacts + provenance)
    r = _record(ws, "C-1", assumption="spawn keeps app alive",
                validity="not-justified", next_method="switch to listen mode",
                capability="frida JNI bridge works (NewByteArray called)",
                obstacle="spawn times out — only the spawn path is dead",
                source="lesson-hit")

    # Assert — unblocked, and the obstacle became a claim (frontier grew)
    assert r["recorded"] is True
    assert fag.check_claim(ws, "C-1")["state"] == "OK_COVERED"
    assert _promoted(ws, "C-1") is not None


def test_blocked_lists_missing_artifacts(tmp_path):
    """check_claim BLOCKED output names which artifacts are missing
    (observability for the orchestrator)."""
    # Arrange — analysis covers the attempt but has only one artifact
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=1)])
    adir = ws / "analyses"
    adir.mkdir()
    (adir / "failure-C-1.yaml").write_text(
        "claim: C-1\n"
        "covers_attempt: 1\n"
        "method_assumption: a\n"
        "assumption_validity: not-justified\n"
        "next_method: b\n"
        "validated_capability: frida bridge works\n"
        "analyzed_at: 2026-08-19T00:00:00+00:00\n",
        encoding="utf-8")

    # Act
    r = fag.check_claim(ws, "C-1")

    # Assert
    assert r["state"] == "BLOCKED"
    assert r["missing_artifacts"] == ["identified_obstacle"]


# ---------- CLI wiring ----------

def test_cli_record_rejects_missing_source(tmp_path):
    """The real CLI rejects a --record without --source (exit 1, REJECTED)."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", attempts=2)])

    # Act
    r = subprocess.run([sys.executable, str(fag.__file__), str(ws), "C-1",
                        "--record", "--assumption", "a",
                        "--validity", "not-justified", "--next-method", "b",
                        "--validated-capability", "c",
                        "--identified-obstacle", "o"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")

    # Assert
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REJECTED" in (r.stdout or "")
    assert "--source" in (r.stdout or "")


def test_cli_record_full_transducer_path(tmp_path):
    """Full CLI path: record with all flags + --library -> RECORDED, the
    analysis file carries the artifacts + ladder trace, the obstacle is
    promoted into the register and claim_deps."""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    lib = tmp_path / "lib"
    _seed_lesson(lib, "lesson-full.md", "spawn timeout on android",
                 "spawn selinux timeout listen")
    _write_register(ws, [_claim("C-1", attempts=2,
                                statement="app calls badger.a",
                                answers_question="q-1")])

    # Act
    r = subprocess.run([sys.executable, str(fag.__file__), str(ws), "C-1",
                        "--record",
                        "--assumption", "spawn keeps the app alive",
                        "--validity", "not-justified",
                        "--next-method", "switch to listen mode",
                        "--validated-capability", "frida JNI bridge works",
                        "--identified-obstacle", "spawn times out under selinux",
                        "--source", "lesson-hit",
                        "--library", str(lib)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")

    # Assert
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RECORDED" in (r.stdout or "")
    entry = yaml.safe_load(
        (ws / "analyses" / "failure-C-1.yaml").read_text(encoding="utf-8"))
    assert entry["validated_capability"] == "frida JNI bridge works"
    assert entry["identified_obstacle"] == "spawn times out under selinux"
    assert entry["next_method_source"] == "lesson-hit"
    assert entry["candidates"], "ladder hits must land in candidates"
    assert "selinux" in entry["method_ladder_query"]
    new = _promoted(ws, "C-1")
    assert new is not None and new["depends_on"] == ["C-1"]
    deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8"))
    assert deps["depends_on"].get(new["id"]) == ["C-1"]
