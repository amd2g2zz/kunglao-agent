# -*- coding: utf-8 -*-
"""Issue #341 — the same-slot value-join rotation induction mechanism (B+D).

Failure class: F(K1 decrypts) and F(K2 decrypts) are individually true,
non-contradictory facts; the rotation is MECHANICALLY derivable (same claim
slot, distinct value fingerprints) but nothing derives it (#341 F2). This
module pins the dumb script that derives it, zero model judgment:

- group `source: dynamic`-family runtime facts by (claim_id, subject_slot);
- >= 2 DISTINCT value_fingerprints under one slot -> fire ONCE:
  `runtime_value_rotation` event + competitor hypothesis + pending
  synthesis note + convergence-ledger row (the D wiring);
- same fingerprint set again -> NO re-emit (idempotent);
- fingerprints only, never raw values, in any event/ledger/hypothesis/note.

Real fixtures on disk (tmp_path) — no gate-mocks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import event_taxonomy  # noqa: E402
import mechanism_scheduler  # noqa: E402
from kunglao_log import iter_jsonl, log_path  # noqa: E402
from hypothesis_store import HypothesisStore  # noqa: E402
from runtime_facts import fingerprint  # noqa: E402
import convergence_health  # noqa: E402
import rotation_induction as ri  # noqa: E402

_FP1 = "b" * 64
_FP2 = "c" * 64
_FP3 = "d" * 64


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "hypotheses").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    statement: sample decrypts the config blob\n"
        "  - id: C-002\n"
        "    status: OPEN\n"
        "    statement: license check passes\n",
        encoding="utf-8")
    return ws


def _write_runtime_fact(ws: Path, n: int, *, claim: str = "C-001",
                        slot: str = "config-decrypt-key",
                        fp: str = _FP1, captured_at: str = "2026-09-22T10:00:00Z",
                        title: str = "Config decrypt AES key recovered") -> None:
    """One schema-legal runtime fact on disk (the write gate guarantees the
    four fields on live facts; the fixture writes them directly)."""
    body = f"""---
id: F{n:03d}-runtime-observation
type: fact
title: {title}
status: INFERRED
created: 2026-09-22
last_reviewed: 2026-09-22
claim_id: {claim}
claim: runtime observation
boundary_type: observation
promotion_gate: characterize the derivation point under a debugger
source: dynamic-trace
confidence: medium
verify_status: pending
temporal_scope: runtime
subject_slot: {slot}
value_fingerprint: {fp}
captured_at: {captured_at}
verified: pending
provenance:
  - {{role: capture_log, path: runs/frida-00{n}.log, content_sha256: {"a" * 64}, credibility: B2}}
reproduce: |
  frida -l hook.js
---

## Status

