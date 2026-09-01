#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_decision_teeth.py — decision-loop value teeth (#496).

Three teeth on the un-bypassable dispatch face (hooks/dispatch_gate.py)
plus the typed-fact consumption in the authoritative scorer's evidence
input (scripts/priority_ratio.py, #499 authority):

  1. top-1 enforcement — dispatching a non-top-1 claim (rank >= 2 under
     worker_budget.check_priority, i.e. priority_ratio) without an
     `agent-reasoning:` prefix in the prompt REJECTs (exact copy of the
     #310 agenttype-deviation structure: stderr + additionalContext +
     exit 2); with the reason it passes AND leaves a trace in the unified
     event log (kunglao_log, action=priority_deviation).
  2. capability cards — a validated_capability (#495 artifact) in hand
     constrains tool choice: switching to a DIFFERENT tool family
     REJECTs unless the prompt shows the disproof
     (`capability-disproof: <family>`). Trajectory-1 replay: frida
     validated, switching to xposed requires showing frida failed.
  3. strategy novelty (minimal interface) — a `[strategy <id>]` marker
     makes the gate log the dispatch; same-strategy historical failures
     (derived from #495's covers_attempt, no new writer) lower that
     claim's novelty in the ratio.

②(b) obstacle leverage: pinned (already-green by design — #495's promoted
depends_on edge is consumed naturally by ratio's rev_deps leverage and the
inherited answers_question feeds D once unblocked; these tests pin that
natural consumption so a refactor cannot silently drop it).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


# ---------- shared fixtures ----------

def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _activate(ws: Path) -> None:
    """Make dispatch_gate ACTIVE on this workspace (v1.9.7 TTL discipline)."""
    (ws / ".hook_state.json").write_text(json.dumps({
        "active_hooks": ["dispatch_gate"],
        "paused_hooks": [],
        "expires_at": "2099-12-31T23:59:59Z",
    }), encoding="utf-8")


def _top1_ws(root: Path) -> Path:
    """Workspace where the authoritative VoI rank is unambiguous:

      C-1  = top-1   (live competitor_group g1, D=1.0, tier 1 -> 0.55)
      C-2  = rank #2 (answers_question, D=0.5, tier 1 -> 0.40)
      C-3  = rank #3 (g1 member, tier 2 cost 3.0 -> 0.183)

    Claim ids must be C-<digits>: the dispatch protocol (#452) parses
    only `[A-Z]+-\\d+` — letter ids would fall into the unparseable path.
    """
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write(ws / "claim-register.yaml", {"claims": [
        {"id": "C-2", "status": "OPEN", "statement": "background work",
         "answers_question": "PQ-1"},
        {"id": "C-1", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1"},
        {"id": "C-3", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1", "evidence_tier_attempted": 1},
    ]})
    _write(ws / "claim_deps.yaml", {
        "depends_on": {}, "competitor_groups": {"g1": ["C-1", "C-3"]}})
    _write(ws / "task_spec.yaml", {"primary_questions": []})
    _activate(ws)
    return ws


def _capability_ws(root: Path, *, with_obstacle_claim: bool = False) -> Path:
    """Trajectory-1 replay shape: C-1 failed once with frida, the #495
    analysis recorded validated_capability=frida (and is complete, so C-1
    is NOT failure-blocked). with_obstacle_claim=True adds the promoted
    obstacle node C-2 exactly as _promote_obstacle_claim writes it."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    claims = [{"id": "C-1", "status": "OPEN", "promotion_attempts": 1,
               "statement": "bypass the anti-debug check via frida"}]
    if with_obstacle_claim:
        claims.append({
            "id": "C-2", "status": "OPEN", "boundary_type": "obstacle",
            "evidence_tier_attempted": 0, "promotion_attempts": 0,
            "depends_on": ["C-1"],
            "statement": "Obstacle (from C-1): spawn timeout kills spawn path",
            "origin": "failure-obstacle", "obstacle_for": "C-1",
            "promoted_from": "analyses/failure-C-1.yaml",
        })
    _write(ws / "claim-register.yaml", {"claims": claims})
    _write(ws / "claim_deps.yaml", {
        "depends_on": {"C-2": ["C-1"]} if with_obstacle_claim else {},
        "competitor_groups": {}})
    _write(ws / "task_spec.yaml", {"primary_questions": []})
    _write(ws / "analyses" / "failure-C-1.yaml", {
        "claim": "C-1", "covers_attempt": 1,
        "method_assumption": "frida spawn would keep the process alive",
        "assumption_validity": "not-justified",
        "next_method": "listen mode instead of spawn",
        "next_method_source": "reference-hit",
        # the capability card in hand: frida WORKS for injection
        "validated_capability":
            "frida injection reaches the anti-debug check and bypasses it",
        "identified_obstacle": "spawn timeout kills the spawn path only",
    })
    _activate(ws)
    return ws


def _run_gate(root: Path, ws: Path, prompt: str) -> subprocess.CompletedProcess:
    script = REPO_ROOT / "hooks" / "dispatch_gate.py"
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(ws),
        "tool_input": {"prompt": prompt},
    })
    return subprocess.run(
        [sys.executable, str(script)],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT), errors="replace",
    )


def _event_rows(ws: Path) -> list[dict]:
    """All rows from the unified event log (runs/logs/kunglao-*.jsonl)."""
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------- ① top-1 enforcement -----------------------------------------

class TestTop1Enforcement:
    def test_dispatch_rank3_without_reasoning_rejected(self, tmp_path) -> None:
        """#496 AC: dispatching rank #3 (C-B2) with no `agent-reasoning:`
        prefix MUST REJECT (exit 2 + stderr + fix guidance naming the
        marker). This is the mechanical tooth the advisory-only audit
        (#310-era) never had on this hook face."""
        root = tmp_path / "r1"
        ws = _top1_ws(root)
        r = _run_gate(root, ws, "[T2 tools=grep] claim C-3 background sweep")
        assert r.returncode == 2, (
            f"rank-3 dispatch without reasoning must REJECT; got rc="
            f"{r.returncode}, stdout={r.stdout!r}, stderr={r.stderr!r}")
        assert "REJECT top1" in r.stderr, f"stderr={r.stderr!r}"
        assert "agent-reasoning" in r.stdout, (
            f"fix guidance must teach the agent-reasoning marker; "
            f"stdout={r.stdout!r}")
        assert "C-1" in (r.stderr + r.stdout), (
            "the rejection must name the authority top-1 (C-1)")

    def test_dispatch_rank2_with_agent_reasoning_passes_and_logs(self, tmp_path) -> None:
        """#496 AC: with `agent-reasoning:` the deviation passes AND leaves
        a trace (unified event log action=priority_deviation, claim=C-2)."""
        root = tmp_path / "r2"
        ws = _top1_ws(root)
        prompt = ("[T1 tools=grep] claim C-2 background work\n"
                  "agent-reasoning: C-1 needs the VM lease which is not up "
                  "yet; C-2 is pure-static and unblocked")
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 0, (
            f"agent-reasoning deviation must pass; stderr={r.stderr!r}")
        assert "TOP1 (deviation recorded)" in r.stderr, (
            f"pass must be observable on stderr (agenttype mirror); "
            f"stderr={r.stderr!r}")
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "priority_deviation"]
        assert any(e.get("claim") == "C-2" for e in rows), (
            f"unified log must carry the deviation trace; rows={rows}")

    def test_dispatch_top1_silent(self, tmp_path) -> None:
        """Dispatching the authority top-1 (C-1) stays silent — no REJECT,
        no deviation trace (guard: the tooth is narrow, rank-#1 only)."""
        root = tmp_path / "r3"
        ws = _top1_ws(root)
        r = _run_gate(root, ws, "[T1 tools=grep] claim C-1 background work")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        assert "REJECT top1" not in r.stderr
        assert not [e for e in _event_rows(ws)
                    if e.get("action") == "priority_deviation"]

    def test_failure_blocked_claim_keeps_guidance_path(self, tmp_path) -> None:
        """Guard: rank-None dispatches (here: failure-blocked, no current
        analysis) keep the #495 injection path — the top-1 tooth must not
        hijack the failure-blocked slice (parity with worker_budget's
        devreason: REJECT only on a known rank >= 2)."""
        root = tmp_path / "r4"
        ws = _top1_ws(root)
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
        reg["claims"].append({"id": "C-4", "status": "OPEN",
                              "statement": "background work",
                              "promotion_attempts": 1})
        _write(ws / "claim-register.yaml", reg)
        r = _run_gate(root, ws, "[T1 tools=grep] claim C-4 retry the failed")
        assert r.returncode == 0, (
            f"failure-blocked slice belongs to the #495 injection, not the "
            f"top-1 REJECT; stderr={r.stderr!r}")
        assert "failure-blocked" in (r.stdout + r.stderr), (
            "the #495 corrective guidance must still fire")


# ---------- ②(a) capability switch — pure judgment -----------------------

class TestCapabilitySwitchJudgment:
    def _view(self, cap_text: str):
        import priority_ratio as pr
        return pr.EvidenceView(
            validated_capabilities=(("C-1", cap_text),))

    def test_switch_from_validated_family_flagged(self) -> None:
        """frida validated in hand, dispatch declares xposed -> violation."""
        import priority_ratio as pr
        v = pr.capability_switch_violation(
            ["C-1"], ["rev-xposed"], "task text",
            self._view("frida injection bypasses the anti-debug check"))
        assert v is not None, "frida->xposed switch must be flagged"
        assert v["validated_families"] == ["frida"]
        assert v["dispatch_families"] == ["xposed"]

    def test_same_family_passes(self) -> None:
        import priority_ratio as pr
        v = pr.capability_switch_violation(
            ["C-1"], ["rev-frida"], "task text",
            self._view("frida injection bypasses the anti-debug check"))
        assert v is None, "staying on the validated family is not a switch"

    def test_disproof_marker_passes(self) -> None:
        import priority_ratio as pr
        v = pr.capability_switch_violation(
            ["C-1"], ["rev-xposed"],
            "capability-disproof: frida (spawn path timed out; injection "
            "itself never got to run)",
            self._view("frida injection bypasses the anti-debug check"))
        assert v is None, "a disproof naming the validated family is the escape"

    def test_unknown_capability_family_fail_open(self) -> None:
        import priority_ratio as pr
        v = pr.capability_switch_violation(
            ["C-1"], ["rev-xposed"], "task text",
            self._view("decompression of the overlay works"))
        assert v is None, "no known tool family in the capability -> no constraint"

    def test_no_capability_passes(self) -> None:
        import priority_ratio as pr
        v = pr.capability_switch_violation(
            ["C-9"], ["rev-xposed"], "task text", pr.EvidenceView())
        assert v is None, "no analysis / no capability for the claim -> no constraint"

    def test_union_parent_card_survives_familyless_child_card(self) -> None:
        """F1 leak direction (review bidirectional reproduce): the obstacle
        child's card sorts AFTER the parent's (higher claim id) and carries
        no known family — the union must still see the parent's frida card,
        so the child's switch to xposed is constrained. Pre-F1 `caps[-1]`
        read only the child card -> None -> the parent's constraint was
        masked exactly on the trajectory-1 continuation path."""
        import priority_ratio as pr
        view = pr.EvidenceView(validated_capabilities=(
            ("C-1", "frida injection bypasses the anti-debug check"),
            ("C-2", "decompression of the overlay works"),
        ))
        v = pr.capability_switch_violation(
            {"C-2", "C-1"}, ["rev-xposed"], "task text", view)
        assert v is not None, (
            "the parent's frida card must survive the child's familyless "
            "card (union over in-scope cards, not the last card)")
        assert v["validated_families"] == ["frida"], f"got {v}"
        assert v["dispatch_families"] == ["xposed"], f"got {v}"

    def test_union_return_to_parent_validated_family_allowed(self) -> None:
        """F1 false-block direction (review bidirectional reproduce): the
        child card validated qiling; dispatching frida RETURNS to the
        parent-chain validated family — the family set intersects the
        union, so it is capability in hand, not a switch. Pre-F1 last-card
        read judged this a violation and demanded a semantically false
        `capability-disproof: qiling`."""
        import priority_ratio as pr
        view = pr.EvidenceView(validated_capabilities=(
            ("C-1", "frida injection bypasses the anti-debug check"),
            ("C-2", "qiling emulates the unpacking stub"),
        ))
        v = pr.capability_switch_violation(
            {"C-2", "C-1"}, ["rev-frida"], "task text", view)
        assert v is None, (
            "returning to a family validated anywhere in scope is not a "
            f"switch; got violation {v}")

    def test_union_disproof_exempts_per_family(self) -> None:
        """F1: the disproof exemption is per family — disproving qiling does
        not excuse abandoning a still-validated frida (the marker shows ONE
        card failed; the other stays in force)."""
        import priority_ratio as pr
        view = pr.EvidenceView(validated_capabilities=(
            ("C-1", "frida injection bypasses the anti-debug check"),
            ("C-2", "qiling emulates the unpacking stub"),
        ))
        v = pr.capability_switch_violation(
            {"C-2", "C-1"}, ["rev-xposed"],
            "capability-disproof: qiling (emulation diverged from the "
            "unpacking path)", view)
        assert v is not None, (
            "frida is still validated and in force after the qiling "
            "disproof")
        assert v["validated_families"] == ["frida"], f"got {v}"


# ---------- ②(a) capability switch — hook-level REJECT -------------------

class TestCapabilityGate:
    def test_capability_switch_rejected(self, tmp_path) -> None:
        """#496 AC: capability-card in hand + tool-family switch -> REJECT
        (must disprove first). Trajectory-1 replay: frida validated, the
        next dispatch silently pivots to xposed."""
        root = tmp_path / "c1"
        ws = _capability_ws(root)
        r = _run_gate(root, ws,
                      "[T2 tools=rev-xposed] claim C-1 hook the check via xposed")
        assert r.returncode == 2, (
            f"validated frida + dispatch xposed must REJECT; rc="
            f"{r.returncode}, stderr={r.stderr!r}")
        assert "REJECT capability" in r.stderr, f"stderr={r.stderr!r}"
        assert "capability-disproof" in r.stdout, (
            f"fix guidance must teach the disproof marker; stdout={r.stdout!r}")

    def test_capability_switch_with_disproof_passes(self, tmp_path) -> None:
        """Showing the disproof (frida failed on the spawn path) passes and
        leaves the capability_switch trace in the unified log."""
        root = tmp_path / "c2"
        ws = _capability_ws(root)
        prompt = ("[T2 tools=rev-xposed] claim C-1 hook the check via xposed\n"
                  "capability-disproof: frida (spawn path timed out twice — "
                  "see analyses/failure-C-1.yaml)")
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        assert "CAPABILITY (disproof recorded)" in r.stderr, (
            f"pass must be observable; stderr={r.stderr!r}")
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "capability_switch"]
        assert any(e.get("claim") == "C-1" for e in rows), (
            f"unified log must carry the switch trace; rows={rows}")

    def test_obstacle_claim_inherits_parent_capability_context(self, tmp_path) -> None:
        """The trajectory-1 pivot lands on the PROMOTED obstacle claim —
        the capability context follows the obstacle_for parent edge, so
        dispatching C-2 with xposed is still blocked until disproven."""
        root = tmp_path / "c3"
        ws = _capability_ws(root, with_obstacle_claim=True)
        r = _run_gate(root, ws,
                      "[T2 tools=rev-xposed] claim C-2 try xposed instead")
        assert r.returncode == 2, (
            f"obstacle claim must inherit the parent capability card; rc="
            f"{r.returncode}, stderr={r.stderr!r}")
        assert "REJECT capability" in r.stderr

    def test_obstacle_child_card_does_not_shadow_parent_card(self, tmp_path) -> None:
        """F1 at the hook face, both directions: the obstacle child failed
        once too, so analyses/failure-C-2.yaml exists (sorted file order ->
        child card LAST). Union semantics must hold through the real
        from_workspace path:
          - leak direction: child card has no known family -> the parent's
            frida card still constrains C-2's switch to xposed (REJECT);
          - false-block direction: child card has no known family and the
            dispatch RETURNS to the parent-validated frida -> pass (rc=0).
        """
        root = tmp_path / "c4"
        ws = _capability_ws(root, with_obstacle_claim=True)
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
        c2 = next(c for c in reg["claims"] if c.get("id") == "C-2")
        c2["promotion_attempts"] = 1
        _write(ws / "claim-register.yaml", reg)
        _write(ws / "analyses" / "failure-C-2.yaml", {
            "claim": "C-2", "covers_attempt": 1,
            "method_assumption": "overlay decompression exposes the payload",
            "assumption_validity": "justified",
            "next_method": "keep the decompression card",
            "next_method_source": "reference-hit",
            # the child card: NO known tool family
            "validated_capability": "decompression of the overlay works",
            "identified_obstacle": "none",
        })
        r = _run_gate(root, ws,
                      "[T2 tools=rev-xposed] claim C-2 try xposed instead")
        assert r.returncode == 2, (
            f"leak direction: the parent's frida card must survive the "
            f"child's familyless card; rc={r.returncode}, "
            f"stderr={r.stderr!r}")
        assert "REJECT capability" in r.stderr, f"stderr={r.stderr!r}"
        assert "frida" in r.stderr, (
            f"the rejection must name the still-constraining family; "
            f"stderr={r.stderr!r}")
        r2 = _run_gate(root, ws,
                       "[T2 tools=rev-frida] claim C-2 back to frida")
        assert r2.returncode == 0, (
            f"false-block direction: returning to the parent-validated "
            f"frida is capability in hand, not a switch; rc="
            f"{r2.returncode}, stderr={r2.stderr!r}, stdout={r2.stdout!r}")


# ---------- ②(b) obstacle leverage — PIN (natural consumption) -----------

class TestObstacleLeverage:
    def _flat_ws(self, root: Path) -> Path:
        ws = root / "ws"
        ws.mkdir(parents=True)
        _write(ws / "claim-register.yaml", {"claims": [
            {"id": "C-1", "status": "OPEN", "promotion_attempts": 1,
             "statement": "c2 protocol restore"},
            {"id": "C-2", "status": "OPEN", "statement": "background work"},
        ]})
        _write(ws / "claim_deps.yaml", {"depends_on": {}, "competitor_groups": {}})
        return ws

    def test_obstacle_promotion_raises_parent_leverage_flat_dag(self, tmp_path) -> None:
        """PIN: in a FLAT DAG everyone has L=0; recording a #495 analysis
        with identified_obstacle grows the DAG (obstacle node depends_on
        the failed claim) and the parent's leverage rises to 1.0, making
        it the unambiguous top-1. This is the 'attacking the obstacle
        unlocks the parent' value the ratio already consumes — pinned so
        a refactor of _reverse_deps/lev_raw cannot silently drop it."""
        import failure_analysis_gate as fag
        import priority_ratio as pr

        before_ws = self._flat_ws(tmp_path / "before")
        after_ws = self._flat_ws(tmp_path / "after")
        empty_lib = tmp_path / "lessons"
        empty_lib.mkdir()

        # the real promotion path (#495 machinery, not a hand-built shape)
        r = fag.record_analysis(
            after_ws, "C-1",
            assumption="spawn keeps the process alive",
            validity="not-justified",
            next_method="listen mode",
            validated_capability="frida injection reaches the check",
            identified_obstacle="spawn timeout kills the spawn path",
            source="reference-hit", library=empty_lib)
        assert r.get("recorded"), f"record failed: {r}"
        assert r["obstacle_claim"]["created"], (
            f"obstacle must be promoted; got {r['obstacle_claim']}")

        def _rank(ws: Path):
            reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
            deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8"))
            return pr.priority_ratio(reg["claims"], deps,
                                     pr.EvidenceView.from_workspace(ws))

        before = {a.claim_id: a for a in _rank(before_ws)}
        after = {a.claim_id: a for a in _rank(after_ws)}
        assert before["C-1"].leverage == 0.0, "flat DAG: no leverage before promotion"
        assert after["C-1"].leverage == 1.0, (
            f"promotion must feed the parent's leverage; got "
            f"{after['C-1'].leverage}")
        assert after["C-1"].score > after["C-2"].score, (
            "the failed parent (with its obstacle child) must now outrank "
            "the untouched sibling")
        ranked = _rank(after_ws)
        assert ranked[0].claim_id == "C-1", (
            f"parent must be top-1 after promotion; got {ranked[0].claim_id}")

    def test_obstacle_claim_discriminator_consumes_inherited_answers_question(self, tmp_path) -> None:
        """PIN: once the parent is terminal the obstacle claim is a
        candidate, and its #495-inherited answers_question feeds D (0.5,
        vs 0.2 for a plain sibling) — the obstacle's value context is
        consumed, not dropped, by unblocking."""
        import priority_ratio as pr
        claims = [
            {"id": "C-1", "status": "PROVEN", "statement": "c2 protocol restore"},
            {"id": "C-2", "status": "OPEN", "boundary_type": "obstacle",
             "origin": "failure-obstacle", "obstacle_for": "C-1",
             "depends_on": ["C-1"], "promotion_attempts": 0,
             "evidence_tier_attempted": 0,
             "statement": "Obstacle (from C-1): spawn timeout",
             "answers_question": "PQ-3"},
            {"id": "C-3", "status": "OPEN", "statement": "background work"},
        ]
        deps = {"depends_on": {"C-2": ["C-1"]}, "competitor_groups": {}}
        ev = pr.EvidenceView(terminal_fact_claims=frozenset({"C-1"}))
        out = {a.claim_id: a for a in pr.priority_ratio(claims, deps, ev)}
        assert "C-2" in out, (
            "obstacle claim must become dispatchable once the parent is terminal")
        assert out["C-2"].discriminator == 0.5, (
            f"inherited answers_question must feed D; got "
            f"{out['C-2'].discriminator}")
        assert out["C-3"].discriminator == 0.2


# ---------- ③ strategy novelty (minimal interface) ----------------------

def _strategy_ws(root: Path) -> Path:
    """C-1's dispatches carried [strategy spawn-inject] twice (snapshots
    0 and 1); the #495 analysis afterwards covers attempt 2 -> BOTH rows
    count as same-strategy failures (2 > 0 and 2 > 1) -> N(C-1) =
    1 - min(1, 2/3) = 0.333. The claim stays rankable (attempts 2 < 3)."""
    ws = root / "ws"
    ws.mkdir(parents=True)
    _write(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN", "promotion_attempts": 2,
         "statement": "c2 protocol restore"},
        {"id": "C-2", "status": "OPEN", "statement": "background work"},
    ]})
    _write(ws / "claim_deps.yaml", {"depends_on": {}, "competitor_groups": {}})
    (ws / "runs").mkdir()
    rows = [
        {"ts": "2026-08-19T00:00:00Z", "event": "dispatch",
         "strategy": "spawn-inject", "claim": "C-1",
         "attempts_at_snapshot": 0},
        {"ts": "2026-08-19T01:00:00Z", "event": "dispatch",
         "strategy": "spawn-inject", "claim": "C-1",
         "attempts_at_snapshot": 1},
    ]
    (ws / "runs" / "strategy-log.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    _write(ws / "analyses" / "failure-C-1.yaml", {
        "claim": "C-1", "covers_attempt": 2,
        "method_assumption": "spawn works", "assumption_validity": "not-justified",
        "next_method": "listen mode", "next_method_source": "reference-hit",
        "validated_capability": "decompression works",
        "identified_obstacle": "spawn timeout",
    })
    return ws


