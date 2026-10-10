# docs/ — Design Documentation

Design and development artifacts for kunglao-agent. After the #355
pre-release hygiene pass this tree contains only material with ongoing
reference value; one-shot fix logs and session-plan residue were removed
(git history preserves them).

## Directory layout

| Directory | Contents | Audience |
|-----------|----------|----------|
| `assets/` | showcase renders (SVG) referenced by the root README |
| `cases/` | Evidence-first case studies from real, converged run artifacts (EN + zh-CN) — transcripts, dead ends, named verification methods | Anyone evaluating what the agent can do |
| `design/` | Live design research (`loop-engineering.md`) | Architects, implementers tracing design intent |
| `design/archive/` | HISTORICAL design docs (`design-spec.md`, `module-design.md` — pre-rename `kong-agent` era) | Design archaeology only; not current contracts |

Current authoritative sources:

- Runtime operative contract — `skills/kunglao-agent/SKILL.md` (the root `SKILL.md` is the thin command router, #413)
- Release record — `CHANGELOG.md` (repo root)
- Change history — `openspec/archive/` (delivered change proposals)

## Relationship to references/

`references/` contains **runtime protocol** documents the orchestrator and
workers read during analysis sessions (contracts, failure modes,
guardrails). `docs/` contains **design and development** artifacts:

- `references/` = what the agent reads at runtime to decide what to do next
- `docs/` = how the system was designed and how development progressed
