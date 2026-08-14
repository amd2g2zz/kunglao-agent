# tools/auxiliary — 辅助工具家

## 工具

### sanitize.py — 样本派生文本净化 CLI (#307 / #333)

确定性文本净化,供样本派生内容进入 LLM worker 上下文前调用。

- `--mode zero-width|homoglyph|markers` — 单注入面净化(零宽字符 / 同形字 / 指令标记)
- `--mode ansi` — 剥离 ANSI escape 序列(CSI/OSC/DCS/Fe)与 C0 控制字符(保留 `\n` `\t`,含 DEL),输出 `ansi_count`/`ctrl_count` + 前后 sha256(#333;`full` 不含此 pass,保持 #307 full 语义不变)
- 默认(full)= 三个注入面全做;`--json` / `--reproduce` / `--report-only` 输出契约见模块 docstring

接入点(worker 读取工具输出进入上下文前)由 #310 合并后单独跟进,见 issue #333。

## 与索引文档的关系

worker 先读 `tools/_index-aux.md`（aux 域 5 件工具的 6 段契约条目： 用途/用法/输入/输出/exit code/when_not， 用法可直接复制）；本 README 只说明家内文件分工与目录沿革。机器契约见 `tools/_INDEX.yaml`。
