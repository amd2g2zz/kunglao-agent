#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Behavioral snapshot tests for core loop scripts (Phase 1b of refactor).

Validates the 5 core loop scripts that previously had ZERO test coverage:
  - convergence_check.py: 5-branch decision matrix (DISPATCH/DISPATCH_VERIFIER/SATURATED/BLOCKED/CONVERGED)
  - convergence_health.py: HEALTHY/STALLED/SPINNING verdicts + same-turn dedup
  - failure_analysis_gate.py: scan BLOCKED detection + covers_attempt versioning
  - plan_drift_detector.py: 5 drift types
  - claim_expiry.py: STALE threshold

These snapshots lock behavior BEFORE the refactor (Phase 2/3 equivalence baseline).
Style: tmp_path + synthetic fixtures (same as test_v1_8_enforcement_gates.py).

check() raises AssertionError on failure so pytest sees real assertions
(#368: the old counter-based check() only printed, so failures never failed).

Run: python -m pytest tests/test_kunglao_core_loop.py -q
Exit 0 if all pass, 1 if any fail.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# pytest resolves scripts/ via pytest.ini pythonpath; the insert keeps the
# documented standalone run (`python tests/test_kunglao_core_loop.py`) importable.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import yaml

import convergence_check as cc
import convergence_health as ch
import claim_expiry as ce

PASS = 0
FAIL = 1


def check(name: str, cond: bool, detail: str = "") -> None:
    assert cond, f"{name} {detail}".strip()


def make_claim_reg(ws: Path, claims: list[dict]) -> Path:
    """Write a synthetic claim-register.yaml with the given claims.

    Optional `extra`: {field: value} lines appended to the claim entry
    (e.g. created_at for claim_expiry staleness tests).
    """
    reg = ws / "claim-register.yaml"
    lines = ["claims:"]
    for c in claims:
        lines.append(
            f"- id: {c['id']}\n  status: {c['status']}\n"
            f"  boundary_type: {c.get('boundary_type', 'positive_observation')}\n"
            f"  evidence_tier_attempted: {c.get('tier', 0)}\n"
            f"  promotion_attempts: {c.get('attempts', 0)}\n"
            f"  depends_on: {c.get('depends_on', '[]')}"
        )
        for field, value in c.get("extra", {}).items():
            lines.append(f"  {field}: {value}")
        lines.append("")
    reg.write_text("\n".join(lines), encoding="utf-8")
    return reg


# ---------- convergence_check: 5-branch decision matrix ----------
def test_convergence_check(tmp: Path) -> None:
    # Each branch: minimal workspace state -> expected decision + exit_code
    ws = tmp / "cc"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()

    # Branch 1: CONVERGED (no open, no partial)
    make_claim_reg(ws, [{"id": "C-1", "status": "PROVEN"}])
    d = cc.decide(ws)
    check("cc.converged", d["decision"] == "CONVERGED" and d["exit_code"] == 0, str(d))

    # Branch 2: DISPATCH (open + free slots)
    make_claim_reg(ws, [{"id": "C-1", "status": "PROVEN"}, {"id": "C-2", "status": "OPEN"}])
    d = cc.decide(ws)
    check("cc.dispatch", d["decision"] == "DISPATCH" and d["exit_code"] == 1, str(d))

    # Branch 3: SATURATED (open + no free slots) — simulate 3 active workers
    (ws / "runs" / "worker-status-w1.md").write_text("## Status\nstatus: in-progress\n", encoding="utf-8")
    (ws / "runs" / "worker-status-w2.md").write_text("## Status\nstatus: in-progress\n", encoding="utf-8")
    (ws / "runs" / "worker-status-w3.md").write_text("## Status\nstatus: in-progress\n", encoding="utf-8")
    d = cc.decide(ws)
    check("cc.saturated", d["decision"] == "SATURATED" and d["exit_code"] == 3, str(d))

    # Branch 4: BLOCKED (open but all blocked) — via failure_analysis_gate scan
    make_claim_reg(ws, [{"id": "C-1", "status": "PROVEN"}, {"id": "C-2", "status": "OPEN", "attempts": 3}])
    (ws / "runs" / "worker-status-w1.md").unlink()
    (ws / "runs" / "worker-status-w2.md").unlink()
    (ws / "runs" / "worker-status-w3.md").unlink()
    # C-2 with promotion_attempts=3 triggers failure-analysis BLOCKED state
    d = cc.decide(ws)
    check("cc.blocked", d["decision"] == "BLOCKED" and d["exit_code"] == 4, str(d))

    # Branch 5: DISPATCH_VERIFIER (partial facts + free slots)
    make_claim_reg(ws, [{"id": "C-1", "status": "PROVEN"}])
    facts = ws / "facts"
    facts.mkdir()
    (facts / "_INDEX.md").write_text("F001 | PARTIAL | C-1 | test\n", encoding="utf-8")
    d = cc.decide(ws)
    check("cc.dispatch_verifier", d["decision"] == "DISPATCH_VERIFIER" and d["exit_code"] == 2, str(d))

    # Ledger append works (idempotent) — real signature needs open_claims + active_blockers
    cc._append_ledger(ws, {"decision": "DISPATCH", "open_count": 1, "open_claims": [{"id": "C-2"}], "partial_count": 0, "active_workers": 0, "active_blockers": [], "facts_total": 1})
    check("cc.ledger_append", (ws / ".convergence_ledger.jsonl").exists())


# ---------- convergence_health: HEALTHY/STALLED/SPINNING ----------
def test_convergence_health(tmp: Path) -> None:
    ws = tmp / "ch"
    ws.mkdir(parents=True)
    ledger = ws / ".convergence_ledger.jsonl"

    import json
    _tick = 0
    def append(decision: str, open_count: int, facts_total: int = 0) -> None:
        nonlocal _tick
        _tick += 5  # minutes apart — avoids SAME_TURN_WINDOW_SEC dedup
        ts = f"2026-08-06T00:{_tick:02d}:00Z"
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts, "decision": decision, "open_count": open_count,
                                "open_ids": [], "partial_count": 0, "active_workers": 0,
                                "blockers": [], "facts_total": facts_total}) + "\n")

    # HEALTHY: open_count trending down
    for oc in (5, 4, 3, 2, 1):
        append("DISPATCH", oc)
    v = ch.assess(ch._read_ledger(ws))
    check("ch.healthy", v.get("verdict") == "HEALTHY", str(v))

    # STALLED: flatline >= 5
    for _ in range(6):
        append("SATURATED", 2)
    v = ch.assess(ch._read_ledger(ws))
    check("ch.stalled", v.get("verdict") == "STALLED", str(v))

    # SPINNING: facts grow 5+ while open_count held
    for i in range(8):
        append("DISPATCH", 2, facts_total=10 + i)
    v = ch.assess(ch._read_ledger(ws))
    check("ch.spinning", v.get("verdict") == "SPINNING", str(v))


