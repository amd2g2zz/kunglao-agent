# Proposal: issue-825-verifier-identity

## Why

豆包事故复盘根因：maker/checker 塌缩——orchestrator 自写 "RED-TEAM PROXY
RECORD" 并自盖 PROVEN，16/16 PROVEN 中 15 个零独立验证。合同
（SKILL.md:254 / 收敛规则 §5"不 self-stamp"）无机械执行面：

1. write_gate `_fact_runs_records` 接受 maker 自己的 L1 `overall=VERIFIED`
   json 当独立验证记录（事故中 89 条 L1 json 过了 R1）。
2. verify_status: passes 无 dispatch 归因要求——无身份的"proxy record"
   直接过门。
3. 身份不被锚定——事后可改写作者身份重刷验证史。

## What Changes

1. 新模块 `scripts/verifier_identity.py`：
   - `extract_from_md/json`：从 verify-redteam-*.md 的 `verifier-identity:`
     头 / verify-<fid>-*.json 的 `l2.verifier_identity` 字段提取机器身份
   - `anchor()`：PROVEN 门接受裁决时把 (claim, source, identity,
     record_sha256) 追加写入 workspace ledger（append-only，#584 行契约，
     #831 同款）——裁决接受即锚定，事后冒名可对账检出
   - `anchors_for()`：读回锚定行（对账/测试面）
2. `scripts/register_proven_gate.py`（#819 门）收敛 #825 语义：
   - redteam 记录必须带 `verifier-identity` → 无身份 = 违规（fail-closed，
     waiver 通道仍在）
   - redteam 身份 == verify-note 记录身份（双方都有时）→ maker/checker
     塌缩违规
   - redteam mtime < verify-note mtime → "redteam predates maker" 违规
     （issue 点 3 的 mtime 归因）
   - 接受路径锚定 (claim, source, identity, record_sha) 到 ledger（幂等）
3. `scripts/write_gate.py` `_fact_runs_records`：
   - **删除 `overall=VERIFIED`（L1）接受分支**——L1 是 maker 自己的机械
     复跑，不构成独立验证（事故实锤后门）
   - json 面只认 `l2.verdict == CONFIRMED` 且带 `l2.verifier_identity`
   - md 面要求 `verifier-identity` 头
4. 夹具合同演进：test_register_proven_gate / test_write_guard_register_gate_819 /
   test_write_gate 的 redteam/json 夹具补身份字段（合同演进，PR 记录）

## Out of scope

- runs/dispatch-*.json 派发归因基建（issue 的 "or equivalent" 由
  记录自带身份字段兑现；真实 dispatch 面属 #626/#627）
- redteam agent 定义文件注入 session_tag()（后继小卡；门先 fail-closed
  逼新记录带身份）

## Impact

- 受影响套件：register_proven_gate / write_gate / 819 integration（夹具
  演进）；其余 VERIFIED 引用是各自模块语义，不受影响
- 门从"内容正则即接受"升级为"身份绑定 + append-only 锚定"——假独立验证
  从免费变昂贵，PROVEN 可信度机械保障
