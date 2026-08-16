# Machine-Check Oracle Contract (#332) — executable oracle contract

> Single source of truth: `references/machine_check_map.yaml` (loaded by
> `scripts/kunglao_verify.py::load_machine_check_map`). This document is the
> contract narrative; the mapping-table mirror below is mechanically compared
> against the YAML by
> `tests/test_machine_check_contract.py::test_map_parity_with_contract_doc` —
> **both places must be changed together**, or the parity test fails.

## Why

CrackMeBench research (#330): agents over-trust decompiler output. An
independent verifier and the maker can fall into **the same static-analysis
error path** — at which point "independent derivation + conclusion comparison"
passes everything and verification is theater. Verification must terminate in
a **machine check**: a byte/execution-level expected/actual comparison; "the
deliverable was accepted by the oracle" is what counts. "I read the source
and it looks right" is not verification.

## Contract

Every verifier verification record (kunglao-redteam output) must contain
**at least one**:

```json
{"command": "<byte/execution-level check command>", "expected": "<expected value>",
 "actual": "<observed value>", "passed": true}
```

- `command` must be an executable byte/execution-level check (tool +
  comparison); prose like "I read the source and it looks right" does not
  pass.
- `passed` must be a strict boolean. **Any single `passed=false` → the whole
  record fails verification** (STAMP must not promote to PROVEN).
- Missing machine_check → verification fails.

### Record format (runs/verify-redteam-\*.md)

````markdown
## MACHINE-CHECK (oracle contract #332)
```machine_check
[
  {"command": "xxd -p -s 0x0 -l 2 bins/<sha>", "expected": "4d5a",
   "actual": "4d5a", "passed": true}
]
```
````

A single-line form is also accepted: `machine_check: {"command": ..., "expected": ..., "actual": ..., "passed": true}`.

### Exception path (pure-CTI classes only)

```markdown
```machine_check
{"machine_check": "none", "reason": "pure CTI correlation — no artifact bytes",
 "claim_kind": "cti_correlation"}
```
```

The exception is accepted if and only if: `claim_kind` is in the map's
`exception_allowed` list **AND** matches the fact's `boundary_type` (see the
boundary_type table below). `reason` is required. Unknown boundary_type →
exception disabled (fail closed).

## Validation hooks

| Entry point | Behavior |
|---|---|
| `kunglao_verify.check_machine_check_contract(record_text, claim_kinds, mc_map)` | Record-level schema validation (ok, reason) |
| `kunglao_verify.machine_check_gate(ws, fact_id, claim_id, fact)` | Locates runs/verify-redteam-\*.md (the latest one) and runs the contract check |
| `kunglao_verify.verify()` | The L2 CONFIRMED branch is forced through the gate; failure → `overall=PARTIAL` + warning `MACHINE_CHECK_FAILED` (no STAMP promotion) |
| `kunglao_verify.machine_check_map_coverage(seen_types)` | Mapping coverage statistics (acceptance ≥80%) |
| `kunglao_verify.validate_machine_check_entry(entry)` | Per-entry structure validation (4 fields/boolean/non-empty/machine-level command) |

## Mapping table (claim kind → machine check type)

| claim kind | machine check type | exception allowed |
|---|---|---|
| static_constant | disasm_constant_check | no |
| decryption_key | decrypt_compare | no |
| input_bypass | vm_execution | no |
| numeric | byte_recalc | no |
| string | byte_offset_locate | no |
| structure | byte_parse | no |
| negative_result | bounded_search | no |
| capability | vm_execution | no |
| cti_correlation | none | yes |
| attribution | none | yes |
| external_source | none | yes |

- **static_constant** → `disasm_constant_check` (byte-level comparison of the VA constant)
- **decryption_key** → actual decryption comparison (key derivation + ciphertext → plaintext bytes)
- **input_bypass** → VM execution (192.168.20.128 channel; sample execution on the host is forbidden)
- **numeric** → raw-byte recomputation (reverse numeric-fidelity check)
- **string** → raw-byte offset location (xxd/grep locate + offset assertion)
- **structure** → byte-level structure parsing (pefile/capstone field comparison)
- **negative_result** → bounded search (re-run the bounded search; 0-hit only proves boundedness)
- **capability** → VM execution or byte-level call-chain resolution
- **cti_correlation / attribution / external_source** → pure CTI/external-source classes; the
  `machine_check: none` exception is allowed; but when a sourced artifact
  (report JSON/sample) exists, a source-byte recheck should still be done

## boundary_type → claim kinds (exception eligibility)

| boundary_type | eligible claim kinds |
|---|---|
| confirmed | static_constant, decryption_key, input_bypass, numeric, string, structure, capability |
| capability_not_executed | capability, input_bypass |
| link_not_closed | capability, static_constant |
| source_derived | cti_correlation, external_source |
| numeric | numeric |
| observation | static_constant, decryption_key, input_bypass, numeric, string, structure, negative_result, capability |
| coordinate | numeric, string |
| pure_negative | negative_result |
| contradiction | numeric, string |
| positive_observation | static_constant, decryption_key, input_bypass, numeric, string, structure, negative_result, capability |

(Consistent with `machine_check_map.yaml::boundary_type_map`; covers all 9
schema classes plus the workspace-legacy `positive_observation`.)
