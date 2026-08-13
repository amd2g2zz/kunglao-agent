# docs/ -- Design Documentation

This directory is the central repository for kunglao-agent design documentation.

## Directory layout

| Directory | Contents | Audience |
|-----------|----------|----------|
| `design/` | Design specifications, module-level design, engineering research | Architects, implementers tracing design intent |
| `devlog/` | Development logs, audit records, fix investigations, plans, baselines | Maintainers, post-incident review |
| `archive/` | Superseded or obsolete documents (retained for history) | Historical reference only |

## Quick links

- [design/](design/) -- `design-spec.md`, `module-design.md`, `loop-engineering.md`
- [devlog/](devlog/) -- audit logs, fix records, refactor plans, baselines, superpowers plans
- Root `DESIGN.md` -- current authoritative design document

## Relationship to references/

`references/` contains **runtime protocol** documents used by the orchestrator and workers during analysis sessions (contracts, failure modes, guardrails, etc.). `docs/` contains **design and development** artifacts. The distinction:

- `references/` = what the agent reads at runtime to decide what to do next
- `docs/` = how the system was designed and how development progressed
