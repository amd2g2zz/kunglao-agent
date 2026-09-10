# -*- coding: utf-8 -*-
"""Issue 215 — apk_mem_gate verdict gates formal analysis (env-fact wiring,
JVM probe, evidence classes).

Field pathology (wbtest run, 2026-09-10): a whole formal analysis ran on
unzip + grep. Two premises were never probed — the apk_mem_gate verdict
(the gate is a provider precondition agents bypassing the provider system
never touch) and the JVM ("no JVM" was read off dexdc's FEATURE text, not
`java -version`). String facts also satisfied algorithm-recovery claims.

This module pins the four enforcement faces:

  A. recording — init probes the gate for the aligned android target and
     records the verdict into <ws>/env-facts.yaml (issue 450 env facts, the
     issue 477 installed-ledger write-through precedent); env_manifest's
     render_section surfaces it.
  B. JVM probe — `java -version` joins _check_android (state-ladder
     layer 1, issue 213); HARD when jadx is present, WARN otherwise.
  C. evidence classes — a →PROVEN transition of an algorithm-scoped claim
     whose facts are all triage-grade fails admission with `evidence-class`
     named in the reason.
  D. wording/registry — the dexdc index entries carry the environment-probe
     caveat; jadx's provider requirements declare `jvm`.

E2 spike decision (mechanism choice, recorded here as the rationale of
record): 'algorithm-recovery claim identification' is done by SCOPE
KEYWORDS over the claim's own register text (statement/title), NOT by a new
claim-scope field. A new field nothing writes would be self-declaration —
the exact trust posture issue 819 rejects — while the register text is the
artifact of record the orchestrator already maintains. The KEEP list is the
four classes named by the issue (key_schedule / crypto_constant /
state_machine / algorithm_verify) in their snake_case and prose spellings.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

import env_manifest  # noqa: E402
import lint_facts  # noqa: E402
import register_proven_gate as rpg  # noqa: E402
import route_capability as rc  # noqa: E402
import toolchain as tc  # noqa: E402
import yaml  # noqa: E402

_INIT_MOD = None


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen blocks direct import)."""
    global _INIT_MOD
    if _INIT_MOD is None:
        spec = importlib.util.spec_from_file_location(
            "kunglao_init_memgate_215", SCRIPTS / "kunglao-init.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _INIT_MOD = mod
    return _INIT_MOD


# =========================================================================
# A. gate verdict recorded as an env fact
# =========================================================================

def _android_ws(tmp_path: Path, sample: str = "wbtest.apk") -> Path:
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / sample).write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    return ws


def _stub_gate(monkeypatch, mod, verdict="smali-only",
               est=4.0, budget=2.6, reason=""):
    calls = []

    def _fake(ws, target_path, timeout=120):
        calls.append((Path(ws), Path(target_path)))
        return {"verdict": verdict, "est_heap_gb": est,
                "budget_gb": budget, "reason": reason}

    monkeypatch.setattr(mod, "_run_mem_gate_cli", _fake)
    return calls


def test_init_records_mem_gate_verdict_as_env_fact(monkeypatch, tmp_path):
    """The gate is a PROBE, not a pipeline stage: init runs it on the
    aligned android target and the verdict lands in the env facts."""
    mod = _load_init_module()
    ws = _android_ws(tmp_path)
    calls = _stub_gate(monkeypatch, mod)

    rec = mod.record_mem_gate_verdict(ws, "android", "wbtest.apk")

    assert rec is not None and rec["verdict"] == "smali-only", rec
    assert calls and calls[0][1].name == "wbtest.apk", calls
    facts = yaml.safe_load((ws / "env-facts.yaml").read_text("utf-8"))
    assert facts["mem_gate"]["verdict"] == "smali-only", facts
    assert facts["mem_gate"]["est_heap_gb"] == 4.0, facts


