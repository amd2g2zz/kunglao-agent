#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_subagent_injection.py — ghidra-light field-incident replay (#493).

Replays the #462 evidence-1 incident (a ghidra-light worker hand-wrote
scripts/ghidra/DecompileFuncs.java + scripts/decompile_funcs_headless.py
while `ls scripts/re` already showed 25+ shelf tools) as BEHAVIOR
EQUIVALENCE CLASSES, not literal fitting (plan risk: 重演测试过度拟合 —
detection keys on classes, never on the incident's exact spelling):

  ① self-invention, no review: new scripts/ files staged with NO
     .subagent-review/*.json -> Gate 5 HARD_PAUSE (rc=2) naming the
     touched paths. Dispatch-layer companion: the dispatch prompt's
     intended tool family (ghidra/decompile) is cross-asserted against
     the #495 validated_capability card at the Agent-tool face (#496
     guard, real subprocess run).
  ② legal review: tools_used cites real tool references (workspace
     scripts/re/ namespace, tools/_INDEX.yaml registered names and
     #anchor paths, real files under tools/ / references/) -> rc=0.
  ③ complete review + self-invented citation: all 5 fields valid,
     verified_by independent, but tools_used cites a path that resolves
     nowhere -> STILL HARD_PAUSE (#493 increment: resolvability check).
  ④ SUFFICIENT negative (independence): the scenarios cannot mask each
     other — a valid sibling review does not hide an unresolvable
     citation, and each scenario fires without the others' fixtures.

Companion: tests/test_subagent_review.py pins the schema boundary
(missing fields / self-stamp / empty tools_used); THIS file pins the
real injection scenarios from the field report.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "devkit"))

import subagent_review as sr  # noqa: E402


# The incident's artifacts (#462 evidence 1), restaged as the behavior
# class "new domain files with no review". The exact names are kept as
# the historical anchor; detection does NOT key on them (see the
# equivalence-class variant below).
GHIDRA_LIGHT_INCIDENT = [
    "scripts/ghidra/DecompileFuncs.java",
    "scripts/decompile_funcs_headless.py",
]

# Legal tools_used citations, one per resolution class (issue #493 What,
# scenario 2): workspace namespace / index anchor / registered bare
# name / real shelf file / references whitelist domain.
LEGAL_TOOL_CITATIONS = [
    "scripts/re/pseudo_c_extractor.py",
    "tools/_INDEX.yaml#ghidra-decompile-functions",
    "ghidra-decompile-functions",
    "tools/ghidra/run_ghidra_postscript.py",
    "references/_INDEX.md",
]

# Unresolvable citations, one per self-invention shape (issue #493 What,
# scenario 3): the incident paths verbatim + fresh spellings + an
# unregistered bare name + traversal.
SELF_INVENTED_CITATIONS = [
    "scripts/decompile_funcs_headless.py",
    "scripts/ghidra/DecompileFuncs.java",
    "scripts/reverse_tool_v2.py",
    "decompile-funcs-headless",
    "scripts/../tools/_INDEX.yaml",
    "tools/_INDEX.yaml#no-such-fake-anchor-xyz",
]

_MINIMAL_INDEX = """tools:
  - name: ghidra-decompile-functions
    category: ghidra
  - name: ghidra-recon
    category: ghidra
"""


def _incident_review(tools_used: list[str]) -> dict:
    """A 5-field-complete, independently-verified review — the only
    variable is the tools_used citation."""
    return {
        "agent": "ghidra-light",
        "plan": "Decompile c-409 via the shelf; no new scripts",
        "status_sync": "runs/worker-status-ghidra-light-c409.md",
        "tools_used": tools_used,
        "verified_by": "verifier-subagent-2026-08-20-c409",
    }


def _write_review(tmp_path: Path, name: str, payload: dict) -> Path:
    rev = tmp_path / ".subagent-review"
    rev.mkdir(exist_ok=True)
    p = rev / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _assets_for(citation: str) -> dict[str, str]:
    """Real-file assets a citation must resolve against in an isolated
    repo. The workspace scripts/re/ namespace needs none — it is
    deployed per engagement and never exists in the skill repo."""
    assets: dict[str, str] = {}
    bare = "/" not in citation
    if bare or citation.startswith("tools/_INDEX.yaml"):
        assets["tools/_INDEX.yaml"] = _MINIMAL_INDEX
    if not bare and not citation.startswith("scripts/re/"):
        path = citation.split("#", 1)[0]
        assets.setdefault(path, "# shelf asset\n")
    return assets


class _IncidentRepo:
    """Isolated tmp git repo replaying the field shape: staged scripts/
    files + optional .subagent-review/*.json + optional real assets the
    tools_used citations resolve against. Monkeypatches sr.REPO_ROOT for
    the duration of the check (same pattern as test_subagent_review)."""

    def __init__(self, tmp_path: Path, files: list[str],
                 reviews: dict[str, dict] | None = None,
                 assets: dict[str, str] | None = None) -> None:
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "--initial-branch=main"],
                       cwd=self.repo, check=True)
        subprocess.run(["git", "-C", str(self.repo), "config",
                        "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config",
                        "user.name", "T"], check=True)
        for rel, text in (assets or {}).items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        for f in files:
            p = self.repo / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# replayed incident artifact\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        for name, payload in (reviews or {}).items():
            _write_review(self.repo, name, payload)
            subprocess.run(["git", "-C", str(self.repo), "add",
                            ".subagent-review"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        self._orig_root = sr.REPO_ROOT

    def run(self) -> int:
        sr.REPO_ROOT = self.repo
        try:
            return sr.check()
        finally:
            sr.REPO_ROOT = self._orig_root


# ---------- ① self-invention, no review ---------------------------------

class TestScenario1SelfInventionNoReview:
    def test_incident_replay_hard_pauses(self, tmp_path: Path, capsys) -> None:
        """The #462 evidence-1 shape verbatim: the two incident files
        staged, no review anywhere -> HARD_PAUSE with a SPECIFIC error
        that names what was touched."""
        iso = _IncidentRepo(tmp_path, GHIDRA_LIGHT_INCIDENT, reviews=None)
        rc = iso.run()
        assert rc == 2, "field incident replay must HARD_PAUSE"
        out = capsys.readouterr().out
        assert "HARD_PAUSE" in out
        for f in GHIDRA_LIGHT_INCIDENT:
            assert f in out, f"specific error must name the touched path {f}"

    def test_equivalence_class_new_names_same_pause(self, tmp_path: Path) -> None:
        """Behavior class, not literal fitting: ANY freshly invented
        scripts/ file without a review pauses — a differently-worded
        repeat of the incident is still caught."""
        iso = _IncidentRepo(tmp_path, ["scripts/my_string_scanner.py"],
                            reviews=None)
        assert iso.run() == 2


# ---------- ① dispatch-layer companion (#496 capability cross-check) ----

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _activate_hooks(ws: Path) -> None:
    """Make dispatch_gate ACTIVE on this workspace (v1.9.7 TTL)."""
    (ws / ".hook_state.json").write_text(json.dumps({
        "active_hooks": ["dispatch_gate"],
        "paused_hooks": [],
        "expires_at": "2099-12-31T23:59:59Z",
    }), encoding="utf-8")


def _dispatch_ws(root: Path, validated_capability: str) -> Path:
    """ghidra-family replay of the trajectory-1 card shape (the
    test_decision_teeth _capability_ws fixture with the family swapped):
    C-1 failed once, the #495 analysis is COMPLETE and records
    validated_capability=<family text>."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write_yaml(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN", "promotion_attempts": 1,
         "statement": "decompile the config-parsing routine"}]})
    _write_yaml(ws / "claim_deps.yaml",
                {"depends_on": {}, "competitor_groups": {}})
    _write_yaml(ws / "task_spec.yaml", {"primary_questions": []})
    _write_yaml(ws / "analyses" / "failure-C-1.yaml", {
        "claim": "C-1", "covers_attempt": 1,
        "method_assumption": "the shelf decompiler covers the target",
        "assumption_validity": "justified",
        "next_method": "keep the validated family",
        "next_method_source": "reference-hit",
        "validated_capability": validated_capability,
        "identified_obstacle": "none",
    })
    _activate_hooks(ws)
    return ws


def _run_dispatch_gate(root: Path, ws: Path, prompt: str
                       ) -> subprocess.CompletedProcess:
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


class TestScenario1DispatchCapabilityCrossCheck:
    """The dispatch-layer companion of ①: the worker's dispatch prompt
    declares its intended tool family; the #496 capability-card guard
    cross-asserts it against the validated card at the Agent-tool face.
    Proves the cross-check holds for the ghidra/decompile family, not
    just the frida/xposed trajectory it was built on."""

    def test_ghidra_family_in_hand_passes(self, tmp_path: Path) -> None:
        ws = _dispatch_ws(
            tmp_path,
            "ghidra headless decompile reaches the config-parsing routine")
        r = _run_dispatch_gate(
            tmp_path, ws,
            "[T1 tools=ghidra-decompile-functions] claim C-1 "
            "decompile the string routine")
        assert r.returncode == 0, (
            f"validated ghidra card + ghidra dispatch is family-in-hand; "
            f"rc={r.returncode}, stderr={r.stderr!r}, stdout={r.stdout!r}")

    def test_switch_off_validated_family_rejected(self, tmp_path: Path) -> None:
        ws = _dispatch_ws(
            tmp_path,
            "x64dbg conditional trace reaches the anti-debug check")
        r = _run_dispatch_gate(
            tmp_path, ws,
            "[T1 tools=ghidra-decompile-functions] claim C-1 "
            "decompile the string routine")
        assert r.returncode == 2, (
            f"validated x64dbg card + ghidra dispatch is an undisproved "
            f"family switch; rc={r.returncode}, stderr={r.stderr!r}")
        assert "REJECT capability" in r.stderr, f"stderr={r.stderr!r}"
        assert "capability-disproof" in r.stdout, (
            f"fix guidance must teach the disproof marker; "
            f"stdout={r.stdout!r}")

    def test_switch_with_disproof_passes(self, tmp_path: Path) -> None:
        ws = _dispatch_ws(
            tmp_path,
            "x64dbg conditional trace reaches the anti-debug check")
        prompt = (
            "[T1 tools=ghidra-decompile-functions] claim C-1 "
            "decompile the string routine\n"
            "capability-disproof: x64dbg (trace diverged at the unpacking "
            "stub — see analyses/failure-C-1.yaml)")
        r = _run_dispatch_gate(tmp_path, ws, prompt)
        assert r.returncode == 0, (
            f"showing the card failed must pass; stderr={r.stderr!r}")


# ---------- ② legal review passes ----------------------------------------

class TestScenario2LegalReviewPasses:
    @pytest.mark.parametrize("citation", LEGAL_TOOL_CITATIONS)
    def test_legal_citation_commits(self, tmp_path: Path, citation: str) -> None:
        iso = _IncidentRepo(
            tmp_path, ["scripts/kunglao.py"],
            reviews={"ok.json": _incident_review([citation])},
            assets=_assets_for(citation))
        rc = iso.run()
        assert rc == 0, (
            f"legal tools_used citation {citation!r} must pass Gate 5")


# ---------- ③ complete review + self-invented citation ------------------

class TestScenario3CompleteReviewSelfInventedCitation:
    @pytest.mark.parametrize("citation", SELF_INVENTED_CITATIONS)
    def test_full_fields_still_hard_pauses(self, tmp_path: Path, capsys,
                                           citation: str) -> None:
        """Issue #493 What, scenario 3: status_sync/verified_by all
        filled, but tools_used cites a self-invented tool -> STILL
        HARD_PAUSE (the resolvability increment)."""
        iso = _IncidentRepo(
            tmp_path, ["scripts/kunglao.py"],
            reviews={"r.json": _incident_review([citation])})
        rc = iso.run()
        assert rc == 2, (
            f"unresolvable citation {citation!r} must HARD_PAUSE even "
            f"with a complete review")
        out = capsys.readouterr().out
        assert "HARD_PAUSE" in out
        assert "tools_used" in out, "error must name the failing field"
        assert citation in out, "error must name the unresolvable citation"


class TestResolvabilityUnit:
    """Unit-level pins of the resolution classes (design D2)."""

    def _shelf(self, tmp_path: Path) -> Path:
        (tmp_path / "tools" / "ghidra").mkdir(parents=True)
        (tmp_path / "tools" / "_INDEX.yaml").write_text(
            _MINIMAL_INDEX, encoding="utf-8")
        (tmp_path / "tools" / "ghidra" / "x.py").write_text("# x\n",
                                                            encoding="utf-8")
        (tmp_path / "references").mkdir()
        (tmp_path / "references" / "_INDEX.md").write_text("# r\n",
                                                           encoding="utf-8")
        return tmp_path

    def test_resolver_accepts_legal_classes(self, tmp_path: Path) -> None:
        root = self._shelf(tmp_path)
        ok_cases = [
            "scripts/re/pseudo_c_extractor.py",   # workspace namespace
            "scripts/re/deep/nested/tool.py",     # namespace, nested
            "ghidra-decompile-functions",         # registered bare name
            "tools/_INDEX.yaml#ghidra-recon",     # real file + anchor
            "tools/ghidra/x.py",                  # real shelf file
            "references/_INDEX.md",               # whitelist domain
        ]
        for c in ok_cases:
            assert sr._tool_resolves(c, root), c

    def test_resolver_rejects_self_invention_shapes(self, tmp_path: Path) -> None:
        root = self._shelf(tmp_path)
        bad_cases = [
            "",                          # nothing
            "#ghidra-recon",             # anchor-only names nothing
            "ghidra-recon-v9",           # unregistered bare name
            "tools/ghidra/missing.py",   # nonexistent under a root
            "docs/_INDEX.md",            # outside the whitelist roots
            "scripts/../../etc/passwd",  # traversal is not resolution
            "tools//x.py",               # empty segment
            "tools/_INDEX.yaml/",        # trailing slash
            "/etc/passwd",               # absolute path
        ]
        for c in bad_cases:
            assert not sr._tool_resolves(c, root), c
        assert not sr._tool_resolves(123, root), "non-string citation"

    def test_traversal_inside_namespace_prefix_rejected(
            self, tmp_path: Path) -> None:
        """F1 (#493 review): traversal rejection must precede the
        scripts/re/ prefix trust — the raw string carries the trusted
        prefix, but a `..` segment is never resolution."""
        root = self._shelf(tmp_path)
        assert not sr._tool_resolves("scripts/re/../../etc/passwd", root)

    def test_bare_namespace_prefix_cites_nothing(self, tmp_path: Path) -> None:
        """F2 (#493 review): the exact bare prefix string references
        nothing under it and must not resolve."""
        root = self._shelf(tmp_path)
        assert not sr._tool_resolves("scripts/re/", root)

    def test_index_anchor_must_name_a_registered_tool(
            self, tmp_path: Path) -> None:
        """#493 LOW patch (FAULT-INJECT bypass bonus): the #anchor on the
        real tools/_INDEX.yaml base is not decoration — only a REGISTERED
        name resolves; a plausible-sounding fabricated anchor does not
        (it cannot elevate an unresolvable base, but it must not ride a
        resolvable one either)."""
        root = self._shelf(tmp_path)
        assert not sr._tool_resolves(
            "tools/_INDEX.yaml#no-such-fake-anchor-xyz", root)
        assert sr._tool_resolves(
            "tools/_INDEX.yaml#ghidra-recon", root), \
            "a REGISTERED anchor on the real index file must resolve"

    def test_index_anchor_fails_closed_without_index(
            self, tmp_path: Path) -> None:
        """#493 LOW patch + M4 pin widening (FAULT-INJECT single-kill
        note): with the index absent OR present-but-yielding-no-names,
        an anchored index citation fails CLOSED — the empty registered-
        name set resolves nothing, even when the base file itself
        exists on disk."""
        no_index = tmp_path / "no-index"
        (no_index / "tools").mkdir(parents=True)
        assert not sr._tool_resolves("tools/_INDEX.yaml#ghidra-recon",
                                     no_index)
        empty_index = tmp_path / "empty-index"
        (empty_index / "tools").mkdir(parents=True)
        (empty_index / "tools" / "_INDEX.yaml").write_text("",
                                                           encoding="utf-8")
        assert not sr._tool_resolves("tools/_INDEX.yaml#ghidra-recon",
                                     empty_index)

    def test_unresolvable_citation_fails_validation(self, tmp_path: Path) -> None:
        p = _write_review(tmp_path, "bad.json",
                          _incident_review(["scripts/decompile_funcs_headless.py"]))
        ok, msg = sr._validate_one(p)
        assert ok is False
        assert "unresolvable" in msg.lower()

    def test_workspace_namespace_citation_passes_validation(
            self, tmp_path: Path) -> None:
        p = _write_review(tmp_path, "ns.json",
                          _incident_review(["scripts/re/anything_at_all.py"]))
        ok, msg = sr._validate_one(p)
        assert ok is True, msg

    def test_tools_used_not_array_fails_closed(self, tmp_path: Path) -> None:
        review = _incident_review(["scripts/re/x.py"])
        review["tools_used"] = "scripts/re/x.py"  # schema says array
        p = _write_review(tmp_path, "str.json", review)
        ok, msg = sr._validate_one(p)
        assert ok is False
        assert "array" in msg.lower()


# ---------- ④ SUFFICIENT negative: scenario independence ----------------

class TestExtNameResolution:
    """#476 compatibility face: the ext catalog (tools/_INDEX.ext.yaml,
    describe-only) contributes logical names to the bare-name resolution
    set — a review citing an ext name cites a REAL repo capability, not a
    self-invention. Broken ext file drops only ext names (fail-closed
    toward strict, internal names unaffected — design D9)."""

    def _with_ext(self, tmp_path: Path) -> Path:
        root = self._shelf(tmp_path)
        (root / "tools" / "_INDEX.ext.yaml").write_text(
            "ext:\n"
            "  - name: convergence_check\n"
            "    capability: converge:check\n"
            "    source: scripts/convergence_check.py\n"
            "    usage: python scripts/convergence_check.py\n"
            "    description: fixture\n",
            encoding="utf-8")
        return root

    def _shelf(self, tmp_path: Path) -> Path:
        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "_INDEX.yaml").write_text(
            _MINIMAL_INDEX, encoding="utf-8")
        return tmp_path

    def test_ext_bare_name_resolves(self, tmp_path: Path) -> None:
        assert sr._tool_resolves("convergence_check", self._with_ext(tmp_path))

    def test_ext_names_do_not_shadow_internal(self, tmp_path: Path) -> None:
        root = self._with_ext(tmp_path)
        names = sr._index_tool_names(root)
        assert names == {"ghidra-recon", "ghidra-decompile-functions",
                         "convergence_check"}, names

    def test_broken_ext_yaml_keeps_internal_names(self, tmp_path: Path) -> None:
        root = self._with_ext(tmp_path)
        (root / "tools" / "_INDEX.ext.yaml").write_text(
            "ext: [ :{broken", encoding="utf-8")
        assert sr._index_tool_names(root) == \
            {"ghidra-recon", "ghidra-decompile-functions"}

    def test_real_repo_ext_citations_resolve(self) -> None:
        ext = REPO_ROOT / "tools" / "_INDEX.ext.yaml"
        assert ext.is_file(), "ext index missing (#476)"
        data = yaml.safe_load(ext.read_text(encoding="utf-8"))
        names = [e["name"] for e in data.get("ext", [])]
        assert names, "ext index is empty"
        bad = [n for n in names if not sr._tool_resolves(n, REPO_ROOT)]
        assert not bad, f"ext names failing resolution: {bad[:5]}"


class TestScenarioIndependence:
    def test_valid_sibling_does_not_mask_unresolvable(self, tmp_path: Path) -> None:
        """A valid review file next to a bad one cannot mask it — the
        gate validates EVERY review file (scenario 2 passing must not
        hide scenario 3)."""
        iso = _IncidentRepo(
            tmp_path, ["scripts/kunglao.py"],
            reviews={
                "ok.json": _incident_review(["scripts/re/pseudo_c_extractor.py"]),
                "invented.json": _incident_review(
                    ["scripts/decompile_funcs_headless.py"]),
            })
        assert iso.run() == 2

    def test_unresolvable_fires_without_incident_files(self, tmp_path: Path) -> None:
        """Scenario 3 is independent of scenario 1's file set: an
        ordinary scripts/ change + a bad citation still pauses."""
        iso = _IncidentRepo(
            tmp_path, ["scripts/kunglao_status.py"],
            reviews={"r.json": _incident_review(
                ["scripts/decompile_funcs_headless.py"])})
        assert iso.run() == 2

    def test_legal_review_passes_even_with_incident_files_staged(
            self, tmp_path: Path) -> None:
        """Scenario 2 is independent of scenario 1: Gate 5 judges the
        review contract, not staged file names (name-sniffing would be
        literal fitting). Incident-named files + a LEGAL review pass —
        an invented FILE behind an honest review is the reviewer's
        question (verified_by chain), not Gate 5's."""
        iso = _IncidentRepo(
            tmp_path, GHIDRA_LIGHT_INCIDENT,
            reviews={"ok.json": _incident_review(
                ["scripts/re/pseudo_c_extractor.py"])})
        assert iso.run() == 0


# ---------- real-shelf pins (against the actual checkout) ----------------

class TestRealShelfResolvability:
    """Pins the REAL shelf so legal reviews cannot silently brick: the
    citations used by the schema doc and the tracked review JSON must
    resolve against the actual checkout, and the incident paths must
    NOT (the real java lives at tools/ghidra/DecompileFunctions.java —
    a different spelling, i.e. a different behavior class)."""

    @pytest.mark.parametrize("citation", [
        "scripts/check_global_rule_subset.py",
        "scripts/references_recall.py",
        "scripts/kunglao.py",
        "tools/_INDEX.yaml#ghidra-decompile-functions",
        "tools/_INDEX.md",
        "references/_INDEX.md",
        "ghidra-recon",
        "ghidra-decompile-functions",
        "ghidra-vtable-struct",
        "ghidra-evidence-annotations",
        "ghidra-scan-pointer",
    ])
    def test_real_citation_resolves(self, citation: str) -> None:
        assert sr._tool_resolves(citation, REPO_ROOT), citation

    @pytest.mark.parametrize("citation", [
        "scripts/decompile_funcs_headless.py",
        "scripts/ghidra/DecompileFuncs.java",
    ])
    def test_incident_paths_do_not_resolve(self, citation: str) -> None:
        assert not sr._tool_resolves(citation, REPO_ROOT), citation

    def test_tracked_gate5_review_citations_resolve(self) -> None:
        """The committed .subagent-review/2026-08-19-gate5.json must stay
        valid under the tightened rule (its three citations are real)."""
        p = REPO_ROOT / ".subagent-review" / "2026-08-19-gate5.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        bad = [t for t in data["tools_used"]
               if not sr._tool_resolves(t, REPO_ROOT)]
        assert not bad, f"tracked review broke: {bad}"
