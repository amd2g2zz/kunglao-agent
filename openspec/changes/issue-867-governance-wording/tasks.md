# tasks — issue-867-governance-wording

- [x] T1 Recon：锚点表 + 镜像样例 + 受影响面基线 122 passed（proposal.md）
- [ ] T2 TDD 收口测试（RED）：external_kicker 无 `import priority`、retirement_gate 真仓
      零 findings、baseline 空（`tests/test_governance_binding_867.py`）
- [ ] T3 收口 external_kicker：`_priority_ordered_ids` → priority_ratio canonical 路径 +
      stderr 降级信号 + :687 prompt 措辞 + 注释同步（GREEN）
- [ ] T4 清偿 baseline：`scripts/.retirement-gate-baseline.txt` 清空 + 真仓钉改写
      （test_retirement_gate_861.py:94-103）
- [ ] T5 devkit/governance_binding.py：检查①(委托 retirement_gate)/②(SKILL 教学形状
      parse-through-detector)/③(evals 对账 + 例外清单) + CLI 两态演示
- [ ] T6 Gate 8 注册：quality_gates.py GATES[8] + docstring；pre-commit 快速集 +1；
      release-check.yml CI 调用 +8；devkit/docs/quality_gates.md 门清单补行
- [ ] T7 eval#1 改写（priority.py → priority_ratio.py 三处）+ LIVE_PATH_SURFACES 扩面
- [ ] T8 清单联动：deploy_manifest --write + --verify；release_receipt --check
- [ ] T9 本地三门：全量 pytest 100% 通过（环境性基线失败甄别表）+ release_receipt --check
      + deploy_manifest --verify
- [ ] T10 push + `gh pr create --base dev` + CI 绿 → 停手（不 merge）
