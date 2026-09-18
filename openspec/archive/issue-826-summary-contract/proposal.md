# Issue-826: user-facing summary 结构合同

## Why

事实层诚实（76 行 unconfirmed/pending 标记），但 user-facing summary 把不确定性全部蒸发——"分析收敛完成 / q1+q2+q3 全部闭合 / 16/16 PROVEN"。C-020 转述层事故在会话层复发：没有任何机制 hook 住 assistant 自己的 summary 文本。CLAUDE.md 的词汇禁令（无 sign-off 不说 FINAL/complete）零强制。

## What Changes

1. `scripts/summary_discriminator.py`（新）：对 workspace 交付 summary（`summary.md`，workspace 根）做机械结构校验：
   - **R1 完成词后果门**：summary 含完成词（完整/全部闭合/CONVERGED/还原完成/fully reverse/全部 PROVEN）∧ facts/ 存在非 PROVEN 盖章的 fact ∧ 无暂定节（## 未独立验证 / ## 暂定 / ## provisional / ## 未确认）→ 拒
   - **R2 不确定性传播**：存在携带不确定性标记（body 含 unconfirmed/pending/hypothesis/T1/暂定/未确认）的非 PROVEN fact，其 fact-id 未在 summary 出现且未 WAIVED（`WAIVED(<fid>):` + ≥8 字理由）→ 拒
   - **R3 未答主问题节**：mission_ledger 存在 unattempted/blocked PQ ∧ summary 无开放问题节（未答/开放问题/open questions/待答）→ 拒；ledger 不存在则跳过
2. `hooks/completion_gate.py` would-PASS 面（NOTES_FAKE 之后）接入：summary.md 不存在 → skip；判别器异常 → 双笼 fail-open；违规 → block `SUMMARY_FAKE`（EXIT=7）
3. 不做：NL 生成质量（模型的事）；summary.md 存在性强制（更大合同变更，proposal 记边界）

## Impact

- completion_gate 新增 exit 7 face + 判别器调用
- mirrors #834 discriminator 模式（判别器 fail-closed / 调用方双笼 fail-open）
- 既有 completion_gate/notes 测试零回退
