# issue-812-tool-value: 工具族档位表进派单契约（契约层批次）

## Why

#812 现场（500MB APK）：jadx 全量（重端）卡死 → 退化 grep+read（裸端）——光谱两端双输，
中间档（targeted/structured）不在选择面。根因 = 工具选择无成本档位的一等表达：
worker 收到的派单契约里没有任何档位/降级链信息，选择完全靠个体自觉。

本变更 = **契约层**：把档位选择表做成结构化数据 + 注入派单契约，让每个 worker
规划时"看得见"完整光谱。不做运行时打分闭环（Q 表消费属 #823-P3；执行包装器
timeout 硬杀属后续 PR）。

## What Changes

1. `scripts/tool_tiers.yaml` — 场景×工具档位表（结构化数据，非代码）：
   - android-dex-static 场景全规格：#670 估算参数（dex_factor=50/floor/budget_ratio）
     + 四档工具链（full/targeted/structured/text）+ 降级链 + 硬顶参数（timeout/-Xmx）
     + 混淆先验适配 + 来源引用（#670 calibration、#812 C-006 实录）
   - generic-binary 场景（ghidra 泳道）同词汇表；未知场景 → 通用档位词汇 fallback
2. `scripts/tool_tiers.py` — 加载器/选择器/注入块（~130 行，fail-open）：
   load / scene_for(task_spec 平台嗅探) / chain_for / tier_entry / inject_block
3. `scripts/dispatch_context.py` — build_dispatch_context 增可选键 `tool_tiers`
   （providers 先例同款：失败→键缺席；不进 VERIFIER_SAFE_KEYS，与 tier/tools 同类）
4. 测试 `tests/test_tool_tiers_812.py`：对数据文件与契约注入断言（非 LLM 行为）

## Capabilities

### 修改的模块
- `scripts/dispatch_context.py`：+1 可选键（providers 先例）
- 新数据文件 + 加载器，零既有行为变更（fail-open）

## Impact

- dispatch 契约从此携带完整工具档位光谱与降级链（中间档 first-class）
- 降级链/硬顶为数据，后续 PR（执行包装器/审计闭环）可直接消费同一文件
