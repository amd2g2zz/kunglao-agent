# -*- coding: utf-8 -*-
"""Issue #466 — /kunglao-agent:resume crash/reboot breakpoint recovery (TDD).

RED on baseline (origin/dev @ 45856bd): no scripts/kunglao_resume.py, no
`resume` in skills/subcommands.yaml (3-command registry), no
skills/resume/SKILL.md, no `resume` subcommand on scripts/kunglao.py.

Scope split under test (design.md D1): external_kicker (#39) recovers the
DYING session and WRITES; resume diagnoses the CRASHED workspace and is
READ-ONLY — every test below that runs resume also asserts it left the
workspace byte-identical (file set + mtimes + ledger line count).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from _factories import write_hook_state

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SKILLS = ROOT / "skills"
REGISTRY_FILE = SKILLS / "subcommands.yaml"
RESUME_SKILL = SKILLS / "resume" / "SKILL.md"
HELP_SKILL = SKILLS / "help" / "SKILL.md"
ROOT_SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"

for _p in (str(SCRIPTS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _armed_ws(tmp_path: Path, *, name: str = "ws",
              heartbeat_age_min: int | None = 0,
              with_ledger: bool = True,
              with_hook_state: bool = True,
              with_event_log: bool = True,
              with_plan: bool = True,
              with_narratives: bool = True,
              with_register: bool = True,
              claims: list[dict] | None = None) -> Path:
    """A crashed-workspace fixture: the #461-armed shape minus the session.

    Same claim-register/task_spec shape as
    tests/test_convergence_completeness._make_ws (canonical decide() input).
    """
    ws = tmp_path / name
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()
    now = datetime.now(timezone.utc)

    if with_register:
        rows = claims or [
            {"id": "C-1", "status": "OPEN", "answers_question": "q1"},
        ]
        lines = ["claims:"]
        for c in rows:
            lines.append(f"- id: {c['id']}")
            for k, v in c.items():
                if k != "id":
                    lines.append(f"  {k}: {v}")
        (ws / "claim-register.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n  - q1: sample family\n", encoding="utf-8")

    # #748: stamp the workspace template version so the stale-workspace
    # gate (RC=5) passes — these tests are about resume's delegation
    # behavior, not about the gate itself.
    ws_version = "0.1.3"
    (ws / "CLAUDE.md").write_text(
        f"# kunglao_template_version: {ws_version}\n", encoding="utf-8")

    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    (facts / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")

    if heartbeat_age_min is not None:
        ts = _iso(now - timedelta(minutes=heartbeat_age_min))
        (ws / "runs" / ".heartbeat.json").write_text(
            json.dumps({"last_tick_ts": ts, "activity_ts": ts}), encoding="utf-8")

    if with_ledger:
        snap = {"type": "snapshot", "ts": _iso(now - timedelta(minutes=30)),
                "decision": "DISPATCH", "open_ids": ["C-1"],
                "active_workers": [], "blockers": [], "facts_total": 0}
        (ws / ".convergence_ledger.jsonl").write_text(
            json.dumps(snap) + "\n", encoding="utf-8")

    if with_hook_state:
        write_hook_state(ws, active_hooks=["worker_budget.py", "dispatch_gate.py"],
                         expires_at=_iso(now + timedelta(minutes=10)))

    if with_event_log:
        logs = ws / "runs" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / f"kunglao-{now:%Y-%m-%d}.jsonl").write_text(
            json.dumps({"ts": _iso(now - timedelta(minutes=25)), "actor": "orchestrator",
                        "action": "converge", "detail": "DISPATCH", "exit": 1}) + "\n",
            encoding="utf-8")

    if with_plan:
        (ws / "global_plan.txt").write_text("plan: dispatch C-1 (static first)\n", encoding="utf-8")
    if with_narratives:
        (ws / "analysis_state.txt").write_text("current_task: C-1 strings\n", encoding="utf-8")
        (ws / "progress.txt").write_text("## VERIFIED-FACTS LEDGER\n(none yet)\n", encoding="utf-8")
    return ws


def _snapshot_tree(ws: Path) -> dict:
    """relpath -> (mtime_ns, size) for every file under ws (read-only proof)."""
    out = {}
    for p in sorted(ws.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(ws))] = (st.st_mtime_ns, st.st_size)
    return out


def _ledger_lines(ws: Path) -> int:
    p = ws / ".convergence_ledger.jsonl"
    return len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0


def _armed_ws_with_active_worker(tmp_path: Path) -> Path:
    """The flagship crash shape (review F1): the session died with >=1
    worker in flight — a FRESH in-progress worker-status file, so
    decide() reports active_workers=1 (and it is not a stale-worker
    annotation)."""
    ws = _armed_ws(tmp_path)
    (ws / "runs" / "worker-status-w1.md").write_text(
        "# worker w1\nstatus: in-progress\n", encoding="utf-8")
    return ws


# ===========================================================================
# 1. module + exit-code triage
# ===========================================================================

def test_module_exists_with_rc_constants() -> None:
    import kunglao_resume as kr
    assert (kr.RC_RESUMABLE, kr.RC_MANUAL, kr.RC_NO_STATE) == (0, 1, 2)


def test_empty_workspace_rc_no_state_with_init_guidance(tmp_path) -> None:
    import kunglao_resume as kr
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = kr.main([str(empty)])
    assert rc == kr.RC_NO_STATE
    brief = kr.build_brief(empty)
    assert brief["verdict"] == "NO-STATE"
    guidance = json.dumps(brief, ensure_ascii=False)
    assert "/kunglao-agent:init" in guidance, "no-state must point at init"


def test_nonexistent_path_rc_no_state(tmp_path, capsys) -> None:
    import kunglao_resume as kr
    rc = kr.main([str(tmp_path / "never-existed")])
    assert rc == kr.RC_NO_STATE
    assert "/kunglao-agent:init" in capsys.readouterr().out


def test_armed_open_workspace_rc_resumable_with_real_decision(tmp_path) -> None:
    """The core drill: OPEN claim + live heartbeat -> rc 0 and the brief
    carries convergence_check's OWN decision verbatim (never recomputed)."""
    import convergence_check as cc
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    pre = cc.decide(ws)  # the pre-crash convergence output
    brief = kr.build_brief(ws)
    assert brief["rc"] == kr.RC_RESUMABLE
    assert brief["health"]["heartbeat"]["status"] == "ALIVE"
    d = brief["summary"]["decision"]
    assert d is not None
    assert d["decision"] == pre["decision"] == "DISPATCH"
    assert d["open_count"] == pre["open_count"] == 1
    assert d["action"] == pre["action"]
    assert brief["next_step"], "next-step advice must be non-empty"


