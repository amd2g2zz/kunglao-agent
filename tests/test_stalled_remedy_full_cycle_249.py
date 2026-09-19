# -*- coding: utf-8 -*-
"""Issue-249 pinned full cycle — the issue demands it, all real faces.

  healthy -> STALLED -> exemption dispatch -> mint -> flatline breaks
  -> HEALTHY -> next dispatch passes.

Every state transition is asserted through the REAL gate functions — the
real convergence_health CLI (subprocess), the real worker_budget pre_check
battery (its subprocess gates run the real detector scripts), the real
issue-234 target-ladder machinery (artifact + mint_sibling_claims), and the
real ledger writer (convergence_check._append_ledger). The only fixture
writes are the flatline backlog rows (60s-spaced ts — the real writer
stamps wall-clock ts, and the dedup pressure valve would collapse
rapid-fire identical rows; test_convergence_health_stalled_2.py sets this
precedent) and the workspace files themselves.

  S1  healthy scaffold -> real CLI verdict HEALTHY (sanity; the pre_check
      pass face is proven at S9 — a sanity dispatch here would consume
      C-001's plan-free FIRST dispatch under the issue-239 plan gate)
  S2  flatline backlog -> real CLI verdict: STALLED (exit 1), the JSON
      carries the invokable remedy reference
  S3  ordinary dispatch of the stuck claim -> REJECT (the deadlock face,
      today's behavior preserved for non-remedy traffic)
  S4  remedy-declared dispatch of the stuck claim -> admitted (channel A)
  S5  real ladder walk + real mint_sibling_claims -> sub-claims C-002/003
  S6  ledger still flatlined; marked dispatch of minted C-002 -> admitted
      (channel B — the split's sub-claims)
  S7  adversarial: UNmarked dispatch of minted C-003 -> stays REJECT
  S8  real ledger row (open 1 -> 3) -> real CLI verdict: HEALTHY (exit 0)
      — minting broke the flatline mechanically
  S9  ordinary dispatch of C-003 -> admitted — deadlock closed by
      construction

Hook-interaction tier (subprocess) -> slow marker.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402
from _path_hygiene import load_hooks_lib  # noqa: E402

LIB = load_hooks_lib()
MARKER = LIB.STALLED_REMEDY_MARKER

pytestmark = pytest.mark.slow


def _run_health_cli(ws: Path, json_mode: bool = False):
    """The REAL detector CLI face (subprocess)."""
    args = [sys.executable, str(SCRIPTS / "convergence_health.py"), str(ws)]
    if json_mode:
        args.append("--json")
    return subprocess.run(args, capture_output=True, text=True, timeout=60,
                          cwd=REPO_ROOT, errors="replace")


def _run_pre_check(ws: Path, claim: str, marked: bool) -> int:
    """The REAL pre_check battery, in-process, ALL gates real (the
    subprocess gates run the real detector scripts against the ws)."""
    import worker_budget as wb
    prompt = (json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": claim, "tier": 1,
        "tools": ["grep"], "agent": "w-test"}})
        + "\nfacts-snapshot: 1 facts"
        + "\nagent-reasoning: executing the STALLED verdict's prescribed "
          "decomposition remedy (issue-249); minted sub-claim dispatch"
        + (f"\n{MARKER}\n" if marked else "\n"))
    payload = {"tool_input": {"name": "w-test", "description": "",
                              "prompt": prompt}}
    paths = {
        "workspace": str(ws),
        "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }
    return wb.pre_check(payload, paths)


def _flatline_rows(n: int, open_count: int, open_ids: list[str]) -> list[dict]:
    """60s-spaced new-format snapshot rows (real writer shape)."""
    base = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)
    return [{
        "ts": (base + timedelta(seconds=60 * i)).isoformat(),
        "decision": "DISPATCH",
        "open_count": open_count,
        "open_ids": open_ids,
        "partial_count": 0,
        "active_workers": 1,
        "blockers": [],
        "facts_total": 5,
        "dispatched_ids": ["C-001"],
    } for i in range(n)]


@pytest.fixture()
def ws(tmp_path) -> Path:
    """All-gates-pass workspace with ONE stuck obstacle claim (C-001)."""
    w = tmp_path / "malware-analysis-workspace"
    w.mkdir(parents=True)
    (w / "runs").mkdir(parents=True, exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    prev = (now_dt - timedelta(minutes=5)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    (w / "runs" / ".heartbeat.json").write_text(json.dumps(
        {"last_tick_ts": now,
         "activity_ts": now, "started_ts": prev,
         "tick_history": [prev, now]}), encoding="utf-8")
    with (w / "runs" / ".heartbeat.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": prev, "actor": "tick"}) + "\n")
        f.write(json.dumps({"ts": now, "actor": "tick"}) + "\n")
    (w / "analysis_state.txt").write_text(
        f"deadline_ts: {int(time.time()) + 3600}\n", encoding="utf-8")
    (w / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [{
        "id": "C-001",
        "status": "IN_PROGRESS",
        "promotion_attempts": 1,
        "evidence_tier_attempted": 1,
        "origin": "failure-obstacle",
        "obstacle_class": "interception",
        "statement": "the target pins certificates",
    }]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (w / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    (w / "task_spec.yaml").write_text(
        yaml.safe_dump({"vm_detonation": "allowed"}, sort_keys=False),
        encoding="utf-8")
    return w


def _write_ledger(ws: Path, rows: list[dict]) -> None:
    (ws / ".convergence_ledger.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


# =====================================================================
# THE PINNED FULL CYCLE
# =====================================================================

def test_full_cycle_stalled_remedy_breaks_flatline(ws, tmp_path):
    import target_ladder

    # ---- S1: healthy scaffold (sanity via the CLI verdict; the
    # pre_check pass face is proven at S9 — a sanity dispatch here would
    # consume C-001's plan-free FIRST dispatch and turn S4 into a
    # re-dispatch under the issue-239 plan gate) -------------------------
    _write_ledger(ws, _flatline_rows(2, 3, ["C-001", "C-X"]))
    proc = _run_health_cli(ws)
    assert proc.returncode == 0, \
        f"scaffold must start HEALTHY, got rc={proc.returncode}: {proc.stdout}"

    # ---- S2: flatline backlog -> STALLED with invokable remedy ---------
    _write_ledger(ws, _flatline_rows(5, 1, ["C-001"]))
    proc = _run_health_cli(ws, json_mode=True)
    assert proc.returncode == 1, \
        f"flatlined ws must be STALLED, got {proc.returncode}"
    verdict = json.loads(proc.stdout)
    assert verdict["verdict"] == "STALLED"
    assert verdict["remedy"]["claims"] == ["C-001"]
    assert verdict["remedy"]["dispatch_marker"] == MARKER

    # ---- S3: ordinary dispatch of the stuck claim -> REJECT ------------
    rc = _run_pre_check(ws, "C-001", marked=False)
    assert rc == 2, "S3: the deadlock face — non-remedy traffic stays blocked"

    # ---- S4: remedy-declared dispatch of the stuck claim -> admitted ---
    rc = _run_pre_check(ws, "C-001", marked=True)
    assert rc == 0, "S4: channel A — the prescribed remedy is admitted"

    # ---- S5: real ladder walk + real mint (issue-234 machinery) --------
    ladder = {
        "obstacle_class": "interception",
        "attempts": [
            {"level": "T1", "family": "hooking", "action": "hook",
             "outcome": "pinned", "instrument": "frida unavailable"},
            {"level": "T2", "family": "repackaging", "action": "repack",
             "outcome": "signature check"},
            {"level": "T3", "family": "ca-install", "action": "install CA",
             "outcome": "cert pinning held"},
        ],
        "inventory": [
            {"family": "hooking", "tried": "frida hook",
             "failed_because": "certificate pinning"},
            {"family": "repackaging", "tried": "apk repack",
             "failed_because": "signature verification"},
        ],
    }
    (ws / "runs" / "target-ladder-C-001.yaml").write_text(
        yaml.safe_dump(ladder, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    r = target_ladder.mint_sibling_claims(ws, "C-001")
    assert r["refused"] is None, f"mint refused: {r['refused']}"
    minted = [m["id"] for m in r["minted"]]
    assert minted == ["C-002", "C-003"], \
        f"expected 2 minted siblings, got {minted}"
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
        encoding="utf-8"))
    by_id = {c["id"]: c for c in reg["claims"]}
    assert by_id["C-002"]["status"] == "OPEN"
    assert by_id["C-002"]["depends_on"] == ["C-001"]
    assert by_id["C-002"]["origin"] == "obstacle-alternative"

    # ---- S6: marked dispatch of the minted sub-claim (channel B) -------
    proc = _run_health_cli(ws)
    assert proc.returncode == 1, "ledger still flatlined right after mint"
    rc = _run_pre_check(ws, "C-002", marked=True)
    assert rc == 0, \
        "S6: channel B — the split's sub-claim dispatch is admitted " \
        "(depends_on -> stuck C-001 is the provenance pin)"

    # ---- S6b: round-2 HIGH exploit shape stays REJECT -------------------
    # The reviewer's exploit: self-append a fresh unrelated OPEN claim
    # mid-STALLED and quote the rejection prose (the marker). ->OPEN is
    # ungated, so provenance (depends_on -> a stuck claim) is the
    # discriminator: C-777 has no deps -> not the split's output -> block.
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
        encoding="utf-8"))
    reg["claims"].append({"id": "C-777", "status": "OPEN"})
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    rc = _run_pre_check(ws, "C-777", marked=True)
    assert rc == 2, \
        "S6b: a fresh unrelated OPEN claim with the marker stays blocked"

    # ---- S7: adversarial — unmarked dispatch stays blocked -------------
    rc = _run_pre_check(ws, "C-003", marked=False)
    assert rc == 2, "S7: a non-remedy dispatch during STALLED stays blocked"

    # ---- S7.5: the remedy dispatch's output retires the stuck claim ----
    # The decomposition worker's sanctioned exit: the parent obstacle
    # claim is SUPERSEDED by its minted alternatives (SUPERSEDED is in
    # status_defs.TERMINAL — C-001 leaves the dispatchable frontier, the
    # OTHER half of what clears the STALLED verdict, since C-001 was
    # dispatched-flat-stuck). NOT PROVEN: a PROVEN settlement without a
    # verified reality check is precisely the UNVERIFIED_EVIDENCE drift
    # the B1o blocker rejects (the issue-237-D3 forgery surface) — the
    # cycle must not manufacture a forged verify record to go green.
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
        encoding="utf-8"))
    for c in reg["claims"]:
        if c["id"] == "C-001":
            c["status"] = "SUPERSEDED"
            c["superseded_by"] = ["C-002", "C-003"]
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    # ---- S8: real ledger row -> flatline breaks -> HEALTHY -------------
    d = {"decision": "DISPATCH", "open_count": 2,
         "open_claims": [{"id": "C-002"}, {"id": "C-003"}],
         "partial_count": 0, "active_workers": 0, "active_blockers": []}
    cc._append_ledger(ws, d)
    proc = _run_health_cli(ws)
    assert proc.returncode == 0, \
        (f"S8: minting must break the flatline mechanically, got "
         f"rc={proc.returncode}: {proc.stdout}")

    # ---- S9: ordinary dispatch passes — deadlock closed ----------------
    rc = _run_pre_check(ws, "C-003", marked=False)
    assert rc == 0, "S9: post-HEALTHY ordinary dispatch must pass"
