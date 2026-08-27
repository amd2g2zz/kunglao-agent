# -*- coding: utf-8 -*-
"""tests/test_notes_closure_762.py — #762 knowledge-sedimentation closure (K1+K2).

Issue #762 root cause: three broken links in the closure chain. #628/#528 fixed
HOW a note is written and WHAT the queue means — nobody wired WHO triggers,
WHO checks, WHO produces:

  K1a  rollup had NO mechanical trigger (`run_rollup(` zero callers outside
       rollup.py itself; SKILL.md L58 prose was the entire contract). The
       field workspace accumulated ZERO queue entries (notes-due.yaml absent).
       -> heartbeat_tick runs `rollup.py --sweep-terminal` every tick;
          reconciliation semantics (stateless scan + ledger idempotency),
          advisory posture (never fails the tick), event-word `rollup_sweep`.
  K1b  scripts/completion_gate.notes_due existed but hooks/completion_gate
       never consumed it (grep notes = zero hits). -> the Stop shim consults
       it at the would-be-PASS point ONLY (#664 pattern), blocks exit 5
       NOTES_DUE listing the owed claim ids until the notes land.
  K2   workers had no sedimentation channel: plan_vs_actual deltas / bonus
       findings / hypothesis rewrites died in runs/worker-status-*.md.
       -> worker contract section + DONE-line `notes:` field + single-parse-
          point existence validation + ops delivery checklist item.

K3 (hypothesis<->note wiring) is Wave 3 (#759/#761) — this wave leaves a
NotImplementedError seam in notes_writer only.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollup  # noqa: E402


def _make_ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True), encoding="utf-8")
    return ws


def _due_ids(ws: Path) -> list[str]:
    p = ws / "runs" / "notes-due.yaml"
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [e.get("claim_id") for e in data.get("due") or []]


# ===========================================================================
# K1a — reconciliation sweep
# ===========================================================================

class TestSweepQueuesTerminalClaims:
    def test_sweep_queues_notes_due_for_terminal_claim(self, tmp_path):
        """Core: terminal claim lacking its rollup row → the tick sweep rolls
        it up and runs/notes-due.yaml gains the id (K1a closes break-link 1)."""
        ws = _make_ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
        res = rollup.sweep_terminal_claims(ws)
        assert res["ok"] is True, res
        assert "C-1" in res["fired"], res
        assert "C-1" in _due_ids(ws), "queue must gain the owed note obligation"

    def test_repeated_sweep_never_duplicates(self, tmp_path):
        """Acceptance: repeating the tick does not duplicate queue entries —
        ledger idempotency keeps the second pass a no-op."""
        ws = _make_ws(tmp_path, [{"id": "C-1", "status": "NEGATIVE"}])
        rollup.sweep_terminal_claims(ws)
        res2 = rollup.sweep_terminal_claims(ws)
        assert res2["fired"] == [], res2
        assert _due_ids(ws).count("C-1") == 1

    def test_retracted_claims_join_the_sweep(self, tmp_path):
        """RETRACTED is outside status_defs.TERMINAL (#331) but is still a
        closure that owes a durable note — the set comes from the domain owner."""
        ws = _make_ws(tmp_path, [{"id": "C-R", "status": "RETRACTED"}])
        res = rollup.sweep_terminal_claims(ws)
        assert "C-R" in res["fired"], res
        assert "C-R" in _due_ids(ws)

    def test_non_terminal_claims_are_not_pending(self, tmp_path):
        ws = _make_ws(tmp_path, [
            {"id": "C-A", "status": "OPEN"},
            {"id": "C-B", "status": "IN_PROGRESS"},
            {"id": "C-C", "status": "PARTIALLY-VERIFIED"},
        ])
        assert rollup.pending_terminal_claims(ws) == []

    def test_pending_empty_after_sweep(self, tmp_path):
        ws = _make_ws(tmp_path, [{"id": "C-1", "status": "VERIFIED"},
                                 {"id": "C-2", "status": "DEAD"}])
        rollup.sweep_terminal_claims(ws)
        assert rollup.pending_terminal_claims(ws) == []

    def test_note_written_before_rollup_skips_queue(self, tmp_path):
        """Terminal claim whose durable note ALREADY exists owes nothing —
        the queue stays clean (judge-then-revise doctrine intact)."""
        ws = _make_ws(tmp_path, [{"id": "C-9", "status": "PROVEN"}])
        (ws / "notes").mkdir()
        (ws / "notes" / "C-9.md").write_text("---\nid: C-9\n---\nbody\n",
                                             encoding="utf-8")
        rollup.sweep_terminal_claims(ws)
        assert _due_ids(ws) == []


class TestSweepFailOpen:
    def test_missing_register_ok(self, tmp_path):
        """Legacy/foreign workspace: no register → nothing pending, no crash."""
        ws = tmp_path / "bare"
        ws.mkdir()
        res = rollup.sweep_terminal_claims(ws)
        assert res == {"ok": True, "fired": [], "skipped": [], "errors": []}

    def test_corrupt_register_reported_not_raised(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text("{oops: [unclosed",
                                                encoding="utf-8")
        res = rollup.sweep_terminal_claims(ws)
        assert res["ok"] is False and res["errors"], \
            "corrupt register must surface in errors, never raise"

    def test_one_bad_claim_cannot_stop_the_rest(self, tmp_path, monkeypatch):
        """Per-claim exception cage: claim A exploding leaves claim B rolled."""
        ws = _make_ws(tmp_path, [{"id": "C-A", "status": "PROVEN"},
                                 {"id": "C-B", "status": "PROVEN"}])

        real = rollup.run_rollup

        def flaky(workspace, claim_id, status, **kw):
            if claim_id == "C-A":
                raise RuntimeError("simulated sweep crash")
            return real(workspace, claim_id, status, **kw)

        monkeypatch.setattr(rollup, "run_rollup", flaky)
        res = rollup.sweep_terminal_claims(ws)
        assert res["ok"] is False
        assert res["fired"] == ["C-B"]
        assert res["errors"][0]["claim_id"] == "C-A"
        assert "C-B" in _due_ids(ws)


# ===========================================================================
# K1a — tick wiring (mechanical trigger in heartbeat_tick's chain)
# ===========================================================================

def _load_tick(name="heartbeat_tick_762"):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "heartbeat_tick.py")
    ht = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ht)
    return ht


class TestTickWiring:
    def test_tick_runs_the_sweep_step(self, monkeypatch, tmp_path):
        """The tick chain MUST invoke the mechanical trigger."""
        ht = _load_tick()
        calls: dict[str, list] = {}

        def spy(script, ws_arg, *extra):
            calls.setdefault(script, []).append([script, list(extra)])
            return {"script": script, "rc": 0, "stdout": "", "stderr": ""}

        monkeypatch.setattr(ht, "run", spy)
        monkeypatch.setattr(ht, "_oracle_registered", lambda w: True)
        ws = _make_ws(tmp_path, [])
        rc = ht.main([str(ws)])
        assert rc == 0
        assert "rollup.py" in calls, f"tick must run the sweep: {list(calls)}"
        assert "--sweep-terminal" in calls["rollup.py"][0][1]

    def test_sweep_is_advisory_never_fails_tick(self, monkeypatch, tmp_path):
        """A crashed sweep lands in the report but NEVER flips the tick rc or
        the alert flag — 崩溃的 sweep 不能崩 tick (fail-open by design)."""
        ht = _load_tick()

        def broken_sweep(script, ws_arg, *extra):
            if script == "rollup.py":
                return {"script": script, "rc": -1,
                        "stdout": "EXC simulated crash", "stderr": ""}
            return {"script": script, "rc": 0, "stdout": "", "stderr": ""}

        monkeypatch.setattr(ht, "run", broken_sweep)
        monkeypatch.setattr(ht, "_oracle_registered", lambda w: True)
        ws = _make_ws(tmp_path, [])
        rc = ht.main([str(ws)])
        assert rc == 0, "advisory step must not weigh into rc/alert"
        report = json.loads((ws / "runs" / ".heartbeat-tick.json").read_text())
        assert report["rollup_sweep"]["rc"] == -1
        assert report["alert"] is False
        assert report["first_failure"] is None


# ===========================================================================
# K1a — CLI compat (legacy invocation unchanged, sweep mode added)
# ===========================================================================

class TestCliCompat:
    def test_sweep_mode_end_to_end(self, tmp_path):
        ws = _make_ws(tmp_path, [{"id": "C-1", "status": "REFUTED"}])
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "rollup.py"), str(ws),
             "--sweep-terminal"],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "C-1" in _due_ids(ws)

    def test_legacy_invocation_still_fires(self, tmp_path):
        """The pre-#762 contract byte-for-byte: <ws> <cid> --status PROVEN."""
        ws = _make_ws(tmp_path, [{"id": "C-L", "status": "PROVEN"}])
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "rollup.py"), str(ws),
             "C-L", "--status", "PROVEN"],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "C-L" in _due_ids(ws)

    def test_mixing_sweep_with_single_claim_rejected(self, tmp_path):
        ws = _make_ws(tmp_path, [])
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "rollup.py"), str(ws),
             "C-1", "--status", "PROVEN", "--sweep-terminal"],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 2, "mode mixing is an invocation error"

    def test_legacy_error_when_status_missing(self, tmp_path):
        ws = _make_ws(tmp_path, [])
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "rollup.py"), str(ws), "C-1"],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 2, "single-claim mode still requires --status"


