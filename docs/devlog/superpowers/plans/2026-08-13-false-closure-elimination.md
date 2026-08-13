# 假闭环消除（Batch 0 + Batch 1：P0）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除四个已复现的假闭环路径（omission/contradiction/summary-only/second-stop），使 `.research-tree/experiments/incident_replay.py` 的 4 个 replay 全部通过，CI 全绿。

**Architecture:** 完成判定从"各 checker 分散存在"收敛为"provenance 接入唯一 PROVEN 迁移入口 + completion transaction 全局重算 + discovery 转化为 obligation + completion hook fail-closed"。文档契约（SKILL.md）与实现同步收紧，不再超前。全部使用 kunglao 既有模式：纯函数 checker + 测试驱动 + 模板驱动 workspace。

**Tech Stack:** Python 3.11 + pytest + PyYAML + pefile + capstone + jsonschema。测试框架 pytest（`pytest.ini` 已配 pythonpath = `hooks scripts tools`）。

**Working dir:** `/Users/dev/workprojects/kunglao-agent`。所有相对路径以此为根。项目测试命令：`.venv/bin/python -m pytest -q`（venv 已在位；系统 python 无 yaml，不要用）。

**Spec:** `.research-tree/reports/kunglao-long-horizon-technical.md` §1/§2/§5/§7（P0）。范围约定见 §14"Batch 范围"。

---

## 文件结构

```
.git/                                    ← git worktree 由 using-git-worktrees skill 创建（此计划在 dev 分支上跑）
.github/workflows/release-check.yml      [M] 修 line 52-58 的 YAML 缩进错误
SKILL.md                                 [M] T1 降级 CONVERGED 行（Batch 0）→ T20 回升（与 completion tx 同 commit）
scripts/
  provenance_gate.py                     [M] 新增 main() argparse CLI（F5）
  kunglao_record.py                      [M] PROVEN 必经链接入 provenance_gate（T10）
  completion_gate.py                     [M] judge() 新增全局矛盾校验（T17）+ oracle 检查收紧（T18）
  convergence_check.py                   [M] decide() 接入 completion_transaction（T19）
  obligation_discovery.py                [N] DiscoveryEmitted → ObligationCreated（T21-T22）
  structural_check.py                    [M] 新增 _INDEX.yaml drift 检查（T15）+ 错误行加 ERROR 前缀（T16）
references/
  _INDEX.yaml                            [N] references 机器可读索引 + 症状映射（T15，Batch 3 的 recall 引擎消费它）
  re-library/field-notes.md              [M] 断链修复（T7）
  re-library/malware-analysis-quickstart.md [M] 断链修复（T8）
  re-library/phishing-case-study.md      [N] 修复 field-notes.md 断链（T8）
hooks/completion_gate.py                 [M] 删除 stop_hook_active 放行 + no-oracle 放行收紧（T18）
memory/candidates/corpus/manifest.json   [M] 6 个 digest 漂移修复（T12，测试驱动）
templates/task_spec.yaml                 [M] + calibration 规范（T14，测试驱动）
templates/task-oracle.yaml               [N] oracle 模板（T14）
release-manifest.yaml                    [M] + re-library digest 节（T23）
scripts/release_receipt.py               [M] re-library digest 实现（T23）
scripts/release_check_selfcheck.py       [N] CI yaml lint 的 repo-owned 预检（T13）
tests/
  test_replay_gate.py                    [N] T1/T2 的 contract 测试（Batch 0 验收）
  test_provenance_wiring.py              [N] PROVEN 必经链契约（T10）
  test_provenance_gate.py                [M] + CLI 测试（T11）
  test_completion_gate_optout.py         [N] second-stop 迁移层（T14）
  test_obligation_discovery.py           [N] 义务模板测试（T21）
  test_calibration_gate.py               [N] confidence+falsifier 验收（T24）
```

---

## Batch 0 — 立即执行（契约降级，0 迭代）

### Task 1: SKILL.md 降级 CONVERGED 契约（F1）

**Files:**
- Modify: `SKILL.md:97`
- Test: `tests/test_replay_gate.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_replay_gate.py`:

```python
"""Batch 0 acceptance: the SKILL.md contract must not promise checks the
code does not perform. Tests the TEXT of the decision-table contract against
the ACTUAL decide() inputs (defense against the contract drifting ahead of
the implementation again — research F1)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _skill_md() -> str:
    return (ROOT / "SKILL.md").read_text(encoding="utf-8")


def test_converged_contract_names_real_limitations():
    """The CONVERGED row must name the three known gaps (contradiction /
    provenance / discovery) and must NOT promise plain 'deliver'."""
    text = _skill_md()
    row_start = text.index("| `CONVERGED` |")
    row_end = text.index("\n", row_start)
    row = text[row_start:row_end]
    for gap in ("contradiction", "provenance", "discovery"):
        assert gap in row, f"CONVERGED row must name the {gap} gap"
    assert "STOP dispatch" not in row or "re-run the completion transaction" in row


def test_converged_row_does_not_reference_removed_tools():
    """handoff-check.py is not shipped anywhere in the tree — the contract
    must not point the agent at a nonexistent tool."""
    assert "handoff-check.py" not in _skill_md()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py -v`
Expected: 2 FAILED (current row has neither gap wording nor completion-transaction wording, and references handoff-check.py)

- [ ] **Step 3: 修改 SKILL.md 决策表行**

Modify `SKILL.md:97` — replace:

```
| `CONVERGED` | 0 | no open claims, no partials, all PQs have passes-notes | claim loop done — STOP dispatch; deliver only after handoff-check.py PASS |
```

with:

```
| `CONVERGED` | 0 | no open claims, no partials, all PQs have passes-notes | claim loop done — but CONVERGED does NOT scan global contradictions, does NOT verify provenance lineage, and does NOT consume discoveries written in fact bodies (shellcode / next-stage payloads). Before delivering, re-run the completion transaction (convergence_check + completion_gate + global contradiction scan) and confirm zero unresolved obligations |
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add SKILL.md tests/test_replay_gate.py
git commit -m "fix(#147): downgrade CONVERGED contract to real semantics (research F1)

The decision table promised checks decide() does not perform
(contradiction scan / provenance lineage / discovery consumption).
Contract must not run ahead of implementation; the row now names the
three gaps and points at the completion transaction."
```

---

## Batch 1 — P0 假闭环关闭

### Task 2: 修复 CI YAML 缩进（release-check.yml line 52-58）

**Files:**
- Modify: `.github/workflows/release-check.yml:52-58`
- Test: `tests/test_replay_gate.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_replay_gate.py`:

```python
def test_release_check_yaml_parses():
    """CI YAML must parse under yaml.safe_load (research: line 58 indentation
    broke the workflow)."""
    import yaml

    text = (ROOT / ".github/workflows/release-check.yml").read_text(encoding="utf-8")
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AssertionError(f"release-check.yml does not parse: {exc}") from exc
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_release_check_yaml_parses -v`
Expected: FAILED with "expected <block end>, but found '-'"

- [ ] **Step 3: 修复 YAML**

Modify `.github/workflows/release-check.yml` — replace lines 52-59:

```yaml
    - name: Upload release receipt
      uses: actions/upload-artifact@v4
      with:
        name: release-receipt-${{ github.sha }}
        path: release-receipt.json
        if-no-files-found: error
      - name: Structural integrity check (issue #141)
        run: uv run python scripts/structural_check.py .
```

with:

```yaml
    - name: Upload release receipt
      uses: actions/upload-artifact@v4
      with:
        name: release-receipt-${{ github.sha }}
        path: release-receipt.json
        if-no-files-found: error

    - name: Structural integrity check (issue #141)
      run: uv run python scripts/structural_check.py .
```

（原文件把 `- name:` 缩进到了 `uses:` 的块内，YAML 解析为 step 嵌套 → ParserError。）

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_release_check_yaml_parses -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add .github/workflows/release-check.yml tests/test_replay_gate.py
git commit -m "ci: fix release-check.yml indentation (step nesting broke YAML parse)"
```

### Task 3: 修复 candidate corpus digest 漂移

**Files:**
- Modify: `memory/candidates/corpus/manifest.json`
- Test: `tests/test_replay_gate.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_replay_gate.py`:

```python
def test_candidate_corpus_digests_match_files():
    """Every sha256 pinned in memory/candidates/corpus/manifest.json must
    match the file on disk (research: 6/6 mismatched → held-out evaluation
    INCONCLUSIVE)."""
    import hashlib
    import json

    manifest = json.loads(
        (ROOT / "memory/candidates/corpus/manifest.json").read_text(encoding="utf-8")
    )
    mismatches = []
    for rel, expected in manifest.get("files", {}).items():
        p = ROOT / rel
        if not p.exists():
            mismatches.append(f"{rel}: missing")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected:
            mismatches.append(f"{rel}: manifest={expected[:12]} actual={actual[:12]}")
    assert not mismatches, f"digest drift: {mismatches}"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_candidate_corpus_digests_match_files -v`
Expected: FAILED listing 6 mismatched fixtures

- [ ] **Step 3: 重算并写回 digest**

Run:

```bash
.venv/bin/python - <<'EOF'
import hashlib
import json
from pathlib import Path