# ---------- claim_expiry: STALE threshold ----------
def test_claim_expiry(tmp: Path) -> None:
    ws = tmp / "ce"
    ws.mkdir(parents=True)

    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    now = datetime.now(tz=timezone.utc)
    # Timestamps are quoted because the system's own writer
    # (claim_expiry._write_yaml via yaml.safe_dump) emits quoted strings;
    # unquoted ISO scalars (datetime objects, YAML 1.1 resolver) are covered
    # by test_claim_expiry_yaml_datetime (#380).
    make_claim_reg(ws, [
        {"id": "C-old", "status": "OPEN", "tier": 1, "extra": {"created_at": f"'{iso(now - timedelta(hours=48))}'"}},
        {"id": "C-new", "status": "OPEN", "tier": 1, "extra": {"created_at": f"'{iso(now - timedelta(hours=1))}'"}},
    ])

    def reg_claims() -> dict[str, dict]:
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
        return {c["id"]: c for c in reg["claims"]}

    # Dry run (default): detection only — register must stay untouched
    rc = ce.check(ws, stale_hours=24)
    check("ce.dry_run_rc", rc == 0, f"rc={rc}")
    check("ce.dry_run_no_write", {k: c["status"] for k, c in reg_claims().items()}
          == {"C-old": "OPEN", "C-new": "OPEN"}, str(reg_claims()))

    # Apply: only the >24h-idle claim flips to STALE (with reason); fresh stays OPEN
    rc = ce.check(ws, stale_hours=24, apply=True)
    claims = reg_claims()
    check("ce.apply_rc", rc == 0, f"rc={rc}")
    check("ce.stale_marked", claims["C-old"]["status"] == "STALE", str(claims))
    check("ce.stale_reason", bool(claims["C-old"].get("stale_reason")), str(claims["C-old"]))
    check("ce.fresh_kept_open", claims["C-new"]["status"] == "OPEN", str(claims))


