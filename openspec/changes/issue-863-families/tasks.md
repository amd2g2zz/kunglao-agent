- [x] Family A: stdio 单体 + 34 CLI 委托转换 + 执法测试 delegation 重写
- [x] Family B: loader util + 前导委托（实测 22 调用点/21 文件 → `hooks/_path_hygiene.load_module_by_path` 单体；scripts 侧经新增 `scripts/_hooks_path.py` 桥；#671 自举 2 处 named-allowlist 保留）
- [x] Family C: _resolve_ws manifest-aware 单源（闭合 #865 主体）——实测 9 份（issue 8 + #883 新增 statusline_snapshot）/4 形状 → `scripts/ws_layout.py` resolve_quiet/resolve_strict 单源；B2 修复（8 份硬编码 sibling → 全部尊重 layout.workspace_dir/claim_register）；守护测试 4 形状全覆盖 + delegation/confinement 执法
- [x] Family G: conftest fork 清零 —— #811 裁决(34e1603)已删 5 个被遮蔽 root fixtures；本卡补防复活机械钉 test_conftest_single_source_863g(4 钉：root 禁 5 名/必持 5 夹具/golden_master #317 UTF-8 解码/fixture 行为解析钉)
- [x] Family L: test fixture families → conftest factories —— tests/_factories.py 三工厂(write_hook_state 29 点/24 文件收编（4 形状 + extra 键）；write_claims_register canonical+sparse 双方言；seed_bins 34 点/26 文件) + conftest 薄再导出 + ws_factory 委托；12 形状等价钉 test_fixture_factories_863l
- [ ] Family D: toolchain `_which_items()` helper
- [x] Family D: toolchain `_which_items()` helper（#877 已交付；863-f 复核 CONFIRMED 单源无残留，见 proposal.md Recon）
- [x] 863-e #1: wire_up_settings deprecated alias 删除（注册表本体保留）+ DEPRECATED_ALIASES 清账 + 测试改调 register_hooks
- [x] 863-e #2: worker_budget._ShimModule + _PROPAGATE_TO 删除 + 3 测试文件直 patch 源模块
- [x] 863-e #3: validate_index._LEGACY_UNANNOTATED 白名单删除 + _INDEX.yaml 29 条目机械回填 + _CAPABILITY_TAGS 扩 27 标签
- [x] 863-e #4: digest_build pre-contract `<ws>/_INDEX.md` fallback 删除
- [x] 863-e #5: promote_lesson 死定义（:654，被 :949 遮蔽）删除 + helper `_read_lesson_frontmatter` 清理 + soft-fail 行为钉
- [x] 863-e #6: kunglao_verify --grace/--grace-scan 一次性迁移旗标退役（含 kunglao.py 镜像 + schema.md 段 + 配对测试）
- [x] 863-e #7: lint_facts/migrate_facts 裁决落地（YAMLError 硬错 + PARTIALLY-VERIFIED 出 status 集 + _parse_kv_block 保留 + migrate_facts 内联 _parse_frontmatter）
- [x] Family E: kunglao_upgrade WARN-triple 单源（16 处 print → `_warn`/`_warn_line` 模块内单源 + delegation/confinement 执法测试）
- [x] Family H: `_ensure_utf8_stderr` 3×9 → `scripts/utf8_boot.ensure_utf8_stderr` 纯别名委托；textual tripwire 改身份级 delegation 断言
- [x] Family I: tools/static `_error` 6 份 → `common.error` sys.exit 契约统一（return-vs-exit 分叉显式修：yara `return _error(...)` → `error(...)` SystemExit 穿透；22+6 调用点；身份级 delegation + SystemExit(2) 契约钉）
- [x] Family J: `_write_evidence` 4×7 → `common.write_evidence(workspace, name, data)`（dexdc 3-arg 为准；11 调用点文件名上提；apkid 经 `_hooks_path.load_module_by_path` 桥唯一名 `tools_static_common`；身份级 delegation + 契约钉）
- [x] Family K: tolerant JSONL loop 19 循环点/18 文件 → `scripts/kunglao_log.iter_jsonl` 单 reader（hook 域导入安全裁决见 Recon；逐文件委托断言 + json.loads/JSONDecodeError 残留 pin；kunglao_upgrade rewrite 形与 bench_analyze strict 形界外点名不转）
- [x] Family F: utc_now 重数（四说 7/33/50/20 → 实数 53 份定义：datetime 8 / strftime-Z 23 / isoformat-Z 20 / +00:00 2）→ `scripts/harness_common.py` utc_now/utc_now_z/utc_now_iso 单源 + 53 份委托（B/C 字节等价收敛、D 真变体保留）；守护测试 confinement/wiring/identity/契约钉
- [x] Family G: conftest fork 清零 —— #811 裁决(34e1603)已删 5 个被遮蔽 root fixtures；本卡补防复活机械钉 test_conftest_single_source_863g(4 钉：root 禁 5 名/必持 5 夹具/golden_master #317 UTF-8 解码/fixture 行为解析钉)

## Package 2（no-backward-compat 九项 + lint 裁决）— 863-d/e 重执行

> 勘误：proposal 头部原称 Package 2 已先行交付（PR #875）——不实：54eef78（#875 血统内）实际 diff 仅 --help/ 垃圾文件（+126，零代码删除）；真实删除 commit 371712d 悬空在 feat/863-enforcement-mechanism，未进 dev。f8022ad 上九项全存活。

### 批 1（863-d，本 PR）— done
- [x] priority_ratio.next_tier_cost（零活体消费者：_cheapness_order 实调 cheapness）
- [x] blind_gate _ZERO_HITS_PATTERNS/_has_zero_hits（诊断已走 #56 广义基）
- [x] references_recall.parse_index shim
- [x] convergence_check._scan_active_workers 壳 + test_worktree_marker 两测试改走 _scan_workers
- [x] dispatch_gate DISPATCH_RE re-export + v0-local-fallback 收敛为显式失败；retirement_gate 白名单配对清理
- [x] 机械守卫 tests/test_compat_removal_863d.py（五 tripwire + import-failure 行为钉）

### 批 2（863-e，已合于 #899）

- [x] wire_up_settings deprecated alias（保模块本体））
- [x] worker_budget._ShimModule + _PROPAGATE_TO + 3 测试文件
- [x] validate_index._LEGACY_UNANNOTATED（+29 entries 机械回填 + _CAPABILITY_TAGS 扩 27 标签）
- [x] digest_build pre-contract fallback
- [x] lint_facts/migrate_facts 冲突裁决
- [x] promote_lesson shadowed def + _read_lesson_frontmatter helper（额外）
- [x] kunglao_verify --grace/--grace-scan + kunglao.py 镜像 + schema.md 段（额外）
- [x] references_recall.parse_index + dispatch_gate.DISPATCH_RE + convergence_check._scan_active_workers + blind_gate._ZERO_HITS 实际由 #899 补做（卡侧错列入批 2）


- [ ] 全量质量门 + CI
