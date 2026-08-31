# Tasks — issue-761-web-knowledge

- [x] T0 openspec scaffold（本目录）
- [ ] T1 = J1 web-risk-control.md + web-crawler-engineering.md + 收录/re-pin/词典（J6 升级链入树、J7 插桩执行列）
- [ ] T2 = J2 sequentialthinking 契约（worker 权威段 + redteam 攻击路径枚举）
- [ ] T3 = J3 plan 状态机 frontmatter + scripts/plan_reviser.py 三触发 --check/--apply + SKILL 契约
- [ ] T4 = J4 recall_useful 全链（DONE 模板/lib 解析/统计+降权建议/红队注入/joint 联合查询）
- [ ] T5 = J5 LEARN 两级梯 + WebSearch evidence 纪律（worker + operational-mechanics）

验收：tests/test_web_knowledge_761.py 全绿；守门扫描
`grep -rn 'recall\|plan-C\|LEARN' tests/ | grep -v test_web_knowledge` 无意外语义漂移。
