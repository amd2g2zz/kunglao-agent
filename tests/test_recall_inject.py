# -*- coding: utf-8 -*-
"""Tests for hooks/recall_inject.py — PreToolUse runtime knowledge recall (#268).

Acceptance (issue #268):
  - claim dispatch payload (kunglao workspace + `[T<N> tools=...] claim C-NN`
    description) -> additionalContext with recall guidance naming the reference
    files references_recall.py actually returns for the claim's features
  - claim features hit the right references: go -> languages-go.md; VM/dynamic
    -> dynamic-re-tool-priority.md + tools-dynamic.md (+ verify-static-vs-dynamic.md);
    disasm/static -> anti-analysis.md
  - recall failure (subprocess raises / rc != 0) -> exit 0, EMPTY context, no
    raise — recall must NEVER block dispatch
  - non-dispatch / non-kunglao payloads -> exit 0, empty context
  - rc is always 0: this hook injects knowledge, never rejects
  - failure_analysis_gate BLOCKED rows append the failure-modes recall (#268 item 3)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from recall_inject import (  # pytest.ini pythonpath = . hooks scripts tools
    evaluate,
    queries_for_features,
)

# ---- helpers (mirror test_env_check_gate fixture style) ----


def _kunglao_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    return ws


def _payload(ws: Path, prompt: str) -> dict:
    return {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": prompt},
    }


# Claim descriptions (dispatch prompts) with distinct feature sets. The
# assertions below are pinned to the REAL references_recall.py outputs for the
# mapped queries (verified 2026-08-13): 'go' -> languages-go.md top;
# 'vm' -> dynamic-re-tool-priority.md top; 'dynamic' -> dynamic-re-tool-priority.md,
# verify-static-vs-dynamic.md, re-library/tools/dynamic/tools-dynamic.md; 'static analysis'
# -> re-library/anti-analysis/catalog/anti-analysis.md top.

VM_CLAIM = (
    "[T3 tools=mcp__x64dbg__*,mcp__frida__*] claim C-101 observe the sample's "
    "dynamic behavior in the VM with x64dbg breakpoints and frida injection, "
    "then dump the runtime state"
)
GO_CLAIM = (
    "[T2 tools=ghidra] claim C-102 reverse the go binary to recover its "
    "symbol table and go runtime structures"
)
DISASM_CLAIM = (
    "[T2 tools=ghidra] claim C-103 disassemble the unpacked sample and decode "
    "the import table to map its api calls"
)
DEFAULT_CLAIM = (
    "[T1 tools=grep] claim C-104 strings and metadata scan of the sample"
)


# ---- feature -> query mapping (pure) ----


def test_go_signals_map_to_go_query():
    assert queries_for_features(GO_CLAIM, tier=1) == ["go", "static analysis"]


def test_t3_signals_map_to_vm_dynamic_queries():
    assert queries_for_features(VM_CLAIM, tier=3) == ["vm", "dynamic"]


def test_disasm_tier2_maps_to_static_analysis_query():
    # 'disasm' itself matches nothing in the index — the scene map's
    # 反汇编/静态分析 entry is reached via the 'static analysis' query.
    assert queries_for_features(DISASM_CLAIM, tier=2) == ["static analysis"]


def test_default_tier1_maps_to_static_analysis_query():
    assert queries_for_features(DEFAULT_CLAIM, tier=1) == ["static analysis"]


# ---- evaluate(): recall injection on claim dispatch ----


def test_vm_claim_injects_recall_guidance(tmp_path):
    """VM/dynamic claim -> additionalContext carries guidance + the reference
    files the real index returns for 'vm' + 'dynamic'."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM))
    assert rc == 0, "recall_inject never rejects"
    assert stderr == ""
    assert ctx, "a VM claim dispatch must receive recall guidance"
    assert "Before dispatching, read:" in ctx
    assert "dynamic-re-tool-priority.md" in ctx, "top hit for 'vm'/'dynamic'"
    assert "tools-dynamic.md" in ctx, "'dynamic' query must surface tools-dynamic.md"
    assert "verify-static-vs-dynamic.md" in ctx, "redteam verify method recall"
    assert "recall" in ctx


