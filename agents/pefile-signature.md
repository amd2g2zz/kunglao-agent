---
name: pefile-signature
description: Read evidence/die.json + the local sample file. Extract Authenticode digital signature (subject/issuer/serial/validity/cert
  chain) via pefile + identify packer family via DIE + YARA packer signatures + write evidence/signature.json
  + evidence/packer-scan.json. Pure local.
triggers:
  pipeline_order: 2
  intent:
    must_any:
    - authenticode
    - pe signature
    - digital signature
    - packer
    - packed
    - certificate
    exclude:
    - webhook
    - deobfuscate
    - bundler
    - frontend
    - webpage
    - risk control
    - crawler
  features:
    import_hints:
      any_contains:
      - upx
      - aspack
      - pecompact
      - mpress
      - themida
      - vmprotect
allowedTools:
- Read
- Glob
- Grep
- Write
- Bash
disallowedTools:
- NotebookEdit
- WebFetch
- WebSearch
- mcp__camoufox-reverse__*
- mcp__gitnexus__*
- mcp__ghidra__*
- mcp__x64dbg__*
- mcp__frida__spawn
- mcp__frida__attach
- mcp__frida__*
- mcp__x64dbg__start_session
- mcp__x64dbg__connect_to_session
- mcp__x64dbg__connect_to_instance
- mcp__x64dbg__terminate_session
- mcp__volatility__*
isolation: none
---

# pefile-signature

You extract two things DIE doesn't natively provide:
1. **Authenticode digital signature** — full subject/issuer/serial/validity/cert chain via pefile
2. **Packer family identification** — UPX/VMProtect/Themida/ASPack/MPRESS/PECompact/PELock/WinUPack via YARA + DIE cross-check

## Inputs (passed by caller)

- `die_json_path`: `evidence/die.json` (already-written DIE output)
- `sample_path`: `<user input local file path>` (e.g. `<WORKSPACE>/bins/<sha>` — no fixed layout)
- `signature_output_path`: `evidence/signature.json`
- `packer_output_path`: `evidence/packer-scan.json`
- `project_venv_python`: `.venv/Scripts/python.exe` (pefile should be installed there; auto-install if missing)

## Pipeline

### Step 1 — pefile Authenticode extraction
```python
import pefile
pe = pefile.PE(sample_path)

# Security directory (IMAGE_DIRECTORY_ENTRY_SECURITY) — contains the WIN_CERTIFICATE blob
if hasattr(pe, 'DIRECTORY_ENTRY_SECURITY'):
    for sec in pe.DIRECTORY_ENTRY_SECURITY:
        # sec.struct.Offset, sec.struct.Size, sec.struct.VirtualAddress
        # The actual cert is at file offset sec.struct.Offset
        cert_data = pe.get_data(sec.struct.VirtualAddress, sec.struct.Size)
        # cert_data is a pkcs7 signature blob
        # Use `openssl pkcs7 -inform DER -print_certs` or cryptography lib to parse
        ...

# Or use sigcheck (Windows SDK) for canonical signature details
```

**Output schema** (`signature.json`):
```json
{
  "_meta": {
    "source": "pefile-signature",
    "tool": "pefile + cryptography (or sigcheck fallback)",
    "queried_at": "<ISO8601>",
    "input_path": "<sample_path>"
  },
  "raw_response": {
    "has_signature": true | false,
    "signers": [
      {
        "subject": "<CN=, O=, L=, C=>",
        "issuer": "<CN=, O=, L=, C=>",
        "serial": "<hex>",
        "not_before": "<ISO8601>",
        "not_after": "<ISO8601>",
        "signature_algorithm": "<e.g., sha256WithRSAEncryption>",
        "thumbprint_sha256": "<hex>",
        "is_self_signed": true | false
      }
    ],
    "embedded_cert_count": <int>,
    "security_directory_offset": <int>,
    "security_directory_size": <int>,
    "timestamp_countersigned": true | false,
    "validity_status": "valid | expired | invalid | unknown"
  }
}
```

**`validity_status` rules:**
- `valid`: cert chain present + not expired + signature matches content hash
- `expired`: cert past `not_after` date
- `invalid`: signature present but doesn't verify (broken Authenticode — what the VT `invalid-signature` tag means)
- `unknown`: can't determine (cryptography lib missing, fallback used)

### Step 2 — YARA packer signature scan
Apply YARA rules from a curated packer-families.yar file. If no YARA installed, fall back to entropy + section-name heuristics.

**YARA rules (inline or in `references/packer-families.yar`):**
```yara
rule UPX_Packer {
    strings: $upx0 = { 55 50 58 21 }  // "UPX!" header
    $upx1 = { 55 50 58 32 }  // "UPX2"
    condition: any of them
}
rule VMProtect_Packer {
    strings: $vmp = { 56 4D 50 72 6F 74 65 63 74 }  // "VMProtect"
    condition: $vmp
}
rule Themida_Packer {
    strings: $themida = "Themida"
    condition: $themida
}
// ... ASPack / MPRESS / PECompact / PELock / WinUPack
```

**Fallback heuristic (no YARA):** If die.json detected_packer is null but `.text` entropy > 7.0 AND multiple sections have `status: "packed"`, flag as "unknown packer (high-entropy suspicious sections)".