# ===========================================================================
# K1a — observability vocabulary
# ===========================================================================

def test_emit_actions_registers_rollup_sweep():
    import event_taxonomy as et
    assert "rollup_sweep" in et.EMIT_ACTIONS
    assert et.EMIT_ACTIONS == sorted(set(et.EMIT_ACTIONS)), \
        "controlled vocab stays sorted+unique"


# ===========================================================================
# K1b — the Stop face consumes the owed-queue (would-be-PASS interception)
# ===========================================================================

HOOKS = ROOT / "hooks"


def _load_scripts_gate():
    """Unique-name by-path load of scripts/completion_gate.py (#671 posture:
    bare `import completion_gate` is ambiguous once any suite prepends
    hooks/ to sys.path — test_event_stream_adoption does exactly that, so
    the shim would shadow the gate module for late importers)."""
    name = "completion_gate_scripts_762"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, SCRIPTS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _load_shim():
    name = "completion_gate_hook_762"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _activated_state(ws: Path) -> None:
    """Real-schema .hook_state.json that is_active_strict accepts."""
    import datetime as dt
    expires = (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(minutes=30)
               ).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": "2026-08-13T00:00:00Z",
        "tier": "none",
        "phase": "IDLE",
        "active_hooks": ["completion_gate"],
        "paused_hooks": [],
        "user_override": {},
        "expires_at": expires,
    }), encoding="utf-8")


