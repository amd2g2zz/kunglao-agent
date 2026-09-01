# issue-881 tasks — 聚合器 + 两处消费接线（同 PR 纪律）

## 1. 聚合器
- [x] 1.1 `scripts/tool_value.py`：aggregate(ws) 四输入 join（claim id）→ (scene,operation,tool) cite/burn/reject + β-Bernoulli utility（先验=静态 tier）
- [x] 1.2 write_table/load_table（runs/.tool-value.json，原子写，tolerant 读）
- [x] 1.3 CLI：默认重算写表+摘要；`--report [--operation X] [--json]` 一条命令可答最高 utility

## 2. 接线① tool_tiers
- [x] 2.1 `chain_for(scene_key, ws=None)`：tier 池化计数 β 后验稳定重排；无表=静态原序
- [x] 2.2 `inject_block(scene_key, ws=None)`：链序同上 + 档内工具 utility 重排；无表=逐字节现状
- [x] 2.3 `inject_for_workspace` 透传 ws

## 3. 接线② recall
- [x] 3.1 `recall_files` cwd-aware utility rerank（文件路径工具名 → 池化 utility；未命中中性稳定；无表/异常 fail-open 原序）

## 4. 测试（TDD：先 RED）
- [x] 4.1 tests/test_tool_value_881.py：三输入 join → 计数与 utility 数值断言
- [x] 4.2 chain 排序随计数变化（翻转断言）+ 无表静态
- [x] 4.3 recall rerank：utility 高者前置；无表原序；坏表原序
- [x] 4.4 --report 可答 + 零使用工具沉底可见（retirement-candidate 标记）

## 5. 门禁与交付
- [ ] 5.1 本地三门：pytest 全绿（7 个 Windows 环境性基线失败甄别）/ release_receipt --check / deploy_manifest --write --verify
- [ ] 5.2 conventional commits 小粒度（聚合器与接线同分支同 PR）
- [ ] 5.3 push → gh pr create --base dev（Fixes #881）→ CI 绿 → 停手不 merge
