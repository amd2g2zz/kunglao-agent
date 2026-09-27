#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""instrument_menu.py — issue #243: tool-first as a standing, repeated,
worker-decided operation. The actor-side price board + the make-vs-reuse
beat's mechanical faces.

wbtest evidence (2026-09-12): the orchestrator hand-rolled a 118-line raw
ELF parser (scripts/elf_rela_ptr_table.py) while `readelf -r` had ALREADY
WORKED in its own transcript, IDA was installed, capstone was a declared
dep — zero value comparison happened. tools/tool-search.py --find existed
(SKILL.md:44) but nothing in the worker's rhythm invoked it. Same ruling as
the recall twin #242: standing, repeated, worker-decided.

Faces (all fail-open unless noted):

  build_instrument_menu(ws, claim_id, domain) -> dict
      The instrument menu: {kind, domain, toolbox, system_clis, deps}.
      Read-only price board — a menu, NEVER a command. toolbox = compact
      projection of tools/_INDEX.yaml (route_capability loader — no second
      assembly path); system_clis = which-scan over the toolchain
      CHECK_SETS CLI vocabulary (found only); deps = the skill's declared
      pyproject dependencies. The #241 domain_family tag ranks
      domain-matching toolbox entries first (stable, zero invented
      vocabulary — keywords are claim_granularity.STEP_DOMAIN_TABLE's).
  context_block(ws, claim_id) -> dict
      The dispatch-context seam: build + shape-check. dispatch_context.py
      calls this and ONLY this (one assembly path).
  manifest_items(menu) -> list
      #293 context-manifest extension: one {kind: "instrument", ref,
      source: "instrument_menu"} row per menu entry — additive,
      version-compatible (detail JSON; pre-#293 readers .get()-based).
  validate_menu_block(menu) -> None
      Strict shape face — raises ValueError on contract violation.
  citation_defects(text) / script_write_intent(text) / tool_search_citations(text)
      The beat's PURE predicate (decision_lint shape: gate on gathered
      facts, never probe). A plan proposing to WRITE a new script must
      carry a cited --find result: `tool-search: <keywords> -> <hit|none>`;
      a bare marker without a result is NOT a citation (#630
      anti-self-attestation shape). No script intent -> silent.
  workspace_scripts(ws) / handroll_floor_findings(scripts, clis, limit)
      The WARN floor: a >HANDROLL_LINE_FLOOR-line workspace script whose
      capability words match an available CLI/toolbox name ("readelf
      exists"). Cheap token overlap (the tool_value.line_tool_hits single
      matching rule); WARN, never REJECT — false-positive-tolerant by
      design (a comment mention warns; it does not block).
  scan_promotion_proposals(scripts) / emit_promotion_proposals(ws, ...)
      Ladder completion: a workspace-proven script carries a
      `promotion: <why>` header note; the emit lands it in the
      lesson/settlement channel (toolbox_promotion_proposed). An emit + a
      note field — no new machinery.

Ladder (agents/kunglao-worker.md): toolbox CLI -> wrap an available system
CLI -> installed lib (declared dep) -> agent-do install -> hand-roll LAST.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

# issue 275 batch-3 posture: fail-open faces keep liveness (never raise,
# never change the return shape) but leave ONE trace - a stderr WARN naming
# the operation + reason, rate-limited to once per op until the reason
# changes.
_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] instrument_menu WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


# ---------- constants ----------

MENU_KIND = "instrument_menu"
# the toolbox face is a menu, not the full index dump: domain-matched
# entries first, then index order, capped (the #692 providers block already
# carries the ranked per-capability detail).
MENU_TOOLBOX_CAP = 16
# the WARN floor line count — the proven failure shape was a 118-line
# hand-rolled parser; scripts at or under the floor never warn.
HANDROLL_LINE_FLOOR = 50
# workspace script faces scanned by the floor / promotion pass
SCRIPT_SUFFIXES = (".py", ".sh")
MAX_SCRIPT_BYTES = 262144  # cheap guard: the floor reads text, not binaries

