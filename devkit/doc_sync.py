#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_sync.py — Gate 7 (Doc Sync) writing-layer drift guard (#446).

Issue #446 G-class: the gate count lives in ONE place (the GATES registry
in quality_gates.py) but was COPIED into docstrings, hook headers, README
tables, and CI workflow comments — every copy a drift seed. The 7th live
drift (issue comment 2026-08-19): references/_INDEX.md edited without
re-pinning references/_INDEX.yaml, failing a test AFTER landing. This gate
makes both failure classes mechanical at commit time.

Three sub-checks (design.md D2-D5):
  (a) gate-count claim scan — any numeric count claim about gates
      ("N-gate", "N gates", "N 个 Gate", "N 门") on the devkit/** +
      .github/workflows/** face is a violation. Number-free wording is
      the fix: the registry is the count's only source. Deliberately NOT
      "number != len(GATES)" — even a currently-correct number goes stale
      when the next gate registers (derive-don't-copy). Face scope is
      empirical: scripts/hooks/tests talk about a DIFFERENT gate family
      (product enforcement gates, version ids, DIFF-N ids); scanning them
      would be noise, not signal.
  (b) references re-pin — staged references/*.md (non-archive) requires a
      staged references/_INDEX.yaml whose files: pins match the STAGED
      content sha256 (git show :path — catches both "yaml not staged" and
      "yaml staged but stale"). Violation → HARD_PAUSE; fix is
      `uv run python scripts/re_pin_references.py` + stage the yaml.
  (c) mechanism registration ledger — staged NEW scripts/*.py
      (--diff-filter=A) whose stem is not mentioned in
      references/_INDEX.md → WARN (non-blocking): a new mechanism
      registers three pieces (code + reference + index row). Existing
      unregistered scripts are pre-existing debt, never retroactive
      failures.

Exit codes: 0 = pass; 1 = violations found; 2 = HARD_PAUSE (references
unpinned). Registered as Gate 7 in quality_gates.GATES; the pre-commit
template runs it in its quick set. Fail-closed on unexpected exceptions
is provided by the quality_gates runner wrapper (same as Gates 5/6).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Scan face: the quality-gate family's documentation carriers only.
SCAN_ROOTS = ("devkit", ".github/workflows")

_SKIP_DIRS = {"__pycache__", ".git"}

# Numeric gate-count claim: digit(s), optional Chinese counter 个,
# optional spaces, then a hyphen+gate(s) / space+gate(s) / 门, with an
# optional "quality" qualifier (the CJK form with 个). Single-gate IDs
# ("Gate 5", "Gate 1 + 3") and CLI arg lists never match because the
# digit must PRECEDE the gate word. (Wording here stays number-free on
# purpose: this file is inside its own scan face.)
_COUNT_CLAIM_RE = re.compile(
    r"(?<![0-9A-Za-z])\d{1,2}(?:[ \t]*个)?[ \t]*-[ \t]*(?:quality[ \t]+)?gates?\b"
    r"|(?<![0-9A-Za-z])\d{1,2}(?:[ \t]*个)?[ \t]+(?:quality[ \t]+)?gates?\b"
    r"|(?<![0-9A-Za-z])\d{1,2}(?:[ \t]*个)?[ \t]*(?:quality[ \t]+)?门",
    re.IGNORECASE)

RC_PASS = 0
RC_FAIL = 1
RC_PAUSE = 2

INDEX_YAML = "references/_INDEX.yaml"
INDEX_MD = "references/_INDEX.md"


def _out_encoding() -> str:
    return getattr(sys.stdout, "encoding", None) or "utf-8"


def _safe(text: str) -> str:
    """GBK-console safety (2026-08-20 lesson): violations carry CJK text;
    printing raw crashed a scan on a GBK Windows console."""
    enc = _out_encoding()
    return text.encode(enc, "replace").decode(enc, "replace")


def _staged_files(extra_args: list[str] | None = None) -> list[str]:
    """Staged (cached) file paths relative to repo root. Git failure →
    empty list (N/A semantics, mirrors subagent_review._staged_files)."""
    cmd = ["git", "diff", "--cached", "--name-only"]
    if extra_args:
        cmd += extra_args
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT,
                       errors="replace")
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _staged_bytes(rel: str) -> bytes | None:
    """Staged (index) content of one file; None when not staged/readable."""
    r = subprocess.run(["git", "show", f":{rel}"], capture_output=True,
                       cwd=REPO_ROOT)
    return r.stdout if r.returncode == 0 else None


def _parse_pins(yaml_text: str) -> dict[str, str]:
    """Parse the files: block of references/_INDEX.yaml (line-level, the
    same parse re_pin_references.py performs — no yaml dependency in
    devkit, which is stdlib-only by convention)."""
    pins: dict[str, str] = {}
    in_files = False
    for ln in yaml_text.splitlines():
        if ln.strip() == "files:":
            in_files = True
            continue
        if in_files:
            if ln.startswith("  ") and ":" in ln:
                path, _, sha = ln.strip().rpartition(":")
                pins[path.strip()] = sha.strip()
            else:
                in_files = False
    return pins


def _iter_face_files() -> list[Path]:
    out: list[Path] = []
    for root_rel in SCAN_ROOTS:
        root = REPO_ROOT / root_rel
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if _SKIP_DIRS.intersection(p.parts):
                continue
            out.append(p)
    return out


def scan_gate_count_claims() -> list[dict]:
    """Return every numeric gate-count claim on the scan face as
    {"file", "line", "text", "claim"} (file is repo-relative POSIX)."""
    claims: list[dict] = []
    for p in _iter_face_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in text:  # binary-ish — not prose, skip
            continue
        for i, ln in enumerate(text.splitlines(), 1):
            m = _COUNT_CLAIM_RE.search(ln)
            if m:
                claims.append({
                    "file": p.relative_to(REPO_ROOT).as_posix(),
                    "line": i,
                    "text": ln.strip()[:120],
                    "claim": m.group(0),
                })
    return claims


def _check_references_pins() -> list[str]:
    """Sub-check (b). Returns HARD_PAUSE reasons (empty = ok / N/A)."""
    staged = _staged_files()
    ref_md = [p for p in staged
              if p.startswith("references/") and p.endswith(".md")
              and "archive/" not in p]
    if not ref_md:
        return []
    if INDEX_YAML not in staged:
        return [
            f"{', '.join(ref_md)}: staged without {INDEX_YAML} — "
            "references edits must re-pin in the same commit "
            "(uv run python scripts/re_pin_references.py, then stage the yaml)"
        ]
    yaml_bytes = _staged_bytes(INDEX_YAML)
    if yaml_bytes is None:
        return [f"{INDEX_YAML}: staged but unreadable from the index"]
    pins = _parse_pins(yaml_bytes.decode("utf-8", errors="replace"))
    pauses: list[str] = []
    for rel in ref_md:
        if rel not in pins:
            pauses.append(f"{rel}: no pin in staged {INDEX_YAML} "
                          "(new references file — re-pin required)")
            continue
        data = _staged_bytes(rel)
        if data is None:
            pauses.append(f"{rel}: staged list says staged, index read failed")
            continue
        actual = hashlib.sha256(data).hexdigest()
        if actual != pins[rel]:
            pauses.append(
                f"{rel}: staged sha {actual[:12]} != staged pin "
                f"{pins[rel][:12]} — pin is stale, re-run "
                "scripts/re_pin_references.py")
    return pauses


def _check_new_script_registration() -> list[str]:
    """Sub-check (c). Returns WARN strings (never blocking, design D5)."""
    added = _staged_files(["--diff-filter=A"])
    new_scripts = [p for p in added
                   if p.startswith("scripts/") and p.endswith(".py")]
    if not new_scripts:
        return []
    idx = REPO_ROOT / INDEX_MD
    try:
        idx_text = idx.read_text(encoding="utf-8", errors="replace")
    except OSError:
        idx_text = ""
    warns: list[str] = []
    for rel in new_scripts:
        stem = Path(rel).stem
        if stem not in idx_text:
            warns.append(
                f"{rel}: stem {stem!r} is not mentioned in {INDEX_MD} — "
                "a new mechanism registers three pieces (code + reference "
                "+ index row); pre-existing unregistered scripts are "
                "existing debt, not a failure")
    return warns


def _registry_note() -> str:
    """Guidance text only — the registry len is NOT part of the verdict
    (design D3: judgement is number-free, so it cannot drift)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import quality_gates as _qg
        return (f"gate count is registry-derived "
                f"(devkit/quality_gates.py GATES: {len(_qg.GATES)} registered)")
    except Exception:
        return "gate count is registry-derived (devkit/quality_gates.py GATES)"


def check() -> int:
    claims = scan_gate_count_claims()
    pauses = _check_references_pins()
    warns = _check_new_script_registration()

    for w in warns:
        print(_safe(f"  [WARN] {w}"))

    if pauses:
        print(_safe(f"HARD_PAUSE Gate 7: {len(pauses)} references re-pin "
                    f"violation(s):"))
        for p in pauses:
            print(_safe(f"  {p}"))
        print(_safe("  Fix: uv run python scripts/re_pin_references.py, "
                    "then git add references/_INDEX.yaml"))
        return RC_PAUSE

    if claims:
        print(_safe(f"FAIL Gate 7: {len(claims)} numeric gate-count "
                    f"claim(s) on the devkit/workflows face "
                    f"({_registry_note()}):"))
        for c in claims:
            print(_safe(f"  {c['file']}:{c['line']}: claim {c['claim']!r} "
                        f"— {c['text']}"))
        print(_safe("  Fix: number-free wording (the GATES registry is the "
                    "count's only source); claims are violations even when "
                    "the number is currently correct"))
        return RC_FAIL

    print("[PASS] Gate 7 doc sync: gate-count claim scan clean, "
          "references pins clean"
          + (f", {len(warns)} registration WARN(s)" if warns else ""))
    return RC_PASS


def main(argv: list[str] | None = None) -> int:
    return check()


if __name__ == "__main__":
    sys.exit(main())