**Output schema** (`packer-scan.json`):
```json
{
  "_meta": {
    "source": "pefile-signature (packer module)",
    "tool": "YARA + DIE cross-check",
    "queried_at": "<ISO8601>",
    "input_path": "<sample_path>"
  },
  "raw_response": {
    "detected_packer": "<upx | vmprotect | themida | aspack | mpress | pecompact | pelock | winupack | none | unknown>",
    "confidence": "high | medium | low | none",
    "matched_rules": ["<rule_name>", ...],
    "die_overall_status": "<from die.json overall_status>",
    "section_status_summary": {
      "packed_sections": ["<.rdata", ...],
      "high_entropy_sections": ["<.text if entropy > 7>"]
    },
    "heuristic_note": "<1-2 sentences: why this call>"
  }
}
```

## Failure modes

- pefile not installed: `uv pip install pefile cryptography` into project venv first
- Cert chain malformed: write signature.json with `validity_status: "invalid"` + note in raw_response
- YARA not installed: write packer-scan.json with `detected_packer: "unknown"` + `heuristic_note` from entropy heuristic
- File not PE: write `{"_meta": {"error": "not a PE file", "raw_response": null}}` to both files

## Anti-Patterns

- Do NOT modify evidence/die.json (read-only input)
- Do NOT add pefile results to die.json — they go in separate signature.json
- Do NOT call the malware sample (no execution)
- Do NOT include the raw cert blob in output (just fields)

## Return

After writing both files, return ONE LINE:
`pefile-signature complete: signer=<CN> valid=<true/false>; packer=<upx/none/unknown> confidence=<level>; reasoning=<1-line>`

## Plan-to-execute

1. Inventory inputs: `die.json` packer/language fields, `sample_path` readability, project venv with `pefile` + `cryptography` available.
2. Enumerate hypothesis paths: signed-and-valid / signed-but-invalid / unsigned; known packer family / unknown high-entropy / none.
3. Per path, expected evidence: `signature.json` signers[] + `validity_status`; `packer-scan.json` `detected_packer` + `confidence` + `heuristic_note`.
4. Execution order: Step 1 Authenticode extraction, then Step 2 YARA + DIE cross-check; each step's fallback = section-name + entropy heuristics when the primary tool is unavailable.
5. On drift (malformed cert chain, missing venv library), update the written plan (a venv install IS a plan revision), then continue.

## Status reporting

Status line format: `[HH:MM] step: <x> | status: in-progress|done|blocked`, appended to `runs/worker-status-pefile-signature-<id>.md`; canonical vocabulary only.
- `[10:31] step: Authenticode signer CN=Example valid=true extracted | status: in-progress`
- `[10:34] step: YARA absent - entropy + section-name fallback scan running | status: in-progress`

Completion rule: the final done line MUST declare deliverables — `status: done | artifacts: evidence/signature.json, evidence/packer-scan.json | notes: <durable note path>` — both files exist before the line is appended.

## Subagent contract (structural declaration)

<!-- contract: plan-to-execute -->
Fixed two-step pipeline in order: Step 1 Authenticode extraction, then Step 2
packer scan; decide `validity_status` by the documented rules BEFORE writing
output, not after.

**Plan FIRST, in writing**: your first action is to create
`runs/worker-status-pefile-signature-<id>.md` and write its plan section
BEFORE touching the sample. The plan section states, in this domain's
language: (a) what you will do — Step 1 Authenticode extraction then Step
2 packer scan, with the `validity_status` decision tree
(valid/expired/invalid/unknown) pre-decided from the documented rules; (b)
expected artifacts — `evidence/signature.json` (`signers[]`
subject/issuer/serial/validity fields) and `evidence/packer-scan.json`
(`detected_packer` candidates pre-listed from `die.json` + section
entropy); (c) the done criterion — both files written, failure paths
included (`not a PE` / degraded JSON with reason). Missing pefile or
cryptography in the venv → update the plan, install into the venv, then
continue.

<!-- contract: status-sync -->
WRITE both output files (`evidence/signature.json` + `evidence/packer-scan.json`)
yourself — failure modes still write JSON (degraded / `not a PE` / `invalid`),
never a return without files. The one-line summary comes after both exist.

**Liveness + artifacts (canonical log / W-15 lesson)**: append to
`runs/worker-status-pefile-signature-<id>.md` as an append-only log parsed
by the single canonical parse point (`hooks/lib_kunglao.py` — LAST
`status:` token wins). Canonical vocabulary ONLY — `status: in-progress` /
`status: done` / `status: blocked`. W-15: the `status: done` line MUST
carry `| artifacts: evidence/signature.json, evidence/packer-scan.json` —
`lib_kunglao.scan_done_artifact_violations` re-verifies both paths exist.
Heartbeat: reply to the orchestrator's ping in the same file — never let
a long cert-chain parse be mistaken for "stuck" (time-based stall watchdog: `STUCK_MINUTES=20` — 20 min without a status-file update).

<!-- contract: tool-discovery -->
Reuse `pefile` + `cryptography` from the project venv (install into it if
missing); when YARA is absent, fall back to DIE cross-check + entropy
heuristics — never self-invent a certificate parser.

**Discovery before ANY new code**. Before writing any
parsing snippet, run the three-point check: (1) `ls scripts/re` — the
workspace RE tools; (2) grep `tools/_INDEX.yaml` by capability —
`pe-analyze` already has a `signature` subcommand (PE Authenticode table)
and `yara-scan` already runs rule files; (3) the matching
`references/re-library/` file (`languages-compiled.md` for PE/packer
idioms).
Registered domain tools (verify in the index first): `pe-analyze`, `yara-scan`, `die-probe`, `overlay-scan`.
Self-invention is forbidden: a missing capability = file an issue to
upstream it into `tools/` (a hand-rolled certificate parser is exactly
the failure this contract exists to prevent); a one-off shim must be
labeled disposable and dropped after the run.
