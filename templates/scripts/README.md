# templates/scripts/ — 脚本生成模板

issue #278 模板化半侧：可复用的分析脚本生成模板，由
`scripts/template_gen.py` 确定性实例化（占位符 `{{KEY}}` 替换 + 生成头）。

| 模板 | 生成什么 | 必填参数 |
| --- | --- | --- |
| `stage-unpack.py.tmpl` | stage 解包分析（carve → hash → dump） | sample_path, sample_sha256, offsets, stage_names, output_dir |
| `decryption-analysis.py.tmpl` | 解密流程分析（定位例程 → 参数 → 解密 → hash） | sample_path, sample_sha256, decrypt_offset, key_va, output_dir |
| `disasm-pipeline.py.tmpl` | 反汇编流水线（入口 → disasm → xref → 摘要） | sample_path, sample_sha256, entry_points, output_dir |

用法与退出码见 `docs/templates-inventory.md`；新增模板时把必填参数同步到
`scripts/template_gen.py` 的 `REQUIRED_PARAMS`（单一事实源）。
