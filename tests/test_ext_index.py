#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_ext_index.py — issue #476: ext index (three-source enum) contract.

Covers the four deliverables of #476 (repo-local reinterpretation, see
openspec/changes/issue-476-tool-search/design.md D2):

  ① ext index three-source enumeration — tools/_INDEX.ext.yaml carries
     entry-point scripts/ CLIs, hooks/ gates, and references/re-library/
     capability docs; every source path exists; zero name collisions
     against the internal registry; unmapped entries surface as
     capability: unknown (discovery never depends on the map);
  ② index consistency — tools/ext-scan.py --check regenerates in memory
     and detects a stale/tampered on-disk index (the doc_sync Gate 7
     sub-check (d) wiring is pinned in tests/test_doc_sync.py);
  ③ discovery interface — tools/tool-search.py --find <keyword> searches
     the internal registry AND the ext index, emitting name + source +
     usage per hit (zero-LLM/zero-network contract unchanged);
  ④ compatibility — devkit/subagent_review._index_tool_names resolves
     ext names too (#493 tools_used may cite an ext logical name).

Zero new trust mechanism is structural (design D6): nothing here (and
nothing in the implementation) executes an ext entry — the index is only
read and printed.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "devkit"))

EXT_INDEX = REPO_ROOT / "tools" / "_INDEX.ext.yaml"
INTERNAL_INDEX = REPO_ROOT / "tools" / "_INDEX.yaml"
EXT_SCAN = REPO_ROOT / "tools" / "ext-scan.py"
TOOL_SEARCH = REPO_ROOT / "tools" / "tool-search.py"

import subagent_review as sr  # noqa: E402


def run_py(script: Path, *args: str) -> subprocess.CompletedProcess:
    # UTF-8 decode: the tools/ CLIs carry the #317 UTF-8 stdout guard.
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
        encoding="utf-8", errors="replace",
    )


def load_ext() -> list[dict]:
    data = yaml.safe_load(EXT_INDEX.read_text(encoding="utf-8"))
    entries = data.get("ext") if isinstance(data, dict) else None
    assert isinstance(entries, list), "ext index must be a list under 'ext:'"
    return entries


def load_internal_names() -> set[str]:
    data = yaml.safe_load(INTERNAL_INDEX.read_text(encoding="utf-8"))
    return {e.get("name") for e in data.get("tools", []) if isinstance(e, dict)}


# ---------------------------------------------------------------------------
# ① shipped ext index — three-source enumeration, describe-only schema
# ---------------------------------------------------------------------------

class TestShippedExtIndex:
    def test_index_file_exists(self) -> None:
        assert EXT_INDEX.is_file(), "tools/_INDEX.ext.yaml missing (#476 deliverable 1)"

    def test_entry_schema_fields(self) -> None:
        for e in load_ext():
            for field in ("name", "capability", "source", "usage", "description"):
                assert isinstance(e.get(field), str) and e[field].strip(), (
                    f"ext entry {e.get('name')!r}: field {field!r} missing/empty")

    def test_three_sources_enumerated(self) -> None:
        sources = [e["source"] for e in load_ext()]
        assert any(s.startswith("scripts/") for s in sources), (
            "no scripts/ CLI enumerated — source 1 of 3 missing")
        assert any(s.startswith("hooks/") for s in sources), (
            "no hooks/ gate enumerated — source 2 of 3 missing")
        assert any(s.startswith("references/re-library/") for s in sources), (
            "no references/re-library/ doc enumerated — source 3 of 3 missing")

    def test_all_source_paths_exist(self) -> None:
        missing = [e["source"] for e in load_ext()
                   if not (REPO_ROOT / e["source"]).exists()]
        assert missing == [], f"ext entries point at missing files: {missing}"

    def test_names_unique_and_disjoint_from_internal(self) -> None:
        names = [e["name"] for e in load_ext()]
        assert len(names) == len(set(names)), "duplicate ext names"
        overlap = set(names) & load_internal_names()
        assert not overlap, (
            f"ext names colliding with internal registered names: {overlap} "
            "(bare-name resolution must stay unambiguous)")

    def test_unknown_capability_is_represented(self) -> None:
        """The capability map is partial by design (issue #476: discovery
        must not depend on map maintenance) — unmapped entries surface as
        capability: unknown, mapped ones carry a domain:op tag."""
        caps = [e["capability"] for e in load_ext()]
        assert "unknown" in caps, (
            "no capability: unknown entry — either everything got mapped "
            "(map no longer optional) or the fallback is broken")
        tagged = [c for c in caps if c != "unknown"]
        assert tagged, "capability map never applied"
        for c in tagged:
            domain, _, op = c.partition(":")
            assert domain.strip() and op.strip(), f"bad capability tag {c!r}"

    def test_scale_sanity(self) -> None:
        """The repo carries 90 entry-point py files + 30 re-library docs;
        a healthy enumeration is order-of-100 entries, not a hand-picked
        handful (loose pin: freshness is enforced by --check, not here)."""
        assert len(load_ext()) >= 100


