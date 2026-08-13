# tools/ghidra — Ghidra 自动化工具家

存放 Ghidra 相关自动化：analyzeHeadless 封装（`run_ghidra_postscript.py`）与 5 件
参数化 postScript 工具（issue #293 吸收，sa-ghidra 定稿）。脚本一律 `--key=value`
参数化，输出 UTF-8 JSON（带 `schema` / `program` / `image_base`），`--out` 绝对路径
自 mkdirs。`GhidraJsonScript.java` 是共享基类（`getArg` / `unescape` / JSON writer）。

## 调用入口

```bash
python tools/ghidra/run_ghidra_postscript.py \
  --tool ghidra-recon --binary <abs-sample> --out <abs-output.json> \
  [--key value ...]   # 其余 --key=value 原样转发给 postScript
```

- `GHIDRA_HOME` 解析顺序：`--ghidra-home` → 环境变量 → `analysis_state.txt`
  （`ghidra_home=...` 行）；缺失或 `analyzeHeadless.bat` 不存在 → exit 2 带指引。
- 临时 Ghidra project 目录用完即删（`--keep-project` 保留）。

## postScript 工具（5 件）

| 工具 id | Java 源 | 契约（input → output） |
|---|---|---|
| `ghidra-recon` | `GhidraRecon.java` | 样本 + `--search-terms/--expected-exports/--sha256/--sha1` → JSON（imports/exports/functions/strings_of_interest/suspicious_api_calls/focus_functions/go/findings） |
| `ghidra-decompile-functions` | `DecompileFunctions.java` | 样本 + `--addresses/--strings/--window` → JSON（per-target decompiled C + disasm window + string xrefs） |
| `ghidra-vtable-struct` | `GhidraExportVtableStruct.java` | 样本 + `--address/--name/--class/--apply` → JSON（vtable slot 表 + function fields） |
| `ghidra-evidence-annotations` | `GhidraEvidenceAnnotations.java` | 样本 + `--mode apply\|verify + --tsv` → JSON（annotation 应用/校验摘要，verify 失败抛错 fail-closed） |
| `ghidra-scan-pointer` | `GhidraScanPointer.java` | 样本 + `--mode xref\|window`（xref: `--addresses/--bytes`; window: `--center/--window`）→ JSON（xref/raw 8-byte 指针扫描命中） |

所有工具基类 `GhidraJsonScript.java`（抽象，不作为 postScript 运行）。
