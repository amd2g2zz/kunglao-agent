#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apkid_scanner.py — T1 pre-scan for android intake (#669).

Wraps the `apkid` YARA-based scanner to fingerprint APK packers, compilers,
obfuscators, anti-VM, and anti-debug techniques BEFORE jadx dispatch (#670).
Writes `evidence/apkid.json` with a stable schema; fail-open on every layer
(missing binary -> status:unavailable; non-APK input -> status:error).

The output is TRIAGE SIGNAL consumed by hypothesis_seeder (#662 extension),
not a verdict. Operators audit `status: unavailable` to decide whether to
install apkid post-hoc.

Spec: openspec/changes/issue-669-apkid-prescan/specs/apkid-prescan/spec.md
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Categories apkid emits — every category MUST appear in summary, default []
_CATEGORIES = ("packer", "compiler", "obfuscator", "anti_vm", "anti_debug")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_summary() -> dict[str, Any]:
    """Return the canonical summary shape (all keys present, defaults)."""
    out: dict[str, Any] = {cat: [] for cat in _CATEGORIES}
    out["total"] = 0
    return out


def _discover_apkid() -> tuple[str | None, str]:
    """Locate the apkid binary. Returns (path_or_None, reason)."""
    path = shutil.which("apkid")
    if not path:
        return None, "apkid binary not found on PATH"
    try:
        r = subprocess.run(
            [path, "--version"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if r.returncode != 0:
            return None, f"apkid --version exited {r.returncode}: {r.stderr.strip()}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"apkid --version failed: {exc}"
    return path, ""


def _is_apk(path: str) -> bool:
    return path.lower().endswith(".apk")


def _parse_apkid_output(stdout: str) -> tuple[list[dict], str]:
    """Parse apkid's JSON. Returns (findings, version). Empty findings on
    any parse error — the caller decides status:error vs ok."""
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        return [], ""
    version = str(doc.get("apkid_version") or "")
    findings: list[dict] = []
    results = doc.get("results") or {}
    if isinstance(results, dict):
        for _target, payload in results.items():
            if isinstance(payload, dict):
                for f in payload.get("findings") or []:
                    findings.append({
                        "rule": str(f.get("rule", "")),
                        "category": str(f.get("category", "")),
                        "description": str(f.get("description", "")),
                        "matched_files": list(f.get("matched_files") or []),
                    })
    return findings, version


def _rollup(findings: list[dict]) -> dict[str, Any]:
    """Categorical rollup: distinct rule names per category + total count."""
    summary = _empty_summary()
    seen: dict[str, set] = {cat: set() for cat in _CATEGORIES}
    for f in findings:
        cat = f.get("category", "")
        rule = f.get("rule", "")
        if cat in seen and rule and rule not in seen[cat]:
            seen[cat].add(rule)
            summary[cat].append(rule)
    summary["total"] = len(findings)
    return summary


def _run_scan(apkid_path: str, apk_path: str, timeout: int = 120) -> tuple[int, str, str]:
    """Invoke `apkid scan --json <apk>`. Returns (rc, stdout, stderr)."""
    cp = subprocess.run(
        [apkid_path, "scan", "--json", apk_path],
        capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    return cp.returncode, cp.stdout, cp.stderr


def _write_evidence(workspace: Path, data: dict) -> Path:
    """Always writes the evidence file (fail-open contract)."""
    out_dir = workspace / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "apkid.json"
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def run(workspace: Path | str, apk_path: str) -> int:
    """Top-level entry: scan + write evidence. 0 on ok|unavailable; 1 on error.

    Always writes evidence/apkid.json (fail-open). Never raises."""
    workspace = Path(workspace)
    apk_path = str(apk_path)
    scanned_at = _utc_now()
    base = {
        "tool": "apkid",
        "version": None,
        "target": apk_path,
        "scanned_at": scanned_at,
        "findings": [],
        "summary": _empty_summary(),
        "status": "ok",
        "reason": "",
    }

    if not _is_apk(apk_path):
        base["status"] = "error"
        base["reason"] = f"target is not an APK: {apk_path}"
        _write_evidence(workspace, base)
        return 1

    apkid_path, why = _discover_apkid()
    if apkid_path is None:
        base["status"] = "unavailable"
        base["reason"] = why
        _write_evidence(workspace, base)
        return 0

    try:
        rc, stdout, stderr = _run_scan(apkid_path, apk_path)
    except (OSError, subprocess.TimeoutExpired) as exc:
        base["status"] = "error"
        base["reason"] = f"apkid invocation failed: {exc}"
        _write_evidence(workspace, base)
        return 1

    if rc != 0:
        base["status"] = "error"
        base["reason"] = f"apkid exit {rc}: {stderr.strip()[:500]}"
        _write_evidence(workspace, base)
        return 1

    findings, version = _parse_apkid_output(stdout)
    base["version"] = version or None
    base["findings"] = findings
    base["summary"] = _rollup(findings)
    base["status"] = "ok"
    _write_evidence(workspace, base)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="apkid pre-scan wrapper (#669). Writes evidence/apkid.json.",
    )
    parser.add_argument("workspace", type=Path, help="workspace root (writes evidence/)")
    parser.add_argument("apk_path", help="absolute path to the APK to scan")
    args = parser.parse_args(argv)
    rc = run(args.workspace, args.apk_path)
    try:
        evidence = json.loads(
            (args.workspace / "evidence" / "apkid.json").read_text(encoding="utf-8")
        )
        print(json.dumps(
            {"status": evidence["status"], "summary": evidence["summary"]},
            ensure_ascii=False,
        ))
    except Exception:  # noqa: BLE001 — best-effort audit line
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())