INFERRED
"""
    (ws / "facts" / f"F{n:03d}-runtime-observation.md").write_text(
        body, encoding="utf-8")


def _events(ws: Path) -> list[dict]:
    p = log_path(ws)
    if not p.exists():
        return []
    return [e for e in iter_jsonl(
        p.read_text(encoding="utf-8", errors="replace").splitlines())]


def _rotation_events(ws: Path) -> list[dict]:
    return [e for e in _events(ws)
            if e.get("action") == ri.ROTATION_ACTION]


def _conv_rows(ws: Path) -> list[dict]:
    p = ws / ".convergence_ledger.jsonl"
    if not p.exists():
        return []
    return [e for e in iter_jsonl(
        p.read_text(encoding="utf-8", errors="replace").splitlines())]


# =====================================================================
# scan + detect: the join keys on (claim_id, subject_slot) ONLY
# =====================================================================

def test_scan_reads_only_runtime_facts_with_slot_and_fingerprint(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1)
    static = ws / "facts" / "F002-static.md"
    static.write_text(
        "---\nid: F002-static\ntitle: Import table\ntype: fact\n"
        "status: INFERRED\ncreated: 2026-09-22\nlast_reviewed: 2026-09-22\n"
        "claim_id: C-001\nsource: static-decompile\nconfidence: medium\n"
        "boundary_type: observation\npromotion_gate: x\n---\n\n## Status\n\nINFERRED\n",
        encoding="utf-8")
    recs = ri.scan_runtime_facts(ws)
    assert [r["fid"] for r in recs] == ["F001-runtime-observation"]
    assert recs[0]["subject_slot"] == "config-decrypt-key"
    assert recs[0]["value_fingerprint"] == _FP1
    assert recs[0]["claim_id"] == "C-001"


def test_two_facts_same_slot_distinct_fps_detected(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, fp=_FP1, captured_at="2026-09-22T10:00:00Z")
    _write_runtime_fact(ws, 2, fp=_FP2, captured_at="2026-09-22T11:00:00Z")
    rots = ri.detect_rotations(ws)
    assert ("C-001", "config-decrypt-key") in rots
    r = rots[("C-001", "config-decrypt-key")]
    assert r["fingerprints"] == [_FP1, _FP2]
    # series is timestamp-ordered and carries (fp, captured_at) pairs
    assert [s["captured_at"] for s in r["series"]] == [
        "2026-09-22T10:00:00Z", "2026-09-22T11:00:00Z"]


def test_join_ignores_same_fp_twice_under_one_slot(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, fp=_FP1, captured_at="2026-09-22T10:00:00Z")
    _write_runtime_fact(ws, 2, fp=_FP1, captured_at="2026-09-22T11:00:00Z")
    assert ri.detect_rotations(ws) == {}


def test_join_ignores_two_different_slots(tmp_path):
    """Distinct slots are different subjects — never joined (reviewer attack
    a: fire ONLY on same-slot distinct-value)."""
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, slot="config-decrypt-key", fp=_FP1)
    _write_runtime_fact(ws, 2, slot="license-token", fp=_FP2)
    assert ri.detect_rotations(ws) == {}


def test_join_ignores_same_slot_across_different_claims(tmp_path):
    """The join key is (claim_id, subject_slot) — the same slot under two
    claims is two contexts, not one rotation."""
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, claim="C-001", fp=_FP1)
    _write_runtime_fact(ws, 2, claim="C-002", fp=_FP2)
    assert ri.detect_rotations(ws) == {}


# =====================================================================
# run(): fire once — event + hypothesis + note + convergence row
# =====================================================================

def test_run_fires_once_with_all_four_artifacts(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, fp=_FP1, captured_at="2026-09-22T10:00:00Z")
    _write_runtime_fact(ws, 2, fp=_FP2, captured_at="2026-09-22T11:00:00Z")

    report = ri.run(ws)
    assert len(report["fired"]) == 1
    fired = report["fired"][0]
    assert fired["claim_id"] == "C-001"
    assert fired["subject_slot"] == "config-decrypt-key"
    assert fired["distinct"] == 2

    # 1. the event (controlled vocabulary, fingerprint series in detail)
    evs = _rotation_events(ws)
    assert len(evs) == 1
    assert evs[0]["action"] == "runtime_value_rotation"
    assert evs[0]["claim"] == "C-001"
    detail = json.loads(evs[0]["detail"])
    assert detail["subject_slot"] == "config-decrypt-key"
    assert detail["distinct"] == 2
    assert [s["fp"] for s in detail["series"]] == [_FP1, _FP2]
    assert [s["captured_at"] for s in detail["series"]] == [
        "2026-09-22T10:00:00Z", "2026-09-22T11:00:00Z"]

    # 2. the hypothesis: open competitor against the static premise
    store = HypothesisStore(ws / "hypotheses")
    hyps = store.list_all()
    assert len(hyps) == 1
    h = hyps[0]
    assert h.claim_id == "C-001"
    assert h.status == "open"
    assert h.competitor_group.startswith("rotation-")
    assert _FP1 in h.body and _FP2 in h.body
    assert "2026-09-22T10:00:00Z" in h.body
    assert "2026-09-22T11:00:00Z" in h.body
    assert "static" in h.body.lower()  # the implicit premise is named
    assert fired["hypothesis_id"] == h.id

    # 3. the synthesis note: pending verification, series recorded
    notes = list((ws / "notes").glob("*.md"))
    assert len(notes) == 1
    note = notes[0].read_text(encoding="utf-8")
    assert "verify_status: pending" in note
    assert "claim_id: C-001" in note
    assert _FP1 in note and _FP2 in note
    assert fired["note"] == notes[0].name

    # 4. the convergence-ledger row (D wiring)
    rows = _conv_rows(ws)
    assert any(r.get("type") == "operator_action"
               and r.get("action") == "runtime_value_rotation"
               and r.get("claim_id") == "C-001" for r in rows)


def test_run_is_idempotent_on_same_fingerprint_set(tmp_path):
    """Acceptance: same slot, same fingerprint set -> no re-emit."""
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, fp=_FP1, captured_at="2026-09-22T10:00:00Z")
    _write_runtime_fact(ws, 2, fp=_FP2, captured_at="2026-09-22T11:00:00Z")
    assert len(ri.run(ws)["fired"]) == 1
    n_events = len(_rotation_events(ws))
    n_hyps = len(HypothesisStore(ws / "hypotheses").list_all())
    n_notes = len(list((ws / "notes").glob("*.md")))
    n_rows = len(_conv_rows(ws))

    report = ri.run(ws)
    assert report["fired"] == []
    assert len(report["skipped"]) == 1
    assert len(_rotation_events(ws)) == n_events
    assert len(HypothesisStore(ws / "hypotheses").list_all()) == n_hyps
    assert len(list((ws / "notes").glob("*.md"))) == n_notes
    assert len(_conv_rows(ws)) == n_rows


def test_sub_threshold_never_fires(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, fp=_FP1)
    report = ri.run(ws)
    assert report["fired"] == []
    assert _rotation_events(ws) == []
    assert list((ws / "hypotheses").glob("*.md")) == []


def test_fingerprint_set_growth_refires_without_dup_hypothesis(tmp_path):
    """A third distinct value IS new evidence: the event refires with the
    fuller series; the open hypothesis is not duplicated; the note is a
    superseding correction."""
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, fp=_FP1, captured_at="2026-09-22T10:00:00Z")
    _write_runtime_fact(ws, 2, fp=_FP2, captured_at="2026-09-22T11:00:00Z")
    ri.run(ws)
    _write_runtime_fact(ws, 3, fp=_FP3, captured_at="2026-09-22T12:00:00Z")
    report = ri.run(ws)
    assert len(report["fired"]) == 1

    evs = _rotation_events(ws)
    assert len(evs) == 2
    detail = json.loads(evs[-1]["detail"])
    assert detail["distinct"] == 3

    hyps = HypothesisStore(ws / "hypotheses").list_all()
    assert len(hyps) == 1  # never duplicated
    assert report["fired"][0]["hypothesis_id"] == hyps[0].id

    notes = sorted((ws / "notes").glob("*.md"))
    assert len(notes) == 2  # correction chain, not overwrite
    newer = notes[-1].read_text(encoding="utf-8")
    assert "supersedes:" in newer
    assert "verify_status: pending" in newer
    assert _FP3 in newer


# =====================================================================
# hygiene: raw value material reaches NO event/ledger/hypothesis/note
# =====================================================================

def test_no_raw_key_material_in_any_written_surface(tmp_path, monkeypatch):
    """The fact fixture carries the raw secret in its provenance log PATH
    only in the fact file itself; every surface the mechanism writes must
    contain fingerprints only."""
    ws = _mk_ws(tmp_path)
    raw = "RAWSECRET-00112233445566778899aabbccddeeff"
    # plant a fact whose BODY embeds raw material (a live fact may carry
    # it in reproduce/expected — facts are workspace carriers, not events);
    # the mechanism must never copy body text outward.
    _write_runtime_fact(ws, 1, fp=fingerprint(raw),
                        captured_at="2026-09-22T10:00:00Z")
    p1 = ws / "facts" / "F001-runtime-observation.md"
    p1.write_text(p1.read_text(encoding="utf-8")
                  + f"\nThe captured key was {raw}.\n", encoding="utf-8")
    _write_runtime_fact(ws, 2, fp=_FP2, captured_at="2026-09-22T11:00:00Z")

    ri.run(ws)

    surfaces = [log_path(ws)]
    conv = ws / ".convergence_ledger.jsonl"
    if conv.exists():
        surfaces.append(conv)
    surfaces += list((ws / "hypotheses").glob("*.md"))
    surfaces += list((ws / "notes").glob("*.md"))
    surfaces.append(ws / "runs" / ".rotation-induction.json")
    for s in surfaces:
        assert s.exists(), s
        assert raw not in s.read_text(encoding="utf-8", errors="replace"), (
            f"raw key material leaked into {s}")


# =====================================================================
# registration: registry + controlled vocabulary + cross-face twin
# =====================================================================

def test_mechanism_registered_and_registry_validates():
    entries, errors = mechanism_scheduler.load_registry()
    assert not errors, errors
    mine = [e for e in entries if e["name"] == "rotation_induction"]
    assert len(mine) == 1
    e = mine[0]
    assert e["channel"] == "tick"
    assert e["trigger"]["type"] == "tick"
    assert e["trigger"]["gate"] in mechanism_scheduler.GATES
    assert e["cost_class"] == "cheap"
    assert str(e.get("cockpit_signal") or "").strip()


def test_event_word_registered_in_emit_actions():
    assert "runtime_value_rotation" in event_taxonomy.EMIT_ACTIONS
    assert event_taxonomy.EMIT_ACTIONS == sorted(set(event_taxonomy.EMIT_ACTIONS))


def test_rotation_action_twin_pinned_across_faces():
    """convergence_health keeps a local literal (import-light face, the
    STALLED_REMEDY_MARKER pattern); the two must never drift."""
    assert convergence_health.ROTATION_ACTION == ri.ROTATION_ACTION


# =====================================================================
# D: convergence_health renders the rotation face
# =====================================================================

def _rot_row(claim: str = "C-001", ts: str = "2026-09-22T10:00:00Z") -> dict:
    return {"type": "operator_action", "action": ri.ROTATION_ACTION,
            "actor": "rotation_induction", "claim_id": claim,
            "reason": "config-decrypt-key: 2 distinct fps", "ts": ts,
            "schema": "convergence-ledger/2"}


def test_assess_surfaces_rotation_events():
    ledger = [
        {"ts": "2026-09-22T09:00:00Z", "open_count": 2,
         "open_ids": ["C-001", "C-002"], "facts_total": 5},
        _rot_row(),
        {"ts": "2026-09-22T10:00:00Z", "open_count": 2,
         "open_ids": ["C-001", "C-002"], "facts_total": 7},
        {"ts": "2026-09-22T11:00:00Z", "open_count": 2,
         "open_ids": ["C-001", "C-002"], "facts_total": 8},
    ]
    r = convergence_health.assess(ledger)
    assert r["rotation_events"]["count"] == 1
    assert r["rotation_events"]["claims"] == ["C-001"]


def test_assess_without_rotation_rows_keeps_prior_shape():
    ledger = [
        {"ts": "2026-09-22T09:00:00Z", "open_count": 2,
         "open_ids": ["C-001"], "facts_total": 5},
        {"ts": "2026-09-22T10:00:00Z", "open_count": 2,
         "open_ids": ["C-001"], "facts_total": 6},
        {"ts": "2026-09-22T11:00:00Z", "open_count": 2,
         "open_ids": ["C-001"], "facts_total": 7},
    ]
    r = convergence_health.assess(ledger)
    assert "rotation_events" not in r  # shape guard: absent when 0


def test_stalled_action_names_the_rotation_requirement():
    """The verdict face renders the value-divergence input: a STALLED action
    for a rotation-flagged claim points at the marker + reference card."""
    ledger = [
        {"ts": "2026-09-22T09:00:00Z", "open_count": 1,
         "open_ids": ["C-001"], "dispatched_ids": ["C-001"], "facts_total": 5},
        _rot_row(),
        {"ts": "2026-09-22T10:00:00Z", "open_count": 1,
         "open_ids": ["C-001"], "dispatched_ids": ["C-001"], "facts_total": 6},
        {"ts": "2026-09-22T11:00:00Z", "open_count": 1,
         "open_ids": ["C-001"], "dispatched_ids": ["C-001"], "facts_total": 7},
        {"ts": "2026-09-22T12:00:00Z", "open_count": 1,
         "open_ids": ["C-001"], "dispatched_ids": ["C-001"], "facts_total": 8},
        {"ts": "2026-09-22T13:00:00Z", "open_count": 1,
         "open_ids": ["C-001"], "dispatched_ids": ["C-001"], "facts_total": 9},
        {"ts": "2026-09-22T14:00:00Z", "open_count": 1,
         "open_ids": ["C-001"], "dispatched_ids": ["C-001"], "facts_total": 10},
    ]
    r = convergence_health.assess(ledger)
    assert r["verdict"] in ("STALLED", "SPINNING")
    assert "rotation-experiment:" in r["action"]
    assert "rotation-characterization" in r["action"]


def test_human_face_renders_rotation_line():
    ledger = [
        {"ts": "2026-09-22T09:00:00Z", "open_count": 2,
         "open_ids": ["C-001", "C-002"], "facts_total": 5},
        _rot_row(),
        {"ts": "2026-09-22T10:00:00Z", "open_count": 2,
         "open_ids": ["C-001", "C-002"], "facts_total": 7},
        {"ts": "2026-09-22T11:00:00Z", "open_count": 2,
         "open_ids": ["C-001", "C-002"], "facts_total": 8},
    ]
    human = convergence_health._human(convergence_health.assess(ledger))
    assert "rotation" in human.lower()


# =====================================================================
# CLI face
# =====================================================================

def test_cli_run_json_report(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_runtime_fact(ws, 1, fp=_FP1)
    _write_runtime_fact(ws, 2, fp=_FP2)
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "rotation_induction.py"), str(ws),
         "--json"],
        capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": str(SCRIPTS), "PATH": "/usr/bin:/bin",
             "PYTHONIOENCODING": "utf-8"})
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert len(out["fired"]) == 1


def test_cli_run_on_empty_workspace_is_clean(tmp_path):
    ws = tmp_path / "cold"
    ws.mkdir()
    (ws / "facts").mkdir()
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "rotation_induction.py"), str(ws),
         "--json"],
        capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": str(SCRIPTS), "PATH": "/usr/bin:/bin",
             "PYTHONIOENCODING": "utf-8"})
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["fired"] == []
