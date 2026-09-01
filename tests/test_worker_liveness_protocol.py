# -*- coding: utf-8 -*-
"""RED tests for issue #444 — worker liveness single source of truth + W-15.

Three acceptance criteria from the issue, each pinned by tests:

  AC-1  全仓库仅一处解析 worker 活性(grep 可验证)
        -> test_single_parse_point_grep / test_canonical_module_owns_the_regex
           / test_consumer_wiring_references_canonical
  AC-2  "报 done 无产物文件"有机器检查路径与测试
        -> test_w15_* / test_decide_exposes_w15 / test_worker_pulse_flags_w15
  AC-3  两层(咨询/hook)消费同一协议的一致性有 CI 断言
        -> test_two_layer_consistency_same_fixture
           / test_two_layers_share_one_protocol_source

Protocol under test (design.md D1): hooks/lib_kunglao.py owns the ONE
implementation of the "last `status:` token wins" parse over
runs/worker-status-*.md (+ .wt-* worktree runs). Every other module is a
consumer. W-15: a `done` status file that carries `artifacts:` declarations
must point at existing files (`artifacts: none` = explicit zero-file failure);
legacy files without declarations stay readable and exempt (migration compat).

The worker-status file vocabulary/format contract lives in
agents/kunglao-worker.md rule #4 (append-only log, both line shapes).
No load_sensitive marker: pure tmp_path fixtures, no cross-process locks.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
SCRIPTS = ROOT / "scripts"
for _p in (str(SCRIPTS), str(HOOKS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The canonical protocol module, loaded by explicit path under the SAME unique
# name every scripts-side consumer uses ("lib_kunglao_hooks") — the
# external_kicker.should_kick / state_anchor._load_drift_lib precedent.
# Bare `import lib_kunglao` is ambiguous under pytest (pythonpath = . hooks
# scripts ... — hooks first) because scripts/lib_kunglao.py (drift lib) shares
# the name; by-path + unique name is the repo's established safe pattern.
_PROTOCOL_NAME = "lib_kunglao_hooks"
CANONICAL_REL = Path("hooks") / "lib_kunglao.py"


def load_protocol():
    lib = sys.modules.get(_PROTOCOL_NAME)
    if lib is None:
        spec = importlib.util.spec_from_file_location(
            _PROTOCOL_NAME, ROOT / CANONICAL_REL)
        lib = importlib.util.module_from_spec(spec)
        sys.modules[_PROTOCOL_NAME] = lib
        spec.loader.exec_module(lib)
    return lib


# ---------- fixtures ----------

def _make_ws(tmp_path, claims=({"id": "C-1", "status": "OPEN"},)) -> Path:
    """Minimal kunglao workspace: claim-register + runs/. decide()/pulse both
    need the register (convergence_check exits 64 without it)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    text = "claims:\n"
    for c in claims or ():
        text += f"- id: {c['id']}\n  status: {c.get('status', 'OPEN')}\n"
    (ws / "claim-register.yaml").write_text(text, encoding="utf-8")
    return ws


def _write_status(ws: Path, name: str, body: str, age_min: float | None = None) -> Path:
    """Write runs/worker-status-<name>.md with raw body (caller controls the
    line shape: pipe-embedded and dedicated-line both legal)."""
    p = ws / "runs" / f"worker-status-{name}.md"
    p.write_text(body, encoding="utf-8")
    if age_min is not None:
        import os
        import time
        old = time.time() - age_min * 60
        os.utime(p, (old, old))
    return p


def _make_worktree_run(ws_parent: Path, wt: str, name: str, body: str) -> Path:
    """A v1.9.13 worker worktree: .wt-*/ marker + malware-analysis-workspace/runs."""
    wt_dir = ws_parent / f".wt-{wt}"
    runs = wt_dir / "malware-analysis-workspace" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (wt_dir / ".kunglao-worktree").write_text("active", encoding="utf-8")
    return _write_status(wt_dir / "malware-analysis-workspace", name, body)


# ============================================================
# AC-1: single parse point (grep-verifiable)
# ============================================================

