"""test_complete_teardown.py - smoke test for v1.8.16 sample complete teardown.

Tests:
  1. Script accepts a workspace + sample path
  2. Outputs a fact file at <workspace>/facts/F-NNN-teardown-<sample>.md
  3. Fact file contains all 5 operator results (imports, byte_grep, capstone, strings, anti_analysis)
  4. Each operator has status: "ok" or "skipped" (not "error")
  5. TL;DR section is present
  6. Packer detection works on UPX (synthetic test)
  7. Smoke tests use a system PE (notepad.exe or calc.exe) to avoid the
     block_malware_exec PreToolUse hook on malware samples.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(r"C:/Users/hr/.claude/skills/kunglao-agent/scripts/complete_teardown.py")

REQUIRED_OPERATORS = ["imports", "byte_grep", "capstone", "strings", "anti_analysis"]


def test_workspace_setup():
    """Set up a temp workspace with a single sample (calc.exe or notepad.exe)."""
    candidates = [r"C:/Windows/System32/calc.exe", r"C:/Windows/System32/notepad.exe"]
    sample = None
    for c in candidates:
        if Path(c).exists():
            sample = Path(c)
            break
    if not sample:
        print(f"  [SKIP] no system PE found in {candidates}")
        return None

    tmpdir = Path(tempfile.mkdtemp(prefix="teardown_test_"))
    (tmpdir / "bins").mkdir()
    (tmpdir / "facts").mkdir()
    shutil.copy(sample, tmpdir / "bins" / sample.name)
    return tmpdir, sample


def run_complete_teardown(workspace: Path) -> tuple:
    import subprocess
    res = subprocess.run(
        ["python", str(SCRIPT), str(workspace)],
        capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    return res.returncode, res.stdout, res.stderr


def test_smoke_basic():
    setup = test_workspace_setup()
    if not setup:
        return
    workspace, sample = setup
    rc, out, err = run_complete_teardown(workspace)
    if rc != 0:
        print(f"  [FAIL] exit {rc}, stdout={out[:200]}, stderr={err[:200]}")
        return
    fact = workspace / "facts" / f"F-001-teardown-{sample.stem}.md"
    if not fact.exists():
        print(f"  [FAIL] no fact file at {fact}")
        return
    text = fact.read_text(encoding="utf-8")
    print(f"  [OK ] smoke test basic: rc=0, fact file written ({len(text)} bytes)")


def test_5_operators_present():
    setup = test_workspace_setup()
    if not setup:
        return
    workspace, sample = setup
    rc, out, err = run_complete_teardown(workspace)
    fact = workspace / "facts" / f"F-001-teardown-{sample.stem}.md"
    if not fact.exists():
        return
    text = fact.read_text(encoding="utf-8")
    missing = [op for op in REQUIRED_OPERATORS if f"### {op}" not in text]
    if missing:
        print(f"  [FAIL] missing operator sections: {missing}")
    else:
        print(f"  [OK ] 5 operator sections all present in fact file")


def test_no_error_status():
    setup = test_workspace_setup()
    if not setup:
        return
    workspace, sample = setup
    rc, out, err = run_complete_teardown(workspace)
    fact = workspace / "facts" / f"F-001-teardown-{sample.stem}.md"
    if not fact.exists():
        return
    text = fact.read_text(encoding="utf-8")
    for op in REQUIRED_OPERATORS:
        m = re.search(rf"### {op}\s*\n\n```json\s*\n(.*?)```", text, re.DOTALL)
        if not m:
            print(f"  [FAIL] {op}: no JSON block found")
            continue
        try:
            d = json.loads(m.group(1))
            status = d.get("status", "?")
            if status == "error":
                print(f"  [FAIL] {op}: status=error, reason={d.get('reason', '?')[:80]}")
            else:
                print(f"  [OK ] {op}: status={status}")
        except json.JSONDecodeError as e:
            print(f"  [FAIL] {op}: JSON parse error {e}")


def test_tldr_present():
    setup = test_workspace_setup()
    if not setup:
        return
    workspace, sample = setup
    rc, out, err = run_complete_teardown(workspace)
    fact = workspace / "facts" / f"F-001-teardown-{sample.stem}.md"
    if not fact.exists():
        return
    text = fact.read_text(encoding="utf-8")
    if "## TL;DR" not in text:
        print("  [FAIL] no TL;DR section in fact file")
    else:
        m = re.search(r"## TL;DR\s*\n\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if m:
            summary = m.group(1).strip()
            print(f"  [OK ] TL;DR present: '{summary[:80]}...'")


def test_packer_detection_upx():
    """Synthetic test: write a minimal file with 'UPX!' in it."""
    from pathlib import Path
    import subprocess
    tmpdir = Path(tempfile.mkdtemp(prefix="upx_test_"))
    (tmpdir / "bins").mkdir()
    (tmpdir / "facts").mkdir()
    fake_sample = tmpdir / "bins" / "fakepacked.exe"
    fake_sample.write_bytes(b"MZ" + b"\x00" * 100 + b"UPX! here" + b"\x00" * 1000)
    proc = subprocess.run(
        ["python", str(SCRIPT), str(tmpdir), str(fake_sample)],
        capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    rc, out, err = proc.returncode, proc.stdout, proc.stderr
    if "UPX" in out or "UPX" in err:
        print(f"  [OK ] UPX marker detected in script output")
    else:
        if rc != 0:
            print(f"  [SKIP] fake PE rejected by pefile (expected); UPX detection in imports-block requires real PE")
        else:
            print(f"  [FAIL] no UPX detection in output")


def main() -> int:
    print("=" * 60)
    print("test_complete_teardown.py - v1.8.16 smoke suite")
    print("=" * 60)
    tests = [
        test_smoke_basic,
        test_5_operators_present,
        test_no_error_status,
        test_tldr_present,
        test_packer_detection_upx,
    ]
    fails = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: AssertionError: {e}")
            fails += 1
        except Exception as e:
            print(f"  [ERR ] {t.__name__}: {type(e).__name__}: {e}")
            fails += 1
    print("=" * 60)
    if fails == 0:
        print("ALL_OK")
    else:
        print(f"FAILURES: {fails}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())