def _would_pass_oracle(ws: Path, **extra) -> None:
    """Oracle that judge() PASSes: task_text anchored, every item closed,
    no deferrals. No workspace_path key → contradiction + intent checks
    skip per their own D4 fail-open rules (isolates the notes face)."""
    oracle = {
        "task_text": "analyze the payload",
        "open_items": [{"id": "OC-1", "closed_by": "verifier"}],
    }
    oracle.update(extra)
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False), encoding="utf-8")


class TestStopFaceNotesDue:
    def test_pass_blocked_while_notes_due(self, tmp_path):
        """K1b core: items all closed, queue owes notes → exit 5 block naming
        the owed claim ids with write guidance (break-link 2 closes)."""
        shim = _load_shim()
        ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
        rollup.sweep_terminal_claims(ws)  # T1 mechanics build the real queue
        _activated_state(ws)
        _would_pass_oracle(ws)
        rc = shim.process_event({"cwd": str(ws)})
        assert rc == 5, f"owed durable note must refuse closure, got rc={rc}"
        # shim-level reason is observable via the CLI path below

    def test_block_reason_lists_owed_ids_and_guidance(self, tmp_path, capsys):
        shim = _load_shim()
        ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"},
                                 {"id": "C-102", "status": "PROVEN"}])
        rollup.sweep_terminal_claims(ws)
        _activated_state(ws)
        _would_pass_oracle(ws)
        rc = shim.process_event({"cwd": str(ws)})
        out = capsys.readouterr().out
        decision = json.loads(out)
        assert rc == 5 and decision["decision"] == "block"
        reason = decision["reason"]
        for fragment in ("NOTES_DUE", "C-302", "C-102",
                         "notes/<claim-id>.md"):
            assert fragment in reason, f"reason must carry {fragment}: {reason}"

    def test_writing_the_note_allows_closure(self, tmp_path, capsys):
        """judge-then-revise: orchestrator writes the owed note → next Stop
        passes (reader drops the written entry; nothing auto-writes it)."""
        shim = _load_shim()
        ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
        rollup.sweep_terminal_claims(ws)
        _activated_state(ws)
        _would_pass_oracle(ws)
        (ws / "notes").mkdir(exist_ok=True)
        (ws / "notes" / "C-302.md").write_text(
            "---\nid: C-302\nclaim_id: C-302\nverify_status: pending\n"
            "---\n# durable result\n", encoding="utf-8")
        rc = shim.process_event({"cwd": str(ws)})
        assert rc == 0, f"written note must clear the obligation, got rc={rc}"
        assert capsys.readouterr().out.strip() == "", \
            "PASS must emit no block decision"

    def test_item_defects_outrank_notes_due(self, tmp_path):
        """Item-level problems strictly outrank the owed-notes interception:
        an unclosed item still exits 1 even when notes are due (no double-
        blocking, no new deadlock surface mid-run)."""
        shim = _load_shim()
        ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
        rollup.sweep_terminal_claims(ws)
        _activated_state(ws)
        _would_pass_oracle(ws, open_items=[{"id": "OC-9"}])  # NOT closed
        assert shim.process_event({"cwd": str(ws)}) == 1

    def test_inactive_session_never_blocked_by_queue(self, tmp_path):
        """The notes check lives INSIDE the activated-workspace branch: a
        workspace without activation passes through untouched (opt-in face
        unchanged)."""
        shim = _load_shim()
        ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
        rollup.sweep_terminal_claims(ws)
        _would_pass_oracle(ws)
        assert shim.process_event({"cwd": str(ws)}) == 0