# A hand-rolled worker-status token regex compiled in-module. Matches the
# exact shapes found in the wild: r"status:\s*(\S+)", r"^\s*status\s*:\s*(\S+)",
# `_re.compile(r"status:\s*(\S+)")` (substring "re.compile(" matches "_re.compile(").
# The tail must match the LITERAL characters `\s*(\S+)` (backslash-s-star ...),
# hence \\s\*\(\\S\+\) — not regex whitespace classes.
_STATUS_TOKEN_COMPILE = re.compile(
    r"re\.compile\(\s*r?['\"][^'\"]{0,24}status\s*:\s*\\s\*\(\\S\+\)")

# Review F-1 (post-GREEN): a parse can dodge the regex shape entirely — the
# 9th site counted liveness by SUBSTRING presence (`"in-progress" in
# text.lower()`). Enumerate that shape too: a file referencing worker-status
# files must not test the in-progress token with `in` / `.find` either.
_SUBSTRING_LIVENESS_COMPILE = re.compile(
    r'["\']in-progress["\']\s+in\b|\.find\(\s*["\']in-progress')

# Documents exceptions that are NOT the worker-status appendable-log protocol.
# Each entry must state the different protocol the regex belongs to.
# (posix-style repo-relative keys — matches _repo_python_files' as_posix().)
ALLOWLIST = {
    "hooks/state_anchor.py":
        "_CLAIM_STATUS_RE parses claim-register.yaml YAML blocks, not the "
        "worker-status appendable log (state_anchor never globs worker-status "
        "files; its docstring only mentions them as a non-parsed input)",
    "scripts/external_kicker.py":
        "_RESUME_CLAIM_STATUS_RE parses claim-register.yaml YAML blocks "
        "(paired with _RESUME_CLAIM_ID_RE `^- id:` entries in "
        "_register_open_ids), not the worker-status appendable log; the "
        "worker-status parsing in this file consumes the canonical protocol "
        "(enforced by test_consumer_wiring_references_canonical)",
}


def _repo_python_files():
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("tests/"):        # fixtures may rebuild shapes freely
            continue
        if rel.startswith((".git", ".review", "openspec/", ".worktrees")):
            continue
        if rel == CANONICAL_REL.as_posix():
            continue
        yield p, rel


def test_single_parse_point_grep():
    """AC-1: no module outside the canonical protocol owner may compile its own
    worker-status token regex while referencing worker-status files."""
    lib = load_protocol()
    offenders = []
    for p, rel in _repo_python_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "worker-status" not in text:
            continue  # does not touch the protocol's files
        hand_rolled = (_STATUS_TOKEN_COMPILE.search(text)
                       or _SUBSTRING_LIVENESS_COMPILE.search(text))
        if hand_rolled and rel not in ALLOWLIST:
            offenders.append(rel)
    assert offenders == [], (
        "worker-liveness parsing must live ONLY in "
        f"{CANONICAL_REL.as_posix()} (issue #444 AC-1); hand-rolled status-token "
        f"regexes found in: {offenders}. Consume lib_kunglao.parse_worker_status"
        "(_tokens) instead. Allowlisted (different protocol): "
        f"{sorted(ALLOWLIST)}"
    )
    # the protocol really is implemented where we say it is
    assert hasattr(lib, "scan_active_workers")


def test_canonical_module_owns_the_regex():
    """AC-1 positive side: the canonical module defines the protocol and
    compiles the token regex exactly once."""
    lib = load_protocol()
    assert hasattr(lib, "WORKER_STATUS_RE")
    for name in ("parse_worker_status", "parse_worker_status_tokens",
                 "parse_declared_artifacts", "iter_worker_states",
                 "scan_active_workers", "scan_done_artifact_violations"):
        assert hasattr(lib, name), f"protocol owner missing {name}"
    text = (ROOT / CANONICAL_REL).read_text(encoding="utf-8")
    assert len(_STATUS_TOKEN_COMPILE.findall(text)) == 1, (
        "canonical module must compile the worker-status token regex exactly once"
    )