def test_stale_heartbeat_rc_manual_with_rearm_advice(tmp_path) -> None:
    """Issue negative path: state present, heartbeat stale -> annotate +
    rc 1 + the #461 re-arm chain (resume itself never re-arms)."""
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, heartbeat_age_min=180)
    rc = kr.main([str(ws)])
    assert rc == kr.RC_MANUAL
    brief = kr.build_brief(ws)
    assert brief["health"]["heartbeat"]["status"] == "STALE"
    advice = "\n".join(brief["advice"])
    assert "--wire-up" in advice and "--heartbeat-on" in advice, (
        "advice must name the #461 bootstrap chain")
    assert "CronCreate" in advice


def test_missing_heartbeat_rc_manual(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, heartbeat_age_min=None)
    brief = kr.build_brief(ws)
    assert brief["health"]["heartbeat"]["status"] == "MISSING"
    assert brief["rc"] == kr.RC_MANUAL


def test_blocked_decision_rc_manual(tmp_path, monkeypatch) -> None:
    """decision in MANUAL set (BLOCKED / INVALID — both exit 4 in VERDICTS)
    -> needs the self-recovery ladder / a human, not a plain continue."""
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    blocked = {"decision": "BLOCKED", "exit_code": 4, "action": "x",
               "open_count": 1, "partial_count": 0, "active_workers": [],
               "free_slots": 3, "worker_cap": 3, "stuck_workers": [],
               "active_blockers": ["B-1"], "failure_blocked": []}
    monkeypatch.setattr(kr, "_decide", lambda ws: blocked)
    brief = kr.build_brief(ws)
    assert brief["rc"] == kr.RC_MANUAL
    assert any("BLOCKED" in r for r in brief["manual_reasons"])


def test_missing_register_with_other_state_rc_manual(tmp_path) -> None:
    """CRITICAL degradation: register gone but ledger/facts survive ->
    counts untrustworthy, decision WITHHELD (never approximated), rc 1."""
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, with_register=False)
    brief = kr.build_brief(ws)
    assert brief["rc"] == kr.RC_MANUAL
    assert brief["summary"]["decision"] is None
    assert brief["sources"]["claim-register.yaml"] == "missing"


# ===========================================================================
# 2. crash-drill fidelity (issue acceptance: counts/decision equal pre-crash)
# ===========================================================================