# CHECK_SETS item names that are probe/abstract faces, not PATH CLIs — the
# which-scan drops them (pefile/unidbg ride the deps face instead).
_NON_CLI_CHECK_ITEMS = frozenset({
    "vm_reachable", "remote_debugger", "device_root", "debug_flag",
    "jdwp_debug", "ebpf", "ebpf_android", "frida_server", "android_server",
    "darwin_runtime", "root_available", "app_permissions", "decompiler",
    "jvm", "channel:docker", "pefile", "unidbg",
})

# generic CLI names excluded from the WARN-floor vocabulary ONLY (they stay
# on the menu): a Python script saying `file`/`strings` is prose, not a
# make-vs-reuse signal — distinctive terms only (the issue 380 P2 structural
# trigger discipline, worker_budget_gates._is_distinctive_trigger).
FLOOR_STOPWORDS = frozenset({
    "file", "strings", "cat", "head", "tail", "echo", "find", "sort",
    "date", "env", "test", "sleep", "touch", "uname",
})

# ---------- events (controlled vocabulary: event_taxonomy.EMIT_ACTIONS) ----


def emit_event(ws, action: str, *, claim: str | None = None,
               detail: str | None = None) -> bool:
    """Fail-open ledger emit (kunglao_record posture): the menu/beat faces
    log through the unified channel; observability never raises."""
    try:
        from kunglao_log import emit
        return bool(emit(Path(ws), actor="instrument_menu", action=action,
                         claim=claim, detail=detail))
    except Exception as exc:  # noqa: BLE001 — logging never breaks the face
        warn("emit_event", f"{type(exc).__name__}: {exc}")
        return False


# ---------- input faces (each fail-open to empty) ---------------------------

def _skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def toolbox_entries(index_path: Path | None = None) -> list[dict]:
    """Compact toolbox projection via the route_capability loader (single
    index-assembly source; no second parse path)."""
    try:
        import route_capability as rc
        tools = rc.load_index(index_path or rc.DEFAULT_INDEX)
    except Exception as exc:  # noqa: BLE001 — fail-open
        warn("toolbox_entries", f"{type(exc).__name__}: {exc}")
        return []
    out = []
    for t in tools or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        out.append({"name": str(t["name"]),
                    "capability": str(t.get("capability") or ""),
                    "tier": str(t.get("tier") or ""),
                    "cost_tier": str(t.get("cost_tier") or ""),
                    "description": str(t.get("description") or "")})
    return out


def available_system_clis() -> list[dict]:
    """The which-scan face: shutil.which over the toolchain CHECK_SETS CLI
    vocabulary (single source of the per-type tool names), found-only,
    sorted by name. Fail-open: toolchain unavailable -> empty."""
    names: set[str] = set()
    try:
        import toolchain as tc
        for items in (tc.CHECK_SETS or {}).values():
            names.update(str(i) for i in items)
    except Exception as exc:  # noqa: BLE001 — fail-open
        warn("available_system_clis", f"{type(exc).__name__}: {exc}")
        return []
    out = []
    for name in sorted(names - _NON_CLI_CHECK_ITEMS):
        path = shutil.which(name)
        if path:
            out.append({"name": name, "path": path})
    return out


def declared_deps(skill_root: Path | None = None) -> list[str]:
    """The skill's declared pyproject dependencies, names only, declaration
    order. tomllib/tomli first, tolerant line-parse fallback."""
    pyproject = (skill_root or _skill_root()) / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return []
    # tomllib is 3.11+; the repo floor is 3.10 — tomli fallback contract
    # (tests/test_python_floor.py anchors the exact shape).
    try:
        import tomli as tomllib
    except ImportError:
        import tomllib
    try:
        data = tomllib.loads(text)
    except Exception:  # noqa: BLE001 — fall through to the tolerant parse
        data = _deps_fallback_parse(text)
    deps = data.get("project", {}).get("dependencies") or []
    out = []
    for d in deps:
        name = re.split(r"[<>=!;\[ ]", str(d), 1)[0].strip()
        if name:
            out.append(name)
    return out


