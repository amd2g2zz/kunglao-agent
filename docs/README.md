# docs/ — Design Documentation

Design and development artifacts for kunglao-agent. After the #355
pre-release hygiene pass this tree contains only material with ongoing
reference value; one-shot fix logs and session-plan residue were removed
(git history preserves them).

## Directory layout

| Directory | Contents | Audience |
|-----------|----------|----------|
| `design/` | Live design research (`loop-engineering.md`) | Architects, implementers tracing design intent |
| `design/archive/` | HISTORICAL design docs (`design-spec.md`, `module-design.md` — pre-rename `kong-agent` era) | Design archaeology only; not current contracts |

Current authoritative sources:

- Runtime operative contract — `SKILL.md` (repo root)
- Release record — `CHANGELOG.md` (repo root)
- Change history — `openspec/archive/` (delivered change proposals)

## Relationship to references/

`references/` contains **runtime protocol** documents the orchestrator and
workers read during analysis sessions (contracts, failure modes,
guardrails). `docs/` contains **design and development** artifacts:

- `references/` = what the agent reads at runtime to decide what to do next
- `docs/` = how the system was designed and how development progressed
