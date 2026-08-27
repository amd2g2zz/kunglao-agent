# templates/ — Workspace and Script-Generation Templates

Two template families live here:

- `state/`, `CLAUDE.md.*.tmpl`, `fact-frontmatter.md` — workspace scaffold
  templates consumed by `/init` (see SKILL.md Phase 0).
- `scripts/*.py.tmpl` — analysis script generation templates,
  instantiated deterministically by `scripts/template_gen.py`.

## Script-generation templates

Each `scripts/<name>.py.tmpl` carries `{{KEY}}` placeholders, a
field-validated process skeleton, and explicit TODO markers for the parts
an analyst must fill per sample. Templates are not fake implementations —
the mechanical parts (hashing, JSON, parsing) are implemented; the
sample-specific parts surface as `NotImplementedError` TODOs.

Generate with (deterministic, stdlib only):

```bash
python scripts/template_gen.py --template <name> --name <slug> --out <dir> \
    --param sample_path=... --param sample_sha256=... [--param ...] [--force]
```

Exit codes: `0` generated; `2` usage error (unknown template / bad --name /
malformed --param); `3` missing required params (stderr lists them); `4`
target exists without `--force`; `5` template defect (uncovered placeholder,
fail-closed). Identical inputs produce byte-identical output except the
`generated ... on <ts>` header line.

`scripts/template_gen.py`'s `REQUIRED_PARAMS` is the single source of truth
for the CLI contract; when adding a template, update `REQUIRED_PARAMS` and
this catalog together.

| Template | Generates | Required params |
| --- | --- | --- |
| `stage-unpack.py.tmpl` | stage unpack analysis (carve → hash → dump) | sample_path, sample_sha256, offsets, stage_names, output_dir |
| `decryption-analysis.py.tmpl` | decryption flow analysis (locate routine → params → decrypt → hash) | sample_path, sample_sha256, decrypt_offset, key_va, output_dir |
| `disasm-pipeline.py.tmpl` | disassembly pipeline (entry → disasm → xref → summary) | sample_path, sample_sha256, entry_points, output_dir |

### Classification framework (for future script absorption)

The absorption half (migrating 236 field scripts from the Windows
host) classifies each script by reuse surface when that host becomes
reachable:

| Class | Criteria (any one promotes; all must hold to demote) | Action | Destination |
| --- | --- | --- | --- |
| Generic CLI | Logic is sample-independent or trivially parameterizable; reusable across same-class samples; no per-sample magic numbers | migrate — port as a standalone parameterized CLI (`scripts/`, deterministic discipline), register in `tools/_INDEX.yaml` if an analysis tool | scripts/ + tools/_INDEX.yaml |
| Semi-generic | Process is generic but carries per-sample constants (offsets, key addresses, stage table positions) | adapt — extract constants as parameters; sink the reusable skeleton into a template | templates/scripts/*.tmpl or scripts/ |
| One-off | Ad-hoc code for a single sample, no reuse value or not parameterizable | template — keep as a reproducible skeleton, instantiated per sample by `template_gen.py` | templates/scripts/*.tmpl |

Rule of thumb: if it can be parameterized, migrate; if the flow is generic
but constants vary per sample, adapt into a template; if it is pure
single-sample hackery, template it.

### Per-template analyst TODOs

- `stage-unpack` — `carve_stages()` (this sample's actual packer split
  boundaries), optional `verify_expected()`
- `decryption-analysis` — `recover_key()` (key extraction at KEY_VA),
  `decrypt_payload()` (algorithm body; if it matches one of the 8 algorithm
  families in `tools/_INDEX.yaml`, reuse tools/ instead of rewriting)
- `disasm-pipeline` — `pin_arch()` (architecture/mode), `interesting_targets()`
  (xref targets), `analyze()` (per-entry analysis notes)

### Registration

Scripts or templates whose destination requires `tools/_INDEX.yaml` entry
follow that file's entry schema
(name/category/capability/tier/cost_tier/input_output); no parallel index
is created for templates.
