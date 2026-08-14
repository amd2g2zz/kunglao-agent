# tools/auxiliary — 辅助工具家

存放杂项辅助工具：格式转换、fixture 生成、golden 采集、工作区运维等不属于上述任何
工具家的工具。

（原命名 `tools/aux/`——`AUX` 为 Windows 保留设备名，git 无法跟踪，故用 `auxiliary`。）
当前为空。后续从 `scripts/` 迁入具备该职责的模块时落位于此（目录分层 #282）。

## 已落位工具（#339 追加）

| 文件 | 工具(id) | 一句话契约 |
|---|---|---|
| `sanitize.py` | `sanitize-text` | 样本派生文本 prompt 注入净化（zero-width/homoglyph/markers; exit 0 检出 / 1 未检出 / 2 错误），issue #307 吸收 |

> 注： 上文"当前为空"系迁移前遗留描述， 与本节矛盾； 本节为 #339 纯新增段落（冲突规避）， 遗留句收编待 #333。

## 与索引文档的关系

worker 先读 `tools/_index-aux.md`（aux 域 5 件工具的 6 段契约条目： 用途/用法/输入/输出/exit code/when_not， 用法可直接复制）；本 README 只说明家内文件分工与目录沿革。机器契约见 `tools/_INDEX.yaml`。