# every consumer must reach the protocol through the canonical entry — the
# static wiring half of AC-3's CI assertion (the behavioral half is below).
# #863 Family B: by-path prologues were consolidated into the canonical
# loader (hooks/_path_hygiene.load_hooks_lib via scripts/_hooks_path), so
# the wiring marker IS the delegation call.
WIRING = {
    #770: worker_budget binds the hooks twin BY PATH under an isolated
    # name (#762 convention) instead of a bare sys.path-order-dependent
    # import; the isolated name is the canonical-consumption marker.
    "hooks/worker_budget.py": "load_module_by_path",
    "hooks/worker_pulse.py": "parse_worker_status",
    "scripts/convergence_check.py": "load_hooks_lib",
    "scripts/lib_kunglao.py": "load_hooks_lib",
    "scripts/external_kicker.py": "load_hooks_lib",
    "scripts/event_taxonomy.py": "load_hooks_lib",
    "scripts/kunglao_status.py": "load_hooks_lib",
    "scripts/reconcile_workers.py": "load_hooks_lib",
    # review F-1: the 9th consumer found post-GREEN (substring count → canonical)
    "scripts/progress_report.py": "load_hooks_lib",
}


def test_consumer_wiring_references_canonical():
    """AC-1/AC-3 static wiring: each known consumer references the canonical
    protocol (bare hooks import, or the lib_kunglao_hooks by-path loader)."""
    missing = {}
    for rel, marker in WIRING.items():
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if marker not in text:
            missing[rel] = marker
    assert missing == {}, (
        "consumers must reach the worker-liveness protocol through "
        f"hooks/lib_kunglao.py (issue #444); missing wiring: {missing}"
    )


def test_progress_report_counts_append_only_done_as_inactive(tmp_path, capsys):
    """Review F-1: progress_report is a liveness consumer — append-only files
    of NORMALLY-COMPLETED workers contain historical in-progress lines, so
    substring presence ("in-progress" in text) counts them as active and
    diverges from every canonical consumer. Last-token-wins must count 0
    active for done files and 1 for the single live one."""
    sys.path.insert(0, str(SCRIPTS))
    import progress_report as pr
    ws = _make_ws(tmp_path)
    _write_status(
        ws, "w-finished",
        "[10:00] step: started t12 | status: in-progress\n"
        "[10:04] step: gathered strings | status: in-progress\n"
        "[10:09] step: finished | status: done | artifacts: facts/F001-x.md\n")
    _write_status(ws, "w-live", "[10:00] step: started t15 | status: in-progress")
    pr.report(ws)
    out = capsys.readouterr().out
    workers_line = next(l for l in out.splitlines() if "in-flight" in l)
    assert "1 in-flight" in workers_line and "2 in-flight" not in workers_line, (
        "progress_report must derive liveness from the canonical protocol "
        "(hooks/lib_kunglao, #444): a done file's historical in-progress "
        f"lines are NOT liveness. got: {workers_line!r}"
    )


# ============================================================
# AC-2: W-15 — done MUST mean the declared files exist
# ============================================================

DONE_DECLARED = (
    "# worker w1\n"
    "[12:00] step: started strings | status: in-progress\n"
    "[12:05] step: fact written | artifacts: facts/F001-strings.md, evidence/strings.json\n"
    "[12:06] step: finished | status: done | artifacts: facts/F001-strings.md, evidence/missing.json\n"
)


def test_w15_done_declared_missing_flagged(tmp_path):
    lib = load_protocol()
    ws = _make_ws(tmp_path)
    (ws / "facts" / "F001-strings.md").parent.mkdir(parents=True, exist_ok=True)
    (ws / "facts" / "F001-strings.md").write_text("fact\n", encoding="utf-8")
    (ws / "evidence").mkdir(exist_ok=True)
    (ws / "evidence" / "strings.json").write_text("{}", encoding="utf-8")
    _write_status(ws, "w1", DONE_DECLARED)
    v = lib.scan_done_artifact_violations(ws)
    assert len(v) == 1, f"declared-but-missing must be flagged; got {v}"
    assert v[0]["worker"] == "worker-status-w1"
    assert v[0]["kind"] == "declared-missing"
    assert v[0]["missing"] == ["evidence/missing.json"]


