# Proposal — issue-458-online-distillation

## Why

The owner ruling (2026-09-30): "我需要有在线蒸馏能力" — the agent needs
ONLINE distillation. Today knowledge acquisition is offline-only: when the
full tool shelf (the 43 one-liner index the worker reads) has no viable
candidate for the task at hand, or the format probes (DIE/apkid) cannot
classify the sample, the run degrades to worker improvisation with no
recorded discovery trail, no method capture, and nothing reusable lands.
The distill machinery that exists (references/re-library cards, the
distill-pipeline contract, the 泛化+自启 quality bar) is a batch-wave
facility — nothing triggers it at the moment of need inside a run.

Same-day rulings shape the design: rules-based selection approaches are
REJECTED (no alias tables, no applies_to mapping) — the trigger is the
LLM worker's own full-shelf semantic selection verdict, reported through
a structured marker, never a hardcoded capability lookup; distillation
restraint survives as BUDGETS, not prohibition; every mechanism
fewer-but-precise.

## What changes

One new capability, `online-distillation`, built as five precise organs:

- **Trigger face** — mechanical detection of two (and only two) honest
  miss signals: the structured `shelf-miss:` marker line a worker writes
  into its `runs/worker-status-*.md` after reading the full tool index,
  and the unknown-format probe failure (a probe evidence file whose
  classification came back empty/unknown). Shelf-miss becomes a
  first-class audit signal. Hosts: the e2e dispatch loop (per-tick scan
  after the dispatch wave) and the production round-closure hook — the
  two faces where #462's dispatch/act wirings live; the choice is
  documented in design.md D1.
- **Budget ledger** — `runs/distill-budget.json` (the mission_ledger
  counter pattern): per-run hard act budget, hard hop budget, and a
  workspace-lifetime global frequency counter. The restraint ruling
  lives here as budgets only. Caps never loosen: a stored budget larger
  than the default clamps to the default; an unreadable ledger fails
  CLOSED (distillation is the optional capability — corruption must not
  open the floodgate).
- **Distillation act** — one bounded LLM-shaped act dispatched through
  the EXISTING dispatch faces (the #459/#462 launch/land seam): local
  re-library retrieval first, then the web search face (URL + access
  date recorded; web-sourced content is never directly PROVEN);
  imperfectly-matched sources are mined for METHODS (methodology-first,
  case specifics discarded). Recursive case expansion is HARD-capped:
  depth 1, breadth 3, every hop consumes budget.
- **Sample-as-oracle** — the engine (not the act) runs every distilled
  candidate against the ACTUAL sample bytes (the engine injects the
  real sample path; manifest-supplied paths are never trusted) and
  records the outcome. No oracle run, no landing.
- **Landing tiers** — tier 1 is run-local only: `<ws>/tools-local/`,
  immediately usable in-run, manifest-carried provenance. The global
  shelf (tools/, references/re-library/) has NO runtime write face;
  promotion stays post-run through the EXISTING distill quality gate.
- **Audit vocabulary** — `distill_attempt` / `distill_result` /
  `candidate_landed` join the unified 17-field stream, in both the e2e
  stream vocabulary (e2e/audit.py) and the production emit vocabulary
  (event_taxonomy.EMIT_ACTIONS), where #457/#462 established them.

Test substrate: a constructed unknown-format fixture (a tiny synthetic
binary under a novel periodic-XOR + position-add transform — genuinely
off the 8-algorithm shelf, zero real-sample bytes) plus one committed
re-library methodology card whose method solves it. The fixture e2e
proves the full chain: miss → trigger → budgeted distill act (bounded)
→ candidate runs against bytes → outcome recorded → run-local landing.

## Non-goals

- No rules-based capability matching (owner rejection): no alias
  tables, no applies_to, no per-tool applicability maps. The worker's
  semantic verdict IS the trigger input; the engine only parses the
  marker.
- No runtime global-shelf writes and no new promotion fast-path: the
  泛化+自启 bar and the five-stage distill pipeline stay the only road
  to references/ and tools/.
- No second decision source: the distill act consumes the existing
  dispatch faces and audit stream; it does not touch the kernel
  compose/sampler organs, the priority ranker, or the method-family
  vocabulary.
- No live-LLM/network dependence in CI: the fixture e2e runs dry —
  scripted retrieval content, REAL oracle execution against real bytes.
