# Tasks: issue-825-verifier-identity

## 1. SDD
- [x] proposal.md + tasks.md

## 2. TDD red
- [x] tests/test_verifier_identity_825.py：
  - [x] register 门：无身份 redteam → 违规 "no verifier identity"
  - [x] register 门：redteam 身份 == verify-note 身份 → 塌缩违规
  - [x] register 门：redteam mtime < verify-note → "predates" 违规
  - [x] register 门：合法双身份 → ok + ledger 锚定行（幂等）
  - [x] write_gate：json overall=VERIFIED only → R1 触发
  - [x] write_gate：json l2 CONFIRMED 无身份 → R1 触发
  - [x] write_gate：json l2 CONFIRMED + 身份 → clean
  - [直接] write_gate：redteam md 无身份头 → R1 触发
  - [x] write_gate：redteam md 带身份 + CONFIRMED → clean

## 3. 实现
- [x] scripts/verifier_identity.py（extract/anchor/anchors_for）
- [x] register_proven_gate.py 身份/塌缩/归因/锚定
- [x] write_gate.py _fact_runs_records 演进（去 L1 接受 + 身份要求）
- [x] 夹具合同演进（3 套件 helper）

## 4. 质量门
- [x] 新套件绿
- [x] 受影响套件绿
- [x] pytest 全量（基线对照）+ ext-scan + deploy_manifest --verify
- [x] README catalog 行