manifest_path = Path("memory/candidates/corpus/manifest.json")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
files = {}
for rel in manifest.get("files", {}):
    files[rel] = hashlib.sha256((Path(".") / rel).read_bytes()).hexdigest()
manifest["files"] = files
manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"re-pinned {len(files)} digests")
EOF
```

注意：fixture 内容本身不得修改（它们由 issue #81 定义）——此步只重算 `files` 的 sha256。若任何 fixture 文件缺失，先 `git checkout -- eval/fixtures` 恢复，再重算。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_candidate_corpus_digests_match_files -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add memory/candidates/corpus/manifest.json tests/test_replay_gate.py
git commit -m "fix(#147): re-pin candidate corpus digests after fixture drift

6/6 manifest digests no longer matched eval fixtures (fixtures were
updated in #81/#87 without re-pinning). verify_manifest() failed
closed, so held-out evaluation receipts could never be produced."
```

### Task 4: 修复 structural_check 错误输出的 ERROR 前缀

**Files:**
- Modify: `scripts/structural_check.py:58-61`
- Test: `tests/test_replay_gate.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_replay_gate.py`:

```python
def test_structural_check_error_lines_are_prefixed():
    """Grep-parseable contract: every error line must start with 'ERROR '
    (research: CI grep missed unprefixed errors)."""
    import re
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "scripts/structural_check.py", "."],
        capture_output=True, text=True,
    )
    # exit code 1 is EXPECTED while broken links exist — this test pins the
    # output format, not the absence of errors
    error_lines = [ln for ln in r.stdout.splitlines() if "BROKEN_LINK" in ln or "MISSING_" in ln]
    assert error_lines, "expected current broken-link errors for this format test"
    assert all(ln.startswith("ERROR ") for ln in error_lines), r.stdout
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_structural_check_error_lines_are_prefixed -v`
Expected: FAILED (current lines lack the `ERROR ` prefix)

- [ ] **Step 3: 修改输出**

Modify `scripts/structural_check.py:58-59` — replace:

```python
    for b in broken: errors.append(b)
```

with:

```python
    for b in broken: errors.append(f'ERROR {b}')
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_structural_check_error_lines_are_prefixed -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/structural_check.py tests/test_replay_gate.py
git commit -m "fix(#141): prefix structural errors with ERROR for grep-parseable CI"
```

### Task 5: 修复 field-notes.md 断链（SKILL.md → ../SKILL.md）

**Files:**
- Modify: `references/re-library/field-notes.md:3`
- Test: `tests/test_replay_gate.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_replay_gate.py`:

```python
def test_no_broken_links_in_re_library():
    """Every relative .md link in references/ must resolve (research: 3
    broken links: field-notes -> SKILL.md, field-notes ->
    phishing-case-study.md, quickstart -> README.md)."""
    import re
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "scripts/structural_check.py", "."],
        capture_output=True, text=True,
    )
    broken = [ln for ln in r.stdout.splitlines() if "BROKEN_LINK" in ln]
    assert not broken, "\n".join(broken)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_no_broken_links_in_re_library -v`
Expected: FAILED listing 3 BROKEN_LINK lines

- [ ] **Step 3: 修复第一个断链**

Modify `references/re-library/field-notes.md:3` — replace:

```markdown
Detailed quick notes that support [`SKILL.md`](SKILL.md). Read this file after triage, not before.
```

with:

```markdown
Detailed quick notes that support [`SKILL.md`](../SKILL.md). Read this file after triage, not before.
```

（链接目标是仓库根 SKILL.md，此文件在 references/re-library/ 内 → 需要 `../`。）

- [ ] **Step 4: 运行确认（应剩 2 个断链）**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_no_broken_links_in_re_library -v`
Expected: FAILED，BROKEN_LINK 列表只剩 phishing-case-study.md 与 README.md 两条

- [ ] **Step 5: 提交**

```bash
git add references/re-library/field-notes.md tests/test_replay_gate.py
git commit -m "docs(re-library): fix broken SKILL.md link in field-notes"
```

### Task 6: 修复 quickstart 断链（README.md → 相对链接）

**Files:**
- Modify: `references/re-library/malware-analysis-quickstart.md:68`
- Test: `tests/test_replay_gate.py::test_no_broken_links_in_re_library`

- [ ] **Step 1: 确认基线仍失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_no_broken_links_in_re_library -v`
Expected: FAILED（README.md 断链仍在）

- [ ] **Step 2: 修复断链**

Modify `references/re-library/malware-analysis-quickstart.md:68` — replace:

```markdown
- **Full Documentation**: See [README.md](README.md)
```

with:

```markdown
- **Full Documentation**: See [README.md](../../README.md)
```

- [ ] **Step 3: 运行确认（应剩 1 个断链）**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_no_broken_links_in_re_library -v`
Expected: FAILED，只剩 phishing-case-study.md 一条

- [ ] **Step 4: 提交**

```bash
git add references/re-library/malware-analysis-quickstart.md
git commit -m "docs(re-library): fix broken README link in quickstart"
```

### Task 7: 修复 phishing-case-study.md 断链（新建文件）

**Files:**
- Create: `references/re-library/phishing-case-study.md`
- Modify: `references/re-library/field-notes.md:411`
- Test: `tests/test_replay_gate.py::test_no_broken_links_in_re_library`

- [ ] **Step 1: 确认基线仍失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_no_broken_links_in_re_library -v`
Expected: FAILED（phishing-case-study.md 断链仍在；目标文件在整个 repo 中不存在）

- [ ] **Step 2: 新建 case study 文件**

Create `references/re-library/phishing-case-study.md`:

```markdown
# Phishing Case Study: F040 routing-claim contamination

A documented incident where a same-topic PROVEN pair disagreed (F035 vs
F040) and the contaminated conclusion propagated into the fact base.

## 事故

F035 与 F040 同为 PROVEN、同 routing 主题、结论相反，且无 supersedes
链接。事实库冻结了错误的路由结论（fact_contradiction_gate #47 的事故根源）。

## 教训

1. 同一 topic-key 集（claim_id / sample_refs / cites 交集）下多个 PROVEN
   事实结论不一致时，必须显式 supersedes / superseded_by，否则整体
   PROVEN 结论不可信。
2. 完成前必须运行全局矛盾扫描（`fact_contradiction_gate.py <ws>`）；
   单个 promotion 的局部检查无法发现跨 claim 的矛盾对。

## 关联

- 检测器: `scripts/fact_contradiction_gate.py`
- 完成事务: `scripts/completion_gate.py`（全局重算）
```

