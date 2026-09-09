#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recall_inject.py - PreToolUse runtime knowledge recall injection (#268).

WHY: the kunglao knowledge base (references/_INDEX.md + references_recall.py +
the re-library) was NEVER recalled at runtime — the hooks injected status /
gates / failures but 0 knowledge. Workers were dispatched for claims with no
idea that languages-go.md or tools-dynamic.md existed. This hook closes the
gap at the ONE point every claim enters the loop: the Agent dispatch.

Design (mirrors dispatch_gate / env_check_gate, inject-only):
  - PreToolUse hook on Agent. Reads the dispatch description from the tool
    input (prompt / description / task / input — the same shapes dispatch_gate
    accepts). Matches the dispatch format `[T<N> tools=...] claim C-NN`.
  - Claim features -> tier via scripts/tier_rules.tier_for_claim (single
    source for T3 VM/dynamic vs T2 static-depth signals), then -> recall
    queries: go signals -> "go" (languages-go.md); tier 3 -> "vm" + "dynamic"
    (dynamic-debugging scene / verify-static-vs-dynamic.md); tier 2 + default ->
    "static analysis" (disasm/static-analysis scene — "disasm" itself matches nothing
    in the index).
  - All queries of a dispatch run in ONE `references_recall.py --queries
    <q1> <q2> ...` subprocess (timeout RECALL_BATCH_TIMEOUT). The layered
    index is parsed once per dispatch, not once per query — the per-query
    child made every query individually flake-prone under CI xdist
    contention (#194: a child past its timeout is swallowed by fail-open
    and the affected query silently contributes nothing). FAIL_OPEN at
    every layer: any failure -> no injection, exit 0 pass-through — recall
    must NEVER block dispatch.
  - On a match it emits the hookSpecificOutput.additionalContext JSON shape
    (same as dispatch_gate.py:137-142 / env_check_gate main()) with a
    "Before dispatching, read: <files>" guidance. rc is ALWAYS 0: this hook
    injects knowledge, it never rejects.
  - Fires only in a kunglao workspace (claim-register.yaml present), so the
    globally-wired hook stays silent in unrelated projects. NO activation
    check: recall injection is knowledge, not enforcement — it helps whether
    or not the enforcement hooks are activated.