class TestStrategyNovelty:
    def test_strategy_failures_lower_novelty(self, tmp_path) -> None:
        import priority_ratio as pr
        ws = _strategy_ws(tmp_path)
        ev = pr.EvidenceView.from_workspace(ws)
        assert ev.claim_strategy == {"C-1": "spawn-inject"}, (
            f"the dispatch log must map claim->latest strategy; got "
            f"{ev.claim_strategy}")
        assert ev.strategy_failures.get("spawn-inject") == 2, (
            f"both dispatch rows whose claim later failed (covers 2 > "
            f"snapshots 0, 1) must count; got {ev.strategy_failures}")
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
        deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8"))
        out = {a.claim_id: a for a in pr.priority_ratio(reg["claims"], deps, ev)}
        # N(C-1) = 1 - min(1, (0 facts + 2 failures)/3) = 1/3
        assert out["C-1"].novelty < out["C-2"].novelty, (
            "same-strategy historical failures must lower novelty")
        assert out["C-1"].novelty == 0.333, (
            f"expected N=0.333 (2 failures / NOVELTY_BASE 3); got "
            f"{out['C-1'].novelty}")

    def test_claim_without_strategy_unchanged(self, tmp_path) -> None:
        import priority_ratio as pr
        ws = _strategy_ws(tmp_path)
        ev = pr.EvidenceView.from_workspace(ws)
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
        deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8"))
        out = {a.claim_id: a for a in pr.priority_ratio(reg["claims"], deps, ev)}
        assert out["C-2"].novelty == 1.0, (
            "a claim with no strategy tag keeps full novelty")
        assert out["C-2"].score > out["C-1"].score, (
            "the un-tagged sibling must outrank the failed-strategy claim")

    def test_strategy_dispatch_row_logged_by_gate(self, tmp_path) -> None:
        """The gate appends the dispatch row on its PASS path when the
        prompt carries `[strategy <id>]` — the only writer the mechanism
        needs (interface not forced: no marker, no row)."""
        root = tmp_path / "s3"
        ws = _top1_ws(root)
        r = _run_gate(root, ws,
                      "[T1 tools=grep] claim C-1 background sweep [strategy first-pass]")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        log = ws / "runs" / "strategy-log.jsonl"
        assert log.exists(), "the strategy dispatch row must be logged"
        rows = [json.loads(ln) for ln in
                log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        row = next((e for e in rows if e.get("strategy") == "first-pass"), None)
        assert row is not None, f"rows={rows}"
        assert row["event"] == "dispatch"
        assert row["claim"] == "C-1"
        assert "attempts_at_snapshot" in row

    def test_strategy_log_truncated_to_recent_200_before_dispatch_row(
            self, tmp_path) -> None:
        """#496 review F4: the ledger is bounded — before each dispatch row
        is written the file is truncated to the most recent 200 rows
        (read-truncate-write, idempotent). 250 old rows -> the 200 kept +
        1 new = 201, oldest dropped; a file already under the cap keeps its
        rows verbatim and in order."""
        root = tmp_path / "s4"
        ws = _top1_ws(root)
        log = ws / "runs" / "strategy-log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        old = [
            json.dumps({"ts": "2026-08-19T00:00:00Z", "event": "dispatch",
                        "strategy": "gen", "claim": f"C-{i}",
                        "attempts_at_snapshot": 0})
            for i in range(250)
        ]
        log.write_text("\n".join(old) + "\n", encoding="utf-8")
        r = _run_gate(root, ws,
                      "[T1 tools=grep] claim C-1 background sweep [strategy fresh]")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        rows = [json.loads(ln) for ln in
                log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(rows) == 201, (
            f"200 kept + 1 new; got {len(rows)}")
        assert rows[-1]["strategy"] == "fresh", "the new dispatch row is last"
        assert rows[0]["claim"] == "C-50", (
            f"rows 0-49 must be the dropped oldest; first kept={rows[0]}")
        assert [e["claim"] for e in rows[:-1]] == [f"C-{i}" for i in range(50, 250)], (
            "the kept prefix must stay verbatim and in order")

        # under the cap: nothing dropped, order preserved
        root2 = tmp_path / "s5"
        ws2 = _top1_ws(root2)
        log2 = ws2 / "runs" / "strategy-log.jsonl"
        log2.parent.mkdir(parents=True, exist_ok=True)
        log2.write_text("\n".join(old[:3]) + "\n", encoding="utf-8")
        r2 = _run_gate(root2, ws2,
                       "[T1 tools=grep] claim C-1 background sweep [strategy small]")
        assert r2.returncode == 0, f"stderr={r2.stderr!r}"
        rows2 = [json.loads(ln) for ln in
                 log2.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(rows2) == 4, f"3 kept + 1 new; got {len(rows2)}"
        assert [e["claim"] for e in rows2[:3]] == ["C-0", "C-1", "C-2"], (
            "an under-cap file must not lose or reorder rows")
        assert rows2[-1]["strategy"] == "small"


# ---------- ②(a) capability dormant observability (#600) ------------------

class TestCapabilityDormantObservability:
    """#600: the capability-card tooth (②(a)) is conditional on the OPTIONAL
    `obstacle_for` field — with none anywhere in the register,
    capability_switch_violation() returns None for every dispatch and the
    whole #496 capability-switch enforcement silently no-ops (same class as
    #594/#596: an operator-absent field makes a gate mute). The fix is
    observability, NOT a required field (that would break every greenfield
    workspace): a ONE-TIME `capability_dormant` WARN at the guard entrance.

    One-time is enforced by a sentinel file (runs/.capability-dormant-warned):
    the gate runs as a fresh process per dispatch, so a module-level flag
    cannot persist across dispatches.
    """

    def test_no_obstacle_for_warns_exactly_once(self, tmp_path) -> None:
        """Register without any `obstacle_for` -> the first dispatch through
        the capability guard leaves ONE dormant WARN (stderr names
        capability-dormant, unified log carries action=capability_dormant,
        guidance names obstacle_for / #496); the second dispatch does NOT
        repeat it (sentinel). Enforcement stays unchanged: staying on the
        validated family passes (rc=0) in both dispatches."""
        root = tmp_path / "d1"
        ws = _capability_ws(root)
        prompt = "[T2 tools=rev-frida] claim C-1 stay on the validated family"
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 0, (
            f"dormant WARN must not change the pass rc; stderr={r.stderr!r}")
        assert "capability-dormant" in r.stderr, (
            f"first dispatch must WARN on stderr; stderr={r.stderr!r}")
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "capability_dormant"]
        assert len(rows) == 1, (
            f"exactly one dormant trace expected; got {len(rows)}: {rows}")
        assert rows[0].get("claim") == "C-1", f"rows={rows}"
        assert "obstacle_for" in (r.stdout + r.stderr), (
            "guidance must name the obstacle_for field (the #496 arming "
            f"condition); stdout={r.stdout!r}")
        # sentinel is in place -> the second dispatch does not repeat
        assert (ws / "runs" / ".capability-dormant-warned").exists()
        r2 = _run_gate(root, ws, "[T2 tools=rev-frida] claim C-1 second dispatch")
        assert r2.returncode == 0, f"stderr={r2.stderr!r}"
        rows2 = [e for e in _event_rows(ws)
                 if e.get("action") == "capability_dormant"]
        assert len(rows2) == 1, (
            f"dormant WARN is one-time per workspace; got {len(rows2)}")

    def test_obstacle_for_present_no_dormant_warn(self, tmp_path) -> None:
        """With an obstacle_for claim in the register the guard is armed —
        no dormant WARN, and enforcement is untouched (the trajectory-1
        obstacle claim still REJECTs the family switch, pinned by
        TestCapabilityGate.test_obstacle_claim_inherits_parent_capability_context)."""
        root = tmp_path / "d2"
        ws = _capability_ws(root, with_obstacle_claim=True)
        r = _run_gate(root, ws,
                      "[T2 tools=rev-frida] claim C-1 background work")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "capability_dormant"]
        assert rows == [], (
            f"armed register must not WARN dormant; rows={rows}")