def test_w15_done_all_declared_present_clean(tmp_path):
    lib = load_protocol()
    ws = _make_ws(tmp_path)
    (ws / "facts").mkdir()
    (ws / "facts" / "F001-strings.md").write_text("fact\n", encoding="utf-8")
    (ws / "evidence").mkdir()
    (ws / "evidence" / "strings.json").write_text("{}", encoding="utf-8")
    _write_status(ws, "w1", (
        "[12:00] step: started | status: in-progress\n"
        "artifacts: facts/F001-strings.md, evidence/strings.json\n"
        "[12:06] step: finished | status: done\n"))
    assert lib.scan_done_artifact_violations(ws) == []


def test_w15_legacy_done_without_declaration_flagged(tmp_path):
    """#550 (user ruling 2026-08-25, no legacy-compat): a bare done file with
    no artifacts: declaration IS flagged — done must declare deliverables."""
    lib = load_protocol()
    ws = _make_ws(tmp_path)
    _write_status(ws, "w1", "[12:00] step: finished | status: done\n")
    v = lib.scan_done_artifact_violations(ws)
    assert any(x["kind"] == "done-undeclared" for x in v)
    active, stuck = lib.scan_active_workers(ws)
    assert (active, stuck) == (0, [])


def test_w15_done_explicit_none_flagged(tmp_path):
    """`artifacts: none` is the honest zero-file declaration — the W-15 core
    case (a worker that reports done without files has FAILED)."""
    lib = load_protocol()
    ws = _make_ws(tmp_path)
    _write_status(ws, "w1", (
        "[12:00] step: started | status: in-progress\n"
        "[12:06] step: nothing to deliver | status: done | artifacts: none\n"))
    v = lib.scan_done_artifact_violations(ws)
    assert len(v) == 1 and v[0]["kind"] == "done-no-files", v


def test_w15_inprogress_missing_artifacts_not_flagged(tmp_path):
    """W-15 binds to the done verdict only; an in-progress worker may reference
    not-yet-written paths."""
    lib = load_protocol()
    ws = _make_ws(tmp_path)
    _write_status(ws, "w1", (
        "[12:00] step: started | status: in-progress\n"
        "artifacts: facts/F009-not-yet.md\n"))
    assert lib.scan_done_artifact_violations(ws) == []


def test_w15_absolute_path_declaration_resolved(tmp_path):
    lib = load_protocol()
    ws = _make_ws(tmp_path)
    target = tmp_path / "out.json"
    target.write_text("{}", encoding="utf-8")
    _write_status(ws, "w1", (
        "[12:00] step: started | status: in-progress\n"
        f"[12:06] step: finished | status: done | artifacts: {target.as_posix()}\n"))
    assert lib.scan_done_artifact_violations(ws) == []
    target.unlink()
    v = lib.scan_done_artifact_violations(ws)
    assert len(v) == 1 and v[0]["kind"] == "declared-missing", v


def test_w15_worktree_status_resolved_against_own_root(tmp_path):
    """A done worker in a .wt-* worktree resolves declared artifacts against
    THAT worktree's workspace root (v1.9.13 isolation), not the main tree."""
    lib = load_protocol()
    ws = _make_ws(tmp_path)
    wt_ws = tmp_path / ".wt-w9" / "malware-analysis-workspace"
    _make_worktree_run(tmp_path, "w9", "w9", (
        "[12:00] step: started | status: in-progress\n"
        "[12:05] step: done | status: done | artifacts: facts/F002-wt.md\n"))
    # file exists ONLY in the worktree root, not the main workspace
    (wt_ws / "facts").mkdir(parents=True, exist_ok=True)
    (wt_ws / "facts" / "F002-wt.md").write_text("fact\n", encoding="utf-8")
    assert lib.scan_done_artifact_violations(ws) == []
    (wt_ws / "facts" / "F002-wt.md").unlink()
    v = lib.scan_done_artifact_violations(ws)
    assert len(v) == 1 and v[0]["worker"] == "worker-status-w9", v