def _deps_fallback_parse(text: str) -> dict:
    """Tolerant [project] dependencies = [...] line-parse (quoted entries,
    comments/trailing commas tolerated)."""
    deps: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw
        if not in_block:
            if re.match(r'^dependencies\s*=\s*\[', line.strip()):
                in_block = True
            continue
        if line.strip().startswith("]"):
            break
        for m in re.finditer(r'"([^"]+)"', line):
            deps.append(m.group(1))
    return {"project": {"dependencies": deps}}


def domain_for_claim(ws: Path, claim_id: str) -> str | None:
    """The claim's declared domain_family tag (#241 granularity split), or
    None. Fail-open: no register / no claim / no tag -> None."""
    try:
        import yaml
        reg = yaml.safe_load(
            (Path(ws) / "claim-register.yaml").read_text(encoding="utf-8")) \
            or {}
        for c in reg.get("claims") or []:
            if isinstance(c, dict) and c.get("id") == claim_id:
                tag = str(c.get("domain_family") or "").strip()
                return tag or None
    except Exception as exc:  # noqa: BLE001 — fail-open
        warn("domain_for_claim", f"{type(exc).__name__}: {exc}")
    return None


# ---------- the menu ---------------------------------------------------------

def _domain_keywords(domain: str | None) -> tuple[str, ...]:
    """claim_granularity.STEP_DOMAIN_TABLE keywords for the #241 family —
    single source, zero invented vocabulary. Unknown family -> ()."""
    if not domain:
        return ()
    try:
        from claim_granularity import STEP_DOMAIN_TABLE
        for family, _inferred, keywords in STEP_DOMAIN_TABLE:
            if family == domain:
                return tuple(keywords)
    except Exception as exc:  # noqa: BLE001 — fail-open
        warn("_domain_keywords", f"{type(exc).__name__}: {exc}")
    return ()


def build_instrument_menu(ws: Path | str, claim_id: str | None = None,
                          domain: str | None = None) -> dict:
    """The read-only price board (a menu, NEVER a command). Every face is
    fail-open; an absent domain leaves the toolbox in index order."""
    ws = Path(ws)
    if domain is None and claim_id:
        domain = domain_for_claim(ws, claim_id)
    keywords = _domain_keywords(domain)
    toolbox = toolbox_entries()

    def score(entry: dict) -> int:
        if not keywords:
            return 0
        hay = " ".join(str(entry.get(k) or "") for k in
                       ("name", "capability", "description")).lower()
        return 1 if any(k in hay for k in keywords) else 0

    ranked = sorted(enumerate(toolbox),
                    key=lambda pair: (-score(pair[1]), pair[0]))
    return {
        "kind": MENU_KIND,
        "domain": domain,
        "toolbox": [e for _i, e in ranked[:MENU_TOOLBOX_CAP]],
        "system_clis": available_system_clis(),
        "deps": declared_deps(),
    }


def context_block(ws: Path | str, claim_id: str | None) -> dict:
    """The dispatch-context seam — build + strict shape check. This is the
    ONLY function dispatch_context.py calls (one assembly path)."""
    menu = build_instrument_menu(ws, claim_id)
    validate_menu_block(menu)
    return menu


def validate_menu_block(menu: dict) -> None:
    """Strict validation — raises ValueError on contract violation."""
    if not isinstance(menu, dict) or menu.get("kind") != MENU_KIND:
        raise ValueError("instrument menu must be a dict with "
                         f"kind={MENU_KIND!r}")
    for key, typ in (("toolbox", list), ("system_clis", list),
                     ("deps", list)):
        if not isinstance(menu.get(key), typ):
            raise ValueError(f"instrument menu key {key!r} must be "
                             f"{typ.__name__}")
    for cli in menu["system_clis"]:
        if not isinstance(cli, dict) or not cli.get("name") \
                or not cli.get("path"):
            raise ValueError("instrument menu system_clis entries must "
                             "carry name + path")
    for dep in menu["deps"]:
        if not isinstance(dep, str) or not dep:
            raise ValueError("instrument menu deps entries must be names")