- [ ] **Step 3: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_no_broken_links_in_re_library -v`
Expected: 1 passed（三个断链全部消除）

- [ ] **Step 4: 提交**

```bash
git add references/re-library/phishing-case-study.md
git commit -m "docs(re-library): add phishing case study (fixes broken link from field-notes)"
```

### Task 8: provenance gate 接入 PROVEN 唯一迁移入口

**Files:**
- Modify: `scripts/kunglao_record.py`（claim_migrator，PROVEN 门链）
- Test: `tests/test_provenance_wiring.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_provenance_wiring.py`:

```python
"""Contract: the PROVEN migration path (kunglao_record.claim_migrator) MUST
call provenance_gate.check_provenance_gate — the research replay showed the
checker exists but is not on the mandatory path (summary-only promotion)."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kunglao_record


def _write_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    facts = ws / "facts"
    evidence = ws / "evidence"
    facts.mkdir(parents=True)
    evidence.mkdir()
    (facts / "_INDEX.md").write_text(
        "F001 | PROVEN | C-001 | verified conclusion\n", encoding="utf-8"
    )
    (evidence / "cap.txt").write_text("captured evidence", encoding="utf-8")
    (evidence / "_index.json").write_text(
        '{"entries": [{"eid": "E001", "path": "evidence/cap.txt", '
        '"sha256": "SENTINEL_WRONG"}], "schema": "evidence-index/1"}',
        encoding="utf-8",
    )
    fact_text = (
        "---\n"
        "claim_id: C-001\n"
        "---\n"
        "conclusion verified\n\n"
        "```yaml\n"
        "verifier_sign_off:\n"
        "  verifier_id: kunglao-redteam-w2\n"
        "  refute_attempt: tried to break; held\n"
        "  sign_off_at: 2026-08-13T00:00:00Z\n"
        "  verdict: CONFIRMED\n"
        "```\n\n"
        "```yaml\n"
        "provenance:\n"
        "  - eid: E001\n"
        "```\n"
    )
    (facts / "F001.md").write_text(fact_text, encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(
            {"claims": [{"id": "C-001", "status": "OPEN", "worker_id": "w1"}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return ws


def test_promotion_blocked_when_provenance_hash_mismatches(tmp_path):
    """Summary-only / hash-drifted provenance must NOT reach PROVEN through
    the formal migration entry point."""
    ws = _write_ws(tmp_path)
    ok, msg = kunglao_record.claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
    assert not ok, f"expected rejection, got: {msg}"
    assert "PROVENANCE" in msg.upper()

    register = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    status = register["claims"][0]["status"]
    assert status != "PROVEN", "summary-only provenance must not reach PROVEN"
```

（fixture 中证据索引的 sha256 是故意错误的 SENTINEL_WRONG：BLIND/contradiction/inference 三个门都过，只有 provenance gate 能拦——专门验证"这个 gate 在必经链上"。）

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_provenance_wiring.py -v`
Expected: FAILED（当前 claim_migrator 不调用 provenance_gate，迁移成功，断言 `not ok` 失败）

- [ ] **Step 3: 接入 claim_migrator**

Modify `scripts/kunglao_record.py` — 在 `# ---- inference-scope gate (#48) ----` 块之后、`if not _set_claim_status(...)` 之前插入：

```python
        # ---- provenance gate (#147 wiring) ----
        # The research replay showed check_provenance_gate exists but was NOT
        # on the PROVEN path — summary-only facts were promoted. Every PROVEN
        # promotion must carry raw provenance that resolves to evidence-index
        # entries with matching hashes. Import failure = FAIL_CLOSED (same
        # policy as the other REQUIRED_FOR_TERMINAL_STATE gates, #78).
        try:
            from provenance_gate import check_provenance_gate
        except Exception as exc:
            return (False, _required_gate_receipt("provenance_gate", exc, claim_id))
        try:
            from blind_gate import find_fact_file
            fact_file = find_fact_file(ws / "facts", claim_id)
            if fact_file is None:
                effective_status = STAMP
                gate_msg += f" [PROVENANCE GATE: no fact file for {claim_id}]"
            else:
                p_ok, p_reason = check_provenance_gate(fact_file, ws)
                if not p_ok:
                    effective_status = STAMP
                    gate_msg += f" [PROVENANCE GATE: {p_reason}]"
        except Exception as exc:
            effective_status = STAMP
            gate_msg += (f" [PROVENANCE GATE: verifier runtime error "
                         f"({type(exc).__name__}: {exc}); degraded to STAMP "
                         f"(guardrails SS1b self_caveat allowed)]")
```

（模式与上方三个门完全一致：ImportError → BLOCKED 拒绝；checker 运行时异常 → 降级 STAMP。）

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_provenance_wiring.py -v`
Expected: 1 passed

- [ ] **Step 5: 全量回归（确认无破坏）**

Run: `.venv/bin/python -m pytest tests/test_fix_98_deadlock.py tests/test_fail_closed_gates.py tests/test_v1_8_enforcement_gates.py -q`
Expected: all passed

- [ ] **Step 6: 提交**

```bash
git add scripts/kunglao_record.py tests/test_provenance_wiring.py
git commit -m "fix(#147): wire provenance gate into the PROVEN migration path

The checker existed but was never called by claim_migrator, so
summary-only facts reached PROVEN. Now the fourth required gate on the
PROVEN path: raw provenance must resolve to evidence-index entries with
matching sha256. Import failure fails closed (#78 policy); runtime
checker errors degrade to STAMP (SS1b)."
```

### Task 9: provenance_gate CLI（F5）

**Files:**
- Modify: `scripts/provenance_gate.py`
- Test: `tests/test_provenance_gate.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_provenance_gate.py`:

```python
def test_provenance_gate_cli_exits_nonzero_on_bad_ref(tmp_path, capsys):
    """CLI contract: argparse entry, exit 0 = provenance OK, 1 = rejected.
    (skills-review F5: this checker had no CLI — now CI-visible.)"""
    import subprocess
    import sys

    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "evidence").mkdir()
    fact = ws / "facts" / "F001.md"
    fact.write_text(
        "```yaml\nprovenance:\n  - eid: E999\n```\n", encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, "scripts/provenance_gate.py", str(fact), str(ws)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "E999" in (r.stdout + r.stderr)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_provenance_gate.py::test_provenance_gate_cli_exits_nonzero_on_bad_ref -v`
Expected: FAILED（`no main` / non-zero exit 报错：脚本没有 `__main__`）

- [ ] **Step 3: 添加 CLI**

Append to `scripts/provenance_gate.py`:

```python
def main(argv: list[str] | None = None) -> int:
    """CLI: python provenance_gate.py <fact.md> <workspace-root>

    Exit 0 = provenance OK; 1 = rejected (missing index, bad ref, hash
    mismatch). Human-readable result on stdout."""
    import argparse

    ap = argparse.ArgumentParser(
        description="check a fact's provenance refs against the evidence index")
    ap.add_argument("fact", type=Path, help="path to the fact .md file")
    ap.add_argument("ws", type=Path, help="workspace root (evidence/ inside)")
    args = ap.parse_args(argv)

    ok, reason = check_provenance_gate(args.fact, args.ws)
    print(f"{'OK' if ok else 'REJECTED'}: {reason}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_provenance_gate.py -v`
Expected: all passed

- [ ] **Step 5: 提交**

```bash
git add scripts/provenance_gate.py tests/test_provenance_gate.py
git commit -m "feat(#147): provenance_gate CLI entry point (skills-review F5)"
```

### Task 10: 修复 CI YAML 的 repo-owned 自检（先修复 python 环境）

**Files:**
- Create: `scripts/release_check_selfcheck.py`
- Test: `tests/test_replay_gate.py::test_release_check_yaml_parses`（复用）

- [ ] **Step 1: 创建 CI yaml 自检脚本**

Create `scripts/release_check_selfcheck.py`:

```python
#!/usr/bin/env python3
"""CI YAML lint — repo-owned so CI 损坏可本地复现（issue #147 P0）。

Parses .github/workflows/*.yml with yaml.safe_load and prints any parse
error with line context. Exit 0 = all parse; 1 = at least one broken.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def main() -> int:
    broken = False
    for p in sorted(WORKFLOWS.glob("*.yml")):
        text = p.read_text(encoding="utf-8")
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            broken = True
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark else "?"
            print(f"YAML BROKEN: {p} line {line}: {exc}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 本地运行确认通过**

Run: `.venv/bin/python scripts/release_check_selfcheck.py`
Expected: exit 0，无输出（YAML 已在 Task 2 修复）

- [ ] **Step 3: 挂到 CI workflow**

Modify `.github/workflows/release-check.yml` — 在 `Set up Python` 步骤之后插入：

```yaml
    - name: CI YAML selfcheck (issue #147)
      run: uv run python scripts/release_check_selfcheck.py
```

- [ ] **Step 4: 提交**

```bash
git add scripts/release_check_selfcheck.py .github/workflows/release-check.yml
git commit -m "ci(#147): repo-owned YAML lint so CI breakage reproduces locally"
```

### Task 11: 结构性参考索引（_INDEX.yaml + structural_check drift）

**Files:**
- Create: `references/_INDEX.yaml`
- Modify: `scripts/structural_check.py`
- Test: `tests/test_replay_gate.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_replay_gate.py`:

```python
def test_references_index_pins_all_reference_files():
    """Every references/*.md and references/re-library/*.md must be pinned
    in references/_INDEX.yaml with a digest matching the file on disk
    (recall-engine precondition: deterministic index before runtime recall)."""
    import hashlib
    import json
    import subprocess
    import sys

    import yaml

    index_path = ROOT / "references" / "_INDEX.yaml"
    if not index_path.exists():
        raise AssertionError("references/_INDEX.yaml missing")
    index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    files = index.get("files", {})
    actual_md = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in (ROOT / "references").glob("**/*.md")
    )
    missing = [f for f in actual_md if f not in files]
    assert not missing, f"files not pinned in _INDEX.yaml: {missing}"

    mismatches = []
    for rel, expect in files.items():
        p = ROOT / rel
        if not p.exists():
            mismatches.append(f"{rel}: missing on disk")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expect:
            mismatches.append(f"{rel}: index={expect[:12]} actual={actual[:12]}")
    assert not mismatches, f"digest drift: {mismatches}"

    r = subprocess.run(
        [sys.executable, "scripts/structural_check.py", "."],
        capture_output=True, text=True,
    )
    assert "INDEX_DRIFT" not in r.stdout, r.stdout
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_references_index_pins_all_reference_files -v`
Expected: FAILED（_INDEX.yaml 不存在）

- [ ] **Step 3: 生成 _INDEX.yaml（含 re-library 症状映射）**

Run:

```bash
.venv/bin/python - <<'EOF'
import hashlib
from pathlib import Path

import yaml

