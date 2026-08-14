# pipeline 领域索引(工具层)

> 领域: 证据索引/报告管线工具。worker 被派发到证据登记、索引构建、报告生成类任务时先读本文件, 再按需加载。契约字段含义见 [README.md](README.md), 机器契约见 [_INDEX.yaml](_INDEX.yaml)。plan 编排模板(recipe)在 `tools/pipelines/recipes/*.yaml`(纯数据模板, 非执行器, 见 `tools/pipelines/README.md`)。

## 工具清单

| 工具 | 用途(一句话) | 何时读 / 何时不用 |
|---|---|---|
| `build-evidence-index` | 证据索引构建器(evidence/_index.json + _INDEX.md) | 证据落盘后需要登记索引时读; 纯分析不做登记时不用 |

## 契约条目

### build-evidence-index

- **用途**: 扫描 workspace 的 evidence/ + analysis_artifacts/, 构建证据索引(evidence/_index.json + _INDEX.md)。
- **用法**:
  ```bash
  python tools/build_evidence_index.py <workspace> --write
  ```
- **输入**: workspace 根(位置参数, 必填) + `--write`(落盘开关); 可选 `--out`/`--rel`。
- **输出**: evidence/_index.json + _INDEX.md(eid/path/sha256/source_reliability)。
- **exit code**: 0 成功 / 2 错误(workspace 缺失等)。
- **when_not**: 纯分析不做证据登记时不用。
