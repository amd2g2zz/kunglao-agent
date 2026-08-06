"""阶段 0 契约测试: pytest 套件健康 + golden master 基建.

Step 0/1 RED — 当前状态:
- test_claim_status_guard.py 在 pytest 收集时报 ModuleNotFoundError(无 pytest.ini pythonpath)
- golden master 尚未采集(manifest/fixtures 不存在) → 重放全部 RED

GREEN 目标(阶段 0 判据):
- 从 kunglao-agent/ 根跑 `uv run pytest` 收集零 ERROR 全绿
- 29/29 golden 用例可重放(逐字节比对 expected)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]  # kunglao-agent/
GOLDEN = ROOT / "tests" / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"


# ---------- 套件健康 ----------

def test_collection_no_error() -> None:
    """pytest 收集全量测试文件无 ERROR(含 test_claim_status_guard.py 的 hooks import)."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"collection had errors:\n{r.stdout}\n{r.stderr}"


def test_claim_status_guard_importable() -> None:
    """hooks/worker_budget.py 在任意 CWD 可导入(pythonpath 修复)."""
    r = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0,'.'); import worker_budget; print('ok')"],
        cwd=ROOT / "hooks", capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


# ---------- golden master ----------

def _load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    import yaml
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _load_manifest(), ids=lambda c: c["id"])
def test_golden_replay(case: dict) -> None:
    """逐字节重放 golden 用例, 输出须与采集的 expected 一致."""
    import re

    case_dir = GOLDEN / case["id"]
    expected = case_dir / "expected" / "stdout.txt"
    assert expected.exists(), f"golden fixture missing: {expected}"
    cmd = case["cmd"]
    env = dict(os.environ)
    env.pop("PRIORITY_WEIGHTS", None)
    r = subprocess.run(
        cmd["argv"], cwd=cmd.get("cwd", str(ROOT)),
        env=env, capture_output=True, text=True, timeout=120,
    )
    if case.get("expected_exit") is not None:
        assert r.returncode == case["expected_exit"], \
            f"exit {r.returncode} != {case['expected_exit']}\nstdout={r.stdout[:500]}\nstderr={r.stderr[:500]}"
    else:
        exp = expected.read_text(encoding="utf-8")
        # 时间戳归一化: 采集与重放跨秒, progress_report 等含当前 UTC 时间
        exp_norm = re.sub(r"\(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ\)", "(<TS>)", exp)
        act_norm = re.sub(r"\(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ\)", "(<TS>)", r.stdout)
        assert act_norm == exp_norm, f"stdout differs:\n--- expected ---\n{exp_norm}\n--- actual ---\n{act_norm}"