Wiring (in .claude/settings.json PreToolUse, Agent matcher — registered
idempotently by scripts/hook_activation.py --wire-up (the canonical
registration entry, #445) alongside dispatch_gate):
  {"matcher": "Agent", "hooks": [{"type": "command",
    "command": "uv run --project <skill_root> <skill_root>/hooks/recall_inject.py"}]}
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from _path_hygiene import (  # #671 sys.path hygiene authority
    ensure_scripts_path,
    load_hooks_lib,
    load_module_by_path,
)

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
RECALL_SCRIPT = SKILL_DIR / "scripts" / "references_recall.py"
# #194: every recall subprocess is ONE batched child per dispatch — it
# parses the layered index ONCE (the parse, not the scoring, is the cost;
# ~2.5 s on a fast unloaded machine) and answers all queries. The former
# per-query children (5 s each, 4-5 per dispatch) each re-paid that parse
# and individually tipped past their timeout under CI xdist contention,
# which fail-open swallowed into silently missing queries — the #194
# recall-injection flake. One window with real headroom, bounded by the
# old serial envelope (len(queries) x 5 s).
RECALL_BATCH_TIMEOUT = 20.0
FILES_PER_QUERY = 4           # top hits only — guidance stays compact;
# four keeps the verification-method file reachable for VM-class claims
# NOTE (#357): ranking below is token-overlap scoring, which is
# language-sensitive — translating a recall data source (references/_INDEX.md,
# references/_index-<domain>.md) shifts scores. Guarded by
# tests/test_recall_inject.py + tests/test_vm_claim_injects_recall_guidance.py
# (the recall-ranking pin); move data source and pin in the same commit.
MAX_FILES = 8                 # global cap across all queries

def _is_claim_dispatch(text: str) -> bool:
    """v1-first claim-dispatch detection — single source (#861).

    Routes through lib_kunglao.parse_dispatch (v1 canonical envelope takes
    precedence, v0 prefix retained for legacy-replay only). Replaces the
    local v0-only regex copy that silently missed v1 dispatches (B1)."""
    lib = load_hooks_lib()
    return lib.parse_dispatch(text)[2] is not None


# Go-binary signals (tier_rules has no go signals — those live here). Substring
# matches; "go" alone is too noisy ("goal", "google", "cargo") so signals are
# compound or language-typed.
GO_SIGNALS = (
    "golang", "go binary", "go 二进制", "go 程序", "go 语言",
    "go runtime", "go symbol", "go function", "go 1.",
)

# Web-domain signals (#761 J1, ruling: 风控/爬虫知识 web 域专用): a claim that
# mentions the anti-bot / crawler surface gets the two web-dictionary queries
# prepended (web-risk-control.md / web-crawler-engineering.md top hits), before
# the tier-based default. All anchors are compound/CJK — deliberately noise-
# safe so legacy dispatch prompts never gain the extra queries (the pinned
# test_recall_inject.py fixtures hit none of these).
WEB_SIGNALS = (
    "风控", "反爬", "风险控制", "爬虫", "验证码", "滑块", "点选",
    "risk control", "risk-control", "anti-bot", "antibot",
    "crawler", "captcha", "web target", "--type web", "camoufox",
)

# Recalled queries for a web-signal claim (#761 J1). "risk control" ranks
# re-library/web/risk-control/web-risk-control.md first (name+domain+purpose CJK tokens);
# "crawler" surfaces web-crawler-engineering.md via its bilingual purpose row.
WEB_QUERIES = ("risk control", "crawler")

# Red-team dispatch detection (#761 J4 second trigger face): adversarial
# knowledge injected BEFORE the checker plans its attacks — same FAIL_OPEN,
# rc-always-0 semantics as the claim face. Claim-shaped prompts keep the
# original flow; a red-team prompt without a `[T<N>] claim` shape takes this
# branch.
REDTEAM_RE = re.compile(r"(?:red[\s_-]*team|redteam|verify-redteam)", re.IGNORECASE)


def queries_for_redteam(prompt_text: str) -> list[str]:
    """Red-team recall queries (#761 J4): failure-modes domain by default
    (how past checks failed -> attack angles); web signals add the anti-bot
    doctrine so an adversarial pass on a web claim carries the decision tree."""
    text = (prompt_text or "").lower()
    queries = ["failure analysis"]
    if any(s in text for s in WEB_SIGNALS):
        queries.extend(WEB_QUERIES)
    return queries

# tier_rules is the single source for T3/T2 feature detection (#241).
# #671: module-level membership via the hygiene authority (was bare insert).
ensure_scripts_path()
from tier_rules import tier_for_claim  # noqa: E402


def _resolve_workspace(payload: dict) -> Path | None:
    """Delegate to hooks.lib_kunglao.resolve_workspace_canonical (#865).

    Pre-#865: hardcoded `cwd / malware-analysis-workspace` — silently
    bypassed env-manifest overrides (B2 substance CONFIRMED). The
    canonical helper reads `layout.workspace_dir` via `_env_layout` so
    the same resolution now applies here, in dispatch_gate, and in
    env_check_gate — three hooks previously drifted apart.
    """
    from _path_hygiene import load_hooks_lib
    return load_hooks_lib().resolve_workspace_canonical(payload)


def _dispatch_text(payload: dict) -> str | None:
    """Extract the dispatch description (prompt / description / task / input
    field; falls back to the first string value). Mirrors dispatch_gate."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("prompt", "description", "task", "input"):
        v = tool_input.get(key)
        if isinstance(v, str) and v.strip():
            return v
    for v in tool_input.values():
        if isinstance(v, str) and v.strip():
            return v
    return None


def queries_for_features(prompt_text: str, tier: int) -> list[str]:
    """Deterministic claim-feature -> recall query mapping (#268).

    go signals -> "go" (languages-go.md is the top hit); tier 3 (VM/dynamic
    intent, via tier_rules) -> "vm" + "dynamic" (dynamic-debugging scene +
    verify-static-vs-dynamic.md); tier 2 (static-depth/disasm) and the tier 1
    default -> "static analysis" (disasm/static-analysis scene — "disasm" itself
    matches nothing in the layered index).
    #761 J1: web-domain signals prepend "risk control" + "crawler" (the two new
    web reference docs) — append-only semantics: every pre-existing mapping is
    unchanged for prompts without web signals.
    """
    text = prompt_text.lower()
    queries: list[str] = []
    if any(s in text for s in WEB_SIGNALS):
        queries.extend(WEB_QUERIES)
    if any(s in text for s in GO_SIGNALS):
        queries.append("go")
    if tier == 3:
        queries.extend(("vm", "dynamic"))
    else:
        queries.append("static analysis")
    return queries


def _parse_files(stdout: str) -> tuple[str, ...]:
    """File paths from references_recall.py stdout (scored and scene formats
    both print rows as `<path> | <category> | ...`; dedup, order-preserving)."""
    files: list[str] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if " | " not in line:
            continue
        candidate = line.split(" | ", 1)[0].strip()
        if candidate.endswith(".md") and candidate not in seen:
            seen.add(candidate)
            files.append(candidate)
    return tuple(files)


_BATCH_QUERY_SEP = "# ==== query: "


def _run_recall_batch(queries: list[str],
                      cwd: Path | None = None) -> tuple[int, str]:
    """#194: ALL of a dispatch's recall queries in ONE child subprocess
    (`references_recall.py --queries ...`) — the layered index is parsed
    once instead of once per query. Returns (rc, stdout); any failure
    (missing script, timeout, usage error) -> (rc != 0, '')."""
    if not queries:
        return 0, ""
    cmd = [sys.executable, str(RECALL_SCRIPT), "--queries", *queries]
    if cwd is not None:
        cmd += ["--ws", str(cwd)]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(cwd) if cwd else None, timeout=RECALL_BATCH_TIMEOUT,
        )
        return r.returncode, r.stdout or ""
    except Exception:  # noqa: BLE001 — recall must NEVER block dispatch
        return 1, ""


def _split_batch_stdout(stdout: str, queries: list[str]) -> dict[str, str]:
    """Per-query stdout sections from a --queries batch run. Each section
    starts at its exact `# ==== query: <q>` separator line; a query with
    no section parses as empty (equivalent to no match)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in stdout.splitlines():
        if line.startswith(_BATCH_QUERY_SEP):
            current = line[len(_BATCH_QUERY_SEP):].strip()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {q: "\n".join(sections.get(q, [])) for q in queries}


def _utility_rerank(files: tuple[str, ...], ws: Path) -> tuple[str, ...]:
    """#881 wiring 2: post-recall utility rerank — recall was pure query-match
    with no value signal; reference docs whose filename names a tool with a
    high pooled runtime utility rise, low-utility ones sink. Files naming no
    tool keep a neutral score and their original relative order (stable sort).
    FAIL_OPEN at every layer: missing/corrupt table or any error -> the
    original order — rerank must never break recall (it is guidance only)."""
    try:
        from tool_value import line_tool_hits, load_table, pooled_utilities
        table = load_table(ws)
        if not table:
            return files
        pooled = pooled_utilities(table)
        if not pooled:
            return files
    except Exception:  # noqa: BLE001 — recall must NEVER block dispatch
        return files

    def score(path: str) -> float:
        best = 0.5  # neutral: no tool named in the filename
        for name in line_tool_hits(Path(path).name, pooled):
            if pooled[name]["utility"] > best:
                best = pooled[name]["utility"]
        return best

    return tuple(sorted(files, key=lambda f: -score(f)))


def recall_files(query: str, cwd: Path | None = None,
                 recall_runner=None) -> tuple[str, ...]:
    """Matched reference files for one query (empty on any failure). Public so
    siblings (failure_analysis_gate #268 item 3) reuse the same recall path.

    #881 wiring 2: when a workspace is supplied (cwd != None — the claim-dispatch
    face) and a tool-value table exists, the result is reranked by pooled tool
    utility. Callers without a workspace (failure_analysis_gate._failure_modes_recall)
    are structurally unaffected. Fail-open: no table / corrupt table / any
    error -> the original query-match order.

    #194: the runner-less subprocess path rides the batch face too (one
    index parse, RECALL_BATCH_TIMEOUT window) — the standalone 5 s per-query
    child is gone; its tight window was the other half of the #194 flake
    (failure_analysis_gate's single recall query timed out under the same
    CI contention). An injected recall_runner keeps its exact per-query
    contract."""
    if recall_runner is None:
        return recall_files_batch([query], cwd=cwd)[0]
    try:
        rc, stdout = recall_runner(query)
    except Exception:  # noqa: BLE001 — FAIL_OPEN at every layer
        return ()
    if rc != 0 or not stdout:
        return ()
    files = _parse_files(stdout)
    if cwd is not None:
        files = _utility_rerank(files, Path(cwd))
    return tuple(files)


def recall_files_batch(queries: list[str], cwd: Path | None = None,
                       recall_runner=None) -> list[tuple[str, ...]]:
    """#194: per-query file tuples for one dispatch, answered by ONE
    references_recall.py child (`--queries` batch face — the layered index
    is parsed once, not once per query). The per-query subprocess was the
    #194 flake: every child re-parsed the full index and individually
    flirted with its timeout under CI xdist contention, and fail-open then
    silently dropped whole queries (pinned doc-set assertions flapped with
    a different failing membership every run).

    Contract:
      - recall_runner injected (pure tests, sibling callers): delegated to
        the per-query recall_files path — one runner call per query, same
        shapes as before.
      - no runner: one batched child; rc != 0 or empty stdout fails open
        for the whole dispatch (all tuples empty) — same failure semantics
        the per-query path had, now at dispatch granularity.
      - rerank: when cwd is supplied, each non-empty query result is
        utility-reranked exactly like recall_files does.
    """
    if recall_runner is not None:
        return [recall_files(q, cwd=cwd, recall_runner=recall_runner)
                for q in queries]
    rc, stdout = _run_recall_batch(queries, cwd)
    if rc != 0 or not stdout:
        return [() for _ in queries]
    sections = _split_batch_stdout(stdout, queries)
    out: list[tuple[str, ...]] = []
    for q in queries:
        files = _parse_files(sections.get(q, ""))
        if cwd is not None and files:
            files = _utility_rerank(files, Path(cwd))
        out.append(files)
    return out


def _guidance(queries: list[str], files: list[str]) -> str:
    # #55 XML injection standard: the recall is INTERNAL kunglao knowledge
    # (references/_INDEX.md + the re-library), so the producer tag is
    # <kunglao-facts> — never <external-tools>. Marks, never gates:
    # rc stays 0 and the payload shape is unchanged
    # (references/contracts/xml-injection-standard.md).
    return (
        f"<kunglao-facts>\n"
        f"recall_inject: claim dispatch knowledge recall (#268) - "
        f"queries: {', '.join(queries)}\n"
        f"Before dispatching, read: {', '.join(files)}\n"
        f"</kunglao-facts>"
    )


def _trace(ws: Path, kind: str, action: str, detail: str, files: int = 0
           ) -> None:
    """#814: fail-open ≠ fail-silent — every recall path leaves a trace
    (kunglao_log emit + recall_metrics record). Telemetry must never block
    dispatch: any error is swallowed. Modules load by explicit file path
    (this hook has no scripts/ sys.path injection of its own) — #863
    Family B: via the canonical loader, fail-open wrappers unchanged."""
    try:
        mod = load_module_by_path(
            "kunglao_log_recall814", SKILL_DIR / "scripts" / "kunglao_log.py")
        mod.emit(ws, "recall_inject", action, tool="Agent", detail=detail)
    except Exception:  # noqa: BLE001
        pass
    try:
        mod = load_module_by_path(
            "recall_metrics_recall814",
            SKILL_DIR / "scripts" / "recall_metrics.py")
        mod.record(ws, kind=kind, query=detail[:80], files=files,
                   reason=action)
    except Exception:  # noqa: BLE001
        pass


def evaluate(payload: dict, recall_runner=None) -> tuple[int, str, str | None]:
    """Hook decision for a PreToolUse(Agent) dispatch payload (#268/#761 J4).

    Returns (exit_code, stderr_text, additional_context_or_None):
      - (0, "", None) — not a kunglao workspace / not a claim or red-team
        dispatch / recall failed or matched nothing (FAIL_OPEN: dispatch
        proceeds)
      - (0, "", ctx)  — recall matched: guidance naming the reference files
    rc is ALWAYS 0 — this hook injects knowledge, never rejects.
    Trigger faces: claim dispatch (`[T<N> tools=...] claim C-NN`, #268) and
    red-team verification dispatch (#761 J4 — adversarial knowledge BEFORE
    the checker plans its attacks).
    """
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0, "", None
    prompt_text = _dispatch_text(payload)
    if not prompt_text:
        return 0, "", None

    is_claim = _is_claim_dispatch(prompt_text)
    if not is_claim and not REDTEAM_RE.search(prompt_text):
        # #814: fail-open ≠ fail-silent — 留痕后放行
        _trace(ws, "skipped", "recall_skip",
               "not_a_claim_or_redteam_dispatch")
        return 0, "", None  # neither a claim nor a red-team dispatch

    if is_claim:
        tier = tier_for_claim({"statement": prompt_text})
        queries = queries_for_features(prompt_text, tier)
    else:
        queries = queries_for_redteam(prompt_text)

    files: list[str] = []
    seen: set[str] = set()
    per_query = recall_files_batch(queries, cwd=ws,
                                   recall_runner=recall_runner)
    for batch_files in per_query:
        for f in batch_files[:FILES_PER_QUERY]:
            if f not in seen:
                seen.add(f)
                files.append(f)
    if not files:
        _trace(ws, "no_match", "recall_skip", "no_recall_results: "
               + ",".join(queries[:3]))
        return 0, "", None  # no knowledge to inject
    _trace(ws, "injected", "recall_injected",
           "files:" + ",".join(files[:MAX_FILES]), files=len(files))
    return 0, "", _guidance(queries, files[:MAX_FILES])


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    rc, stderr_text, context = evaluate(payload)
    if stderr_text:
        print(stderr_text, file=sys.stderr)
    if context:
        # mirror dispatch_gate.py:137-142 / env_check_gate main() — the model
        # receives the recall guidance before the dispatch is processed
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": context,
            }
        }, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
