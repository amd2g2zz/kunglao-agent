# Design: Remove CTI agents (B4-1)

## Deletions (tracked files — use `git rm`)

| File | Reason |
|------|--------|
| `agents/cti-correlator.md` | CTI aggregator, not RE |
| `agents/shodan-host.md` | Shodan scraper, not RE |

## Reference cleanups

### `references/guardrails.md` (~L330-332)
- Remove `cti-correlator` and `shodan-host` from the stage-agent enumeration in section 6e
- Before: `floss-filter/cti-correlator/shodan-host/verdict-scorer`
- After: `floss-filter/verdict-scorer`

### `references/convergence-loop.md` (~L48)
- Remove the CTI correlation routing line: `- CTI correlation → cti-correlator`

### `references/operational-mechanics.md` (~L130-131)
- Remove `cti-correlator` from the specialist bootstrap-tolerance list
- Before: `verdict-scorer, ghidra-light, floss-filter, pefile-signature, go-symbols, cti-correlator`
- After: `verdict-scorer, ghidra-light, floss-filter, pefile-signature, go-symbols`
- Do NOT touch the historical incident narrative at L117-122

### `release-manifest.yaml` (L26, L28)
- Remove `- agents/cti-correlator.md` and `- agents/shodan-host.md` entries

### `agents/kunglao-worker.md` (L3, description field)
- Remove `cti-correlator` and `shodan-host` from the stage-specific agent enumeration
- Before: `(ghidra-light / go-symbols / pefile-signature / floss-filter / cti-correlator / shodan-host / verdict-scorer)`
- After: `(ghidra-light / go-symbols / pefile-signature / floss-filter / verdict-scorer)`

### `agents/verdict-scorer.md` (L36)
- Remove reference to `cti-correlator` in evidence input list
- Before: `- evidence/cti-correlated.json — cti-correlator output (deep/hunt)`
- Remove this line entirely (cti-correlated.json will no longer be produced)

## Test updates

### `tests/test_release_receipt.py` (L29)
- Remove `"cti-correlator.md"` and `"shodan-host.md"` from `MANIFEST_AGENTS` set

### `tests/test_global_rule_subset.py` (L265-266)
- Remove `cti-correlator` from the synthetic global-rule fixture text

### New test: `tests/test_no_cti_agents.py`
- Assert `agents/cti-correlator.md` does not exist
- Assert `agents/shodan-host.md` does not exist
- Assert no string `cti-correlator` or `shodan-host` in `agents/`, `references/`, `release-manifest.yaml` (excluding openspec/changes/)

## Out of scope (NOT changed)

- `SKILL.md`, `DESIGN.md`, `README.md`, `docs/`, `rules/`
- `agents/go-symbols.md` (grep confirms no literal `cti-correlator` or `shodan-host` string — only `cti-correlated.json` filename, which is a distinct token)
- `references/re-library/malware-analysis*.md`
- Frozen openspec history
