# -*- coding: utf-8 -*-
"""tests/test_plan_repair_verify_281.py — bounded-window plan-repair
verification (the plan-drift mirror of the issue-249 remedy verification).

The gap (issue verbatim): the plan-drift REJECT instructs a repair
("update global_plan.txt and/or ...") that nothing verifies — the
issue-249 dead-lock class ("knows the error but the next step doesn't
move") on the plan face. The detector already re-reads global_plan.txt
every detection round; this module pins the verification face that closes
the loop:

  W1  a drift REJECT opens a repair episode (rounds=1) silently — output
      and exit codes unchanged
  W2  un-repaired: the cumulative drift-round counter (fingerprint-
      INDEPENDENT — a rotating drift shape cannot reset the window)
      re-escalates at every multiple of PLAN_REPAIR_WINDOW_ROUNDS — a
      plan_repair_overdue event row + a stderr line; never a new block
  W3  repair landed: ONLY a genuinely clean round closes the episode with
      a plan_repair_verified event row; drift changing shape is never
      evidence of repair (the adversarial-review flip-flop probe:
      alternating disjoint drift sets escalate, zero false verified)
  W4  cadence, not once-forever: overdue re-fires each window of
      continued drift (no re-emit spam within a window, no permanent
      silence after it)
  W5  fail-open: an unreadable state file never changes the detector's
      verdict — verification skips with an annotation on stderr
  W6  a clean workspace writes no state (no churn on plain rounds)
  W7  registration: both event words ship in event_taxonomy.EMIT_ACTIONS
      (sorted + unique, the issue-459 discipline); the window constant is
      the named literal 3
  W8  cross-face sync: the sinks drift guidance names the verification
      with the same window number (same posture as the issue-249 literal
      duplication pinning)

Fast tier: in-process only — spawns no processes, no nested pytest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import event_taxonomy as et  # noqa: E402
import plan_drift_detector as pdd  # noqa: E402
import worker_budget_sinks as wbs  # noqa: E402

STATE_FILE = "runs/plan-repair-state.json"


# ---------- workspace builders --------------------------------------------

def _register(claims: list[dict]) -> str:
    return yaml.safe_dump({"claims": claims}, sort_keys=True)


def _mk_drift_ws(tmp_path: Path, orphan_ids: tuple[str, ...] = ("C-9",)) -> Path:
    """A workspace with exactly the ORPHAN_CLAIM drift(s): register claims
    C-1 + the orphan ids, plan mentions only C-1 (namespace overlaps, so
    plan-vs-register classes are live)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    claims = [{"id": "C-1", "status": "OPEN"}]
    claims += [{"id": cid, "status": "OPEN"} for cid in orphan_ids]
    (ws / "claim-register.yaml").write_text(_register(claims), encoding="utf-8")
    (ws / "global_plan.txt").write_text(
        "## plan\n- C-1 do the thing\n", encoding="utf-8")
    return ws


def _amend_plan(ws: Path) -> None:
    """The prescribed repair: log the orphaned claims in the plan."""
    plan = ws / "global_plan.txt"
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    plan_ids = pdd.extract_claim_ids_from_plan(plan)
    missing = sorted({c["id"] for c in reg["claims"]} - plan_ids)
    plan.write_text(plan.read_text(encoding="utf-8")
                    + "".join(f"- {cid} discovered mid-run\n" for cid in missing),
                    encoding="utf-8")


def _set_shape_orphan(ws: Path, cid: str = "C-2") -> None:
    """Drift shape A: ORPHAN_CLAIM — register lists an extra claim the
    plan never mentions (namespace still overlaps on C-1)."""
    (ws / "claim-register.yaml").write_text(_register([
        {"id": "C-1", "status": "OPEN"}, {"id": cid, "status": "OPEN"}]),
        encoding="utf-8")
    (ws / "global_plan.txt").write_text("## plan\n- C-1 do the thing\n",
                                        encoding="utf-8")


def _set_shape_stale(ws: Path, cid: str = "C-9") -> None:
    """Drift shape B: STALE_PLAN_ENTRY — the plan lists a claim the
    register no longer has."""
    (ws / "claim-register.yaml").write_text(
        _register([{"id": "C-1", "status": "OPEN"}]), encoding="utf-8")
    (ws / "global_plan.txt").write_text(
        f"## plan\n- C-1 do the thing\n- {cid} long gone\n", encoding="utf-8")


def _event_rows(ws: Path, action: str) -> list[dict]:
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("action") == action:
                out.append(row)
    return out


def _state(ws: Path) -> dict:
    return json.loads((ws / STATE_FILE).read_text(encoding="utf-8"))


# =====================================================================
# W1: the opening REJECT opens an episode, silently
# =====================================================================

