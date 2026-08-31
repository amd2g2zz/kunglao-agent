# Proposal: issue-814-recall-quality — recall 注入链修复 + 打分去污染 + 度量面

## Why

#814 实证：检索层健康但 **注入层断链**（worker 收不到 recall 列表，fail-open=fail-silent 无痕迹）+ **污染率≥40%**（泛文档靠 purpose/when 单词碰撞挤进 top-K，"static" 命中 tools.md 即为一例）。用户裁决：召回改进只认 precision。

## What Changes

1. **打分去污染**（references_recall.py）：purpose/when-only 单字段碰撞乘 `W_SINGLE_FIELD=0.3` 阻尼（name/category/domain/symptom 强字段命中不受影响）；demotion 乘子闭环——`demotion_map(ws)` 把 `.recall-stats.json` 的 demotion_suggestions 变成 `{term: 0.25}` 乘子进 `score_entry`；CLI 增 `--ws` 传工作区。
2. **注入链留痕**（hooks/recall_inject.py）：所有 pass-through 路径 emit `recall_skip`（带归因 reason），成功注入 emit `recall_injected`——fail-open ≠ fail-silent。
3. **度量面**（scripts/recall_metrics.py 新）：`record()` 追加 jsonl 到 `runs/.recall-metrics.jsonl`（ts/kind/query/files/reason），`summarize()` 聚合 injected/skipped/no_match——#833 优化器的 precision 输入口。
4. EMIT_ACTIONS 注册 `recall_injected`/`recall_skip`（字母序）。

## Impact

- touched: scripts/references_recall.py, hooks/recall_inject.py, scripts/recall_metrics.py(新), scripts/event_taxonomy.py, scripts/README.md, manifests
- 不做：BM25 换算法（瓶颈在语料）；android 域内容建设（P1 内容面，独立卡）；worker 侧 recall_useful 解析（lib_kunglao 既有）
