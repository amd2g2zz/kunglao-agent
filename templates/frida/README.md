# templates/frida/ — Frida 脚本模板

issue #278 P3：CFG（caller→callee 调用图）捕获与分析模板，供 VM 侧动态
插桩使用（目录分层 #282：工具家 = tools/frida/，模板 = templates/frida/）。

> **VM-only（硬禁令 #5）**：本目录模板实例化出的脚本**仅限 VM 通道**
> （`<VM_IP>:1337`）执行——hook 只允许在分析 VM 内加载，宿主通道禁止。
> 绝不把这些模板（或其实例）用于宿主进程，也绝不通过宿主通道运行或
> 收发 hook 产物；trace 只能先由 VM 通道导出、再在本侧离线归约。

| 模板 | 生成什么 | 必填参数 |
| --- | --- | --- |
| `cfg-hook.js.tmpl` | Frida CFG 捕获 hook：`Interceptor.attach` 每个目标导出，记录 (caller, target, args_count, thread_id, ts) 入共享缓冲，按批 flush 为 JSONL 到 OUTFILE | TARGET_MODULE, TARGET_EXPORTS（逗号列表）, CALL_DEPTH, OUTFILE, SAMPLE_SHA256 |
| `cfg-analyze.py.tmpl` | trace 归约分析器：唯一 caller→callee 边表 + 每 callee 调用计数 + top-N callers，写 edges.csv + summary.md（#277：确定性排序、幂等覆盖、明确输入/输出） | TRACE_FILE, SAMPLE_SHA256, OUT_DIR |

## 何时使用

- **cfg-hook**：需要对目标模块导出函数做调用图采集时（API 调用捕获、
  CFG 重建前置、行为基线），在 VM 内以 Frida 会话加载。
- **cfg-analyze**：hook 产出 trace 后（已由 VM 通道导出），归约成边表与
  统计；确定性输出，同输入可复现、可 diff。

## 实例化方式

`scripts/template_gen.py` 当前**不**覆盖本目录：其 `REQUIRED_PARAMS` 注册表
硬编码于 `templates/scripts/*.py.tmpl` 三个模板（输出固定为 `.py`）。本目录
模板当前**手动实例化**（占位符单遍替换；值插入模板的引号串内，值中含
引号/反斜杠由调用方负责转义——与 template_gen.py 同口径）：

```bash
# cfg-hook.js（在 VM 内替换后由 Frida 加载）
sed -e 's/{{TARGET_MODULE}}/target.dll/' \
    -e 's/{{TARGET_EXPORTS}}/ExportA,ExportB/' \
    -e 's/{{CALL_DEPTH}}/5/' \
    -e 's/{{OUTFILE}}/trace-cfg.jsonl/' \
    -e 's/{{SAMPLE_SHA256}}/<sha256>/' \
    templates/frida/cfg-hook.js.tmpl > cfg-hook.js

# cfg-analyze.py（本侧离线归约）
sed -e 's/{{TRACE_FILE}}/trace-cfg.jsonl/' \
    -e 's/{{SAMPLE_SHA256}}/<sha256>/' \
    -e 's/{{OUT_DIR}}/out-cfg/' \
    templates/frida/cfg-analyze.py.tmpl > cfg-analyze.py
```

未来扩展：把 frida 模板接入 `template_gen.py` 的动态发现或注册表
（需同步 REQUIRED_PARAMS 并支持 `.js`/`.py` 双输出扩展名）。在工具从
`scripts/` 迁入之前，不注册 tools/_INDEX.yaml（见 tools/frida/README.md）。
