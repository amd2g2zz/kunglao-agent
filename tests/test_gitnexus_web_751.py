# -*- coding: utf-8 -*-
"""tests/test_gitnexus_web_751.py — issue #751 web JS semantic index layer.

Pins the web-domain extension of the #692 gitnexus layer:

- T1 Rule B vocabulary: `js:semantic-query` + `js:call-graph` join
  _CAPABILITY_TAGS; the shipped index validates.
- T2 registry entry: one gitnexus-query provider covers android + js
  domains (annotation schema per #692); wakaru/webcrack entries name the
  evidence unpack_out hand-off.
- T3 quickref: the layered-peeling section carries the post-recovery index
  step (`gitnexus analyze <out_dir>`) + signature-trace query posture;
  references/_INDEX.yaml pins stay accurate (re-pin contract).
- T4 routing: resolve_capability resolves js tags to [gitnexus-query];
  capability_matches keeps its prefix semantics for js queries; the
  specialist trigger CONTRACT is pinned via a fixture table (#760 owns the
  agent file — design D2): fixed claim -> gitnexus-query under the fixture,
  no mis-route under today's real table.
- T5 demo: tests/fixtures/web751/bundle.min.js runs under node, the demo
  script self-checks offline and degrades with STRUCTURED skip reasons.

RED phase expectations before implementation:
  _CAPABILITY_TAGS lacks the js pair / _INDEX.yaml unannotated /
  quickref has no index step / fixture routing unasserted.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tools"))

import yaml

FIX = REPO / "tests" / "fixtures" / "web751"
SPECIALIST_FIXTURE = FIX / "specialists" / "gitnexus-query.md"
DEMO_SCRIPT = REPO / "tools" / "static" / "web_gitnexus_demo.py"

CLAIM = ("trace which function builds the signature string "
         "through the bundle")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_vi = _load("_validate_index_751", REPO / "tools" / "validate_index.py")
_rc = _load("_route_capability_751", REPO / "scripts" / "route_capability.py")


def _index() -> list[dict]:
    data = yaml.safe_load((REPO / "tools" / "_INDEX.yaml")
                          .read_text(encoding="utf-8"))
    return data["tools"]


def _by_name(name: str) -> dict:
    return next(t for t in _index() if t.get("name") == name)


# ---------- T1: closed vocabulary ----------

class TestCapabilityVocabulary:
    def test_js_semantic_query_tag_in_vocabulary(self):
        assert "js:semantic-query" in _vi._CAPABILITY_TAGS

    def test_js_call_graph_tag_in_vocabulary(self):
        assert "js:call-graph" in _vi._CAPABILITY_TAGS

    def test_shipped_index_still_validates(self):
        errors = _vi.validate_index(yaml.safe_load(
            (REPO / "tools" / "_INDEX.yaml").read_text(encoding="utf-8")))
        assert errors == []

    def test_unknown_js_tag_still_rejected(self):
        """Vocabulary stays closed — an unknown js tag must fail."""
        data = yaml.safe_load((REPO / "tools" / "_INDEX.yaml")
                              .read_text(encoding="utf-8"))
        data["tools"] = [_by_name("gitnexus-query")]
        data["tools"][0]["produces"] = ["js:not-a-capability"]
        errors = _vi.validate_index(data)
        assert any("CAPABILITY_TAGS" in e for e in errors)


# ---------- T2: registry entry shape (#692 annotation schema) ----------

class TestRegistryEntry:
    @pytest.fixture(scope="class")
    def gitnexus(self) -> dict:
        return _by_name("gitnexus-query")

    def test_produces_carry_js_pair(self, gitnexus):
        produced = set(gitnexus["produces"])
        assert {"js:semantic-query", "js:call-graph"} <= produced

    def test_android_tags_survive(self, gitnexus):
        produced = set(gitnexus["produces"])
        assert {"android:semantic-query", "android:call-graph"} <= produced

    def test_requires_keeps_source_tree_and_index(self, gitnexus):
        assert set(gitnexus["requires"]) >= {"source_tree",
                                             "gitnexus_index"}

    def test_quality_maps_every_produced_tag(self, gitnexus):
        produced = set(gitnexus["produces"])
        quality = set(gitnexus["quality"])
        assert produced <= quality
        assert all(gitnexus["quality"][t] in ("high", "mid", "floor")
                   for t in produced)

    def test_capability_member_of_produces(self, gitnexus):
        assert gitnexus["capability"] in gitnexus["produces"]

    def test_annotation_schema_contract_holds(self, gitnexus):
        """Whole-entry pass through the #692 validator."""
        data = {"tools": [dict(gitnexus)]}
        assert _vi.validate_index(data) == []

    def test_input_output_documents_js_source_tree_semantics(self, gitnexus):
        io_text = json.dumps(gitnexus.get("input_output", ""),
                             ensure_ascii=False) + \
            str(gitnexus.get("when_not", ""))
        assert "unpack_out" in io_text
        # wakaru/webcrack output dir satisfies source_tree on js targets
        low = io_text.lower()
        assert "wakaru" in low or "webcrack" in low

    @pytest.mark.parametrize("name", ["wakaru-unbundle",
                                      "webcrack-deobfuscate"])
    def test_recovery_entries_name_unpack_out_handoff(self, name):
        entry = _by_name(name)
        blob = json.dumps(entry.get("input_output", ""), ensure_ascii=False)
        assert "unpack_out" in blob, (
            f"{name} input_output must record the unpack_out registration")

    def test_single_gitnexus_provider(self):
        providers = [t.get("provider") for t in _index()
                     if t.get("provider") == "gitnexus"]
        assert len(providers) == 1


