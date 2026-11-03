# -*- coding: utf-8 -*-
"""tests/test_web_chain_793.py — #793 web lane analysis chain v1 (wiring).

The web lane graduates from a documented stub to a registered analysis
chain. Two external toolchains join as FIRST-CLASS supply (the tool bodies
install through the kunglao-init toolchain face / agent-do — this card is
the wiring surface, never a vendor):

  - JSIR (google/jsir) — static deep-analysis engine (L2 face): MLIR-based
    JS IR with source-to-source deobfuscation + taint dataflow + Hermes
    decompilation. Supply gate = a docker image pinned BY DIGEST; upstream
    publishes NO image, so the registry pins the upstream source ref and
    the digest is minted (frozen) at the first agent-do build.
  - iv8 (PyPI, HanZzzzz000/iv8) — offline V8 execution with a faithful
    browser env (L3 face): requests-injection loop, logical time,
    browser-API monitoring that locates env-detection chains. Supply gate
    = pinned PyPI `==`; license is proprietary non-commercial — the
    commercial-use constraint must reach the owner before any commercial
    deployment.

The lane's analysis ladder (the web reading of "static:disasm"):
  L1 AST census -> census marker features (this module's scan face)
  L2 web:static-jsir | L3 web:offline-iv8 | L4 web:live-camoufox
  corner web:wasm
No rule fired on the web lane -> the router ABSTAINS to the agent (the
addendum-3 owner ruling: fallback is abstention, not a fabricated chain)
and emits `route_abstained` telemetry — zero static:disasm output on the
web lane is the acceptance assert.

Tests never require the real tools: every probe face is pinned through an
injected `run` callable (recording injections pin the exact argv), the
same discipline as the #812 capability probes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

import lane_spec  # noqa: E402
import lane_profile  # noqa: E402
import web_chain  # noqa: E402


# ================================================= helpers

def _recorder(argv_results: dict | None = None):
    """Injection pin: records argv, never executes; per-argv scripted
    results default to rc=0 / empty out."""
    calls: list[list[str]] = []

    def run(argv, timeout: int = 10):
        calls.append(list(argv))
        scripted = (argv_results or {}).get(tuple(argv), (0, "", ""))
        return (int(scripted[0]), str(scripted[1]), str(scripted[2]))

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _declared_ws(tmp_path: Path, lane: str, ptype: str = "linux") -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"lane": lane}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        f"project_type={ptype}\n", encoding="utf-8")
    return ws


# ================================================= 1. the chain registry

class TestChainRegistry:
    def test_four_chains_with_exact_names_and_rungs(self) -> None:
        names = tuple(c["name"] for c in web_chain.CHAINS)
        assert names == ("web:static-jsir", "web:offline-iv8",
                         "web:live-camoufox", "web:wasm")
        rungs = [c["rung"] for c in web_chain.CHAINS]
        assert rungs == ["L2", "L3", "L4", "corner"]

    def test_every_chain_names_its_toolchain_and_supply(self) -> None:
        for c in web_chain.CHAINS:
            assert c.get("toolchain"), c
            assert c.get("supply"), c

    def test_jsir_supply_is_a_digest_pinned_docker_image(self) -> None:
        img = web_chain.JSIR_IMAGE
        assert img["image"] == "jsir"
        assert img["source_repo"] == "google/jsir"
        # upstream publishes no image: the source ref is the pin until the
        # first agent-do build mints (freezes) the digest
        ref = img["source_ref"]
        assert isinstance(ref, str) and len(ref) >= 40
        assert "digest" in img

    def test_iv8_supply_pin_is_an_exact_pypi_version(self) -> None:
        assert isinstance(web_chain.IV8_PIN, str)
        assert web_chain.IV8_PIN.count(".") == 2
        # the non-commercial constraint travels WITH the pin (supply gate
        # + legal note from the issue)
        note = web_chain.IV8_LICENSE_NOTE.lower()
        assert "non-commercial" in note or "noncommercial" in note

    def test_jsir_license_is_verified_apache(self) -> None:
        assert web_chain.JSIR_LICENSE == "Apache-2.0"


# ================================================= 2. the L1 census face

class TestCensus:
    def test_empty_input_counts_zero_for_every_marker(self) -> None:
        c = web_chain.census()
        assert c == {name: 0 for name, _rx in web_chain.CENSUS_MARKERS}

    def test_wasm_magic_detected(self) -> None:
        c = web_chain.census(b"\x00asm\x01\x00\x00\x00")
        assert c["wasm_magic"] >= 1

    def test_hermes_bytecode_detected(self) -> None:
        c = web_chain.census("1cHermes dHermes more text")
        assert c["hermes_bytecode"] >= 1

    def test_string_array_decoder_and_hex_ids(self) -> None:
        bundle = ("var _0x3a2f = function(_0x1b2c, _0x2c3d) { return "
                  "_0x1b2c(0x1a); }; " + " ".join(
                      f"_0x{i:04x}" for i in range(12)))
        c = web_chain.census(bundle)
        assert c["string_array_decoder"] >= 1
        assert c["hex_renamed_ids"] >= web_chain.HEX_ID_FLOOR

    def test_webpack_bootstrap(self) -> None:
        c = web_chain.census("var __webpack_require__ = function(id) {}")
        assert c["webpack_bootstrap"] >= 1

    def test_crypto_over_request_surface(self) -> None:
        c = web_chain.census(
            "const sig = CryptoJS.HmacSHA256(p).toString();"
            "var x = new XMLHttpRequest(); x.send(sig);")
        assert c["crypto_api"] >= 1
        assert c["xhr_fetch"] >= 1

    def test_env_detection_probes(self) -> None:
        c = web_chain.census("if (navigator.webdriver || window.cdc_adoQpoasnfa76pfcZLmcfl_Array)")
        assert c["env_probe"] >= 1

    def test_census_is_deterministic(self) -> None:
        src = "fetch('/api')\n__webpack_require__(1)"
        assert web_chain.census(src) == web_chain.census(src)


# ================================================= 3. rule -> chain map

class TestRouteWebRules:
    def test_wasm_magic_routes_to_wasm_corner(self) -> None:
        hits = web_chain.route_web(web_chain.census(b"\x00asm"))
        chains = {ch for ch, _, _ in hits}
        assert "web:wasm" in chains

    def test_obfuscation_markers_route_to_static_jsir(self) -> None:
        feats = web_chain.census(
            "var _0x0a1b = _0x2c3d(0x1a); " + " ".join(
                f"_0x{i:04x}" for i in range(12)))
        hits = web_chain.route_web(feats)
        top = max(hits, key=lambda h: h[1])
        assert top[0] == "web:static-jsir"

    def test_hermes_routes_to_static_jsir(self) -> None:
        hits = web_chain.route_web(web_chain.census("2cHermes"))
        assert any(ch == "web:static-jsir" and s >= 0.9
                   for ch, s, _ in hits)

    def test_crypto_plus_xhr_routes_to_offline_iv8(self) -> None:
        feats = web_chain.census(
            "CryptoJS.AES.encrypt(d, k); new XMLHttpRequest().send(d)")
        chains = {ch for ch, _, _ in web_chain.route_web(feats)}
        assert "web:offline-iv8" in chains

    def test_crypto_alone_is_weak_offline_iv8(self) -> None:
        feats = web_chain.census("CryptoJS.MD5(x).toString()")
        hits = web_chain.route_web(feats)
        assert any(ch == "web:offline-iv8" for ch, _, _ in hits)
        assert all(s < 0.9 for ch, s, _ in hits if ch == "web:offline-iv8")

    def test_env_probes_route_to_live_camoufox(self) -> None:
        feats = web_chain.census("navigator.webdriver === true")
        chains = {ch for ch, _, _ in web_chain.route_web(feats)}
        assert "web:live-camoufox" in chains

    def test_no_marker_no_rule(self) -> None:
        assert web_chain.route_web(web_chain.census("")) == []

    def test_rules_only_emit_registered_chains(self) -> None:
        feats = web_chain.census(
            "\x00asm 1cHermes _0x2c3d(0x1a) CryptoJS XMLHttpRequest "
            "navigator.webdriver __webpack_require__")
        for ch, _s, _r in web_chain.route_web(feats):
            assert ch in {c["name"] for c in web_chain.CHAINS}


# ================================================= 4. abstention default

class TestAbstention:
    def test_shape_has_no_fabricated_recommendation(self) -> None:
        a = web_chain.abstention("web", "no rule fired")
        assert a["recommendation"] is None
        assert a["hand_to"] == "agent"
        assert a["lane"] == "web"
        assert a["reason"]

    def test_telemetry_word_is_registered_in_emit_vocabulary(self) -> None:
        import event_taxonomy
        assert web_chain.ROUTE_ABSTAINED == "route_abstained"
        assert "route_abstained" in event_taxonomy.EMIT_ACTIONS


# ================================================= 5. lane profile join

class TestLaneProfileJoin:
    def test_web_capabilities_carry_the_chain_supplies(self) -> None:
        caps = lane_profile.lane_capabilities("web")
        assert "host_docker" in caps
        assert "iv8_module" in caps
        assert "mcp_bridge" in caps

    def test_analysis_chains_web_returns_registry(self) -> None:
        chains = lane_profile.analysis_chains("web")
        assert tuple(c["name"] for c in chains) == (
            "web:static-jsir", "web:offline-iv8", "web:live-camoufox",
            "web:wasm")

    def test_analysis_chains_other_lanes_empty(self) -> None:
        for lane in ("malware", "algorithm", "protocol", "data", "app"):
            assert lane_profile.analysis_chains(lane) == (), lane

    def test_capability_family_reverse_map_grows_web(self) -> None:
        assert lane_profile.capabilities_for_family("jsir") == \
            ("host_docker",)
        assert lane_profile.capabilities_for_family("iv8") == \
            ("iv8_module",)

    def test_web_graduates_out_of_the_stub_lanes(self) -> None:
        assert "web" not in lane_spec.STUB_LANES
        assert "stub" not in lane_spec.material("web")


# ================================================= 6. capability probes

class TestWebCapabilityProbes:
    def test_names_are_separate_facts_from_the_android_pair(self) -> None:
        import capability_probe as cp
        assert cp.WEB_CAPABILITY_NAMES == ("host_docker", "iv8_module")
        assert set(cp.WEB_CAPABILITY_NAMES).isdisjoint(cp.CAPABILITY_NAMES)
        assert cp.ALL_CAPABILITY_NAMES == cp.CAPABILITY_NAMES \
            + cp.WEB_CAPABILITY_NAMES

    def test_host_docker_pass(self) -> None:
        import capability_probe as cp
        run = _recorder({("docker", "version"): (0, "Docker version 24.0.9",
                                                 "")})
        status, detail = cp.probe_host_docker(run=run)
        assert status == "pass"
        assert "24.0.9" in detail

    def test_host_docker_fail_is_an_honest_negative(self) -> None:
        import capability_probe as cp
        run = _recorder({("docker", "version"): (1, "",
                                                 "Cannot connect to daemon")})
        status, detail = cp.probe_host_docker(run=run)
        assert status == "fail"
        assert "daemon" in detail

    def test_host_docker_argv_pinned(self) -> None:
        import capability_probe as cp
        run = _recorder()
        cp.probe_host_docker(run=run)
        assert run.calls == [["docker", "version"]]

    def test_iv8_module_pass_and_argv_pin(self) -> None:
        import capability_probe as cp
        run = _recorder({(sys.executable, "-c", "import iv8"):
                         (0, "0.1.4", "")})
        status, detail = cp.probe_iv8_module(run=run)
        assert status == "pass"
        assert "0.1.4" in detail
        assert run.calls == [[sys.executable, "-c", "import iv8"]]

    def test_iv8_module_fail_names_the_remediation_pin(self) -> None:
        import capability_probe as cp
        run = _recorder({(sys.executable, "-c", "import iv8"):
                         (1, "", "ModuleNotFoundError")})
        status, detail = cp.probe_iv8_module(run=run)
        assert status == "fail"
        assert f"iv8=={web_chain.IV8_PIN}" in detail

    def test_probe_crash_is_skip_never_fail(self) -> None:
        import capability_probe as cp

        def boom(argv, timeout: int = 10):
            raise OSError("exec outage")

        assert cp.probe_host_docker(run=boom)[0] == "skip"
        assert cp.probe_iv8_module(run=boom)[0] == "skip"

    def test_probes_registry_answers_the_web_names(self) -> None:
        import capability_probe as cp
        for name in cp.WEB_CAPABILITY_NAMES:
            assert name in cp.PROBES, name


class TestWebFamilies:
    def test_web_families_require_their_supply_fact(self) -> None:
        import capability_probe as cp
        by_name = {fam: caps for fam, _t, caps, _a in cp.WEB_FAMILIES}
        assert by_name["web-static-jsir"] == ("host_docker",)
        assert by_name["web-offline-iv8"] == ("iv8_module",)
        assert by_name["web-live-camoufox"] == ("mcp_bridge",)

    def test_match_required_fires_web_families_on_web_type(self) -> None:
        import capability_probe as cp
        got = cp.match_required("run jsir deobfuscate on the bundle", "web")
        assert ("web-static-jsir", ("host_docker",)) in got
        got2 = cp.match_required("offline reproduction via iv8", "web")
        assert ("web-offline-iv8", ("iv8_module",)) in got2

    def test_android_families_byte_identical_regression(self) -> None:
        import capability_probe as cp
        got = cp.match_required("frida hook the target", "android")
        assert ("android-dynamic-trace", ("host_frida",)) in got
        # web keywords never fire on android and vice versa
        assert cp.match_required("jsir deobfuscate", "android") == []
        assert cp.match_required("frida hook", "web") == []

    def test_unknown_project_type_never_matches(self) -> None:
        import capability_probe as cp
        assert cp.match_required("jsir iv8 camoufox", None) == []
        assert cp.match_required("jsir iv8 camoufox", "linux") == []

    def test_alternative_arm_exists_for_each_web_family(self) -> None:
        import capability_probe as cp
        for fam, _t, _c, alt in cp.WEB_FAMILIES:
            assert alt and cp.alternative_for(fam) == alt


# ================================================= 7. env-state wiring

class TestEnvStateWebBranch:
    def test_web_project_type_emits_the_three_facts(self, tmp_path,
                                                    monkeypatch) -> None:
        import env_state_probe as esp
        ws = _declared_ws(tmp_path, "web", ptype="web")
        monkeypatch.setattr(esp, "_probe_mcp_bridge",
                            lambda ws_, p: {"status": "pass"})
        monkeypatch.setattr(esp, "_cp", type("CP", (), {
            "probe_host_docker": staticmethod(
                lambda: ("pass", "docker up")),
            "probe_iv8_module": staticmethod(
                lambda: ("fail", "not importable")),
        }))
        state = esp.probe(ws)
        caps = state["per_capability"]
        assert set(caps) == {"mcp_bridge", "host_docker", "iv8_module"}
        assert caps["host_docker"]["status"] == "pass"
        assert caps["iv8_module"]["status"] == "fail"

    def test_web_caps_vocabulary_declared(self) -> None:
        import env_state_probe as esp
        assert esp.WEB_CAPS == ("mcp_bridge", "host_docker", "iv8_module")


# ================================================= 8. router face

_WEB_CENSUS = ("fetch('/api/x'); new XMLHttpRequest().send(p);"
               "CryptoJS.HmacSHA256(p, k).toString();")


class TestRouterWebLane:
    def _route(self, features, lane="web", tmp_path=None):
        from route_capability import route
        return route(features, "reproduce the signature", _index(tmp_path),
                     lane=lane)

    def test_census_fires_a_chain_no_static_disasm(self, tmp_path) -> None:
        feats = web_chain.census(_WEB_CENSUS)
        result = self._route(feats, "web", tmp_path)
        chain = result["recommendation"]["chain"]
        assert chain and chain[0] == "web:offline-iv8"
        text = json.dumps(result)
        assert "static:disasm" not in text
        assert result["recommendation"]["confidence"] >= 0.9

    def test_no_rule_abstains_to_the_agent(self, tmp_path) -> None:
        result = self._route(web_chain.census(""), "web", tmp_path)
        assert result["recommendation"] is None
        assert result["hand_to"] == "agent"
        text = json.dumps(result)
        assert "static:disasm" not in text

    def test_abstention_emits_telemetry(self, tmp_path) -> None:
        import kunglao_log
        from route_capability import route
        ws = tmp_path / "ws"
        (ws / "runs" / "logs").mkdir(parents=True)
        route(web_chain.census(""), "x", _index(tmp_path), ws=ws,
              lane="web")
        logs = list((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "abstention telemetry row expected"
        rows = [json.loads(l) for l in
                logs[0].read_text(encoding="utf-8").splitlines() if l]
        assert any(r.get("action") == "route_abstained" and
                   "lane=web" in str(r.get("detail")) for r in rows), rows

    def test_legacy_lanes_keep_the_pre_lane_behavior(self, tmp_path,
                                                     monkeypatch) -> None:
        from route_capability import route
        # the malware-lane fallback shape is NOT this card's surface: a
        # lane=None call behaves exactly as before (fabricated fallback
        # face unchanged until the general abstention card lands)
        monkeypatch.setattr("route_capability.subprocess.run",
                            lambda *a, **k: _FakeProc())
        result = route({"machine": "AMD64"}, "go binary", _index(tmp_path),
                       lane=None)
        assert result["recommendation"]["chain"]
        assert result["recommendation"]["confidence"] >= 0.7


class _FakeProc:
    returncode = 0

    @property
    def stdout(self):
        return json.dumps({"tools": [{"name": "fake-tool"}]})


def _index(tmp_path: Path) -> Path:
    p = tmp_path / "index.yaml"
    p.write_text(yaml.safe_dump({"tools": []}), encoding="utf-8")
    return p


# ================================================= 9. toolchain lane face

class TestToolchainWebSupply:
    def test_web_required_checks_grow_the_supply_items(self) -> None:
        assert lane_spec.REQUIRED_CHECKS["web"] == (
            "uv", "python", "web_material", "jsir", "iv8")

    def _check(self, tmp_path, monkeypatch, jsir_rc=1, jsir_err="no image",
               iv8_rc=1, iv8_err="ModuleNotFoundError"):
        import toolchain as tc
        ws = _declared_ws(tmp_path, "web")

        def fake_run(argv, timeout=10):
            argv = list(argv)
            if argv[:2] == ["docker", "version"]:
                return (0, "Docker version 24", "")
            if argv[:3] == ["docker", "image", "inspect"]:
                return (jsir_rc, "", jsir_err)
            if len(argv) >= 3 and argv[1] == "-c" and "import iv8" in argv[2]:
                return (iv8_rc, "", iv8_err)
            if len(argv) >= 3 and argv[1] == "-c" and "sys.version" in argv[2]:
                return (0, "3.11.4", "")
            if argv[-1] == "--version":
                return (0, "uv 1.2.3", "")
            return (0, "ok", "")

        monkeypatch.setattr(tc, "_run_cmd", fake_run)
        monkeypatch.setattr(tc.shutil, "which",
                            lambda name: f"/fake/bin/{name}")
        return tc.check(ws, "linux", lane="web")

    def test_missing_supply_warns_never_refuses_init(self, tmp_path,
                                                     monkeypatch) -> None:
        import toolchain as tc
        report = self._check(tmp_path, monkeypatch)
        names = [i.name for i in report.items]
        assert names == ["uv", "python", "web_material", "jsir", "iv8"]
        assert not [n for n in names if n in tc.LANE_NEVER_CHECKS]
        for item in report.items:
            assert item.status != tc.Status.FAIL, item
            assert (item.tier == tc.Tier.WARN
                    or item.name in ("uv", "python"))  # HARD faces

    def test_jsir_unminted_digest_carries_agent_do_build(self, tmp_path,
                                                         monkeypatch) -> None:
        import toolchain as tc
        report = self._check(tmp_path, monkeypatch)
        jsir = next(i for i in report.items if i.name == "jsir")
        assert jsir.status == tc.Status.WARN
        assert "docker build" in jsir.detail.lower()
        assert web_chain.JSIR_IMAGE["source_repo"] in jsir.detail

    def test_iv8_missing_names_the_exact_install(self, tmp_path,
                                                 monkeypatch) -> None:
        report = self._check(tmp_path, monkeypatch)
        iv8 = next(i for i in report.items if i.name == "iv8")
        assert f"iv8=={web_chain.IV8_PIN}" in iv8.detail

    def test_supply_present_passes(self, tmp_path, monkeypatch) -> None:
        import toolchain as tc
        report = self._check(tmp_path, monkeypatch, iv8_rc=0)
        iv8 = next(i for i in report.items if i.name == "iv8")
        assert iv8.status == tc.Status.PASS

    def test_lane_gate_never_hard_fails_on_supply(self, tmp_path,
                                                  monkeypatch) -> None:
        import toolchain as tc
        report = self._check(tmp_path, monkeypatch)  # everything missing
        assert report.overall_status != tc.Status.FAIL


# ================================================= 10. priority tokens

class TestPriorityFamilyTokens:
    def test_web_chain_tokens_map_to_families(self) -> None:
        from priority_ratio import tool_families_from_tools
        assert tool_families_from_tools(["jsir_gen"]) == {"jsir"}
        assert tool_families_from_tools(["iv8"]) == {"iv8"}
        assert "camoufox" in tool_families_from_tools(
            ["mcp__camoufox-reverse__launch_browser"])

    def test_lane_gate_maps_families_to_supply_capabilities(self) -> None:
        # the mechanical dispatch-eligibility chain: declared tool ->
        # family -> capability (the gate reads the reverse map)
        assert lane_profile.capabilities_for_family("camoufox") == ()
