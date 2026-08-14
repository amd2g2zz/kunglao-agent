# Proposal: Remove CTI agents (B4-1)

## Problem

kunglao-agent is a convergence-driven **reverse engineering** orchestrator. The intelligence phase (CTI/OSINT/attribution/IOC) is explicitly out of scope. Two current agents are pure CTI/OSINT tools, not RE:

- `cti-correlator` — CTI aggregator that reads `evidence/cti-*.json` source files and writes `evidence/cti-correlated.json`
- `shodan-host` — Shodan host-page scraper that queries `shodan.io/host/{ip}` for IP targets

These agents are vestiges of an earlier scope that included CTI correlation. They are never dispatched by the current orchestrator flow (Stages 1-5 are pure RE; Stage 6 verdict-scorer reads evidence but does not produce CTI data). Keeping them creates scope confusion and maintenance burden.

## What

1. **DELETE** `agents/cti-correlator.md` and `agents/shodan-host.md`
2. **UPDATE** all references in `references/`, `release-manifest.yaml`, and agent files that enumerate specialists or reference CTI routing
3. **UPDATE** tests that assert the presence of these agents in the manifest or agent lists

## Why

- Scope clarity: RE orchestrator should not ship CTI tools
- Acceptance criteria: zero grep hits for `cti-correlator` or `shodan-host` in `agents/`, `references/`, `release-manifest.yaml`

## Non-goals

- Do NOT touch SKILL.md, DESIGN.md, README.md, or other files outside the scoped set
- Do NOT modify `references/re-library/malware-analysis*.md` (malware analysis is RE, not CTI)
- Do NOT touch frozen openspec history in `openspec/changes/release-contract` or `openspec/changes/icd203-source-reliability`
