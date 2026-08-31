# Proposal: 部署模型反转 — 工程 .claude/ 本地化部署（#783）

## Why
现在 init/upgrade 只写 settings.json 命令行指向技能包绝对路径：升级全局包即刻影响所有存量工程、插件目录移动即失效、工程不可自包含迁移。用户裁决 2026-08-27 要求部署面反转进工程。

## What changes
1. 新增 deployment manifest 单一源（YAML，per-file sha256 + 类别 hook|agent|scaffold）
2. init: 把清单文件复制到 `<workspace>/.claude/`（hooks/ 与 agents/ 子目录）；settings.json 命令改工程内相对形态
3. upgrade: 按清单 sha 比对 → 覆盖刷新副本 → items[] 报 changed/warn 明细；孤儿清理走清道夫
4. stamp 记 manifest digest；check-stale/#748/#779 门语义不变，仅输入口径换新

## Impact
- 触及：hook_activation / kunglao_upgrade / template_version(+stamp 渲染) / release-manifest(资产) / CLAUDE.md.base.tmpl(无?仅若模板文档提及)
- 不变式：七用户数据目录只读铁律；settings.json 改动前后 JSON 必须可解析；operator 文本零 tracker 号