class TestEpisodeOpen:
    def test_drift_reject_opens_episode_silently(self, tmp_path, capsys):
        ws = _mk_drift_ws(tmp_path)
        rc = pdd.check(ws)
        assert rc == 1
        st = _state(ws)
        assert st["status"] == "open"
        assert st["rounds"] == 1  # the opening round itself counts
        assert st["fingerprint"]["items"] == ["ORPHAN_CLAIM:C-9"]
        assert st["fingerprint"]["classes"] == ["ORPHAN_CLAIM"]
        out = capsys.readouterr()
        assert "PLAN_REPAIR" not in out.out
        assert "PLAN_REPAIR" not in out.err

    def test_exit_codes_unchanged_across_window(self, tmp_path, capsys):
        ws = _mk_drift_ws(tmp_path, orphan_ids=("C-9", "C-10", "C-11"))
        assert pdd.check(ws) == 2  # 3+ drifts: HARD_PAUSE, as before
        for _ in range(pdd.PLAN_REPAIR_WINDOW_ROUNDS):
            assert pdd.check(ws) == 2  # window expiry never changes rc
        assert "PLAN_REPAIR_OVERDUE" in capsys.readouterr().err


# =====================================================================
# W2/W4: the cumulative counter re-escalates every window
# =====================================================================

class TestOverdue:
    def test_unrepaired_window_expires_emits_overdue(self, tmp_path, capsys):
        ws = _mk_drift_ws(tmp_path)
        assert pdd.check(ws) == 1  # round 1: episode opens
        assert _event_rows(ws, "plan_repair_overdue") == []
        capsys.readouterr()
        assert pdd.check(ws) == 1  # round 2: still inside the window
        assert _event_rows(ws, "plan_repair_overdue") == []
        assert _state(ws)["rounds"] == 2
        capsys.readouterr()
        assert pdd.check(ws) == 1  # round 3: window expires
        rows = _event_rows(ws, "plan_repair_overdue")
        assert len(rows) == 1
        detail = json.loads(rows[0]["detail"])
        assert detail["rounds"] == pdd.PLAN_REPAIR_WINDOW_ROUNDS
        assert detail["window"] == pdd.PLAN_REPAIR_WINDOW_ROUNDS
        assert detail["items"] == ["ORPHAN_CLAIM:C-9"]
        assert "PLAN_REPAIR_OVERDUE" in capsys.readouterr().err

    def test_overdue_re_escalates_every_window(self, tmp_path):
        """Cadence, not once-forever: continued drift re-escalates at each
        multiple of the window (no spam inside a window, no permanent
        silence after it)."""
        ws = _mk_drift_ws(tmp_path)
        for _ in range(2 * pdd.PLAN_REPAIR_WINDOW_ROUNDS + 1):
            pdd.check(ws)
        rows = _event_rows(ws, "plan_repair_overdue")
        assert [json.loads(r["detail"])["rounds"] for r in rows] == [
            pdd.PLAN_REPAIR_WINDOW_ROUNDS, 2 * pdd.PLAN_REPAIR_WINDOW_ROUNDS]

    def test_verified_never_fired_without_repair(self, tmp_path):
        ws = _mk_drift_ws(tmp_path)
        for _ in range(pdd.PLAN_REPAIR_WINDOW_ROUNDS + 1):
            pdd.check(ws)
        assert _event_rows(ws, "plan_repair_verified") == []


# =====================================================================
# W3/W4: the repair-landed path closes the loop visibly
# =====================================================================