# ---------------------------------------------------------------------------
# ② ext-scan generator — determinism, staleness detection, structure rule
# ---------------------------------------------------------------------------

CLI_FIXTURE = '''#!/usr/bin/env python3
"""alpha_tool.py - fixture CLI with a usage block.

Longer prose line that must not leak into the usage slot.
"""
if __name__ == "__main__":
    raise SystemExit(0)
'''

LIB_FIXTURE = '''#!/usr/bin/env python3
"""lib_mod.py - fixture library module (no entry point)."""
def helper():
    return 1
'''

HOOK_FIXTURE = '''#!/usr/bin/env python3
"""omega_gate.py - fixture hook gate."""
if __name__ == "__main__":
    raise SystemExit(0)
'''

REF_FIXTURE = """---
name: cap-doc
description: Fixture capability declaration doc.
---
# Cap Doc
prose body
"""


def _sandbox_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "hooks").mkdir()
    (root / "references" / "re-library").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "scripts" / "alpha_tool.py").write_text(CLI_FIXTURE, encoding="utf-8")
    (root / "scripts" / "lib_mod.py").write_text(LIB_FIXTURE, encoding="utf-8")
    (root / "hooks" / "omega_gate.py").write_text(HOOK_FIXTURE, encoding="utf-8")
    (root / "references" / "re-library" / "cap-doc.md").write_text(
        REF_FIXTURE, encoding="utf-8")
    return root