def test_go_claim_recalls_languages_go(tmp_path):
    """go-signal claim -> recall names languages-go.md (real 'go' query top hit)."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws, GO_CLAIM))
    assert rc == 0 and stderr == ""
    assert ctx and "languages-go.md" in ctx


def test_disasm_claim_recalls_static_analysis_references(tmp_path):
    """disasm/decode claim -> recall names anti-analysis.md (real 'static
    analysis' query top hit)."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws, DISASM_CLAIM))
    assert rc == 0 and stderr == ""
    assert ctx and "anti-analysis.md" in ctx


def test_default_t1_claim_still_gets_recall(tmp_path):
    """Even a plain T1 strings claim gets the default static-analysis recall —
    the knowledge base must be recalled on EVERY dispatch, not just feature-rich
    ones (#268: hooks injected 0 knowledge before)."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws, DEFAULT_CLAIM))
    assert rc == 0 and stderr == ""
    assert ctx and ".md" in ctx


# ---- FAIL_OPEN: recall must never block dispatch ----


def test_recall_failure_returns_empty_context_no_raise(tmp_path):
    """Subprocess failure (runner raises) -> (0, '', None), no raise."""
    ws = _kunglao_ws(tmp_path)

    def boom(query):
        raise RuntimeError(f"recall crashed on {query!r}")

    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM), recall_runner=boom)
    assert rc == 0 and stderr == "" and ctx is None


def test_recall_no_match_returns_empty_context(tmp_path):
    """rc != 0 (no match) -> (0, '', None) — nothing to inject."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM),
                               recall_runner=lambda q: (1, "# no match"))
    assert rc == 0 and stderr == "" and ctx is None


def test_recall_partial_match_keeps_matched_files(tmp_path):
    """One query matches, another doesn't -> guidance from the matched one."""
    ws = _kunglao_ws(tmp_path)
    calls = []

    def runner(q):
        calls.append(q)
        if q == "vm":
            return 0, "# references recall: vm — 1 file(s)\ndynamic-re-tool-priority.md | x | y | z"
        return 1, "# no match"

    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM), recall_runner=runner)
    assert rc == 0 and stderr == ""
    assert calls == ["vm", "dynamic"]
    assert ctx and "dynamic-re-tool-priority.md" in ctx


# ---- recall parses the index ONCE per process, in-process ----
#
# Issue 194, iteration 2. The first fix batched all queries of a dispatch
# into one child, but the child still re-parsed the whole layered index
# (~2.5 s CPU unloaded; measured 7-9 s under a local 4-worker storm and
# 10-30 s on CI-class 2-4 core runners), so any wall-clock window around
# the child stayed load-fragile. The mechanism fix is to parse the index
# IN-PROCESS and memoize it: the first recall in a process pays the parse
# once, every later query is milliseconds, and no recall child is spawned
# on the fast path at all (the batched child survives only as the
# fail-open fallback when the in-process path cannot run). The injected
# recall_runner contract (fake runners called once per query) is
# preserved for pure tests.

_RECALL_SCRIPT_MARK = "references_recall"


def _count_recall_children(recall_inject, monkeypatch):
    """Monkeypatch subprocess.run to record only references_recall.py
    child spawns (other incidental spawns, e.g. the git rev-parse the
    trace logger makes, must not pollute the count)."""
    import subprocess as sp

    spawns = []
    real_run = sp.run

    def counting_run(cmd, **kw):
        if any(_RECALL_SCRIPT_MARK in str(part) for part in cmd):
            spawns.append(list(cmd))
        return real_run(cmd, **kw)

    monkeypatch.setattr(recall_inject.subprocess, "run", counting_run)
    return spawns


def _count_index_parses(recall_inject, monkeypatch):
    """Monkeypatch build_index on the loaded recall module and clear the
    memoization cache so a test observes fresh parses. Returns the parse
    count list."""
    mod = recall_inject._recall_module()
    recall_inject._INDEX_CACHE.clear()
    parses = []
    real_build = mod.build_index

    def counting_build(path):
        parses.append(str(path))
        return real_build(path)

    monkeypatch.setattr(mod, "build_index", counting_build)
    return parses


def test_batch_timeout_is_a_single_bounded_hostage_window():
    """The fallback batched child keeps ONE bounded window per dispatch
    (>= 15 s of real headroom); no per-query 5 s window may remain, since
    that tight window was the guillotine the flake tripped."""
    import recall_inject

    assert recall_inject.RECALL_BATCH_TIMEOUT >= 15, (
        "the fallback child needs one window with real headroom, not 4-5 "
        "tight per-query windows")
    assert not hasattr(recall_inject, "RECALL_TIMEOUT"), (
        "the per-query 5 s guillotine must stay retired")


def test_recall_fast_path_spawns_no_child_and_parses_once(tmp_path, monkeypatch):
    """Core pin: a dispatch's recall is answered IN-PROCESS — zero
    references_recall children spawned, the layered index parsed exactly
    once, and the pinned doc set still injected."""
    import recall_inject

    ws = _kunglao_ws(tmp_path)
    spawns = _count_recall_children(recall_inject, monkeypatch)
    parses = _count_index_parses(recall_inject, monkeypatch)

    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM))
    assert rc == 0 and stderr == "" and ctx
    assert spawns == [], (
        f"fast path must spawn no recall children; got {spawns}")
    assert len(parses) == 1, (
        f"index must be parsed exactly once per dispatch; got {parses}")
    for expected in ("dynamic-re-tool-priority.md", "tools-dynamic.md",
                     "verify-static-vs-dynamic.md"):
        assert expected in ctx, f"{expected} missing from in-process recall"


