# -*- coding: utf-8 -*-
"""TDD tests — issue #460 Part A: historical-run feature mining.

Spec: openspec/changes/issue-460-feature-mining/specs/feature-mining/spec.md
Every test maps to a Requirement/Scenario there (names in comments).
The golden table + fixture root are the pinned regression truth.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import feature_mining  # noqa: E402  (the module under test)

FIXTURES = _HERE / "fixtures" / "feature-mining-460"
ROOT = FIXTURES / "root"
GOLDEN = FIXTURES / "golden" / "feature-table.jsonl"

RUN_A = "e2e-fix-211504-a"   # landed + timeout + unpaired; settled C-005
RUN_B = "e2e-fix-221504-b"   # timeout + blocked + rc-null; die/apkid present
RUN_C = "e2e-fix-231630-c"   # degraded: dangling ws


def mine_rows(out: Path, roots: list[Path] | None = None):
    """Mine the fixture (or given roots) into out; return parsed rows."""
    args = [str(r) for r in (roots or [ROOT])]
    summary = feature_mining.main([*args, "--out", str(out)])
    assert summary == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    return rows


def row_by_run(rows: list[dict], run_id: str) -> dict:
    return next(r for r in rows if r["run_id"] == run_id)


# ---------------------------------------------------------------------------
# Requirement: Feature-table row extraction anchored on run-state
# ---------------------------------------------------------------------------

class TestRowExtraction:
    def test_complete_run_mines_full_row(self, tmp_path):
        """Scenario: complete run mines a full row."""
        rows = mine_rows(tmp_path / "t.jsonl")
        a = row_by_run(rows, RUN_A)
        assert a["family"] == "release"
        assert a["task_id"] == "rust-apk-beacon-v1"
        assert a["schema"] == "feature-table/1"
        # features joined from ws + task_dir
        assert a["features"]["lane"] == "algorithm"
        assert a["features"]["target_kind"] == {
            "language": "rust/arm64-android", "entry_suffix": ".apk"}
        assert a["features"]["difficulty_factors"]["tier"] == "easy"
        assert len(a["outcomes"]) == 3

    def test_relative_pointers_resolve_against_root(self, tmp_path):
        """Scenario: relative pointers resolve against the mining root."""
        rows = mine_rows(tmp_path / "t.jsonl")
        b = row_by_run(rows, RUN_B)
        # ws read via the relative pointer: difficulty + probes joined
        assert b["features"]["difficulty_factors"]["tier"] == "hard"
        assert b["features"]["probe_outputs"]["die"]["usable"] is True

    def test_absolute_pointer_used_verbatim(self, tmp_path):
        """Absolute pointers resolve verbatim (live shape), never against
        the mining root — Requirement 1's second resolution arm. The
        pointer targets an EXISTING copy with distinct difficulty
        content, so a re-rooting regression (reading root/ws/e2e-ws-a
        instead) fails on content, not just on absence."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        outside = tmp_path / "outside-ws"
        shutil.copytree(copy / "ws" / "e2e-ws-a", outside)
        spec = outside / "task_spec.yaml"
        text = spec.read_text(encoding="utf-8").replace("tier: easy",
                                                        "tier: medium")
        spec.write_text(text, encoding="utf-8")
        state_path = copy / "runs" / "e2e" / RUN_A / "run-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["ws"] = str(outside)  # absolute, existing
        state_path.write_text(json.dumps(state, indent=2) + "\n",
                              encoding="utf-8")
        rows = mine_rows(tmp_path / "t.jsonl", [copy])
        a = row_by_run(rows, RUN_A)
        assert a["features"]["difficulty_factors"]["tier"] == "medium"

    def test_inputs_never_written(self, tmp_path):
        """Scenario: inputs are never written — including the warn-firing
        path (corrupt run-state) with CWD INSIDE the mining root, where
        kunglao_log's ledger face would have appended into the input
        (review finding 1: the miner's warns are stderr-only)."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        (copy / "runs" / "e2e" / RUN_C / "run-state.json").write_text(
            "{ not json", encoding="utf-8")

        def snapshot(root: Path) -> dict:
            return {
                str(p.relative_to(root)): (p.stat().st_mtime_ns,
                                           hashlib.sha256(p.read_bytes()).hexdigest())
                for p in sorted(root.rglob("*")) if p.is_file()}

        before = snapshot(copy)
        monkey = pytest.MonkeyPatch()
        with monkey.context() as m:
            m.chdir(copy)  # cwd walk-up would find copy/ (has runs/)
            out = tmp_path / "t.jsonl"
            rc = feature_mining.main([str(copy), "--out", str(out)])
            assert rc == 0
        assert snapshot(copy) == before


# ---------------------------------------------------------------------------
# Requirement: Instance signature hash over the features object
# ---------------------------------------------------------------------------

class TestSignatureHash:
    def test_same_task_two_runs_same_signature(self, tmp_path):
        """Scenario: same task, two runs, same signature."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        src = copy / "runs" / "e2e" / RUN_A
        clone = copy / "runs" / "e2e" / "e2e-fix-clone-a2"
        shutil.copytree(src, clone)
        # the clone gets its OWN workspace copy (identical features,
        # different outcomes stream)
        shutil.copytree(copy / "ws" / "e2e-ws-a", copy / "ws" / "e2e-ws-a2")
        state = json.loads((clone / "run-state.json").read_text(encoding="utf-8"))
        state["run_id"] = "e2e-fix-clone-a2"
        state["ws"] = "ws/e2e-ws-a2"
        (clone / "run-state.json").write_text(
            json.dumps(state, indent=2) + "\n", encoding="utf-8")
        # different outcomes: drop the last audit row (unpaired attempt)
        audit = (copy / "ws" / "e2e-ws-a2" / "runs" / "logs" / "e2e-audit.jsonl")
        lines = audit.read_text(encoding="utf-8").splitlines()
        audit.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

        rows = mine_rows(tmp_path / "t.jsonl", [copy])
        a = row_by_run(rows, RUN_A)
        a2 = row_by_run(rows, "e2e-fix-clone-a2")
        assert a["signature_hash"] == a2["signature_hash"]
        assert len(a["outcomes"]) == 3
        assert len(a2["outcomes"]) == 2

    def test_changed_features_change_the_hash(self, tmp_path):
        """Scenario: changed features change the hash."""
        rows = mine_rows(tmp_path / "t.jsonl")
        a = row_by_run(rows, RUN_A)
        b = row_by_run(rows, RUN_B)
        assert a["signature_hash"] != b["signature_hash"]
        # run B carries probe evidence run A lacks
        assert b["features"]["packer_flags"]["detected_packers"] == ["UPX"]
        assert a["features"]["packer_flags"]["detected_packers"] == []

    def test_hash_is_stable_canonical_digest(self):
        feats = {"lane": "algorithm", "project_type": "linux",
                 "target_kind": {"language": "python", "entry_suffix": ".py"},
                 "packer_flags": {}, "difficulty_factors": None,
                 "probe_outputs": {}}
        expect = hashlib.sha256(json.dumps(
            feats, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        assert feature_mining.signature_hash(feats) == expect


# ---------------------------------------------------------------------------
# Requirement: Per-act outcomes joined from the audit stream
# ---------------------------------------------------------------------------

class TestOutcomes:
    def test_timeout_dispatch(self, tmp_path):
        """Scenario: timeout dispatch."""
        rows = mine_rows(tmp_path / "t.jsonl")
        b = row_by_run(rows, RUN_B)
        assert b["outcomes"][0]["act_result"] == "timeout"

    def test_blocked_dispatch(self, tmp_path):
        rows = mine_rows(tmp_path / "t.jsonl")
        b = row_by_run(rows, RUN_B)
        assert b["outcomes"][1]["act_result"] == "blocked"

    def test_rc_null_result_is_unknown_not_blocked(self, tmp_path):
        """Scenario: rc-null result row is unknown, not blocked."""
        rows = mine_rows(tmp_path / "t.jsonl")
        b = row_by_run(rows, RUN_B)
        assert b["outcomes"][2]["act_result"] == "unknown"

    def test_fifo_pairing_interleaved_stream(self, tmp_path):
        """H2 pairing: attempt C-005 pairs with the EARLIEST LATER C-005
        result even though a C-004 result sits between them."""
        rows = mine_rows(tmp_path / "t.jsonl")
        a = row_by_run(rows, RUN_A)
        got = [(o["claim"], o["act_result"]) for o in a["outcomes"]]
        assert got == [("C-005", "timeout"), ("C-004", "landed"),
                       ("C-005", "unknown")]

    def test_envelope_family_wins_over_register_source(self, tmp_path):
        """Scenario: envelope family wins over register source."""
        rows = mine_rows(tmp_path / "t.jsonl")
        a = row_by_run(rows, RUN_A)
        c004 = next(o for o in a["outcomes"] if o["claim"] == "C-004")
        assert c004["method_family_or_claim_source"] == "static-decompile"
        # the register says static_re for C-004 — envelope wins
        c005 = a["outcomes"][0]
        assert c005["method_family_or_claim_source"] == "synthesis"

    def test_ledger_settlement_feeds_credit(self, tmp_path):
        """Scenario: ledger settlement feeds credit (dispatched claim)."""
        rows = mine_rows(tmp_path / "t.jsonl")
        a = row_by_run(rows, RUN_A)
        c005 = [o for o in a["outcomes"] if o["claim"] == "C-005"]
        assert all(o["settled"] is True and o["credit"] == 0.0 for o in c005)
        c004 = next(o for o in a["outcomes"] if o["claim"] == "C-004")
        assert c004["settled"] is False and c004["credit"] is None

    def test_unpaired_attempt_stays_unknown(self, tmp_path):
        """Scenario: unpaired attempt stays unknown."""
        rows = mine_rows(tmp_path / "t.jsonl")
        a = row_by_run(rows, RUN_A)
        assert a["outcomes"][2]["act_result"] == "unknown"

    def test_no_attribution_material_stays_null(self, tmp_path):
        """Scenario: no attribution material stays null."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        (copy / "ws" / "e2e-ws-b" / "claim-register.yaml").write_text(
            "claims: [ {{ broken", encoding="utf-8")
        rows = mine_rows(tmp_path / "t.jsonl", [copy])
        b = row_by_run(rows, RUN_B)
        assert all(o["method_family_or_claim_source"] is None
                   for o in b["outcomes"])


# ---------------------------------------------------------------------------
# Requirement: Deterministic byte-identical emission
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_byte_identical_remine_and_golden(self, tmp_path):
        """Scenario: byte-identical remine (+ committed golden pin)."""
        out1, out2 = tmp_path / "t1.jsonl", tmp_path / "t2.jsonl"
        mine_rows(out1)
        mine_rows(out2)
        assert out1.read_bytes() == out2.read_bytes()
        assert out1.read_bytes() == GOLDEN.read_bytes()

    def test_root_order_and_duplicates_do_not_change_bytes(self, tmp_path):
        """Scenario: root order does not change bytes."""
        copy = tmp_path / "root2"
        shutil.copytree(ROOT, copy)
        one = tmp_path / "one.jsonl"
        mine_rows(one, [ROOT, copy])
        two = tmp_path / "two.jsonl"
        mine_rows(two, [copy, ROOT, ROOT])
        assert one.read_bytes() == two.read_bytes()
        # same run_id in two roots: both rows ship (6 rows, 3 duplicated ids)
        rows = [json.loads(l) for l in one.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 6

    def test_sorted_row_order(self, tmp_path):
        rows = mine_rows(tmp_path / "t.jsonl")
        keys = [(r["family"], r["task_id"], r["run_id"]) for r in rows]
        assert keys == sorted(keys)
        assert keys[0][0] == "chain"          # chain < release
        assert keys[1][1] < keys[2][1]        # mod-crypto < rust-apk

    def test_no_wallclock_in_rows(self, tmp_path):
        rows = mine_rows(tmp_path / "t.jsonl")
        assert all("mined_at" not in r and "ts" not in r for r in rows)


# ---------------------------------------------------------------------------
# Requirement: Malformed-source tolerance
# ---------------------------------------------------------------------------

class TestTolerance:
    def test_corrupt_run_state_skips_one_run(self, tmp_path):
        """Scenario: corrupt run-state skips one run."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        (copy / "runs" / "e2e" / RUN_C / "run-state.json").write_text(
            "{ not json", encoding="utf-8")
        out = tmp_path / "t.jsonl"
        rc = feature_mining.main([str(copy), "--out", str(out)])
        assert rc == 0
        rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert {r["run_id"] for r in rows} == {RUN_A, RUN_B}

    def test_undecodable_run_state_skips_one_run(self, tmp_path):
        """#438 lesson: decode errors count as unparseable."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        (copy / "runs" / "e2e" / RUN_C / "run-state.json").write_bytes(
            b"\xff\xfe\x00broken")
        out = tmp_path / "t.jsonl"
        rc = feature_mining.main([str(copy), "--out", str(out)])
        assert rc == 0
        rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 2

    def test_missing_ws_degrades_features(self, tmp_path):
        """Scenario: missing workspace degrades features."""
        rows = mine_rows(tmp_path / "t.jsonl")
        c = row_by_run(rows, RUN_C)
        assert c["features"]["lane"] == "algorithm"      # from run-state
        assert c["features"]["project_type"] == "linux"
        assert c["features"]["target_kind"]["entry_suffix"] == ".py"  # task_dir joined
        assert c["features"]["difficulty_factors"] is None
        assert c["features"]["probe_outputs"]["die"]["prescan_state"] is None
        assert c["outcomes"] == []

    def test_non_object_evidence_docs_degrade(self, tmp_path):
        """Malformed joined sources: valid JSON of the wrong shape degrades
        to usable=false, never crashes the run."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        ev = copy / "ws" / "e2e-ws-b" / "evidence"
        (ev / "die.json").write_text("[1, 2]", encoding="utf-8")
        (ev / "apkid.json").write_text('"junk"', encoding="utf-8")
        rows = mine_rows(tmp_path / "t.jsonl", [copy])
        b = row_by_run(rows, RUN_B)
        assert b["features"]["probe_outputs"]["die"]["usable"] is False
        assert b["features"]["probe_outputs"]["apkid"]["usable"] is False
        assert b["features"]["packer_flags"]["detected_packers"] == []

    def test_malformed_evidence_values_degrade(self, tmp_path):
        """Review finding 3: mixed-type packer lists, non-numeric entropy,
        scalar families entries — every one degrades, none aborts the
        table (the tolerance requirement's SHALL)."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        ev = copy / "ws" / "e2e-ws-b" / "evidence"
        die = json.loads((ev / "die.json").read_text(encoding="utf-8"))
        die["derived"]["section_table"] = [
            {"name": ".text", "entropy": "high"},      # non-numeric
            {"name": ".rodata", "entropy": 6.1},
        ]
        (ev / "die.json").write_text(json.dumps(die), encoding="utf-8")
        apkid = json.loads((ev / "apkid.json").read_text(encoding="utf-8"))
        apkid["summary"]["packer"] = ["UPX", 3]        # mixed-type list
        (ev / "apkid.json").write_text(json.dumps(apkid), encoding="utf-8")
        spec = (copy / "ws" / "e2e-ws-b" / "task_spec.yaml")
        text = spec.read_text(encoding="utf-8")
        text = text.replace(
            "    packing:\n      active: true\n      score: 1.0",
            "    packing: scalar-not-mapping")
        spec.write_text(text, encoding="utf-8")
        rows = mine_rows(tmp_path / "t.jsonl", [copy])
        b = row_by_run(rows, RUN_B)
        assert b["features"]["probe_outputs"]["die"]["entropy_max"] == 6.1
        assert b["features"]["packer_flags"]["detected_packers"] == ["3", "UPX"]
        assert b["features"]["difficulty_factors"]["families"]["packing"] is False

    def test_hostile_claim_ids_never_crash(self, tmp_path):
        """Review finding 5: null-byte / path-separator claims in the
        audit stream — outcome still emits, no filesystem read."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        audit = copy / "ws" / "e2e-ws-a" / "runs" / "logs" / "e2e-audit.jsonl"
        rows_txt = audit.read_text(encoding="utf-8").splitlines()
        hostile = json.dumps({
            "action": "dispatch_attempt", "actor": "orchestrator",
            "arm": None, "artifact": None, "channel": "local",
            "claim": "../escape\u0000x", "detail": "{}",
            "duration_ms": None, "epoch": 0, "exit": None,
            "hypothesis_ref": None, "matched_rule": None,
            "null_reasons": {}, "tool": None, "trace_id": None,
            "ts": "2026-09-29T06:00:00Z", "version": "fixture-sha-0001"})
        audit.write_text("\n".join([*rows_txt, hostile]) + "\n",
                         encoding="utf-8")
        rows = mine_rows(tmp_path / "t.jsonl", [copy])
        a = row_by_run(rows, RUN_A)
        extra = [o for o in a["outcomes"] if o["claim"] == "../escape\u0000x"]
        assert len(extra) == 1
        assert extra[0]["act_result"] == "unknown"
        assert extra[0]["method_family_or_claim_source"] is None

    def test_incomplete_run_state_skips_on_shape(self, tmp_path):
        """Review finding 4: a parseable run-state whose row fails
        feature-table/1 (identity absent) is skipped — the miner never
        ships a row its own validator rejects."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        state_path = copy / "runs" / "e2e" / RUN_C / "run-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        del state["family"], state["unit"]
        state_path.write_text(json.dumps(state, indent=2) + "\n",
                              encoding="utf-8")
        out = tmp_path / "t.jsonl"
        rc = feature_mining.main([str(copy), "--out", str(out)])
        assert rc == 0
        rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert {r["run_id"] for r in rows} == {RUN_A, RUN_B}
        assert all(feature_mining.validate_row(r) == [] for r in rows)

    def test_settlement_join_is_kind_scoped(self, tmp_path):
        """Review finding 2: a self_distill settlement anchored at the
        same string is NOT the claim's task settlement."""
        copy = tmp_path / "root"
        shutil.copytree(ROOT, copy)
        ledger = copy / "ws" / "e2e-ws-b" / "runs" / "rollout-ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps({
            "schema": "rollout-ledger/1",
            "rollout_id": "self_distill/C-005", "kind": "self_distill",
            "anchor": "C-005", "ts": "2026-09-29T15:00:00Z",
            "signals": [], "reward": 1.0,
            "settlement": {"reward": 1.0, "band": "HELPED",
                           "rule_id": "self_distill/helped",
                           "evidence_refs": [], "settled_ts":
                           "2026-09-29T15:00:00Z"}}) + "\n", encoding="utf-8")
        rows = mine_rows(tmp_path / "t.jsonl", [copy])
        b = row_by_run(rows, RUN_B)
        assert all(o["settled"] is False and o["credit"] is None
                   for o in b["outcomes"])

    def test_summary_counts(self, tmp_path, capsys):
        out = tmp_path / "t.jsonl"
        rc = feature_mining.main([str(ROOT), "--out", str(out)])
        assert rc == 0
        summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert summary == {"roots": 1, "runs": 3, "rows": 3, "skipped": 0}


# ---------------------------------------------------------------------------
# Requirement: Schema-validated rows
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_fixture_rows_validate(self, tmp_path):
        """Scenario: fixture rows validate."""
        rows = mine_rows(tmp_path / "t.jsonl")
        assert all(feature_mining.validate_row(r) == [] for r in rows)

    def test_junk_signature_hash_rejected(self):
        """Scenario: junk row is rejected (field-precise)."""
        rows = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines()]
        bad = dict(rows[0], signature_hash="xyz")
        errs = feature_mining.validate_row(bad)
        assert errs and "signature_hash" in errs[0]

    def test_junk_act_result_rejected(self):
        rows = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines()]
        a = row_by_run(rows, RUN_A)
        bad = json.loads(json.dumps(a))
        bad["outcomes"][0]["act_result"] = "exploded"
        errs = feature_mining.validate_row(bad)
        assert errs and "act_result" in errs[0]

    def test_missing_feature_key_rejected(self):
        rows = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines()]
        bad = json.loads(json.dumps(rows[0]))
        del bad["features"]["lane"]
        errs = feature_mining.validate_row(bad)
        assert any("lane" in e for e in errs)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-x", "-q"])
