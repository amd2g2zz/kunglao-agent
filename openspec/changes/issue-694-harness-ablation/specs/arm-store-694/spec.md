# arm-store-694 delta — issue-694-harness-ablation

## ADDED Requirements

### Requirement: The registry declares the store scope

The matrix registry SHALL accept `warm_up.store_mode` with values
`per-run` (default) and `per-arm`. Any other value SHALL refuse the
whole matrix (`ConfigError`): the two scopes materialize different
stores, and an unreadable scope must never silently degrade to one of
them.

#### Scenario: the default stays per-run

- **WHEN** a registry declares no `warm_up.store_mode`
- **THEN** every cell keeps its own isolated `<run_dir>/store` exactly
  as before

#### Scenario: a malformed scope refuses

- **WHEN** `warm_up.store_mode` is not `per-run` or `per-arm`
- **THEN** `load_config` raises `ConfigError` naming the legal values

### Requirement: Per-arm scope accumulates one store across the arm's sequence

Under `per-arm`, all cells of one arm SHALL resolve the store env to a
single shared `<arm>/store` directory; cells of different arms SHALL
never share a store. The scope SHALL bind store-bearing arms only (a
cc face never reads the store, so its cells stay per-run). The first
unit of the arm SHALL materialize the store (cold: an empty dir; warm:
one isolated copy of the configured source); every later unit SHALL
reuse it with accumulated rows intact. The accumulating store SHALL
persist across re-invocations of the matrix into the same out dir (the
launcher never wipes it) — first-unit materialization is once per out
dir, never once per invocation, so a fresh measurement uses a fresh out
dir. A warm per-arm dir that exists without its store file (a torn
first materialization) SHALL be repaired by the copy. The warm-source
refusal SHALL still fire when no usable source is configured.

#### Scenario: later units see earlier units' rows

- **WHEN** the first unit of an accumulating arm has written rows to
  the shared store
- **THEN** the next unit's materialization leaves those rows in place
  (no re-copy, no wipe)

#### Scenario: arms stay mutually isolated

- **WHEN** two arms declare `per-arm`
- **THEN** each arm's cells resolve a distinct store directory — one
  arm's writes can never reach the other's reads

#### Scenario: the warm claim stays honest

- **WHEN** an accumulating warm arm has no usable source
- **THEN** the materialization refuses with the same refusal as the
  per-run scope (the warm claim would be false)

### Requirement: Accumulating arms launch as one sequential group

The launcher SHALL schedule an accumulating arm's cells as ONE launch
group executed sequentially in declared unit order — concurrent
same-arm cells would race the shared live store. The grouping SHALL be
enforced for any plan order, not by caller discipline. Every
non-accumulating cell SHALL keep its own group and the matrix's
parallelism. The progress spine SHALL record the declared store scope.

#### Scenario: declared order is the sequence

- **WHEN** an accumulating arm spans units u1, u2, u3 (declared order)
- **THEN** the launch group runs u1, then u2, then u3 — never two of
  them concurrently

#### Scenario: an interleaved plan list still groups per arm

- **WHEN** the plans of two accumulating arms arrive interleaved
- **THEN** the schedule is exactly one sequential group per arm

#### Scenario: the receipt names the scope

- **WHEN** the dry-run or the launch writes its progress rows
- **THEN** an accumulating cell's row carries `store_mode: per-arm`
  and the store path the child would read
