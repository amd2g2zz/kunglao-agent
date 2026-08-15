# templates/scripts/ — script-generation templates

Issue #278 templated half: reusable analysis-script generation templates,
deterministically instantiated by `scripts/template_gen.py` (placeholder
`{{KEY}}` substitution + generated header).

| Template | What it generates | Required params |
|---|---|---|
| `stage-unpack.py.tmpl` | stage unpacking analysis (carve -> hash -> dump) | sample_path, sample_sha256, offsets, stage_names, output_dir |
| `decryption-analysis.py.tmpl` | decryption-flow analysis (locate routine -> params -> decrypt -> hash) | sample_path, sample_sha256, decrypt_offset, key_va, output_dir |
| `disasm-pipeline.py.tmpl` | disassembly pipeline (entry -> disasm -> xref -> summary) | sample_path, sample_sha256, entry_points, output_dir |

Usage and exit codes: `docs/templates-inventory.md`; when adding a template,
sync its required params into `scripts/template_gen.py`'s `REQUIRED_PARAMS`
(single source of truth).
