# -*- coding: utf-8 -*-
"""tests/test_verifier_integrity_809.py — verifier-integrity faces.

The production replay pins (synthetic fixtures; no production text):

  1. A decisive-success mint resolves its verification reference to a
     PASSED record — settlement preceding a REJECT, and an all-reject
     corpus, refuse; a passing record mints.
  2. A 100 percent one-sided verifier is BROKEN — loud, bounded per
     verifier, escalating at the Standard 11 limit.
  3. YAML block-scalar format differences land a warn sidecar without
     changing the verdict; semantic mismatches still fail.
  4. Oracle registration is asserted at run start — loud and bounded
     when armed cases lack a registered client, silent otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import claims_store as cs  # noqa: E402
import kunglao_verify as kv  # noqa: E402
import oracle_cadence as oc  # noqa: E402
import verifier_integrity as vi  # noqa: E402
from _factories import write_claims_register  # noqa: E402


def _ws(tmp_path: Path, claims: list[dict] | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, claims or [{"id": "C-1", "status": "OPEN",
                                         "dispatch_count": 0}])
    return ws


def _reg_status(ws: Path, claim: str) -> str | None:
    import ws_yaml
    doc = ws_yaml.yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    for c in (doc.get("claims") or []):
        if str(c.get("id") or "") == claim:
            return str(c.get("status") or "")
    return None


def _prov(ws: Path) -> list[dict]:
    p = ws / cs.PROVENANCE_REL
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _events(ws: Path, action: str) -> list[dict]:
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if row.get("action") == action:
                out.append(row)
    return out


def _md(identity: str, verdict: str) -> str:
    return (f"---\nverifier-identity: {identity}\n"
            f"verdict: {verdict}\n---\n\nrecord body\n")


def _seed(ws: Path, rel: str, text: str) -> Path:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ------------------- 1. the mint resolves a PASSED record -------------------

def test_proven_refused_when_record_rejected(tmp_path) -> None:
    """Production shape A: the settlement mint precedes the verifier's
    REJECT — the store refuses; the register is byte-unchanged; one
    provenance row names the failing record."""
    ws = _ws(tmp_path, [{"id": "C-004", "status": "IN_PROGRESS"}])
    rec = _seed(ws, "runs/verification-C-004.md", _md("v-l1", "REJECTED"))
    r = cs.apply(ws, "C-004", "settle_proven", actor="settler",
                 evidence="oracle 3/3",
                 verification="runs/verification-C-004.md",
                 verification_ts="2000-01-01T00:00:00Z")
    assert r.ok is False
    assert "verification-not-passed" in r.reason
    assert "rejected" in r.reason.lower()
    assert _reg_status(ws, "C-004") == "IN_PROGRESS"
    row = _prov(ws)[-1]
    assert row["outcome"] == "refused"
    assert "verification-not-passed" in row["reason"]


def test_proven_refused_when_whole_corpus_rejected(tmp_path) -> None:
    """Production shape B: the L1 verifier rejected every verdict in the
    corpus — a non-path reference still resolves the canonical surfaces
    and the mint is refused (no passing record, no PROVEN)."""
    ws = _ws(tmp_path, [{"id": "C-006", "status": "IN_PROGRESS"}])
    _seed(ws, "runs/verification-C-006.md", _md("v-l1", "REJECTED"))
    _seed(ws, "runs/C-006-verify-note.md", _md("v-l1", "refuted"))
    r = cs.apply(ws, "C-006", "settle_proven", actor="settler",
                 verification="l1-verify-run",
                 verification_ts="2000-01-01T00:00:00Z")
    assert r.ok is False
    assert "verification-not-passed" in r.reason
    assert _reg_status(ws, "C-006") == "IN_PROGRESS"


def test_proven_applies_when_record_passes(tmp_path) -> None:
    ws = _ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
    _seed(ws, "runs/verification-C-1.md", _md("v-l1", "verified"))
    r = cs.apply(ws, "C-1", "settle_proven", actor="settler",
                 evidence="oracle 3/3",
                 verification="l1-verify-run",
                 verification_ts="2000-01-01T00:00:00Z")
    assert r.ok is True and r.to_status == "PROVEN"
    row = _prov(ws)[-1]
    assert row["outcome"] == "applied"


def test_verified_settle_requires_passing_record_too(tmp_path) -> None:
    ws = _ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
    _seed(ws, "runs/verification-C-1.md", _md("v-l1", "REJECTED"))
    r = cs.apply(ws, "C-1", "settle_verified", actor="settler",
                 verification="l1-verify-run",
                 verification_ts="2000-01-01T00:00:00Z")
    assert r.ok is False
    assert "verification-not-passed" in r.reason


def test_redteam_record_via_explicit_reference(tmp_path) -> None:
    ws = _ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
    _seed(ws, "runs/verify-redteam-C-1.md", _md("rt-1", "confirmed"))
    r = cs.apply(ws, "C-1", "settle_proven", actor="settler",
                 verification="runs/verify-redteam-C-1.md",
                 verification_ts="2000-01-01T00:00:00Z")
    assert r.ok is True and r.to_status == "PROVEN"


def test_reference_may_not_escape_workspace(tmp_path) -> None:
    ws = _ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
    outside = tmp_path / "outside.md"
    outside.write_text(_md("v-l1", "verified"), encoding="utf-8")
    r = cs.apply(ws, "C-1", "settle_proven", actor="settler",
                 verification="../outside.md",
                 verification_ts="2000-01-01T00:00:00Z")
    assert r.ok is False
    assert "verification-not-passed" in r.reason


def test_missing_record_refuses(tmp_path) -> None:
    ws = _ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
    r = cs.apply(ws, "C-1", "settle_proven", actor="settler",
                 verification="never-landed",
                 verification_ts="2000-01-01T00:00:00Z")
    assert r.ok is False
    assert "verification-not-passed" in r.reason


def test_resolver_classifies_words_and_faces() -> None:
    """Direct resolver pins: pass words, fail words, unknown words,
    verify-note mirror face, and the verdict.json face."""
    assert vi.PASS_VERDICTS >= {"verified", "confirmed", "pass",
                                "passed", "passes"}
    assert vi.FAIL_VERDICTS >= {"refuted", "rejected", "fail",
                                "failed", "falsified"}


def test_resolver_reads_verdict_json_face(tmp_path) -> None:
    ws = _ws(tmp_path)
    _seed(ws, "evidence/verdict.json", json.dumps({
        "claims": [{"id": "C-1", "verdict": "PASS"}]}))
    ok, word, detail = vi.resolve_verification(ws, "C-1", "verdict-face")
    assert ok is True and word.lower() == "pass"


# ------------------- 2. per-verifier calibration floor ----------------------

def test_calibration_all_reject_broken_loud_and_bounded(tmp_path) -> None:
    ws = _ws(tmp_path)
    n = vi.CALIBRATION_MIN_SAMPLE
    for i in range(n):
        _seed(ws, f"runs/verification-C-0{i + 1}.md",
              _md("v-broken", "REJECTED"))
    rows = vi.calibration_check(ws)
    assert rows and rows[0]["identity"] == "v-broken"
    assert rows[0]["broken"] is True
    assert rows[0]["fail"] == n and rows[0]["pass"] == 0
    ev = _events(ws, "verifier_calibration_broken")
    assert len(ev) == 1
    # bounded repetition: occurrences count, escalate AT the limit,
    # silence beyond it — while the audit keeps counting
    for _ in range(vi.CALIBRATION_REPEAT_LIMIT):
        rows = vi.calibration_check(ws)
    ev = _events(ws, "verifier_calibration_broken")
    assert len(ev) == vi.CALIBRATION_REPEAT_LIMIT
    last = json.loads(ev[-1].get("detail") or "{}")
    assert last.get("escalated") is True
    assert rows and rows[0]["occurrence"] == vi.CALIBRATION_REPEAT_LIMIT + 1
    vi.calibration_check(ws)
    assert len(_events(ws, "verifier_calibration_broken")) == \
        vi.CALIBRATION_REPEAT_LIMIT


def test_calibration_all_pass_symmetric_face(tmp_path) -> None:
    ws = _ws(tmp_path)
    for i in range(vi.CALIBRATION_MIN_SAMPLE):
        _seed(ws, f"runs/verification-C-1{i}.md",
              _md("v-rubber-stamp", "verified"))
    rows = vi.calibration_check(ws)
    assert rows and rows[0]["identity"] == "v-rubber-stamp"
    assert rows[0]["broken"] is True


def test_calibration_mixed_not_broken(tmp_path) -> None:
    ws = _ws(tmp_path)
    _seed(ws, "runs/verification-C-1.md", _md("v-ok", "verified"))
    _seed(ws, "runs/verification-C-2.md", _md("v-ok", "REJECTED"))
    _seed(ws, "runs/verification-C-3.md", _md("v-ok", "confirmed"))
    assert vi.calibration_check(ws) == []
    assert _events(ws, "verifier_calibration_broken") == []


def test_calibration_below_sample_floor_not_broken(tmp_path) -> None:
    ws = _ws(tmp_path)
    _seed(ws, "runs/verification-C-1.md", _md("v-thin", "REJECTED"))
    _seed(ws, "runs/verification-C-2.md", _md("v-thin", "REJECTED"))
    assert vi.calibration_check(ws) == []


# ------------------- 3. block-scalar parse faces ----------------------------

def test_literal_block_expected_parses_with_warning(tmp_path) -> None:
    ws = tmp_path
    (ws / "facts").mkdir()
    (ws / "facts" / "F-1.md").write_text(
        "---\nclaim_id: C-1\nexpected: |\n"
        "  field = 0x2A\n  count = 3\nreproduce: run.sh\n"
        "---\n\nbody\n", encoding="utf-8")
    fm = kv.load_fact(ws, "F-1")
    assert fm["expected"] == "field = 0x2A\ncount = 3"
    assert fm["reproduce"] == "run.sh"
    assert fm["_format_warnings"], "block-scalar normalization is recorded"
    assert kv.parse_value_assertions(fm["expected"]) == [
        ("field", "0x2A"), ("count", "3")]


def test_l1_block_scalar_expected_passes(tmp_path) -> None:
    """The pre-fix shape: a block-scalar expected with matching reproduce
    output was rejected for format. Now it passes with a warn sidecar
    and an unchanged verdict."""
    fact = {"reproduce": "print('field = 0x2A'); print('count = 3')",
            "expected": "field = 0x2A\ncount = 3",
            "_format_warnings": ["expected: literal block scalar folded"]}
    out = kv.l1_mechanical(fact, fixture=tmp_path)
    assert out["verdict"] == "PASS"
    assert out["warnings"]


def test_folded_scalar_normalizes_with_warning(tmp_path) -> None:
    ws = tmp_path
    (ws / "facts").mkdir()
    (ws / "facts" / "F-2.md").write_text(
        "---\nclaim_id: C-1\nexpected: >-\n"
        "  field =\n  0x2A\n---\n\nbody\n", encoding="utf-8")
    fm = kv.load_fact(ws, "F-2")
    assert fm["expected"] == "field = 0x2A"
    assert any("fold" in w.lower() for w in fm["_format_warnings"])


def test_block_scalar_semantic_mismatch_still_fails(tmp_path) -> None:
    fact = {"reproduce": "print('field = 0x2B')",
            "expected": "field = 0x2A"}
    out = kv.l1_mechanical(fact, fixture=tmp_path)
    assert out["verdict"] == "FAIL"
    assert "value-assertion mismatch" in out["detail"]
    assert not out.get("warnings")


# ------------------- 4. run-start oracle registration -----------------------

def _arm(ws: Path) -> None:
    cases = ws / "oracle" / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    (cases / "case-1.yaml").write_text("id: k-1\n", encoding="utf-8")


def test_run_start_loud_when_armed_but_unregistered(tmp_path) -> None:
    ws = _ws(tmp_path)
    _arm(ws)
    out = oc.assert_run_start(ws)
    assert out["registered"] is False
    ev = _events(ws, "oracle_cadence_warn")
    assert len(ev) == 1
    assert "client_not_registered" in ev[0]["detail"]
    assert "run_start" in ev[0]["detail"]


def test_run_start_bounded_across_repeats(tmp_path) -> None:
    ws = _ws(tmp_path)
    _arm(ws)
    total = oc.RUN_START_REPEAT_LIMIT + 3
    for _ in range(total):
        oc.assert_run_start(ws)
    ev = _events(ws, "oracle_cadence_warn")
    assert len(ev) == oc.RUN_START_REPEAT_LIMIT
    raw = ev[-1].get("detail") or ""
    last = json.loads(raw.split(": ", 1)[1]) if ": " in raw else {}
    assert last.get("escalated") is True


def test_run_start_quiet_when_registered_or_unarmed(tmp_path) -> None:
    ws = _ws(tmp_path)
    _arm(ws)
    _seed(ws, "oracle/client.py", "# the implementation under test\n")
    assert oc.assert_run_start(ws)["registered"] is True
    assert _events(ws, "oracle_cadence_warn") == []
    unarmed = _ws(tmp_path / "u2")
    assert oc.assert_run_start(unarmed)["registered"] is True
    assert _events(unarmed, "oracle_cadence_warn") == []


def test_begin_dispatch_fires_run_start_assertion(tmp_path) -> None:
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN",
                         "dispatch_count": 0}])
    _arm(ws)
    b = cs.begin_dispatch(ws, "C-1", actor="t", tier=1, prompt="d",
                          agent="w1", method_family="static-first")
    assert b.ok is True and b.reason == "intent-open"
    ev = _events(ws, "oracle_cadence_warn")
    assert ev and "run_start" in ev[0]["detail"]


# ------------------- existing store faces keep their contract ---------------

def test_negative_settlement_stays_exempt(tmp_path) -> None:
    ws = _ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
    r = cs.apply(ws, "C-1", "settle_negative", actor="settler")
    assert r.ok is True