def manifest_items(menu: dict | None) -> list[dict]:
    """#293 context-manifest extension rows: one {kind: instrument, ref,
    source} per menu entry (CLIs + toolbox + deps). Additive only — the
    manifest rides detail JSON, so pre-#293 readers stay byte-compatible."""
    if not isinstance(menu, dict):
        return []
    items: list[dict] = []
    for cli in menu.get("system_clis") or []:
        if isinstance(cli, dict) and cli.get("name"):
            items.append({"kind": "instrument", "ref": str(cli["name"]),
                          "source": "instrument_menu"})
    for entry in menu.get("toolbox") or []:
        if isinstance(entry, dict) and entry.get("name"):
            items.append({"kind": "instrument", "ref": str(entry["name"]),
                          "source": "instrument_menu"})
    for dep in menu.get("deps") or []:
        items.append({"kind": "instrument", "ref": str(dep),
                      "source": "instrument_menu"})
    return items


# ---------- the beat's pure predicate (decision_lint shape) -----------------
# gate on gathered facts: the plan text IS the gathered fact; the predicate
# never probes the environment.

SCRIPT_INTENT_RE = re.compile(
    r"\b(?:write|create|add|implement|build|draft|develop)\s+"
    r"(?:a\s+|an\s+|the\s+|one\s+)?"
    r"(?:new\s+|small\s+|simple\s+|helper\s+|dedicated\s+)?"
    r"(?:python\s+|shell\s+)?script\b"
    r"|\bhand[- ]?roll(?:ed|ing)?\b"
    r"|\bnew\s+script\b"
    r"|写(?:一?个)?新?脚本|新建脚本|手写脚本|自行写脚本",
    re.IGNORECASE)

# the cited --find result: `tool-search: <keywords> -> <hit|none>`. A bare
# `tool-search:` with no result is NOT a citation (#630 shape).
TOOL_SEARCH_CITE_RE = re.compile(
    r"tool-search:\s*(.+?)\s*->\s*(\S+)", re.IGNORECASE)

CITATION_GUIDANCE = (
    "run `python tools/tool-search.py --find <keywords>` BEFORE hand-rolling "
    "and cite the outcome in the plan as "
    "`tool-search: <keywords> -> <hit|none>`")


def script_write_intent(text: str) -> list[str]:
    """Matched script-writing intent snippets ([] = no intent -> silent)."""
    return [m.group(0) for m in SCRIPT_INTENT_RE.finditer(text or "")]


def tool_search_citations(text: str) -> list[dict]:
    """Well-formed `tool-search: <keywords> -> <result>` rows in the text."""
    return [{"keywords": m.group(1).strip(), "result": m.group(2).strip()}
            for m in TOOL_SEARCH_CITE_RE.finditer(text or "")]


def citation_defects(text: str) -> list[str]:
    """decision_lint shape: PURE. A plan that proposes writing a new script
    without a cited tool-search result has ONE defect; no intent or a cited
    result -> no defects (silent, false-positive-tolerant)."""
    if not script_write_intent(text):
        return []
    if tool_search_citations(text):
        return []
    return ["script-writing intent without a cited tool-search result "
            f"({CITATION_GUIDANCE})"]


# ---------- the WARN floor ---------------------------------------------------

def workspace_scripts(ws: Path | str) -> dict[str, str]:
    """The workspace's script faces (ws/scripts/*.py|*.sh), size-capped,
    keyed by workspace-relative posix path."""
    scripts_dir = Path(ws) / "scripts"
    if not scripts_dir.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(scripts_dir.iterdir()):
        if not p.is_file() or p.suffix not in SCRIPT_SUFFIXES:
            continue
        try:
            if p.stat().st_size > MAX_SCRIPT_BYTES:
                continue
            out[p.relative_to(ws).as_posix()] = \
                p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # noqa: BLE001 — one unreadable file skips
            warn("workspace_scripts", f"{type(exc).__name__}: {exc}")
    return out


