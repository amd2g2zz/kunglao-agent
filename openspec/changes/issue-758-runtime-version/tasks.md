# Tasks: #758 Wave-1（G1 钉版 + G4 stamp 一致性门）

## 1. SDD
- [x] 1.1 proposal / design / tasks（specs 增量并 Wave-2 G2/G3 时一并出——本切片无新外部行为契约）

## 2. G1a 仓库钉版（T1）
- [x] 2.1 `.python-version` = `3.11`
- [x] 2.2 pyproject requires-python 保持 `>=3.10`（test_python_floor.py 不动即守卫）
- [x] 2.3 venv 3.11 重建验证（见报告的环境裁决段：uv→pypi TLS 全阻，pip+官方 index 重建，版本集与 uv.lock 一致）

## 3. G1b 漂移检测（T2）
- [x] 3.1 RED: monkeypatch sys.version_info → env_check python_version=WARN 且 overall 不因它 FAIL
- [x] 3.2 RED: upgrade main() stderr 含 `[event] name=python_version status=warn`；匹配时无该行
- [x] 3.3 GREEN: env_check.check_python_version + checks 注册；kunglao_upgrade._warn_python_version

## 4. G4 stamp 一致性门（T3）
- [x] 4.1 RED: 漂移正文 workspace → item `template_stamp_refresh(skipped: frame-drift)`、三载体戳不变、stderr WARN
- [x] 4.2 RED: 一致 fixture（CLAUDE.md 标题骨架=模板期望）→ 正常刷新到当前版
- [x] 4.3 GREEN: template_version.frame_section_current / expected_frame_headings / workspace_frame_headings + kunglao_upgrade 双接线点（item + belt-and-braces）
- [x] 4.4 test_kunglao_upgrade_726 三载体断言按 D4 新契约改写

## 5. 回归与守门（T4）
- [x] 5.1 grep 'python_requires|3.10|3.11' tests/ 核查既有断言（tomli backfill 条件测试）
- [x] 5.2 grep 'stamp_workspace|template_stamp_refresh' tests/ 命中点核查
- [ ] 5.3 质量门全过（聚焦三件套 + 全套 + release_receipt --check + quality_gates + ruff）

## 6. Evidence + 提交
- [ ] 6.1 每 task 一 commit；staged 后重 mint review gate
- [ ] 6.2 PR body 写 "Part of #758（G2/G3 另 PR）" ——不写 Closes，避免提前关 issue