class TestNotesQueueFailOpen:
    def test_legacy_workspace_without_queue_passes(self, tmp_path):
        shim = _load_shim()
        ws = _make_ws(tmp_path, [])
        _activated_state(ws)
        _would_pass_oracle(ws)
        assert shim.process_event({"cwd": str(ws)}) == 0, \
            "absent queue = fail-open (a legacy ws must never be blocked)"

    def test_corrupt_queue_blocks_nothing(self, tmp_path):
        gate = _load_scripts_gate()
        shim = _load_shim()
        ws = _make_ws(tmp_path, [])
        _activated_state(ws)
        _would_pass_oracle(ws)
        (ws / "runs" / "notes-due.yaml").write_text("{not: [valid", encoding="utf-8")
        assert gate.notes_due(ws) == []
        assert shim.process_event({"cwd": str(ws)}) == 0

    def test_malformed_entry_shapes_degrade_to_no_obligation(self, tmp_path):
        """due: [bare-string, 42, {}] — non-mapping entries carry no id and
        must not crash the reader into a blocked session."""
        gate = _load_scripts_gate()
        ws = _make_ws(tmp_path, [])
        (ws / "runs" / "notes-due.yaml").write_text(
            'due:\n- bare string\n- 42\n- {}\n', encoding="utf-8")
        assert gate.notes_due(ws) == []

    def test_reader_keeps_628_semantics(self, tmp_path):
        """The #628 reader contract survives hardening: owed ids surfaced,
        written notes dropped."""
        gate = _load_scripts_gate()
        ws = _make_ws(tmp_path, [])
        (ws / "runs" / "notes-due.yaml").write_text(
            'due:\n- {claim_id: C-A}\n- {claim_id: C-B}\n', encoding="utf-8")
        (ws / "notes").mkdir()
        (ws / "notes" / "C-B.md").write_text("note\n", encoding="utf-8")
        assert gate.notes_due(ws) == ["C-A"]


