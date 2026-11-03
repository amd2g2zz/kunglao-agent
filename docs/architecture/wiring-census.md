# Gate A — 接线完整性清查（wiring census, 2026-10-19）

基准：feat-773-executor @ 4fcbf216（dev 518e2d10 + #773 全量）。方法：真实导入图入度（diagramctl python 导入器）× 注册表交叉 × 账本读写清查 × 拒绝码覆盖。

## 1. 零调用者扫描

- scripts/rlvr（39 模块）：**零孤儿**（导入图入度全 ≥1）。
- hooks（26 模块）：19 个零导入入度 = 路径注册入口；**19/19 全部在单源注册表** `scripts/wire_up_settings.py::WIRE_UP_HOOK_WIRING`（freeze-test 钉死）。
- 结论：**无装饰面**。

## 2. EMIT 词表双向核对

`tests/test_emit_gate_880.py` 在本树 7 passed（正向孤儿扫描 + 反向未注册扫描均绿，CI unit-fast 同证）。880 双向门 = 清查机制本身（#772 落地后它抓住了 gate_sample_failed 缺 emit 位点——机制实战记录）。

## 3. 账本读写对账（18 条核心账本抽样）

全部存在 writer+reader 双面（belief.jsonl 为 belief.py 模块内双面；plan-receipts.jsonl 的读者 = devkit 活体指纹 + #769 投影规划中）。无只写死账、无只读僵尸。全 69 路径映射见附录 B §5。

## 4. 拒绝码可达性

| 拒绝码 | 测试覆盖（引用文件数） |
|---|---|
| snapshot | 154 |
| plan | 177 |
| ladder | 73 |
| granularity | 15 |
| devreason | 6 |
| methodfamily | 4（含 #773 W2 携带采样家族钉） |
| zerooutput | 2 |
| tiercons | 2 |

全部可达且有测试。

## 判定

**门 A 通过：零候选装饰面遗留；五活体指纹机制在合成夹具全可证（11 pins）。** 放行门 B。
