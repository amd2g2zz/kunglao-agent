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

Output: JSON {recommendation: {chain, confidence, alternatives}, rationale,
agent_type, agent_rationale} or text. chain = concrete index tool names
resolved per capability (same prefix semantics as tool-search); capabilities
with no registered tool stay as capability queries. agent_type = recommended
specialist agent (issue #310) from the mechanical trigger table parsed out of
the `triggers:` frontmatter of agents/*.md — claim task domain x sample
features; None when no specialist fits (kunglao-worker allowed).

Exit codes: 0 ok / 2 usage / 3 missing inputs.

Usage:
  python scripts/route_capability.py --features-file probe.json --json
  python scripts/route_capability.py --features '{"machine":"AMD64"}' \
      --claim-text "decrypt" --json
  python scripts/route_capability.py --claim C-1 --workspace ws --json
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
DEFAULT_TOOL_SEARCH = Path(__file__).resolve().parent.parent / "tools" / \
    "tool-search.py"
DEFAULT_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)


def load_index(index_path: Path) -> list[dict]:
    """Load tools/_INDEX.yaml → list of raw entries (order preserved)."""
    data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    tools = data.get("tools") if isinstance(data, dict) else None
    return tools if isinstance(tools, list) else []


# ---------- issue #310: specialist trigger table (parsed from agents/*.md) ----------
# The mechanical table lives in the `triggers:` frontmatter of each
# agents/*.md definition — the agent LIST is the agents/ directory listing
# itself, so the table can never drift from the installed agents.
# Entry shape:
#   triggers:
#     pipeline_order: 4          # lower wins when several specialists fit
#     intent:                    # matched against the claim statement text
#       must_any: [regex, ...]   # any match (re.IGNORECASE) ...
#       exclude: [regex, ...]    # ... AND no exclude match
#     features:                  # matched against feature_probe output
#       language: {any_of: [Go]}
#       import_hints: {any_contains: [go.buildinfo]}


def _parse_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def load_specialist_table(agents_dir: Path | None = None) -> list[dict]:
    """Mechanical specialist trigger table from agents/*.md `triggers:` blocks."""
    agents_dir = Path(agents_dir) if agents_dir else DEFAULT_AGENTS_DIR
    out: list[dict] = []
    if not agents_dir.is_dir():
        return out
    for p in sorted(agents_dir.glob("*.md")):
        fm = _parse_frontmatter(p)
        name = fm.get("name")
        triggers = fm.get("triggers")
        if not name or not isinstance(triggers, dict):
            continue
        order = triggers.get("pipeline_order")
        out.append({
            "name": name,
            "pipeline_order": order if isinstance(order, int) else 99,
            "intent": triggers.get("intent") or {},
            "features": triggers.get("features") or {},
        })
    return out


def _re_any(patterns, text: str) -> bool:
    if not patterns or not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def intent_matches(entry: dict, claim_text: str) -> bool:
    """True iff a must_any intent regex matches and no exclude regex matches."""
    intent = entry.get("intent") or {}
    if not _re_any(intent.get("must_any"), claim_text):
        return False
    return not _re_any(intent.get("exclude"), claim_text)


def _feature_value_matches(features: dict, key: str, cond: dict) -> bool:
    if key not in features:
        return False
    val = features[key]
    vals = val if isinstance(val, list) else [val]
    any_of = cond.get("any_of") or []
    if any_of:
        wanted = {str(a).strip().lower() for a in any_of}
        if any(str(v).strip().lower() in wanted for v in vals):
            return True
    any_contains = cond.get("any_contains") or []
    if any_contains:
        subs = [str(s).lower() for s in any_contains]
        for v in vals:
            sv = str(v).lower()
            if any(s in sv for s in subs):
                return True
    return False


def feature_matches(entry: dict, features: dict) -> bool:
    """True iff ANY feature condition key matches (alternatives, not conjunction)."""
    conds = entry.get("features") or {}
    if not conds or not features:
        return False
    for key, cond in conds.items():
        if isinstance(cond, dict) and _feature_value_matches(features, key, cond):
            return True
    return False


def recommend_agent_type(features: dict, claim_text: str,
                         specialists: list[dict]) -> tuple[str | None, list[str]]:
    """Deterministic specialist recommendation: the first specialist in
    pipeline_order whose intent matches the claim text (no exclude) OR whose
    feature conditions match. Returns (name | None, rationale lines);
    None means no specialist fits — kunglao-worker is allowed."""
    ordered = sorted(specialists, key=lambda s: s.get("pipeline_order", 99))
    for s in ordered:
        im = intent_matches(s, claim_text or "")
        fm = feature_matches(s, features or {})
        if im or fm:
            reasons = []
            if im:
                reasons.append(f"claim-intent matches {s['name']} trigger "
                               "(must_any hit, no exclude)")
            if fm:
                reasons.append(f"sample features match {s['name']} trigger")
            reasons.append(f"pipeline_order={s['pipeline_order']}")
            return s["name"], reasons
    return None, ["no specialist trigger matched — kunglao-worker allowed"]


def capability_matches(capability: str, query: str) -> bool:
    """Exact or prefix match on the capability tag (tool-search semantics)."""
    return capability == query or capability.startswith(query)


def resolve_capability(query: str, tools: list[dict]) -> list[str]:
    """Concrete tool names for a capability; the query itself when unregistered."""
    names = [t.get("name") for t in tools
             if t.get("name")
             and capability_matches(str(t.get("capability", "")), query)]
    return names or [query]


# ---------- issue #692 WP3: provider selection (design D3/D4) ----------

QUALITY_ORDER = {"high": 0, "mid": 1, "floor": 2}
MEM_GATE_JADX_OK = ("jadx-ok", "targeted-jadx")   # #670 verdicts that satisfy jadx
DEX_EXTS = (".apk", ".dex")


def _provider_health_mod():
    """Sibling import (tests load this module by file path)."""
    try:
        import provider_health  # noqa: PLC0415
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import provider_health  # noqa: PLC0415
    return provider_health


def _has_java_tree(ev: Path) -> bool:
    """Bounded walk (<=60 dirs, depth 3): any *.java under evidence/."""
    if not ev.is_dir():
        return False
    scanned = 0
    stack = [(ev, 0)]
    while stack and scanned < 60:
        d, depth = stack.pop()
        scanned += 1
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        if any(f.suffix == ".java" for f in entries if f.is_file()):
            return True
        if depth < 3:
            stack.extend((f, depth + 1) for f in entries if f.is_dir())
    return False


def _valid_gitnexus_marker(path: Path) -> bool:
    """#692 WP7: the lazy-index marker is SCHEMA-VALIDATED, not
    existence-checked - {source_root, indexed_at, tools} all present.
    A garbage or key-less file must not fake an index (stale markers
    stay blocked)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return all(k in data for k in ("source_root", "indexed_at", "tools"))


def load_workspace_state(ws) -> dict:
    """Files-only workspace state for provider selection (design D2).

    NEVER runs environment probes (import/which) - a token without a
    workspace-state answer stays `unverified` downstream, never blocked.
    """
    ev = Path(ws) / "evidence"
    state: dict = {
        "mem_gate_verdict": None,
        "tool_probes": {},
        "source_tree": False,
        "gitnexus_index": False,
        "target_ext": None,
    }
    try:
        mg = json.loads((ev / "apk_mem_gate.json").read_text(
            encoding="utf-8"))
        state["mem_gate_verdict"] = (mg.get("verdict")
                                     if isinstance(mg, dict) else None)
    except (OSError, ValueError):
        pass
    try:
        probes = json.loads((ev / "tool-probes.json").read_text(
            encoding="utf-8"))
        if isinstance(probes, dict):
            state["tool_probes"] = probes
    except (OSError, ValueError):
        pass
    state["gitnexus_index"] = _valid_gitnexus_marker(
        ev / "gitnexus_index.json")
    # #692 WP6: apkid obfuscator rules (the deobf COMPOSITION prior)
    try:
        apkid = json.loads((ev / "apkid.json").read_text(encoding="utf-8"))
        summary = apkid.get("summary") if isinstance(apkid, dict) else None
        rules = (summary or {}).get("obfuscator") if isinstance(
            summary, dict) else None
        state["apkid_obfuscators"] = [str(r) for r in (rules or [])]
    except (OSError, ValueError):
        state["apkid_obfuscators"] = []
    state["source_tree"] = (state["gitnexus_index"]
                            or _has_java_tree(ev))
    try:
        state["provider_failures"] = _provider_health_mod() \
            .recent_failures(Path(ws))
    except Exception:  # noqa: BLE001 - fail-open: no memory, no crash
        state["provider_failures"] = {}
    return state


def _eval_token(token: str, state: dict) -> tuple[str, str | None]:
    """("ok", None) | ("blocked", reason) | ("unverified", reason).

    The evaluator is TOLERANT (any registry data must resolve); the closed
    vocabulary is enforced at LINT time by tools/validate_index.py.
    """
    if token == "dex":
        ext = state.get("target_ext")
        if ext is None:
            return "ok", None  # target shape unknown: do not block
        if str(ext).lower() in DEX_EXTS:
            return "ok", None
        return "blocked", "target %s is not dex" % ext
    if token == "mem_budget_ok":
        verdict = state.get("mem_gate_verdict")
        if verdict is None:
            return ("unverified",
                    "mem_budget_ok: no apk_mem_gate verdict yet")
        if verdict in MEM_GATE_JADX_OK:
            return "ok", None
        return ("blocked",
                "mem budget verdict %s (#670 - jadx provider precondition, "
                "not a pipeline stage)" % verdict)
    if token in ("jadx_bin", "dexdc_wheel", "smali_toolchain"):
        probes = state.get("tool_probes") or {}
        if token not in probes:
            return ("unverified",
                    "%s: no tool-probes evidence" % token)
        if probes[token]:
            return "ok", None
        return "blocked", "%s: probe failed" % token
    if token == "source_tree":
        if state.get("source_tree"):
            return "ok", None
        return ("blocked",
                "no decompiled source tree under evidence/")
    if token == "gitnexus_index":
        if state.get("gitnexus_index"):
            return "ok", None
        return ("blocked",
                "needs lazy index build (marker "
                "evidence/gitnexus_index.json absent)")
    return "unverified", "%s: unknown token (tolerant evaluator)" % token


def select_providers(capability: str, tools: list[dict],
                     state: dict) -> dict:
    """Rank providers for one capability from workspace state (D3).

    quality desc -> cost_hint.mem_gb asc -> registry order; a recent
    provider-health failure (24h window) demotes below non-failed.
    Statuses: available | blocked(reason) | unverified(reason).
    Recommendation: first available, else first unverified, else None.
    """
    rows: list[tuple[dict, int]] = []
    for pos, t in enumerate(tools):
        if not t.get("provider") or capability not in (t.get("produces")
                                                       or []):
            continue
        quality = (t.get("quality") or {}).get(capability)
        entry = {
            "name": t.get("name"),
            "provider": t.get("provider"),
            "quality": quality,
            "cost": (t.get("cost_hint") or {}).get("mem_gb"),
            "status": "available",
            "recent_failure": False,
        }
        blocked = []
        unverified = []
        for token in t.get("requires") or []:
            verdict, reason = _eval_token(token, state)
            if verdict == "blocked":
                blocked.append("%s: %s" % (token, reason))
            elif verdict == "unverified":
                unverified.append("%s: %s" % (token, reason))
        blocked = "; ".join(blocked) or None
        unverified = "; ".join(unverified) or None
        if blocked is not None:
            entry["status"] = "blocked"
            entry["blocked_reason"] = blocked
        elif unverified is not None:
            entry["status"] = "unverified"
            entry["unverified_reason"] = unverified
        failure = (state.get("provider_failures") or {}).get(
            t.get("provider"))
        if failure:
            entry["recent_failure"] = True
            entry["failure_reason"] = failure.get("reason", "")
        rows.append((entry, pos))

    def _sort_key(item):
        e, pos = item
        mem = e["cost"] if isinstance(e["cost"], (int, float)) else 0.0
        return (1 if e["recent_failure"] else 0,
                QUALITY_ORDER.get(e["quality"], 9), mem, pos)

    rows.sort(key=_sort_key)
    ordered = [e for e, _ in rows]
    recommendation = next(
        (e["name"] for e in ordered if e["status"] == "available"), None)
    if recommendation is None:
        recommendation = next(
            (e["name"] for e in ordered if e["status"] == "unverified"),
            None)

    rationale = ["ranked %d provider(s) for %s: quality desc, cost asc, "
                 "registry order; recent failures demoted (24h window)"
                 % (len(ordered), capability)]
    for e in ordered:
        if e["status"] == "blocked":
            rationale.append("%s: blocked (%s)"
                             % (e["name"], e["blocked_reason"]))
        elif e["recent_failure"]:
            rationale.append("%s: recent failure demoted (%s)"
                             % (e["name"], e.get("failure_reason", "")))
        elif e["status"] == "unverified":
            rationale.append("%s: unverified (%s)"
                             % (e["name"], e["unverified_reason"]))
    return {"capability": capability, "providers": ordered,
            "recommendation": recommendation, "rationale": rationale}


def format_providers_text(result: dict) -> str:
    lines = ["capability: %s" % result["capability"],
             "recommendation: %s" % result["recommendation"]]
    for e in result["providers"]:
        mark = {"available": "OK", "blocked": "BLK",
                "unverified": "UNV"}[e["status"]]
        note = e.get("blocked_reason") or e.get("unverified_reason") or (
            "recent failure: %s" % e.get("failure_reason", "")
            if e["recent_failure"] else "")
        lines.append("  [%s] %s (quality=%s, cost=%sgb) %s"
                     % (mark, e["name"], e["quality"], e["cost"], note))
    lines.append("rationale:")
    lines.extend("  - %s" % r for r in result["rationale"])
    return "\n".join(lines)


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
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
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
            "rationale": rationale,
            "agent_type": None,
            "agent_rationale": ["no specialist trigger matched — "
                                "kunglao-worker allowed"]}


def _deobf_prior(state: dict) -> list[dict]:
    """#692 WP6 (design D8): apkid's obfuscator tag raises the PRIOR that
    the deobf capabilities will be wanted — a prior ONLY: no chain
    reordering, no stage sequence. The agent COMPOSES string_decrypt
    (emulator) + dex_rewrite (dexlib2 rename) + re-decompile + re-index per
    claim in whatever order the claim needs."""
    rules = state.get("apkid_obfuscators") or []
    if not rules:
        return []
    named = ", ".join(rules[:3])
    return [
        {"capability": "android:string-decrypt",
         "rationale": "apkid obfuscator rules [%s] raise the "
                      "string-decrypt prior (#692 WP6 - compose dexdc "
                      "emulator per claim, no fixed stage order)" % named},
        {"capability": "android:dex-rewrite",
         "rationale": "apkid obfuscator rules [%s] raise the dex-rewrite "
                      "prior (#692 WP6 - dexlib2 rename is the only "
                      "persistent form; compose per claim)" % named},
    ]


def route(features: dict, claim_text: str, index_path: Path,
          agents_dir: Path | None = None,
          ws: Path | None = None) -> dict:
    """Deterministic routing: feature rules + claim overlay → recommendation,
    plus the specialist agent_type recommendation (#310).

    #692 WP6: `ws` (optional — all pre-#692 callers omit it) adds the
    deobf composition prior (capability_suggestions) from apkid evidence.
    A prior only: chain/confidence are never altered by suggestions."""
    tools = load_index(index_path)
    fhits = feature_hits(features or {})
    chits = claim_hits(claim_text)
    all_hits = fhits + chits
    agent_type, agent_rationale = recommend_agent_type(
        features, claim_text, load_specialist_table(agents_dir))
    if not all_hits:
        result = _fallback()
        result["agent_type"] = agent_type
        result["agent_rationale"] = agent_rationale
        if ws is not None:
            suggestions = _deobf_prior(load_workspace_state(ws))
            if suggestions:
                result["capability_suggestions"] = suggestions
        return result

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
    result = {"recommendation": {"chain": chain, "confidence": confidence,
                                 "alternatives": alternatives},
              "rationale": rationale,
              "agent_type": agent_type,
              "agent_rationale": agent_rationale}
    if ws is not None:
        suggestions = _deobf_prior(load_workspace_state(ws))
        if suggestions:
            result["capability_suggestions"] = suggestions
    return result


def format_text(result: dict) -> str:
    rec = result["recommendation"]
    lines = [f"recommendation: chain=[{', '.join(rec['chain'])}] "
             f"confidence={rec['confidence']:.2f}"]
    if rec["alternatives"]:
        lines.append(f"alternatives: [{', '.join(rec['alternatives'])}]")
    if result.get("agent_type"):
        lines.append(f"agent_type: {result['agent_type']}")
    lines.append("rationale:")
    lines.extend(f"  - {r}" for r in result["rationale"])
    if result.get("agent_rationale"):
        lines.append("agent_rationale:")
        lines.extend(f"  - {r}" for r in result["agent_rationale"])
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="deterministic feature→capability router "
                    "(issue P4-b)")
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
    ap.add_argument("--agents-dir", default=None,
                    help="agents dir with specialist trigger frontmatter "
                         "(default: agents/)")
    ap.add_argument("--capability", default=None,
                    help="direct provider-selection query: rank "
                         "providers for this capability tag from "
                         "--workspace state")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of text lines")
    args = ap.parse_args(argv)

    if args.capability:
        index_path = Path(args.index) if args.index else DEFAULT_INDEX
        if not index_path.is_file():
            print("error: index file not found: %s" % index_path,
                  file=sys.stderr)
            return 3
        tools = load_index(index_path)
        state = load_workspace_state(_resolve_ws(args.workspace))
        result = select_providers(args.capability, tools, state)
        if args.json:
            print(json.dumps({"providers": result}, ensure_ascii=False,
                             indent=2))
        else:
            print(format_providers_text(result))
        return 0

    if not args.features_file and not args.features:
        print("error: --features-file or --features required", file=sys.stderr)
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
        result = route(features, claim_text, index_path,
                       Path(args.agents_dir) if args.agents_dir else None)
    except (OSError, yaml.YAMLError) as exc:
        print(f"error: cannot read index {index_path}: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