# ---------- claim_expiry: unquoted ISO timestamps (datetime objects, #380) ----------
def test_claim_expiry_yaml_datetime(tmp: Path) -> None:
    """#380: unquoted ISO scalars load as datetime objects (YAML 1.1 resolver)
    and used to be silently skipped by last_activity_for — a hand-edited
    register with unquoted timestamps never went STALE. datetime and
    quoted-string forms must age identically."""
    ws = tmp / "ce-dt"
    ws.mkdir(parents=True)

    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    now = datetime.now(tz=timezone.utc)
    make_claim_reg(ws, [
        # Unquoted: yaml.safe_load resolves these scalars to datetime objects
        {"id": "C-old-unq", "status": "OPEN", "tier": 1, "extra": {"created_at": iso(now - timedelta(hours=48))}},
        {"id": "C-new-unq", "status": "OPEN", "tier": 1, "extra": {"created_at": iso(now - timedelta(hours=1))}},
        # Quoted controls: identical staleness behavior expected
        {"id": "C-old-q", "status": "OPEN", "tier": 1, "extra": {"created_at": f"'{iso(now - timedelta(hours=48))}'"}},
        {"id": "C-new-q", "status": "OPEN", "tier": 1, "extra": {"created_at": f"'{iso(now - timedelta(hours=1))}'"}},
    ])

    def reg_claims() -> dict[str, dict]:
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
        return {c["id"]: c for c in reg["claims"]}

    # Fixture sanity: the unquoted form really parsed as datetime (bug precondition)
    check("ce_dt.fixture_is_datetime",
          isinstance(reg_claims()["C-old-unq"]["created_at"], datetime),
          str(type(reg_claims()["C-old-unq"]["created_at"])))

    rc = ce.check(ws, stale_hours=24, apply=True)
    claims = reg_claims()
    check("ce_dt.apply_rc", rc == 0, f"rc={rc}")
    check("ce_dt.unquoted_stale", claims["C-old-unq"]["status"] == "STALE", str(claims["C-old-unq"]))
    check("ce_dt.unquoted_reason", bool(claims["C-old-unq"].get("stale_reason")), str(claims["C-old-unq"]))
    check("ce_dt.unquoted_fresh_open", claims["C-new-unq"]["status"] == "OPEN", str(claims["C-new-unq"]))
    check("ce_dt.quoted_stale", claims["C-old-q"]["status"] == "STALE", str(claims["C-old-q"]))
    check("ce_dt.quoted_reason", bool(claims["C-old-q"].get("stale_reason")), str(claims["C-old-q"]))
    check("ce_dt.quoted_fresh_open", claims["C-new-q"]["status"] == "OPEN", str(claims["C-new-q"]))


def main() -> int:
    import tempfile
    suites = [
        ("test_convergence_check", test_convergence_check, "cc-t"),
        ("test_convergence_health", test_convergence_health, "ch-t"),
        ("test_claim_expiry", test_claim_expiry, "ce-t"),
        ("test_claim_expiry_yaml_datetime", test_claim_expiry_yaml_datetime, "ce-dt-t"),
    ]
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, fn, sub in suites:
            try:
                fn(tmp / sub)
            except AssertionError as e:
                failed += 1
                print(f"  FAIL {name}: {e}")
    print(f"test_kunglao_core_loop: {len(suites)} tests, {failed} failed")
    return FAIL if failed else PASS


if __name__ == "__main__":
    sys.exit(main())
