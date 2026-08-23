# Mechanisms — Master Ledger (issue #446 AC #1, #566 sample retirement)

> Single source of truth for every mechanism in the kunglao-agent runtime.
> Each row is the canonical answer to "what is this, who owns it, and
> what is its lifecycle?" — future readers do NOT grep `scripts/` to find
> out.
>
> **Ledger contract** (enforced by `tests/test_mechanisms_retirement.py`):
>
> 1. Every row declares a lifecycle: **ACTIVE** (default), **DEPRECATED**
>    (soft-warning window — callers must migrate, code still runs), or
>    **RETIRED** (governance-only — code may remain for back-compat, but
>    no new usage). The lifecycle field is the only state machine; do not
>    invent ad-hoc statuses.
> 2. RETIRED rows must reference a `replacement` (no orphan retirements).
> 3. A RETIRED row's audit trail must show a prior DEPRECATED milestone
>    (lifecycle cannot skip — DEPRECATED is the soft-warning window).
> 4. New ACTIVE mechanisms must be added here as part of their landing
>    PR (companion to the doc_sync.py Gate 7 WARN front哨).

## Lifecycle vocabulary

| State | Code status | New usage | Caller migration |
|-------|-------------|-----------|------------------|
| **ACTIVE** | full implementation | allowed | n/a |
| **DEPRECATED** | full implementation + warning surface | discouraged; warning emitted | required within window |
| **RETIRED** | governance-only; code may stay for back-compat | forbidden | complete (record proof in `audit:` field) |

## Mechanisms

| Mechanism | Owner | Lifecycle | Introduced | Deprecated | Retired | Replacement | Audit |
|-----------|-------|-----------|-----------|-----------|---------|-------------|-------|
| `DISPATCH_RE` — v0 dispatch protocol regex `[T<N> tools=a,b] claim C-NN …` (#452) | hooks/lib_kunglao.py | **RETIRED** (was **DEPRECATED** since 2026-08-19 when v1 took precedence) | 2026-Q2 (pre-#452) | 2026-08-19 (v1 lands, takes precedence) | 2026-08-23 (this ledger, #566) | `parse_dispatch_json` v1 (`kunglao_dispatch` JSON envelope, `DISPATCH_PROTOCOL_VERSION = 1`) | v1 first caller: 2026-08-19 worker_budget:1297-1298; zero production v0 callers remaining post-#452; v0 retained as in-module `DISPATCH_RE` for back-compat only — future removal gated on full call-site audit (separate PR). **DEPRECATED window 2026-08-19 → 2026-08-23 (5 days)** — soft warning surface ran via `parse_dispatch`'s v1-first ordering. |

## See

- `openspec/changes/issue-446-governance-fg/mechanisms-status.md` — the
  SKILL.md MUST ↔ implementation status table (this ledger is its single
  source for mechanism lifecycle).
- `openspec/changes/issue-446-governance-fg/design.md` §D7 — the worker
  activity four-way representation ledger (sister ledger; same
  governance doctrine).
- `tests/test_mechanisms_retirement.py` — ledger contract tests (RED/GREEN
  locked here).
- `hooks/lib_kunglao.py` — `MECHANISMS` module attribute mirrors the table
  for runtime introspection (e.g., by future lint probes).

## How to add a row

1. Pick the lifecycle you are entering. **You cannot add a row already
   in RETIRED** — re-retirements extend `audit:`, not the row.
2. If lifecycle = RETIRED, the row must cite the replacement AND a
   prior DEPRECATED milestone.
3. If the new mechanism is ACTIVE, also update:
   - `references/_INDEX.md` (and re-pin `_INDEX.yaml`),
   - `skills/kunglao-agent/SKILL.md` if it is a MUST contract surface,
   - the relevant `mechanisms-status.md` row (PENDING → implemented).
4. Run `uv run pytest tests/test_mechanisms_retirement.py -q` — the
   ledger contract tests must remain green.