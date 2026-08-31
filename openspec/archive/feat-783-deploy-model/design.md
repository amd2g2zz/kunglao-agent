# Design decisions（裁决点）

## D1 manifest 格式
`deploy-manifest.yaml`（repo 根，release-manifest 兄弟）：
```yaml
schema_version: "1"
files:
  - {src: hooks/dispatch_gate.py, dest: .claude/hooks/dispatch_gate.py, kind: hook}
  - {src: agents/kunglao-worker.md, dest: .claude/agents/kunglao-worker.md, kind: agent}
```
生成器 scripts/deploy_manifest.py 提供 `--verify`（sha256 全量校验）。manifest 自身 sha 进入 stamp。

## D2 运行命令形态
**决策：workspace venv 直跑 `python`** —— settings 命令 `{venv_python} {ws}/.claude/hooks/<name>.py`（相对 ws 写作 `.venv/Scripts|bin/python` 由 init 平台分支拼接；缺 venv 回退 `python`）。摆脱 uv 对技能包锁定；依赖面已收敛在 cryptography/pyyaml 之外的 stdlib+已装包。settings 输出统一 PosixPath 字符串。

## D3 手改部署件处置
默认 **覆盖 + WARN 明细**（items[] 标 `changed:<name>` 与 `overwritten-modified:[names]` sha 对照表），不做交互询问（无头友好）；被覆盖前原内容落 `runs/deploy-backup-<ts>/` 留证。

## D4 孤儿判定
清道夫删除条件（双确认）：文件位于 `.claude/hooks|.claude/agents` ∧ 不在当前 manifest 目标集 ∧ sha ≠ 任一历史清单版本可得的记录→ 记 runs 报告 WARN-only。

## D5 stamp 口径
template_version 渲染行追加 `deploy-manifest: <sha256>`；check-stale envelope 增字段 tolerated；RC=5 判定仍只看 semver——语义保真。

## D6 测试矩阵
RED->GREEN 集：manifest 存在性与 P0 名单、copy 幂等（同 sha skip）、覆盖改 stamped 工程演示、孤儿双确认负样本、stale 门回归不动。