def test_mem_gate_unavailable_when_no_aligned_target(monkeypatch, tmp_path):
    """No target -> `unavailable` is an EXPLICIT env fact (never a silent
    skip, never a fabricated verdict); the gate CLI is not invoked."""
    mod = _load_init_module()
    ws = _android_ws(tmp_path)
    calls = _stub_gate(monkeypatch, mod)

    rec = mod.record_mem_gate_verdict(ws, "android", None)

    assert rec is not None and rec["verdict"] == "unavailable", rec
    assert rec.get("reason"), rec
    assert calls == [], "the gate must not run without an aligned target"
    facts = yaml.safe_load((ws / "env-facts.yaml").read_text("utf-8"))
    assert facts["mem_gate"]["verdict"] == "unavailable", facts


def test_mem_gate_probe_is_android_only(monkeypatch, tmp_path):
    """Lane gating is issue 208's work — this probe fires on android only: a
    windows/linux/web workspace records nothing at all."""
    mod = _load_init_module()
    ws = _android_ws(tmp_path)
    calls = _stub_gate(monkeypatch, mod)
    for ptype in ("windows", "linux", "web", "macos"):
        assert mod.record_mem_gate_verdict(ws, ptype, "wbtest.apk") is None
    assert calls == []
    assert not (ws / "env-facts.yaml").exists()


def test_mem_gate_cli_runner_parses_the_one_json_line(monkeypatch, tmp_path):
    """The tool's stdout contract: ONE JSON line {verdict, est_heap_gb,
    budget_gb}; anything else -> unavailable (fail-open, never raises)."""
    mod = _load_init_module()
    ws = _android_ws(tmp_path)
    target = ws / "bins" / "wbtest.apk"
    payload = {"verdict": "jadx-ok", "est_heap_gb": 4.0, "budget_gb": 6.1}

    class _R:
        returncode = 0
        stdout = json.dumps(payload) + "\n"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _R())
    assert mod._run_mem_gate_cli(ws, target) == payload

    class _Bad:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Bad())
    rec = mod._run_mem_gate_cli(ws, target)
    assert rec["verdict"] == "unavailable" and "boom" in rec["reason"], rec


def test_init_run_wires_the_mem_gate_record():
    """Wiring pin: a helper nobody calls would pass every unit test above."""
    mod = _load_init_module()
    assert "record_mem_gate_verdict(" in inspect.getsource(mod.initialize)


def test_env_render_section_surfaces_the_recorded_verdict(tmp_path):
    ws = _android_ws(tmp_path)
    env_manifest.record_mem_gate(ws, "smali-only", est_heap_gb=4.0,
                                 budget_gb=2.6)
    section = env_manifest.render_section(env_manifest.resolve(ws))
    assert "smali-only" in section, section
    assert "mem" in section.lower(), section


def test_env_render_section_names_the_unknown_verdict_honestly(tmp_path):
    """Absent fact -> honest unknown + the exact command (never invented)."""
    ws = _android_ws(tmp_path)
    section = env_manifest.render_section(env_manifest.resolve(ws))
    assert "apk_mem_gate" in section, section
    assert "unknown" in section.lower(), section


# =========================================================================
# B. JVM probe joins the android check set
# =========================================================================

def _stub_probe_surface(monkeypatch, found=(), run_rc=0,
                        out="openjdk version \"17.0.11\" 2024-04-16",
                        err="openjdk version \"17.0.11\" 2024-04-16"):
    monkeypatch.setattr(tc, "_shutil_which",
                        lambda name: (f"/stub-bin/{name}"
                                      if name in found else None))
    monkeypatch.setattr(tc, "_run_cmd",
                        lambda args, timeout=10: (run_rc, out, err))


def _android_report(tmp_path) -> tc.ToolchainReport:
    report = tc.ToolchainReport(project_type="android")
    tc._check_android(report, tmp_path)
    return report


