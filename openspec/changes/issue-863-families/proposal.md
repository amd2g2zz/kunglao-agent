# #863 治理机械化 — enforcement-by-mechanism（剩余 Families）

Package 2（纯兼容删除九项 + lint_facts 仲裁裁决）已先行交付（PR #875）。
本 change 覆盖 Package 1 剩余 Family（按 issue 表）：

- Family A: tools/ UTF-8 stdout guard（35×4 副本）→ `tools/_lib/stdio.py::ensure_utf8_stdout`
  单体 + 全 CLI 委托；扩展覆盖 stdout+stderr 双流（吸收 3 个双流变体）。
  执法测试 test_utf8_stdout_convention.py 改写为 delegation 断言（#863 机制化语义）。
- Family B: spec_from_file_location loader 前导 ×21 → loader util + delegation
- Family C: _resolve_ws ×8（4 形状）→ manifest-aware 单一源（同源闭合 #865 主体）
- Family D: toolchain which 循环 + docker probe → `_which_items()` helper

规则：永不删除有测试守卫的行为——抽共享实现、执法测试改写为 delegation 断言。
