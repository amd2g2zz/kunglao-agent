# templates/scripts/ — script-generation templates

Templated reusable analysis-script generation templates,
deterministically instantiated by `scripts/template_gen.py` (placeholder
`{{KEY}}` substitution + generated header).

**Lane scope (issue 208)**: the three shipped templates are MALWARE-lane
templates — their first required params are `sample_path, sample_sha256`,
i.e. they assume a binary sample under `bins/<sha>`. A non-malware lane
(algorithm / protocol / web / data / app) generates its scripts from its
own lane contract instead of these: its CLI signature is keyed on the lane
material (`corpora`/capture/dataset path), never on `sample_path`. The
lane-specific templates are a DOCUMENTED STUB — `template_gen.py` +
`REQUIRED_PARAMS` stay the single source of truth for the CLI contract, so
a lane template lands there when it lands here, with its own required
params and this table updated in the same change.

| Template | What it generates | Required params |
|---|---|---|
| `stage-unpack.py.tmpl` | stage unpacking analysis (carve -> hash -> dump) | sample_path, sample_sha256, offsets, stage_names, output_dir |
| `decryption-analysis.py.tmpl` | decryption-flow analysis (locate routine -> params -> decrypt -> hash) | sample_path, sample_sha256, decrypt_offset, key_va, output_dir |
| `disasm-pipeline.py.tmpl` | disassembly pipeline (entry -> disasm -> xref -> summary) | sample_path, sample_sha256, entry_points, output_dir |

Usage and exit codes: `docs/templates-inventory.md`; when adding a template,
sync its required params into `scripts/template_gen.py`'s `REQUIRED_PARAMS`
(single source of truth).
