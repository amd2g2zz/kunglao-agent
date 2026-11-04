# -*- coding: utf-8 -*-
"""tests/test_verifier_integrity_measured_818.py — the verification
resolver + per-verifier calibration floor (#809) in the MEASURED leg
(issue #818; counts double: the Wave-0 verifier-integrity tooth).

Real record files on real workspaces. The resolver is fail-closed on
every miss; the calibration floor flags a one-sided corpus over the
sample floor, escalates at the repeat limit, and degrades to bounded
silence past it while the audit keeps counting.
"""
from __future__ import annotations

import json
from pathlib import Path

import verifier_integrity as vi  # noqa: E402  (scripts/ on pytest path)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _md(word: str, identity: str | None = None) -> str:
    head = (f"verifier-identity: {identity}\n" if identity else "")
    return head + f"## Result\nverdict: {word}\ndetail body\n"


# ---------- resolve_verification: the fail-closed ladder ----------

def test_explicit_reference_resolves_pass_words(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "runs" / "verification-C-1.md").write_text(
        _md("verified"), encoding="utf-8")
    for word in ("pass", "PASSED", "Confirmed", "passes"):
        (ws / "runs" / "verification-C-1.md").write_text(
            _md(word), encoding="utf-8")
        ok, got, detail = vi.resolve_verification(ws, "C-1",
                                                  "runs/verification-C-1.md")
        assert ok is True and got == word.lower()


def test_explicit_reference_fail_word_refuses(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "runs" / "verification-C-1.md").write_text(
        _md("rejected"), encoding="utf-8")
    ok, word, detail = vi.resolve_verification(ws, "C-1",
                                               "runs/verification-C-1.md")
    assert (ok, word) == (False, "rejected")
    assert "verdict=rejected" in detail


def test_unknown_verdict_word_is_not_a_pass(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "runs" / "verification-C-1.md").write_text(
        _md("kind-of-fine"), encoding="utf-8")
    ok, word, detail = vi.resolve_verification(ws, "C-1",
                                               "runs/verification-C-1.md")
    assert ok is False and word == "kind-of-fine"
    assert "unknown verdict word" in detail


def test_unparseable_record_fails_closed(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "runs" / "verification-C-1.md").write_text(
        "no verdict line here\n", encoding="utf-8")
    ok, _w, detail = vi.resolve_verification(ws, "C-1",
                                             "runs/verification-C-1.md")
    assert ok is False
    assert "no parseable verdict word" in detail


def test_explicit_escape_reference_is_refused(tmp_path) -> None:
    ws = _ws(tmp_path)
    ok, _w, detail = vi.resolve_verification(
        ws, "C-1", "../outside/verification.md")
    assert ok is False
    assert "escapes the workspace" in detail


def test_canonical_surfaces_first_hit_wins(tmp_path) -> None:
    ws = _ws(tmp_path)
    # the verify-note mirror surface carries the Overall verdict section
    (ws / "runs" / "C-2-verify-note.md").write_text(
        "## Overall verdict\npassed\n", encoding="utf-8")
    ok, word, rel = vi.resolve_verification(ws, "C-2", "")
    assert ok is True and word == "passed"
    assert "C-2-verify-note.md" in rel


def test_json_record_with_claims_list(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "runs" / "verify-redteam-C-3.md").unlink(missing_ok=True)
    (ws / "evidence").mkdir()
    (ws / "evidence" / "verdict.json").write_text(
        json.dumps({"claims": [{"id": "C-3", "verdict": "verified"}]}),
        encoding="utf-8")
    ok, word, _d = vi.resolve_verification(ws, "C-3", "")
    assert ok is True and word == "verified"
    # a claim absent from the json list is a fail-closed miss at that
    # surface, never a pass
    (ws / "evidence" / "verdict.json").write_text(
        json.dumps({"claims": [{"id": "C-OTHER", "verdict": "verified"}]}),
        encoding="utf-8")
    ok, _w, detail = vi.resolve_verification(ws, "C-3", "")
    assert ok is False
    assert "no parseable verdict word" in detail


