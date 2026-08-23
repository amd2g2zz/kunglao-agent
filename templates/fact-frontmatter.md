# Fact Frontmatter Template — kunglao × malware-veri-notes aligned schema (#336)

Authoritative template for kunglao fact files (`facts/F<NNN>-<slug>.md`).
The schema is defined by `malware-veri-notes/references/frontmatter-schema.md`
(live skill dir, not this repo). This template is the kunglao-side projection:
the 12 mandatory fields of the schema, plus the documented kunglao extension
layer. Validation: `python scripts/lint_facts.py <WORKSPACE>` — a fact that
fails lint is unqualified and must not enter the fact base.

## 12 mandatory schema fields

| # | Field | Rule |
|---|-------|------|
| 1 | `id` | `<FNNN>-<slug>`; unique in the whole project; the file is `facts/<id>.md` for new facts |
| 2 | `type` | `fact` |
| 3 | `title` | Human-readable, unicode allowed |
| 4 | `status` | Claim strength: `PROVEN`/`INFERRED`/`NEGATIVE`/`REFUTED`/`VERIFIED`/`OPEN`/`DEFERRED`. Workflow states (`PARTIALLY-VERIFIED`, `STAMP`) are NOT legal here — see `references/state-mapping.md` |
| 5 | `created` | ISO date the node was first written. Never backdate |
| 6 | `last_reviewed` | ISO date of last audit; ≥ `created` |
| 7 | `source` | 8-value enum (below) |
| 8 | `confidence` | `high`/`medium`/`low` — must match the status×source matrix (below) |
| 9 | `claim_id` | `C-NNN` stable claim id (matches claim-register.yaml) |
| 10 | `boundary_type` | One of 9 values (below) |
| 11 | `promotion_gate` | The promotion CONDITION, not a verification command. Empty exactly for `confirmed`/`pure_negative`/`contradiction`/`coordinate` |
| 12 | `provenance` | ≥1 entry, each with `role` + `path`/`url`/`bytes` + `content_sha256` + `credibility` |

Plus the schema pin (#536): every fact carries `schema_rev: 1` in its
frontmatter — the revision of THIS template it was written against. The
schema authority lives in the live skill dir
(`malware-veri-notes/references/frontmatter-schema.md`); the pin makes
silent semantic drift mechanically detectable (`lint_facts` reports
`active_schema_rev: 1` so consumers can compare).

## source enum (8 values)

`static-decompile` · `dynamic-trace` · `frida-capture` · `qiling-emu` ·
`vt-pivot` · `public-osint` · `inference` · `analyst-judgment`

## status × source × confidence matrix

| status | legal source | confidence |
|--------|--------------|------------|
| PROVEN | any except `inference` / `analyst-judgment` | `high` only |
| INFERRED | any | `medium` only |
| NEGATIVE | static-decompile / dynamic-trace / qiling-emu / vt-pivot / public-osint | `high` only |
| REFUTED | any except `inference` / `analyst-judgment` | `high` only |
| OPEN / DEFERRED | omit both fields | omit |

## boundary_type (9 values) + promotion_gate

- Open boundaries (`capability_not_executed`, `link_not_closed`, `source_derived`, `observation`, `numeric`): gate MUST be non-empty — write the exact evidence that would reclassify this fact as `confirmed`. NOT `L1 sha256 reproduce via …`.
- Empty-gate types (`confirmed`, `pure_negative`, `contradiction`, `coordinate`): gate MUST be empty.
- `pure_negative` pairs with `status: NEGATIVE` and (if set) `confidence_zh: 不支持`.

## provenance entry (with ICD-203 #1 credibility)

```yaml
provenance:
  - {role: sample_raw,        path: bins/<sha1>, content_sha256: "<64-hex>", credibility: A1}
  - {role: decompiled_c,      path: evidence/static-ghidra.json, content_sha256: "<64-hex>", credibility: A2}
  - {role: recompute_script,  path: runs/verify-fNNN.py, content_sha256: "<64-hex>", credibility: A2}
```

- `content_sha256` = sha256 of the artifact bytes (migrate_facts.py computes it).
- `credibility` = Admiralty code `{letter}{digit}`: source reliability A (completely
  reliable) → F (unreliable) × information credibility 1 (confirmed) → 6 (cannot be
  judged). Role defaults: sample_raw/capture_log/screenshot/hex_bytes_inline → `A1`;
  decompiled_c/disassembled_s/recompute_script → `A2`; `other` → `B3`; `cti-*` files → `C5`.
- Hard rule: any script called from `reproduce:` MUST be a provenance entry with
  `role: recompute_script`.

## kunglao extension layer (above the schema)

kunglao keeps four fields the schema does not define. They are an explicit
extension layer — consumed by `scripts/kunglao_verify.py` (#332), NOT part of
the 12 mandatory fields, but REQUIRED on every kunglao fact:

| Field | Meaning |
|-------|---------|
| `claim` | kunglao claim summary line (kept for worker/verify compatibility) |
| `reproduce` | L1 mechanical reproduce command (runs with cwd=facts/) |
| `expected` | L1 oracle: sha256 of reproduce stdout, or assignment-class `field=value` assertions |
| `verified` | date of last L1 pass (`pending` when none yet) |

Plus the verifier gate: `verify_status` ∈ `pending`/`partial`/`passes`/`fails`/`stale`
(schema Layer-4 field). Two-layer mapping: `references/state-mapping.md`.

## Complete example (passes lint_facts.py on first write)

```yaml
---
id: F999-example-c2-endpoint
type: fact
schema_rev: 1
title: "C2 endpoint extraction from XOR-encoded config"
status: PROVEN
verify_status: passes
created: 2026-08-13
last_reviewed: 2026-08-14
source: static-decompile
confidence: high
claim_id: C-999
boundary_type: observation
promotion_gate: "Runtime capture of HttpSendRequestW to the decoded endpoint from this process"
confidence_zh: 可确认
provenance:
  - {role: sample_raw, path: bins/865e8eb489b2935b745502026a81e1ef9a6ad6b9, content_sha256: "6cecd136d02b71948cdc8a36251c977629a877da5696d5631bf6b63289b3b9c5", credibility: A1}
  - {role: decompiled_c, path: evidence/static-ghidra.json, content_sha256: "271ebfab8606ca68137cb9573c563713e6bf8613736722aabe535ccc06bc8346", credibility: A2}
  - {role: recompute_script, path: runs/verify-f999.py, content_sha256: "271ebfab8606ca68137cb9573c563713e6bf8613736722aabe535ccc06bc8346", credibility: A2}
claim: "C2 endpoint extraction from XOR-encoded config"
reproduce: "python ../runs/verify-f999.py"
expected: "c2_endpoint=cdk.steam.work xor_key=0x4d"
verified: 2026-08-14
---
```

On use: replace `F999`/`C-999`/hashes/dates; `content_sha256` values are the real
sha256 of each artifact (`python scripts/migrate_facts.py` computes them, or
`sha256sum <path>`); delete `confidence_zh` if the 5-verb mapping does not apply.

ICD-203 landing fields per rule: see `references/state-mapping.md`.
