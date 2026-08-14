# tools/auxiliary — 辅助工具家

## 工具

| 文件 | 工具 | 职责 |
|---|---|---|
| `sanitize.py` | `sanitize-text` | 样本派生文本 prompt 注入净化 CLI(#307/#333, 见下) |
| `audit_legacy_proven.py` | `audit-legacy-proven` | legacy PROVEN claim 审计(BLIND 签名维度 + 索引溯源性; #340 起由 tools/ 根层归位) |
| `capture_golden.py` | `capture-golden` | golden master 基线采集(#340 起归位) |
| `measure_blind_coverage.py` | `measure-blind-coverage` | BLIND 盲验覆盖率测量(#340 起归位) |
| `measure_cold_start.py` | `measure-cold-start` | 冷启动 token 基线测量(#340 起归位) |

`audit_legacy_proven.py` 惰性复用 `tools/pipelines/build_evidence_index.py` 的索引构建器(跨类目 import, 自行把 `tools/pipelines/` 加上 `sys.path`)。

### sanitize.py — 样本派生文本净化 CLI (#307 / #333)

确定性文本净化,供样本派生内容进入 LLM worker 上下文前调用。

- `--mode zero-width|homoglyph|markers` — 单注入面净化(零宽字符 / 同形字 / 指令标记)
- `--mode ansi` — 剥离 ANSI escape 序列(CSI/OSC/DCS/Fe)与 C0 控制字符(保留 `\n` `\t`,含 DEL),输出 `ansi_count`/`ctrl_count` + 前后 sha256(#333;`full` 不含此 pass,保持 #307 full 语义不变)
- 默认(full)= 三个注入面全做;`--json` / `--reproduce` / `--report-only` 输出契约见模块 docstring

接入点(worker 读取工具输出进入上下文前)由 #310 合并后单独跟进,见 issue #333。

## 与索引文档的关系

worker 先读 `tools/_index-auxiliary.md`（auxiliary 域 5 件工具的 6 段契约条目： 用途/用法/输入/输出/exit code/when_not， 用法可直接复制）；本 README 只说明家内文件分工与目录沿革。机器契约见 `tools/_INDEX.yaml`。类目 id 与目录名一致（#340；旧 id `aux` 是 Windows 保留设备名，无法作目录名，故改 id 随目录）。
