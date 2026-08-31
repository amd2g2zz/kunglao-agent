# Tasks — issue-427-rust-dep-strings

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/427`, branch `v012/issue-427-rust-dep-strings` off `origin/dev` afaae75
- [x] 1.2 必读: plan Task 2 / issue #427 正文 / `tools/static/go-buildinfo-carve.py` + `common.py` / `references/cli-script-checklist.md` / `references/re-library/languages-compiled.md` Rust 面

## 2. SDD

- [x] 2.1 proposal.md(吸收来源 + 双通道范围 + 影响文件表)
- [x] 2.2 design.md(D1 落位与风格镜像 / D2 双通道 / D3 防跨段 / D4 输出与 exit / D5 登记面 / 署名 / R1-R4)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_rust_dep_strings.py` — 合成 fixture:registry 路径正/反斜杠变体、cache `.crate` 变体、16hex registry id、prerelease 版本尾、独立 crate 串、通道过滤、防跨段拒绝、普通二进制零误报、CLI 契约(--help rc0 / 缺 --in rc2 / --json 键 / --reproduce L1 / 空&负例 rc1)
- [x] 3.2 pin 更新:`tests/test_tool_search.py`(28→29, cheap 25→26)+ `tests/test_index_docs_contract.py`(28→29)
- [x] 3.3 确认 RED:uv run python -m pytest -q tests/test_rust_dep_strings.py tests/test_tool_search.py tests/test_index_docs_contract.py(全 failed,commit 哈希记录)

## 4. GREEN

- [x] 4.1 `tools/static/rust-dep-strings.py`(marker+window+回溯提取,双通道,--channels 参数化,署名 docstring,UTF-8 stdout 守卫)
- [x] 4.2 登记:tools/_INDEX.yaml + tools/_index-static.md(目录行 + 6 段契约)+ tools/static/README.md(吸收行,16→17)
- [x] 4.3 references:languages-compiled.md Rust 工具段提及 + references/_INDEX.yaml digest 重钉
- [x] 4.4 快检:uv run python -m pytest -q -m "not load_sensitive" tests/test_rust_dep_strings.py tests/test_tool_search.py tests/test_index_docs_contract.py tests/test_subagent_injection.py — 尾行全绿

## 5. Gates + 产出

- [x] 5.1 uv run ruff check . — 零 finding
- [x] 5.2 uv run python devkit/quality_gates.py 1 3 4 5 6 7 — ALL-PASS(Gate 5 JSON: .subagent-review/2026-08-20-427.json, verified_by=pending-427-reviewer)
- [x] 5.4 (GREEN 期间追加) release-manifest.yaml 资产行 + C:/Users 禁形修复(test_hardcode_purge / test_release_receipt 由全量快门捕获)
- [x] 5.3 .review/RUNBOOK.md(不入库)
