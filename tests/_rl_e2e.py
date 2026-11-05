# -*- coding: utf-8 -*-
"""Shared harness for the RL end-to-end rounds (user requirement 2026-11-06).

Two flows ride the SAME production chain; only the DATA face is mocked:

    resume -> analysis rounds -> blind settlement -> round credit -> posterior
    init   -> analysis rounds -> blind settlement -> round credit -> posterior

Data is SEEDED-random: the method family, settler credit, artifact bytes,
oracle verdict and the fault schedule vary per seed but replay identically
for the same seed. Assertions are invariants (learning moved, settlement
landed, faults classified/refused), never fixed values.

The LLM settler is the mocked face: the harness writes the
``settlement-verdict/1`` doc the kunglao-settler agent would write. Every
other step (claims_store transaction, q-cell dispatch observation,
round_closure blind park, settlement wire/scorer/ledger, round credit,
posterior, episode settle) runs the REAL code.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "tests", ROOT / "hooks"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _factories import (seed_bins, seed_oracle_anchors, stamp_current,
                        write_claims_register, write_worker_status,
                        write_certified_fact)

FAMILIES = ("static-triage", "dynamic-trace", "hypothesis-falsification",
            "red-team-verification", "obfuscation-peeling")
FAULT_KINDS = ("tampered-artifact", "missing-verdict", "orphan-launch")

# Deterministic settlement clock: the wire row's content-hash dedupe keys on
# the row (ts included), so a fixed per-round clock keeps replays byte-stable
# while the DATA itself stays seeded-random.
ROUND_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def round_now(round_no: int) -> datetime:
    return ROUND_T0 + timedelta(minutes=int(round_no))


def _utc(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Scenario:
    """The seeded data face: same seed -> identical scenario."""

    def __init__(self, seed: int):
        self.seed = int(seed)
        self.rng = random.Random(self.seed)

    def family(self) -> str:
        return self.rng.choice(FAMILIES)

    def credit(self) -> float:
        # settler action credit — inside the [0,1] bounded rail
        return round(self.rng.uniform(0.05, 0.95), 6)

    def artifact_bytes(self) -> bytes:
        return self.rng.randbytes(self.rng.randrange(32, 192))

    def oracle(self) -> str:
        return "pass" if self.rng.random() < 0.75 else "fail"

    def plan(self, rounds: int = 7) -> list[dict]:
        """One entry per round: fault kind (or healthy), family, credit.

        The random draws are seeded; two coverage guarantees are pinned by
        construction so every seed exercises BOTH learning directions:
        round 1 is a pass (the loop opens on a success) and ONE seeded
        round is a measured fail (negative learning).
        """
        kinds = ["healthy"] * rounds
        slots = list(range(1, rounds))          # never fault the first round
        self.rng.shuffle(slots)
        for kind, slot in zip(FAULT_KINDS, slots):
            kinds[slot] = kind
        outcomes = ["pass" if self.rng.random() < 0.75 else "fail"
                    for _ in range(rounds)]
        outcomes[0] = "pass"
        fail_slot = self.rng.choice(list(range(1, rounds)))
        outcomes[fail_slot] = "fail"
        return [{"round": i + 1, "fault": kinds[i],
                 "family": self.family(), "credit": self.credit(),
                 "oracle": outcomes[i]} for i in range(rounds)]


# ---------------------------------------------------------------- fixtures

def _seed_task_spec(ws: Path) -> None:
    """Anchors (the intake contract) + one primary question (the state
    signature the dispatch observation folds in)."""
    seed_oracle_anchors(ws)
    p = ws / "task_spec.yaml"
    text = p.read_text(encoding="utf-8")
    if "primary_questions" not in text:
        p.write_text(text.rstrip() + "\n"
                     "primary_questions:\n"
                     "- id: pq1\n"
                     "  q: what is the sample's behaviour chain?\n",
                     encoding="utf-8")


def _claims(n: int) -> list[dict]:
    return [{"id": f"C-{i:03d}", "status": "OPEN",
             "answers_question": "pq1"}
            for i in range(1, n + 1)]


def build_workspace(tmp_path: Path, *, seed: int = 0,
                    n_claims: int = 7) -> Path:
    """A ready-to-dispatch workspace (no init run): stamped, anchored,
    claims OPEN, heartbeat fresh."""
    ws = tmp_path / f"ws-resume-{seed}"
    (ws / "runs").mkdir(parents=True)
    (ws / "evidence").mkdir()
    (ws / "facts").mkdir()
    seed_bins(ws)
    _seed_task_spec(ws)
    stamp_current(ws)
    write_claims_register(ws, _claims(n_claims))
    _write_heartbeat(ws)
    _write_activation(ws)
    return ws


def init_workspace(tmp_path: Path, *, seed: int = 0,
                   n_claims: int = 7) -> Path:
    """Run the REAL init CLI on a fresh directory (mocked anchor answers +
    skipped toolchain probe), then seed the analysis claims."""
    ws = tmp_path / f"ws-init-{seed}"
    (ws / "bins").mkdir(parents=True)
    seed_bins(ws)
    _seed_task_spec(ws)
    env = {k: v for k, v in os.environ.items()
           if k != "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"}
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "kunglao-init.py"), str(ws),
         "--type", "linux", "--lane", "algorithm", "--skip-toolchain",
         "--host-exec-protection", "enabled", "--assume-yes",
         "--profile-root", str(tmp_path / f"profile-{seed}")],
        capture_output=True, text=True, timeout=180, env=env, errors="replace")
    if proc.returncode != 0:
        raise AssertionError(
            f"init failed rc={proc.returncode}\n{proc.stdout[-2000:]}\n"
            f"{proc.stderr[-2000:]}")
    write_claims_register(ws, _claims(n_claims))
    _write_heartbeat(ws)
    _write_activation(ws)
    return ws


def _write_heartbeat(ws: Path, *, age_minutes: float = 0) -> None:
    ts = _utc(datetime.now(timezone.utc) - timedelta(minutes=age_minutes))
    p = ws / "runs" / ".heartbeat.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "started_ts": ts, "interval_min": 5, "last_tick_ts": ts,
        "loop_registered": True}), encoding="utf-8")


def _write_activation(ws: Path, *, expires_minutes: float = 30) -> None:
    expires = _utc(datetime.now(timezone.utc)
                   + timedelta(minutes=expires_minutes))
    (ws / ".hook_state.json").write_text(json.dumps({
        "active_hooks": ["dispatch_gate", "worker_budget"],
        "paused_hooks": [], "expires_at": expires,
        "phase": "DISPATCH", "tier": "none"}), encoding="utf-8")


def resume_brief(ws: Path) -> dict:
    """The resume CLI face (read-only): rc 0 + the JSON brief."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "kunglao_resume.py"),
         str(ws), "--json"],
        capture_output=True, text=True, timeout=120, errors="replace")
    if proc.returncode != 0:
        raise AssertionError(
            f"resume rc={proc.returncode}\n{proc.stdout[-2000:]}\n"
            f"{proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


# ------------------------------------------------------------- one round

def dispatch_round(ws: Path, claim: str, family: str, *,
                   tier: int = 1) -> dict:
    """The production dispatch transaction + the q-cell dispatch row."""
    import claims_store
    meta = {"method_family": family, "action_type": "dispatch", "tier": tier}
    prompt = ("# dispatch\n\n```json\n"
              + json.dumps({"kunglao_dispatch": meta}) + "\n```\n")
    intent = claims_store.begin_dispatch(
        ws, claim, actor="e2e-orchestrator", tier=tier, prompt=prompt,
        method_family=family, branch_budget={"wall_s": 600, "retries": 1})
    if not intent.ok:
        raise AssertionError(f"begin_dispatch refused: {intent.reason}")
    commit = claims_store.commit_dispatch(ws, claim)
    if not commit.ok:
        raise AssertionError(f"commit_dispatch refused: {commit.reason}")
    from rlvr import incremental_reward as ir
    ir.record_launch(ws, claim, family,
                     branch_budget={"wall_s": 600, "retries": 1},
                     action_type="dispatch")
    from rlvr import q_cells
    obs = q_cells.record_dispatch_observation(
        ws, prompt, envelope_meta=meta, claim=claim,
        dispatch_id=commit.journal_id)
    if not obs.get("appended"):
        raise AssertionError(f"q-cell dispatch row not appended: {obs}")
    return {"journal_id": commit.journal_id, "observation": obs}


def complete_round(ws: Path, claim: str, *, artifact_rel: str,
                   payload: bytes, status: str = "PROVEN") -> Path:
    """The mocked worker completion: status line, artifact, fact.

    The fact carries ``creator=<claim>`` (the provenance key the round
    credit ladder attributes on) and ``claim_id`` (the citation relation
    via the claim's answers_question — a full-credit terminal fact).
    """
    write_worker_status(ws, claim, "DONE")
    art = ws / artifact_rel
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_bytes(payload)
    fact = write_certified_fact(ws, f"F-{claim}", claim, status=status)
    text = fact.read_text(encoding="utf-8")
    close = text.find("\n---\n", 4)
    if close != -1 and "creator:" not in text:
        fact.write_text(text[:close] + f"\ncreator: {claim}"
                        + text[close:], encoding="utf-8")
    return art


def close_round(ws: Path, claim: str, session: str) -> None:
    """SubagentStop face: transition close + blind input park."""
    import round_closure
    from rlvr import step_ledger as sl
    for i in range(2):
        row = sl.build_step_row(
            session_id=session, tool="Bash",
            tool_input={"command": f"round-step-{i}"},
            tool_response={"stdout": "ok"},
            ts=_utc(datetime.now(timezone.utc)))
        sl.record_step(ws, row)
    rc = round_closure.main_with_payload(
        {"cwd": str(ws), "session_id": session,
         "transcript_path": str(ws / "runs" / f"transcript-{claim}.jsonl")})
    if rc != 0:
        raise AssertionError(f"round_closure rc={rc} for {claim}")


def rule_round(ws: Path, claim: str, *, credit: float,
               oracle_verdict: str) -> None:
    """The mocked settler ruling + the verification record the mint needs."""
    from rlvr import settlement_wire as wire
    parked = wire.load_parked(ws, claim)
    if parked is None:
        raise AssertionError(f"no parked blind input for {claim}")
    evidence = [a.get("path") for a in (parked.get("artifacts") or [])]
    verdict = {
        "schema": "settlement-verdict/1",
        "identity": "kunglao-settler",
        "claim": claim,
        "actions": [{"action_id": f"step-{claim}", "credit": credit,
                     "evidence": evidence}],
        "trajectory_credit": credit,
    }
    (ws / "runs" / f"settlement-verdict-{claim}.json").write_text(
        json.dumps(verdict, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    word = "verified" if oracle_verdict == "pass" else "refuted"
    (ws / "runs" / f"verification-{claim}.md").write_text(
        f"verdict: {word}\n", encoding="utf-8")


def settle_round(ws: Path, claim: str, *, oracle_verdict: str,
                 round_no: int = 0,
                 has_reproducible_evidence: bool = True) -> dict:
    """The single-claim blind settlement (the production consumer face).

    ``settle_parked`` (not ``settle_face``) — the face sweep would re-emit
    every prior claim's event; the per-claim call keeps each round's audit
    trail to its own claim. A fixed per-round clock keeps the wire row's
    content-hash dedupe stable.
    """
    from rlvr import settlement_wire as wire
    return wire.settle_parked(
        ws, claim, oracle_verdict=oracle_verdict,
        has_reproducible_evidence=has_reproducible_evidence,
        verification=f"runs/verification-{claim}.md",
        now=round_now(round_no))


def credit_round(ws: Path) -> dict:
    import settle_round_credit
    return settle_round_credit.run(ws)


def settle_mission(ws: Path) -> dict:
    from rlvr import episode_settle
    return episode_settle.settle_mission(ws)


def pending_claims(ws: Path) -> list[dict]:
    from rlvr import settlement_wire as wire
    return wire.pending_settlements(ws)


def run_rounds(ws: Path, sc: "Scenario", plan: list[dict]) -> dict:
    """Drive the seeded round matrix over ONE workspace.

    Healthy rounds settle + bank credit. Fault rounds are contained (the
    pipeline refuses/marks them) and then REPAIRED so every claim reaches
    a terminal state for the mission-terminal settle. Every claim is
    settled through the real blind wire; the only mocked face is the
    settler verdict.
    """
    from rlvr import incremental_reward as ir

    settled = refused = failed_oracle = 0
    for step in plan:
        r = step["round"]
        claim = f"C-{r:03d}"
        dispatch_round(ws, claim, step["family"])
        payload = sc.artifact_bytes()
        art_rel = f"evidence/round-{claim}.bin"
        complete_round(ws, claim, artifact_rel=art_rel, payload=payload,
                       status="PROVEN" if step["oracle"] == "pass"
                       else "REFUTED")
        close_round(ws, claim, f"sess-{claim}")
        if step["oracle"] != "pass":
            failed_oracle += 1

        fault = step["fault"]
        if fault == "tampered-artifact":
            (ws / art_rel).write_bytes(b"tampered-after-the-blind-park")
            rule_round(ws, claim, credit=step["credit"],
                       oracle_verdict=step["oracle"])
            res = settle_round(ws, claim, oracle_verdict=step["oracle"],
                               round_no=r)
            assert res.get("settled") is False, (claim, res)
            assert any(not row.get("settled")
                       for row in wire_rows(ws, claim)), claim
            (ws / art_rel).write_bytes(payload)          # the repair
            refused += 1
        elif fault == "missing-verdict":
            assert any(p["claim"] == claim
                       for p in pending_claims(ws)), claim
            refused += 1
        elif fault == "orphan-launch":
            side = f"C-ORPHAN-{r}"
            ir.record_launch(ws, side, step["family"], action_type="dispatch")
            orphans = ir.sweep_orphan_launches(ws)
            assert any(str(o.get("claim")) == side for o in orphans), orphans
            for o in orphans:
                Path(o["path"]).unlink()
            refused += 1

        rule_round(ws, claim, credit=step["credit"],
                   oracle_verdict=step["oracle"])
        res = settle_round(ws, claim, oracle_verdict=step["oracle"], round_no=r)
        assert res.get("settled") is True, (claim, res)
        # Consume the ruling: a later round's round_closure blind face would
        # otherwise re-settle this claim with the pass-through oracle verdict
        # (no runs/oracle-status.json in the fixture), changing the banked
        # reward behind the test's back.
        (ws / "runs" / f"settlement-verdict-{claim}.json").unlink(
            missing_ok=True)
        rows = wire_rows(ws, claim)
        assert any(row.get("settled") for row in rows), (claim, rows)
        assert task_settlement(ws, claim) is not None, claim
        credit_round(ws)
        settled += 1
    return {"settled": settled, "refused": refused,
            "failed_oracle": failed_oracle}


def expire_activation(ws: Path) -> None:
    _write_activation(ws, expires_minutes=-5)


def renew_activation(ws: Path) -> None:
    _write_activation(ws)


# ------------------------------------------------------------- assertions

def cell_totals(ws: Path) -> tuple[float, float]:
    """(success mass, failure mass) over the settled Q cells."""
    from rlvr import q_cells
    table = q_cells.cell_table(ws, gamma=1.0)
    success = sum(float(c.get("success") or 0.0)
                  for c in table.get("cells") or [])
    failure = sum(float(c.get("failure") or 0.0)
                  for c in table.get("cells") or [])
    return success, failure


def cell_mass(ws: Path) -> float:
    success, failure = cell_totals(ws)
    return success + failure


def wire_rows(ws: Path, claim: str) -> list[dict]:
    from rlvr import consolidated_ledger as cl
    return [r for r in cl.read(ws, "settlement")
            if str(r.get("schema") or "") == "settlement-wire/1"
            and str(r.get("claim") or "") == claim]


def task_settlement(ws: Path, claim: str) -> dict | None:
    from rlvr import ledger as rl
    row = rl.fold(ws, f"task/{claim}")
    return (row or {}).get("settlement")