class TestExtScan:
    def test_check_passes_on_real_repo(self) -> None:
        r = run_py(EXT_SCAN, "--check")
        assert r.returncode == 0, (
            f"shipped ext index is stale/tampered — regenerate via "
            f"`python tools/ext-scan.py`. stderr: {r.stderr}")

    def test_deterministic_output(self) -> None:
        r1 = run_py(EXT_SCAN, "--stdout")
        r2 = run_py(EXT_SCAN, "--stdout")
        assert r1.returncode == r2.returncode == 0
        assert r1.stdout == r2.stdout

    def test_sandbox_enumeration_and_exclusion(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        assert r.returncode == 0, r.stderr
        data = yaml.safe_load(r.stdout)
        entries = {e["name"]: e for e in data["ext"]}
        # three sources in, structural rule applied: lib module OUT
        assert "alpha_tool" in entries
        assert entries["alpha_tool"]["source"] == "scripts/alpha_tool.py"
        assert "omega_gate" in entries
        assert "cap-doc" in entries
        assert "lib_mod" not in entries, (
            "no-entry-point library module must stay out of the ext index "
            "(structural whitelist, design D3)")

    def test_unknown_fallback_and_map_override(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        (root / "tools" / "_INDEX.ext.map.yaml").write_text(
            "map:\n  alpha_tool: sandbox:alpha\n", encoding="utf-8")
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        assert entries["alpha_tool"]["capability"] == "sandbox:alpha"
        assert entries["omega_gate"]["capability"] == "unknown"

    def test_check_detects_stale_index(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        fresh = r.stdout
        # stale variant: one entry short
        data = yaml.safe_load(fresh)
        data["ext"] = data["ext"][:-1]
        (root / "tools" / "_INDEX.ext.yaml").write_text(
            yaml.safe_dump(data), encoding="utf-8")
        r2 = run_py(EXT_SCAN, "--root", str(root), "--check")
        assert r2.returncode == 1, "stale index must fail --check"

    def test_check_non_utf8_tampered_index_exits_clean(self, tmp_path: Path) -> None:
        """L3 (#476 review): a non-UTF-8 tampered on-disk index must land
        in the `stale` branch (structured stderr + exit 1), not raise a
        UnicodeDecodeError traceback — same "structured error, never a
        traceback" CLI contract as #317."""
        root = _sandbox_root(tmp_path)
        run_py(EXT_SCAN, "--root", str(root))  # regenerate a valid index
        (root / "tools" / "_INDEX.ext.yaml").write_bytes(
            b"schema: tools-ext-index/1\next:\n  - name: \xff\xfe\x92 garbage\n")
        r = run_py(EXT_SCAN, "--root", str(root), "--check")
        assert r.returncode == 1, "tampered index must fail --check"
        assert "stale" in r.stderr, (
            f"must report staleness, got stderr: {r.stderr!r}")
        assert "Traceback" not in r.stderr, (
            "non-UTF-8 on-disk index must not crash with a traceback")

    def test_check_passes_on_fresh_sandbox(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        run_py(EXT_SCAN, "--root", str(root))  # regenerate in place
        r = run_py(EXT_SCAN, "--root", str(root), "--check")
        assert r.returncode == 0, r.stderr

    def test_usage_lines_derived(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        assert entries["alpha_tool"]["usage"] == "python scripts/alpha_tool.py"
        assert entries["omega_gate"]["usage"].startswith("hook hooks/omega_gate.py")
        assert entries["cap-doc"]["usage"].startswith("read references/re-library/")


# ---------------------------------------------------------------------------
# ③ discovery interface — tool-search --find (query face of the #494 contract)
# ---------------------------------------------------------------------------

class TestToolSearchFind:
    def test_find_hits_ext_with_source_and_usage(self) -> None:
        r = run_py(TOOL_SEARCH, "--find", "converg", "--json")
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["count"] >= 1
        ext_hits = [t for t in out["tools"] if t.get("kind") == "ext"]
        assert any(t["source"] == "scripts/convergence_check.py"
                   for t in ext_hits), "ext hit must carry its source path"
        assert all(t.get("usage") for t in ext_hits), "hits must carry a usage line"

    def test_find_hits_internal_registry_too(self) -> None:
        r = run_py(TOOL_SEARCH, "--find", "crypto", "--json")
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        internal = [t for t in out["tools"] if t.get("kind") == "internal"]
        assert any(t["name"] == "crypto-tool" for t in internal)
        assert all(t["source"] == "tools/_INDEX.yaml" for t in internal)

    def test_find_is_case_insensitive(self) -> None:
        r = run_py(TOOL_SEARCH, "--find", "CONVERG", "--json")
        assert r.returncode == 0
        assert json.loads(r.stdout)["count"] >= 1

    def test_find_no_match_is_valid_empty_query(self) -> None:
        r = run_py(TOOL_SEARCH, "--find", "zzz-no-such-capability-qqq", "--json")
        assert r.returncode == 0
        assert json.loads(r.stdout) == {"count": 0, "tools": []}

    def test_find_mutually_exclusive_with_filters(self) -> None:
        r = run_py(TOOL_SEARCH, "--find", "x", "--tier", "T1")
        assert r.returncode == 2, (
            "--find composes with --tier/--cost-max/--capability only by "
            "silently dropping ext entries (they carry no tier) — refuse "
            "instead (design D8)")

    def test_find_text_mode_carries_usage(self) -> None:
        r = run_py(TOOL_SEARCH, "--find", "converg")
        assert r.returncode == 0
        assert "scripts/convergence_check.py" in r.stdout
        assert "convergence_check" in r.stdout


# ---------------------------------------------------------------------------
# ③b zero-LLM / zero-network contract (mechanical, #476 acceptance)
# ---------------------------------------------------------------------------

NETWORK_IMPORT_RE = re.compile(
    r"^\s*(import|from)\s+(requests|urllib|http|socket|ftplib|smtplib|ssl|aiohttp)\b",
    re.MULTILINE)


class TestZeroNetworkContract:
    def test_tool_search_has_no_network_imports(self) -> None:
        src = TOOL_SEARCH.read_text(encoding="utf-8")
        assert not NETWORK_IMPORT_RE.search(src), (
            f"tool-search must stay zero-network: {NETWORK_IMPORT_RE.search(src)}")

    def test_ext_scan_has_no_network_imports(self) -> None:
        src = EXT_SCAN.read_text(encoding="utf-8")
        assert not NETWORK_IMPORT_RE.search(src), (
            "ext-scan must stay zero-network (offline deterministic generator)")


# ---------------------------------------------------------------------------
# ③c import purity — the UTF-8 stdout guard is a CLI-entry concern only
# ---------------------------------------------------------------------------

class TestImportPurity:
    def test_doc_sync_style_import_keeps_importer_stdout_codec(self) -> None:
        """L2 (#476 review): devkit/doc_sync._load_ext_scan() executes
        ext-scan.py's module top level via importlib (entry-point
        predicate reuse). That execution must NOT reconfigure the
        IMPORTING gate process's stdout codec: doc_sync._safe() encodes
        per sys.stdout.encoding at call time, so a UTF-8 flip mid-run
        turns Chinese violation text into mojibake on a GBK console
        (exit codes unaffected, but the gate output rots)."""
        import importlib.util
        buf = io.BytesIO()
        fake = io.TextIOWrapper(buf, encoding="ascii", errors="replace")
        saved = sys.stdout
        sys.stdout = fake
        try:
            # exactly the doc_sync._load_ext_scan() load shape (same
            # module name, file-location spec, exec_module)
            spec = importlib.util.spec_from_file_location(
                "kunglao_ext_scan", EXT_SCAN)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # runs the module top level
        finally:
            sys.stdout = saved
            fake.close()
        assert mod.__name__ == "kunglao_ext_scan"
        # the import stayed functional (doc_sync predicate reuse intact)
        assert callable(mod.has_entry_point) and callable(mod.iter_entry_sources)
        # the importer's stdout codec is untouched
        assert fake.encoding.lower() == "ascii", (
            f"import reconfigured the gate process's stdout to "
            f"{fake.encoding!r} — the guard must fire on CLI entry only "
            f"(if __name__ == '__main__'), never on import")

    def test_cli_entry_still_reconfigures_stdout_utf8(self) -> None:
        """Positive control for the L2 fix: the SCRIPT entry path keeps
        the canonical #317 guard. PYTHONIOENCODING=ascii reproduces the
        GBK-console hazard without a real GBK terminal — the shipped ext
        index carries non-ASCII (CJK descriptions), so without the guard
        --stdout dies with UnicodeEncodeError (traceback, exit != 0)."""
        env = {**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"}
        r = subprocess.run(
            [sys.executable, str(EXT_SCAN), "--stdout"],
            capture_output=True, timeout=120, cwd=str(REPO_ROOT), env=env)
        assert r.returncode == 0, (
            f"non-ASCII output crashed under PYTHONIOENCODING=ascii: "
            f"exit {r.returncode}\nstderr={r.stderr.decode('utf-8', 'replace')!r}")
        out = r.stdout.decode("utf-8", errors="replace")
        assert any(ord(c) > 127 for c in out), (
            "fixture lost: shipped ext index should carry non-ASCII text "
            "(CJK descriptions) for this hazard to be observable")


# ---------------------------------------------------------------------------
# ④ compatibility — _index_tool_names resolves ext names (#493 surface)
# ---------------------------------------------------------------------------

class TestIndexToolNamesExt:
    def test_real_repo_resolves_ext_names(self) -> None:
        names = sr._index_tool_names(REPO_ROOT)
        assert "convergence_check" in names, (
            "ext logical names must join the bare-name resolution set (#493 "
            "tools_used may cite them)")
        assert "crypto-tool" in names  # internal names unchanged

    def test_resolver_accepts_ext_bare_name(self) -> None:
        assert sr._tool_resolves("convergence_check", REPO_ROOT)

    def test_fail_closed_on_broken_ext_yaml(self, tmp_path: Path) -> None:
        """A broken ext file drops ONLY ext names — internal resolution
        must not be collateral damage (design D9)."""
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "_INDEX.yaml").write_text(
            "tools:\n  - name: crypto-tool\n", encoding="utf-8")
        (tmp_path / "tools" / "_INDEX.ext.yaml").write_text(
            "ext: [ :{broken", encoding="utf-8")
        names = sr._index_tool_names(tmp_path)
        assert "crypto-tool" in names
        assert names == {"crypto-tool"}, (
            f"broken ext yaml must not leak names: {names}")


# ---------------------------------------------------------------------------
# #515: environment-side wiring — ext-scan --with-mcp <probe-json>
# ---------------------------------------------------------------------------

# Machine-local project path in the probe fixture — absolute shape from
# inert fragments (#690); the leak assertion derives from the same constant.
_PROJ = "D:" + "/lab/proj"

PROBE_JSON: dict = {
    "schema": "mcp-inventory/1",
    "claude_json": "somewhere/.claude.json",
    "server_count": 3,
    "servers": [
        {"name": "camoufox", "prefix": "mcp__camoufox__*",
         "sources": ["user-global"], "in_manifest": False,
         "manifest_tier": None, "required_for_types": []},
        {"name": "gitnexus", "prefix": "mcp__gitnexus__*",
         "sources": ["user-project:" + _PROJ], "in_manifest": True,
         "manifest_tier": "HARD", "required_for_types": ["android"]},
        {"name": "playwright", "prefix": "mcp__playwright__*",
         "sources": ["workspace"], "in_manifest": False,
         "manifest_tier": None, "required_for_types": []},
    ],
}


def _probe_file(tmp_path: Path, probe: dict | None = None) -> Path:
    p = tmp_path / "probe.json"
    p.write_text(json.dumps(probe if probe is not None else PROBE_JSON),
                 encoding="utf-8")
    return p


class TestMcpWiring:
    """① ext-scan --with-mcp merges mcp_probe inventory entries into the
    ext catalog (kind-inferable by the mcp__ name prefix, source =
    claude-json provenance label, describe-only); ② generator-level
    inconsistency exits 1; ③ the COMMITTED repo index stays
    environment-free (regeneration discipline)."""

    def test_with_mcp_merges_entries(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                   str(_probe_file(tmp_path)), "--stdout")
        assert r.returncode == 0, r.stderr
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        for name in ("mcp__camoufox", "mcp__gitnexus", "mcp__playwright"):
            assert name in entries, f"{name} missing from merged index"
        e = entries["mcp__camoufox"]
        assert e["source"] == "claude-json", (
            "mcp entries carry a provenance label, not a repo path (#515 D2)")
        assert e["capability"] == "mcp:camoufox"
        assert "--mcp-inventory" in e["usage"], (
            "usage must name the probe regeneration command")
        assert "describe-only" in e["description"]
        # repo entries survive the merge untouched
        assert "alpha_tool" in entries

    def test_with_mcp_manifest_annotation_in_description(self,
                                                         tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                   str(_probe_file(tmp_path)), "--stdout")
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        assert "user-global" in entries["mcp__camoufox"]["description"]
        assert "environment-extra" in entries["mcp__camoufox"]["description"]
        assert "HARD" in entries["mcp__gitnexus"]["description"]
        assert "android" in entries["mcp__gitnexus"]["description"]
        # project path detail is sanitized to the surface kind
        assert _PROJ not in entries["mcp__gitnexus"]["description"]

    def test_with_mcp_capability_map_override(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        (root / "tools" / "_INDEX.ext.map.yaml").write_text(
            "map:\n  mcp__camoufox: web:stealth-browse\n", encoding="utf-8")
        r = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                   str(_probe_file(tmp_path)), "--stdout")
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        assert entries["mcp__camoufox"]["capability"] == "web:stealth-browse"
        assert entries["mcp__gitnexus"]["capability"] == "mcp:gitnexus"

    def test_with_mcp_deterministic(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        probe = _probe_file(tmp_path)
        r1 = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                    str(probe), "--stdout")
        r2 = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                    str(probe), "--stdout")
        assert r1.returncode == r2.returncode == 0
        assert r1.stdout == r2.stdout

    def test_with_mcp_rejects_duplicate_server(self, tmp_path: Path) -> None:
        probe = json.loads(json.dumps(PROBE_JSON))
        probe["servers"].append(dict(probe["servers"][0]))
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                   str(_probe_file(tmp_path, probe)), "--stdout")
        assert r.returncode == 1, "duplicate server = generator inconsistency"
        assert "duplicate" in r.stderr

    def test_with_mcp_rejects_non_probe_document(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                   str(_probe_file(tmp_path, {"nope": 1})), "--stdout")
        assert r.returncode == 1
        assert "mcp-inventory" in r.stderr or "servers" in r.stderr

    def test_with_mcp_unreadable_file_is_usage_error(self,
                                                     tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                   str(tmp_path / "missing-probe.json"), "--stdout")
        assert r.returncode == 2

    def test_with_mcp_name_collision_with_repo_stem(self,
                                                    tmp_path: Path) -> None:
        """A probe server whose mcp__<name> collides with a repo entry-point
        stem must refuse generation (bare-name resolution stays unambiguous)."""
        root = _sandbox_root(tmp_path)
        (root / "scripts" / "mcp__evil.py").write_text(CLI_FIXTURE,
                                                       encoding="utf-8")
        probe = {"servers": [{"name": "evil", "prefix": "mcp__evil__*",
                              "sources": ["user-global"],
                              "manifest_tier": None,
                              "required_for_types": []}]}
        r = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
                   str(_probe_file(tmp_path, probe)), "--stdout")
        assert r.returncode == 1, "mcp/repo stem collision must refuse"
        assert "ambiguous" in r.stderr

    def test_committed_repo_index_stays_environment_free(self) -> None:
        """The shipped tools/_INDEX.ext.yaml is regenerated WITHOUT
        --with-mcp (committed artifact = repo face only; the environment
        face is per-machine, #515 D2)."""
        names = [e["name"] for e in load_ext()]
        mcp = [n for n in names if n.startswith("mcp__")]
        assert mcp == [], (
            f"committed ext index carries environment entries: {mcp} — "
            "regenerate with plain `python tools/ext-scan.py`")
        r = run_py(EXT_SCAN, "--check")
        assert r.returncode == 0, r.stderr