# ---------- T3: quickref index step + pin freshness ----------

QUICKREF = REPO / "references" / "re-library" / "web-re-quickref.md"


class TestQuickrefIndexStep:
    @pytest.fixture(scope="class")
    def quickref(self) -> str:
        return QUICKREF.read_text(encoding="utf-8")

    def test_analyze_step_present(self, quickref):
        assert "gitnexus analyze" in quickref

    def test_signature_trace_posture_present(self, quickref):
        text = quickref.lower()
        assert "signature" in text
        assert "request entry" in text or "entry point" in text

    def test_step_sits_between_peeling_and_parameters(self, quickref):
        """The index step lives inside the layered-peeling narrative: after
        the recovery tool mentions, before the next (crypto) section."""
        peel_start = quickref.find("## Obfuscation recognition")
        crypto_start = quickref.find("## Crypto-algorithm signatures")
        idx = quickref.find("gitnexus analyze")
        assert peel_start != -1 and crypto_start != -1 and idx != -1
        assert peel_start < idx < crypto_start
        section = quickref[peel_start:crypto_start]
        # step comes AFTER the recovery tools it builds on
        wakaru_at = section.find("wakaru")
        assert wakaru_at != -1 < section.find("gitnexus analyze")

    def test_quickref_sections_intact(self, quickref):
        for title in ("Hook & breakpoint quick reference",
                      "Signed-parameter location workflow",
                      "Obfuscation recognition and layered peeling",
                      "Crypto-algorithm signatures",
                      "Anti-patterns",
                      "Advanced topics"):
            assert f"## {title}" in quickref, title

    def test_quickref_english_only(self, quickref):
        cjk = [ch for ch in quickref if "一" <= ch <= "鿿"]
        assert not cjk, cjk[:5]

    def test_references_pins_fresh(self):
        """Gate 7(b) spirit: quickref edits ship with accurate pins."""
        sys.path.insert(0, str(REPO / "scripts"))
        import hashlib
        pins = yaml.safe_load((REPO / "references" / "_INDEX.yaml")
                              .read_text(encoding="utf-8"))["files"]
        rel = "references/re-library/web-re-quickref.md"
        want = pins[rel]
        got = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
        assert want == got


# ---------- T4: route linkage ----------

