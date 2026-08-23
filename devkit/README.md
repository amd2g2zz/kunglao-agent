# devkit/ — development scaffolding (NOT shipped product)

> 一切开发者自用、不随产品发布的工具,集中在这里。
> 与 `scripts/`(产品源码)严格分离 — `scripts/` 是发布面。

## 完整目录结构

```
devkit/
├── README.md                 ← 你在这里
├── quality_gates.py          ← 质量门 runner(门数 = GATES 注册表,勿在文档复制计数)
├── pass_rate_metric.py       ← CI metric 提取
├── install_git_hooks.py      ← 把 githooks/ 部署到 .git/hooks/
├── githooks/                 ← hook 模板(原样,带 __KUNGLAO_DEVKIT_ROOT__ 占位符)
│   └── pre-commit
├── docs/                     ← devkit 自己的文档
│   ├── README.md
│   ├── quality_gates.md      ← 质量门框架(#463 初版图示 + 后续门追加说明)
│   ├── quality_roadmap.md    ← KPI 跟踪
│   ├── defect_escape_rate.md
│   └── unit_test_spec.md     ← 单元测试编写规范
└── tests/                    ← (Phase 2) devkit 自己的测试
```

## 这是什么 / 不是什么

| ✅ 在 devkit/ | ❌ 不在 devkit/ |
|---|---|
| 质量门 runner (`quality_gates.py`) | 产品 CLI (`kunglao.py`) |
| CI metric 提取 (`pass_rate_metric.py`) | 产品 toolchain (`toolchain.py`) |
| Git hook 部署 (`install_git_hooks.py`) | 业务逻辑 (`init_state.py`) |
| Mutation testing 助手 (Phase 2) | 任何被产品 import 的模块 |
| Fault injection fixtures (Phase 2) | |

## 为什么独立目录

- **发布面纯粹**:`scripts/` 里的内容会被打包 / 上传到 plugin marketplace;
  不能混入只在开发期有用的工具。
- **故障隔离**:CI 调 `devkit/quality_gates.py` 时,即使 devkit 出问题,
  也不会污染产品路径(`sys.path.insert(0, "scripts")` 仍是产品)。
- **跨平台**:`devkit/` 只放 Python(无 bash)。Windows / Linux / macOS 同行为。
- **Git hook 与产品隔离**:产品 `.claude/git-hooks/pre-commit`(review gate)
  和 devkit `githooks/pre-commit`(quality gate)是不同概念,各自独立。

## 与质量门框架的关系

```python
# devkit/quality_gates.py 是质量门的 runner;门清单的唯一来源是其
# GATES 注册表(本文不复制计数 — 派生不复制,#446 G 类):
Gate 1 (Requirement Correctness) — 验 scripts/ 里的契约模块能 import
Gate 2 (Regression Safety)       — 调 pytest(在 tests/ 跑)
Gate 3 (Engineering Quality)     — pytest --collect-only
Gate 4 (Test Effectiveness)      — mutmut 可用性
Gate 5 (Subagent Review)         — .subagent-review 执行层证据(#462)
Gate 6 (Agents Contract)         — agents/*.md 三要素声明 lint(#492)
Gate 7 (Doc Sync)                — 写作层漂移门(#446)
```

devkit/ 只关心**怎么跑 gates**;**每个 gate 该验什么**写在 `devkit/docs/`。

## 安装 git hook(强制 commit 走质量门)

```bash
# 安装(把 devkit/githooks/pre-commit 部署到 .git/hooks/pre-commit)
uv run python devkit/install_git_hooks.py

# 预览不真装
uv run python devkit/install_git_hooks.py --dry-run

# 卸载(只卸 devkit 装的,非 devkit 的 hook 不动)
uv run python devkit/install_git_hooks.py --uninstall
```

安装后,每次 commit 自动跑 hook 模板声明的快速门集(GATES 注册表减去
opt-in 的 Gate 2,<10s)。

跑 Gate 2 (full pytest, ~3min) 需要 opt-in:
```bash
export KUNGLAO_DEV_GATE2=1
```

## 跨目录依赖

| from | to | 为什么 |
|---|---|---|
| `devkit/*.py` | `scripts/*.py` | devkit 验产品契约是否在位(只 import,不调用业务逻辑) |
| `devkit/*.py` | `tests/` | devkit 调 pytest(无代码 import,subprocess 而已) |
| `tests/*.py` | `scripts/*.py` | 产品测试 import 产品代码(单向) |
| `tests/test_devkit_*.py` | `devkit/*.py` | devkit 自己的测试 |
| 任何目录 | `devkit/` | **禁止**产品代码 import devkit/ |

## 怎么运行

```bash
# 全跑
uv run python devkit/quality_gates.py

# 跑特定 gate
uv run python devkit/quality_gates.py 1 2

# 静默
uv run python devkit/quality_gates.py --quiet

# devkit 自己的测试
uv run python -m pytest tests/test_devkit_*.py
```

## 不变性

- devkit/ 永远**不会被** `release-manifest.yaml` `assets:` 收编(它是 dev-only)
- devkit/ 永远**不会被** `scripts/README.md` 列在产品脚本清单里
- devkit/ 里的脚本**必须** 跨平台 Python;新增代码评审时这是 P0
- devkit/githooks/ 里的 hook 模板**必须** 含 `__KUNGLAO_DEVKIT_ROOT__` 占位符
  (不允许 hardcode 路径 — installer 才会 stamp)

## 见

- `devkit/docs/quality_gates.md` — 质量门框架定义
- `devkit/docs/quality_roadmap.md` — KPI 跟踪
- `devkit/docs/unit_test_spec.md` — 单元测试编写规范
- `openspec/changes/issue-463-coverage-gate/` — 完整 spec