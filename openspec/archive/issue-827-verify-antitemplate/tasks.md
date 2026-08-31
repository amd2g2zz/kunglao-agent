# Tasks: issue-827-verify-antitemplate

- [x] 1. SDD proposal + tasks
- [ ] 2. RED tests：批量模板(KEEP 头,无 marker)排除；marker 齐全同构爆发簇排除；两个同构文件(<3)保留；
        独立可信文件计数；write_gate R1 模板簇拒绝/可信文件通过
- [ ] 3. 实现 credible_redteam_files（marker + burst 簇）接入 extract_verified_claim_ids
- [ ] 4. write_gate 两处 md 接受面接入同一筛选层
- [ ] 5. 本地质量门：pytest 全量 + ext-scan + deploy_manifest --verify/--write
- [ ] 6. push + PR(base=dev)
