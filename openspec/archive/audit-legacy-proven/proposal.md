# audit-legacy-proven
## What
tools/audit_legacy_proven.py: 读 workspace 的 claim-register.yaml + facts/_INDEX.md, 列全部 PROVEN claim, 按 BLIND 签字分类 (verified / unverified / has-evidence-no-signoff), 输出 JSON + 人类可读摘要。
## Why
PRD M4: 现存 47 PROVEN claim 中 46 条未经独立 BLIND 验证 (98% 假 PROVEN)。需要度量工具量化假自主规模, 为清账 (批量补验证 / 标 UNVERIFIED / 重跑) 提供数据基础。
## Scope
- 新建 tools/audit_legacy_proven.py (独立度量脚本, 无运行时依赖)
- 解析 claim-register.yaml (status: PROVEN)
- 解析 facts/_INDEX.md (pipe-delimited: F### | STATUS | C-### | desc)
- 分类: verified (BLIND in status) / has-evidence-no-signoff (VERIFIED-BY-* but no BLIND) / unverified (plain PROVEN)
- 输出: JSON audit-<ws>-<ts>.json + stdout 摘要
## Acceptance
- test_audit_legacy_proven 3/3 (混合分类 / 空 workspace / 无 _INDEX)
- pytest 全量绿 (181 existing + 3 new)