class TestVerified:
    def test_repair_lands_emits_verified_no_overdue(self, tmp_path, capsys):
        ws = _mk_drift_ws(tmp_path)
        assert pdd.check(ws) == 1  # episode opens (rounds=1)
        _amend_plan(ws)  # the amendment the REJECT guidance prescribes
        capsys.readouterr()
        assert pdd.check(ws) == 0  # genuinely clean round: verified
        rows = _event_rows(ws, "plan_repair_verified")
        assert len(rows) == 1
        detail = json.loads(rows[0]["detail"])
        assert detail["items"] == ["ORPHAN_CLAIM:C-9"]
        assert detail["rounds"] == 1
        assert _event_rows(ws, "plan_repair_overdue") == []
        assert "PLAN_REPAIR_VERIFIED" in capsys.readouterr().out
        assert _state(ws)["status"] == "verified"

    def test_repair_late_after_overdue_still_closes_loop(self, tmp_path):
        ws = _mk_drift_ws(tmp_path)
        for _ in range(pdd.PLAN_REPAIR_WINDOW_ROUNDS + 1):
            pdd.check(ws)  # overdue fires inside this span
        assert len(_event_rows(ws, "plan_repair_overdue")) == 1
        _amend_plan(ws)
        assert pdd.check(ws) == 0
        assert len(_event_rows(ws, "plan_repair_verified")) == 1
        assert _state(ws)["status"] == "verified"

    def test_fingerprint_rotation_supersedes_silently(self, tmp_path):
        """Drift CHANGING shape is not repair: the episode keeps counting
        under the new fingerprint, with NO event of either kind."""
        ws = _mk_drift_ws(tmp_path)
        assert pdd.check(ws) == 1  # shape A: ORPHAN_CLAIM:C-9, rounds=1
        _set_shape_stale(ws)  # shape B: STALE_PLAN_ENTRY:C-9
        assert pdd.check(ws) == 1
        st = _state(ws)
        assert st["status"] == "open"  # same episode, not a fresh one
        assert st["rounds"] == 2  # cumulative: the window did not reset
        assert st["fingerprint"]["items"] == ["STALE_PLAN_ENTRY:C-9"]
        assert _event_rows(ws, "plan_repair_verified") == []
        assert _event_rows(ws, "plan_repair_overdue") == []

    def test_alternating_disjoint_shapes_escalate(self, tmp_path):
        """The adversarial-review probe, pinned: a workspace alternating
        two DISJOINT drift shapes every round is continuously drifting —
        the cumulative counter escalates on schedule and no false
        plan_repair_verified row is ever emitted."""
        ws = _mk_drift_ws(tmp_path)
        for i in range(9):
            if i % 2 == 0:
                _set_shape_orphan(ws, "C-2")
            else:
                _set_shape_stale(ws, "C-9")
            assert pdd.check(ws) == 1
        verified = _event_rows(ws, "plan_repair_verified")
        assert verified == []  # zero false success rows
        rounds = [json.loads(r["detail"])["rounds"]
                  for r in _event_rows(ws, "plan_repair_overdue")]
        assert rounds == [3, 6, 9]  # cadence held under rotation
        assert _state(ws)["status"] == "open"

    def test_new_episode_after_close_gets_fresh_window(self, tmp_path):
        ws = _mk_drift_ws(tmp_path)
        assert pdd.check(ws) == 1
        _amend_plan(ws)
        assert pdd.check(ws) == 0  # episode closes verified
        # a brand-new drift opens a fresh episode, counter reset to 1
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
        reg["claims"].append({"id": "C-42", "status": "OPEN"})
        (ws / "claim-register.yaml").write_text(_register(reg["claims"]),
                                                encoding="utf-8")
        assert pdd.check(ws) == 1
        st = _state(ws)
        assert st["status"] == "open"
        assert st["rounds"] == 1
        assert st["fingerprint"]["items"] == ["ORPHAN_CLAIM:C-42"]


# =====================================================================
# W5/W6: fail-open posture and no-churn
# =====================================================================

class TestFailOpen:
    def test_unreadable_state_skips_verification_annotated(self, tmp_path, capsys):
        ws = _mk_drift_ws(tmp_path)
        (ws / STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        (ws / STATE_FILE).write_text("{not json", encoding="utf-8")
        rc = pdd.check(ws)
        assert rc == 1  # verdict untouched
        assert "fail-open" in capsys.readouterr().err
        assert _event_rows(ws, "plan_repair_overdue") == []

    def test_clean_workspace_writes_no_state(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text(
            _register([{"id": "C-1", "status": "OPEN"}]), encoding="utf-8")
        (ws / "global_plan.txt").write_text("plan: C-1\n", encoding="utf-8")
        assert pdd.check(ws) == 0
        assert not (ws / STATE_FILE).exists()

    def test_tick_never_raises(self, tmp_path):
        # a workspace so broken the tick cannot even resolve paths
        ws = tmp_path / "ws"
        ws.mkdir()
        assert pdd.plan_repair_tick(ws, [{"type": "X", "claim_id": "C-1"}]) is not None


# =====================================================================
# W7/W8: registration and cross-face sync
# =====================================================================

class TestRegistration:
    def test_event_words_registered_sorted_unique(self):
        for word in ("plan_repair_overdue", "plan_repair_verified"):
            assert word in et.EMIT_ACTIONS, word
        assert et.EMIT_ACTIONS == sorted(set(et.EMIT_ACTIONS))

    def test_window_constant_is_named_three(self):
        assert pdd.PLAN_REPAIR_WINDOW_ROUNDS == 3
        assert pdd.PLAN_REPAIR_OVERDUE_ACTION == "plan_repair_overdue"
        assert pdd.PLAN_REPAIR_VERIFIED_ACTION == "plan_repair_verified"

    def test_sinks_guidance_names_verification(self):
        text = wbs.REJECT_FIXES["drift"]["additionalContext"]
        assert "plan_repair_overdue" in text
        assert f"{pdd.PLAN_REPAIR_WINDOW_ROUNDS} detection rounds" in text

    def test_fingerprint_shape(self):
        fp = pdd.repair_fingerprint([
            {"type": "ORPHAN_CLAIM", "claim_id": "C-9"},
            {"type": "ORPHAN_CLAIM", "claim_id": "C-9"},
            {"type": "STALE_NEXT_STEP", "claim_id": "C-1"},
        ])
        assert fp == {"items": ["ORPHAN_CLAIM:C-9", "STALE_NEXT_STEP:C-1"],
                      "classes": ["ORPHAN_CLAIM", "STALE_NEXT_STEP"]}
