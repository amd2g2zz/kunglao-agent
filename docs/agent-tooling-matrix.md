# Agent Tooling & Capability Matrix (spec, #790 follow-up)

Diagnosis this encodes: allows ranged 4-16 and denials 2-8 across nine defs
with no governing principle; `model` / `maxTurns` / `memory` were absent
everywhere. This file IS the authority the frontmatter must mirror.

## Tool families

| Family | Members |
|---|---|
| CORE_READ | Read, Glob, Grep |
| CORE_WRITE | Write, Edit |
| EXEC | Bash |
| WEB | WebFetch, WebSearch |
| BROWSER | mcp__camoufox-reverse__* |
| JS_INDEX | mcp__gitnexus__* |
| STATIC_BIN | mcp__ghidra__* |
| DBG_WIN | mcp__x64dbg__* (incl. session start/connect/terminate) |
| DYNCHECK | mcp__frida__* (incl. spawn/attach) |
| MEM_FORENSIC | mcp__volatility__* |
| DOC_LIB | mcp__context7__resolve-library-id, query-docs |
| THINK | mcp__sequential-thinking__sequentialthinking |
| MGMT | Skill |

## Global rules (every agent)

1. NEVER grant: NotebookEdit; any Task/spawn tool (agents never nest).
2. Skill is default-OFF; granted ONLY to kunglao-worker and kunglao-redteam
   (verification methodology access), each stating the reason inline.
3. The DENY list must EXPLICITLY name every withheld dangerous family
   (STATIC_BIN / DBG_WIN / DYNCHECK / MEM_FORENSIC / BROWSER / JS_INDEX as
   applicable) even though an allowlist already implies absence --
   belt-and-braces against accidental union merges (#790 ruling).
4. Platform-gated fields (model / maxTurns / memory) MAY be added per role;
   unknown-field safety comes from the host.

## Role matrix

| Role | Granted families/tools | Explicitly denied (dangerous set) | Rationale |
|---|---|---|---|
| kunglao-worker | CORE_READ+CORE_WRITE, EXEC, WEB, DOC_LIB, THINK, STATIC_BIN, DBG_WIN, DYNCHECK, MEM_FORENSIC, JS_INDEX (+Skill exception) | NotebookEdit only outside analysis set | generalist escalation surface; T2 dynamic usage bound to VM-channel contract |
| kunglao-redteam | CORE_READ, EXEC, WEB, DOC_LIB, THINK, STATIC_BIN, DBG_WIN, DYNCHECK, MEM_FORENSIC, Skill; writes limited to verify-record surfaces | NotebookEdit (+nothing in the dangerous set: dynamic verification allowed per ruling) | checker dynamic verification enabled with mandatory WHEN-section: Windows-only targets for x64dbg; frida is cross-platform default; escalate only after static + file-level machine checks fail to settle a DIFF; terminate lifecycle on finish; MACHINE-CHECK fence still applies to every finding |
| verdict-scorer | CORE_READ, THINK | EXEC + ALL mcp families + NotebookEdit | pure read-side judgment over existing artifacts; scoring runs in-process |
| floss-filter | CORE_READ, CORE_WRITE (filtered.json artifact) | EXEC, WEB, all mcp families, NotebookEdit | consumes orchestrator-provided evidence/floss-raw.txt; zero execution |
| pefile-signature | CORE_READ, CORE_WRITE (signature/packer json), EXEC (python pefile invocations) | WEB, other mcp families, NotebookEdit | bounded local binary parsing |
| go-symbols | CORE_READ, CORE_WRITE (unstrip outputs), EXEC (unstrip CLI chain) | WEB, other mcp families, NotebookEdit | local symbol-recovery pipeline |
| ghidra-light | CORE_READ, CORE_WRITE (evidence/static-ghidra.json), EXEC (headless fallback), STATIC_BIN, THINK | DYNCHECK, DBG_WIN, MEM_FORENSIC, WEB, NotebookEdit | static-only recon specialist |
| web-re-worker | CORE_READ, CORE_WRITE, EXEC (node/browser CLIs), WEB, BROWSER, JS_INDEX, THINK, DOC_LIB | STATIC_BIN, DBG_WIN, DYNCHECK, MEM_FORENSIC, Skill, NotebookEdit | web-domain isolation; binary tools are foreign |
| kunglao-init-worker | CORE_READ, CORE_WRITE, EXEC, DOC_LIB, THINK | every ANALYSIS family (STATIC_BIN/DBG_WIN/DYNCHECK/MEM_FORENSIC/BROWSER/JS_INDEX), WEB, Skill, NotebookEdit | scaffolding/configuring role; no sample knowledge work |

## Frontmatter additions beyond tools

- `model`: scorer / redteam suggest the strongest reasoning tier; mechanical
  extractors suggest the light tier. Field presence is host-gated.
- `maxTurns`: only gate-like short roles should cap; makers stay uncapped
  ("no time budget" rule untouched).
- Plan-to-execute + Status reporting panels and an Anti-patterns block are
  REQUIRED sections checked by tests/test_agents_hygiene.py.

## Migration

One sweep commit applies this matrix to all nine defs after the hygiene lane
lands; tests/test_agents_hygiene.py then pins the matrix itself (per-role
expected allow-set strings plus global rule-1 denies everywhere).
