# Tasks: issue-814-recall-quality

- [x] SDD proposal + tasks
- [ ] TDD 红：单字段碰撞阻尼 / demotion 闭环 / recall_skip 留痕 / recall_injected / metrics 落盘与聚合
- [ ] 实现：references_recall 打分阻尼+demotions 线程 + CLI --ws；recall_inject 全路径留痕 + --ws 传递；recall_metrics 新模块
- [ ] event_taxonomy 注册 recall_injected/recall_skip
- [ ] 本地质量门：pytest 全量 + ext-scan + deploy_manifest --verify
- [ ] push + PR(base=dev)