def test_decide_exposes_w15(tmp_path):
    """咨询层 machine path: decide() carries done_artifact_violations as a
    diagnostic field WITHOUT changing the decision matrix (branch structure is
    #443's, untouched)."""
    from convergence_check import decide
    ws = _make_ws(tmp_path)
    (ws / "facts").mkdir()
    (ws / "facts" / "F001-strings.md").write_text("fact\n", encoding="utf-8")
    (ws / "evidence").mkdir()
    (ws / "evidence" / "strings.json").write_text("{}", encoding="utf-8")
    _write_status(ws, "w1", DONE_DECLARED)
    d = decide(ws)
    assert d["decision"] == "DISPATCH", (
        "open claim + free slots must stay DISPATCH (no branch change)"
    )
    assert d["active_workers"] == 0
    got = d.get("done_artifact_violations")
    assert got and got[0]["worker"] == "worker-status-w1" and \
        got[0]["missing"] == ["evidence/missing.json"], got


def test_worker_pulse_flags_w15(tmp_path):
    """hook 层 machine path: the pulse surfaces the W-15 violation at the
    delivery moment (same channel as the quarantined= flag, #36 precedent)."""
    import worker_pulse as wp
    ws = tmp_path / "ws-pulse"
    ws.mkdir()
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    _write_status(ws, "w1", DONE_DECLARED)
    pulse, decision = wp._build_pulse(ws)
    assert "w15=" in pulse, (
        f"pulse must flag a done-without-files worker (W-15); got:\n{pulse}"
    )
    assert "worker-status-w1" in pulse


# ============================================================
# AC-3: two-layer (advisory / hook) consistency
# ============================================================

MIXED_FIXTURE = (
    # pipe-embedded shape — the shape worker_pulse's old anchored regex missed
    "[12:00] step: started | status: in-progress\n"
    "[12:03] step: parsing | status: in-progress\n",
    # dedicated-line shape
    "status: in-progress\n",
)


def _mixed_workspace(tmp_path) -> Path:
    ws = _make_ws(tmp_path)
    _write_status(ws, "w1", MIXED_FIXTURE[0], age_min=30)   # active + stuck
    _write_status(ws, "w2", MIXED_FIXTURE[1])               # active, fresh
    _write_status(ws, "w3", "[12:00] step: over | status: done\n")  # not active
    _make_worktree_run(tmp_path, "wt1", "w4", MIXED_FIXTURE[0])
    return ws


def test_two_layer_consistency_same_fixture(tmp_path):
    """AC-3 behavioral: on ONE fixture (both line shapes + a .wt-* worktree),
    the advisory layer (convergence_check.decide) and the hook layer
    (worker_budget.check_workers_lt_3) must report the SAME active count.
    Re-forking either side onto a private parser (e.g. an anchored variant that
    misses the pipe shape) breaks this equality."""
    from convergence_check import decide
    from worker_budget import check_workers_lt_3
    ws = _mixed_workspace(tmp_path)
    d = decide(ws)
    assert d["active_workers"] == 3, d
    assert [s["worker"] for s in d["stuck_workers"]] == ["worker-status-w1"], d
    # 3 active == WORKER_CAP: the gate correctly rejects, but its COUNT must
    # equal the advisory layer's count — that equality is the two-layer contract.
    ok, msg = check_workers_lt_3({"workspace": str(ws)})
    assert ok is False, msg
    assert "active_workers=3" in msg, (
        f"hook layer count must equal advisory layer count (3); got: {msg}"
    )


def test_two_layers_share_one_protocol_source():
    """AC-3 static: both layers are wired to the canonical protocol module —
    worker_budget imports lib_kunglao.scan_active_workers (hooks namespace);
    convergence_check loads the SAME file by path (lib_kunglao_hooks loader)."""
    wb = (ROOT / "hooks" / "worker_budget.py").read_text(encoding="utf-8")
    cc = (ROOT / "scripts" / "convergence_check.py").read_text(encoding="utf-8")
    assert "load_module_by_path" in wb, (
        "hook layer must consume the canonical scan via the #770 by-path "
        "bind (#863 Family B: through the canonical loader; a bare "
        "lib_kunglao import resolves by sys.path race)"
    )
    assert "load_hooks_lib" in cc, (
        "advisory layer must load the canonical protocol through the "
        "scripts-side loader delegation (#863 Family B)"
    )
