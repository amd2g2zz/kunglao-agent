# templates/frida/ — Frida script templates

CFG (caller→callee call-graph) capture and analysis
templates, for VM-side dynamic instrumentation (layering: tool
home = tools/frida/, templates = templates/frida/).

> **VM-only (hard prohibition #5)**: scripts instantiated from these
> templates run **on the VM channel only** (`<VM_IP>:1337`) — hooks may be
> loaded only inside the analysis VM; the host channel is forbidden. Never
> use these templates (or their instances) on host processes, and never run
> or exchange hook artifacts over the host channel; traces must first be
> exported via the VM channel, then reduced offline on this side.

| Template | What it generates | Required params |
| --- | --- | --- |
| `cfg-hook.js.tmpl` | Frida CFG capture hook: `Interceptor.attach` on every target export, recording (caller, target, args_count, thread_id, ts) into a shared buffer, flushed in batches as JSONL to OUTFILE | TARGET_MODULE, TARGET_EXPORTS (comma-separated list), CALL_DEPTH, OUTFILE, SAMPLE_SHA256 |
| `cfg-analyze.py.tmpl` | trace reduction analyzer: unique caller→callee edge table + per-callee call counts + top-N callers, writing edges.csv + summary.md (deterministic ordering, idempotent overwrite, explicit inputs/outputs) | TRACE_FILE, SAMPLE_SHA256, OUT_DIR |

## When to use

- **cfg-hook**: when you need call-graph capture on a target module's
  exported functions (API call capture, CFG-rebuild prerequisite, behavior
  baseline), loaded in a Frida session inside the VM.
- **cfg-analyze**: after the hook produces a trace (already exported via the
  VM channel), reduce it to edge tables and statistics; deterministic output
  — same input reproduces and diffs cleanly.

## Instantiation

`scripts/template_gen.py` currently does **not** cover this directory: its
`REQUIRED_PARAMS` registry is hardcoded for the three
`templates/scripts/*.py.tmpl` templates (output fixed to `.py`). Templates
here are currently **instantiated manually** (single-pass placeholder
substitution; values are inserted into quoted strings in the template — the
caller is responsible for escaping quotes/backslashes in values, same rule
as template_gen.py):

```bash
# cfg-hook.js (substituted on the VM, then loaded by Frida)
sed -e 's/{{TARGET_MODULE}}/target.dll/' \
    -e 's/{{TARGET_EXPORTS}}/ExportA,ExportB/' \
    -e 's/{{CALL_DEPTH}}/5/' \
    -e 's/{{OUTFILE}}/trace-cfg.jsonl/' \
    -e 's/{{SAMPLE_SHA256}}/<sha256>/' \
    templates/frida/cfg-hook.js.tmpl > cfg-hook.js

# cfg-analyze.py (offline reduction on this side)
sed -e 's/{{TRACE_FILE}}/trace-cfg.jsonl/' \
    -e 's/{{SAMPLE_SHA256}}/<sha256>/' \
    -e 's/{{OUT_DIR}}/out-cfg/' \
    templates/frida/cfg-analyze.py.tmpl > cfg-analyze.py
```

Future extension: wire the frida templates into `template_gen.py`'s
dynamic discovery or registry (requires syncing REQUIRED_PARAMS and
supporting both `.js`/`.py` output extensions). Until the tools migrate out
of `scripts/`, do not register them in tools/_INDEX.yaml (see
tools/frida/README.md).
