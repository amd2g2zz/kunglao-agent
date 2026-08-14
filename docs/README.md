# docs/ -- Design Documentation

This directory is the central repository for kunglao-agent design documentation.

## Directory layout

| Directory | Contents | Audience |
|-----------|----------|----------|
| `design/` | Design specifications, module-level design, engineering research | Architects, implementers tracing design intent |
| `devlog/` | Development logs, audit records, fix investigations, plans (`devlog/baselines/`, `devlog/superpowers/`) | Maintainers, post-incident review |
| `superpowers/` | Global development plans (`superpowers/plans/`) | Maintainers, planning |

> 2026-08-14 (#319): `docs/refactor/` 已于 #263 并入 `design/`/`devlog/`;
> `archive/` 不再存在 — 本表按实际目录重列。

## Quick links

- [design/](design/) -- `design-spec.md`, `module-design.md`, `loop-engineering.md`
- [devlog/](devlog/) -- audit logs, fix records, refactor plans, baselines, superpowers plans
- [superpowers/](superpowers/) -- global dev plans (GLOBAL-DEV-PLAN-B3/B4)
- `templates-inventory.md` -- script-template classification framework (issue #278)
- Root `DESIGN.md` -- current authoritative design document

## Relationship to references/

`references/` contains **runtime protocol** documents used by the orchestrator and workers during analysis sessions (contracts, failure modes, guardrails, etc.). `docs/` contains **design and development** artifacts. The distinction:

- `references/` = what the agent reads at runtime to decide what to do next
- `docs/` = how the system was designed and how development progressed
