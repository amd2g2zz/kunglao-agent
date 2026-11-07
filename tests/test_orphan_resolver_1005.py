# -*- coding: utf-8 -*-
"""tests/test_orphan_resolver_1005.py — the orphan launch-sweep resolver.

issue-1005 S7: a launch stash without a transition row must be RESOLVED
(settled or refused with a reason), not left as an orphan. The end-of-run
sweep (``incremental_reward.sweep_orphan_launches``, issue-654 1-F1) only
warns; ``rlvr.orphan_resolver.resolve`` consumes the sweep's return value
at the close path and finishes each orphan:

  - ONE ``orphan-resolution/1`` audit row in the telemetry family citing
    the stash path + sha256;
  - classification from stash content through the EXISTING disposition
    vocabulary (``rlvr.disposition``): real attempt evidence inside ->
    ATTEMPTED_EXHAUSTED; no attempts (writer-crash shape) -> INFRA;
  - QUARANTINE by explicit move to ``runs/orphan-archive/<name>.json``
    (never ``runs/archive/`` -- that name is scheduled for deletion by
    the schema-cutover slice; never unlink -- user evidence is never
    deleted);
  - refused path: a claim whose register status is not terminal keeps
    its stash (a refused-with-reason row only);
  - per-stash cage: one corrupt stash is ONE warn and is skipped; the
    others still resolve;
  - fail-open: a broken workspace resolves nothing and never raises into
    the caller.

All fixtures here are SYNTHETIC (privacy rule: no real workspace data).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kunglao_log  # noqa: E402
from _factories import write_claims_register  # noqa: E402
import rlvr.consolidated_ledger as consolidated_ledger  # noqa: E402
import rlvr.disposition as disposition  # noqa: E402
import rlvr.incremental_reward as incremental_reward  # noqa: E402
import rlvr.orphan_resolver as orphan_resolver  # noqa: E402

RESOLVER_OP = "rlvr.orphan_resolver"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _resolution_rows(ws: Path) -> list[dict]:
    return consolidated_ledger.read(
        ws, "telemetry", schema_prefix="orphan-resolution")


def _warn_recorder(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        kunglao_log, "warn",
        lambda op, reason, **kw: calls.append((str(op), str(reason))))
    return calls


def _resolver_warns(calls: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [c for c in calls if c[0].startswith(RESOLVER_OP)]


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _writer_crash_stash(ws: Path, claim: str) -> Path:
    """A parseable stash doc with NO attempt evidence -- the writer-crash
    shape (schema + claim ride, but the launch never completed its
    record: no attempt_id, no action key)."""
    p = ws / "runs" / f"dispatch-launch-{claim}.json"
    p.write_text(json.dumps({
        "schema": "dispatch-launch/1",
        "ts": "2026-11-08T00:00:00Z",
        "claim": claim,
        "action_type": "dispatch",
    }), encoding="utf-8")
    return p


# ------------------------------------------------------------- resolve

def test_attempted_orphan_resolves_quarantines_one_row(tmp_path,
                                                       monkeypatch):
    """A real launch stash with no transitions row: ONE resolution row
    citing the stash path + sha256, disposition from the EXISTING
    vocabulary, then the stash is quarantine-MOVED to
    runs/orphan-archive/<name>.json (bytes intact, never deleted)."""
    ws = _ws(tmp_path)
    doc = incremental_reward.record_launch(ws, "C-101", "strings-first")
    assert doc is not None
    stash = ws / "runs" / "dispatch-launch-C-101.json"
    pre_sha = _sha256_of(stash)
    calls = _warn_recorder(monkeypatch)

    orphans = incremental_reward.sweep_orphan_launches(ws)
    assert len(orphans) == 1
    summary = orphan_resolver.resolve(ws, orphans)

    assert summary["resolved"] == 1
    # quarantined: gone from runs/, present under runs/orphan-archive/
    archive = ws / "runs" / "orphan-archive" / "dispatch-launch-C-101.json"
    assert not stash.exists()
    assert archive.is_file()
    assert _sha256_of(archive) == pre_sha  # a MOVE -- bytes intact
    # exactly ONE resolution row, citing path + sha256
    rows = _resolution_rows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "orphan-resolution/1"
    assert row["claim"] == "C-101"
    assert row["action_type"] == "dispatch"
    assert row["refused"] is False
    # the disposition word rides the EXISTING vocabulary
    assert row["disposition"] == "ATTEMPTED_EXHAUSTED"
    assert row["disposition"] in disposition.DISPOSITIONS
    assert "runs/dispatch-launch-C-101.json" in row["evidence_refs"]
    assert row["stash_sha256"] == pre_sha
    assert row["archived_to"] == \
        "runs/orphan-archive/dispatch-launch-C-101.json"
    # the resolver itself stays silent on the clean path
    assert _resolver_warns(calls) == []


def test_writer_crash_orphan_classifies_infra(tmp_path):
    """A parseable stash with no attempt evidence is the writer-crash
    shape -> INFRA (still resolved + quarantined: the stash names no
    live settle that could ever fire)."""
    ws = _ws(tmp_path)
    stash = _writer_crash_stash(ws, "C-102")
    orphans = incremental_reward.sweep_orphan_launches(ws)
    summary = orphan_resolver.resolve(ws, orphans)
    assert summary["resolved"] == 1
    rows = _resolution_rows(ws)
    assert len(rows) == 1
    assert rows[0]["disposition"] == "INFRA"
    assert rows[0]["disposition"] in disposition.DISPOSITIONS
    assert rows[0]["refused"] is False
    assert not stash.exists()
    assert (ws / "runs" / "orphan-archive"
            / "dispatch-launch-C-102.json").is_file()


def test_legacy_shape_stash_classifies_attempted(tmp_path):
    """Review MEDIUM-2 pin: a pre-1-F2 LEGACY stash (a real action key,
    NO attempt_id — a shape the settle face still honors) is a real
    attempt -> ATTEMPTED_EXHAUSTED, never the false INFRA."""
    ws = _ws(tmp_path)
    stash = ws / "runs" / "dispatch-launch-C-112.json"
    stash.write_text(json.dumps({
        "schema": "dispatch-launch/1",
        "ts": "2026-11-08T00:00:00Z",
        "claim": "C-112",
        "a": "strings-first",
        "action_type": "dispatch",
    }), encoding="utf-8")
    summary = orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))
    assert summary["resolved"] == 1
    rows = _resolution_rows(ws)
    assert len(rows) == 1
    assert rows[0]["disposition"] == "ATTEMPTED_EXHAUSTED"
    assert rows[0]["disposition"] in disposition.DISPOSITIONS
    assert not stash.exists()
    assert (ws / "runs" / "orphan-archive"
            / "dispatch-launch-C-112.json").is_file()


def test_unreadable_register_warns_once_stays_fail_open(tmp_path,
                                                        monkeypatch):
    """Review MEDIUM-1 pin: a PRESENT-but-unreadable register leaves ONE
    resolver warn (the open-claim gate is skipped loudly) and the
    fail-open posture holds — the orphan still resolves. An ABSENT
    register stays the normal silent case."""
    ws = _ws(tmp_path)
    (ws / "claim-register.yaml").write_text("{claims: [broken", encoding="utf-8")
    incremental_reward.record_launch(ws, "C-113", "strings-first")
    calls = _warn_recorder(monkeypatch)
    summary = orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))
    assert summary["resolved"] == 1
    assert len(_resolver_warns(calls)) == 1
    assert "register" in _resolver_warns(calls)[0][1]


def test_occupied_destination_is_a_stable_skip_not_a_failure(
        tmp_path, monkeypatch):
    """Review LOW-6 pin: a stash whose quarantine destination is already
    occupied (a byte-identical restore) is a STABLE state — ONE targeted
    trace, never the transient-failure warn, failed stays empty, and the
    occupied trace is once-per-process (the second pass is silent)."""
    ws = _ws(tmp_path)
    archive_dir = ws / "runs" / "orphan-archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "dispatch-launch-C-111.json").write_text(
        '{"older": true}', encoding="utf-8")
    incremental_reward.record_launch(ws, "C-111", "strings-first")
    calls = _warn_recorder(monkeypatch)
    summary = orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))
    assert summary["failed"] == []
    assert summary["resolved"] == 0
    assert (ws / "runs" / "dispatch-launch-C-111.json").is_file()
    assert json.loads(
        (archive_dir / "dispatch-launch-C-111.json").read_text("utf-8")
    ) == {"older": True}  # never clobbered
    assert len(_resolver_warns(calls)) == 1  # ONE targeted occupied trace

    # the second pass: already-resolved identity, occupied again —
    # no duplicate row and no second occupied trace (once per process)
    calls2 = _warn_recorder(monkeypatch)
    summary2 = orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))
    assert summary2["resolved"] == 0
    assert summary2["failed"] == []
    assert len(_resolution_rows(ws)) == 1  # no duplicate row
    assert _resolver_warns(calls2) == []


def test_second_pass_is_a_noop(tmp_path):
    """Idempotency: after one close pass the sweep returns [] and a
    second resolver pass resolves nothing and writes no duplicate rows."""
    ws = _ws(tmp_path)
    incremental_reward.record_launch(ws, "C-106", "strings-first")
    orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))
    assert _resolution_rows(ws) != []
    assert incremental_reward.sweep_orphan_launches(ws) == []
    summary = orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))
    assert summary["resolved"] == 0
    assert summary["refused"] == []
    assert len(_resolution_rows(ws)) == 1


def test_partial_failure_heals_without_duplicating_rows(
        tmp_path, monkeypatch):
    """Row landed but the quarantine move failed: the next pass must NOT
    write a second row -- it re-attempts the move (the heal)."""
    ws = _ws(tmp_path)
    incremental_reward.record_launch(ws, "C-107", "strings-first")
    orphans = incremental_reward.sweep_orphan_launches(ws)
    stash = ws / "runs" / "dispatch-launch-C-107.json"

    real_replace = Path.replace

    def _failing_replace(self, target):
        if self.name == "dispatch-launch-C-107.json":
            raise OSError("synthetic move failure")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", _failing_replace)
    summary = orphan_resolver.resolve(ws, orphans)
    monkeypatch.undo()
    assert summary["resolved"] == 0
    assert len(summary["failed"]) == 1
    assert stash.is_file()  # the evidence never left
    assert len(_resolution_rows(ws)) == 1  # the row DID land

    # the heal pass: same stash swept again -> no duplicate row
    orphans2 = incremental_reward.sweep_orphan_launches(ws)
    summary2 = orphan_resolver.resolve(ws, orphans2)
    assert summary2["resolved"] == 1
    assert not stash.exists()
    assert (ws / "runs" / "orphan-archive"
            / "dispatch-launch-C-107.json").is_file()
    assert len(_resolution_rows(ws)) == 1, "no duplicate resolution row"


# ------------------------------------------------------------ refused

def test_open_claim_orphan_is_refused_with_reason(tmp_path):
    """An orphan whose claim is still open in the register: a
    refused-with-reason resolution row; the stash file STAYS in place
    (the live settle may still consume it)."""
    ws = _ws(tmp_path)
    write_claims_register(ws, [{"id": "C-103", "status": "OPEN"}])
    stash = ws / "runs" / "dispatch-launch-C-103.json"
    incremental_reward.record_launch(ws, "C-103", "strings-first")
    orphans = incremental_reward.sweep_orphan_launches(ws)
    summary = orphan_resolver.resolve(ws, orphans)

    assert summary["resolved"] == 0
    assert summary["refused"] == ["C-103"]
    assert stash.is_file()  # stays -- never quarantined while open
    assert not (ws / "runs" / "orphan-archive").exists()
    rows = _resolution_rows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["refused"] is True
    assert "open" in str(row["reason"]).lower()
    assert row["archived_to"] is None
    assert row["disposition"] is None  # a refusal classifies nothing
    assert row["stash_sha256"] == _sha256_of(stash)


def test_terminal_claim_orphan_still_resolves(tmp_path):
    """A TERMINAL register status is not open: the orphan resolves
    normally (the claim closed but its settle never fired)."""
    ws = _ws(tmp_path)
    write_claims_register(ws, [{"id": "C-104", "status": "PROVEN"}])
    incremental_reward.record_launch(ws, "C-104", "strings-first")
    summary = orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))
    assert summary["resolved"] == 1
    assert summary["refused"] == []
    assert not (ws / "runs" / "dispatch-launch-C-104.json").exists()


def test_foreign_envelope_is_refused_never_moved(tmp_path):
    """A parked orchestrator envelope parked in the stash namespace (the
    1-F3 shape) is NOT launch state: refused with a reason, and the file
    is never moved out of the namespace its wake reader scans."""
    ws = _ws(tmp_path)
    stash = ws / "runs" / "dispatch-launch-C-004--redteam.json"
    stash.write_text(json.dumps({"status": "PARKED_NOT_LAUNCHED"}),
                     encoding="utf-8")
    summary = orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))
    assert summary["resolved"] == 0
    assert summary["refused"] == ["C-004"]
    assert stash.is_file()
    rows = _resolution_rows(ws)
    assert len(rows) == 1
    assert rows[0]["refused"] is True


# --------------------------------------------------------------- cage

def test_corrupt_stash_caged_one_warn_others_resolve(tmp_path,
                                                     monkeypatch):
    """Per-stash cage: one corrupt stash file is exactly ONE resolver
    warn and is skipped; the OTHER stashes still resolve."""
    ws = _ws(tmp_path)
    incremental_reward.record_launch(ws, "C-108", "strings-first")
    (ws / "runs" / "dispatch-launch-C-109.json").write_bytes(
        b"{not json at all")
    calls = _warn_recorder(monkeypatch)
    summary = orphan_resolver.resolve(
        ws, incremental_reward.sweep_orphan_launches(ws))

    assert summary["resolved"] == 1  # C-108 resolved
    assert len(_resolver_warns(calls)) == 1  # exactly ONE cage warn
    assert (ws / "runs" / "orphan-archive"
            / "dispatch-launch-C-108.json").is_file()
    # C-109 stays untouched, unresolved, unrowed
    assert (ws / "runs" / "dispatch-launch-C-109.json").is_file()
    claims = [r["claim"] for r in _resolution_rows(ws)]
    assert claims == ["C-108"]


# ----------------------------------------------------------- fail-open

def test_broken_workspace_resolves_nothing_never_raises(tmp_path):
    """A missing runs/ resolves nothing and never raises into the
    caller; an orphan pointing at a vanished file is a silent skip (it
    was consumed between sweep and resolve)."""
    bare = tmp_path / "bare"
    bare.mkdir()
    summary = orphan_resolver.resolve(bare, [])
    assert summary["resolved"] == 0
    summary2 = orphan_resolver.resolve(bare, [{
        "claim": "C-110", "action_type": "dispatch",
        "path": str(bare / "runs" / "dispatch-launch-C-110.json"),
        "ts": "",
    }])
    assert summary2["resolved"] == 0


# ------------------------------------------------------------- wiring

def test_close_path_hands_the_sweep_return_to_the_resolver(
        tmp_path, monkeypatch):
    """The close path (convergence_check.decide CONVERGED face) calls the
    resolver with the sweep's return value -- the orphan list is finally
    consumed, not dropped."""
    from test_terminal_settlement_136 import _base_ws, _seed_ledger
    from convergence_check import decide

    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    incremental_reward.record_launch(ws, "C-201", "strings-first")
    seen: list[list[dict]] = []
    monkeypatch.setattr(
        orphan_resolver, "resolve",
        lambda w, o: seen.append([dict(x) for x in o])
        or {"resolved": 0})
    d = decide(ws)
    assert d["decision"] == "CONVERGED"
    assert len(seen) == 1, \
        "decide() must hand the sweep result to the resolver"
    assert [o["claim"] for o in seen[0]] == ["C-201"]


def test_decide_close_pass_resolves_a_real_orphan(tmp_path):
    """End-to-end at the close path: one CONVERGED decide() on a seeded
    orphan leaves the stash quarantined and ONE resolution row -- no
    orphan launch stash remains after the sweep."""
    from test_terminal_settlement_136 import _base_ws, _seed_ledger
    from convergence_check import decide

    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    incremental_reward.record_launch(ws, "C-202", "strings-first")
    d = decide(ws)
    assert d["decision"] == "CONVERGED"
    assert not (ws / "runs" / "dispatch-launch-C-202.json").exists()
    assert (ws / "runs" / "orphan-archive"
            / "dispatch-launch-C-202.json").is_file()
    rows = _resolution_rows(ws)
    assert len(rows) == 1
    assert rows[0]["claim"] == "C-202"
    assert rows[0]["disposition"] == "ATTEMPTED_EXHAUSTED"
    # a second close pass resolves nothing further (idempotent close)
    d2 = decide(ws)
    assert d2["decision"] == "CONVERGED"
    assert len(_resolution_rows(ws)) == 1