def test_crash_drill_brief_matches_pre_crash_convergence(tmp_path) -> None:
    import convergence_check as cc
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, heartbeat_age_min=5)  # crash: no tick since
    pre = cc.decide(ws)
    brief = kr.build_brief(ws)
    d = brief["summary"]["decision"]
    for key in ("decision", "exit_code", "action", "open_count",
                "partial_count", "active_workers", "free_slots",
                "active_blockers"):
        assert d[key] == pre[key], f"resume diverged from pre-crash on {key}"
    assert brief["rc"] == kr.RC_RESUMABLE


def test_decision_counters_are_ints_not_collections(tmp_path) -> None:
    """Review F1 type pin: decide()'s counters are INTs — active_workers is
    a COUNT (convergence_check._DecideInputs.active: int), not a worker
    list. Renderers must never len()/iterate them; with a worker in flight
    the count is 1, not a 1-element list."""
    import convergence_check as cc
    import kunglao_resume as kr
    ws = _armed_ws_with_active_worker(tmp_path)
    pre = cc.decide(ws)
    assert pre["active_workers"] == 1, (
        f"fixture must put one worker in flight, got {pre['active_workers']!r}")
    d = kr.build_brief(ws)["summary"]["decision"]
    for key in ("open_count", "partial_count", "active_workers",
                "free_slots", "worker_cap"):
        assert isinstance(d[key], int) and not isinstance(d[key], bool), (
            f"summary.{key} must stay decide()'s int, got {type(d[key])}")


def test_resume_is_read_only(tmp_path) -> None:
    """The load-bearing contract: resume writes NOTHING — not the ledger
    (cc.main appends; decide() must be called directly), not state files,
    not even new artifacts like runs/digest.md."""
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    before_tree, before_ledger = _snapshot_tree(ws), _ledger_lines(ws)
    kr.main([str(ws), "--json"])
    assert _snapshot_tree(ws) == before_tree, "resume modified the workspace"
    assert _ledger_lines(ws) == before_ledger, "resume appended to the ledger"


# ===========================================================================
# 3. degradation drills (issue acceptance: >=3 missing sources)
# ===========================================================================

def _row(brief: dict, source: str) -> dict:
    for r in brief["data_age"]:
        if r["source"] == source:
            return r
    raise AssertionError(f"data-age row missing: {source} "
                         f"(have {[r['source'] for r in brief['data_age']]})")


def test_missing_ledger_degrades_with_flag(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, with_ledger=False)
    brief = kr.build_brief(ws)
    assert _row(brief, ".convergence_ledger.jsonl")["exists"] is False
    assert brief["rc"] == kr.RC_RESUMABLE  # DEGRADE, not CRITICAL


def test_missing_hook_state_degrades_with_flag(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, with_hook_state=False)
    brief = kr.build_brief(ws)
    assert _row(brief, ".hook_state.json")["exists"] is False
    assert brief["health"]["activation"]["status"] == "MISSING"
    assert brief["rc"] == kr.RC_RESUMABLE


def test_missing_event_log_degrades_with_flag(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, with_event_log=False)
    brief = kr.build_brief(ws)
    assert _row(brief, "runs/logs/kunglao-*.jsonl")["exists"] is False
    assert brief["rc"] == kr.RC_RESUMABLE