def test_noted_exit_code_is_five_and_documented():
    """The new code is distinct from {0..4} and named in the shim source so
    the exit-code table cannot silently drift."""
    shim_src = (HOOKS / "completion_gate.py").read_text(encoding="utf-8")
    assert "EXIT_NOTES_DUE = 5" in shim_src
    assert "NOTES_DUE" in shim_src


# ===========================================================================
# K2 — worker sedimentation contract (text face + single-parse-point face)
# ===========================================================================

WORKER_MD = ROOT / "agents" / "kunglao-worker.md"


def _load_protocol():
    """hooks/lib_kunglao.py under the repo's canonical unique name (the
    #444 posture: bare `import lib_kunglao` is ambiguous under pytest)."""
    name = "lib_kunglao_hooks"
    lib = sys.modules.get(name)
    if lib is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "lib_kunglao.py")
        lib = importlib.util.module_from_spec(spec)
        sys.modules[name] = lib
        spec.loader.exec_module(lib)
    return lib


def test_worker_contract_has_sedimentation_section():
    """K2 text face: the worker owns a knowledge-sedimentation section with
    the three content lanes and the NotesWriter frontmatter contract."""
    text = WORKER_MD.read_text(encoding="utf-8")
    for fragment in ("Knowledge sedimentation", "notes/<claim-id>.md",
                     "plan_vs_actual", "bonus"):
        assert fragment in text, f"contract must teach {fragment}"
    # frontmatter contract the convergence note-gate reads (#528 writer):
    assert "verify_status: pending" in text
    assert "supersedes" in text, \
        "corrections chain through supersedes, never silent overwrite"
    assert '<!-- contract: knowledge-sedimentation -->' in text or 'Knowledge sedimentation' in text

def test_worker_done_line_template_declares_notes():
    """The machine-checkable shape: the final done line declares the note
    next to artifacts, on the SAME line (append-only protocol, one read)."""
    text = WORKER_MD.read_text(encoding="utf-8")
    import re
    assert re.search(r"status: done \| artifacts:[^|\n]*\| notes: notes/",
                     text), \
        "DONE-line template must carry a `| notes: notes/<id>.md` field"


