# Tasks — issue-477-deploy-completion

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/477` branch
  `v012/issue-477-deploy-completion` off `origin/dev` afaae75
- [x] 1.2 必读:plan(Task 2 / 验收方法 A)/ issue #477 正文 /
  toolchain_install.py(INSTALL_PLANS + ask_then_install)/ toolchain.py
  (CHECK_SETS / FIXES / NextAction / #449 Requirements)/ env_manifest.py
  (#450)/ toolchain_negotiation.py(#451)/ #462 契约(垫片标注即弃)

## 2. SDD

- [x] 2.1 proposal.md(四证据 + 四改动面 + 不做边界)
- [x] 2.2 design.md(D1 管理器模型 / D2 解析模型 / D3 数据与覆盖率
  封闭声明 / D4 deploy_shim / D5 闭环 / D6 测试映射 / R1-R5)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红;新文件函数内 import)

- [x] 3.1 `tests/test_pkg_detect.py` — 词汇表封闭 / which-first +
  known-path 回退 / win32 winget-无-choco / apt known-path / 半装态
  ghidra 探测 / MANAGERS↔plans 引用完整性(红)
- [x] 3.2 `tests/test_deploy_shim.py` — deploy argv / 幂等两轮 /
  re-probe 门 / android-server / 台账 / new 面(README+字段+校验+
  拒覆盖)(红)
- [x] 3.3 `tests/test_toolchain_install.py` 扩容 — 覆盖率封闭声明
  (29 = 17 ∪ 12)/ install_commands 探测驱动(改写平台矩阵测试)/
  resolve_install 四 mode / ④ ask_then_install 装后台账 / CLI 一条命令
  端到端(红)
- [x] 3.4 `tests/test_env_manifest.py` 扩容 — record_installed 六面
  (新建/合并/保留/覆盖/garbage 拒写/非字符串)(红)
- [x] 3.5 `tests/test_toolchain_negotiation.py` — NEGOTIABLE 派生集
  钉值更新(数据扩容,派生逻辑不变)
- [x] 3.6 确认 RED:新测试 + 扩容测试全红,基线 93 项不受影响

## 4. GREEN

- [x] 4.1 `scripts/pkg_detect.py`(D1:Manager/ManagerHit/
  detect_managers/find_ghidra_install,只读)
- [x] 4.2 `scripts/toolchain_install.py`(D2/D3:PkgSpec +
  InstallResolution + resolve_install + INSTALL_PLANS 17 项 +
  NOT_AUTO_INSTALLABLE + _run_install_plan 重写 + ④ 台账接线)
- [x] 4.3 `scripts/env_manifest.py`(D5:record_installed)
- [x] 4.4 `scripts/deploy_shim.py`(D4:deploy 面 + new 面)
- [x] 4.5 `scripts/README.md` 增两行(pkg_detect.py / deploy_shim.py)
- [x] 4.6 快检全绿:`uv run python -m pytest -q -m "not load_sensitive"
  tests/test_toolchain_install.py tests/test_init_toolchain_gate.py
  tests/test_env_manifest.py` + 新测试文件

## 5. 门与产出

- [x] 5.1 `uv run ruff check .` 零红
- [x] 5.2 `uv run python devkit/quality_gates.py 1 3 4 5 6 7` ALL-PASS
- [x] 5.3 `.subagent-review/2026-08-20-477.json`(5 字段,
  verified_by=pending-477-reviewer)
- [x] 5.4 `.review/RUNBOOK.md`(不提交)
