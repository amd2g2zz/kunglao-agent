#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_manifest.py — deployment manifest single source (#783).

Builds/verifies the manifest of framework files that init deploys INTO the
workspace and upgrade refreshes (overwrite semantics):

  <manifest> entries: {src, dest, kind}    kind ∈ hook | agent | scaffold

The `scaffold` set is NOT hand-maintained: it is the TRANSITIVE import
closure of everything the deployed hooks need from scripts/, computed here
by an AST walk to a fixpoint — correct-by-construction instead of a drifting
hand list.

CLI:
  python scripts/deploy_manifest.py --write     # regenerate + fill sha256
  python scripts/deploy_manifest.py --verify    # rc0 when sha all match
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "deploy-manifest.yaml"
SKILL_SCRIPTS = ROOT / "scripts"
IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.MULTILINE)

# #810: dynamic run-by-path references (`_run_py([str(root / 'scripts' /
# <name dot py>)])`) are invisible to import-AST closure. Scan
# BOTH source trees for the literal `scripts/<name>.py` string forms and
# treat them as first-class deployment obligations (validation face — the
# manifest itself is now a full mirror, so this set must be a subset).
_DYNAMIC_REF_RE = re.compile(
    r"['\"]scripts/([A-Za-z0-9_.-]+\.py)['\"]"          # plain-slash form
    r"|['\"]scripts['\"]\s*/\s*['\"]([A-Za-z0-9_.-]+\.py)['\"]")  # /-chain form

# #810: non-code assets materialize with hooks/agents (full mirror).
_ASSET_DIRS = ("references", "templates", "tools")


def _iter_asset_files():
    for d in _ASSET_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                yield d, p


def dynamic_script_refs() -> set:
    """`scripts/<name>.py` literal path references across hooks/ + scripts/
    source trees — the class #783's import-AST closure could not see."""
    out: set = set()
    for base in (ROOT / "hooks", SKILL_SCRIPTS):
        for p in base.glob("*.py"):
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in _DYNAMIC_REF_RE.finditer(src):
                name = m.group(1) or m.group(2)
                if name:
                    out.add(f"scripts/{name}")
    return out


def closure_validation(entries) -> list:
    """#810 validation face (was the trimming basis — now gate only):
    every dynamically-referenced scripts/<name>.py must be in the deployed
    set. Returns human-readable missing lines (empty = green)."""
    srcs = {str(e.get("src", "")) for e in entries}
    missing = []
    for ref in sorted(dynamic_script_refs()):
        if ref not in srcs:
            missing.append(
                f"{ref}: dynamically referenced (hooks/scripts source scan) "
                f"but absent from the deployment manifest")
    return missing


def _sha(p: Path) -> str:
    # Normalize newlines before hashing: CI checks out LF while Windows
    # working trees are often CRLF; byte-exact hashing would flag every
    # entry stale across environments.
    data = p.read_bytes()
    CRLF = bytes((13, 10))
    CR = bytes((13,))
    LF = bytes((10,))
    if CR in data:
        data = data.replace(CRLF, LF).replace(CR, LF)
    return hashlib.sha256(data).hexdigest()

def _module_imports(py: Path) -> set[str]:
    src = py.read_text(encoding="utf-8", errors="replace")
    return {m.group(1) for m in IMPORT_RE.finditer(src)}


def scaffold_closure() -> list[str]:
    """Transitive scripts/ dependency closure of the hooks directory."""
    available = {p.stem: p for p in SKILL_SCRIPTS.glob("*.py")}
    seen: dict[str, Path] = {}
    frontier: list[str] = []
    for h in sorted((ROOT / "hooks").glob("*.py")):
        frontier.extend(_module_imports(h))
    while frontier:
        name = frontier.pop()
        if name in seen or name not in available:
            continue
        seen[name] = available[name]
        frontier.extend(_module_imports(available[name]))
    return sorted(seen)


