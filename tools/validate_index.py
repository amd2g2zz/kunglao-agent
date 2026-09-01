#!/usr/bin/env python3
"""validate_index.py — tools/_INDEX.yaml machine-contract validator (issue #283).

Validates the machine-readable tool index against the contract:

  name:         unique, non-empty (lowercase kebab-case tool id)
  category:     one of crypto|static|ghidra|dynamic|auxiliary|pipelines
                (#340: category id == tools/<category>/ directory name; the
                only dir-less exception is dynamic — external MCP capability)
  capability:   "<domain>:<operation>" tag (e.g. crypto:decode), non-empty
  tier:         T1|T2|T3   (T1 static tool / T2 emulation / T3 VM-dynamic)
  cost_tier:    probe|cheap|deep
  input_output: non-empty input->output contract (str, or {input, output})
  description:  required non-empty English one-liner, 15-40 chars
                (what it does + when to choose it) — issue #356 W1
  when_not:     optional — when NOT to use the tool (non-empty if present)

#692 WP1 capability-provider annotation block (design D1/D2; OPT-IN — an
# entry without `provider` never raises annotation errors):
  provider:    unique provider identity (matches a toolchain FIXES key or
               an mcp_probe.MANIFEST name); one entry per provider
  produces:    non-empty list of "<domain>:<operation>" tags; MUST include
               the entry's primary `capability`
  requires:    list of precondition tokens from the closed vocabulary
               PROVIDER_TOKENS (design D2); may be empty
  cost_hint:   {mem_gb: number >= 0, time: probe|cheap|deep}
  quality:     non-empty map {capability-tag: high|mid|floor} whose keys are
               exactly the `produces` set (per-capability quality: baksmali
               is floor for java-source but high for bytecode-truth)

CLI contract (gate-callable):
  python validate_index.py [path_to_index.yaml]
  exit 0 = pass, exit 1 = fail with an error list printed to stderr.
  Default path: tools/_INDEX.yaml (sibling of this script).

An empty index (`tools: []`, a missing `tools` key, or a null/empty YAML
payload) passes — the file ships as an initially-empty skeleton.

Usage:
  python tools/validate_index.py            # validate the shipped skeleton
  python tools/validate_index.py my-index.yaml
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402


import argparse
import sys
from pathlib import Path

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.

# ---- #729 annotation gate constants ------------------------------------
# Rule A — LEGACY_UNANNOTATED whitelist (29 entries without provider blocks).
# Frozen set: entries may ONLY be removed, never added. Every removal is a
# deliberate annotation migration (one-way, never reversed). Annotating a
# LEGACY entry is encouraged — it graduates to the real registry.
_LEGACY_UNANNOTATED = frozenset({
    "crypto-tool", "ghidra-recon", "ghidra-decompile-functions",
    "ghidra-vtable-struct", "ghidra-evidence-annotations",
    "ghidra-scan-pointer", "disasm-constant-check", "yara-scan",
    "yara-gen", "extract-syscalls", "stack-strings", "binary-sweep",
    "strings-classify", "go-buildinfo-carve", "rust-dep-strings",
    "call-site-args", "pe-analyze", "overlay-scan", "disasm-dump",
    "shellcode-scan", "die-probe", "c-normalize", "opaque-pred",
    "build-evidence-index", "audit-legacy-proven", "capture-golden",
    "measure-blind-coverage", "measure-cold-start", "sanitize-text",
})

# Rule B — CAPABILITY_TAGS closed vocabulary (#729).
# Every <domain>:<operation> tag that appears in any `produces` field must
# be listed here. Expanding this constant is an intentional, review-visible
# design decision (one tool ≠ one tag; one tag = distinct routing
# capability that changes tool-selection behaviour).
#
# Seeded from existing produces tags (9 android: tags from #692 WP1).
# #728 (web labs) landed js:unbundle / js:deobfuscate; #751 adds the
# js-domain semantic pair mirroring android (#751 design D1).
_CAPABILITY_TAGS = frozenset({
    # android: — seeded from #692 WP1 provider entries
    "android:algorithm-verify",
    "android:bytecode-truth",
    "android:call-graph",
    "android:data-flow",
    "android:dex-rewrite",
    "android:java-source",
    "android:packer-fingerprint",
    "android:semantic-query",
    "android:string-decrypt",
    # aux: — seeded from the #340 category contract test (auxiliary must be
    # a legal category with at least one routable capability tag)
    "aux:sanitize",
    # web: — coordinated with #728 merge (js_unbundle / js_deobfuscate)
    # Note: wakaru-unbundle produces js:unbundle; webcrack-deobfuscate produces js:deobfuscate
    # These are the canonical routing tags for JS recovery pipelines.
    "js:deobfuscate",
    "js:call-graph",      # #751: gitnexus over wakaru/webcrack output
    "js:semantic-query",  # #751: graph RAG queries over a js source tree
    "js:unbundle",
    # crypto: — legitimate routing tag for the crypto-tool family
    "crypto:decode",
})
# ---- end annotation gate constants -------------------------------------

CATEGORIES = ("crypto", "static", "ghidra", "dynamic", "auxiliary", "pipelines")
TIERS = ("T1", "T2", "T3")
COST_TIERS = ("probe", "cheap", "deep")
# #692 WP1: closed precondition vocabulary (design D2) + quality tiers.
PROVIDER_TOKENS = ("dex", "mem_budget_ok", "dexdc_wheel", "jadx_bin",
                   "smali_toolchain", "source_tree", "gitnexus_index")
QUALITY_TIERS = ("high", "mid", "floor")
REQUIRED_FIELDS = ("name", "category", "capability", "tier", "cost_tier",
                   "input_output", "description")


def _is_nonempty_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_domain_operation(value: str) -> bool:
    """capability must be '<domain>:<operation>' with both sides non-empty."""
    if not _is_nonempty_str(value):
        return False
    domain, _, op = value.partition(":")
    return bool(domain.strip()) and bool(op.strip())


def _is_nonempty_io(value) -> bool:
    """input_output non-empty: a non-blank string, or a dict holding a value."""
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, dict):
        return bool(value) and any(_is_nonempty_str(v) for v in value.values())
    return False


def _check_provider_annotations(entry: dict, loc: str, i: int,
                                seen_providers: dict[str, int],
                                errors: list[str]) -> None:
    """#692 WP1: the opt-in capability-provider annotation block (D1).

    Only runs when `provider` is present — legacy entries are untouched.
    """
    provider = entry.get("provider")
    if not _is_nonempty_str(provider):
        errors.append(f"{loc}: 'provider' must be a non-empty string")
        provider = None
    elif provider in seen_providers:
        errors.append(f"{loc}: duplicate 'provider' '{provider}' "
                      f"(first at tools[{seen_providers[provider]}])")
    else:
        seen_providers[provider] = i

    produces = entry.get("produces")
    produced: set[str] = set()
    if not isinstance(produces, list) or not produces:
        errors.append(f"{loc}: 'produces' must be a non-empty list of "
                      "'<domain>:<operation>' tags")
    else:
        for tag in produces:
            if not _is_domain_operation(tag):
                errors.append(f"{loc}: 'produces' tag {tag!r} must be "
                              "'<domain>:<operation>'")
            else:
                produced.add(tag)
        if not produced:
            errors.append(f"{loc}: 'produces' holds no valid tags")

    # #729 Rule B: every produces tag must be in the closed CAPABILITY_TAGS
    # vocabulary. Expanding this vocabulary is an intentional design decision
    # (one tool ≠ one tag; one tag = distinct routing capability).
    if produced:
        unknown_tags = produced - _CAPABILITY_TAGS
        if unknown_tags:
            errors.append(
                f"{loc}: produces tag(s) {sorted(unknown_tags)} not in the "
                "closed CAPABILITY_TAGS vocabulary — add to _CAPABILITY_TAGS "
                f"only after deliberate review (current vocabulary: "
                f"{sorted(_CAPABILITY_TAGS)})"
            )

    requires = entry.get("requires")
    if not isinstance(requires, list):
        errors.append(f"{loc}: 'requires' must be a list of precondition "
                      "tokens (may be empty)")
    else:
        for token in requires:
            if token not in PROVIDER_TOKENS:
                errors.append(f"{loc}: 'requires' token {token!r} outside "
                              f"the closed vocabulary {PROVIDER_TOKENS}")

    cost_hint = entry.get("cost_hint")
    if not isinstance(cost_hint, dict):
        errors.append(f"{loc}: 'cost_hint' must be a mapping "
                      "{{mem_gb, time}}")
    else:
        mem = cost_hint.get("mem_gb")
        if not isinstance(mem, (int, float)) or isinstance(mem, bool)                 or mem < 0:
            errors.append(f"{loc}: 'cost_hint.mem_gb' must be a number >= 0, "
                          f"got {mem!r}")
        if cost_hint.get("time") not in COST_TIERS:
            errors.append(f"{loc}: 'cost_hint.time' must be one of "
                          f"{COST_TIERS}, got {cost_hint.get('time')!r}")

    quality = entry.get("quality")
    if not isinstance(quality, dict) or not quality:
        errors.append(f"{loc}: 'quality' must be a non-empty map "
                      "{capability-tag: high|mid|floor}")
    else:
        for tag, tier in quality.items():
            if tag not in produced:
                errors.append(f"{loc}: 'quality' key {tag!r} is not in "
                              "'produces' (every produced capability needs "
                              "a quality tier)")
            if tier not in QUALITY_TIERS:
                errors.append(f"{loc}: 'quality[{tag!r}]' must be one of "
                              f"{QUALITY_TIERS}, got {tier!r}")
        missing_q = produced - set(quality)
        if missing_q:
            errors.append(f"{loc}: 'quality' missing tiers for produced "
                          f"capabilities {sorted(missing_q)}")

    if produced and entry.get("capability") not in produced:
        errors.append(f"{loc}: 'capability' {entry.get('capability')!r} must "
                      "be a member of 'produces'")


def validate_index(data) -> list[str]:
    """Validate a parsed _INDEX.yaml payload. Returns a list of error strings.

    Empty payload / missing `tools` key -> empty index -> no errors.
    """
    errors: list[str] = []
    if data is None:
        return errors
    if not isinstance(data, dict):
        return ["index root must be a YAML mapping"]
    if "tools" not in data:
        return errors  # initially-empty skeleton: no tools list yet
    tools = data["tools"]
    if not isinstance(tools, list):
        return ["'tools' must be a list"]

    seen_names: dict[str, int] = {}
    seen_providers: dict[str, int] = {}
    for i, entry in enumerate(tools):
        loc = f"tools[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{loc}: entry must be a mapping")
            continue
        name = entry.get("name")
        if not _is_nonempty_str(name):
            errors.append(f"{loc}: missing or empty 'name'")
        elif name in seen_names:
            errors.append(f"{loc}: duplicate 'name' '{name}' (first at tools[{seen_names[name]}])")
        else:
            seen_names[name] = i

        category = entry.get("category")
        if category not in CATEGORIES:
            errors.append(f"{loc}: 'category' must be one of "
                          f"{'/'.join(CATEGORIES)}, got {category!r}")

        capability = entry.get("capability")
        if not _is_domain_operation(capability):
            errors.append(f"{loc}: 'capability' must be '<domain>:<operation>' "
                          f"(e.g. crypto:decode), got {capability!r}")

        tier = entry.get("tier")
        if tier not in TIERS:
            errors.append(f"{loc}: 'tier' must be one of {TIERS}, got {tier!r}")

        cost_tier = entry.get("cost_tier")
        if cost_tier not in COST_TIERS:
            errors.append(f"{loc}: 'cost_tier' must be one of "
                          f"{COST_TIERS}, got {cost_tier!r}")

        if not _is_nonempty_io(entry.get("input_output")):
            errors.append(f"{loc}: 'input_output' must be non-empty "
                          f"(str or {{input, output}})")

        # #356 W1: description is required — agent tool selection aid
        if not _is_nonempty_str(entry.get("description")):
            errors.append(f"{loc}: missing or empty 'description' "
                          f"(one-liner: what it does + when to choose it)")

        when_not = entry.get("when_not")
        if when_not is not None and not _is_nonempty_str(when_not):
            errors.append(f"{loc}: optional 'when_not' must be a non-empty string")

        # #729 Rule A: new entries without a provider block are dead weight.
        # LEGACY_UNANNOTATED (29 entries, frozen) get a WARN pass.
        # Every other entry MUST carry a provider block.
        if "provider" not in entry:
            if name not in _LEGACY_UNANNOTATED:
                errors.append(
                    f"{loc}: entry '{name}' has no 'provider' block and is not "
                    "in LEGACY_UNANNOTATED — new entries must carry annotation "
                    f"blocks ({len(_LEGACY_UNANNOTATED)} legacy names are "
                    "tolerated without annotation)"
                )

        # #692 WP1: opt-in annotation block (skipped for legacy entries)
        if "provider" in entry:
            _check_provider_annotations(entry, loc, i, seen_providers, errors)

    return errors


# ---- CLI ----

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="validate tools/_INDEX.yaml (issue #283)")
    ap.add_argument("path", nargs="?", default=None,
                    help="path to the index yaml (default: tools/_INDEX.yaml "
                         "next to this script)")
    args = ap.parse_args(argv)

    if args.path:
        index_path = Path(args.path)
    else:
        index_path = Path(__file__).resolve().parent / "_INDEX.yaml"
    if not index_path.is_file():
        print(f"error: index file not found: {index_path}", file=sys.stderr)
        return 1

    try:
        import yaml
        data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - report any YAML parse failure
        print(f"error: failed to parse {index_path}: {exc}", file=sys.stderr)
        return 1

    errors = validate_index(data)
    if errors:
        print(f"error: {index_path} has {len(errors)} violation(s):",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"ok: {index_path} passes the tools-index contract "
          f"({len(data.get('tools', [])) if isinstance(data, dict) else 0} tool(s))")
    return 0


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