class TestDoneLineMechanicalFace:
    """K2 mechanical face lives at THE single parse point (#444 AC-1):
    hooks/lib_kunglao.py parses + existence-checks declared notes."""

    def _ws_with_status_file(self, tmp_path: Path, body: str) -> Path:
        ws = tmp_path / "ws"
        runs = ws / "runs"
        runs.mkdir(parents=True)
        (runs / "worker-status-w1.md").write_text(body, encoding="utf-8")
        return ws

    DONE_BODY = (
        "[10:00] step: started C-302 | status: in-progress\n"
        "[10:20] step: complete C-302 | status: done | "
        "artifacts: facts/F001-x.md | notes: notes/C-302.md\n")

    def test_parse_declared_notes_reads_the_template_shape(self):
        lib = _load_protocol()
        assert lib.parse_declared_notes(self.DONE_BODY) == ["notes/C-302.md"]

    def test_parse_declared_notes_split_and_dedupe_like_artifacts(self):
        lib = _load_protocol()
        body = "[x] a | status: failed\n[y] b | notes: notes/A.md, notes/B.md; notes/A.md\n"
        assert lib.parse_declared_notes(body) == ["notes/A.md", "notes/B.md"]

    def test_parse_declared_notes_empty_when_absent_or_none(self):
        lib = _load_protocol()
        assert lib.parse_declared_notes("[x] done | artifacts: f.md") == []
        assert lib.parse_declared_notes("[x] done | notes: none") == []

    def test_iter_states_rows_carry_notes_key(self, tmp_path):
        lib = _load_protocol()
        ws = self._ws_with_status_file(tmp_path, self.DONE_BODY)
        rows = lib.iter_worker_states(ws)
        assert len(rows) == 1 and rows[0]["status"] == "done"
        assert rows[0]["notes"] == ["notes/C-302.md"]

    def test_missing_declared_note_is_a_violation(self, tmp_path):
        """A done file that DECLARES a note must point at an existing file —
        same 'references must be real' law as the W-15 artifacts check."""
        lib = _load_protocol()
        ws = self._ws_with_status_file(tmp_path, self.DONE_BODY)
        (ws / "facts").mkdir()  # artifact exists; note does NOT
        (ws / "facts" / "F001-x.md").write_text("x\n", encoding="utf-8")
        v = lib.scan_done_artifact_violations(ws)
        kinds = [(x["kind"], x["missing"]) for x in v]
        assert ("declared-note-missing", ["notes/C-302.md"]) in kinds, kinds

    def test_present_note_is_clean(self, tmp_path):
        lib = _load_protocol()
        ws = self._ws_with_status_file(tmp_path, self.DONE_BODY)
        (ws / "facts").mkdir(); (ws / "facts" / "F001-x.md").write_text("x\n", encoding="utf-8")
        notes = ws / "notes"; notes.mkdir(exist_ok=True)
        (notes / "C-302.md").write_text("---\nid: C-302\n---\nbody\n", encoding="utf-8")
        assert lib.scan_done_artifact_violations(ws) == []

    def test_legacy_done_without_notes_line_stays_exempt(self, tmp_path):
        """Opt-in, exactly like #444 artifacts: no declaration -> no liveness
        penalty (owed-NESS is the Stop gate's business, D5 division)."""
        lib = _load_protocol()
        legacy = ("[10:00] step: started | status: in-progress\n"
                  "[10:30] status: done | artifacts: runs/r.md\n")
        ws = self._ws_with_status_file(tmp_path, legacy)
        (ws / "runs" / "r.md").write_text("report\n", encoding="utf-8")
        assert lib.scan_done_artifact_violations(ws) == []


def test_ops_mechanics_delivery_checklist_covers_notes():
    """The orchestrator's delivery checklist verifies the note BEFORE
    TaskStop, and names where a skipped closure resurfaces (Stop gate)."""
    text = (ROOT / "references" / "operational-mechanics.md").read_text(encoding="utf-8")
    assert "notes/<claim-id>.md" in text
    assert "NOTES_DUE" in text


# ===========================================================================
# K3 seam — placeholder ONLY (real wiring is Wave 3: J3/H2 → #759/#761)
# ===========================================================================

def _load_notes_writer():
    name = "notes_writer_762"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, SCRIPTS / "notes_writer.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def test_k3_seam_is_wired_for_wave_3(tmp_path):
    """#759 Wave 3 landed the reserved seam (#762 K3): the name no longer
    raises NotImplementedError — it performs the real hypothesis retirement.
    Full trio coverage (transition + event + affected_claims) lives in
    tests/test_cognition_759.py; here we pin only that the placeholder era
    is over, so a future stub-regression turns red in THIS suite too."""
    nw = _load_notes_writer()
    assert hasattr(nw, "note_supersedes_hypothesis")
    ws = tmp_path / "ws"
    (ws / "notes").mkdir(parents=True)
    hyp = ws / "hypotheses"
    hyp.mkdir()
    (hyp / "H-001.md").write_text(
        "---\nid: H-001\nclaim_id: C-1\ncompetitor_group: g\ncandidates: []\n"
        "status: open\nschema_rev: 1\n---\nbody\n", encoding="utf-8")
    (ws / "notes" / "N-1.md").write_text(
        "---\nid: N-1\nclaim_id: C-1\nverify_status: pending\n"
        "supersedes_hypothesis: H-001\n---\nbody\n", encoding="utf-8")
    out = nw.note_supersedes_hypothesis(ws / "notes", "N-1",
                                        hypotheses_dir=hyp)
    assert out["ok"] is True and out["affected_claims"] == ["C-1"]
