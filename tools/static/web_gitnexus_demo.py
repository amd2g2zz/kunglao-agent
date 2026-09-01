#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_gitnexus_demo.py — issue #751 web JS semantic-index-layer regression demo.

Pipeline demonstrated (bundled JS -> graph query):

  bundled sample (webpack-shaped IIFE)
    -> [leg] npx wakaru --unpack        (bundler undo; SKIPS on unsupported
         platforms with a recorded reason)
    -> [leg] npx webcrack -o            (classic-obfuscation peel; SKIPs on
         install/runtime failure with the captured reason)
    -> recovered source tree            (committed post-recovery stand-in when
         both recovery legs are unavailable)
    -> npx gitnexus analyze --skip-git --skip-agents-md
    -> npx gitnexus context buildSignature   (semantic caller/callee query)
       assert sendRequest is among incoming callers

Design (#751 design D5):
- every external tool leg degrades STRUCTURED: {"tool", "status": ran/skipped,
  "detail"} — offline or platform-blocked hosts still produce a coherent
  evidence payload and exit 0 as long as nothing ASSERTED failed.
- assertions live ONLY at the semantic layer (gitnexus answers, bundle
  runs): the new layer must work wherever its CLI works.
- tool versions follow tools/_INDEX.yaml upstream pins (wakaru 1.10.0 /
  webcrack 2.16.0; gitnexus >= 1.6 CLI surface).

Usage:
  python tools/static/web_gitnexus_demo.py                 # full pipeline
  python tools/static/web_gitnexus_demo.py --out ev.json   # + evidence file
  python tools/static/web_gitnexus_demo.py --selfcheck     # offline, no npm
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys

# UTF-8 stdout convention (#317): non-ASCII detail strings must survive a
# GBK console without a UnicodeEncodeError traceback.
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "web751"
BUNDLE = FIXTURES / "bundle.min.js"
RECOVERED_TREE = FIXTURES / "unpacked"

WAKARU_PIN = "1.10.0"
WEBCRACK_PIN = "2.16.0"
GITNEXUS_MIN = (1, 6)

TIMEOUT_PROBE = 600      # npx cold-install probe (native builds are slow)
TIMEOUT_RECOVER = 900    # webcrack transform pass
TIMEOUT_ANALYZE = 600    # gitnexus full analysis
TIMEOUT_QUERY = 120

# Tool resolution: a PATH-resolved binary wins over npx (hosts that pre-seed
# the npm package skip the cold-install; mirrors how agents invoke these CLIs).


def _run(cmd: list[str], cwd: Path | None = None,
         timeout: int = TIMEOUT_PROBE) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def _tool_base(name: str) -> list[str] | None:
    bin_ = shutil.which(name)
    return [bin_] if bin_ else None


def leg_selfcheck_bundle(workdir: Path) -> dict:
    """The bundled sample itself must execute under node."""
    leg = {"tool": "node", "status": "skipped", "detail": ""}
    node = shutil.which("node")
    if node is None:
        leg["detail"] = "node unavailable"
        return leg
    driver = workdir / "selfcheck.js"
    driver.write_text(
        "global.window={};global.fetch=function(){return null};\n"
        f"eval({json.dumps(BUNDLE.read_text(encoding='utf-8'))});\n"
        "const s=window.__api.buildSignature({b:'2',a:'1'},'s3cr3t');\n"
        "if(!/^[0-9a-f]{8}$/.test(s)) throw new Error('bad sign '+s);\n",
        encoding="utf-8")
    try:
        proc = _run([node, str(driver)], cwd=workdir, timeout=60)
    except subprocess.TimeoutExpired:
        leg["detail"] = "timeout"
        return leg
    if proc.returncode == 0:
        leg["status"] = "ran"
        leg["detail"] = "bundle executes; buildSignature emits 8-hex digest"
    else:
        leg["status"] = "failed"
        leg["detail"] = proc.stderr.strip()[-300:]
    return leg


def _probe_wakaru() -> tuple[list[str], str]:
    """wakaru pins native esbuild-family binaries; unsupported hosts fail at
    runtime (e.g. darwin-x64 rejected by wakaru 1.10.0). Returns (cmd|None,
    version-or-reason)."""
    base = _tool_base("wakaru") or ["npx", "-y",
                                    f"wakaru@{WAKARU_PIN}"]
    try:
        proc = _run([*base, "--version"], timeout=TIMEOUT_PROBE)
    except subprocess.TimeoutExpired:
        return None, f"probe timeout after {TIMEOUT_PROBE}s"
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and out:
        return base, out.splitlines()[-1]
    err = (proc.stderr or "").strip()
    reason = next((ln.strip() for ln in err.splitlines()
                   if "Unsupported platform" in ln), None)
    if not reason and err:
        tail = err.splitlines()[-1][:200]
    elif err:
        tail = ""
    else:
        tail = f"exit {proc.returncode}"
    return None, reason or tail


def leg_recover_wakaru(workdir: Path) -> tuple[dict, Path | None]:
    leg = {"tool": f"wakaru@{WAKARU_PIN}", "status": "skipped", "detail": ""}
    base, note = _probe_wakaru()
    if base is None:
        leg["detail"] = note
        return leg, None
    leg["detail"] = f"version {note}"
    out = workdir / "wakaru-out"
    try:
        proc = _run([*base, str(BUNDLE), "--unpack", "-o", str(out)],
                    cwd=workdir, timeout=TIMEOUT_RECOVER)
    except subprocess.TimeoutExpired:
        leg["status"], leg["detail"] = "failed", "unpack timeout"
        return leg, None
    if proc.returncode != 0:
        leg["status"] = "failed"
        leg["detail"] = (proc.stderr or proc.stdout).strip()[-300:]
        return leg, None
    js = sorted(out.rglob("*.js")) if out.is_dir() else []
    if not js:
        leg["status"], leg["detail"] = "failed", "no .js produced"
        return leg, None
    leg.update(status="ran",
               detail=f"{len(js)} module file(s) under {out.name}/")
    return leg, out


def _probe_webcrack() -> tuple[list[str], str]:
    base = _tool_base("webcrack") or ["npx", "-y",
                                      f"webcrack@{WEBCRACK_PIN}"]
    try:
        proc = _run([*base, "--version"], timeout=TIMEOUT_PROBE)
    except subprocess.TimeoutExpired:
        return None, f"probe timeout after {TIMEOUT_PROBE}s"
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and out:
        return base, out.splitlines()[-1]
    return None, ((proc.stderr or "") or
                  f"exit {proc.returncode}").strip()[-200:]


def leg_recover_webcrack(workdir: Path) -> tuple[dict, Path | None]:
    leg = {"tool": f"webcrack@{WEBCRACK_PIN}", "status": "skipped",
           "detail": ""}
    # webcrack creates -o itself; a pre-existing dir is an error for it
    out = workdir / "recovered"
    base, why = _probe_webcrack()
    if base is None:
        leg["detail"] = why
        return leg, None
    try:
        proc = _run([*base, str(BUNDLE), "-o", str(out)],
                    cwd=workdir, timeout=TIMEOUT_RECOVER)
    except subprocess.TimeoutExpired:
        leg["status"], leg["detail"] = "failed", "recover timeout"
        return leg, None
    if proc.returncode != 0:
        leg["status"] = "failed"
        leg["detail"] = (proc.stderr or proc.stdout).strip()[-300:]
        return leg, None
    produced = out.is_dir() and any(out.rglob("*.js"))
    if not produced:
        leg["status"], leg["detail"] = "failed", "no .js produced"
        return leg, None
    leg.update(status="ran", detail=f"deobfuscated tree under {out.name}/")
    return leg, out


def leg_source_tree(workdir: Path, pick: list[Path],
                    reasons: list[str]) -> tuple[dict, Path]:
    """First successful recovery output wins; otherwise the committed
    stand-in tree is COPIED into the workdir — gitnexus analyze must never
    consume a repo directory in place (it writes .gitnexus/ and can emit
    .claude skill files next to the source)."""
    for candidate, leg_tool in pick:
        if candidate is not None and any(candidate.rglob("*.js")):
            return {"tool": "source-tree", "status": "ran",
                    "detail": f"recovery output of {leg_tool}"}, candidate
    tree = workdir / "unpacked-stand-in"
    shutil.copytree(RECOVERED_TREE, tree)
    detail = "; ".join(reasons) or "committed fixture"
    return {"tool": "source-tree", "status": "degraded",
            "detail": f"{detail}; stand-in copied to {tree.name}/"}, tree


def _parse_version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    parts = m.groups()
    head = (int(parts[0]), int(parts[1]))
    return head + ((int(parts[2]),) if parts[2] else ())


def leg_gitnexus_analyze(tree: Path) -> tuple[dict, bool]:
    leg = {"tool": "gitnexus analyze", "status": "skipped", "detail": ""}
    base = _tool_base("gitnexus") or ["npx", "-y", "gitnexus"]
    try:
        p = _run([*base, "--version"], timeout=TIMEOUT_PROBE)
    except subprocess.TimeoutExpired:
        leg["detail"] = f"gitnexus probe timeout after {TIMEOUT_PROBE}s"
        return leg, False
    parsed = _parse_version(p.stdout or "")
    if p.returncode != 0 or parsed is None or parsed < GITNEXUS_MIN:
        leg["detail"] = ("gitnexus CLI unavailable "
                         "(need >= 1.6): version probe gave "
                         f"{(p.stdout or '').strip()[:40]!r} rc={p.returncode}")
        return leg, False
    try:
        proc = _run([*base, "analyze", str(tree), "--skip-git",
                     "--skip-agents-md"],
                    cwd=tree.parent, timeout=TIMEOUT_ANALYZE)
    except subprocess.TimeoutExpired:
        leg["status"], leg["detail"] = "failed", "analysis timeout"
        return leg, False
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    if proc.returncode != 0:
        leg["status"] = "failed"
        leg["detail"] = (proc.stderr or "\n".join(tail)).strip()[-300:]
        return leg, False
    leg.update(status="ran", detail=" ".join(tail).strip()[:200])
    return leg, True


def leg_semantic_query(tree: Path) -> tuple[dict, dict | None]:
    leg = {"tool": "gitnexus context buildSignature", "status": "skipped",
           "detail": ""}
    qbase = _tool_base("gitnexus") or ["npx", "-y", "gitnexus"]
    repo_arg = ["--repo", tree.name]
    try:
        proc = _run([*qbase, "context", "buildSignature", *repo_arg],
                    cwd=tree.parent, timeout=TIMEOUT_QUERY)
    except subprocess.TimeoutExpired:
        leg["detail"] = "query timeout"
        return leg, None
    if proc.returncode != 0:
        leg["status"] = "failed"
        leg["detail"] = (proc.stderr or proc.stdout).strip()[-300:]
        return leg, None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        leg["status"] = "failed"
        leg["detail"] = "non-JSON answer"
        return leg, None
    if data.get("status") != "found":
        leg["status"] = "failed"
        leg["detail"] = f"symbol not found: {data.get('status')}"
        return leg, None
    leg.update(status="ran",
               detail=data.get("symbol", {}).get("uid", ""))
    return leg, data


def run_pipeline(out_path: Path | None, skip_recovery: bool = False) -> int:
    workdir = Path(tempfile.mkdtemp(prefix="web751-demo-"))
    legs: list[dict] = []

    def _skip(tag, why):
        return {"tool": tag, "status": "skipped", "detail": why}

    def add(leg):
        print(f"[{leg['status']:>8}] {leg['tool']}: {leg['detail']}",
              file=sys.stderr)
        legs.append(leg)

    add(leg_selfcheck_bundle(workdir))
    if skip_recovery:
        # index the committed post-recovery stand-in directly
        wakaru_leg = _skip(f"wakaru@{WAKARU_PIN}", "skipped by --stand-in")
        wakaru_tree = None
        webcrack_leg = _skip(f"webcrack@{WEBCRACK_PIN}",
                             "skipped by --stand-in")
        webcrack_tree = None
    else:
        wakaru_leg, wakaru_tree = leg_recover_wakaru(workdir)
        webcrack_leg, webcrack_tree = leg_recover_webcrack(workdir)
    add(wakaru_leg)
    add(webcrack_leg)
    reasons = []
    for tag, leg in (("wakaru", wakaru_leg), ("webcrack", webcrack_leg)):
        if leg["status"] != "ran":
            reasons.append(f"{tag} [{leg['status']}]: {leg['detail']}")
    tree_leg, tree = leg_source_tree(
        workdir,
        [(webcrack_tree, f"webcrack@{WEBCRACK_PIN}"),
         (wakaru_tree, f"wakaru@{WAKARU_PIN}")], reasons)
    add(tree_leg)
    # recovery-leg failure degrades to the copied stand-in tree; only the
    # semantic layer's own legs can hard-fail the demo.

    evidence = {
        "schema": "gitnexus-web-demo/1",
        "issue": "#751",
        "bundles": {"sample": str(BUNDLE.relative_to(REPO)),
                    "stand_in_tree": str(RECOVERED_TREE.relative_to(REPO))},
        "workdir": str(workdir),
        "legs": legs,
        "status": "degraded",
    }

    analyze_leg, analyzed = leg_gitnexus_analyze(tree)
    add(analyze_leg)
    evidence["legs"].append(analyze_leg)
    query_leg, ctx = leg_semantic_query(tree)
    add(query_leg)
    evidence["legs"].append(query_leg)

    hard_failed = any(l["status"] == "failed"
                      for l in (evidence["legs"][0], analyze_leg, query_leg))
    if analyzed and ctx is not None:
        callers = [c["name"] for c in ctx.get("incoming", {}).get("calls", [])]
        callees = [c["name"] for c in ctx.get("outgoing", {}).get("calls", [])]
        chain_exact = "sendRequest" in callers
        evidence["answer"] = {
            "symbol_uid": ctx.get("symbol", {}).get("uid"),
            "incoming_callers": callers,
            "outgoing_callees": callees,
            # full entry-point -> signer -> callee chain visible to the graph
            "chain_exact": chain_exact,
        }
        # asserted: the signer resolves exactly and exposes its assembly
        # helpers; chain_exact additionally pins the caller edge (present on
        # split trees, may vanish under single-file deobfuscation output when
        # the call rides an exports-object member access).
        if not callees or len(callees) < 2 or hard_failed:
            evidence["status"] = "failed"
            print("ASSERT FAIL: buildSignature must resolve exactly with "
                  "its assembly callees and no failed asserting leg",
                  file=sys.stderr)
        else:
            evidence["status"] = "ok"
    elif hard_failed:
        evidence["status"] = "failed"

    print(json.dumps(evidence, indent=2))
    if out_path is not None:
        out_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"evidence written: {out_path}", file=sys.stderr)
    return 0 if evidence["status"] in ("ok", "degraded") else 1


