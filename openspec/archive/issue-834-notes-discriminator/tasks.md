# Tasks: issue-834-notes-discriminator

## 1. SDD
- [x] 1.1 proposal.md + tasks.md（本文件）先行提交

## 2. TDD 红
- [ ] 2.1 tests/test_notes_discriminator.py：复制冒充拒 / 引用型过 / 零引用拒 / 悬空引用拒 / facts 空目录拒 / notes 缺失过 / 阈值可配（0.0 全拒 / 1.0 不触发重叠拒）
- [ ] 2.2 tests/test_notes_fake_834.py（shim 集成）：复制型 note 在 owed 清空后 block rc=6 NOTES_FAKE；引用型 rc=0；判别器异常 fail-open 过
- [ ] 2.3 跑红（模块不存在 → collection error / assert 失败）

## 3. TDD 绿
- [ ] 3.1 scripts/notes_discriminator.py 实现 check()
- [ ] 3.2 hooks/completion_gate.py：EXIT_NOTES_FAKE=6 + would-PASS 点接入（fail-open 笼）
- [ ] 3.3 单测+集成全绿

## 4. 质量门与交付
- [ ] 4.1 本地门：pytest 全量 0 fail + ext-scan + deploy_manifest --check
- [ ] 4.2 push + gh pr create --base dev（含复现命令）