def build_entries() -> list[dict]:
    """#810 FULL MIRROR: hooks + agents + ALL scripts/*.py + data assets
    (references/ templates/ tools/). The import-AST closure is no longer
    the trimming basis (it was blind to dynamic path calls, scripts-to-
    scripts chains and non-code assets — the live-run sample 15/30 REJECT root).
    Trimming is forbidden; `closure_validation` keeps the dynamic-reference
    scan as a gate-only validation face."""
    ents: list[dict] = []
    for p in sorted((ROOT / "hooks").glob("*.py")):
        ents.append({"src": f"hooks/{p.name}", "kind": "hook"})
    for p in sorted((ROOT / "agents").glob("*.md")):
        ents.append({"src": f"agents/{p.name}", "kind": "agent"})
    for p in sorted(SKILL_SCRIPTS.glob("*.py")):
        ents.append({"src": f"scripts/{p.name}", "kind": "scaffold"})
    # #420 (package README, Phase-2 execution notes): the rlvr package
    # modules join the deployed tree — the flat glob above predates the
    # package; without these rows the deployed scaffold lacks
    # rlvr/q_cells.py and the #429 dispatch-gate recorder's lazy import
    # can never resolve outside the repo (#429 §4).
    for p in sorted(SKILL_SCRIPTS.glob("rlvr/*.py")):
        ents.append({"src": f"scripts/rlvr/{p.name}", "kind": "scaffold"})
    # #142: the statusline renderer rides the deployed scaffold like the
    # scripts it reads — statusLine commands point at the workspace-local
    # copy (<ws>/.claude/scripts/), so the workspace stays self-contained.
    for p in sorted(SKILL_SCRIPTS.glob("*.mjs")):
        ents.append({"src": f"scripts/{p.name}", "kind": "scaffold"})
    # #432: scripts/*.yaml are RUNTIME DATA the deployed scripts read —
    # method_families.yaml is the fail-closed vocabulary registry the
    # dispatch gate validates against (unmirrored => every deployed
    # dispatch REJECTs); mechanisms.yaml / tool_tiers.yaml are the same
    # class (read by deployed mechanism_scheduler / tool_tiers). The
    # #810 full-mirror rationale extends verbatim: data assets belong to
    # the mirror, trimming is forbidden.
    for p in sorted(SKILL_SCRIPTS.glob("*.yaml")):
        ents.append({"src": f"scripts/{p.name}", "kind": "scaffold"})
    for d, p in _iter_asset_files():
        ents.append({"src": f"{d}/{p.relative_to(ROOT / d).as_posix()}",
                     "kind": "asset"})
    for e in ents:
        parts = e["src"].split("/", 1)
        e["dest"] = f".claude/{parts[0]}/{parts[1]}"
        e["sha256"] = _sha(ROOT / e["src"])
    return ents


# ---------------------------------------------------------------------------
# #783 T5: deployed-manifest carrier + drift check
# ---------------------------------------------------------------------------

CARRIER_REL = ".claude/deployed-manifest.json"


def load_manifest_entries() -> list[dict]:
    """The committed deploy-manifest.yaml entries (the audited D1 contract).
    Raises when the manifest is unreadable — a silently empty entry set would
    stamp a lying carrier."""
    import yaml
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    return list(data.get("files") or [])


def manifest_digest(entries: list[dict]) -> str:
    """THE #783 T5 digest algorithm — sha256 over the dest+sha256 entry
    pairs concatenated in dest-sorted order. Single source: every consumer
    (deploy_workspace_copy, deployed_refresh, check-stale) calls THIS, so
    the workspace carrier, the skill-side expectation and the observed
    bytes always speak the same language. Order-independence (dest sort)
    makes the digest stable against manifest reordering."""
    h = hashlib.sha256()
    for e in sorted(entries, key=lambda x: str(x.get("dest", ""))):
        h.update(str(e.get("dest", "")).encode("utf-8"))
        h.update(str(e.get("sha256", "")).encode("utf-8"))
    return h.hexdigest()


def deployed_carrier_path(ws: Path) -> Path:
    return Path(ws) / CARRIER_REL


