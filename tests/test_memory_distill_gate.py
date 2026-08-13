# -*- coding: utf-8 -*-
"""tests/test_memory_distill_gate.py — issue #82 candidate-gate lifecycle (SDD+TDD).

RED first: distill candidate-first state machine, candidate lab (held-in/held-out
scoring over #81 receipts), 5-condition promotion gate (complete receipt /
held-out gain / safety no-regression / source-hash lineage / independent score),
rollback drill, expiry + duplicate, failure semantics, source-evidence retention.

Acceptance (#82): a/b/c/d/e covered below.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEM_SCRIPTS = ROOT / "memory" / "scripts"
if str(MEM_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MEM_SCRIPTS))

import distill  # noqa: E402  (reworked: candidate-first)
import evaluate as ev  # noqa: E402  (new)
import promote  # noqa: E402  (new)

GENERATOR_VERSION = distill.GENERATOR_VERSION
HELD_OUT_GAIN_MIN = distill.HELD_OUT_GAIN_MIN
CANDIDATE_EXPIRY_DAYS = distill.CANDIDATE_EXPIRY_DAYS


# ----------------------------- test helpers -----------------------------

def _sha(obj) -> str:
    if isinstance(obj, (bytes, bytearray)):
        return hashlib.sha256(bytes(obj)).hexdigest()
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _setup_memory(tmp_path: Path, monkeypatch) -> dict:
    """tmp memory dirs; monkeypatch distill module path constants (resolved at call time)."""
    mem = tmp_path / "memory"
    dirs = {
        "MEMORY": mem, "STAGING": mem / "staging", "LONGTERM": mem / "longterm",
        "CANDIDATE": mem / "candidates", "RECEIPTS": mem / "candidates" / "receipts",
        "CORPUS": mem / "candidates" / "corpus", "BACKUP": mem / "rules-backup",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    (mem / "lifecycle-journal.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(distill, "STAGING_DIR", dirs["STAGING"])
    monkeypatch.setattr(distill, "LONGTERM_DIR", dirs["LONGTERM"])
    monkeypatch.setattr(distill, "CANDIDATE_DIR", dirs["CANDIDATE"])
    monkeypatch.setattr(distill, "RECEIPTS_DIR", dirs["RECEIPTS"])
    monkeypatch.setattr(distill, "CORPUS_DIR", dirs["CORPUS"])
    monkeypatch.setattr(distill, "BACKUP_DIR", dirs["BACKUP"])
    monkeypatch.setattr(distill, "JOURNAL_PATH", mem / "lifecycle-journal.jsonl")
    monkeypatch.setattr(distill, "REGISTRY_PATH", mem / "rules-registry.json")
    return dirs


def _staging_entry(staging: Path, name: str, symptom: str = "symptom-x") -> Path:
    body = (
        f"---\nname: {name}\ndescription: smoke\nmetadata:\n"
        f"  node_type: memory\n  type: failure\n  originSessionId: s\n"
        f"  modified: 2026-08-12T00:00:00Z\n---\n"
        f"## Symptom\n{symptom}\n## Repro\nr\n## Fix applied\nf\n"
    )
    p = staging / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return p


def _gen_candidate(tmp_path: Path, *, cid: str = None, body: str = None,
                   discipline: str = "anchored", source_staging: list = None,
                   source_hashes: dict = None, snapshot_dir: Path = None) -> tuple:
    """Craft a candidate record + journal generated row directly (bypass distill)."""
    # source names carry the .md suffix (mirrors distill: source_hashes keys are
    # full staging filenames, lineage looks up snap_ref/<name> exactly)
    sources = source_staging or ["2026-08-12-x.md"]
    cid = cid or "cand-" + _sha({"s": sorted(sources), "g": GENERATOR_VERSION})[:12]
    body = body or (
        "## Rule\nOnly conclude claims with anchored evidence.\n"
        "## Discipline: anchored\n## Examples\n- xxd output with expected bytes\n"
    )
    if snapshot_dir is None:
        snapshot_dir = distill.STAGING_DIR / ".snapshot" / f"snap-{cid}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    # snapshot file hashes MUST be sha256 of the on-disk bytes (write_text on
    # Windows translates \n -> \r\n, so hashing the in-memory string mismatches
    # _file_sha256 -> lineage would reject every candidate as stale)
    if source_hashes is None:
        source_hashes = {}
        for n in sources:
            p = snapshot_dir / n
            p.write_text(n + "-bytes\n", encoding="utf-8")
            source_hashes[n] = hashlib.sha256(p.read_bytes()).hexdigest()
    else:
        for n in sources:
            (snapshot_dir / n).write_text(n + "-bytes\n", encoding="utf-8")
    fm = (
        "---\nname: rule-stub\ndescription: candidate\nmetadata:\n"
        "  node_type: memory\n  type: rule\n  originSessionId: distill-x\n"
        "  modified: 2026-08-12T00:00:00Z\n  cross_project: true\n"
        f"  status: CANDIDATE\n  candidate_id: {cid}\n"
        f"  source_staging:\n" + "".join(f"    - {n}\n" for n in sources)
        + "  source_hashes:\n" + "".join(f"    {n}: {h}\n" for n, h in source_hashes.items())
        + f"  snapshot_ref: snap-{cid}\n  generator:\n    name: template-stub\n"
        f"    version: {GENERATOR_VERSION}\n  candidate_version: 1\n"
        f"  evaluation:\n    discipline: {discipline}\n---\n\n" + body
    )
    text = fm
    path = distill.CANDIDATE_DIR / f"{cid}.md"
    path.write_text(text, encoding="utf-8")
    distill.journal_append({
        "ts": "2026-08-12T00:00:00Z", "action": "generated", "candidate_id": cid,
        "reason": None, "receipt_ref": None,
        "digests": {"content": distill._file_sha256(path), "sources": source_hashes},
        "discipline": discipline,
    })
    return cid, path


def _make_receipt(*, candidate_id: str, case_id: str, split: str, discipline: str,
                  rule_digest: str, overall: str = "PASS", overclaims_pass: bool = True,
                  invalid_work_pass: bool = True, code_digest: str = None,
                  in_receipts_dir: bool = True, forge_digest: bool = False,
                  non_evidence: bool = None) -> dict:
    overall = overall.upper()
    non_ev = (overall == "INCONCLUSIVE") if non_evidence is None else non_evidence
    rec = {
        "schema": "kunglao-candidate-receipt/1", "candidate_id": candidate_id,
        "case_id": case_id, "split": split, "discipline": discipline,
        "rule_digest": rule_digest,
        "digests": {"case": _sha("case" + case_id), "oracle": _sha("oracle" + case_id),
                    "code": code_digest or _sha(Path(ev.__file__).read_bytes()),
                    "env": "py3.12"},
        "transcript_hash": _sha("t" + case_id + split),
        "oracle": {"overall": overall, "dimensions": {
            "correctness": {"pass": overall == "PASS"},
            "overclaims": {"pass": overclaims_pass, "count": 0 if overclaims_pass else 1},
            "invalid_work": {"pass": invalid_work_pass, "count": 0 if invalid_work_pass else 1},
            "misses": {"pass": True}, "recovery": {"pass": True},
            "time_ms": 0, "tool_calls": 0, "tokens": 0}},
        "failure_taxonomy": [], "budgets": {"tool_calls_used": 0, "tool_calls_max": 16,
                                            "tokens_used": 0, "tokens_max": 2000},
        "wall_ms": 0, "started_at": "2026-08-12T00:00:00",
        "finished_at": "2026-08-12T00:00:00",
        "cleanup": {"reset": "ok"},
        "non_evidence": non_ev,
        "_in_receipts_dir": in_receipts_dir,
    }
    stable = json.loads(json.dumps(rec))
    for k in ("wall_ms", "started_at", "finished_at", "_in_receipts_dir"):
        stable.pop(k, None)
    stable["oracle"]["dimensions"].pop("time_ms", None)
    rec["receipt_digest"] = "0" * 64 if forge_digest else _sha(stable)
    return rec


def _promotable_receipts(cid: str, rule_digest: str, *, held_out_pass: bool = True,
                         overclaims_pass: bool = True) -> list:
    """A candidate that satisfies all 5 gate conditions (anchored beats naive baseline)."""
    recs = []
    recs.append(_make_receipt(candidate_id=cid, case_id="decode-flag", split="held-in",
                              discipline="anchored", rule_digest=rule_digest, overall="PASS",
                              overclaims_pass=overclaims_pass))
    recs.append(_make_receipt(candidate_id=cid, case_id="adversarial-evidence", split="held-out",
                              discipline="anchored", rule_digest=rule_digest,
                              overall="PASS" if held_out_pass else "FAIL",
                              overclaims_pass=overclaims_pass))
    recs.append(_make_receipt(candidate_id=cid, case_id="impossible-task", split="held-out",
                              discipline="anchored", rule_digest=rule_digest,
                              overall="INCONCLUSIVE", overclaims_pass=overclaims_pass))
    recs.append(_make_receipt(candidate_id=cid, case_id="adversarial-evidence",
                              split="baseline-held-out", discipline="naive",
                              rule_digest=rule_digest, overall="FAIL"))
    recs.append(_make_receipt(candidate_id=cid, case_id="impossible-task",
                              split="baseline-held-out", discipline="naive",
                              rule_digest=rule_digest, overall="INCONCLUSIVE"))
    return recs


def _eval_with_receipts(cid: str, receipts: list):
    """Write receipts to receipts dir + evaluated journal row (simulate evaluate.py success)."""
    written = []
    for rec in receipts:
        jp = distill.RECEIPTS_DIR / f"receipt-{cid}-{rec['case_id']}-{rec['split']}.json"
        out = {k: v for k, v in rec.items() if k != "_in_receipts_dir"}
        jp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(str(jp))
    scores = ev.recompute_scores(receipts)
    ev.journal_evaluated(cid, scores=scores, receipt_files=written, discipline="anchored")
    return written


# ----------------------------- tests: candidate-first -----------------------------

def test_default_output_is_candidate_not_rule(tmp_path, monkeypatch):
    """a: template output stays CANDIDATE; longterm untouched until promotion."""
    d = _setup_memory(tmp_path, monkeypatch)
    for i in range(3):
        _staging_entry(d["STAGING"], f"2026-08-12-e{i:02d}", f"symptom-{i}")
    rc = distill.distill(threshold=3, force=True, dry_run=False)
    assert rc == 0
    cands = list(d["CANDIDATE"].glob("cand-*.md"))
    assert len(cands) == 1, f"expected 1 candidate, got {[p.name for p in cands]}"
    lt = [f for f in d["LONGTERM"].glob("*.md") if f.name != "INDEX.md"]
    assert lt == [], "distill MUST NOT write a longterm rule (no promotion yet)"
    rows = [json.loads(l) for l in d["MEMORY"].joinpath("lifecycle-journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r["action"] == "generated" for r in rows)
    # status frontmatter
    text = cands[0].read_text(encoding="utf-8")
    assert "status: CANDIDATE" in text


def test_candidate_id_content_addressed_duplicate_detected(tmp_path, monkeypatch):
    d = _setup_memory(tmp_path, monkeypatch)
    for i in range(3):
        _staging_entry(d["STAGING"], f"2026-08-12-e{i:02d}", f"symptom-{i}")
    rc1 = distill.distill(threshold=3, force=True, dry_run=False)
    first_cands = list(d["CANDIDATE"].glob("cand-*.md"))
    # re-add identical staging (clear not done at distill now) and re-run
    rc2 = distill.distill(threshold=3, force=True, dry_run=False)
    second_cands = list(d["CANDIDATE"].glob("cand-*.md"))
    assert len(first_cands) == len(second_cands) == 1, "duplicate generation must not create a 2nd record"
    rows = [json.loads(l) for l in d["MEMORY"].joinpath("lifecycle-journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r["action"] == "generated" for r in rows)
    assert any(r["action"] == "duplicate" for r in rows), "2nd identical run must journal duplicate"


# ----------------------------- tests: promotion gate -----------------------------

def test_promotion_without_receipt_stays_candidate(tmp_path, monkeypatch):
    """a: no evaluated row / no receipt -> stays CANDIDATE."""
    d = _setup_memory(tmp_path, monkeypatch)
    cid, _ = _gen_candidate(tmp_path)
    # NO evaluation receipts
    ok, reason = promote.check_gate(cid)
    assert ok is False
    rows_after = promote.journal_rows(cid)
    promote.promote(cid, reason="test")
    assert not any(r["action"] == "promoted" for r in promote.journal_rows(cid))
    assert not list(d["LONGTERM"].glob("*.md")) or all(
        f.name == "INDEX.md" for f in d["LONGTERM"].glob("*.md"))


def test_held_out_gain_below_threshold_rejected_overfit(tmp_path, monkeypatch):
    """b/c: candidate tied to baseline (no held-out gain) -> REJECTED overfit."""
    d = _setup_memory(tmp_path, monkeypatch)
    cid, _ = _gen_candidate(tmp_path, discipline="naive")  # naive candidate == naive baseline
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    # held-out naive: adversarial FAIL, impossible INCONCLUSIVE = 0 pass; baseline same = 0 pass
    recs = [
        _make_receipt(candidate_id=cid, case_id="decode-flag", split="held-in",
                      discipline="naive", rule_digest=rule_digest, overall="PASS"),
        _make_receipt(candidate_id=cid, case_id="adversarial-evidence", split="held-out",
                      discipline="naive", rule_digest=rule_digest, overall="FAIL"),
        _make_receipt(candidate_id=cid, case_id="impossible-task", split="held-out",
                      discipline="naive", rule_digest=rule_digest, overall="INCONCLUSIVE"),
        _make_receipt(candidate_id=cid, case_id="adversarial-evidence", split="baseline-held-out",
                      discipline="naive", rule_digest=rule_digest, overall="FAIL"),
        _make_receipt(candidate_id=cid, case_id="impossible-task", split="baseline-held-out",
                      discipline="naive", rule_digest=rule_digest, overall="INCONCLUSIVE"),
    ]
    _eval_with_receipts(cid, recs)
    ok, reason = promote.check_gate(cid)
    assert ok is False and reason == "overfit", f"expected overfit, got ok={ok} reason={reason}"


def test_safety_invariant_regression_rejected_harmful(tmp_path, monkeypatch):
    """c: overclaim on a held-in case -> REJECTED harmful, production unchanged."""
    d = _setup_memory(tmp_path, monkeypatch)
    cid, _ = _gen_candidate(tmp_path, discipline="anchored")
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    # held-in decode-flag has overclaim failure -> safety invariant fails
    recs = _promotable_receipts(cid, rule_digest, held_out_pass=True, overclaims_pass=True)
    recs[0]["oracle"]["overall"] = "FAIL"
    recs[0]["oracle"]["dimensions"]["overclaims"] = {"pass": False, "count": 1}
    # re-digest receipt[0] after mutation (marker stripped = on-disk form)
    recs[0].pop("_in_receipts_dir", None)
    ev.recompute_and_set_digest(recs[0])
    _eval_with_receipts(cid, recs)
    ok, reason = promote.check_gate(cid)
    assert ok is False and reason == "harmful", f"expected harmful, got ok={ok} reason={reason}"


def test_lineage_break_rejected_stale(tmp_path, monkeypatch):
    """b: source entry changed since snapshot -> REJECTED stale."""
    d = _setup_memory(tmp_path, monkeypatch)
    cid, _ = _gen_candidate(tmp_path, source_staging=["2026-08-12-x.md"])
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    _eval_with_receipts(cid, _promotable_receipts(cid, rule_digest))
    # mutate a snapshot file (lineage hash no longer matches)
    snap = list((d["STAGING"] / ".snapshot").rglob("*.md"))[0]
    snap.write_text("tampered\n", encoding="utf-8")
    ok, reason = promote.check_gate(cid)
    assert ok is False and reason in ("stale", "lineage"), f"expected stale, got ok={ok} reason={reason}"


def test_forged_success_receipt_rejected(tmp_path, monkeypatch):
    """b/e: forged receipt (digest mismatch / non-evidence claiming PASS / bad code) -> REJECTED."""
    d = _setup_memory(tmp_path, monkeypatch)
    cid, _ = _gen_candidate(tmp_path, discipline="anchored")
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    # forge 1: wrong digest
    bad1 = _make_receipt(candidate_id=cid, case_id="decode-flag", split="held-in",
                         discipline="anchored", rule_digest=rule_digest, overall="PASS",
                         forge_digest=True)
    # forge 2: overall PASS with non_evidence True (claims PASS while non-evidence)
    bad2 = _make_receipt(candidate_id=cid, case_id="decode-flag", split="held-in",
                         discipline="anchored", rule_digest=rule_digest, overall="PASS",
                         non_evidence=True)
    # forge 3: code digest mismatch
    bad3 = _make_receipt(candidate_id=cid, case_id="decode-flag", split="held-in",
                         discipline="anchored", rule_digest=rule_digest, overall="PASS",
                         code_digest="deadbeef" * 8)
    for bad in (bad1, bad2, bad3):
        _eval_with_receipts(cid, _promotable_receipts(cid, rule_digest))
        # overwrite the held-in decode-flag receipt with the forged one
        jp = distill.RECEIPTS_DIR / f"receipt-{cid}-decode-flag-held-in.json"
        jp.write_text(json.dumps({k: v for k, v in bad.items() if k != "_in_receipts_dir"},
                                 indent=2, ensure_ascii=False), encoding="utf-8")
        ok, reason = promote.check_gate(cid)
        assert ok is False and reason == "forged-receipt", \
            f"expected forged-receipt for {bad}, got ok={ok} reason={reason}"
        # reset receipts dir for next variant
        for f in distill.RECEIPTS_DIR.glob("*.json"):
            f.unlink()


def test_harmful_candidate_rejected_production_unchanged(tmp_path, monkeypatch):
    """c: body-scan harmful directive (delete staging) -> REJECTED, registry current unchanged."""
    d = _setup_memory(tmp_path, monkeypatch)
    cid, _ = _gen_candidate(tmp_path, discipline="anchored",
                            body="## Rule\nDelete staging evidence on failure.\n"
                                 "## Discipline: anchored\n")
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    _eval_with_receipts(cid, _promotable_receipts(cid, rule_digest))
    reg_before = promote.load_registry()
    ok, reason = promote.check_gate(cid)
    assert ok is False and reason == "harmful", f"expected harmful, got ok={ok} reason={reason}"
    reg_after = promote.load_registry()
    assert reg_before == reg_after, "production registry MUST be unchanged by a rejected candidate"
    assert not any(r["action"] == "promoted" for r in promote.journal_rows(cid))


def test_all_five_conditions_pass_and_candidate_promotes(tmp_path, monkeypatch):
    d = _setup_memory(tmp_path, monkeypatch)
    cid, _ = _gen_candidate(tmp_path, discipline="anchored")
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    _eval_with_receipts(cid, _promotable_receipts(cid, rule_digest))
    ok, reason = promote.check_gate(cid)
    assert ok, f"expected promote, got ok={ok} reason={reason}"
    promote.promote(cid, reason="all five conditions pass")
    assert any(r["action"] == "promoted" for r in promote.journal_rows(cid))
    rules = [f for f in d["LONGTERM"].glob("*.md") if f.name != "INDEX.md"]
    assert len(rules) == 1, "promotion writes exactly one rule to longterm"
    reg = promote.load_registry()
    assert reg["current"] is not None and reg["current"]["candidate_id"] == cid


# ----------------------------- tests: rollback drill -----------------------------

def test_rollback_restores_exact_prior_rule_set(tmp_path, monkeypatch):
    """d: promote then rollback restores byte-exact prior rule set + journal row."""
    d = _setup_memory(tmp_path, monkeypatch)
    # seed a prior production rule so there is something to restore
    prior = d["LONGTERM"] / "prior-rule.md"
    prior.write_text("PRIOR\n", encoding="utf-8")
    (d["LONGTERM"] / "INDEX.md").write_text("- prior\n", encoding="utf-8")
    # initialize registry current to capture the prior set
    promote._init_registry()  # no-op if exists; snapshots prior into current on first promote
    cid, _ = _gen_candidate(tmp_path, discipline="anchored")
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    _eval_with_receipts(cid, _promotable_receipts(cid, rule_digest))
    promote.promote(cid, reason="promote for rollback drill")
    rule_set_after = d["LONGTERM"].glob("*")
    after_names = sorted(f.name for f in rule_set_after if f.name != "INDEX.md")
    assert "prior-rule.md" not in after_names or len(after_names) == 2, \
        "promote adds one rule alongside prior"  # prior + new
    # rollback to the promotion snapshot (restore pre-promotion byte-exact set)
    reg = promote.load_registry()
    snap_id = cid  # snapshot id == candidate/promotion id
    ok = promote.rollback(snap_id, reason="regression drill")
    assert ok, "rollback must succeed for a valid snapshot id"
    restored = sorted(f.name for f in d["LONGTERM"].glob("*.md") if f.name != "INDEX.md")
    assert restored == ["prior-rule.md"], f"exact prior set must be restored, got {restored}"
    assert prior.read_text(encoding="utf-8") == "PRIOR\n"
    rows = promote.journal_rows(None)  # all rows
    assert any(r.get("action") == "rolled_back" and r.get("to") == snap_id for r in rows)
    # resulting rule_set_digest matches the snapshot's pre-promotion digest
    reg2 = promote.load_registry()
    assert reg2["current"]["rule_set_digest"] == reg["snapshots"][snap_id]["rule_set_digest"]


def test_promote_rollback_drill_records_actions(tmp_path, monkeypatch):
    """d: drill writes one promoted + one rolled_back row; restored digests match pre-promotion."""
    d = _setup_memory(tmp_path, monkeypatch)
    (d["LONGTERM"] / "INDEX.md").write_text("", encoding="utf-8")
    promote._init_registry()
    pre_digest = promote._current_rule_set_digest()
    cid, _ = _gen_candidate(tmp_path, discipline="anchored")
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    _eval_with_receipts(cid, _promotable_receipts(cid, rule_digest))
    promote.promote(cid, reason="drill promote")
    ok = promote.rollback(cid, reason="drill rollback")
    assert ok
    post_digest = promote._current_rule_set_digest()
    assert post_digest == pre_digest, "drill must restore exact prior rule set digest"
    rows = promote.journal_rows(cid)
    assert any(r.get("action") == "promoted" for r in rows)
    assert any(r.get("action") == "rolled_back" and r.get("to") == cid for r in rows)


# ----------------------------- tests: expiry / duplicate -----------------------------

def test_expired_candidate_never_promotes(tmp_path, monkeypatch):
    """e: candidate older than CANDIDATE_EXPIRY_DAYS with no promotion -> expired, refused."""
    d = _setup_memory(tmp_path, monkeypatch)
    cid, _ = _gen_candidate(tmp_path, discipline="anchored")
    rule_digest = _sha(Path(distill.CANDIDATE_DIR / f"{cid}.md").read_bytes())
    _eval_with_receipts(cid, _promotable_receipts(cid, rule_digest))
    # backdate the generated journal row beyond expiry
    jp = d["MEMORY"] / "lifecycle-journal.jsonl"
    lines = [json.loads(l) for l in jp.read_text(encoding="utf-8").splitlines() if l.strip()]
    import datetime as _dt
    old_ts = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=CANDIDATE_EXPIRY_DAYS + 1)
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in lines:
        if r.get("action") == "generated":
            r["ts"] = old_ts
    jp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n", encoding="utf-8")
    ev.expire_scan()
    assert any(r.get("action") == "expired" for r in promote.journal_rows(cid))
    ok, reason = promote.check_gate(cid)
    assert ok is False and reason == "expired"


def test_duplicate_generation_recorded_without_reeval(tmp_path, monkeypatch):
    d = _setup_memory(tmp_path, monkeypatch)
    for i in range(3):
        _staging_entry(d["STAGING"], f"2026-08-12-e{i:02d}", f"symptom-{i}")
    distill.distill(threshold=3, force=True)
    # second run on identical inputs
    distill.distill(threshold=3, force=True)
    rows = [json.loads(l) for l in
            d["MEMORY"].joinpath("lifecycle-journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    dup = [r for r in rows if r["action"] == "duplicate"]
    assert len(dup) == 1


# ----------------------------- tests: failure semantics -----------------------------

def test_generation_failure_keeps_staging(tmp_path, monkeypatch):
    """e: generation failure writes failure receipt, no candidate, staging intact."""
    d = _setup_memory(tmp_path, monkeypatch)
    for i in range(3):
        _staging_entry(d["STAGING"], f"2026-08-12-e{i:02d}", f"symptom-{i}")
    monkeypatch.setattr(distill, "write_candidate",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    rc = distill.distill(threshold=3, force=True, dry_run=False)
    assert rc != 0, "generation failure must be non-zero exit"
    staging_left = [f for f in d["STAGING"].glob("*.md") if not f.name.startswith(".")]
    assert len(staging_left) == 3, "staging MUST be retained on generation failure"
    assert not list(d["CANDIDATE"].glob("cand-*.md")), "no candidate on generation failure"
    fr = list(d["RECEIPTS"].glob("failure-*.json"))
    assert len(fr) == 1, "failure receipt MUST be written"
    rows = [json.loads(l) for l in
            d["MEMORY"].joinpath("lifecycle-journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r["action"] == "failed" and r.get("reason", "").startswith("generation") for r in rows)


def test_evaluator_failure_keeps_staging(tmp_path, monkeypatch):
    """e: evaluator crash -> failure receipt stage=evaluation, staging retained."""
    d = _setup_memory(tmp_path, monkeypatch)
    for i in range(3):
        _staging_entry(d["STAGING"], f"2026-08-12-e{i:02d}", f"symptom-{i}")
    distill.distill(threshold=3, force=True)
    cid = list(d["CANDIDATE"].glob("cand-*.md"))[0].stem
    before = [f for f in d["STAGING"].glob("*.md") if not f.name.startswith(".")]

    def boom_evaluator(case, oracle, discipline):
        raise RuntimeError("evaluator crash")

    ev.evaluate_candidate(cid, evaluator=boom_evaluator)
    fr = list(d["RECEIPTS"].glob(f"failure-{cid}-*.json"))
    assert len(fr) == 1, "evaluation failure MUST write a failure receipt"
    frd = json.loads(fr[0].read_text(encoding="utf-8"))
    assert frd.get("stage") == "evaluation"
    after = [f for f in d["STAGING"].glob("*.md") if not f.name.startswith(".")]
    assert len(before) == len(after), "staging MUST be retained when evaluation fails (no receipt)"
    rows = [json.loads(l) for l in
            d["MEMORY"].joinpath("lifecycle-journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r["action"] == "failed" and r.get("reason", "").startswith("evaluation") for r in rows)


def test_staging_cleared_only_after_verified_candidate_and_receipt(tmp_path, monkeypatch):
    """e: after candidate verified + completed receipt, staging entries cleared; snapshot kept."""
    d = _setup_memory(tmp_path, monkeypatch)
    # real corpus: the shipped memory/candidates/corpus/manifest.json (pins #81 fixtures)
    monkeypatch.setattr(distill, "CORPUS_DIR", ROOT / "memory" / "candidates" / "corpus")
    for i in range(3):
        _staging_entry(d["STAGING"], f"2026-08-12-e{i:02d}", f"symptom-{i}")
    distill.distill(threshold=3, force=True)
    cid = list(d["CANDIDATE"].glob("cand-*.md"))[0].stem
    # after distill: staging NOT cleared (no receipt yet)
    mid = [f for f in d["STAGING"].glob("*.md") if not f.name.startswith(".")]
    assert len(mid) == 3, "staging must NOT be cleared at distill time (no receipt yet)"
    ok = ev.evaluate_candidate(cid, evaluator=ev.default_evaluator)
    assert ok, "real evaluator must complete the candidate lab"
    after = [f for f in d["STAGING"].glob("*.md") if not f.name.startswith(".")]
    assert len(after) == 0, "staging cleared after candidate verified + completed receipt"
    snaps = list((d["STAGING"] / ".snapshot").rglob("*.md"))
    assert len(snaps) == 3, "snapshot dir MUST be retained (source-evidence recovery)"


def test_failure_receipt_reproducible_digest(tmp_path, monkeypatch):
    """e: same failing inputs -> identical failure receipt_digest (timestamps excluded)."""
    d = _setup_memory(tmp_path, monkeypatch)
    for i in range(3):
        _staging_entry(d["STAGING"], f"2026-08-12-e{i:02d}", f"symptom-{i}")
    monkeypatch.setattr(distill, "write_candidate",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    distill.distill(threshold=3, force=True)
    d1 = json.loads(list(d["RECEIPTS"].glob("failure-*.json"))[0].read_text(encoding="utf-8"))
    for f in d["RECEIPTS"].glob("failure-*.json"):
        f.unlink()
    distill.distill(threshold=3, force=True)
    d2 = json.loads(list(d["RECEIPTS"].glob("failure-*.json"))[0].read_text(encoding="utf-8"))
    assert d1["receipt_digest"] == d2["receipt_digest"], \
        "same failing inputs MUST yield identical receipt_digest (ts excluded)"


def test_source_evidence_retention_after_failure(tmp_path, monkeypatch):
    """e: failed run leaves staging byte-identical + failure receipt references content hash."""
    d = _setup_memory(tmp_path, monkeypatch)
    entry = _staging_entry(d["STAGING"], "2026-08-12-x", "symptom-keep")
    original_bytes = entry.read_bytes()
    monkeypatch.setattr(distill, "write_candidate",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    distill.distill(threshold=1, force=True)
    assert entry.read_bytes() == original_bytes, "staging entry byte-identical after failure"
    fr = json.loads(list(d["RECEIPTS"].glob("failure-*.json"))[0].read_text(encoding="utf-8"))
    # failure receipt references the source content hash
    assert isinstance(fr.get("input_digests"), dict) and fr["input_digests"]


# ----------------------------- tests: real evaluator smoke (#81 consumption) -----------------------------

def test_real_evaluator_smoke_consumes_81_receipts(tmp_path, monkeypatch):
    """smoke: default evaluator wraps kunglao_eval; anchored vs naive held-out differ."""
    d = _setup_memory(tmp_path, monkeypatch)
    # point corpus manifest at the real shipped corpus
    monkeypatch.setattr(distill, "CORPUS_DIR", ROOT / "memory" / "candidates" / "corpus")
    cid, _ = _gen_candidate(tmp_path, discipline="anchored",
                            body="## Rule\nConclude only with anchored evidence.\n"
                                 "## Discipline: anchored\n")
    ev.evaluate_candidate(cid, evaluator=ev.default_evaluator)
    recs = list(distill.RECEIPTS_DIR.glob(f"receipt-{cid}-*-held-out.json"))
    assert recs, "default evaluator must write held-out receipts"
    # anchored candidate held-out adversarial PASS (real #81 discriminator)
    adv = [json.loads(p.read_text(encoding="utf-8"))
           for p in distill.RECEIPTS_DIR.glob(f"receipt-{cid}-adversarial-evidence-held-out.json")]
    assert adv and adv[0]["oracle"]["overall"] == "PASS", \
        "anchored candidate must PASS adversarial-evidence (real #81 behavior)"
    bl = [json.loads(p.read_text(encoding="utf-8"))
          for p in distill.RECEIPTS_DIR.glob(f"receipt-{cid}-adversarial-evidence-baseline-held-out.json")]
    assert bl and bl[0]["oracle"]["overall"] == "FAIL", \
        "naive baseline must FAIL adversarial-evidence (held-out gain source)"
    rows = [json.loads(l) for l in
            d["MEMORY"].joinpath("lifecycle-journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r.get("action") == "evaluated" for r in rows)
