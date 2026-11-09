# -*- coding: utf-8 -*-
"""tests/test_schema_cutover_1004.py — issue-1004 R3: the schema cutover.

The ledger compat window is DELETED: the consolidated core reads ONLY
the four consolidated files. The pins:

  1. Introspection  the module carries no LEGACY / SWITCHED /
                    DEFAULT_MIGRATION / ARCHIVE_DIR_REL attribute and
                    read() takes no include_legacy parameter; migrate()
                    takes its source list explicitly (the migration
                    registry lives in the R4 CLI surface,
                    scripts/consolidate_ledgers.py).
  2. Family-only    read() returns exactly the consolidated file's rows:
                    a legacy rel on disk leaks NOTHING into any read
                    (filtered or not, any family).
  3. Liveness       all four families report from the consolidated files
                    only; every registered schema reports a count (a
                    dead schema reads 0, never silently absent); rows
                    still sitting in a legacy rel add no bucket.
  4. Registration   REGISTERED covers all four families including the
                    moved writers' stamps — the consolidated-file
                    liveness of every series that predates the
                    consolidation survives the cutover.
  5. Repo scan      no production .py (scripts/ + hooks/, excluding the
                    R4 CLI surface scripts/consolidate_ledgers.py) names
                    any of the 15 legacy rel literals.
  6. Readers        the narrowed cost/signal readers (episode_settle,
                    disposition_measure, disposition_reward) ride the
                    plain family read — no include_legacy call site
                    survives, and a legacy cost face on disk never
                    enters a spend window.
  7. The exception  rlvr.disposition.legacy_disposition stays importable
                    and live (the documented session-ladder bridge —
                    NOT part of this retirement).
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, ROOT / "tests", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import rlvr.consolidated_ledger as cl  # noqa: E402
import rlvr.disposition_measure as disposition_measure  # noqa: E402
import rlvr.disposition_reward as disposition_reward  # noqa: E402
import rlvr.episode_settle as episode_settle  # noqa: E402

TS = "2026-11-09T00:00:00Z"

#: the 15 legacy rels the compat window served (issue-1004 R3 deletes
#: the window; the R4 retire CLI deletes the files)
LEGACY_RELS = (
    # experience
    "runs/transitions.jsonl", "runs/q-cell-log.jsonl",
    "runs/step-ledger.jsonl", "runs/evidence-credit.jsonl",
    # settlement
    "runs/rollout-ledger.jsonl", "runs/attributed-waste.jsonl",
    "cost_events.jsonl",
    # telemetry
    "runs/interventions.jsonl", "runs/predictions.jsonl",
    "runs/situation-stream.jsonl", "runs/strategy-log.jsonl",
    # knowledge
    "posterior-store.jsonl", "marl-negative.jsonl",
    "runs/feature-table.jsonl", "runs/posterior-store.jsonl",
)

#: the moved writers' stamps — the series that predate the consolidation
#: and now live (only) inside the family files
MOVED_WRITER_STAMPS = {
    "experience": ("transition/1", "q-cell-obs/1", "step-record/1",
                   "step-record/2", "evidence-item/1",
                   "credit-amendment/1"),
    "settlement": ("rollout-ledger/1", "attributed-waste/1",
                   "cost-event/1", "settlement-wire/1"),
    "telemetry": ("intervention/1", "prediction-ledger/1",
                  "situation/1", "strategy-log/1"),
    "knowledge": ("posterior-store/1", "marl-negative/1",
                  "feature-table/1"),
}

#: the live family-writer stamps the fix round registered (a dead
#: writer must read 0, never absent — REGISTERED is the sole liveness
#: source since the cutover)
LIVE_WRITER_STAMPS = {
    "experience": ("censored/1", "q-cell-action/1", "q-cell-result/1"),
    "settlement": ("distill-rollout/1",),
    "telemetry": ("probe-price/1",),
}

#: the sanctioned legacy-face surfaces excluded from the repo scan
#: (the R4 retire CLI owns the migration source list until it retires it)
SANCTIONED_SURFACES = ("scripts/consolidate_ledgers.py",)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def _seed(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")


# ------------------------------------------------ 1. introspection

class TestCutoverIntrospection:
    def test_the_compat_names_are_gone_from_the_module(self):
        for name in ("LEGACY", "SWITCHED", "DEFAULT_MIGRATION",
                     "ARCHIVE_DIR_REL"):
            assert not hasattr(cl, name), name

    def test_read_takes_no_legacy_parameter(self):
        assert "include_legacy" not in \
            inspect.signature(cl.read).parameters

    def test_migrate_takes_an_explicit_source_list(self):
        params = inspect.signature(cl.migrate).parameters
        assert "sources" in params, "migrate lost its source list"
        p = params["sources"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
        assert p.default is inspect.Parameter.empty

    def test_the_r4_cli_carries_the_migration_source_list(self):
        import consolidate_ledgers as cli  # noqa: PLC0415 — scripts on path
        registry = getattr(cli, "LEGACY_SOURCES", None)
        assert isinstance(registry, dict)
        assert set(registry) == set(cl.FAMILIES)
        rels = [rel for rels in registry.values() for rel in rels]
        assert sorted(rels) == sorted(LEGACY_RELS)

    def test_liveness_reads_no_legacy_flag(self):
        src = inspect.getsource(cl.liveness)
        assert "include_legacy" not in src


# ------------------------------------------------ 2. family-only reads

class TestFamilyOnlyReads:
    def test_a_legacy_experience_rel_leaks_nothing(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        _seed(ws / "runs" / "transitions.jsonl",
              [{"ts": TS, "dispatch_id": "C-1"}])  # unstamped archive row
        _seed(ws / "runs" / "q-cell-log.jsonl",
              [{"schema": "q-cell-obs/1", "ts": TS}])
        live = {"schema": "transition/1", "ts": TS, "dispatch_id": "C-2"}
        assert cl.append(ws, "experience", live) is True
        assert cl.read(ws, "experience",
                       schema_prefix="transition") == [live]
        assert cl.read(ws, "experience",
                       schema_prefix="q-cell-obs") == []
        assert cl.read(ws, "experience") == [live]

    def test_knowledge_rels_leak_nothing(self, tmp_path, monkeypatch):
        root = tmp_path / "root"
        root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(cl.STORE_ENV, str(root))
        ws = _ws(tmp_path)
        _seed(root / "posterior-store.jsonl",
              [{"schema": "posterior-store/1", "ts": TS,
                "workspace_id": "old"}])
        _seed(root / "marl-negative.jsonl",
              [{"schema": "marl-negative/1", "ts": TS,
                "method_family": "old"}])
        _seed(ws / "runs" / "posterior-store.jsonl",
              [{"schema": "posterior-store/1", "ts": TS,
                "workspace_id": "ws-local"}])
        live = {"schema": "posterior-store/1", "ts": TS,
                "workspace_id": "ws"}
        assert cl.append(ws, "knowledge", live) is True
        assert cl.read(ws, "knowledge",
                       schema_prefix="posterior-store") == [live]
        assert cl.read(ws, "knowledge",
                       schema_prefix="marl-negative") == []

    def test_settlement_and_telemetry_rels_leak_nothing(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        _seed(ws / "runs" / "rollout-ledger.jsonl",
              [{"schema": "rollout-ledger/1", "ts": TS}])
        _seed(ws / "runs" / "strategy-log.jsonl",
              [{"ts": TS, "event": "dispatch", "claim": "C-1"}])
        live = {"schema": "cost-event/1", "ts": TS, "amount": 1.0}
        assert cl.append(ws, "settlement", live) is True
        assert cl.read(ws, "settlement",
                       schema_prefix="rollout-ledger") == []
        assert cl.read(ws, "settlement",
                       schema_prefix="cost-event") == [live]
        assert cl.read(ws, "telemetry",
                       schema_prefix="strategy-log") == []


# ------------------------------------------------ 3. liveness

class TestLivenessFamilyOnly:
    def test_all_four_families_report_stamps_on_a_bare_workspace(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        live = cl.liveness(_ws(tmp_path))
        for family in cl.FAMILIES:
            keys = [k for k in live if k.startswith(f"{family}:")]
            assert keys, f"family {family} reports no stamps"
        # a registered schema reads 0, never silently absent
        assert live["knowledge:posterior-store/1"] == 0
        assert live["settlement:rollout-ledger/1"] == 0

    def test_a_legacy_rel_on_disk_adds_no_bucket(self, tmp_path,
                                                 monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        _seed(ws / "runs" / "transitions.jsonl",
              [{"ts": TS, "dispatch_id": "C-1"}])  # unstamped
        _seed(ws / "runs" / "q-cell-log.jsonl",
              [{"schema": "q-cell-obs/1", "ts": TS}])
        live = cl.liveness(ws)
        assert "experience:(no-schema)" not in live
        assert live["experience:q-cell-obs/1"] == 0

    def test_family_rows_count_under_their_stamps(self, tmp_path,
                                                  monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        assert cl.append(ws, "experience",
                         {"schema": "step-record/2", "ts": TS}) is True
        assert cl.append(ws, "experience",
                         {"schema": "step-record/2", "ts": TS}) is True
        # a foreign stamp still shows (attribution beats the registry)
        assert cl.append(ws, "experience",
                         {"schema": "claim-ref/9", "ts": TS}) is True
        live = cl.liveness(ws)
        assert live["experience:step-record/2"] == 2
        assert live["experience:claim-ref/9"] == 1


# ------------------------------------------------ 4. registration

class TestRegistration:
    def test_registered_covers_every_family(self):
        assert set(cl.REGISTERED) == set(cl.FAMILIES)

    def test_the_moved_writers_stamps_stay_registered(self):
        for family, stamps in MOVED_WRITER_STAMPS.items():
            for stamp in stamps:
                assert stamp in cl.REGISTERED[family], (family, stamp)

    def test_the_live_writer_stamps_are_registered(self):
        """The fix-round five: registered so a dead writer reads 0,
        never absent (REGISTERED is the sole liveness source since the
        cutover)."""
        for family, stamps in LIVE_WRITER_STAMPS.items():
            for stamp in stamps:
                assert stamp in cl.REGISTERED[family], (family, stamp)

    def test_the_live_writer_stamps_pre_seed_liveness_at_zero(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        live = cl.liveness(_ws(tmp_path))
        for family, stamps in LIVE_WRITER_STAMPS.items():
            for stamp in stamps:
                assert live[f"{family}:{stamp}"] == 0, (family, stamp)

    def test_a_migrated_row_counts_under_its_stamp(self, tmp_path,
                                                   monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        assert cl.append(ws, "settlement",
                         {"schema": "rollout-ledger/1", "ts": TS}) is True
        assert cl.liveness(ws)["settlement:rollout-ledger/1"] == 1


# ------------------------------------------------ 5. repo scan

def _production_sources() -> list[Path]:
    out = [p for base in (SCRIPTS, ROOT / "hooks")
           for p in sorted(base.rglob("*.py"))]
    return [p for p in out
            if p.name != "conftest.py"
            and not any(s in p.as_posix() for s in SANCTIONED_SURFACES)]


class TestNoLegacyRelLiterals:
    def test_no_production_source_names_a_legacy_rel(self):
        offenders: list[str] = []
        for path in _production_sources():
            text = path.read_text(encoding="utf-8", errors="replace")
            for rel in LEGACY_RELS:
                if rel in text:
                    offenders.append(
                        f"{path.relative_to(ROOT)}: {rel}")
        assert not offenders, (
            "production sources must not name a legacy rel literal "
            "(issue-1004 R3 cut the window over; the R4 CLI surface is "
            "the only sanctioned naming site):\n" + "\n".join(offenders))

    def test_feature_mining_carries_no_retired_rel_constant(self):
        """The miner's retired rel is dead as a CONSTANT too — the
        split-literal Path form would evade the flat string scan."""
        src = (SCRIPTS / "feature_mining.py").read_text(
            encoding="utf-8")
        assert "feature-table.jsonl" not in src


# ------------------------------------------------ 6. the narrowed readers

class TestNarrowedReaders:
    def test_no_narrowed_reader_names_the_legacy_parameter(self):
        for rel in ("rlvr/episode_settle.py", "rlvr/disposition_measure.py",
                    "rlvr/disposition_reward.py"):
            src = (SCRIPTS / rel).read_text(encoding="utf-8")
            assert "include_legacy" not in src, rel

    def test_a_legacy_cost_face_never_enters_the_spend_windows(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        for rel in ("cost_events.jsonl", "runs/cost_events.jsonl"):
            _seed(ws / rel, [{"ts": TS, "amount": 9.0,
                              "source": "legacy"}])
        assert cl.append(ws, "settlement",
                         {"schema": "cost-event/1", "ts": TS,
                          "amount": 2.0, "source": "live"}) is True
        total, counts = episode_settle._spend_window(ws)
        assert total == 2.0
        assert set(counts) == {"runs/settlement.jsonl"}
        cost = disposition_measure._cost_workspace(ws)
        assert cost["amount"] == 2.0
        assert cost["files"] == ["runs/settlement.jsonl"]

    def test_disposition_signal_dedupe_reads_the_family_only(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(cl.STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        signal = {"schema": disposition_reward.SIGNAL_SCHEMA, "ts": TS,
                  "episode_id": "e1", "claim": "C-1"}
        assert disposition_reward._existing_signal(ws, signal) is False
        assert cl.append(ws, "telemetry", signal) is True
        assert disposition_reward._existing_signal(ws, signal) is True


# ------------------------------------------------ 7. the window sweep

class TestRevocationTransitiveOverMigration:
    def test_revoke_then_migrate_never_resurrects_a_revoked_row(
            self, tmp_path, monkeypatch):
        """The R3→R4 window: a revoke must stay transitive over
        everything migration can resurrect — a row revoked out of the
        pre-move file must not ride the R4 append back into the live
        family read."""
        from rlvr import crystallize as crystallize_mod  # noqa: PLC0415
        root = tmp_path / "root"
        root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(cl.STORE_ENV, str(root))
        ws = _ws(tmp_path)
        _seed(root / "marl-negative.jsonl", [
            {"schema": "marl-negative/1", "ts": TS,
             "claim_ref": "C-9", "method_family": "old",
             "fails": 1},
            {"schema": "marl-negative/1", "ts": TS,
             "claim_ref": "C-keep", "method_family": "keep",
             "fails": 2}])
        out = crystallize_mod.revoke_claim(ws, "C-9")
        assert out["negatives_removed"] == 1
        # the revoked row is gone from the PRE-MOVE file; the survivor
        # stays
        left = [json.loads(ln)
                for ln in (root / "marl-negative.jsonl")
                .read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert [r["claim_ref"] for r in left] == ["C-keep"]
        # migration appends what is left — the revoked claim NEVER
        # re-enters the family read
        import consolidate_ledgers as cli  # noqa: PLC0415 — the registry
        report = cl.migrate(ws, sources=cli.LEGACY_SOURCES)
        assert report["knowledge"]["marl-negative.jsonl"]["status"] \
            == "migrated"
        rows = cl.read(ws, "knowledge", schema_prefix="marl-negative")
        assert [r["claim_ref"] for r in rows] == ["C-keep"]


# ------------------------------------------------ 8. the exception

class TestDispositionBridgeException:
    def test_legacy_disposition_stays_importable_and_live(self):
        from rlvr import disposition as disposition_mod  # noqa: PLC0415
        fn = disposition_mod.legacy_disposition
        assert callable(fn)
        assert fn("terminal", True) == "SOLVED"
        assert fn("terminal", False) == "FAILED"
        assert fn("censored_env", True) == "CENSORED_ENV"
        assert fn("agent_death", False) == "FAILED"