# ---------------------------------------------------------------------------
# update identity — source head hash (manifest digest as fallback)
# ---------------------------------------------------------------------------

def source_head(root: Path | None = None) -> str | None:
    """The SOURCE TREE's git head hash — the unique update identity of
    `kunglao upgrade`. The version string stays human-facing metadata; a
    re-cut batch can carry different content under the same version, and
    only the head hash separates the batches.

    Accepted ONLY when <root> is its OWN repo top: a plugin copy nested
    inside an unrelated host repo must not inherit the host's head (identity
    would then move on every unrelated host commit). Not-a-repo, no-commits
    and git-missing all answer None — callers fall back to the manifest
    digest, which the carrier already records.
    """
    base = Path(root) if root is not None else ROOT
    try:
        head = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace")
        top = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace")
        if head.returncode != 0 or top.returncode != 0:
            return None
        top_out = top.stdout.strip()
        if not top_out or Path(top_out).resolve() != base.resolve():
            return None
    except (OSError, ValueError):
        return None
    return head.stdout.strip() or None


def _source_version() -> str | None:
    """Human-facing metadata for the carrier: the skill version the
    deployment came from. Lazy import + fail-open — a version probe must
    never break a deployment."""
    try:
        import template_version
        return template_version.read_skill_version()
    except Exception:  # noqa: BLE001 — metadata only
        return None