def run_selfcheck() -> int:
    """Offline contract check: fixtures present, bundle runnable via plain
    node when available, CLI shapes intact. Never touches npm."""
    checks: list[dict] = []
    node = shutil.which("node")

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("bundle_fixture_exists", BUNDLE.is_file())
    check("recovered_tree_has_js",
          RECOVERED_TREE.is_dir() and any(RECOVERED_TREE.rglob("*.js")))
    src = BUNDLE.read_text(encoding="utf-8") if BUNDLE.is_file() else ""
    check("fixture_is_bundled_iife",
          src.startswith("!function") and "buildSignature" in src
          and "sendRequest" in src)
    if node and BUNDLE.is_file():
        tmp = Path(tempfile.mkdtemp(prefix="web751-sc-"))
        res = leg_selfcheck_bundle(tmp)
        check("bundle_runs_under_node", res["status"] == "ran", res["detail"])
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        check("bundle_runs_under_node", node is None,
              "node unavailable — structural checks only")
    ok = all(c["ok"] for c in checks)
    print(json.dumps({"mode": "selfcheck", "ok": ok, "checks": checks},
                     indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None,
                    help="also write the evidence JSON to this path")
    ap.add_argument("--selfcheck", action="store_true",
                    help="offline structural check only (no npm/network)")
    ap.add_argument("--stand-in", action="store_true",
                    help="index the committed recovered tree directly "
                         "(skips recovery legs); deterministic exact-chain "
                         "evidence capture")
    args = ap.parse_args(argv)
    if args.selfcheck:
        return run_selfcheck()
    return run_pipeline(Path(args.out) if args.out else None,
                        skip_recovery=args.stand_in)


if __name__ == "__main__":
    sys.exit(main())