def test_android_report_carries_jvm_probe_item(monkeypatch, tmp_path):
    _stub_probe_surface(monkeypatch, found=("jadx", "java"))
    item = next((i for i in _android_report(tmp_path).items
                 if i.name == "jvm"), None)
    assert item is not None, "android report must carry a jvm probe item"
    assert item.status == tc.Status.PASS, item
    assert item.tier == tc.Tier.HARD, item
    assert item.probe == tc.ProbeTier.CAPABILITY, item
    assert "17" in item.detail, item


def test_jvm_probe_is_hard_when_jadx_present(monkeypatch, tmp_path):
    """jadx is a Java program: jadx without a JVM is a broken environment,
    so the miss is HARD (the item can then enter the exit-4 refusal set)."""
    _stub_probe_surface(monkeypatch, found=("jadx",))
    item = next((i for i in _android_report(tmp_path).items
                 if i.name == "jvm"), None)
    assert item is not None and item.status == tc.Status.FAIL, item
    assert item.tier == tc.Tier.HARD, item


def test_jvm_probe_is_warn_without_jadx(monkeypatch, tmp_path):
    """No jadx -> nothing needs the JVM: a WARN, never a HARD refusal."""
    _stub_probe_surface(monkeypatch, found=())
    item = next((i for i in _android_report(tmp_path).items
                 if i.name == "jvm"), None)
    assert item is not None and item.tier == tc.Tier.WARN, item
    assert item.status == tc.Status.WARN, item


def test_jvm_probe_fails_on_nonzero_java(monkeypatch, tmp_path):
    _stub_probe_surface(monkeypatch, found=("jadx", "java"), run_rc=1,
                        out="", err="Error: could not open JVM")
    item = next((i for i in _android_report(tmp_path).items
                 if i.name == "jvm"), None)
    assert item is not None and item.status == tc.Status.FAIL, item


def test_jvm_joins_the_android_check_set():
    assert "jvm" in tc.CHECK_SETS["android"]
    assert "jvm" not in tc.CHECK_SETS["windows"]
    # the issue 477 coverage declaration must classify the new item
    import toolchain_install as ti
    assert ("jvm" in ti.INSTALL_PLANS) or ("jvm" in ti.NOT_AUTO_INSTALLABLE)


# =========================================================================
# C. evidence-class gate on →PROVEN
# =========================================================================

REG = (
    "claims:\n"
    "  - id: C-001\n"
    "    status: {s}\n"
    "    statement: \"{stmt}\"\n"
)

ALGO_STMT = "Recover the AES key schedule expansion used by the crypto class"
PLAIN_STMT = "Sample package name and version strings"

FACT = """---
id: {fid}
type: fact
schema_rev: 2
title: "{title}"
status: PROVEN
verify_status: passes
created: 2026-09-10
last_reviewed: 2026-09-10
source: static-decompile
confidence: high
claim_id: C-001
boundary_type: observation
promotion_gate: "runtime capture of the same values"
provenance:
  - {{role: sample_raw, path: bins/x.apk, content_sha256: "{sha}", credibility: A1}}
claim: "{title}"
reproduce: "unzip -p bins/x.apk classes.dex | grep -a AES"
expected: "AES"
verified: pending
{extra}---
{body}
"""

SHA = "a" * 64


def _mk_ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    return ws


def _verify(ws, claim="C-001"):
    (ws / "runs" / f"2026-09-10-verify-{claim}.md").write_text(
        f"---\nclaim_id: {claim}\n---\n\n## Overall verdict\npasses\n",
        encoding="utf-8")


def _redteam(ws, claim="C-001"):
    (ws / "runs" / f"verify-redteam-{claim}.md").write_text(
        f"---\ntarget: {claim}\n---\n\nRED-TEAM VERDICT: CONFIRMED\n"
        f"claim: {claim}\n\nverifier-identity: rt-worker-1", encoding="utf-8")


