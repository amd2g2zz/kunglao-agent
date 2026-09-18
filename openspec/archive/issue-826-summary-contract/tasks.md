# Tasks: issue-826-summary-contract

- [ ] 1. SDD proposal + tasks 提交
- [ ] 2. tests/test_summary_discriminator_826.py 红测（R1 完成词无暂定节 / R2 未传播不确定性 / R3 缺未答节 / waiver 放行 / 缺 summary skip / 全 PROVEN 无需暂定节）
- [ ] 3. scripts/summary_discriminator.py 实现（R1-R3，fail-closed）
- [ ] 4. hooks/completion_gate.py would-PASS 接入（EXIT_SUMMARY_FAKE=7，双笼 fail-open）
- [ ] 5. README catalog + deploy manifest 重生成 + 全量本地门
- [ ] 6. push + PR(base=dev)
