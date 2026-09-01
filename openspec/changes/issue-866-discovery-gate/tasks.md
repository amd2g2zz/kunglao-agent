# issue-866-discovery-gate — tasks

两支 PR 共用本 change；勾选按 PR 分节。

## PR 866-a（本卡：产线语义档 + README 双口径 + 发现面 CI 门）

- [ ] Recon：锚点表 + 镜像样例 + 基线绿（proposal.md ## Recon）
- [ ] relib_audit 产线语义档：`audit_production()` + `--production` 模式（TDD，
      tests/test_relib_audit_production_866a.py）
- [ ] 全仓首跑数字记入 Recon（46 未接线 = scripts 32 + tools 14，~11,310 LOC）
- [ ] scripts/README.md Orphans 双口径声明 + 总数漂移修正 + 防删行回归测试
- [ ] devkit/discovery_gate.py：tools/ 新 CLI 两面登记门（_INDEX.yaml + SKILL/references）
      + 基线棘轮 devkit/.discovery-gate-baseline.txt（TDD，tests/test_discovery_gate_866a.py）
- [ ] Gate 9 注册进 devkit/quality_gates.py GATES；release-check.yml 步骤 1 3 4 8 →
      1 3 4 8 9；scripts/local_gate.py 同帧挂门
- [ ] 门红/绿两态演示（未登记假 CLI → 红；登记 → 绿）——pytest 夹具 + 真仓演示记 Recon
- [ ] 本地门全绿（pytest 100% / release_receipt --check / deploy-manifest 不变免 write）
- [ ] push + gh pr create --base dev + CI 绿（不 merge，orchestrator 串行合并）

## PR 866-b（另行派发：存量逐个鉴定 + Ghidra 四件套 + scripts 鉴定表）

- [ ] tools 侧产线未接线 14 个逐个鉴定：真有用（opaque_pred/stack-strings 类 RE 刚需）
      → 补 SKILL 教学段 + references 条目 + recall 语料条目并出基线；过时 → 按退役政策删
- [ ] "在册但零教学面"清单（22 口径下的 8 个）补教学面或绑定价值排序说明
- [ ] Ghidra 四件套（ghidra_diff/ghidra_job/run_ghidra_postscript/job_store，~1,928L）
      登记或显式退役；基线同步收缩
- [ ] scripts 侧 32 个鉴定表：绑定在途 change 标注 / SUSPECT→DEAD 按产线语义档输出
- [ ] deploy-manifest 对账：发布面与登记面对齐佐证条目（deploy 全树收录退化的纠偏
      属此节评估）
- [ ] 基线清偿后 devkit/.discovery-gate-baseline.txt 归零核对
