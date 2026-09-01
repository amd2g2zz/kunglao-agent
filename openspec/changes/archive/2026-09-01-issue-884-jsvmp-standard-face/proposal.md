# issue-884-jsvmp-standard-face — JSVMP 收编标准面（tools/web 归位 + 知识卡 + 三中二修正 + worker 标准通道）

## Why

#816 的交付形状（scripts/ 独立 CLI + 手工触发词）是被用户否决的 bespoke 形态。VMP 不需要单独机制——与其它 ref 和 tools 同构：方法论进 references（recall 可注入），能力进 tools/（执行注册表 + 类目页 + manifest），worker 经标准通道发现。另有两处实现偏航需一并修正：`confident = f1 and f2`（规格=三中二）与 `_semantics_ratio` 无 switch 时返回 1.0 的空洞真值。

## Recon

### 锚点表（计划锚点 vs 实测）

| 计划锚点 | 实测（wt-816 @1266078） | 判定 |
|---|---|---|
| `tools/_lib/stdio.py` 存在（#863 Family A） | `tools/_lib/stdio.py:10` `def ensure_utf8_stdout()`（接口名是 ensure_utf8_stdout，**不是** force_utf8） | ✓ |
| 兄弟 CLI boot 委托 8+ 处 | 实测 35 处 `from _lib.stdio import ensure_utf8_stdout  # noqa: E402` | ✓ |
| `tools/web/jsvmp_triage.py:158-161` boot import 必然 ImportError | `:159-160` `from utf8_boot import force_utf8`；utf8_boot 仅在 `scripts/utf8_boot.py`，tools/web/ 下 sys.path[0] 不可达，子进程实测 `ModuleNotFoundError` | ✓ 必崩 |
| `tests/test_jsvmp_triage.py:17` SCRIPT 指 scripts/ | `:17` `SCRIPT = ROOT / "scripts" / "jsvmp_triage.py"`；另 docstring `jsvmp_triage.py:16` Usage 行也写旧路径 | ✓ |
| 三中二偏航 `confident = f1 and f2` | `jsvmp_triage.py:108` | ✓ |
| `_semantics_ratio` 空洞真值 1.0 | `jsvmp_triage.py:85-96`，`:94` 无 case_bodies 时 `return 1.0` | ✓ |
| web-re-worker JSVMP 分支 | `agents/web-re-worker.md:87-89`（指 scripts/jsvmp_triage.py）；`:28-29` 路由关键词 jsvmp/vmp/opcode 保留 | ✓ |
| deploy_manifest 刷新 | `scripts/deploy_manifest.py` build_entries FULL MIRROR 反向扫描，`--write` 自动收录 tools/web/ | ✓ |
| 知识卡经 ext-scan 收录 | `tools/ext-scan.py:87` SOURCE_DIRS 含 `("references/re-library", "*.md", "reference")` | ✓ |
| 本地门 `deploy_manifest.py --check` | 实测旗标为 `--verify`（`--check` 报 usage error） | 实现级偏航 Y1 |

### 变更前测试基线

- HEAD 布局（scripts/jsvmp_triage.py + scripts/utf8_boot.py）在 tmp 目录复现：`python -m pytest tests/test_jsvmp_triage.py -q` → **3 passed**（逻辑基线绿）。
- wt-816 当前（rename 已暂存）：3 failed —— 根因 SCRIPT 旧路径不存在 + boot ModuleNotFoundError（`python tools/web/jsvmp_triage.py --json` 实测崩）。即本卡 RED 的自然起点。

### 镜像样例（≥3）

1. `tools/crypto/crypto-tool.py:31-35`（子目录 CLI 的 _lib 注入 + 顶部 import；`__main__` 尾部 `ensure_utf8_stdout(); sys.exit(main())`）：
   ```python
   _TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
   if str(_TOOLS_DIR) not in _sys_io.path:
       _sys_io.path.insert(0, str(_TOOLS_DIR))
   from _lib.stdio import ensure_utf8_stdout  # noqa: E402
   ```
2. `tools/auxiliary/sanitize.py:53-57`（常规 import 之后的别名注入块——jsvmp_triage 顶部已有常规 import，用这个形状）。
3. `tools/ext-scan.py:53-55` + 尾部 `__main__`（#476 review L2：guard 调用留在 CLI entry，import 纯净性）。
4. `_INDEX.yaml` 条目形状：计划说"镜像 crypto-tool 条目"，但 crypto-tool 在 `#729 Rule A` LEGACY 白名单内（`tools/validate_index.py:64-74`），**新条目必须带 provider 块**（`validate_index.py` #729 Rule A：无 provider 且不在白名单 = error）。镜像对象改为带 annotation 块的 `wakaru-unbundle` 条目（`_INDEX.yaml` 尾部：provider/produces/requires/cost_hint/quality 全套）。