def test_no_record_anywhere_is_a_clean_miss(tmp_path) -> None:
    ws = _ws(tmp_path)
    ok, word, detail = vi.resolve_verification(ws, "C-404", "")
    assert (ok, word) == (False, "")
    assert "no verification record found" in detail


# ---------- calibration_check: the per-verifier floor ----------

def _seed_corpus(ws: Path, identity: str | None, words: list) -> None:
    for i, word in enumerate(words):
        name = f"verification-C-{i}.md" if i % 2 == 0 \
            else f"verify-redteam-C-{i}.md"
        (ws / "runs" / name).write_text(
            _md(word, identity), encoding="utf-8")


def test_thin_corpus_says_nothing(tmp_path) -> None:
    ws = _ws(tmp_path)
    _seed_corpus(ws, "red-a", ["verified", "refuted"])   # 2 < floor 3
    assert vi.calibration_check(ws) == []
    assert _events(ws, "verifier_calibration_broken") == []


def test_mixed_corpus_is_never_broken(tmp_path) -> None:
    ws = _ws(tmp_path)
    _seed_corpus(ws, "red-a", ["verified", "refuted", "passes"])
    assert vi.calibration_check(ws) == []


def _events(ws: Path, action: str) -> list:
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return []
    return [json.loads(ln) for p in sorted(logs.glob("kunglao-*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and json.loads(ln).get("action") == action]


def test_all_reject_corpus_flags_and_escalates_at_the_limit(
        tmp_path) -> None:
    ws = _ws(tmp_path)
    _seed_corpus(ws, "red-flat", ["refuted", "rejected", "failed"])
    for occurrence in range(1, vi.CALIBRATION_REPEAT_LIMIT + 2):
        rows = vi.calibration_check(ws)
        assert len(rows) == 1
        row = rows[0]
        assert row["identity"] == "red-flat"
        assert row["sample"] == 3
        assert row["occurrence"] == occurrence
        assert row["broken"] is True
        assert row["escalated"] == (occurrence == vi.CALIBRATION_REPEAT_LIMIT)
    # occurrences past the limit: bounded silence, audit still counts
    assert len(_events(ws, "verifier_calibration_broken")) \
        == vi.CALIBRATION_REPEAT_LIMIT
    audit = json.loads(
        (ws / vi.CALIBRATION_AUDIT_REL).read_text(encoding="utf-8"))
    assert audit["red-flat"] == vi.CALIBRATION_REPEAT_LIMIT + 1


def test_all_pass_corpus_is_flagged_symmetrically(tmp_path) -> None:
    ws = _ws(tmp_path)
    _seed_corpus(ws, "red-rubber-stamp",
                 ["verified", "pass", "confirmed"])
    rows = vi.calibration_check(ws)
    assert rows and rows[0]["identity"] == "red-rubber-stamp"
    assert rows[0]["pass"] == 3 and rows[0]["fail"] == 0


def test_unattributed_all_reject_still_names_the_hole(tmp_path) -> None:
    ws = _ws(tmp_path)
    _seed_corpus(ws, None, ["refuted", "reject", "falsified"])
    rows = vi.calibration_check(ws)
    assert rows and rows[0]["identity"] == vi.UNATTRIBUTED


def test_scan_skips_unclassifiable_records(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "runs" / "verification-C-1.md").write_text(
        "verdict: shrug\n", encoding="utf-8")
    (ws / "runs" / "verification-C-2.md").write_text(
        "no verdict at all\n", encoding="utf-8")
    assert vi._scan_records(ws) == {}


# ---------- canonical_records ----------

def test_canonical_records_order_is_decisive() -> None:
    recs = vi.canonical_records("C-7")
    assert recs[0] == "runs/verification-C-7.md"
    assert recs[1] == "runs/C-7-verify-note.md"
    assert recs[2] == "runs/verify-redteam-C-7.md"
    assert recs[3] == "evidence/verdict.json"
