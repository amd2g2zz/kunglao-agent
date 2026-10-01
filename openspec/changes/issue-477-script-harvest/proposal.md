# Proposal — issue-477-script-harvest

## Why

Worker-written code is today's BEST distillation source and it evaporates
every run. Live evidence: round-5's worker hand-wrote `scripts/so_disasm.py`
(a capstone-based ELF disasm harness), produced 7 disasm dumps solving real
sub-problems — then the workspace was discarded. Research grounding
(Code2Skill arXiv:2609.05571: skills synthesized from code hit ~93.5% pass —
code is the richest skill substrate, no environment interaction needed; ASI
arXiv:2504.06821: executable skills beat text memory) says the executable
form is the strongest skill substrate. The internal-source distillation axis
(rollup lessons: prose) and the external-source axis (#458: world knowledge)
both miss it: the run's OWN code artifacts have no harvest face.

## What changes

One new capability, `script-harvest`: a POST-RUN sweep that mines the run's
own worker-written scripts into skill candidates, built as four precise
organs (three mechanisms + the cross-cutting audit-stream face), all riding
the #474 online-distillation landing spine — no second landing API:

- **Harvest sweep** — one mechanical post-run pass over `<ws>/scripts/`
  (excluding the DECLARED one-off dir `scripts/sample_specific/`) and
  `<ws>/evidence/*.py`, scoped to files written during the run (mtime at or
  after the RUN-START timestamp the host supplies — never the distill
  ledger's engine-minted `run_started_ts`, which only exists after the
  first ledger-writing event). Success-trace discriminator (mechanical,
  workspace-native signals only): a script is a CANDIDATE when (a) a
  `facts/F*.md` whose frontmatter `status` is exactly `PROVEN`/`VERIFIED`
  cites it (a provenance entry path, the `reproduce` line, or a body
  mention) — the artifact it produced fed a verified outcome; OR (b) a
  LATER worker act reused it with an outcome-bearing reference: a done-line
  `artifacts:` deliverable reference, or at least two independent later
  referencing documents (bare mentions and failure-protocol
  `what_I_tried` notes fire nothing). Everything else is a one-off:
  counted, never silent, never landed.
- **Skill candidate** — executable form by nature (O1 preference already
  satisfied: the script IS code); fixture verification = staged-then-
  verified against the workspace's anchored sample with a double-run
  byte-exact stdout pin (two bounded subprocess runs of the LANDED copy
  must agree byte-exact, rc 0, non-empty; the agreed sha256 + input sha256
  are pinned in the manifest for future re-verification); landing through
  the EXISTING #474 spine: the same run-local shelf
  (`<ws>/tools-local/` + provenance manifest), the same budget-ledger
  document (`runs/distill-budget.json`) with harvest-owned counters, the
  same never-loosen clamp and fail-closed corruption rule, NO global-shelf
  write face (promotion stays the standing post-run wave).
- **Playbook co-product** — each verified candidate exports its
  script→evidence→outcome chain (the script, the evidence artifacts its
  citing facts carry, the PROVEN fact + claim it served) as one chain
  record in `<ws>/runs/harvest-playbook.json` (`harvest-playbook/1`) — a
  minimal sequence record that the future playbook capability (#478, not
  yet landed) can consume or supersede (owner-directed per the #477 card's
  product-stack comment).
- **Audit vocabulary** — `harvest_scan` / `script_harvested` /
  `harvest_landed` join the unified 17-field stream in BOTH vocabularies
  (e2e/audit.py + event_taxonomy.EMIT_ACTIONS), new category `harvest`,
  same registration pattern #457/#458 established.

Test substrate: a fixture workspace with (a) a success-traced script
(cited by a PROVEN fact) → candidate → verified → landed; (b) a one-off
(no citing document) → skipped; (c) a nondeterministic script (fails the
byte-exact double-run) → archived, not landed.

## Non-goals

- No runtime harvest: the sweep is POST-RUN only (in-run harvesting would
  classify scripts before their outcomes exist).
- No global-shelf write and no new promotion fast-path: the 泛化+自启 bar
  and the five-stage distill pipeline stay the only road to `references/`
  and `tools/`.
- No LLM act: harvesting is mechanical (scan + cite + verify + land). The
  #474 distill act budget is NOT consumed; harvest lands under its own
  counters in the same ledger.
- No fact-base mutation: harvest reads `facts/F*.md`, never writes them.
- No playbook schema invention beyond the minimal chain record: #478 owns
  the playbook schema; this record feeds it.
