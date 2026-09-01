# issue-811-gbk-utf8 — Windows GBK 编码冲突系统化治理

## Why

Windows locale（GBK/cp936）与仓库 UTF-8 内容的编码假设冲突是 v0.1.3→v0.1.4 多起现场失败（#754 四连崩、#794 双例）的直接根因。逐处补丁追不完新代码，需三层治理。

## What Changes

1. **P0 全局模式**：hook 注册命令注入 `PYTHONUTF8=1`（build_hook_entry 一处改全部生效）；CLI 入口统一调用 `scripts/utf8_boot.py::force_utf8()`（setdefault + stdout/stderr reconfigure，heartbeat_tick 先例推广）
2. **P1 双保险**：scripts/hooks/tools/templates 全量机械 sweep——write_text/read_text/open(文本)/subprocess(text=True) 无 encoding 的调用补 `encoding='utf-8'`（subprocess 另加 `errors='replace'`，hook/审计路径永不因解码崩）
3. **P2 防复发门**：`scripts/encoding_lint.py`（AST 扫描器，多行/嵌套鲁棒）挂为机械门——bare 调用清零后任何新增即 CI 红

## 豁免记录

- `scripts/migrate_facts.py`：用户 WIP 文件，本轮跳过（内含 1 处 bare 调用，scanner SKIP_FILES 显式豁免并计数上报）

## Impact

- 受益：全部 Windows 用户的文件 IO/subprocess 解码确定性
- 风险：批量修改可能改变成功路径行为 → 逐块 py_compile + 全量 pytest 兜底
- 边界：tests/ 不在扫描面（tmp 夹具为主）；CI 的 GBK-locale job（P2 CI 面）留后续 PR

## 范围变更记录（coordinator 纠正, 2026-09-01）

Issue 评论区 B6 CONFIRMED 审计实证并入本卡（优先级最高）：根 conftest.py 与
tests/conftest.py 定义同 5 个夹具，根副本 golden_master 裸 text=True 是活体
GBK 陷阱（删 tests/conftest.py 的方案已被仲裁否决）。已按仲裁执行：根
conftest.py 删除 5 个被遮蔽夹具定义（保留 #369 锁 + #770 守卫），全部夹具
单源于 tests/conftest.py（其 golden_master 带 #317 errors="replace" 修复）。