def test_index_parse_memoized_across_dispatches(tmp_path, monkeypatch):
    """Second dispatch in the SAME process must not re-parse the index —
    the memoization is the whole point: one parse per process, not one
    per dispatch (and historically, not one per query)."""
    import recall_inject

    spawns = _count_recall_children(recall_inject, monkeypatch)
    parses = _count_index_parses(recall_inject, monkeypatch)

    rc1, _, ctx1 = evaluate(_payload(_kunglao_ws(tmp_path / "a"), VM_CLAIM))
    rc2, _, ctx2 = evaluate(_payload(_kunglao_ws(tmp_path / "b"), VM_CLAIM))
    assert rc1 == 0 and rc2 == 0 and ctx1 and ctx2
    assert len(parses) == 1, (
        f"one parse per process expected; got {len(parses)}: {parses}")
    assert spawns == [], "memoized dispatches must spawn no children"


def test_index_cache_invalidates_when_index_file_changes(tmp_path, monkeypatch):
    """The memo key carries the index file's stat; when the file changes
    (mtime/size), the next recall re-parses instead of serving stale
    entries. Unchanged file -> served from cache with zero re-parse.
    Runs against a TMP copy of the index — bumping the shared repo file's
    mtime would race other xdist workers' memo keys mid-run."""
    import os
    import shutil

    import recall_inject

    mod = recall_inject._recall_module()
    tmp_index = tmp_path / "references" / "_INDEX.md"
    tmp_index.parent.mkdir(parents=True)
    shutil.copyfile(mod.default_index_path(), tmp_index)
    monkeypatch.setattr(mod, "default_index_path", lambda: tmp_index)

    recall_inject._INDEX_CACHE.clear()
    parses = []
    real_build = mod.build_index

    def counting_build(path):
        parses.append(str(path))
        return real_build(path)

    monkeypatch.setattr(mod, "build_index", counting_build)

    recall_inject._memoized_index(mod)
    recall_inject._memoized_index(mod)
    assert len(parses) == 1, "unchanged index must be served from cache"

    os.utime(tmp_index, None)  # content unchanged, mtime bumped
    recall_inject._memoized_index(mod)
    assert len(parses) == 2, "changed index stat must invalidate the cache"


def test_inprocess_results_match_subprocess_cli(tmp_path, monkeypatch):
    """Parity guard: the in-process answer for a query set must equal what
    the references_recall CLI subprocess answers for the same set (the
    pinned ranking contract may not drift between the two faces)."""
    import subprocess as sp

    import recall_inject

    ws = _kunglao_ws(tmp_path)
    queries = ["vm", "dynamic"]

    spawns = _count_recall_children(recall_inject, monkeypatch)
    inproc = recall_inject.recall_files_batch(list(queries), cwd=ws)
    assert spawns == [], "parity baseline must come from the in-process face"

    cmd = [sp.sys.executable if hasattr(sp, "sys") else "python3",
           str(recall_inject.RECALL_SCRIPT), "--queries", *queries,
           "--ws", str(ws)]
    r = sp.run(cmd, capture_output=True, text=True, encoding="utf-8",
               errors="replace", cwd=str(ws), timeout=120)
    assert r.returncode == 0, r.stderr
    sections = recall_inject._split_batch_stdout(r.stdout, queries)
    from_cli = tuple(recall_inject._parse_files(sections[q])
                     for q in queries)
    assert inproc == list(from_cli), (
        f"in-process {inproc} != CLI {list(from_cli)}")


def test_batched_stdout_splits_per_query(tmp_path, monkeypatch):
    """Fallback face: when the in-process path cannot run, the batched
    child answers each query in its own `# ==== query:` section and
    evaluate() splits and merges them (dedup, FILES_PER_QUERY, order)."""
    import recall_inject

    ws = _kunglao_ws(tmp_path)

    canned = (
        "# ==== query: vm\n"
        "# references recall: vm — 1 file(s)\n"
        "orchestration/dynamic-re-tool-priority.md | a | b | c\n"
        "# ==== query: dynamic\n"
        "# references recall: dynamic — 2 file(s)\n"
        "re-library/tools/dynamic/tools-dynamic.md | a | b | c\n"
        "orchestration/verify-static-vs-dynamic.md | a | b | c\n"
    )

    class Done:
        returncode = 0
        stdout = canned
        stderr = ""

    def fake_run(cmd, **kw):
        assert "--queries" in cmd, f"batch face expected: {cmd}"
        return Done()

    def broken_inprocess(queries, cwd):
        raise RuntimeError("in-process recall unavailable")

    monkeypatch.setattr(recall_inject, "_inprocess_batch", broken_inprocess)
    monkeypatch.setattr(recall_inject.subprocess, "run", fake_run)
    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM))
    assert rc == 0 and stderr == ""
    assert ctx, "batched stdout must still inject"
    for expected in ("dynamic-re-tool-priority.md", "tools-dynamic.md",
                     "verify-static-vs-dynamic.md"):
        assert expected in ctx, f"{expected} missing from batched injection"


