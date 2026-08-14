#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_capability.py — deterministic feature→capability router (issue #278 P4-b).

Same family as priority.py / feature_probe.py / tool-search.py: zero-LLM,
zero-network, stdlib-only (+ repo pyyaml). Reads the SAME state the rest of
the system owns (tools/_INDEX.yaml, claim-register.yaml, feature_probe JSON)
and creates NO new state files. The router is meta (like tool-search) and is
deliberately NOT registered in tools/_INDEX.yaml.

Inputs:
  features     feature_probe.py --json output, via --features-file <path>
               (canonical) or inline --features '<json>' (injectable)
  claim        --claim <claim-id> [--register <path>] reads the claim's
               statement from a claim-register.yaml; OR --claim-text
               "<description>" supplies intent text directly (mutually
               exclusive). --workspace <ws> locates the default register.
  --index      override the tool index (default tools/_INDEX.yaml)

Feature→capability rules (deterministic, fired in rule order):
  machine I386/AMD64 (0x14c/0x8664)    → static:disasm-check   (0.7 structural)
  overlay true                         → static:overlay        (0.7 structural)
  entropy >= 6.5                       → crypto:decode         (0.6 weak)
  import_hints crypt32/bcrypt/advapi   → crypto:decode         (0.9 exact)
  string_density >= 0.5 + packer mark  → anti-analysis         (0.6 weak)
  go markers (go.buildinfo/runtime.*)  → languages:go          (0.9 exact)

Claim-intent overlay keywords (word-boundary match; refine the recommendation):
  decrypt|decode → crypto:decode (0.9)   unpack → static:overlay (0.7)
  syscall → dynamic:syscall (0.8)        iat → static:disasm-check (0.8)
  go → languages:go (0.8)                vm|run|execute|detonate → dynamic:run (0.9)

CONFIDENCE FORMULA (documented contract):
  confidence = min(0.95, max(fired rule strengths)
                       + 0.05 * n_corroborations)
  where n_corroborations = |claim capabilities ∩ feature capabilities|.
  Rule-strength tiers: exact-signal 0.9 (crypto imports, go markers, dynamic
  intent, decrypt/decode intent), structural 0.7-0.8 (machine, overlay,
  syscall/iat/go intent), weak 0.6 (entropy alone, density+packer).
  Fallback (no rule fired): tools/tool-search.py --capability static:disasm
  subprocess (deterministic), confidence fixed at 0.4.