def _fact(ws, fid="F001-aes", evidence_class=None, title="AES key schedule"):
    extra = (f"evidence_class: {evidence_class}\n" if evidence_class
             else "")
    (ws / "facts" / f"{fid}.md").write_text(
        FACT.format(fid=fid, title=title, sha=SHA, extra=extra,
                    body="unzip + grep string fact\n"), encoding="utf-8")


def _reg(status="PROVEN", stmt=ALGO_STMT) -> str:
    return REG.format(s=status, stmt=stmt)


OLD = _reg("OPEN")


def test_algorithm_claim_triage_only_evidence_is_blocked(tmp_path):
    """The issue 215 pathology: string facts alone could mint PROVEN on an
    algorithm-recovery claim."""
    ws = _mk_ws(tmp_path)
    _verify(ws)
    _redteam(ws)
    _fact(ws, evidence_class="triage")

    res = rpg.check_register_transitions(ws, _reg(), OLD)

    assert res["ok"] is False, res
    assert any("evidence-class" in v for v in res["violations"]), \
        res["violations"]


def test_algorithm_claim_without_evidence_class_is_blocked(tmp_path):
    """Fail-closed default: an UNDECLARED class is not a claim of strength
    (the `source: static-decompile` masquerade is exactly the issue 215 blind
    spot — the triage fact above declares that same source enum)."""
    ws = _mk_ws(tmp_path)
    _verify(ws)
    _redteam(ws)
    _fact(ws, evidence_class=None)

    res = rpg.check_register_transitions(ws, _reg(), OLD)

    assert res["ok"] is False, res
    assert any("evidence-class" in v for v in res["violations"]), \
        res["violations"]