def test_batch_child_failure_fails_open_all_queries(tmp_path, monkeypatch):
    """When BOTH faces fail (in-process unavailable AND the fallback child
    times out), recall fails open for the whole dispatch — (0, '', None),
    never a raise."""
    import subprocess as sp

    import recall_inject

    ws = _kunglao_ws(tmp_path)

    def timeout_run(cmd, **kw):
        raise sp.TimeoutExpired(cmd, 20.0)

    def broken_inprocess(queries, cwd):
        raise RuntimeError("in-process recall unavailable")

    monkeypatch.setattr(recall_inject, "_inprocess_batch", broken_inprocess)
    monkeypatch.setattr(recall_inject.subprocess, "run", timeout_run)
    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM))
    assert rc == 0 and stderr == "" and ctx is None


# ---- silent on non-dispatch / non-kunglao payloads ----


def test_non_dispatch_payload_silent(tmp_path):
    """No `[T<N> tools=...] claim C-NN` description -> no recall, no context."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws, "run the report writer agent"))
    assert rc == 0 and stderr == "" and ctx is None


def test_non_kunglao_workspace_silent(tmp_path):
    """no claim-register.yaml -> silent even with a dispatch-shaped prompt
    (the globally-wired hook must not recall in unrelated projects)."""
    other = tmp_path / "other"
    other.mkdir()
    rc, stderr, ctx = evaluate(_payload(other, VM_CLAIM))
    assert rc == 0 and stderr == "" and ctx is None


def test_missing_tool_input_silent(tmp_path):
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate({"cwd": str(ws)})
    assert rc == 0 and stderr == "" and ctx is None


# ---- end-to-end: the wired main() shape ----


def test_main_stdin_injects_recall_end_to_end(tmp_path):
    """The wired shape: JSON payload on stdin -> exit 0, stdout carries the
    hookSpecificOutput.additionalContext JSON with recall guidance."""
    ws = _kunglao_ws(tmp_path)
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "hooks" / "recall_inject.py")],
        input=json.dumps(_payload(ws, VM_CLAIM)), capture_output=True,
        encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
        cwd=str(ws), timeout=60,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "Before dispatching, read:" in ctx
    assert ".md" in ctx


def test_main_stdin_non_dispatch_silent_end_to_end(tmp_path):
    """The wired shape, non-dispatch payload -> exit 0, EMPTY stdout."""
    ws = _kunglao_ws(tmp_path)
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "hooks" / "recall_inject.py")],
        input=json.dumps(_payload(ws, "run the report writer agent")),
        capture_output=True, encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
        cwd=str(ws), timeout=60,
    )
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


# ---- issue #268 item 3: failure_analysis_gate BLOCKED -> failure-modes recall ----


def test_failure_gate_blocked_output_recalls_failure_modes(tmp_path, capsys):
    """A BLOCKED row appends the failure-modes reference recall to the gate's
    question output (real recall over the real index)."""
    import yaml

    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{
            "id": "C-50", "status": "OPEN", "boundary_type": "observation",
            "evidence_tier_attempted": 1, "promotion_attempts": 1,
            "answers_question": "q1",
            "depends_on": [], "statement": "sample does X",
        }]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # #146: arm the gate the live way — a linked case carrying a red
    # settlement in the #106 ledger (the counter no longer arms).
    import posteriors as po
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True)
    (cdir / "case-c-50.yaml").write_text(
        "id: case-c-50\ntarget_pq: q1\n", encoding="utf-8")
    led = po.PosteriorLedger.load(ws)
    led.cases["case-c-50"] = po.CasePosterior("case-c-50", alpha=1.0,
                                              beta=2.0)
    led.save(ws)

    import failure_analysis_gate as fag
    r = fag.check_claim(ws, "C-50")
    assert r["state"] == "BLOCKED"
    fag._print_blocked(r)
    out = capsys.readouterr().out
    assert "failure-modes" in out, "BLOCKED output must recall the failure-modes references"
    assert "failure-modes-lifecycle.md" in out, "lifecycle domain file must be named"
    assert "failure-modes-state.md" in out, "state domain file must be named"