Output: JSON {recommendation: {chain, confidence, alternatives}, rationale}
or text. chain = concrete index tool names resolved per capability (same
prefix semantics as tool-search); capabilities with no registered tool stay
as capability queries. --list-recipes catalogs tools/pipelines/recipes/*.yaml
(templates for plan generation, not executed here).

Exit codes: 0 ok / 2 usage / 3 missing inputs.

Usage:
  python scripts/route_capability.py --features-file probe.json --json
  python scripts/route_capability.py --features '{"machine":"AMD64"}' \
      --claim-text "decrypt" --json
  python scripts/route_capability.py --claim C-1 --workspace ws --json
  python scripts/route_capability.py --list-recipes --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

CONFIDENCE_CAP = 0.95
CORROBORATION_BONUS = 0.05
FALLBACK_CONFIDENCE = 0.4
FALLBACK_GUESS = "static:disasm"

ENTROPY_CRYPTO = 6.5
DENSITY_PACKER = 0.5
MACHINE_STATIC = {"i386", "amd64", "0x14c", "0x8664"}
CRYPTO_IMPORT_HINTS = ("crypt32", "bcrypt", "advapi")
PACKER_MARKERS = ("upx", "aspack", "pecompact", "mpress", "themida",
                  "vmprotect")
GO_MARKER_SUBSTR = "go.buildinfo"
GO_RUNTIME_PREFIX = "runtime."

# claim-intent keyword → (capability, strength). Dict order = firing order.
CLAIM_KEYWORDS = {
    "decrypt": ("crypto:decode", 0.9),
    "decode": ("crypto:decode", 0.9),
    "unpack": ("static:overlay", 0.7),
    "syscall": ("dynamic:syscall", 0.8),
    "iat": ("static:disasm-check", 0.8),
    "go": ("languages:go", 0.8),
}
DYNAMIC_INTENT = ("vm", "run", "execute", "detonate")

DEFAULT_INDEX = Path(__file__).resolve().parent.parent / "tools" / "_INDEX.yaml"
DEFAULT_RECIPES_DIR = Path(__file__).resolve().parent.parent / "tools" / \
    "pipelines" / "recipes"
DEFAULT_TOOL_SEARCH = Path(__file__).resolve().parent.parent / "tools" / \
    "tool-search.py"


def load_index(index_path: Path) -> list[dict]:
    """Load tools/_INDEX.yaml → list of raw entries (order preserved)."""
    data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    tools = data.get("tools") if isinstance(data, dict) else None
    return tools if isinstance(tools, list) else []


def capability_matches(capability: str, query: str) -> bool:
    """Exact or prefix match on the capability tag (tool-search semantics)."""
    return capability == query or capability.startswith(query)


def resolve_capability(query: str, tools: list[dict]) -> list[str]:
    """Concrete tool names for a capability; the query itself when unregistered."""
    names = [t.get("name") for t in tools
             if t.get("name")
             and capability_matches(str(t.get("capability", "")), query)]
    return names or [query]


def _dedupe(hits: list[tuple[str, float, str]]) -> list[tuple[str, float, str]]:
    """One entry per capability: max strength, first rule's reason."""
    best: dict[str, list] = {}
    order: list[str] = []
    for cap, strength, reason in hits:
        if cap not in best:
            best[cap] = [strength, reason]
            order.append(cap)
        elif strength > best[cap][0]:
            best[cap][0] = strength
    return [(cap, best[cap][0], best[cap][1]) for cap in order]


def feature_hits(features: dict) -> list[tuple[str, float, str]]:
    """Fire deterministic feature→capability rules over feature_probe output."""
    hits: list[tuple[str, float, str]] = []
    machine = str(features.get("machine", "") or "").lower()
    if machine in MACHINE_STATIC:
        hits.append(("static:disasm-check", 0.7,
                     f"machine {features.get('machine')} → "
                     "x86/x64 static disasm family"))
    if features.get("overlay"):
        hits.append(("static:overlay", 0.7,
                     "overlay bytes detected → static:overlay"))
    entropy = float(features.get("entropy") or 0.0)
    if entropy >= ENTROPY_CRYPTO:
        hits.append(("crypto:decode", 0.6,
                     f"high entropy {entropy:.2f} >= {ENTROPY_CRYPTO} → "
                     "crypto:decode (weak)"))
    hints = [str(h).lower() for h in (features.get("import_hints") or [])]
    crypto_marks = [h for h in hints if any(m in h for m in CRYPTO_IMPORT_HINTS)]
    if crypto_marks:
        hits.append(("crypto:decode", 0.9,
                     f"crypto import hints {crypto_marks[:3]} → crypto:decode"))
    density = float(features.get("string_density") or 0.0)
    packer_marks = [h for h in hints if any(m in h for m in PACKER_MARKERS)]
    if density >= DENSITY_PACKER and packer_marks:
        hits.append(("anti-analysis", 0.6,
                     f"string_density {density:.2f} + packer markers "
                     f"{packer_marks[:3]} → anti-analysis"))
    go_marks = [h for h in hints
                if GO_MARKER_SUBSTR in h or h.startswith(GO_RUNTIME_PREFIX)]
    if go_marks:
        hits.append(("languages:go", 0.9,
                     f"go markers {go_marks[:3]} → languages:go"))
    return hits


def _kw_hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = (text or "").lower()
    return [k for k in keywords if re.search(rf"\b{re.escape(k)}\b", lowered)]


def claim_hits(text: str) -> list[tuple[str, float, str]]:
    """Claim-intent overlay: keyword → capability refinement hits."""
    hits: list[tuple[str, float, str]] = []
    for kw, (cap, strength) in CLAIM_KEYWORDS.items():
        if _kw_hits(text, (kw,)):
            hits.append((cap, strength, f"claim-intent: '{kw}' → {cap}"))
    for kw in _kw_hits(text, DYNAMIC_INTENT):
        hits.append(("dynamic:run", 0.9,
                     f"claim-intent: dynamic keyword '{kw}' → dynamic:run"))
        break
    return _dedupe(hits)


def _fallback() -> dict:
    """No rule fired: deterministic tool-search subprocess, confidence 0.4."""
    rationale = ["no feature/claim rule fired",
                 f"tool-search fallback: --capability {FALLBACK_GUESS}"]
    try:
        proc = subprocess.run(
            [sys.executable, str(DEFAULT_TOOL_SEARCH), "--capability",
             FALLBACK_GUESS, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        names = ([t.get("name") for t in
                  json.loads(proc.stdout).get("tools", [])]
                 if proc.returncode == 0 and proc.stdout else [])
        chain = [n for n in names if n] or [FALLBACK_GUESS]
        rationale.append(f"tool-search → {len(chain)} tool(s)")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        chain = [FALLBACK_GUESS]
        rationale.append(f"tool-search unavailable: {exc}")
    return {"recommendation": {"chain": chain,
                               "confidence": FALLBACK_CONFIDENCE,
                               "alternatives": []},
            "rationale": rationale}


def route(features: dict, claim_text: str, index_path: Path) -> dict:
    """Deterministic routing: feature rules + claim overlay → recommendation."""
    tools = load_index(index_path)
    fhits = feature_hits(features or {})
    chits = claim_hits(claim_text)
    all_hits = fhits + chits
    if not all_hits:
        return _fallback()

    corroborations = len({c for c, _, _ in fhits} & {c for c, _, _ in chits})
    top = max(s for _, s, _ in all_hits)
    confidence = round(min(CONFIDENCE_CAP,
                           top + CORROBORATION_BONUS * corroborations), 2)

    chain: list[str] = []
    seen: set[str] = set()
    for cap, _, _ in all_hits:
        for entry in resolve_capability(cap, tools):
            if entry not in seen:
                seen.add(entry)
                chain.append(entry)
    alternatives: list[str] = []
    for cap, strength, _ in all_hits:
        if strength >= top:
            continue
        for entry in resolve_capability(cap, tools):
            if entry not in seen and entry not in alternatives:
                alternatives.append(entry)

    rationale = [reason for _, _, reason in all_hits]
    if corroborations:
        rationale.append(f"claim-intent corroborates feature rules "
                         f"x{corroborations} "
                         f"(+{CORROBORATION_BONUS * corroborations:.2f})")
    return {"recommendation": {"chain": chain, "confidence": confidence,
                               "alternatives": alternatives},
            "rationale": rationale}


def load_recipes(recipes_dir: Path) -> list[dict]:
    """Catalog recipes: {id, title, description} per yaml, sorted by name."""
    recipes = []
    for p in sorted(recipes_dir.glob("*.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        recipes.append({"id": data.get("id", p.stem),
                        "title": data.get("title", ""),
                        "description": data.get("description", "")})
    return recipes


def format_text(result: dict) -> str:
    rec = result["recommendation"]
    lines = [f"recommendation: chain=[{', '.join(rec['chain'])}] "
             f"confidence={rec['confidence']:.2f}"]
    if rec["alternatives"]:
        lines.append(f"alternatives: [{', '.join(rec['alternatives'])}]")
    lines.append("rationale:")
    lines.extend(f"  - {r}" for r in result["rationale"])
    return "\n".join(lines)


def _resolve_ws(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    cwd = Path.cwd()
    sub = cwd / "malware-analysis-workspace"
    return sub if (sub / "claim-register.yaml").exists() else cwd


def _register_path(args: argparse.Namespace) -> Path:
    if args.register:
        return Path(args.register)
    return _resolve_ws(args.workspace) / "claim-register.yaml"


def _load_claim_text(args: argparse.Namespace) -> str:
    if not args.claim:
        return args.claim_text or ""
    reg_path = _register_path(args)
    if not reg_path.is_file():
        print(f"error: claim register not found: {reg_path}", file=sys.stderr)
        return None  # type: ignore[return-value]
    try:
        reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"error: cannot read register {reg_path}: {exc}", file=sys.stderr)
        return None  # type: ignore[return-value]
    claims = reg.get("claims") if isinstance(reg, dict) else None
    claims = claims if isinstance(claims, list) else []
    for c in claims:
        if c.get("id") == args.claim:
            return c.get("statement", "") or ""
    print(f"error: claim {args.claim!r} not found in {reg_path}",
          file=sys.stderr)
    return None  # type: ignore[return-value]


def _load_features(args: argparse.Namespace):
    if args.features_file:
        p = Path(args.features_file)
        if not p.is_file():
            print(f"error: features file not found: {p}", file=sys.stderr)
            return None, 3
        try:
            features = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"error: cannot parse {p}: {exc}", file=sys.stderr)
            return None, 2
    else:
        try:
            features = json.loads(args.features)
        except ValueError as exc:
            print(f"error: invalid --features JSON: {exc}", file=sys.stderr)
            return None, 2
    if not isinstance(features, dict):
        print("error: --features must be a JSON object", file=sys.stderr)
        return None, 2
    return features, 0


def _list_recipes(args: argparse.Namespace) -> int:
    recipes_dir = Path(args.recipes_dir) if args.recipes_dir \
        else DEFAULT_RECIPES_DIR
    if not recipes_dir.is_dir():
        print(f"error: recipes dir not found: {recipes_dir}", file=sys.stderr)
        return 3
    try:
        recipes = load_recipes(recipes_dir)
    except (OSError, yaml.YAMLError) as exc:
        print(f"error: cannot read recipes in {recipes_dir}: {exc}",
              file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps({"count": len(recipes), "recipes": recipes},
                         ensure_ascii=False, indent=2))
    else:
        print(f"{len(recipes)} plan recipes:")
        for rec in recipes:
            print(f"  {rec['id']} — {rec['title']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="deterministic feature→capability router "
                    "(issue #278 P4-b)")
    ap.add_argument("--features-file", default=None,
                    help="feature_probe.py --json output file (canonical)")
    ap.add_argument("--features", default=None,
                    help="inline feature_probe JSON (injectable)")
    claim_group = ap.add_mutually_exclusive_group()
    claim_group.add_argument("--claim", default=None,
                             help="claim id; statement read from the register")
    claim_group.add_argument("--claim-text", default=None,
                             help="freeform claim intent text")
    ap.add_argument("--register", default=None,
                    help="claim-register.yaml path (default: "
                         "--workspace/claim-register.yaml)")
    ap.add_argument("--workspace", default=None,
                    help="workspace for state reads (default: "
                         "$PWD/malware-analysis-workspace or $PWD)")
    ap.add_argument("--index", default=None,
                    help="tool index yaml (default: tools/_INDEX.yaml)")
    ap.add_argument("--list-recipes", action="store_true",
                    help="catalog tools/pipelines/recipes/*.yaml instead of "
                         "routing")
    ap.add_argument("--recipes-dir", default=None,
                    help="recipes dir override (with --list-recipes)")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of text lines")
    args = ap.parse_args(argv)

    if args.list_recipes:
        return _list_recipes(args)
    if not args.features_file and not args.features:
        print("error: --features-file or --features required "
              "(or --list-recipes)", file=sys.stderr)
        return 2

    features, code = _load_features(args)
    if features is None:
        return code
    claim_text = _load_claim_text(args)
    if claim_text is None:
        return 3

    index_path = Path(args.index) if args.index else DEFAULT_INDEX
    if not index_path.is_file():
        print(f"error: index file not found: {index_path}", file=sys.stderr)
        return 3
    try:
        result = route(features, claim_text, index_path)
    except (OSError, yaml.YAMLError) as exc:
        print(f"error: cannot read index {index_path}: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
