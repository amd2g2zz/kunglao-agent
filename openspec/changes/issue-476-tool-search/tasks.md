# Tasks: tool-search 三方工具发现 — ext 索引 (#476)

- [x] 1. SDD 三件套(openspec/changes/issue-476-tool-search/)
- [x] 2. RED:`tests/test_ext_index.py`(新)— shipped pin(三源齐/
      source 全存在/unknown 在场/内外零撞名)+ ext-scan 确定性 +
      --check 陈旧检出 + `--find` 行为 + 零网络断言;
      `tests/test_doc_sync.py` 子检 (d) FAIL/WARN/N-A/修法提示;
      `tests/test_subagent_injection.py` ext 裸名解析 + fail-closed
      — 数字口径更正(#476 review M1,独立重放裁定): 真实 RED =
      22 failed(`pytest tests/test_ext_index.py` 单文件,另有 3 个
      非-RED 合法通过)/ 30 failed(三文件合跑,78 passed);commit
      message 中的 "32 red" 为 implementer 误报,两种自然口径均不能
      复现 32。历史 commit 不可改写,后续 PR body 以本口径为准。
- [x] 3. GREEN:`tools/ext-scan.py` + `tools/_INDEX.ext.map.yaml` +
      生成 `tools/_INDEX.ext.yaml`;`tools/tool-search.py --find`;
      `devkit/doc_sync.py` 子检 (d);`devkit/subagent_review.py`
      `_index_tool_names` ext 纳入
- [x] 4. 契约同步:`tools/README.md` 结构规则 + 目录布局 +
      meta-tool 注册;`tests/test_tools_structure_340.py` META_TOOLS
      扩为三
- [x] 5. 快检:`uv run python -m pytest -q -m "not load_sensitive"
      tests/test_doc_sync.py tests/test_subagent_injection.py
      tests/test_ext_index.py` 全绿
- [x] 6. 门:`uv run ruff check .` 零红;
      `uv run python devkit/quality_gates.py 1 3 4 5 6 7` ALL-PASS;
      Gate 5 review JSON `.subagent-review/2026-08-20-476.json`
      (verified_by=pending-476-reviewer,待 reviewer 回填)
