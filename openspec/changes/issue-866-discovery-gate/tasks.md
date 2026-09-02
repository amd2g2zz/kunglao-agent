# issue-866-discovery-gate — tasks

两支 PR 共用本 change；勾选按 PR 分节。

## PR 866-a（本卡：产线语义档 + README 双口径 + 发现面 CI 门）

- [x] Recon：锚点表 + 镜像样例 + 基线绿（proposal.md ## Recon）
- [x] relib_audit 产线语义档：`audit_production()` + `--production` 模式（TDD，
      tests/test_relib_audit_production_866a.py）
- [x] 全仓首跑数字记入 Recon（45 未接线 = scripts 31 + tools 14，~11.2k LOC）
- [x] scripts/README.md Orphans 双口径声明 + 总数漂移修正 + 防删行回归测试
- [x] devkit/discovery_gate.py：tools/ 新 CLI 两面登记门（_INDEX.yaml + SKILL/references）
      + 基线棘轮 devkit/.discovery-gate-baseline.txt（TDD，tests/test_discovery_gate_866a.py）
- [x] Gate 9 注册进 devkit/quality_gates.py GATES；release-check.yml 步骤 1 3 4 8 →
      1 3 4 8 9；scripts/local_gate.py 同帧挂门
- [x] 门红/绿两态演示（未登记假 CLI → 红；登记 → 绿）——pytest 夹具 + 真仓演示记 Recon
- [x] 本地门全绿（pytest 5050 passed，仅 7 个文档化 Windows 环境性基线失败；release_receipt --check 绿；deploy-manifest --write 后 --verify 364 条绿；ext-scan --check 绿；Gate 9 单跑 PASS）
- [x] push + gh pr create --base dev + CI 绿（不 merge，orchestrator 串行合并）——PR #894

## PR 866-b（另行派发：存量逐个鉴定 + Ghidra 四件套 + scripts 鉴定表）

- [x] tools 侧产线未接线 14 个逐个鉴定：真有用（opaque_pred/stack-strings 类 RE 刚需）
      → 补 SKILL 教学段 + references 条目 + recall 语料条目并出基线；过时 → 按退役政策删
- [x] "在册但零教学面"清单（22 口径下的 8 个，实测 10 个缺教学）补教学面（references/re-library/kunglao-toolshelf.md）
- [x] Ghidra 四件套（ghidra_diff/ghidra_job/run_ghidra_postscript/job_store，~1,928L）
      登记或显式退役；基线同步收缩（ghidra_diff 独立条目+契约条目；job_store 按 lib 处置；基线 27 到 0）
- [x] scripts 侧 29 个鉴定表（31 减 capture_golden 闭包翻转 2）：绑定在途 change 标注 / SUSPECT→DEAD 判定按产线语义档输出（退役=0；ledger 落 scripts/README.md）
- [ ] deploy-manifest 对账：发布面与登记面对齐佐证条目（deploy 全树收录退化的纠偏
      属此节评估）
- [x] 基线清偿后 devkit/.discovery-gate-baseline.txt 归零核对（27 到 0，门 exit 0）
