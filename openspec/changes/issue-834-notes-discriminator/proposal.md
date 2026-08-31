# Proposal: issue-834-notes-discriminator

## Why

completion_gate 的 notes-due 面（#762）只查"文件存在"不查内容来源：把 facts/ 正文复制进 notes/ 冒充叙事交付可以过门（v0.1.3 现场行为："要么不写 notes，要么拿 fact 当 notes 冒充"）。需要机械判别器在 would-PASS 点拦截假 notes。

## What Changes

1. 新增 `scripts/notes_discriminator.py`：`check(notes_dir, facts_dir, max_overlap=0.6)` → `{ok, violations[]}`，三条机械规则：
   - 重叠率：note 词集对 facts 全体词集的包含率 > max_overlap → 拒（复制即拒）
   - 零引用：note 无任何 fact-id 引用（`F-?\d{2,4}` 规范化比较）→ 拒
   - 悬空引用：引用的 fact id 在 facts/ 不存在 → 拒
2. hooks/completion_gate.py 在 NOTES_DUE（exit 5）之后的 would-PASS 点接入：violations 非空 → block，**exit 6 NOTES_FAKE**；异常 fail-open（双重笼式，同 notes_due 惯例）
3. 阈值可配（check 参数），默认 0.6——复制冒充通常 >0.8，合法引用型笔记通常 <0.4，0.6 两侧留裕量

## Impact

- Affected: scripts/notes_discriminator.py（新）、hooks/completion_gate.py（notes-due 面扩展，fail-open 笼内）
- Tests: tests/test_notes_discriminator.py（单元）+ tests/test_notes_fake_834.py（shim 集成）
- Out of scope: 主线覆盖检查（mission_ledger，W3/#823）；不判 notes 叙事质量（无 LLM）

## Deviation note

Issue 验收第三条"边角料 notes（主线 PQ 零覆盖）不满足交付"依赖 mission_ledger（W3），本卡显式 defer 到 W3 接线。
