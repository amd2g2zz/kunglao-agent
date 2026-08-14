# provenance-gate
## What
`scripts/provenance_gate.py` — fact provenance 必引 evidence/_index.json 里的 eid 或 path,且 sha256 匹配 + 该条在 index 内(派生不在 index,自然拒)。
## Why
F023 引派生 summary.json 不引原始 full_trace.txt(C-020 全链错锚根因)。P1 已建 evidence index(raw 注册,派生排除);P2 用 index 做 provenance 门禁,堵"摘要代原始"。
## Scope
- `scripts/provenance_gate.py`: `check_provenance_gate(fact_path, ws) -> (ok, reason)`
- 解析 fact 的 provenance(或 cites/eid 字段)→ 查 evidence/_index.json → path 解析 + sha256 匹配 + 在 index 内
- 派生-only(引 summary.json 等)或引不存在的 eid/path → invalid
- 复用 M1 blind_gate.py 模式(纯函数,无 I/O 副作用)
## Acceptance
- RED1: provenance 引派生 summary.json(不在 index)→ 拒
- RED2: provenance 引不存在的 eid → 拒
- RED3: provenance 引 index eid 但文件 hash 不匹配 → 拒
- RED4: provenance 引 index eid + hash 匹配 → 过
- 全量 pytest 绿