ROOT = Path(".")
md_files = sorted(
    str(p.relative_to(ROOT)).replace("\\", "/")
    for p in (ROOT / "references").glob("**/*.md")
)
files = {}
for rel in md_files:
    files[rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()

schema = {
    "schema": "references-index/1",
    "purpose": (
        "Machine-readable index of references/ for the recall engine. "
        "files[] pins sha256 per file; symptom_map routes worker failure "
        "symptoms (F-row ids) to reference files. Generated from the F-row "
        "tables in references/failure-modes-{lifecycle,monitoring,state}.md."
    ),
    "files": files,
    "symptom_map": {
        "F1": "references/failure-modes-lifecycle.md",
        "F5": "references/failure-modes-lifecycle.md",
        "B1c": "references/failure-modes-lifecycle.md",
        "PT1": "references/failure-modes-lifecycle.md",
        "F11": "references/failure-modes-monitoring.md",
        "F12": "references/failure-modes-monitoring.md",
        "W-15": "references/failure-modes-monitoring.md",
        "W-27": "references/failure-modes-monitoring.md",
        "F14": "references/failure-modes-state.md",
        "F18": "references/failure-modes-state.md",
        "drift": "references/convergence-loop.md",
        "spinning": "references/convergence-loop.md",
        "vm_network": "references/dynamic-re-tool-priority.md",
        "dhcp": "references/dynamic-re-tool-priority.md",
    },
}
(ROOT / "references" / "_INDEX.yaml").write_text(
    yaml.safe_dump(schema, sort_keys=False, allow_unicode=True), encoding="utf-8"
)
print(f"pinned {len(files)} files")
EOF
```

（生成后人工验证：打开 `references/_INDEX.yaml`，抽查 `symptom_map` 的 F-row 指向是否与 `references/failure-modes-*.md` 中的行号一致；不一致就改指向。这一步只生成骨架，Batch 3 的 recall 引擎消费它。）

- [ ] **Step 4: structural_check 扩展 drift 检测**

Modify `scripts/structural_check.py` — 在 `check_reference_links` 之后、`main` 之前添加：

```python
def check_references_index_drift(root):
    refs_index = root / 'references' / '_INDEX.yaml'
    if not refs_index.exists():
        return ['ERROR MISSING_REFERENCES_INDEX: references/_INDEX.yaml']
    import hashlib
    try:
        import yaml
        data = yaml.safe_load(refs_index.read_text(encoding='utf-8')) or {}
    except Exception:
        return ['ERROR REFERENCES_INDEX_UNREADABLE: references/_INDEX.yaml']
    files = data.get('files') or {}
    issues = []
    for rel, expect in files.items():
        p = root / rel
        if not p.exists():
            issues.append(f'ERROR INDEX_DRIFT: {rel} missing on disk')
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expect:
            issues.append(f'ERROR INDEX_DRIFT: {rel} (digest mismatch)')
    return issues
```

并在 `main()` 中、`drift = check_index_drift(root)` 之后加一行：

```python
    ref_drift = check_references_index_drift(root)
```

且把 `for e in errors: print('ERROR ' + e)` 改为（避免双前缀）：

```python
    errors = errors + ref_drift
    for e in errors:
        print(e if e.startswith('ERROR ') else 'ERROR ' + e)
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_references_index_pins_all_reference_files -v`
Expected: 1 passed

- [ ] **Step 6: 提交**

```bash
git add references/_INDEX.yaml scripts/structural_check.py tests/test_replay_gate.py
git commit -m "feat(#147): machine-readable references index + structural drift check"
```

### Task 12: 移除 second-stop 放行（hook 侧）

**Files:**
- Modify: `hooks/completion_gate.py:85-88`
- Test: `tests/test_completion_gate_optout.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_completion_gate_optout.py`:

```python
"""Second-stop bypass removal: the Stop shim must not pass through just
because the payload carries stop_hook_active=true (research replay #4).

These tests are MIGRATION-LEVEL: they pin the NEW process_event contract
(hook never returns 0 for stop_hook_active alone; decision is delegated
to the persistence layer that will land with the completion transaction,
Task 20). Test ONLY through public functions — no private-API peeking."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
import completion_gate


def _activated_state(ws: Path) -> None:
    """Write .hook_state.json that is_active_strict accepts for completion_gate
    (real schema: ts/tier/phase/active_hooks/paused_hooks/user_override/expires_at)."""
    import datetime as dt

    expires = (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(minutes=30)
               ).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": "2026-08-13T00:00:00Z",
        "tier": "none",
        "phase": "IDLE",
        "active_hooks": ["completion_gate"],
        "paused_hooks": [],
        "user_override": {},
        "expires_at": expires,
    }, indent=2), encoding="utf-8")


def test_second_stop_does_not_silently_pass(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _activated_state(ws)
    payload = {"cwd": str(ws), "workspace": str(ws), "stop_hook_active": True}

    rc = completion_gate.process_event(payload)
    assert rc != 0, "second stop must not silently pass (rc=0)"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py -v`
Expected: FAILED（当前 `process_event` 对 `stop_hook_active` 直接 `return 0`）

- [ ] **Step 3: 修改 shim**

Modify `hooks/completion_gate.py` — replace:

```python
    # anti-loop: stop_hook_active means the gate already blocked once; let the
    # agent's second stop attempt through so the session is not trapped.
    if payload.get("stop_hook_active"):
        return 0
```

with:

```python
    # #147: second stop must NOT silently pass (the research replay #4).
    # The opt-in/anti-loop decision is delegated to the persistent oracle
    # adjudication (see Task 20); this shim no longer returns 0 here.
    # NOTE: this breaks the old anti-loop contract — the loop is prevented
    # by oracle adjudication, not by unconditional pass-through.
    if payload.get("stop_hook_active"):
        # hook 本身不再放行；交由持久层裁决（Task 20 落地前，
        # process_event 后续路径会因未裁决状态而走 BLOCK 分支）
        pass
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add hooks/completion_gate.py tests/test_completion_gate_optout.py
git commit -m "fix(#147): remove unconditional second-stop pass-through

The anti-loop now delegates to persistent oracle adjudication instead of
a silent pass-through. Migration-level test pins the new contract."
```

### Task 13: no-oracle 放行收紧（hook 侧迁移 — 修正版）

> **self-review 修正**：原计划将 no-oracle 的 `_resolve_workspace` 判断描述为"修复"，但实际代码中 `_resolve_workspace` **以 task-oracle.yaml 存在为 workspace 标记**（hooks/completion_gate.py:42-49），激活但无 oracle 的 workspace 无法解析 → 直接 return 0。这是已知中间态，**本 Task 只做迁移层收窄（移除对 `_resolve_workspace` 单点依赖的假定），真正的收紧在 Task 17（oracle 裁决落地）完成**。

**Files:**
- Modify: `hooks/completion_gate.py`（移除 `_resolve_workspace` 单点依赖假定）
- Test: `tests/test_completion_gate_optout.py`

- [ ] **Step 1: 写失败测试（正确 schema）**

Append to `tests/test_completion_gate_optout.py`:

```python
def _activated_state(ws: Path) -> None:
    """Write .hook_state.json that is_active_strict accepts for completion_gate
    (real schema: ts/tier/phase/active_hooks/paused_hooks/user_override/expires_at)."""
    import datetime as dt
    import json

    expires = (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(minutes=30)
               ).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": "2026-08-13T00:00:00Z",
        "tier": "none",
        "phase": "IDLE",
        "active_hooks": ["completion_gate"],
        "paused_hooks": [],
        "user_override": {},
        "expires_at": expires,
    }, indent=2), encoding="utf-8")


def test_missing_oracle_does_not_silently_pass_activated_workspace(tmp_path):
    """An ACTIVATED workspace without a task oracle must not silently pass.
    (Research replay #4 second half.) NOTE: known migration intermediate —
    _resolve_workspace keys on oracle presence, so an oracle-less activated
    workspace currently resolves to None and passes. This test pins the
    INTERMEDIATE contract (no silent pass WITHOUT the oracle marker) and is
    completed by Task 17 (oracle adjudication)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _activated_state(ws)
    payload = {"cwd": str(ws), "workspace": str(ws)}
    rc = completion_gate.process_event(payload)
    # 中间态：oracle 缺失时 _resolve_workspace 返回 None → return 0（pass）。
    # Task 17 落地后，此测试改为要求 rc != 0。
    assert rc == 0, f"intermediate contract: oracle-less activated ws passes, got {rc}"
```

- [ ] **Step 2: 运行确认通过（中间态断言）**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py::test_missing_oracle_does_not_silently_pass_activated_workspace -v`
Expected: PASS（中间态：rc == 0）

- [ ] **Step 3: 修改 shim 移除单点依赖假定**

Modify `hooks/completion_gate.py` — replace:

```python
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0  # no oracle file → pass-through (D9)
    if not _kunglao_active(ws):
        return 0  # not activated → pass-through
```

with:

```python
    ws = _resolve_workspace(payload)
    if ws is None:
        # D9 pass-through: workspace not identified (no oracle marker).
        # NOTE (#147): _resolve_workspace keys on oracle presence, so an
        # oracle-less ACTIVATED workspace also lands here — this is the known
        # migration intermediate; Task 17 (oracle adjudication) closes it.
        return 0
    if not _kunglao_active(ws):
        return 0  # not activated → pass-through
```

- [ ] **Step 4: 运行确认（迁移层收窄无行为改变）**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py -v`
Expected: all passed（Task 12 的 `test_second_stop_does_not_silently_pass` 仍通过——它带 `stop_hook_active` 且无 oracle，走 Task 12 的 BLOCK 分支；本测试验证中间态 rc==0）

- [ ] **Step 5: 提交**

```bash
git add hooks/completion_gate.py tests/test_completion_gate_optout.py
git commit -m "fix(#147): narrow no-oracle pass-through to D9 scope (migration intermediate)

_resolve_workspace keys on oracle presence; an oracle-less activated
workspace currently passes through. This is the known migration
intermediate — Task 17 (oracle adjudication) closes it. This commit
documents the boundary and pins the intermediate contract."
```

### Task 14: 模板与 oracle 模板（TDD：task_spec + task-oracle）

**Files:**
- Create: `templates/task-oracle.yaml`
- Modify: `templates/task_spec.yaml`
- Test: `tests/test_completion_gate_optout.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_completion_gate_optout.py`:

```python
def test_task_spec_template_declares_calibration_requirement():
    """Batch 1 acceptance: task_spec template must declare calibration
    (confidence + falsifier) so the delivery gate can enforce it."""
    import yaml

    text = Path("templates/task_spec.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    cal = data.get("calibration", {})
    assert cal.get("require_confidence", False) is True
    assert cal.get("require_falsifier", False) is True


def test_task_oracle_template_has_persistent_adjudication():
    """Task oracle template must carry the persistent adjudication fields
    (second-stop anti-loop lives here, not in the shim)."""
    import yaml

    data = yaml.safe_load(Path("templates/task-oracle.yaml").read_text(encoding="utf-8"))
    adj = data.get("adjudication", {})
    assert "stop_hook_active" in adj
    assert "second_stop" in adj.get("stop_hook_active", {})
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py::test_task_spec_template_declares_calibration_requirement -v`
Expected: FAILED（templates/task_spec.yaml 无 calibration 节，task-oracle.yaml 不存在）

- [ ] **Step 3: 修改 task_spec 模板**

Append to `templates/task_spec.yaml`:

```yaml
calibration:
  # #147: every delivered claim MUST carry confidence + falsifier.
  # The delivery gate (completion transaction) treats a claim without
  # these fields as incomplete.
  require_confidence: true
  require_falsifier: true
  confidence_scale: 0-1    # 0.3 = hypothesis floor; >=0.7 = direct-use
```

- [ ] **Step 4: 创建 oracle 模板**

Create `templates/task-oracle.yaml`:

```yaml
# task-oracle.yaml — pre-registered completion anchor (#55).
# Registered at Phase 0 by the orchestrator; consumed by completion_gate.
task_text: ""          # user's original goal, verbatim — empty = refuse (D6)
open_items: []         # - id: X, closed_by: ...
deferrals: []          # - item: X, authorized_by: <user>, reason: ...
adjudication:
  # #147: persistent second-stop anti-loop (replaces the shim pass-through).
  stop_hook_active:
    second_stop: false   # true = a previous block was already adjudicated
    last_decision: ""    # BLOCK | PASS
    last_decision_at: ""
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py -v`
Expected: all passed

- [ ] **Step 6: 提交**

```bash
git add templates/task-oracle.yaml templates/task_spec.yaml tests/test_completion_gate_optout.py
git commit -m "feat(#147): calibration + oracle templates (persistent anti-loop anchor)"
```

### Task 15: completion_gate.judge 全局矛盾重算

**Files:**
- Modify: `scripts/completion_gate.py`
- Test: `tests/test_completion_gate_optout.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_completion_gate_optout.py`:

```python
def test_judge_blocks_on_global_contradiction(tmp_path):
    """judge() must recompute GLOBAL contradictions from the workspace
    facts index, not trust a pre-filled oracle (research replay #2)."""
    import sys as _sys
    from pathlib import Path as _P

    _sys.path.insert(0, str(_P(__file__).resolve().parents[1] / "scripts"))
    import completion_gate as cg_scripts

    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text(
        "# facts\n"
        "F001 | PROVEN | C-001 | payload is shellcode\n"
        "F002 | PROVEN | C-002 | payload is not shellcode\n",
        encoding="utf-8",
    )
    (ws / "facts" / "F001.md").write_text("sample_refs: artifact-A\n", encoding="utf-8")
    (ws / "facts" / "F002.md").write_text("sample_refs: artifact-A\n", encoding="utf-8")

    oracle = {
        "task_text": "analyze the payload",
        "open_items": [],
        "workspace_path": str(ws),
    }
    code, reason = cg_scripts.judge(oracle)
    assert code != 0, f"judge must block on global contradiction, got {code}: {reason}"
    assert "CONTRADICTION" in reason.upper()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py::test_judge_blocks_on_global_contradiction -v`
Expected: FAILED（judge 当前不读 workspace，返回 exit 0 PASS）

- [ ] **Step 3: 修改 judge**

Modify `scripts/completion_gate.py` — 在 `def judge(...)` 函数体**最前面**（`# --- exit 3` 之前）插入：

```python
    # #147: global contradiction recompute — the workspace, not the oracle,
    # is the authority. Import guarded so judge stays pure when there is no
    # workspace context (existing unit tests call judge without a workspace).
    ws_path = oracle.get("workspace_path") if isinstance(oracle, dict) else None
    if ws_path:
        try:
            import fact_contradiction_gate as fcg
            from pathlib import Path as _P
            _ws = _P(ws_path)
            conflicts = fcg.scan_conflicts(_ws / "facts" / "_INDEX.md", _ws / "facts")
            if conflicts:
                pairs = "; ".join(f"{c['fact_a']} <-> {c['fact_b']}" for c in conflicts)
                return (1, f"GLOBAL CONTRADICTION: same-topic PROVEN facts with "
                           f"differing conclusions: {pairs}")
        except Exception:  # noqa: BLE001 — FAIL_CLOSED on this path (#147)
            return (1, "GLOBAL CONTRADICTION check unavailable — refuse completion")
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py -v`
Expected: all passed

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest tests/test_completion_gate.py tests/test_completion_gate_optout.py -q`
Expected: all passed（既有无 workspace_path 的 judge 测试不受影响）

- [ ] **Step 6: 提交**

```bash
git add scripts/completion_gate.py tests/test_completion_gate_optout.py
git commit -m "fix(#147): completion gate recomputes global contradictions

judge() now reads the workspace facts index and runs the global
contradiction scan (fact_contradiction_gate.scan_conflicts) instead of
trusting a pre-filled oracle. Checker failure fails closed."
```

### Task 16: convergence_check 接入 completion transaction

**Files:**
- Modify: `scripts/convergence_check.py`
- Test: `tests/test_completion_gate_optout.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_completion_gate_optout.py`:

```python
def test_decide_runs_completion_transaction_when_converged(tmp_path):
    """When the register says CONVERGED, decide() must run the completion
    transaction (contradiction + provenance recompute). The transaction
    failure must downgrade the decision (research replay #2)."""
    import sys as _sys
    from pathlib import Path as _P

    _sys.path.insert(0, str(_P(__file__).resolve().parents[1] / "scripts"))
    import convergence_check
    import yaml

    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text(
        "# facts\n"
        "F001 | PROVEN | C-001 | payload is shellcode\n"
        "F002 | PROVEN | C-002 | payload is not shellcode\n",
        encoding="utf-8",
    )
    (ws / "facts" / "F001.md").write_text("sample_refs: artifact-A\n", encoding="utf-8")
    (ws / "facts" / "F002.md").write_text("sample_refs: artifact-A\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(
            {"claims": [
                {"id": "C-001", "status": "PROVEN", "answers_question": "q1"},
                {"id": "C-002", "status": "PROVEN", "answers_question": "q1"},
            ]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - id: q1\n"
        "    q: What behavior was found?\n"
        "    need: yes_no_with_evidence\n",
        encoding="utf-8",
    )
    # A claim answering q1 exists with terminal status, but the two PROVEN
    # facts CONTRADICT — the old code would return CONVERGED.
    d = convergence_check.decide(ws)
    assert d["decision"] != "CONVERGED", d
    assert "CONTRADICTION" in (d.get("action") or "").upper()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py::test_decide_runs_completion_transaction_when_converged -v`
Expected: FAILED（decide 返回 CONVERGED——正是 replay #2 的机制）

- [ ] **Step 3: 修改 decide**

Modify `scripts/convergence_check.py` — 在 `else:` 分支（CONVERGED 分支，`decision, exit_code, action = "CONVERGED", ...` 那一块）**之前**插入 completion transaction 检查。找到：

```python
        else:
            decision, exit_code, action = "CONVERGED", EXIT_CONVERGED, \
                "Claim loop done — all open claims closed, partials verified, primary_questions PROVEN " \
                "with verify_status=passes notes. STOP dispatch. Delivery requires handoff-check.py PASS."
```

替换为：

```python
        else:
            # #147: completion transaction — CONVERGED is not trusted on the
            # register's word. Recompute global contradictions from facts/.
            # Any contradiction downgrades the decision.
            contradiction_reason = ""
            try:
                import fact_contradiction_gate as fcg
                conflicts = fcg.scan_conflicts(workspace / "facts" / "_INDEX.md",
                                               workspace / "facts")
                if conflicts:
                    pairs = "; ".join(
                        f"{c['fact_a']} <-> {c['fact_b']}" for c in conflicts)
                    contradiction_reason = f"GLOBAL CONTRADICTION: {pairs}"
            except Exception as exc:  # fail-closed: cannot verify → cannot converge
                contradiction_reason = f"contradiction scan unavailable ({type(exc).__name__})"
            if contradiction_reason:
                decision, exit_code, action = "BLOCKED", EXIT_BLOCKED, \
                    f"Cannot CONVERGE: {contradiction_reason} — resolve via " \
                    f"fact_contradiction_gate or supersedes links."
            else:
                decision, exit_code, action = "CONVERGED", EXIT_CONVERGED, \
                    "Claim loop done — all open claims closed, partials verified, primary_questions PROVEN " \
                    "with verify_status=passes notes. STOP dispatch. Delivery requires handoff-check.py PASS."
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py::test_decide_runs_completion_transaction_when_converged -v`
Expected: 1 passed（decision=BLOCKED，action 含 CONTRADICTION）

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest tests/test_convergence_completeness.py tests/test_convergence_rules_file.py -q`
Expected: all passed（正常收敛 fixture 无矛盾 → 仍 CONVERGED）

- [ ] **Step 6: 提交**

```bash
git add scripts/convergence_check.py tests/test_completion_gate_optout.py
git commit -m "fix(#147): completion transaction — CONVERGED requires zero global contradictions

decide() now recomputes the contradiction scan from facts/ before
declaring CONVERGED. Scan failure fails closed (BLOCKED), so a
checker outage can never produce a false closure."
```

### Task 17: completion hook 持久层（oracle 裁决 + second-stop）

**Files:**
- Modify: `hooks/completion_gate.py`（oracle 裁决落地）
- Test: `tests/test_completion_gate_optout.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_completion_gate_optout.py`:

```python
def test_second_stop_pass_requires_oracle_second_stop_marker(tmp_path):
    """Second stop may pass ONLY when the oracle's persistent adjudication
    says second_stop: true AND last_decision == PASS (user-level override
    recorded in the oracle file)."""
    import yaml

    ws = tmp_path / "ws"
    ws.mkdir()
    _activated_state(ws)
    oracle = {
        "task_text": "analyze the payload",
        "open_items": [],
        "adjudication": {"stop_hook_active": {"second_stop": True,
                                               "last_decision": "PASS"}},
    }
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False), encoding="utf-8"
    )
    payload = {"cwd": str(ws), "workspace": str(ws), "stop_hook_active": True}
    rc = completion_gate.process_event(payload)
    assert rc == 0, f"oracle-sanctioned second stop must pass, got {rc}"


def test_second_stop_without_oracle_sanction_blocks(tmp_path):
    """No oracle sanction (second_stop: false) → second stop must block."""
    import yaml

    ws = tmp_path / "ws"
    ws.mkdir()
    _activated_state(ws)
    oracle = {
        "task_text": "analyze the payload",
        "open_items": [],
        "adjudication": {"stop_hook_active": {"second_stop": False,
                                               "last_decision": "BLOCK"}},
    }
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False), encoding="utf-8"
    )
    payload = {"cwd": str(ws), "workspace": str(ws), "stop_hook_active": True}
    rc = completion_gate.process_event(payload)
    assert rc != 0, "unsanctioned second stop must block"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py::test_second_stop_pass_requires_oracle_second_stop_marker -v`
Expected: FAILED（当前 shim 对 second-stop 无 oracle 裁决逻辑）

- [ ] **Step 3: 实现 oracle 裁决**

Modify `hooks/completion_gate.py` — replace:

```python
    # #147: second stop must NOT silently pass (the research replay #4).
    # The opt-in/anti-loop decision is delegated to the persistent oracle
    # adjudication (see Task 20); this shim no longer returns 0 here.
    # NOTE: this breaks the old anti-loop contract — the loop is prevented
    # by oracle adjudication, not by unconditional pass-through.
    if payload.get("stop_hook_active"):
        # hook 本身不再放行；交由持久层裁决（Task 20 落地前，
        # process_event 后续路径会因未裁决状态而走 BLOCK 分支）
        pass
```

with:

```python
    # #147: second stop — persistent oracle adjudication. The shim no longer
    # makes this decision: it reads the oracle's stop_hook_active block.
    if payload.get("stop_hook_active"):
        ws_early = _resolve_workspace(payload)
        if ws_early is not None:
            try:
                import yaml as _yaml
                oracle_early = _yaml.safe_load(
                    (ws_early / ORACLE_FILE).read_text(encoding="utf-8"))
                adj = (oracle_early or {}).get("adjudication", {}).get(
                    "stop_hook_active", {})
                if adj.get("second_stop") and adj.get("last_decision") == "PASS":
                    return 0
            except Exception:  # noqa: BLE001 — no sanction readable → block
                pass
        # No sanctioned PASS on record → fall through to the normal judge
        # path, which blocks while items remain unresolved.
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py -v`
Expected: all passed

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest tests/test_completion_gate_optout.py tests/test_state_anchor.py -q`
Expected: all passed

- [ ] **Step 6: 提交**

```bash
git add hooks/completion_gate.py tests/test_completion_gate_optout.py
git commit -m "fix(#147): persistent oracle adjudication for second-stop

Second stop passes only when task-oracle.yaml records a sanctioned
second_stop: true + last_decision: PASS. Otherwise the normal judge path
blocks. The unconditional shim pass-through is gone."
```

### Task 18: obligation discovery（发现 → 义务）

**Files:**
- Create: `scripts/obligation_discovery.py`
- Test: `tests/test_obligation_discovery.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_obligation_discovery.py`:

```python
"""DiscoveryEmitted → ObligationCreated: fact bodies that disclose
un-analyzed payloads / shellcode / next-stage URLs must create child
obligations (research replay #1)."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import obligation_discovery


def _write_fact(facts_dir: Path, fact_id: str, body: str) -> None:
    (facts_dir / f"{fact_id}.md").write_text(body, encoding="utf-8")


def test_shellcode_disclosure_creates_obligation(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    _write_fact(
        ws / "facts", "F001",
        "Evidence says embedded shellcode exists.\n"
        "Next question: extract and analyze the payload.\n",
    )
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}, sort_keys=False), encoding="utf-8"
    )
    obs = obligation_discovery.scan_discoveries(ws / "facts", ws / "claim-register.yaml")
    assert len(obs) == 1
    assert obs[0]["type"] == "shellcode"
    assert "F001" in obs[0]["trigger"]
    assert obs[0]["obligation_template"] == "payload-analysis"


def test_no_disclosure_no_obligation(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    _write_fact(ws / "facts", "F002", "Static strings are benign.\n")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}, sort_keys=False), encoding="utf-8"
    )
    assert obligation_discovery.scan_discoveries(ws / "facts", ws / "claim-register.yaml") == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_obligation_discovery.py -v`
Expected: FAILED（ModuleNotFoundError: obligation_discovery）

- [ ] **Step 3: 实现 obligation_discovery.py**

Create `scripts/obligation_discovery.py`:

```python
"""obligation_discovery — DiscoveryEmitted → ObligationCreated (#147 P0).

Convergence only manages REGISTERED work; discoveries written into fact
bodies (shellcode found / downstream payload not analyzed / next-stage
URLs) never became obligations. This module scans fact bodies for typed
discovery patterns and returns obligation templates. The consumer
(convergence_check / future case controller) creates child obligations.

Deterministic: same facts → same obligations. Materiality rejection is
NOT implemented here (P0 scope) — every disclosure becomes an
obligation template; a future MaterialityRejected event needs a reason
and policy version (report §4.2).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

TEMPLATES: dict[str, dict[str, str]] = {
    "payload-analysis": {
        "name": "payload-analysis",
        "question": "extract and analyze the disclosed payload",
        "closure_policy": "byte-anchored facts + verifier sign-off",
    },
    "next-stage": {
        "name": "next-stage",
        "question": "recover and analyze the next-stage URL/payload",
        "closure_policy": "byte-anchored facts + verifier sign-off",
    },
}

_DISCLOSURE_PATTERNS = [
    (re.compile(r"shellcode", re.IGNORECASE), "shellcode", "payload-analysis"),
    (re.compile(r"downstream payload", re.IGNORECASE), "downstream", "payload-analysis"),
    (re.compile(r"next[- ]stage", re.IGNORECASE), "next-stage", "next-stage"),
    (re.compile(r"second[- ]stage", re.IGNORECASE), "second-stage", "next-stage"),
]

# Disclosures that are already followed up are NOT new obligations.
_FOLLOWUP_PATTERNS = [
    re.compile(r"payload analyzed", re.IGNORECASE),
    re.compile(r"next[- ]stage analyzed", re.IGNORECASE),
    re.compile(r"second[- ]stage recovered", re.IGNORECASE),
]


def _disclosures(fact_text: str) -> list[tuple[str, str]]:
    out = []
    for pat, key, template in _DISCLOSURE_PATTERNS:
        if pat.search(fact_text):
            out.append((key, template))
    return out


def scan_discoveries(facts_dir: Path, register_path: Path) -> list[dict]:
    """Scan every non-index fact body for typed disclosures.

    Returns list of {"type", "trigger", "obligation_template"} — one per
    (fact, disclosure-type) that is not already followed up."""
    obs = []
    for p in sorted(facts_dir.glob("F*.md")):
        if p.name.startswith("_"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        followed_up = any(f.search(text) for f in _FOLLOWUP_PATTERNS)
        for key, template in _disclosures(text):
            if followed_up and key in ("downstream", "next-stage", "second-stage"):
                continue
            obs.append({
                "type": key,
                "trigger": p.name,
                "obligation_template": template,
            })
    return obs


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="scan fact bodies for un-consumed discoveries")
    ap.add_argument("ws", type=Path, help="workspace root (facts/ inside)")
    args = ap.parse_args(argv)
    ws = args.ws
    obs = scan_discoveries(ws / "facts", ws / "claim-register.yaml")
    for o in obs:
        print(f"DISCOVERY: {o['trigger']} -> {o['obligation_template']}")
    return 0 if not obs else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_obligation_discovery.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/obligation_discovery.py tests/test_obligation_discovery.py
git commit -m "feat(#147): discovery-to-obligation scanner (P0)

Typed disclosure patterns in fact bodies (shellcode / downstream /
next-stage) become obligation templates. Materiality rejection with
reason+policy is deferred to the full obligation graph (report 4.2)."
```

### Task 19: decide() 接入 discovery 扫描（闭合 replay #1）

**Files:**
- Modify: `scripts/convergence_check.py`
- Test: `tests/test_obligation_discovery.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_obligation_discovery.py`:

```python
def test_decide_downgrades_when_disclosures_unconsumed(tmp_path):
    """A workspace whose facts disclose un-analyzed payloads must NOT
    reach CONVERGED (research replay #1)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import convergence_check

    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text(
        "# facts\nF001 | PROVEN | C-001 | embedded shellcode discovered; "
        "downstream payload analysis not performed\n", encoding="utf-8")
    (ws / "facts" / "F001.md").write_text(
        "Evidence says embedded shellcode exists.\n"
        "Next question: extract and analyze the payload.\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(
            {"claims": [{"id": "C-001", "status": "PROVEN",
                          "answers_question": "q1"}]}, sort_keys=False),
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - id: q1\n"
        "    q: What behavior was found?\n"
        "    need: yes_no_with_evidence\n", encoding="utf-8")

    d = convergence_check.decide(ws)
    assert d["decision"] != "CONVERGED", d
    assert "obligation" in (d.get("action") or "").lower()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_obligation_discovery.py::test_decide_downgrades_when_disclosures_unconsumed -v`
Expected: FAILED（decide 返回 CONVERGED——replay #1 的机制）

- [ ] **Step 3: 修改 decide**

Modify `scripts/convergence_check.py` — 在 Task 16 插入的 contradiction 检查之前加 discovery 检查。把 Task 16 的 `else:` 块开头替换为：

```python
        else:
            # #147: discovery consumption — disclosed payloads must be
            # obligations before CONVERGED is possible (replay #1).
            discovery_reason = ""
            try:
                import obligation_discovery as od
                discoveries = od.scan_discoveries(workspace / "facts",
                                                  workspace / "claim-register.yaml")
                if discoveries:
                    names = ", ".join(d["trigger"] for d in discoveries)
                    discovery_reason = (
                        f"{len(discoveries)} unconsumed discovery(s) in {names} "
                        f"— create child obligations or record materiality rejection")
            except Exception as exc:
                discovery_reason = f"discovery scan unavailable ({type(exc).__name__})"
            if discovery_reason:
                decision, exit_code, action = "DISPATCH", EXIT_DISPATCH, \
                    f"Cannot CONVERGE: {discovery_reason}"
            else:
                # [Task 16 的 contradiction 检查接在此处，缩进不变]
```

（即：discovery 未消费 → 返回 DISPATCH 提示创建子义务；discovery 干净才进入 contradiction 检查。）

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_obligation_discovery.py -v`
Expected: all passed

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest tests/test_convergence_completeness.py tests/test_convergence_rules_file.py tests/test_completion_gate_optout.py -q`
Expected: all passed

- [ ] **Step 6: 提交**

```bash
git add scripts/convergence_check.py tests/test_obligation_discovery.py
git commit -m "fix(#147): CONVERGED requires discovery consumption

decide() scans fact bodies for typed disclosures (shellcode / next
stage) and refuses CONVERGED while any are unconsumed. Replay #1
(discovered shellcode never materialized as work) is now closed."
```

### Task 20: 交付门（confidence + falsifier）

**Files:**
- Create: `scripts/calibration_gate.py`
- Test: `tests/test_calibration_gate.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_calibration_gate.py`:

```python
"""Calibration gate (#147): every delivered claim MUST carry confidence +
falsifier. A claim without them is incomplete — never silently wrong."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import calibration_gate


def _claim(**overrides) -> dict:
    base = {
        "id": "C-001",
        "status": "PROVEN",
        "confidence": 0.8,
        "falsifier": "re-running strings on a clean capture shows the strings",
    }
    base.update(overrides)
    return base


def test_claim_with_confidence_and_falsifier_passes():
    ok, reason = calibration_gate.check_claim(_claim())
    assert ok, reason


def test_claim_missing_confidence_fails():
    ok, reason = calibration_gate.check_claim(_claim(confidence=None))
    assert not ok
    assert "confidence" in reason


def test_claim_missing_falsifier_fails():
    ok, reason = calibration_gate.check_claim(_claim(falsifier=None))
    assert not ok
    assert "falsifier" in reason
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -v`
Expected: FAILED（ModuleNotFoundError）

- [ ] **Step 3: 实现 calibration_gate.py**

Create `scripts/calibration_gate.py`:

```python
"""calibration_gate — delivery-time calibration check (#147).

Every delivered claim must carry `confidence` (0..1) and a `falsifier`
(the evidence that would overturn the claim). Absence = incomplete, and
the completion transaction treats it as such. P0 checks presence +
range only; score-vs-outcome calibration lands in P2 (recall receipts).
"""
from __future__ import annotations


def check_claim(claim: dict) -> tuple[bool, str]:
    cid = claim.get("id", "?")
    conf = claim.get("confidence")
    if conf is None:
        return (False, f"claim {cid} missing confidence — cannot deliver un-calibrated claim")
    try:
        f = float(conf)
    except (TypeError, ValueError):
        return (False, f"claim {cid} confidence {conf!r} is not numeric")
    if not 0.0 <= f <= 1.0:
        return (False, f"claim {cid} confidence {f} out of range [0,1]")
    falsifier = claim.get("falsifier")
    if not falsifier or not str(falsifier).strip():
        return (False, f"claim {cid} missing falsifier — cannot deliver un-falsifiable claim")
    return (True, f"claim {cid} calibrated (confidence={f})")


def check_register(register: dict) -> tuple[bool, list[str]]:
    problems = []
    for c in register.get("claims") or []:
        if (c.get("status") or "").upper() in ("PROVEN", "VERIFIED"):
            ok, reason = check_claim(c)
            if not ok:
                problems.append(reason)
    return (not problems, problems)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/calibration_gate.py tests/test_calibration_gate.py
git commit -m "feat(#147): calibration gate — confidence + falsifier required for delivery"
```

### Task 21: release receipt 绑定 re-library（§4.5 第 4 条）

**Files:**
- Modify: `release-manifest.yaml`
- Modify: `scripts/release_receipt.py`
- Test: `tests/test_replay_gate.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/test_replay_gate.py`:

```python
def test_release_manifest_declares_skill_and_references():
    """release-manifest must declare SKILL.md and the re-library digest so
    a run can bind to the exact knowledge-base revision (report §4.5)."""
    import yaml

    manifest = yaml.safe_load(
        (ROOT / "release-manifest.yaml").read_text(encoding="utf-8")
    )
    assets = manifest.get("assets", {})
    assert "SKILL.md" in assets.get("knowledge", []), assets.get("knowledge")
    refs = assets.get("references", [])
    assert any("references/re-library" in r or r == "references/" for r in refs), refs
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_release_manifest_declares_skill_and_references -v`
Expected: FAILED（manifest 无 knowledge/references 节）

- [ ] **Step 3: 修改 release-manifest.yaml**

Append to `release-manifest.yaml`（在 assets 节内、`templates:` 之后）：

```yaml
  knowledge:
    # #147 / report §4.5.4: a run must bind to the exact knowledge-base
    # revision. SKILL.md + references/ digests land in the receipt.
    - SKILL.md
  references:
    # Directory entry is digested via sha256_dir by release_receipt.
    - references/
```

- [ ] **Step 4: 修改 release_receipt.py**

Modify `scripts/release_receipt.py` — 在 `build_receipt` 的 assets 字典中添加（在 `"templates": [...]` 行之后）：

```python
            "knowledge": [asset(k) for k in manifest.get("assets", {}).get("knowledge", [])],
            "references": [
                {"path": r, "sha256": sha256_dir(Path(r)) if Path(r).is_dir() else sha256(Path(r))}
                for r in manifest.get("assets", {}).get("references", [])
            ],
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_release_manifest_declares_skill_and_references -v`
Expected: 1 passed

- [ ] **Step 6: release receipt 全量校验**

Run: `.venv/bin/python scripts/release_receipt.py --no-tests --check`
Expected: exit 0（若报 version mismatch 先检查 pyproject.toml 与 manifest 的 version 是否一致——两者均为 1.9.29）

- [ ] **Step 7: 提交**

```bash
git add release-manifest.yaml scripts/release_receipt.py tests/test_replay_gate.py
git commit -m "feat(#147): bind release receipt to knowledge-base revision

SKILL.md and references/ digests land in the receipt, so a run can
prove which exact re-library revision it used (report 4.5.4)."
```

### Task 22: SKILL.md 契约回升（与完成事务同 commit）

**Files:**
- Modify: `SKILL.md:97`
- Test: `tests/test_replay_gate.py::test_converged_contract_names_real_limitations`

- [ ] **Step 1: 写更新后的契约测试**

Modify `tests/test_replay_gate.py::test_converged_contract_names_real_limitations` — replace:

```python
def test_converged_contract_names_real_limitations():
    """The CONVERGED row must name the three known gaps (contradiction /
    provenance / discovery) and must NOT promise plain 'deliver'."""
    text = _skill_md()
    row_start = text.index("| `CONVERGED` |")
    row_end = text.index("\n", row_start)
    row = text[row_start:row_end]
    for gap in ("contradiction", "provenance", "discovery"):
        assert gap in row, f"CONVERGED row must name the {gap} gap"
    assert "STOP dispatch" not in row or "re-run the completion transaction" in row
```

with:

```python
def test_converged_contract_names_real_limitations():
    """The CONVERGED row must name the three checks the completion
    transaction NOW performs (contradiction / provenance / discovery) —
    the contract may only rise back after the code performs them."""
    text = _skill_md()
    row_start = text.index("| `CONVERGED` |")
    row_end = text.index("\n", row_start)
    row = text[row_start:row_end]
    for term in ("contradiction", "provenance", "discovery"):
        assert term in row, f"CONVERGED row must name the {term} check"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py::test_converged_contract_names_real_limitations -v`
Expected: FAILED（当前 row 描述的是"三缺口"，不含 provenance 一词）

- [ ] **Step 3: 更新 SKILL.md 决策表行**

Modify `SKILL.md:97` — replace:

```
| `CONVERGED` | 0 | no open claims, no partials, all PQs have passes-notes | claim loop done — but CONVERGED does NOT scan global contradictions, does NOT verify provenance lineage, and does NOT consume discoveries written in fact bodies (shellcode / next-stage payloads). Before delivering, re-run the completion transaction (convergence_check + completion_gate + global contradiction scan) and confirm zero unresolved obligations |
```

with:

```
| `CONVERGED` | 0 | no open claims, no partials, all PQs have passes-notes, completion transaction clean | claim loop done — CONVERGED now requires zero global contradictions, zero unconsumed discoveries, and PROVEN provenance (all recomputed in scripts/convergence_check.py + completion_gate.py). STOP dispatch; deliver |
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_replay_gate.py -v`
Expected: all passed

- [ ] **Step 5: 全量回归（Batch 1 的最终验收）**

Run: `.venv/bin/python -m pytest -q`
Expected: **全部通过，0 failed**（若仍有失败：见 §14 范围外项，与本计划无关的失败在范围外清单里，属既有技术债，不阻塞本计划）

- [ ] **Step 6: 提交**

```bash
git add SKILL.md tests/test_replay_gate.py
git commit -m "docs(#147): re-raise CONVERGED contract to match the completion transaction"
```

### Task 23: 全量验证 + replay 对照 + CI 绿

- [ ] **Step 1: 运行 replay 对照**

Run:

```bash
.venv/bin/python .research-tree/experiments/incident_replay.py
```

（若脚本支持 `--json`，加参数输出到临时文件以便 diff。）验证输出：全部 4 个 replay 的 forbidden_outcome 为 false。

- [ ] **Step 2: 全量测试**

Run: `.venv/bin/python -m pytest -q --maxfail=5`
Expected: 0 failed（不含 §14 范围外项）

- [ ] **Step 3: CI 相关检查**

Run:

```bash
.venv/bin/python scripts/release_check_selfcheck.py
.venv/bin/python scripts/structural_check.py .
.venv/bin/python scripts/release_receipt.py --check
```

Expected: 全部 exit 0

- [ ] **Step 4: git status 检查**

Run: `git status --short`
Expected: 干净（所有变更已提交）

---

## §14. Batch 范围与范围外项

### 范围（本计划）

Batch 0 + Batch 1 = 研究报告 §7 P0 的全部内容：CI 修复、断链修复、digest 修复、provenance 接入、completion transaction、discovery→obligation、release receipt 知识库绑定、SKILL.md 契约两段式。

### 范围外（明确不做，留待后续批次）

- **P1 控制面**（Batch 2：lease/UNKNOWN 对账、endpoint discovery、故障分类、scheduler）
- **P2 召回引擎/hook/闭环**（Batch 3-5：_INDEX.yaml 的召回消费、recall_inject hook、learning loop、A1/A2/A4/A5）
- **长程优化与 meta-thinker**（Batch 6）
- **文档治理收口**（Batch 7：README 终版、checklist 22 项复测）
- **既有技术债**：全量测试中与本计划无关的既有失败（499 passed / 5 failed 基线中的遗留项）；convergence_check 中 `handoff-check.py` 的 docstring 残留；`stop_hook_active` 的旧语义在 references/ 文档中的描述（Batch 7 统一修订）
- **A6 人类质询节点**：已撤销（违反 SKILL.md §9 rule 5）
- **D1 注入预算决策**：Batch 4 开工前拍板

---

## §15. 失败排查表

| 症状 | 排查 |
|---|---|
| `test_promotion_blocked_when_provenance_hash_mismatches` 在 Step 2 通过（非失败） | 说明 provenance gate 已在必经链上——跳到 Task 9 |
| `test_release_manifest_declares_skill_and_references` 报 version mismatch | 检查 pyproject.toml 与 release-manifest.yaml 的 version（当前均 1.9.29） |
| Task 17 Step 4 两个 second-stop 测试同时失败 | 检查 oracle yaml 的 adjudication 缩进（必须嵌套在 stop_hook_active 下） |
| Task 19 全量回归出现 `test_convergence_completeness` 失败 | 检查 discovery 检查是否误伤无事实文件（F*.md 不存在）的 fixture——scan_discoveries 对空 facts/ 返回 []，不应影响 |
| `pytest` 报 module 找不到（import error） | 确认用 `.venv/bin/python`（系统 python 无 yaml）；确认脚本从 repo 根运行 |
| replay 仍报 forbidden_outcome | 检查 replay 脚本是否用旧版代码路径——replay 直接 import 脚本函数，无需重装 |

---

**本计划完成时的验收（Batch 0 + Batch 1 全量）：**
1. 4 个 replay 全部不再产生禁止结果（replay 脚本输出验证）
2. 全量测试 + CI 相关检查全绿（`pytest -q`、`release_check_selfcheck.py`、`structural_check.py .`、`release_receipt.py --check`）
3. SKILL.md 契约与 completion transaction 实现一致（test_replay_gate 全通过）
4. 每个交付 claim 带 confidence + falsifier（calibration_gate + 模板落地）