class TestRouteLinkage:
    def _state_with_web_index(self, tmp_path):
        """A workspace whose evidence shows an unpacked tree + valid marker."""
        ev = tmp_path / "evidence"
        ev.mkdir(parents=True)
        marker = {"source_root": str(tmp_path),
                  "indexed_at": "2026-08-26T00:00:00Z", "tools": 16}
        (ev / "gitnexus_index.json").write_text(json.dumps(marker),
                                                encoding="utf-8")
        src = ev / "unpack-out"
        src.mkdir()
        (src / "module.js").write_text("function buildSignature(){}\n",
                                       encoding="utf-8")
        return _rc.load_workspace_state(tmp_path)

    def test_select_providers_resolves_js_semantic_query(self, tmp_path):
        """#692 provider-selection face: js:semantic-query ranks the single
        gitnexus provider available once source_tree + marker exist."""
        state = self._state_with_web_index(tmp_path)
        result = _rc.select_providers("js:semantic-query", _index(), state)
        assert result["recommendation"] == "gitnexus-query"
        top = result["providers"][0]
        assert top["quality"] == "high" and top["status"] == "available"

    def test_select_providers_resolves_js_call_graph(self, tmp_path):
        state = self._state_with_web_index(tmp_path)
        result = _rc.select_providers("js:call-graph", _index(), state)
        assert result["recommendation"] == "gitnexus-query"

    def test_resolve_capability_documents_legacy_semantics(self):
        """The pre-#692 helper matches the singular capability FIELD only;
        js domain additions must therefore ride select_providers (#692).
        Pinned so nobody 'fixes' one side without noticing the other."""
        tools = [{"name": "gitnexus-query",
                  "capability": "android:semantic-query"}]
        assert _rc.resolve_capability("js:semantic-query", tools) == [
            "js:semantic-query"]

    def test_capability_matches_prefix_semantics(self):
        assert _rc.capability_matches("js:semantic-query", "js:")
        assert not _rc.capability_matches("js:semantic-query", "web:")

    def test_specialist_fixture_exists(self):
        assert SPECIALIST_FIXTURE.is_file()

    def test_fixture_table_routes_claim_to_gitnexus_query(self):
        table = _rc.load_specialist_table(SPECIALIST_FIXTURE.parent)
        name, rationale = _rc.recommend_agent_type({"language": "JavaScript"},
                                                   CLAIM, table)
        assert name == "gitnexus-query", rationale

    def test_real_table_does_not_misroute_today(self):
        # #760 landed agents/web-re-worker.md: a signature-tracing claim on a
        # web sample now routes to the web specialist (must_any 'signature')
        # — the exact hand-off #751 design D2 predicted. gitnexus-query stays
        # reachable via its own intent words (fixture test above) and is the
        # web-re-worker's query layer, not the first-hop specialist.
        table = _rc.load_specialist_table(REPO / "agents")
        name, _ = _rc.recommend_agent_type({}, CLAIM, table)
        assert name in (None, "gitnexus-query", "web-re-worker"), (
            f"misrouted to {name!r}")


# ---------- T5: real-sample demo ----------

@pytest.mark.skipif(DEMO_SCRIPT.name == "web_gitnexus_demo.py"
                    and not DEMO_SCRIPT.is_file(),
                    reason="demo script missing")
class TestDemo:
    def test_bundle_fixture_is_valid_js_and_runs(self, tmp_path):
        """The bundled sample executes under node and exposes buildSignature."""
        node = None
        for cand in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
            if Path(cand).exists():
                node = cand
                break
        if node is None:
            pytest.skip("node unavailable on host")
        src = (FIX / "bundle.min.js").read_text(encoding="utf-8")
        driver = tmp_path / "run.js"
        driver.write_text(
            "global.window={};global.fetch=function(){return null};\n"
            f"eval({json.dumps(src)});\n"
            "const s=window.__api.buildSignature({b:'2',a:'1'},'s3cr3t');\n"
            "if(!/^[0-9a-f]{8}$/.test(s)) throw new Error('bad sign '+s);\n"
            "console.log('OK '+s);\n", encoding="utf-8")
        proc = subprocess.run([node, str(driver)], capture_output=True,
                              text=True, timeout=30)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith("OK ")

    def test_demo_selfcheck_offline_green(self):
        r = subprocess.run([sys.executable, str(DEMO_SCRIPT), "--selfcheck"],
                           capture_output=True, text=True, timeout=120,
                           cwd=str(REPO))
        assert r.returncode == 0, r.stdout + r.stderr
        payload = json.loads(r.stdout)
        assert payload["mode"] == "selfcheck"
        assert payload["ok"] is True

    def test_demo_script_clis_available(self):
        selfcheck = subprocess.run(
            [sys.executable, str(DEMO_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=60, cwd=str(REPO))
        assert selfcheck.returncode == 0
        blob = open(DEMO_SCRIPT, encoding="utf-8").read()
        assert "--stand-in" in blob and "gitnexus analyze" in blob
        # upstream pins from tools/_INDEX.yaml L381 stay echoed here
        assert "1.10.0" in blob and "2.16.0" in blob

    def test_golden_query_answer_from_local_run(self):
        """Committed REAL-run capture (see fixtures README): the semantic
        layer answered the signature-trace question on this host."""
        golden = FIX / "evidence-demo.json"
        data = json.loads(golden.read_text(encoding="utf-8"))
        assert data["status"] == "ok"
        answer = data["answer"]
        assert answer["chain_exact"] is True
        assert "sendRequest" in answer["incoming_callers"]
        assert {"digest", "buildParams", "assembleBase"} <=             set(answer["outgoing_callees"])
        ran_tools = {leg["tool"] for leg in data["legs"]
                     if leg["status"] == "ran"}
        assert "gitnexus context buildSignature" in ran_tools
        skipped_names = {leg["tool"] for leg in data["legs"]
                         if leg["status"] == "skipped"}
        # degradation must stay structured, never silent
        for leg in data["legs"]:
            if leg["status"] == "skipped":
                assert leg["detail"], leg["tool"]
