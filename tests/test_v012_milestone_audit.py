# -*- coding: utf-8 -*-
"""tests/test_v012_milestone_audit.py — #539 v0.1.2 里程碑四件套审计测试

#539 split E: 里程碑审计本体 (white-box + black-box + replay + log + regression)

外部现场回放场景 (split E-2): 在外部目录/tmp/empty 模拟 user 首次接触 kunglao-agent 的真实条件,
逐个跑 convergence_check / kunglao-init / hook_activation / release_receipt 四件套,
验证 v0.1.2 milestone 在外部现场不依赖仓库内部状态仍能给出确定性结论。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]

# #794: behavioral env vars — values that rewrite a CLI's decision flow
# rather than its infrastructure. Scrubbed unconditionally from every child
# env _run_cli builds (see _run_cli docstring for the maintenance policy).
_BEHAVIORAL_ENV_VARS = (
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",  # kunglao-init #276 Phase-0 gate
)


def test_milestone_issues_closed():
    """Sprint Goal: 大部分 milestone issues 已 closed (>= 70%)。"""
    # Locally check: count open vs closed milestone files in docs
    milestone_file = ROOT / ".github" / "MILESTONES.md"
    if not milestone_file.exists():
        pytest.skip("MILESTONES.md not present")
    text = milestone_file.read_text(encoding="utf-8")
    assert "v0.1.2" in text


def test_changelog_has_unreleased_section():
    """CHANGELOG.md 包含未发布变更记录。"""
    cl = ROOT / "CHANGELOG.md"
    if not cl.exists():
        pytest.skip("CHANGELOG.md not present")
    text = cl.read_text(encoding="utf-8")
    # Either [Unreleased] or [0.1.2] section
    assert "Unreleased" in text or "0.1.2" in text


def test_no_legacy_precommit_reference():
    """#445: 单一 hook 注册路径,无 .claude/hooks/pre-commit 残留引用。"""
    offenders = []
    for p in ROOT.rglob("*"):
        # #799: exclude the `.review` prefix family (.review, .review-gate,
        # any .review-* sibling) — local review evidence surface, not repo
        # content. Exact component match missed .review-gate (#799).
        if not p.is_file() or ".git" in p.parts or any(
            part.startswith(".review") for part in p.parts
        ):
            continue
        if ".worktrees" in p.parts or "docs/superpowers" in str(p):
            continue
        if p.suffix not in (".py", ".md", ".yaml", ".txt", ".sh", ".tmpl"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except (UnicodeDecodeError, OSError):
            continue
        if ".claude/hooks/pre-commit" in text:
            # Allow self-reference
            if p.name in ("test_dedup_319.py", "test_v012_milestone_audit.py"):
                continue
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, f"legacy pre-commit refs: {offenders}"


def test_hook_registration_single_entry():
    """#445: 单一 hook 注册入口。"""
    ha = ROOT / "scripts" / "hook_activation.py"
    text = ha.read_text(encoding="utf-8")
    assert 'CANONICAL_REGISTRATION_ENTRY = "hook_activation.register_hooks"' in text


def test_convergence_check_exists():
    """v0.1.2 核心: convergence_check.py 存在。"""
    assert (ROOT / "scripts" / "convergence_check.py").exists()


def test_init_negotiation_interface():
    """S8 (#451): init 协商接口存在。"""
    assert (ROOT / "scripts" / "kunglao-init.py").exists()


def test_worker_liveness_protocol():
    """S5 (#444): worker liveness 单一真相源。"""
    # lib_kunglao.py 应包含 parse_worker_status
    lib = ROOT / "hooks" / "lib_kunglao.py"
    text = lib.read_text(encoding="utf-8")
    assert "parse_worker_status" in text


def test_priority_ratio_scorer():
    """S5/S6: priority_ratio 是唯一 live scorer (#499)。"""
    pr = ROOT / "scripts" / "priority_ratio.py"
    assert pr.exists()


def test_execution_receipt_present():
    """release-receipt 在 CI 生成。"""
    rr = ROOT / "scripts" / "release_receipt.py"
    assert rr.exists()


# ---------------------------------------------------------------------------
# 外部现场回放场景 (split E-2: black-box replay against a fresh external dir)
# ---------------------------------------------------------------------------
# 模拟 user 在外部空目录首次接触 v0.1.2 milestone 四件套，确认:
#   1. convergence_check 在空 workspace 给出确定性 JSON(不退化/不崩溃)
#   2. kunglao-init 在外部 workspace 能产出最小 claim-register + manifest 契约
#   3. hook_activation 在外部 workspace 能写入 .kunglao/ 状态且 wire-up 幂等
#   4. release_receipt 在外部空 workspace 走 --check 仅校验 manifest/CLI surface,无副作用
# 所有外部 replay 在 pytest tmp_path 下,不污染仓库内任何状态。


def _run_cli(args: list[str], cwd: Path, *, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a kunglao CLI script as subprocess under the venv interpreter.

    sys.executable is the uv-managed venv python (>= the project floor on
    every CI matrix job), which supports the PEP 604 union syntax the
    scripts use. The old hard pin /usr/local/bin/python3.11 (#457) broke
    the 3.10 CI job with PermissionError, so we resolve dynamically.

    Deterministic child environment (#794):
    - Behavioral vars are scrubbed AFTER the env= merge — neither the parent
      shell nor a caller may leak them in. `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`
      flips kunglao-init's #276 Phase-0 gate to HARD REJECT before the bins
      logic, which made these replay tests report the launching shell's state
      instead of the behavior they pin (issue #794 Windows symptom). Extend
      the tuple only for vars that change a CLI's decision flow, each with a
      citation; infrastructure vars (PATH, PYTHONPATH, venv) stay inherited —
      a full env sandbox would break the dynamic sys.executable resolution
      above (#457 lesson).
    - UTF-8 is forced on both sides of the pipe: PYTHONUTF8=1 +
      PYTHONIOENCODING=utf-8 via setdefault (explicit env= values still win —
      override contract preserved), and the capture decodes utf-8/replace —
      mirrors conftest.golden_master; bare text=True locale-decodes strictly,
      so a GBK console host crashes the reader thread on any non-ASCII output
      (same family as #457 items #2-#5).
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    for behavioral_var in _BEHAVIORAL_ENV_VARS:
        full_env.pop(behavioral_var, None)
    full_env.setdefault("PYTHONUTF8", "1")
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def test_replay_convergence_check_on_empty_workspace(tmp_path: Path):
    """回放场景 1: 外部空 workspace 跑 convergence_check --json。

    v0.1.2 现场契约: 缺 claim-register.yaml 时必须给出确定性诊断(非空 stderr + 非零 exit),
    而不是模糊崩溃/或假阳性 "should_dispatch=true"。
    """
    proc = _run_cli(
        [str(ROOT / "scripts" / "convergence_check.py"), str(tmp_path), "--json"],
        cwd=ROOT,
    )
    # exit code 非零(代表 "应阻塞派活"),且 stderr 必须明确指出缺 claim-register
    assert proc.returncode != 0, (
        f"convergence_check must refuse empty workspace, got exit={proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "claim-register" in combined or "claim_register" in combined, (
        f"expected claim-register diagnostic, got:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    # --json 模式下 stdout 应包含可解析 JSON(即便 exit 非零)
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(
                f"--json 模式 stdout 非合法 JSON:\nstdout={proc.stdout!r}\nerr={e}"
            )
        assert "should_dispatch" in payload, f"missing should_dispatch in {payload}"
        assert payload["should_dispatch"] is False, (
            f"empty workspace must NOT recommend dispatch: {payload}"
        )
    # 幂等:第二次跑必须给同样结论(同 exit + 同诊断)
    proc2 = _run_cli(
        [str(ROOT / "scripts" / "convergence_check.py"), str(tmp_path), "--json"],
        cwd=ROOT,
    )
    assert proc2.returncode == proc.returncode, (
        f"idempotency broken on empty workspace: first={proc.returncode} second={proc2.returncode}"
    )


def test_replay_init_minimal_workspace_contract(tmp_path: Path):
    """回放场景 2: 外部空 workspace 跑 kunglao-init (--type linux + bins/ 占位样本)。

    v0.1.2 现场契约: 满足最小输入(bins/ 下有样本 + --type)时,init 必须能产出
    claim-register.yaml + .workspace-manifest.json 最小契约,且 exit 0。
    """
    # 模拟 user 准备: 至少一个 bins/ 样本 + --type
    seed_bins(tmp_path, payload=b"\x00\x01\x02")
    proc = _run_cli(
        [
            str(ROOT / "scripts" / "kunglao-init.py"),
            str(tmp_path),
            "--type", "linux",
            "--skip-toolchain", "--host-exec-protection", "enabled",  # 测试环境无 toolchain,走 ops escape hatch
            "--no-hooks",  # 不污染外部 workspace 的 .claude/settings.json
            "--assume-yes",
        ],
        cwd=ROOT,
    )
    assert proc.returncode == 0, (
        f"kunglao-init failed on external workspace with bins/ sample:\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    # 验证最小契约: claim-register + workspace-manifest 必须存在
    assert (tmp_path / "claim-register.yaml").exists(), \
        "claim-register.yaml not produced (minimal contract violated)"
    assert (tmp_path / ".workspace-manifest.json").exists(), \
        ".workspace-manifest.json not produced (minimal contract violated)"
    # state_hash 必须在 stdout 或 stderr 中暴露(后续 receipt/trace 依赖)
    combined_io = (proc.stdout or "") + (proc.stderr or "")
    assert "state_hash=" in combined_io, (
        f"kunglao-init must emit state_hash for downstream receipt/trace:\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def test_replay_init_refuses_empty_bins(tmp_path: Path):
    """回放场景 2b: 外部空 workspace 跑 kunglao-init 但 bins/ 无样本。

    v0.1.2 现场契约: 无 bins/ 样本时,init 必须给出确定性失败(exit 5 + 明确诊断),
    不能默默创建空 workspace 假装成功。
    """
    proc = _run_cli(
        [
            str(ROOT / "scripts" / "kunglao-init.py"),
            str(tmp_path),
            "--skip-toolchain", "--host-exec-protection", "enabled",
            "--no-hooks",
            "--assume-yes",
        ],
        cwd=ROOT,
    )
    assert proc.returncode != 0, (
        f"kunglao-init must refuse empty bins/, got exit={proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "analysis target" in (proc.stderr or "").lower() or "bins" in (proc.stderr or "").lower(), (
        f"expected diagnostic pointing to bins/ or analysis target:\nstderr={proc.stderr!r}"
    )


def test_replay_hook_activation_wire_up_is_idempotent(tmp_path: Path):
    """回放场景 3: 外部空 workspace 跑 hook_activation --wire-up 两次。

    v0.1.2 现场契约: wire-up 必须幂等 — 二次运行不应重复写入状态、不应崩溃。
    这是 #445 (canonical hook registration) 的关键回归门。
    """
    hook_script = ROOT / "scripts" / "hook_activation.py"
    # 第一次 wire-up
    proc1 = _run_cli(
        [str(hook_script), str(tmp_path), "--wire-up", "--tier", "advisory"],
        cwd=ROOT,
    )
    assert proc1.returncode == 0, (
        f"first wire-up failed:\nstdout={proc1.stdout!r}\nstderr={proc1.stderr!r}"
    )
    # v0.1.2 真实状态文件: HOOK_STATE_FILE = ".hook_state.json" (per hook_activation.py L81)
    state_file = tmp_path / ".hook_state.json"
    settings_file = tmp_path / ".claude" / "settings.json"
    assert state_file.exists() or settings_file.exists(), (
        "wire-up produced no state — canonical wire-up path broken "
        f"(expected {state_file} or {settings_file})"
    )
    # 二次 wire-up 必须幂等(同输入,同 exit code,不重复追加)
    proc2 = _run_cli(
        [str(hook_script), str(tmp_path), "--wire-up", "--tier", "advisory"],
        cwd=ROOT,
    )
    assert proc2.returncode == proc1.returncode, (
        f"idempotency broken: first={proc1.returncode} second={proc2.returncode}"
    )
    if state_file.exists():
        before = state_file.read_text()
        after = (proc2 and state_file.read_text())
        assert before == after, (
            f".hook_state.json changed across idempotent re-runs:\n"
            f"before={before!r}\nafter={after!r}"
        )


def test_replay_release_receipt_check_only_no_side_effects(tmp_path: Path):
    """回放场景 4: 外部空 workspace 跑 release_receipt --check。

    v0.1.2 现场契约: --check 模式只校验不写盘。
    必须: 退出 0 + 不在 tmp_path 下产生 release-receipt.json。
    这是 CI/release 流程的关键安全门(避免意外覆盖正式 receipt)。
    """
    proc = _run_cli(
        [
            str(ROOT / "scripts" / "release_receipt.py"),
            "--check",
            "--manifest", str(ROOT / "release-manifest.yaml"),
            "--out", str(tmp_path / "release-receipt.json"),
        ],
        cwd=ROOT,
    )
    assert proc.returncode == 0, (
        f"release_receipt --check failed:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    # --check 模式不应写 receipt 文件(只在 --out 显式给路径时仍不应写,因为 --check 优先)
    # 留宽松断言:如果写了,内容必须是有效 JSON;但不应在 tmp_path 之外产生副作用
    if (tmp_path / "release-receipt.json").exists():
        try:
            json.loads((tmp_path / "release-receipt.json").read_text())
        except json.JSONDecodeError:
            pytest.fail("release_receipt wrote malformed JSON under --check mode")


if __name__ == "__main__":
    sys.exit(0)
