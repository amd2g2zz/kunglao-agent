# -*- coding: utf-8 -*-
"""tests/test_tool_first_243.py — issue #243: tool-first as a STANDING,
REPEATED, worker-decided operation (the recall twin #242's ruling, applied
to tools).

wbtest evidence (2026-09-12): the orchestrator hand-rolled a 118-line raw
ELF parser while `readelf -r` had ALREADY WORKED in its own transcript, IDA
was installed, capstone was a declared dep — zero value comparison happened.
tools/tool-search.py --find existed (SKILL.md:44) but nothing in the
worker's rhythm invoked it.

Contract under test:
  (a) citation gate (decision_lint shape — pure predicate, gate on gathered
      facts): a plan that proposes WRITING a new script at a make-vs-reuse
      decision MUST cite a tool-search --find result
      (`tool-search: <keywords> -> <hit|none>`); missing citation -> the
      plan-check-point gate REJECTS with mechanical guidance. RED-first:
      writing a new script with no cited result is flagged.
  (b) instrument menu rides dispatch (read-only price board, NOT a command):
      the dispatch context carries the actor-side snapshot for the claim's
      domain — toolbox entries (route_capability providers), system CLIs
      available (which-scan over the toolchain CHECK_SETS vocabulary),
      declared deps. EXTENDS the #293 context manifest with {kind:
      "instrument"} items — no second assembly path. Appears for a claim
      with a declared domain_family tag (#241).
  (c) WARN floor: a >50-line workspace script whose capability words match
      an available CLI ("readelf exists") triggers a WARN — never a REJECT.
  (d) ladder completion / promotion flag: a workspace script carrying a
      `promotion: <why>` note emits into the lesson/settlement channel
      (toolbox_promotion_proposed) — an emit + a note field, no new
      machinery.
  (e) provenance: every CITED tool-search result is a ledger row
      (toolfirst_search) at the approval point.

Fast tier: pure unit + tmp-path file IO only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("scripts", "hooks"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import yaml  # noqa: E402

import instrument_menu as im  # noqa: E402 — the #243 module (RED: absent)
import worker_budget_gates as wbg  # noqa: E402
import event_taxonomy  # noqa: E402


# ---------- fixtures ----------

def _write_reg(ws: Path, claims: list[dict]) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True,
                       sort_keys=False), encoding="utf-8")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """Minimal workspace: register + runs + one armed (pre-dispatched) claim."""
    w = tmp_path / "ws"
    _write_reg(w, [{"id": "C-001", "status": "OPEN",
                    "domain_family": "crypto-analysis",
                    "statement": "decode the config blob"}])
    (w / "runs").mkdir(parents=True)
    (w / "runs" / ".dispatch-anchor-C001.jsonl").write_text(
        json.dumps({"ts": "2026-09-12T00:00:00Z", "claim": "C-001"}) + "\n",
        encoding="utf-8")
    return w


def _write_plan(ws: Path, text: str, cid: str = "C-001") -> Path:
    key = cid.replace("-", "")
    p = ws / "runs" / f"plan-{key}.md"
    p.write_text(text, encoding="utf-8")
    return p


ARMED_PATHS = lambda w: {"workspace": str(w)}  # noqa: E731


PLAN_HANDROLL_NO_CITE = """goal: decode the config blob
preflight: check tools/_INDEX.yaml
steps:
- write a new script to parse the config container
- run it on the sample
fallback: grep the raw bytes
"""

PLAN_HANDROLL_CITED = """goal: decode the config blob
preflight: tool-search: config decode -> none
steps:
- write a new script to parse the config container (nothing matched)
fallback: grep the raw bytes
"""

PLAN_NO_SCRIPT_INTENT = """goal: decode the config blob
steps:
- run tools/crypto-tool.py --in sample.bin decode
fallback: xxd the header
"""


# ---------- (a) pure citation predicate (decision_lint shape) ----------

def test_intent_without_citation_is_a_defect():
    defects = im.citation_defects(PLAN_HANDROLL_NO_CITE)
    assert defects, "script-writing plan with no tool-search citation -> flagged"


def test_intent_with_cited_result_passes():
    assert im.citation_defects(PLAN_HANDROLL_CITED) == []


def test_no_script_intent_is_silent():
    assert im.citation_defects(PLAN_NO_SCRIPT_INTENT) == []


def test_bare_marker_without_result_is_not_a_citation():
    # anti-self-attestation (#630 shape): `tool-search:` with no cited
    # RESULT is not a value comparison.
    text = PLAN_HANDROLL_NO_CITE.replace("write a new script",
                                         "tool-search:\n- write a new script")
    assert im.citation_defects(text), "bare marker must not count as cited"


def test_handroll_wording_triggers_intent():
    assert im.script_write_intent("we hand-rolled a 118-line ELF parser")
    assert im.script_write_intent("create a helper script for the rela table")
    assert im.script_write_intent("新建脚本解析配置容器")
    assert not im.script_write_intent("run the existing script scripts/x.py")


def test_citations_parse_keywords_and_result():
    rows = im.tool_search_citations(
        "- tool-search: elf rela readelf -> readelf\n"
        "- tool-search: config decode -> none\n")
    assert {"keywords": "elf rela readelf", "result": "readelf"} in rows
    assert {"keywords": "config decode", "result": "none"} in rows


# ---------- (a) the gate at the plan-check point ----------

def test_gate_rejects_uncited_script_writing(ws):
    _write_plan(ws, PLAN_HANDROLL_NO_CITE)
    ok, reason = wbg.check_tool_search_citation(ARMED_PATHS(ws), "C-001")
    assert ok is False, "uncited script-writing plan must be REJECTED"
    assert "tool-search" in reason and "--find" in reason, \
        "rejection must carry the mechanical beat guidance"


def test_gate_passes_cited_plan(ws):
    _write_plan(ws, PLAN_HANDROLL_CITED)
    ok, reason = wbg.check_tool_search_citation(ARMED_PATHS(ws), "C-001")
    assert ok is True


def test_gate_silent_without_script_intent(ws):
    _write_plan(ws, PLAN_NO_SCRIPT_INTENT)
    ok, _ = wbg.check_tool_search_citation(ARMED_PATHS(ws), "C-001")
    assert ok is True


def test_gate_not_armed_on_first_dispatch(tmp_path):
    w = tmp_path / "ws2"
    _write_reg(w, [{"id": "C-001", "status": "OPEN"}])
    (w / "runs").mkdir(parents=True)
    _write_plan(w, PLAN_HANDROLL_NO_CITE)
    ok, _ = wbg.check_tool_search_citation(ARMED_PATHS(w), "C-001")
    assert ok is True, "first dispatch: no worker plan yet, gate not armed"


def test_gate_failopen_without_plan(ws):
    ok, _ = wbg.check_tool_search_citation(ARMED_PATHS(ws), "C-001")
    assert ok is True, "no-plan rejection belongs to the plan-first gate"


# ---------- (b) instrument menu ----------

def test_menu_shape_toolbox_clis_deps(ws):
    menu = im.build_instrument_menu(ws, claim_id="C-001")
    assert menu["kind"] == "instrument_menu"
    assert menu["domain"] == "crypto-analysis", \
        "the #241 domain_family tag feeds the menu"
    assert isinstance(menu["system_clis"], list) and menu["system_clis"], \
        "which-scan must list the CLIs available on this host"
    for cli in menu["system_clis"]:
        assert set(cli) >= {"name", "path"}
        assert Path(cli["path"]).exists()
    assert isinstance(menu["deps"], list) and "capstone" in menu["deps"], \
        "declared deps come from the skill pyproject (capstone is one)"
    assert menu["toolbox"], "toolbox entries come from tools/_INDEX.yaml"
    for entry in menu["toolbox"]:
        assert set(entry) >= {"name", "capability", "tier", "cost_tier"}


def test_menu_domain_ranks_crypto_first(ws):
    menu = im.build_instrument_menu(ws, claim_id="C-001")
    keywords = im._domain_keywords("crypto-analysis")
    matched = [e for e in menu["toolbox"]
               if any(k in " ".join(str(e.get(k2) or "") for k2 in
                                    ("name", "capability", "description"))
                      .lower() for k in keywords)]
    unmatched = [e for e in menu["toolbox"] if e not in matched]
    assert matched, "the crypto-analysis domain matches toolbox entries"
    menu_ids = [id(e) for e in menu["toolbox"]]
    first_unmatched = min((menu_ids.index(id(e)) for e in unmatched),
                          default=len(menu_ids))
    assert all(menu_ids.index(id(e)) < first_unmatched for e in matched), \
        "domain-matched toolbox entries rank first (stable, no invention)"


def test_menu_failopen_on_empty_workspace(tmp_path):
    menu = im.build_instrument_menu(tmp_path / "nope", claim_id="C-404")
    assert menu["kind"] == "instrument_menu"
    assert menu["domain"] is None
    assert menu["system_clis"] == [] or menu["system_clis"]


def test_dispatch_context_carries_instrument_menu(ws):
    from dispatch_context import (build_dispatch_context,  # noqa: E402
                                  validate_context_shape)
    ctx = build_dispatch_context(ws=ws, claim_id="C-001", tier=1, tools=[],
                                 agent_name="kunglao-worker")
    assert "instrument_menu" in ctx, \
        "the price board rides EVERY dispatch (read-only, not a command)"
    validate_context_shape(ctx), "optional key must keep the strict face green"
    assert ctx["instrument_menu"]["kind"] == "instrument_menu"


def test_manifest_gains_instrument_items(ws):
    from dispatch_context import _context_manifest  # noqa: E402
    from dispatch_context import build_dispatch_context  # noqa: E402
    ctx = build_dispatch_context(ws=ws, claim_id="C-001", tier=1, tools=[],
                                 agent_name="kunglao-worker")
    manifest = _context_manifest(ctx)
    instruments = [i for i in manifest["items"] if i["kind"] == "instrument"]
    assert instruments, "#293 manifest EXTENDED with {kind: instrument} items"
    assert all(i["source"] == "instrument_menu" for i in instruments)
    names = {i["ref"] for i in instruments}
    assert any("readelf" == n for n in names) or len(names) >= 3


def test_manifest_version_compatible_without_menu(ws, monkeypatch):
    # a broken menu build must degrade to the pre-#243 context (no key), and
    # the manifest must stay byte-shape-compatible (additive only).
    from dispatch_context import _context_manifest  # noqa: E402
    from dispatch_context import build_dispatch_context  # noqa: E402
    monkeypatch.setattr(im, "context_block", lambda *a, **k: None,
                        raising=True)
    ctx = build_dispatch_context(ws=ws, claim_id="C-001", tier=1, tools=[],
                                 agent_name="kungloa-worker"[:14])
    assert "instrument_menu" not in ctx
    manifest = _context_manifest(ctx)
    assert manifest["kind"] == "context_manifest"
    assert not [i for i in manifest["items"] if i["kind"] == "instrument"]


def test_validate_menu_block_rejects_garbage():
    with pytest.raises(ValueError):
        im.validate_menu_block({"kind": "instrument_menu"})
    im.validate_menu_block({"kind": "instrument_menu", "domain": None,
                            "toolbox": [], "system_clis": [], "deps": []})


# ---------- (c) WARN floor ----------

def _script(lines: int, body: str = "x = 1\n") -> str:
    header = "#!/usr/bin/env python3\n"
    return header + body * max(lines - 1, 1)


def test_floor_flags_long_script_matching_cli():
    # the wbtest shape: the transcript had `readelf -r` ALREADY WORKING, and
    # the fallback branch names the CLI it duplicates — distinctive-term
    # matching (FLOOR_STOPWORDS discipline), never generic prose.
    scripts = {"scripts/elf_rela_ptr_table.py":
               _script(118, "out = run(['readelf', '-r', path])\n")}
    findings = im.handroll_floor_findings(
        scripts, ["readelf", "objdump"], limit=50)
    assert len(findings) == 1
    f = findings[0]
    assert f["lines"] == 118 and f["matched"] == ["readelf"]


def test_floor_silent_under_line_limit():
    scripts = {"scripts/small.py": _script(40, "data = readelf_rela()\n")}
    assert im.handroll_floor_findings(scripts, ["readelf"], limit=50) == []


def test_floor_silent_without_cli_tokens():
    scripts = {"scripts/unrelated.py": _script(60, "process_rows(db)\n")}
    assert im.handroll_floor_findings(scripts, ["readelf"], limit=50) == []


def test_floor_matches_hyphenated_cli_names():
    scripts = {"scripts/dump.py": _script(60, "run(['class-dump', p])\n")}
    findings = im.handroll_floor_findings(scripts, ["class-dump"], limit=50)
    assert findings and findings[0]["matched"] == ["class-dump"]


def test_floor_gate_warns_but_never_rejects(ws, tmp_path, monkeypatch):
    scripts_dir = ws / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "elf_rela_ptr_table.py").write_text(
        _script(118, "out = run(['readelf', '-r', path])\n"), encoding="utf-8")
    emitted: list[tuple] = []
    monkeypatch.setattr(im, "emit_event",
                        lambda w, a, **k: emitted.append((a, k)))
    # deterministic CLI supply: the host which-scan (fail-open -> empty on
    # transient failure) made this test environment-flaky in CI; the floor
    # LOGIC under test needs exactly one known CLI, not the scanner
    monkeypatch.setattr(im, "available_system_clis",
                        lambda: [{"name": "readelf"}])
    ok, msg = wbg.check_handroll_floor(ARMED_PATHS(ws), "C-001")
    assert ok is True, "WARN floor NEVER rejects a dispatch"
    assert "WARN" in msg and "readelf" in msg
    assert any(a == "handroll_warn" for a, _ in emitted)


def test_floor_gate_silent_on_clean_workspace(ws):
    ok, msg = wbg.check_handroll_floor(ARMED_PATHS(ws), "C-001")
    assert ok is True and msg == ""


# ---------- (d) promotion flag (ladder completion) ----------

def test_promotion_note_parsed_from_script_header():
    text = "#!/usr/bin/env python3\n# promotion: proven on C-005, 3 claims reused it\nx = 1\n"
    proposals = im.scan_promotion_proposals({"scripts/env_fix.py": text})
    assert proposals == [{"script": "scripts/env_fix.py",
                          "note": "proven on C-005, 3 claims reused it"}]


def test_promotion_emit_lands_in_ledger(ws):
    proposals = [{"script": "scripts/env_fix.py", "note": "proven on C-005"}]
    n = im.emit_promotion_proposals(ws, proposals, claim="C-001")
    assert n == 1
    from kunglao_log import _all_rows
    rows = [r for r in _all_rows(ws) if r.get("action") ==
            "toolbox_promotion_proposed"]
    assert rows, "promotion proposal reaches the lesson/settlement channel"
    detail = json.loads(rows[0]["detail"])
    assert detail["script"] == "scripts/env_fix.py"
    assert detail["note"] == "proven on C-005"


def test_promotion_emit_failopen_on_bad_ws(tmp_path):
    assert im.emit_promotion_proposals(tmp_path / "nope", []) == 0


def test_floor_gate_carries_promotion_proposals(ws, monkeypatch):
    scripts_dir = ws / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "env_fix.py").write_text(
        "# promotion: proven on C-005\n" + _script(10), encoding="utf-8")
    emitted: list[tuple] = []
    monkeypatch.setattr(im, "emit_event",
                        lambda w, a, **k: emitted.append((a, k)))
    ok, _ = wbg.check_handroll_floor(ARMED_PATHS(ws), "C-001")
    assert ok is True
    assert any(a == "toolbox_promotion_proposed" for a, _ in emitted), \
        "the standing script pass carries proposals into the channel"


# ---------- (e) provenance: cited searches are ledger rows ----------

def test_record_tool_search_citations_emits_rows(ws):
    _write_plan(ws, PLAN_HANDROLL_CITED)
    n = wbg.record_tool_search_citations(ARMED_PATHS(ws), "C-001")
    assert n == 1
    from kunglao_log import _all_rows
    rows = [r for r in _all_rows(ws)
            if r.get("action") == "toolfirst_search"]
    assert rows and rows[0]["claim"] == "C-001"
    detail = json.loads(rows[0]["detail"])
    assert detail["keywords"] == "config decode"
    assert detail["result"] == "none"


def test_record_citations_silent_without_plan(ws):
    assert wbg.record_tool_search_citations(ARMED_PATHS(ws), "C-001") == 0


# ---------- emit vocabulary + wiring ----------

def test_emit_words_registered_at_sorted_position():
    for word in ("toolfirst_search", "handroll_warn",
                 "toolbox_promotion_proposed"):
        assert word in event_taxonomy.EMIT_ACTIONS, f"{word} not registered"
    assert event_taxonomy.EMIT_ACTIONS == sorted(event_taxonomy.EMIT_ACTIONS), \
        "the controlled vocabulary stays sorted (registration discipline)"


def test_gate_wired_into_pre_check_battery():
    src = (ROOT / "hooks" / "worker_budget_sinks.py").read_text("utf-8")
    assert "'toolsearch', check_tool_search_citation" in src, \
        "citation gate rides the plan-check point in the battery"
    assert "'handroll', check_handroll_floor" in src, \
        "WARN floor rides the same battery"
    assert "record_tool_search_citations(paths, cid, prompt)" in src, \
        "citation provenance rows fire at the approval point"
