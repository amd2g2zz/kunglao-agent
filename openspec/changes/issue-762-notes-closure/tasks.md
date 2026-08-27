# Tasks — issue #762 知识沉淀闭环 K1+K2

## 1. SDD

- [ ] 1.1 `openspec/changes/issue-762-notes-closure/proposal.md` — 三处断链取证 + 用户裁决
- [ ] 1.2 `design.md` — D1 裁决 / D2 断链锚 / D3 reconciliation sweep / D4 would-be-PASS 拦截 / D5 worker 契约 / D6 K3 留缝
- [ ] 1.3 `tasks.md`（本文件）

## 2. T1 = K1a rollup 机械触发

- [x] 2.1 RED `tests/test_notes_closure_762.py`：sweep 把终态 claim 入队 notes-due；
      重复 sweep 不重复；RETRACTED 入 sweep；已 rollup 不重跑；CLI `--sweep-terminal`
      端到端；legacy `<ws> <cid> --status` 逐字节兼容；tick 报告携带 rollup_sweep 且
      advisory（rc 权重不变）；事件词表含 rollup_sweep
- [x] 2.2 GREEN scripts/rollup.py（pending_terminal_claims / rollup_terminal_claim /
      sweep_terminal_claims / CLI 追加）；heartbeat_tick 接 tick 链；event_taxonomy
      受控词注册；SKILL 契约句降级为文档描述由机械触发取代；commit

## 3. T2 = K1b completion gate 消费欠账

- [x] 3.1 RED：notes-due 非空 + would-be-PASS → exit 5 block 列欠账 id；
      补写 notes/<id>.md → 放行；item 未清时 item 级优先（exit 1 先于 5）；
      legacy 缺队列不拦；corrupt queue 不拦（fail-open 加固）
- [x] 3.2 GREEN hooks/completion_gate.py process_event（judge==0 后查 notes_due，
      return 5 NOTES_DUE）；scripts/completion_gate.notes_due 形态加固；双 docstring
      同步；commit

## 4. T3 = K2 worker 沉淀契约

- [x] 4.1 RED：worker md 含"知识沉淀"段 + DONE 行模板带 `notes:` 字段 +
      三通道关键词 + frontmatter 契约；lib_kunglao.parse_declared_notes 解析形态；
      scan_done_artifact_violations 对缺失 note 报 declared-note-missing、存在则清、
      legacy 无声明豁免；operational-mechanics 交付清单含 notes 项
- [x] 4.2 GREEN agents/kunglao-worker.md / hooks/lib_kunglao.py /
      references/operational-mechanics.md；commit

## 5. T4 = K3 留缝（不做实现）

- [x] 5.1 notes_writer.note_supersedes_hypothesis 占位接口（NotImplementedError +
      TODO 注释指向 Wave 3 #759/#761）；形态测试；commit

## 6. Close-out

- [x] 6.1 守门 grep 全扫 + 全质量门电池（定向 → 净化 PATH 全套 → receipt →
      quality_gates → ruff）——全绿（4 pre-existing
      机器态失败已对照 origin/dev 基线复现，见 design 附注）
- [ ] 6.2 evidence+mint；PR（title `fix(#762): 知识沉淀闭环 K1+K2 — ...`）；
      CI 绿后 squash+delete
