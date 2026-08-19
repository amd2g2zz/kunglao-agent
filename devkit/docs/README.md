# devkit/docs/ — developer-facing policy & KPI tracking (NOT shipped product)

> 一切给开发者读、不给用户看的文档,集中在这里。
> 与 `docs/`(产品文档)严格分离 — `docs/` 是 README / changelog / 用户教程。

## 这是什么 / 不是什么

| ✅ 在 devkit/docs/ | ❌ 不在 devkit/docs/ |
|---|---|
| 4-Gate 质量门框架 (`quality_gates.md`) | README / 用户面向教程 |
| KPI 跟踪 (`quality_roadmap.md`) | CHANGELOG(发布给用户) |
| Defect Escape 跟踪 (`defect_escape_rate.md`) | API reference |
| 单元测试编写规范 (`unit_test_spec.md`) | |
| 内部 ADR / 设计 rationale | |
| 故障注入技术规范 (Phase 2) | |

## 为什么在 devkit/ 下

devkit/ 是个完整的开发工作目录(`代码`+`文档`+`hook`+`fixture`):
```
devkit/
├── *.py            可执行工具
├── install_git_hooks.py
├── docs/           ← 你在这里
└── tests/          (Phase 2:devkit/ 自己的测试)
```

devkit/docs/ 是 devkit/ 的内嵌子目录,**不是** 顶层目录 —
让 devkit/ 自身是个完整包,可以独立 clone / 走 review。

## 与 devkit 其它部分的关系

| 路径 | 内容 |
|---|---|
| `devkit/*.py` | 可执行(工具脚本) |
| `devkit/install_git_hooks.py` | 把 `.githooks/*` 部署到 `.git/hooks/` |
| `devkit/docs/*.md` | 只读(政策/规范) |
| `devkit/tests/`(Phase 2)| devkit 自己的测试 |

## 与 docs/(产品文档)的关系

| devkit/docs/ | docs/ |
|---|---|
| 给开发者读 | 给用户读 |
| 内部 KPI、gate 框架、unit test 规范 | README / 安装 / 教程 |
| 仓库内部演进 | 随版本发布 |
| 所有者:开发团队 | 所有者:产品/DX |

## 见

- `devkit/README.md` — devkit 总目录约定
- `docs/`(如有)— 产品文档
- `openspec/changes/issue-463-coverage-gate/` — 4-gate 框架来源