### 实现级偏航记录（WHAT/WHY）

- **Y1 `--verify` 不是 `--check`**：deploy_manifest 实际 CLI 旗标 `--write|--verify`。WHY：实测 usage error。不改变门语义。
- **Y2 类目扩张的机械联动（计划未列，#340/#729/#339 契约强制）**：
  - `tools/validate_index.py:111` `CATEGORIES` 加 `"web"` + `:7` 文档注释同步（否则 category 校验 error）。
  - `_INDEX.yaml:11` 注释枚举同步；`web:triage` 加入 `_CAPABILITY_TAGS` 闭词汇（produces 校验要求）。
  - 新建 `tools/web/README.md`（`test_index_docs_contract.py::test_category_readmes_state_relation_to_index_md` 要求类目 README 且提及 `_index-web.md`）。
  - `tests/test_index_docs_contract.py`：`CATEGORY_READMES` 加 `("web", "web")`；`test_yaml_registry_has_29_tools` 的 `len(tools)==36` → 37（该断言历史上随 #692/#728 递增，惯例如此）。
  - `tools/_INDEX.md` 主页四表加 web 行（progressive disclosure 入口一致性）。
- **Y3 知识卡发现面联动（计划未列）**：`references/_INDEX.md` 手工加行（`tests/test_references_index.py` 要求覆盖 references/ 全部 .md）；`tools/_INDEX.ext.yaml` 用 `ext-scan.py` 重生成（`--check` 门）。
- **Y4 release-manifest 联动（计划未列）**：`release_receipt.py --check` 实测 FAIL "undeclared asset: tools/web/jsvmp_triage.py" → `release-manifest.yaml` assets.tools 手工加行。
- **Y5 exit code 三态语义**：jsvmp_triage 是 advisory always-0 姿态；`_index-web.md` 条目按 6 段契约写明 0=triage 完成（命中与否都是 0，advisory）、1/2 预留未用（与 think_seat 同姿态）。不改 CLI 退出语义（超范围）。

无规格级偏航，不触发 RECON-DEVIATION。

## What Changes

1. 归位：保留已暂存的 `git mv scripts/jsvmp_triage.py tools/web/jsvmp_triage.py`。
2. 三中二修正：`_semantics_ratio` → `(ratio, has_cases)`；`f3 = has_cases and ratio >= 0.9`；`votes = f1+f2+f3`；`confident = votes >= 2`；confidence 3/3=high、2/3=medium、else low；verdict 增加 `votes` 字段。
3. boot 修复：镜像 _lib.stdio 惯例（crypto-tool/sanitize/ext-scan 同款），替换 utf8_boot import。
4. 执行注册表：_INDEX.yaml web 类目 + jsvmp_triage 条目（capability `web:triage`，provider 块全套）；validate_index CATEGORIES/_CAPABILITY_TAGS 扩张。
5. 类目页：`tools/_index-web.md`（三特征表）+ `tools/web/README.md` + `_INDEX.md` 主页行。
6. 知识卡：`references/re-library/jsvmp-triage.md`（三特征阈值、判定语义、trace/OPCODE_MAP/replay 方法论纲要）+ `references/_INDEX.md` 行 + ext 索引重生成。
7. worker 标准通道：`agents/web-re-worker.md:87-89` 指向新路径 + 知识卡（路由关键词表保留）。
8. 测试：SCRIPT 路径更新 + 钉住三中二（F1+F3、F2+F3 命中、大数组单独不命中=空洞 F3 绊线、votes/置信档断言），≥6 测试。
9. 清单：release-manifest.yaml 资产行 + deploy_manifest --write。

## Impact

- 受益：JSVMP 识别从 bespoke 收编进标准工具面（注册表/类目页/知识卡/worker 通道/清单全覆盖），三中二消除 {F1,F3}/{F2,F3} 漏报，空洞 F3 被 has_cases 锚定。
- 风险：CATEGORIES 扩张触碰 validate_index/docs-contract 测试面 → 联动更新同 PR 内完成，全量 pytest 兜底。
- 边界：不改 triage 的 advisory 语义与 CLI 参数面；不动 web-re-quickref 的 Advanced topics 索引段（不在 issue 范围）。