def handroll_floor_findings(scripts: dict[str, str], clis: list[str],
                            limit: int = HANDROLL_LINE_FLOOR) -> list[dict]:
    """A >limit-line script whose capability words match an available
    CLI/toolbox name. Token matching = the tool_value.line_tool_hits single
    rule (exact token for single-word names, separator-bound regex for
    hyphenated ones). Cheap, false-positive-tolerant: the caller WARNS,
    never rejects."""
    findings: list[dict] = []
    names = [str(c) for c in clis or []]
    if not names:
        return findings
    for path in sorted(scripts):
        text = scripts[path]
        if len(text.splitlines()) <= limit:
            continue
        try:
            from tool_value import line_tool_hits
            matched = sorted(line_tool_hits(text, names))
        except Exception as exc:  # noqa: BLE001 — fail-open to no findings
            warn("handroll_floor_findings", f"{type(exc).__name__}: {exc}")
            return findings
        if matched:
            findings.append({"script": path,
                             "lines": len(text.splitlines()),
                             "matched": matched})
    return findings


# ---------- promotion flag (ladder completion) -------------------------------

PROMOTION_NOTE_RE = re.compile(r"(?m)^\s*#*\s*promotion:\s*(\S.+)$")


def scan_promotion_proposals(scripts: dict[str, str]) -> list[dict]:
    """Workspace scripts carrying a `promotion: <why>` note — the note field
    of the promotion flag (NO new machinery: it is a header line)."""
    out: list[dict] = []
    for path in sorted(scripts):
        m = PROMOTION_NOTE_RE.search(scripts[path])
        if m:
            out.append({"script": path, "note": m.group(1).strip()})
    return out


def emit_promotion_proposals(ws: Path | str, proposals: list[dict],
                             claim: str | None = None) -> int:
    """Land promotion proposals in the lesson/settlement channel
    (toolbox_promotion_proposed rows). Fail-open; returns rows emitted."""
    n = 0
    for p in proposals or []:
        detail = json.dumps({"script": str(p.get("script") or ""),
                             "note": str(p.get("note") or "")},
                            ensure_ascii=False, sort_keys=True)
        if emit_event(ws, "toolbox_promotion_proposed", claim=claim,
                      detail=detail):
            n += 1
    return n


# ---------- CLI (smoke) ------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="instrument_menu.py",
        description="#243 the instrument menu (read-only price board) + "
                    "promotion-proposal scan")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--claim", default=None, help="claim id (C-NN)")
    ap.add_argument("--json", action="store_true",
                    help="menu as JSON on stdout")
    ap.add_argument("--scan-promotions", action="store_true",
                    help="emit toolbox_promotion_proposed rows for "
                         "workspace scripts carrying `promotion: <why>`")
    args = ap.parse_args(argv)
    if args.scan_promotions:
        scripts = workspace_scripts(args.workspace)
        n = emit_promotion_proposals(args.workspace,
                                     scan_promotion_proposals(scripts))
        print(f"promotion proposals emitted: {n}")
        return 0
    menu = build_instrument_menu(args.workspace, claim_id=args.claim)
    print(json.dumps(menu, ensure_ascii=False, indent=2)
          if args.json else _menu_text(menu))
    return 0


def _menu_text(menu: dict) -> str:
    lines = [f"instrument menu (domain={menu.get('domain') or '-'}) — "
             f"a price board, not a command (#243)"]
    lines.append("  toolbox:")
    lines += [f"    {e['name']}  [{e['capability']}] {e['tier']}/"
              f"{e['cost_tier']}" for e in menu["toolbox"]]
    lines.append("  system CLIs available:")
    lines += [f"    {c['name']}  ({c['path']})"
              for c in menu["system_clis"]]
    lines.append("  declared deps: " + ", ".join(menu["deps"]))
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