def write_carrier(ws: Path, entries: list[dict]) -> dict:
    """Stamp the deployment carrier recording what was just written into
    <ws>/.claude/ (both writer faces: deploy_workspace_copy at init,
    deployed_refresh at upgrade). #810: dests list added so the activation
    completeness face can verify the deployed surface without the manifest.
    source_head + source_version added — the update identity (git head of
    the executing source tree; None on non-git installs, where the digest
    carries identity) plus the version kept as human metadata."""
    import time
    carrier = {
        "schema_version": 3,
        "deployed_digest": manifest_digest(entries),
        "source_head": source_head(),
        "source_version": _source_version(),
        "entries": len(entries),
        "dests": sorted(str(e.get("dest", "")) for e in entries),
        "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = deployed_carrier_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(carrier, indent=2) + "\n", encoding="utf-8")
    return carrier


def observed_workspace_digest(ws: Path, entries: list[dict]) -> str | None:
    """Digest over the workspace's ACTUAL deployed bytes for the manifest
    dest set (newline-normalized like the manifest shas). Returns None when
    any declared dest is missing — a hole is drift by definition."""
    seen: list[dict] = []
    for e in entries:
        f = Path(ws) / str(e["dest"])
        if not f.is_file():
            return None
        seen.append({"dest": e["dest"], "sha256": _sha(f)})
    return manifest_digest(seen)


def deploy_drift(ws: Path) -> dict:
    """#783 T5 three-leg drift check for a copies-present workspace.

    Legs (all must hold for 'current'):
      carrier-present — <ws>/.claude/deployed-manifest.json exists and
                        parses (pre-T5 deploys and hand-deletions land here);
      carrier-fresh   — carrier digest == current manifest digest (catches
                        same-version skill-content moves);
      bytes-fresh     — digest recomputed over the workspace's deployed
                        files == current manifest digest (catches hand
                        tampering; makes the T6 tamper e2e observable).

    Returns {"drift": bool, "reason": str|None, "observed": str|None,
             "expected": str, "carrier_digest": str|None}. Callers gate on
    `<ws>/.claude/hooks` being a directory BEFORE calling (legacy
    workspaces without deployed copies never enter this criterion).
    """
    expected = manifest_digest(build_entries())
    out: dict = {"drift": False, "reason": None, "observed": None,
                 "expected": expected, "carrier_digest": None}
    path = deployed_carrier_path(ws)
    carrier_digest = None
    if path.is_file():
        try:
            carrier_digest = str(json.loads(
                path.read_text(encoding="utf-8")).get("deployed_digest"))
        except (json.JSONDecodeError, OSError):
            carrier_digest = None
    if carrier_digest is None:
        out.update(drift=True, reason="carrier-missing")
        return out
    out["carrier_digest"] = carrier_digest
    if carrier_digest != expected:
        out.update(drift=True, reason="carrier-stale")
        return out
    observed = observed_workspace_digest(ws, build_entries())
    out["observed"] = observed
    if observed is None:
        out.update(drift=True, reason="copy-missing")
        return out
    if observed != expected:
        out.update(drift=True, reason="copy-drift")
    return out


def identity_status(ws: Path) -> dict:
    """The update identity — workspace-recorded vs source-current.

    Identity precedence: the git head hash on BOTH sides when both are
    available (the primary basis); otherwise the manifest digest the
    carrier already records (`deployed_digest` vs the digest recomputed
    from the executing tree — the deploy-manifest digest algorithm, the
    fallback for non-git installs and legacy carriers). The RECORDED side is the
    workspace carrier: a missing/unreadable carrier (or one without a
    digest) yields changed=True — the deploy_drift fail-towards-work
    posture, an unverifiable identity is never reported current.

    Read-only. Returns {"changed": bool, "basis": "head"|"digest"|"none",
    "recorded_head", "current_head", "recorded_digest", "current_digest"}.
    """
    current_digest = manifest_digest(build_entries())
    current_head = source_head()
    recorded_head = recorded_digest = None
    path = deployed_carrier_path(ws)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            recorded_head = str(data.get("source_head") or "") or None
            recorded_digest = str(data.get("deployed_digest") or "") or None
    if recorded_digest is None:
        changed, basis = True, "none"
    elif recorded_head and current_head:
        changed, basis = (recorded_head != current_head), "head"
    else:
        changed, basis = (recorded_digest != current_digest), "digest"
    return {"changed": changed, "basis": basis,
            "recorded_head": recorded_head, "current_head": current_head,
            "recorded_digest": recorded_digest,
            "current_digest": current_digest}


def render_yaml(entries: list[dict]) -> str:
    lines = ["schema_version: '1'", "files:"]
    for e in entries:
        lines.append(f"  - src: {e['src']}")
        lines.append(f"    dest: {e['dest']}")
        lines.append(f"    kind: {e['kind']}")
        lines.append(f"    sha256: {e['sha256']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="#783 deployment manifest single source")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true",
                   help="regenerate the manifest (fills sha256)")
    g.add_argument("--verify", action="store_true",
                   help="check every entry's sha256 against the tree")
    args = ap.parse_args(argv)

    if args.write:
        entries = build_entries()
        MANIFEST.write_text(render_yaml(entries), encoding="utf-8")
        total = sum((ROOT / e["src"]).stat().st_size for e in entries)
        print(f"OK: wrote {MANIFEST.name} ({len(entries)} entries, "
              f"{total} bytes deployed surface)")  # #810 P2 size audit
        return 0

    text = MANIFEST.read_text(encoding="utf-8")
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: manifest unreadable: {exc}", file=sys.stderr)
        return 1
    bad = []
    for e in data.get("files") or []:
        p = ROOT / str(e["src"])
        if not p.is_file() or _sha(p) != e.get("sha256"):
            bad.append(e["src"])
    # #810: validation face — dynamic refs must be a subset of deployed.
    # The live-run sample REJECT was exactly this class: run-by-path scripts invisible
    # to import-AST closure, silently undeployed.
    missing_dyn = closure_validation(data.get("files") or [])
    if bad:
        print("FAIL: stale entries — run --write:", file=sys.stderr)
        print("\n".join(sorted(bad)), file=sys.stderr)
        return 1
    if missing_dyn:
        print("FAIL: dynamic script references not deployed — "
              "run --write:", file=sys.stderr)
        print("\n".join(missing_dyn), file=sys.stderr)
        return 1
    if bad:
        print("FAIL: stale entries — run --write:", file=sys.stderr)
        print("\n".join(sorted(bad)), file=sys.stderr)
        return 1
    print(f"OK: {len(data.get('files') or [])} entries verified")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
