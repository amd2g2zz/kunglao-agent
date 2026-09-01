# issue-884 tasks

## TDD 序

- [x] R1 前置探索：锚点表 + 镜像样例 + 基线（HEAD 布局 3 passed；见 proposal.md ## Recon）
- [ ] T1 RED：tests/test_jsvmp_triage.py — SCRIPT → tools/web/jsvmp_triage.py；新增 F1+F3 pair、F2+F3 pair、大数组单独不命中（空洞 F3 绊线）、votes/置信档断言（≥6 测试）
- [ ] T2 GREEN：三中二实现（_semantics_ratio → (ratio, has_cases)；f3 锚定 has_cases；votes/confident/confidence）
- [ ] T3 boot 修复：_lib.stdio 委托（crypto-tool.py:31-35 镜像）
- [ ] T4 注册面：validate_index CATEGORIES/_CAPABILITY_TAGS；_INDEX.yaml web 条目；_index-web.md；tools/web/README.md；_INDEX.md 主页行；docs-contract 测试联动（CATEGORY_READMES + len 37）
- [ ] T5 知识卡：references/re-library/jsvmp-triage.md + references/_INDEX.md 行 + ext-scan 重生成 _INDEX.ext.yaml
- [ ] T6 worker 通道：agents/web-re-worker.md JSVMP 分支 → 新路径 + 知识卡
- [ ] T7 清单：release-manifest.yaml assets.tools 行；deploy_manifest.py --write

## 门禁

- [ ] G1 `python -m pytest tests/ -q` 100% 通过
- [ ] G2 `python scripts/release_receipt.py --check` 绿
- [ ] G3 `python scripts/deploy_manifest.py --verify` 绿（--write 后）
- [ ] G4 `python tools/ext-scan.py --check` 绿
- [ ] G5 `git grep -i jsvmp -- scripts/` = 空

## 交付

- [ ] D1 conventional commits（一个逻辑单元一个 commit）
- [ ] D2 push + `gh pr create --base dev`
- [ ] D3 CI 绿后停手回报（不 merge）
