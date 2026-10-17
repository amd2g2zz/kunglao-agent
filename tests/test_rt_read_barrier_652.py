# -*- coding: utf-8 -*-
"""tests/test_rt_read_barrier_652.py — the RT read barrier is
MECHANICAL, not prompt-enforced.

RED: `agents/kunglao-redteam.md` allowedTools is (Read, Glob, Grep, Bash, ...)
and the act rides DEFAULT_RACK (scripts/e2e/llm_faces.py) — nothing denied
facts/F<NNN>*.md, notes/, runs/verification-<claim>.md, or
runs/worker-status-*.md. Blindness was self-reported in the RT artifact;
facts/_INDEX.md was explicitly allowed and names the exact target fact ids
(one Read from the forbidden conclusion).

Fix under test: hooks/rt_read_barrier.py — a PreToolUse(Read|Glob|Grep|Bash)
deny face keyed on the subagent identity Claude Code puts in the hook
payload (`agent_type`, verified live on 2.1.270), plus a UserPromptSubmit
arming face for the top-level `claude -p` act shape (e2e RT acts): a prompt
carrying the v1 dispatch envelope with `agent: kunglao-redteam` arms that
session; its tool calls then ride the same deny list. evidence/** stays
readable; facts/_INDEX.md is CLOSED for RT acts (it names the ids).
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_hook():
    spec = importlib.util.spec_from_file_location(
        "rt_read_barrier_uut", ROOT / "hooks" / "rt_read_barrier.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text("---\nid: F001\n---\n", encoding="utf-8")
    (ws / "facts" / "_INDEX.md").write_text("F001 — conclusion: md5\n", encoding="utf-8")
    (ws / "notes").mkdir()
    (ws / "notes" / "n.md").write_text("maker note\n", encoding="utf-8")
    (ws / "runs").mkdir()
    (ws / "runs" / "verification-C-1.md").write_text("verdict: verified\n", encoding="utf-8")
    (ws / "runs" / "worker-status-w1.md").write_text("status: in-progress\n", encoding="utf-8")
    (ws / "runs" / "C-1-verify-note.md").write_text("passes\n", encoding="utf-8")
    (ws / "runs" / "method-family-log.jsonl").write_text(
        '{"sentinel": "LEARN_POISON_FAMILY"}\n', encoding="utf-8")
    (ws / "runs" / "q-cell-log.jsonl").write_text(
        '{"sentinel": "LEARN_POISON_QCELL"}\n', encoding="utf-8")
    (ws / "evidence").mkdir()
    (ws / "evidence" / "replay-C-1.json").write_text('{"claim_id": "C-1"}', encoding="utf-8")
    (ws / "evidence" / "verdict.json").write_text('{"verdict": "PASS"}', encoding="utf-8")
    return ws


def _payload(ws: Path, tool: str, tool_input: dict, *,
             agent_type: str | None = None, session: str | None = None) -> dict:
    p = {"cwd": str(ws), "tool_name": tool, "tool_input": tool_input}
    if agent_type is not None:
        p["agent_type"] = agent_type
        p["agent_id"] = "a1b2c3"
    if session is not None:
        p["session_id"] = session
    return p


_RT = "kunglao-redteam"


# ---------- the barrier: RT subagent identity (mechanically present) -------

def test_rt_subagent_read_of_target_fact_rejected(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, err, ctx = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")},
                 agent_type=_RT))
    assert rc == 2, "an RT act must be mechanically unable to read a maker fact"
    assert "REJECT rt_read_barrier" in err, "stderr carries the verdict"
    assert ctx and "evidence" in ctx, "repair path names the allowed face"


def test_rt_read_of_evidence_stays_open(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, err, ctx = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "evidence" / "replay-C-1.json")},
                 agent_type=_RT))
    assert (rc, err, ctx) == (0, "", None), \
        "evidence/** is the RT act's WORKING face — it must stay readable"


def test_fact_index_closed_for_rt(tmp_path):
    """facts/_INDEX.md names the exact fact ids AND titles — the one-Read
    hop to the forbidden conclusion; the barrier closes it for RT acts."""
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, _err, _ctx = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "_INDEX.md")},
                 agent_type=_RT))
    assert rc == 2


def test_notes_verification_status_and_note_faces_rejected(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    for rel in ("notes/n.md", "runs/verification-C-1.md",
                "runs/worker-status-w1.md", "runs/C-1-verify-note.md",
                "evidence/verdict.json"):
        rc, err, _ctx = mod.evaluate(
            _payload(ws, "Read", {"file_path": str(ws / rel)}, agent_type=_RT))
        assert rc == 2, f"{rel} must be denied for an RT act"
        assert "REJECT rt_read_barrier" in err


def test_relative_paths_resolve_against_cwd(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, _err, _ctx = mod.evaluate(
        _payload(ws, "Read", {"file_path": "facts/F001.md"}, agent_type=_RT))
    assert rc == 2, "relative Read targets must normalize to the workspace faces"


def test_glob_and_grep_cannot_mine_the_faces(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    # root inside facts/ → deny
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Glob", {"path": str(ws / "facts"), "pattern": "*.md"},
                 agent_type=_RT))
    assert rc == 2, "Glob scoped INTO facts/ is the mining attack"
    # unscoped (cwd == ws root) → deny
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Grep", {"pattern": "md5"}, agent_type=_RT))
    assert rc == 2, "unscoped Grep sweeps facts/ — must be denied"
    # pattern targeting the faces from elsewhere → deny
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Glob", {"path": str(ws), "pattern": "facts/**/*.md"},
                 agent_type=_RT))
    assert rc == 2, "a pattern naming facts/ is the same read"
    # scoped to evidence/ → allow
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Grep", {"pattern": "md5", "path": str(ws / "evidence")},
                 agent_type=_RT))
    assert rc == 0, "Grep scoped to evidence/ is the working face"


def test_bash_direct_reads_rejected_and_compares_allowed(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, err, _ctx = mod.evaluate(
        _payload(ws, "Bash", {"command": "cat facts/F001.md"}, agent_type=_RT))
    assert rc == 2, "cat facts/F001.md is the read the barrier exists for"
    assert "REJECT rt_read_barrier" in err
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Bash", {"command": "grep -rn md5 notes/"}, agent_type=_RT))
    assert rc == 2
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Bash",
                 {"command": "cmp evidence/a.json evidence/b.json && sha256sum evidence/a.json"},
                 agent_type=_RT))
    assert rc == 0, "byte-exact comparison over evidence/ must keep working"


def test_rt_cannot_re_delegate_via_agent_tool(tmp_path):
    """An RT act dispatching a helper would launder the read through a
    differently-identified subagent — the dispatch itself is denied."""
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, _err, _ctx = mod.evaluate(
        _payload(ws, "Agent", {"prompt": "read facts/F001.md",
                               "subagent_type": "general-purpose"},
                 agent_type=_RT))
    assert rc == 2


# ---------- non-RT callers are untouched -----------------------------------

def test_worker_subagent_unaffected(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, err, ctx = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")},
                 agent_type="kunglao-worker"))
    assert (rc, err, ctx) == (0, "", None), \
        "the maker IS allowed its own fact — only RT acts are blinded"


def test_main_agent_unarmed_session_unaffected(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")}))
    assert rc == 0, "the orchestrator keeps its state faces"


# ---------- the armed-session face (top-level `claude -p` act shape) -------

def test_userpromptsubmit_arms_rt_session_and_blocks_reads(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    envelope = json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1, "agent": "kunglao-redteam"}})
    rc = mod.main_face_user_prompt({"cwd": str(ws), "session_id": "sess-rt-1",
                                    "prompt": envelope + "\n\nclaim: C-1\n"})
    assert rc == 0, "arming is a recorder — it never blocks a prompt"
    # the armed session's own tool calls ride the deny list (no agent_type)
    rc, err, _ctx = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")},
                 session="sess-rt-1"))
    assert rc == 2, "the armed RT session must not read the maker fact"
    assert "REJECT rt_read_barrier" in err
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "evidence" / "replay-C-1.json")},
                 session="sess-rt-1"))
    assert rc == 0, "evidence/ stays readable in the armed session"


def test_arming_only_fires_for_redteam_envelopes(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    envelope = json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1, "agent": "kunglao-worker"}})
    rc = mod.main_face_user_prompt({"cwd": str(ws), "session_id": "sess-w-1",
                                    "prompt": envelope})
    assert rc == 0
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")},
                 session="sess-w-1"))
    assert rc == 0, "a worker-act session is NOT armed"


def test_worker_subagent_inside_armed_session_keeps_its_own_identity(tmp_path):
    """agent_type, when present, is authoritative: a worker subagent is not
    blinded just because some outer session got armed."""
    mod = _load_hook()
    ws = _ws(tmp_path)
    mod.main_face_user_prompt({
        "cwd": str(ws), "session_id": "sess-rt-2",
        "prompt": json.dumps({"kunglao_dispatch": {
            "version": 1, "claim": "C-1", "tier": 1,
            "agent": "kunglao-redteam"}})})
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")},
                 agent_type="kunglao-worker", session="sess-rt-2"))
    assert rc == 0


# ---------- main() faces ---------------------------------------------------

def test_main_pretooluse_face_emits_rc2_and_durable_row(tmp_path, monkeypatch, capsys):
    mod = _load_hook()
    ws = _ws(tmp_path)
    payload = _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")},
                       agent_type=_RT)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rc = mod.main()
    assert rc == 2
    out = capsys.readouterr()
    assert "rt_read_barrier" in out.err
    doc = json.loads(out.out)
    assert doc["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    rows = []
    for f in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows += [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
    hits = [r for r in rows if r.get("action") == "rt_read_blocked"]
    assert hits, "the REJECT must also be durable (runs/logs row)"
    assert hits[0].get("exit") == 2


# ---------- registration + markers -----------------------------------------

def test_registered_in_wire_up_and_subset_tables():
    wu = (ROOT / "scripts" / "wire_up_settings.py").read_text(encoding="utf-8")
    assert "rt_read_barrier.py" in wu, "must be in WIRE_UP_HOOK_FILES"
    ha = (ROOT / "scripts" / "hook_activation.py").read_text(encoding="utf-8")
    assert "rt_read_barrier.py" in ha, "register_hooks must wire it"
    ek = (ROOT / "scripts" / "external_kicker.py").read_text(encoding="utf-8")
    assert "rt_read_barrier.py" in ek, "must join _KICKER_SKIP_FILES"
    hs = (ROOT / "scripts" / "hooks_selfcheck.py").read_text(encoding="utf-8")
    assert "rt_read_barrier.py" in hs, "must join _KONG_SKIP_FILES"


def test_marker_family_matches_the_canonical_verifier_markers():
    mod = _load_hook()
    import blind_gate
    assert "kunglao-redteam" in mod.REDTEAM_AGENT_MARKERS
    assert set(mod.REDTEAM_AGENT_MARKERS) & set(blind_gate.VERIFIER_AGENT_MARKERS), \
        ("the barrier's identity family must intersect the canonical "
         "VERIFIER_AGENT_MARKERS (a renamed agent must not silently "
         "de-blind the act)")


# ---------- issue-687: the settler family rides the same barrier ----------

def test_settler_read_of_maker_and_learning_faces_rejected(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    for rel in ("runs/method-family-log.jsonl", "runs/q-cell-log.jsonl",
                "runs/experience.jsonl",  # #721: the consolidated feed
                "notes/n.md", "runs/worker-status-w1.md",
                "runs/verification-C-1.md", "runs/C-1-verify-note.md",
                "facts/F001.md", "evidence/verdict.json"):
        rc, err, _ctx = mod.evaluate(
            _payload(ws, "Read", {"file_path": str(ws / rel)},
                     agent_type="kunglao-settler"))
        assert rc == 2, f"a settler act must be denied {rel}"
        assert "REJECT rt_read_barrier" in err


def test_learning_faces_denied_to_rt_acts_too(tmp_path):
    """The two learning logs joined the shared deny face: an RT act is
    blinded from arm identity/values as well. #721: their consolidated
    home (runs/experience.jsonl) rides the same wall."""
    mod = _load_hook()
    ws = _ws(tmp_path)
    for rel in ("runs/method-family-log.jsonl", "runs/q-cell-log.jsonl",
                "runs/experience.jsonl"):
        rc, _err, _ctx = mod.evaluate(
            _payload(ws, "Read", {"file_path": str(ws / rel)},
                     agent_type=_RT))
        assert rc == 2, f"{rel} must be denied for an RT act"


def test_learning_faces_denied_on_bash_and_pattern_faces(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Bash",
                 {"command": "cat runs/method-family-log.jsonl"},
                 agent_type="kunglao-settler"))
    assert rc == 2, "Bash path tokens ride the same deny face"
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Bash",
                 {"command": "tail -n 5 runs/experience.jsonl"},  # #721
                 agent_type="kunglao-settler"))
    assert rc == 2, "the consolidated feed is a Bash-denied path token"
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Glob",
                 {"path": str(ws / "evidence"),
                  "pattern": "*/q-cell-log.jsonl"},
                 agent_type="kunglao-settler"))
    assert rc == 2, "a pattern naming a learning face is the same read"
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Glob",
                 {"path": str(ws / "runs"),
                  "pattern": "*experience.jsonl"},  # #721
                 agent_type="kunglao-settler"))
    assert rc == 2, "a pattern naming the consolidated feed is denied too"


def test_settler_working_face_and_worker_untouched(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    rc, err, ctx = mod.evaluate(
        _payload(ws, "Read",
                 {"file_path": str(ws / "evidence" / "replay-C-1.json")},
                 agent_type="kunglao-settler"))
    assert (rc, err, ctx) == (0, "", None), \
        "raw evidence is the settler's working face"
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")},
                 agent_type="kunglao-worker"))
    assert rc == 0, "the maker keeps its own fact"


def test_settler_session_arms_from_dispatch_envelope(tmp_path):
    mod = _load_hook()
    ws = _ws(tmp_path)
    envelope = json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1, "agent": "kunglao-settler"}})
    rc = mod.main_face_user_prompt(
        {"cwd": str(ws), "session_id": "sess-settle-1", "prompt": envelope})
    assert rc == 0, "arming is a recorder — it never blocks a prompt"
    rc, err, _ctx = mod.evaluate(
        _payload(ws, "Read",
                 {"file_path": str(ws / "runs" / "q-cell-log.jsonl")},
                 session="sess-settle-1"))
    assert rc == 2, "the armed settler session rides the deny list"
    assert "REJECT rt_read_barrier" in err
    # a worker envelope never arms
    rc = mod.main_face_user_prompt(
        {"cwd": str(ws), "session_id": "sess-w2",
         "prompt": json.dumps({"kunglao_dispatch": {
             "version": 1, "claim": "C-1", "tier": 1,
             "agent": "kunglao-worker"}})})
    assert rc == 0
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "facts" / "F001.md")},
                 session="sess-w2"))
    assert rc == 0


def test_settler_identity_family_registered():
    mod = _load_hook()
    assert "kunglao-settler" in mod.SETTLER_AGENT_MARKERS
    assert mod.blind_act_class({"agent_type": "kunglao-settler"}) == "settler"
    assert mod.blind_act_class({"agent_type": "kunglao-redteam"}) == "redteam"
    assert mod.blind_act_class({"agent_type": "kunglao-worker"}) is None
    assert mod.blind_act_class({}) is None


# ---------- issue-687 hardening: aliases, arms, own status ---------------

def test_case_variant_aliases_still_denied(tmp_path):
    """Case aliases route around NOTHING: the dev filesystem is
    case-insensitive, so every path/token comparison is folded."""
    mod = _load_hook()
    ws = _ws(tmp_path)
    for rel in ("Runs/Method-Family-Log.Jsonl", "Notes/n.md",
                "Facts/F001.md", "Runs/Worker-Status-W1.MD"):
        for actor in (_RT, "kunglao-settler"):
            rc, err, _ctx = mod.evaluate(
                _payload(ws, "Read", {"file_path": str(ws / rel)},
                         agent_type=actor))
            assert rc == 2, f"{actor} must be denied the alias {rel}"
            assert "REJECT rt_read_barrier" in err
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Bash", {"command": "cat Notes/n.md"},
                 agent_type="kunglao-settler"))
    assert rc == 2, "Bash path tokens are case-folded too"


def test_armed_session_with_blank_agent_stays_blind(tmp_path):
    """Arming only RESTRICTS: a legacy or hand-edited arm row without a
    recognizable agent still rides the deny list (the family merely
    selects the reject message)."""
    mod = _load_hook()
    ws = _ws(tmp_path)
    mod.arm_session(ws, "sess-legacy", claim="C-1", agent="")
    rc, err, _ctx = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(ws / "notes" / "n.md")},
                 session="sess-legacy"))
    assert rc == 2, "an armed session is blind by construction"
    assert "REJECT rt_read_barrier" in err


def test_own_status_face_is_exempt_only_for_its_own_actor(tmp_path):
    """A blind act's OWN liveness file is its one exempt worker-status
    face (narrative-free by construction); every foreign status — any
    family — stays denied, and a Bash command mixing own + foreign
    tokens still denies."""
    mod = _load_hook()
    ws = _ws(tmp_path)
    own = ws / "runs" / "worker-status-kunglao-settler-1.md"
    own.write_text("plan\n", encoding="utf-8")
    rt_own = ws / "runs" / "worker-status-kunglao-redteam-1.md"
    rt_own.write_text("plan\n", encoding="utf-8")
    other = ws / "runs" / "worker-status-w1.md"
    # own liveness file: targeted Read + Bash append allowed
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(own)},
                 agent_type="kunglao-settler"))
    assert rc == 0
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Bash",
                 {"command": "echo 'status: in-progress' >> "
                             "runs/worker-status-kunglao-settler-1.md"},
                 agent_type="kunglao-settler"))
    assert rc == 0, "an act may append to its OWN status line"
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Read", {"file_path": str(rt_own)},
                 agent_type="kunglao-redteam"))
    assert rc == 0, "the red-team's own status face is exempt too"
    # foreign statuses stay closed
    for target, actor in ((rt_own, "kunglao-settler"),
                          (other, "kunglao-redteam"),
                          (own, "kunglao-redteam")):
        rc, _e, _c = mod.evaluate(
            _payload(ws, "Read", {"file_path": str(target)},
                     agent_type=actor))
        assert rc == 2, f"{actor} must not read {target.name}"
    rc, _e, _c = mod.evaluate(
        _payload(ws, "Bash",
                 {"command": "cat runs/worker-status-kunglao-settler-1.md "
                             "runs/worker-status-w1.md"},
                 agent_type="kunglao-settler"))
    assert rc == 2, "one foreign token and the whole command denies"