def test_algorithm_claim_decompile_evidence_allows(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify(ws)
    _redteam(ws)
    _fact(ws, evidence_class="decompile")

    res = rpg.check_register_transitions(ws, _reg(), OLD)

    assert res["ok"] is True, res["violations"]


def test_non_algorithm_claim_is_not_gated_by_evidence_class(tmp_path):
    """Scope keywords identify algorithm-recovery claims only; ordinary
    claims keep the issue 819 gate untouched."""
    ws = _mk_ws(tmp_path)
    _verify(ws)
    _redteam(ws)
    _fact(ws, evidence_class="triage")

    res = rpg.check_register_transitions(ws, _reg(stmt=PLAIN_STMT), OLD)

    assert res["ok"] is True, res["violations"]


def test_algorithm_claim_without_facts_keeps_the_819_gate(tmp_path):
    """Documented boundary: with no fact file there is no fact-frontmatter
    evidence class to read — the issue 819 verify/redteam gate governs."""
    ws = _mk_ws(tmp_path)
    _verify(ws)
    _redteam(ws)

    res = rpg.check_register_transitions(ws, _reg(), OLD)

    assert res["ok"] is True, res["violations"]


def test_evidence_class_scope_keywords_cover_the_four_issue_classes():
    """The KEEP list is data, not prose: one keyword per issue class."""
    from register_proven_gate import ALGO_SCOPE_KEYWORDS
    joined = " ".join(ALGO_SCOPE_KEYWORDS).lower()
    for token in ("key_schedule", "crypto_constant", "state_machine",
                  "algorithm_verify"):
        assert token in joined, (token, ALGO_SCOPE_KEYWORDS)


def test_819_no_evidence_still_blocks_algorithm_claim(tmp_path):
    """Regression pin: the evidence-class predicate is ADDITIVE — the issue 819
    predicates still fire first-class on the same claim."""
    ws = _mk_ws(tmp_path)
    _fact(ws, evidence_class="decompile")
    res = rpg.check_register_transitions(ws, _reg(), OLD)
    assert res["ok"] is False, res
    assert any("verify-note" in v for v in res["violations"]), \
        res["violations"]


# =========================================================================
# C2. lint_facts / template: the evidence_class extension field
# =========================================================================

def _lint_ws(tmp_path, evidence_class="triage") -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    _fact(ws, evidence_class=evidence_class)
    return ws


def _lint_issues(ws: Path):
    fact = next((ws / "facts").glob("*.md"))
    fm = lint_facts._load_fact(fact)
    return lint_facts.lint_fact(fm.get("id", "F001-aes"), fm, set(), "")


def test_lint_facts_accepts_evidence_class(tmp_path):
    codes = [c for _sev, c, _m in _lint_issues(_lint_ws(tmp_path))]
    assert "BAD_EVIDENCE_CLASS" not in codes, codes
    assert "UNKNOWN_KEY" not in codes, codes


def test_lint_facts_rejects_unknown_evidence_class(tmp_path):
    codes = [c for _sev, c, _m in
             _lint_issues(_lint_ws(tmp_path, evidence_class="totally-made-up"))]
    assert "BAD_EVIDENCE_CLASS" in codes, codes


def test_fact_template_documents_the_extension_field():
    text = (ROOT / "templates" / "fact-frontmatter.md").read_text("utf-8")
    assert "evidence_class" in text, "the extension layer must document it"
    for value in ("triage", "decompile"):
        assert value in text, value


# =========================================================================
# D. registry / index contracts
# =========================================================================

def test_route_jvm_token_reads_the_probe_state():
    assert rc._eval_token("jvm", {"tool_probes": {"jvm": True}}) == ("ok", None)
    verdict, reason = rc._eval_token("jvm", {"tool_probes": {"jvm": False}})
    assert verdict == "blocked" and reason, (verdict, reason)
    verdict, _reason = rc._eval_token("jvm", {"tool_probes": {}})
    assert verdict == "unverified", verdict


def test_jadx_provider_requires_jvm_in_registry():
    data = yaml.safe_load((ROOT / "tools" / "_INDEX.yaml").read_text("utf-8"))
    entry = next(e for e in data["tools"] if e.get("name") == "jadx-decompile")
    assert "jvm" in entry["requires"], entry["requires"]
    assert set(entry["requires"]) >= {"dex", "mem_budget_ok", "jadx_bin", "jvm"}
    sys.path.insert(0, str(ROOT / "tools"))
    import validate_index as vi
    assert "jvm" in vi.PROVIDER_TOKENS, vi.PROVIDER_TOKENS
    assert [e for e in vi.validate_index(data)
            if "jadx-decompile" in e] == [], vi.validate_index(data)


def test_dexdc_index_entries_carry_the_jvm_probe_caveat():
    """The conflation source: 'no JVM' is a dexdc PROPERTY, not an
    environment fact — the wording must say so and point at the probe."""
    text = (ROOT / "tools" / "_index-static.md").read_text("utf-8")
    for chunk in text.split("### dexdc-decompile")[1:]:
        assert "requires no JVM" in chunk, chunk[:200]
        assert "probe" in chunk.lower(), chunk[:400]
    assert "no JVM - immune to jadx heap thrash" not in text


def test_jadx_index_entry_lists_the_jvm_requirement():
    text = (ROOT / "tools" / "_index-static.md").read_text("utf-8")
    line = next(l for l in text.splitlines()
                if l.startswith("- **provider**: `jadx`"))
    assert "jvm" in line, line


def test_apk_mem_gate_behavior_unchanged():
    """issue 215 wires and enforces — the 12x formula itself is untouched."""
    from apk_mem_gate import DEFAULTS, _verdict
    assert DEFAULTS["apk_mem_dex_factor"] == 50.0
    assert DEFAULTS["apk_mem_floor_gb"] == 4.0
    assert DEFAULTS["apk_mem_budget_ratio"] == 0.65
    # refuse is an EXPECTED outcome (jar target, no smali fallback)
    assert _verdict(4.0, 10.0, ".jar", None)[0] == "refuse"
    assert _verdict(4.0, 10.0, ".apk", None)[0] == "jadx-ok"
    assert _verdict(4.0, 2.6, ".apk", None)[0] == "smali-only"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
