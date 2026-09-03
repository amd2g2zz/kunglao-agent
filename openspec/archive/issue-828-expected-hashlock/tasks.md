# Tasks: issue-828-expected-hashlock

## 1. TDD red

- [ ] tests/test_expected_hashlock_828.py：首锚（expected_hash 落盘）/ FAIL 后改 expected → EXPECTED_TAMPERED 拒（red）/ expected_correction 通道放行 / 同 expected 重跑幂等 / PASS 后改 expected 放行

## 2. Implementation

- [ ] kunglao_verify.py：`prior_expected_history()` + `check_rewrite_after_fail()`；verify() lint 链接入（lint_ok 三门合取）；out 增 `expected_hash`
- [ ] 输出文件名同秒碰撞 `-k` 后缀修复
- [ ] expected_correction 放行时 ledger detail 追加 correction 标记

## 3. Gates

- [ ] 定向套件绿（新测试 + 既有 verify 套件不回退）
- [ ] 本地质量门：pytest 全量 + ext-scan + deploy_manifest --write/--verify
- [ ] scripts/README catalog 无新脚本（kunglao_verify 已有行）

## 4. Delivery

- [ ] push + PR → dev（body 含篡改攻击复现命令）
- [ ] 不 merge；openspec 归档由 orchestrator 在 merge 后执行
