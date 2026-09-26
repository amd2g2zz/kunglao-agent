# -*- coding: utf-8 -*-
"""tests/test_probe_liveness_303.py — issue 303 satellite D2: fail-loud
instrumentation (probe liveness markers).

issue-127 doctrine (scripts/detector_liveness.py) externalized to runtime
instrumentation: "mechanism existence is not mechanism effectiveness" —
the doubao incident's first chained bug (a bridge import loss, silent)
masqueraded as a business negative for multiple rounds and updated the
WRONG posterior on a dead instrument.

Contract pinned here:
  - every STRICT-era probe result record carries a liveness marker
    (`liveness_marker: "alive"` in the client's returned dict); the row
    gains `liveness: "present" | "absent"`.
  - marker-absent routes INFRA, never business: status pending, excluded
    from case posteriors (Beta(alpha, beta) untouched), and a
    ``probe_infra_dead`` repair item emitted on the unified log.
  - marker-present behaves byte-equivalently to today's healthy path.
  - versioning: the row-level `liveness` FIELD's presence is the era
    stamp. Records without the field (all pre-issue 303 ledgers and rows of
    legacy clients that never declared LIVENESS_CONTRACT = 2) route
    absence as business — legacy tolerance; existing ledgers are never
    retro-invalidated. Absence in a field-carrying record routes INFRA.
  - tool quality gate: `probe_quality_gate` — a strict-era probe client
    that does not emit the marker FAILS the gate; the cadence routes a
    gate-failed client to infra (never red posteriors).
  - the client_broken face (the doubao import-loss shape) routes INFRA:
    loud warn + pending statuses, and NEVER red Bernoulli observations
    (supersedes the issue 132 all-red pin on this one face — issue 303: a dead
    instrument must not feed Beta(alpha, beta)).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import event_taxonomy as et  # noqa: E402
import oracle_cadence as oc  # noqa: E402
import oracle_runner as orun  # noqa: E402
import posteriors as po  # noqa: E402


# ---------------------------------------------------------------- fixtures

CASE_GOOD = {
    "id": "auth-fields",
    "channel": "device-trace",
    "hypothesis_ref": "H-001",
    "update_map": {"green_up": ["H-001"], "red_up": ["H-002"]},
    "params": {"user": "alice", "nonce": 10},
    "expected": [
        {"field": "auth_algo", "value": "hmac-sha256",
         "evidence_refs": ["F001"]},
        {"field": "nonce_len", "value": 2, "evidence_refs": ["F001"]},
    ],
    "mutations": [{"field": "auth_algo", "kind": "swap"}],
    "verification": {
        "artifact": "auth fields pinned by facts/F001",
        "artifact_kind": "hook-state",
        "criterion": "byte-match",
        "threshold": {"exact": True},
        "feeds_decision": "C-001",
    },
}

# literals here (the module constants do not exist yet — that IS the RED);
# test_constants_pinned below pins the runtime names to these literals.
LIVENESS_MARKER_STR = "liveness_marker"
LIVENESS_ALIVE_STR = "alive"
MARKER = f'"{LIVENESS_MARKER_STR}": "{LIVENESS_ALIVE_STR}"'

# strict-era probe (declares contract v2) that PROVES liveness
V2_ALIVE_CLIENT = f'''LIVENESS_CONTRACT = 2

def compute(params):
    return {{"auth_algo": "hmac-sha256",
            "nonce_len": len(str(params["nonce"])),
            {MARKER}}}
'''

# strict-era probe that FORGETS the marker: a dead instrument whose
# business-looking values must never become evidence either way
V2_DEAD_CLIENT = '''LIVENESS_CONTRACT = 2

def compute(params):
    return {"auth_algo": "hmac-sha256",
            "nonce_len": len(str(params["nonce"]))}
'''

# strict-era probe whose values MISMATCH (would be a business red today)
V2_DEAD_WRONG_CLIENT = '''LIVENESS_CONTRACT = 2

def compute(params):
    return {"auth_algo": "sha256-wrong",
            "nonce_len": len(str(params["nonce"]))}
'''

# strict-era probe that crashes (the doubao bridge-import-loss shape)
V2_CRASH_CLIENT = '''LIVENESS_CONTRACT = 2

def compute(params):
    raise RuntimeError("bridge import lost")
'''

# legacy client: no contract declaration — the pre-issue 303 population
LEGACY_CLIENT = '''def compute(params):
    return {"auth_algo": "hmac-sha256",
            "nonce_len": len(str(params["nonce"]))}
'''

LEGACY_WRONG_CLIENT = '''def compute(params):
    return {"auth_algo": "sha256-wrong",
            "nonce_len": len(str(params["nonce"]))}
'''

BROKEN_CLIENT = "raise RuntimeError('bridge import lost')\n"


def _write_hypothesis(ws: Path, hyp_id: str, group: str) -> None:
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        "claim_id: C-001\n"
        f"competitor_group: {group}\n"
        "candidates: [AES, ChaCha20]\n"
        "status: open\n"
        "schema_rev: 1\n"
        "---\n\npq:q1\n",
        encoding="utf-8")


def _mk_ws(tmp_path: Path, client_src: str | None,
           dirname: str = "ws") -> Path:
    ws = tmp_path / dirname
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text(
        "# F001\n\nauth fields pinned (byte-anchored).\n", encoding="utf-8")
    _write_hypothesis(ws, "H-001", "grp-live")
    _write_hypothesis(ws, "H-002", "grp-live")
    (ws / "oracle" / "cases" / "case-00.yaml").write_text(
        yaml.safe_dump(CASE_GOOD, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    if client_src is not None:
        (ws / "oracle" / "client.py").write_text(client_src, encoding="utf-8")
    return ws


def _record_emits(monkeypatch):
    calls: list[dict] = []
    import kunglao_log
    orig = kunglao_log.emit

    def spy(ws, *a, **kw):
        calls.append({"action": kw.get("action") or (a[1] if len(a) > 1 else None),
                      "detail": kw.get("detail") or (a[3] if len(a) > 3 else None)})
        return orig(ws, *a, **kw)

    monkeypatch.setattr(kunglao_log, "emit", spy)
    return calls


def _log_events(ws: Path) -> list[dict]:
    out = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def _infra_events(ws: Path) -> list[dict]:
    return [e for e in _log_events(ws)
            if e.get("action") == "probe_infra_dead"]


# ------------------------------------------------- runtime marker convention

class TestConstants:
    """The marker key/value names are part of the client-facing contract."""

    def test_constants_pinned(self) -> None:
        assert orun.LIVENESS_MARKER == "liveness_marker"
        assert orun.LIVENESS_ALIVE == "alive"
        assert orun.LIVENESS_CONTRACT_V2 == 2


class TestStrictEraRouting:
    """check_case: the classification point routes marker-absent to INFRA."""

    def test_marker_present_healthy_path_unchanged(self, tmp_path) -> None:
        """RED: a live probe (marker present) classifies exactly as today —
        green stays green, alpha moves, no infra item."""
        ws = _mk_ws(tmp_path, V2_ALIVE_CLIENT)
        report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        row = report["cases"]["auth-fields"]
        assert row["status"] == "pass"
        assert row["liveness"] == "present"
        assert report["counts"] == {"red": 0, "green": 1, "pending": 0}
        orun.record_posteriors(ws, report)
        led = po.PosteriorLedger.load(ws)
        assert led.cases["auth-fields"].alpha == 2.0
        assert _infra_events(ws) == []

    def test_marker_absent_business_fail_routes_infra(self, tmp_path) -> None:
        """RED: strict-era probe, no marker, MISMATCHING values — today this
        lands red and feeds beta; it must instead be INFRA (pending), keep
        posteriors untouched, and surface a probe_infra_dead repair item."""
        ws = _mk_ws(tmp_path, V2_DEAD_WRONG_CLIENT)
        report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        row = report["cases"]["auth-fields"]
        assert row["status"] == "pending", "dead instrument is never business-fail"
        assert row["liveness"] == "absent"
        assert report["counts"] == {"red": 0, "green": 0, "pending": 1}
        orun.record_posteriors(ws, report)
        # cold workspace + zero observations -> the ledger is never born
        # (the established no-posterior-movement convention, test_oracle_
        # cadence_132 style)
        assert not (ws / "runs" / "posteriors.yaml").exists()
        infra = _infra_events(ws)
        assert infra and "auth-fields" in str(infra[0].get("detail"))

    def test_marker_absent_business_pass_routes_infra(self, tmp_path) -> None:
        """RED: strict-era probe, no marker, MATCHING values — a dead
        instrument cannot green either: pending, no alpha movement."""
        ws = _mk_ws(tmp_path, V2_DEAD_CLIENT)
        report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        row = report["cases"]["auth-fields"]
        assert row["status"] == "pending"
        assert row["liveness"] == "absent"
        orun.record_posteriors(ws, report)
        assert not (ws / "runs" / "posteriors.yaml").exists()
        assert _infra_events(ws)

    def test_marker_absent_crash_routes_infra(self, tmp_path) -> None:
        """RED: a strict-era probe that crashes proved no liveness — INFRA,
        and the probe_infra_dead item names the shape."""
        ws = _mk_ws(tmp_path, V2_CRASH_CLIENT)
        report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        row = report["cases"]["auth-fields"]
        assert row["status"] == "pending"
        assert row["liveness"] == "absent"
        orun.record_posteriors(ws, report)
        assert not (ws / "runs" / "posteriors.yaml").exists()
        assert _infra_events(ws)

    def test_no_client_no_infra_item(self, tmp_path) -> None:
        """No probe injected at all (no client) is the honest-unknown face —
        pending, but NOT a dead-probe repair item (nothing was injected)."""
        ws = _mk_ws(tmp_path, None)
        report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "nope.py")
        row = report["cases"]["auth-fields"]
        assert row["status"] == "pending"
        assert "liveness" not in row
        assert _infra_events(ws) == []


class TestLegacyTolerance:
    """Versioning: field absence = pre-issue 303 era; absence routes business."""

    def test_legacy_client_rows_keep_legacy_shape(self, tmp_path) -> None:
        """RED: a legacy client (no contract declaration) produces rows
        WITHOUT the liveness field and routes business exactly as today —
        existing ledgers/records are never retro-invalidated."""
        ws = _mk_ws(tmp_path, LEGACY_CLIENT)
        report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        row = report["cases"]["auth-fields"]
        assert row["status"] == "pass"
        assert "liveness" not in row
        orun.record_posteriors(ws, report)
        assert po.PosteriorLedger.load(ws).cases["auth-fields"].alpha == 2.0
        assert _infra_events(ws) == []

    def test_legacy_wrong_client_still_business_red(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path, LEGACY_WRONG_CLIENT)
        report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        assert report["cases"]["auth-fields"]["status"] == "fail"
        assert report["counts"]["red"] == 1

    def test_classify_row_era_switch(self) -> None:
        """The pure classification point: field presence is the era stamp.
        Old records (no field) = legacy = business; field-carrying absent =
        infra; present = business."""
        assert orun.classify_row({"status": "fail"}) == "legacy"
        assert orun.classify_row({"status": "pending",
                                  "liveness": "absent"}) == "infra"
        assert orun.classify_row({"status": "fail",
                                  "liveness": "present"}) == "business"
        assert orun.classify_row({"status": "pass",
                                  "liveness": "present"}) == "business"


class TestPosteriorGuard:
    """Marker-absence must never feed Beta(alpha, beta) — even if a
    status of pass/fail somehow rides an infra row (defense in depth)."""

    def test_record_posteriors_skips_infra_rows(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path, LEGACY_CLIENT)
        report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        report["cases"]["auth-fields"]["liveness"] = "absent"
        orun.record_posteriors(ws, report)
        # the row read "pass" but proved no liveness: it must not settle —
        # zero observations -> the ledger is never born
        assert not (ws / "runs" / "posteriors.yaml").exists()

    def test_settled_rows_excludes_infra_rows(self) -> None:
        """The shared settle-filter (feeding BOTH record_posteriors and
        record_pq_updates) drops infra rows — no Beta/PQ face can see them."""
        report = {"cases": {
            "legacy-pass": {"status": "pass"},
            "infra-fail": {"status": "fail", "liveness": "absent"},
            "infra-pass": {"status": "pass", "liveness": "absent"},
            "strict-pass": {"status": "pass", "liveness": "present"},
        }}
        assert orun._settled_rows(report) == {"legacy-pass": True,
                                              "strict-pass": True}


class TestObservationRows:
    """The observation event payload carries the marker compatibly."""

    def test_observation_row_carries_liveness_on_strict_rows(
            self, tmp_path) -> None:
        ws = _mk_ws(tmp_path, V2_ALIVE_CLIENT)
        orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        obs = [e for e in _log_events(ws) if e.get("action") == "observation"]
        assert obs
        detail = json.loads(obs[0]["detail"])
        assert detail["liveness"] == "present"

    def test_observation_row_legacy_shape_unchanged(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path, LEGACY_CLIENT)
        orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
        obs = [e for e in _log_events(ws) if e.get("action") == "observation"]
        assert obs
        detail = json.loads(obs[0]["detail"])
        assert "liveness" not in detail


class TestByteEquivalence:
    """Healthy path: marker-present and legacy runs write IDENTICAL
    verdict files (the DRAIN probe's three-field projection is sacred)."""

    def test_status_file_bytes_identical(self, tmp_path) -> None:
        ws_alive = _mk_ws(tmp_path, V2_ALIVE_CLIENT, dirname="ws-alive")
        ws_legacy = _mk_ws(tmp_path, LEGACY_CLIENT, dirname="ws-legacy")
        for ws in (ws_alive, ws_legacy):
            report = orun.run(ws / "oracle" / "cases",
                              ws / "oracle" / "client.py")
            orun.write_status(ws, report)
        a = (ws_alive / "runs" / "oracle-status.json").read_bytes()
        b = (ws_legacy / "runs" / "oracle-status.json").read_bytes()
        assert a == b


# ---------------------------------------------------- cadence infra routing

class TestCadenceInfraRouting:
    """The doubao face: a client that cannot even import is INFRA, never
    red posteriors (supersedes issue-132's all-red pin for this face)."""

    def test_broken_client_routes_infra_never_red(self, tmp_path,
                                                  monkeypatch) -> None:
        ws = _mk_ws(tmp_path, BROKEN_CLIENT)
        calls = _record_emits(monkeypatch)
        oc.run_cadence(ws)
        status = json.loads(
            (ws / "runs" / "oracle-status.json").read_text(encoding="utf-8"))
        assert status["counts"] == {"red": 0, "green": 0, "pending": 1}
        assert status["cases"]["auth-fields"]["status"] == "pending"
        # a dead instrument moves NOTHING: the ledger is never born
        assert not (ws / "runs" / "posteriors.yaml").exists()
        durable = [e for e in _log_events(ws)
                   if e.get("action") == "oracle_cadence_warn"]
        assert durable and "client_broken" in str(durable[0].get("detail"))
        assert any(c["action"] == "oracle_cadence_warn"
                   and "client_broken" in str(c.get("detail")) for c in calls)
        infra = [e for e in _log_events(ws)
                 if e.get("action") == "probe_infra_dead"]
        assert infra and "client_broken" in str(infra[0].get("detail"))


# ------------------------------------------------------- tool quality gate

class TestProbeQualityGate:
    """probe_quality_gate: a strict-era probe tool lacking marker emission
    FAILS the gate; legacy clients are tolerated (versioned migration)."""

    def test_v2_without_emission_fails_gate(self, tmp_path) -> None:
        p = tmp_path / "dead_probe.py"
        p.write_text(V2_DEAD_CLIENT, encoding="utf-8")
        violations = orun.probe_quality_gate(p)
        assert violations, "marker-less strict probe must fail the gate"
        assert any("marker" in v.lower() for v in violations)

    def test_v2_with_emission_passes_gate(self, tmp_path) -> None:
        p = tmp_path / "alive_probe.py"
        p.write_text(V2_ALIVE_CLIENT, encoding="utf-8")
        assert orun.probe_quality_gate(p) == []

    def test_legacy_client_tolerated_by_gate(self, tmp_path) -> None:
        p = tmp_path / "legacy_probe.py"
        p.write_text(LEGACY_CLIENT, encoding="utf-8")
        assert orun.probe_quality_gate(p) == []

    def test_gate_failed_client_routes_infra_at_cadence(
            self, tmp_path, monkeypatch) -> None:
        """A registered strict client that fails the quality gate never
        runs as evidence: infra pending + repair item, zero posteriors."""
        ws = _mk_ws(tmp_path, V2_DEAD_CLIENT)
        calls = _record_emits(monkeypatch)
        oc.run_cadence(ws)
        status = json.loads(
            (ws / "runs" / "oracle-status.json").read_text(encoding="utf-8"))
        assert status["counts"] == {"red": 0, "green": 0, "pending": 1}
        assert not (ws / "runs" / "posteriors.yaml").exists()
        assert any(c["action"] == "oracle_cadence_warn"
                   and "marker_gate_failed" in str(c.get("detail"))
                   for c in calls)
        infra = [e for e in _log_events(ws)
                 if e.get("action") == "probe_infra_dead"]
        assert infra and "marker_gate_failed" in str(infra[0].get("detail"))


# ------------------------------------------------------ emission registration

class TestEmissionRegistration:
    """probe_infra_dead is a registered, sorted, unique EMIT_ACTION."""

    def test_word_registered_sorted_unique(self) -> None:
        assert "probe_infra_dead" in et.EMIT_ACTIONS
        assert et.EMIT_ACTIONS == sorted(set(et.EMIT_ACTIONS))

    def test_sorted_position_between_priority_and_proven(self) -> None:
        i = et.EMIT_ACTIONS.index("probe_infra_dead")
        assert et.EMIT_ACTIONS[i - 1] == "priority_deviation"
        assert et.EMIT_ACTIONS[i + 1] == "proven_waiver_used"