def test_missing_facts_index_degrades_with_flag(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    (ws / "facts" / "_INDEX.md").unlink()
    brief = kr.build_brief(ws)
    assert _row(brief, "facts/_INDEX.md")["exists"] is False
    assert brief["rc"] == kr.RC_RESUMABLE


def test_expired_activation_flagged(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    expired = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
    (ws / ".hook_state.json").write_text(
        json.dumps({"expires_at": expired, "active_hooks": []}), encoding="utf-8")
    brief = kr.build_brief(ws)
    assert brief["health"]["activation"]["status"] == "EXPIRED"


# ===========================================================================
# 4. data-age STALE rules (issue comment: per-class thresholds)
# ===========================================================================

def test_stale_plan_warns(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    plan = ws / "global_plan.txt"
    old = datetime.now().timestamp() - 3 * 86400  # >= 2 days
    os.utime(plan, (old, old))
    row = _row(kr.build_brief(ws), "global_plan.txt")
    assert row["flag"] == "plan-stale"


def test_plan_variant_single_source_warning(tmp_path) -> None:
    """D1-family: >1 global_plan* file -> warn (pointer FIX is #446's)."""
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    (ws / "global_plan.v5.yaml").write_text("plan: v5\n", encoding="utf-8")
    brief = kr.build_brief(ws)
    assert len(brief["plan"]["variants"]) >= 2


def test_stale_open_claim_annotated(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, claims=[
        {"id": "C-1", "status": "OPEN", "answers_question": "q1",
         "last_activity_at": "2026-08-17T00:00:00Z"},  # > 24h (claim_expiry line)
    ])
    brief = kr.build_brief(ws)
    assert any(s["id"] == "C-1" for s in brief["stale_claims"])


def test_stale_inprogress_worker_annotated(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    w = ws / "runs" / "worker-status-w9.md"
    w.write_text("# worker w9\nstatus: in-progress\n", encoding="utf-8")
    old = datetime.now().timestamp() - 2 * 3600  # > FRESH_WORKER_MINUTES (20)
    os.utime(w, (old, old))
    brief = kr.build_brief(ws)
    assert any(s["worker"] == "w9" for s in brief["stale_workers"])


def test_fresh_heartbeat_row_ok(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, heartbeat_age_min=2)
    row = _row(kr.build_brief(ws), "runs/.heartbeat.json")
    assert row["flag"] == "ok"


# ===========================================================================
# 5. timeline (issue req: last event -> crash point, human-readable)
# ===========================================================================

def test_breakpoint_timeline_ascending_and_names_crash_point(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, heartbeat_age_min=40)
    brief = kr.build_brief(ws)
    tl = brief["timeline"]
    assert len(tl) >= 4, "timeline must aggregate ledger/heartbeat/log/mtimes"
    ts_list = [e["ts"] for e in tl]
    assert ts_list == sorted(ts_list), "timeline must be oldest -> newest"
    assert "crash" in tl[-1]["note"].lower(), (
        "the newest signal is the crash point — label it")


def test_timeline_includes_ledger_snapshot_and_event_log(tmp_path) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    sources = {e["source"] for e in kr.build_brief(ws)["timeline"]}
    assert ".convergence_ledger.jsonl" in sources
    assert "runs/logs/kunglao-*.jsonl" in sources


# ===========================================================================
# 6. render: text + JSON
# ===========================================================================

def test_json_mode_roundtrip(tmp_path, capsys) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    rc = kr.main([str(ws), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    for key in ("rc", "verdict", "health", "summary", "data_age",
                "timeline", "next_step", "advice", "sources"):
        assert key in data, f"json brief missing {key}"


def test_text_mode_sections(tmp_path, capsys) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    kr.main([str(ws)])
    out = capsys.readouterr().out
    for marker in ("RESUME BRIEF", "verdict", "health", "state summary",
                   "data age", "timeline", "next step"):
        assert marker.lower() in out.lower(), f"text brief missing {marker!r}"


def test_text_mode_names_convergence_as_decision_source(tmp_path, capsys) -> None:
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path)
    kr.main([str(ws)])
    out = capsys.readouterr().out
    assert "convergence_check" in out, "brief must cite its decision source"


def test_text_mode_renders_with_worker_in_flight(tmp_path, capsys) -> None:
    """Review F1 regression: the flagship crash input (>=1 active worker at
    crash time) must render on the DEFAULT text path — was
    `TypeError: object of type 'int' has no len()` from len() on
    decide()'s int active_workers."""
    import kunglao_resume as kr
    ws = _armed_ws_with_active_worker(tmp_path)
    rc = kr.main([str(ws)])
    out = capsys.readouterr().out
    assert rc == kr.RC_RESUMABLE
    assert "workers: 1/3 (2 free)" in out, (
        f"text brief must render the in-flight worker count verbatim, got: {out!r}")


def test_kunglao_entry_text_mode_with_worker_in_flight(tmp_path) -> None:
    """Review F1 regression, second entry point: `kunglao.py resume` (text
    mode, no --json) must render the in-flight-worker brief, not a
    traceback."""
    ws = _armed_ws_with_active_worker(tmp_path / "cli")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao.py"), "resume", str(ws)],
        capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=str(ROOT))
    assert r.returncode == 0, f"stdout={r.stdout[-400:]}\nstderr={r.stderr[-400:]}"
    assert "workers: 1/3" in r.stdout
    assert "Traceback" not in r.stderr


def test_text_mode_counters_withheld_not_faked_when_register_missing(
        tmp_path, capsys) -> None:
    """Counters are withheld ('-') when the decision is withheld — never
    faked as 0 (the old `x or []` fallback rendered a false 0)."""
    import kunglao_resume as kr
    ws = _armed_ws(tmp_path, with_register=False)
    rc = kr.main([str(ws)])
    out = capsys.readouterr().out
    assert rc == kr.RC_MANUAL
    assert "workers: -/-" in out


def test_render_crash_exits_rc_error_with_distinct_message(
        tmp_path, capsys, monkeypatch) -> None:
    """Review F4: an unexpected internal failure must not surface as a bare
    traceback exiting rc 1 — silently colliding with RC_MANUAL's
    needs-a-manual-step verdict. It exits RC_ERROR (same 1, triage surface
    stable) with a stderr message that names it a tool failure."""
    import kunglao_resume as kr

    def _boom(brief: dict) -> str:
        raise RuntimeError("render exploded")

    monkeypatch.setattr(kr, "render_text", _boom)
    rc = kr.main([str(_armed_ws(tmp_path))])
    err = capsys.readouterr().err
    assert rc == kr.RC_ERROR == kr.RC_MANUAL, "RC_ERROR keeps the 0/1/2 triage"
    assert "internal error" in err.lower()
    assert "render exploded" in err, "the underlying exception must survive"
    assert "not a" in err.lower() and "verdict" in err.lower(), (
        "the message must distinguish tool failure from a workspace verdict")


# ===========================================================================
# 7. routing — #456 single source, four-command surface (issue acceptance)
# ===========================================================================

def _registry() -> dict:
    data = yaml.safe_load(REGISTRY_FILE.read_text(encoding="utf-8"))
    return data["subcommands"]


def test_registry_covers_four_commands() -> None:
    reg = _registry()
    # #466 acceptance: registry must be the four-command set; #746 added
    # upgrade to the user-facing slash-command UX surface (the CLI was
    # workspace-internal via #726, now promoted per user 2026-08-26).
    assert set(reg) == {"init", "analysis", "help", "resume", "upgrade"}, (
        f"#466 acceptance: registry must be the four-command set (now five "
        f"after #746): got {sorted(reg)}")


def test_registry_resume_record_complete() -> None:
    rec = _registry()["resume"]
    for field in ("invocation", "argument-hint", "zero-args",
                  "missing-args", "example", "next-step"):
        assert str(rec.get(field, "")).strip(), f"resume.{field} empty"
    assert "<workspace>" in rec["argument-hint"]
    assert rec["invocation"].startswith("/kunglao-agent:resume")


def test_resume_skill_hint_and_no_args_section() -> None:
    text = RESUME_SKILL.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "skills/resume/SKILL.md needs YAML frontmatter"
    fm = yaml.safe_load(m.group(1))
    assert fm.get("argument-hint") == _registry()["resume"]["argument-hint"], (
        "resume hint drifts from subcommands.yaml (#413 defect class)")
    body = text[m.end():]
    sec = re.search(r"^## No arguments.*?$(.*?)(?=^## )", body, re.S | re.M)
    assert sec, "resume needs a '## No arguments' guided-prompt section"
    low = sec.group(1).lower()
    assert "guided" in low and "never guess" in low
    assert "workspace" in low


def test_root_menu_and_routing_render_resume() -> None:
    body = ROOT_SKILL.read_text(encoding="utf-8")
    menu = re.search(r"^## No arguments.*?$(.*?)(?=^## )", body, re.S | re.M).group(1)
    rec = _registry()["resume"]
    assert "/kunglao-agent:resume" in menu, "menu missing the resume command"
    assert rec["example"] in menu, "menu missing the resume example"
    routing = re.search(r"^## Routing$(.*?)(?=^## )", body, re.S | re.M)
    assert routing and "resume" in routing.group(1).lower(), (
        "Routing section must route the resume token")
    assert "crashed" in menu.lower() or "reboot" in menu.lower(), (
        "menu must say what resume is for (crash/reboot recovery)")


def test_readme_and_help_tables_carry_resume_row() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "`/kunglao-agent:resume`" in readme
    help_text = HELP_SKILL.read_text(encoding="utf-8")
    assert "/kunglao-agent:resume" in help_text


def test_kunglao_entry_resume_subcommand_delegates(tmp_path) -> None:
    """scripts/kunglao.py resume <ws> --json == kunglao_resume.main — the
    unified entry must carry the subcommand (issue routing requirement)."""
    ws = _armed_ws(tmp_path / "cli")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao.py"), "resume", str(ws), "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=str(ROOT))
    assert r.returncode == 0, f"stdout={r.stdout[-400:]}\nstderr={r.stderr[-400:]}"
    data = json.loads(r.stdout)
    assert data["summary"]["decision"]["decision"] == "DISPATCH"


def test_cli_matrix_registers_resume_cli() -> None:
    """kunglao_resume.py is a real CLI -> it belongs in the CLIS registry
    (test_cli_matrix) so --help stays convergent."""
    src = (ROOT / "tests" / "test_cli_matrix.py").read_text(encoding="utf-8")
    assert "kunglao_resume.py" in src
