# ADR-002: Artifact Graduation Gate (design spec — machinery is v0.2)

- Status: Accepted (design-only slice of issue #137, v0.1.6; the gate
  MACHINERY itself is v0.2 scope — nothing here wires a new check into
  any loop or CI leg yet)
- Deciders: kunglao-agent owner
- Date: 2026-09-22

## Context

The v0.1.x loop produces artifacts that today live only inside one
workspace: oracle cases (+#301 admission), case-bank lessons (#49/#136
terminal-chain weighting), posteriors (#106), rank terms and their free
parameters (#251/#294), prompt fragments. Some of these are good enough
to become REPO assets — promoted into the skill's scripts, cases, or
reference data so every future workspace starts from earned experience.
Today that promotion happens by hand, with no stated bar, so the only
alternatives are "never promote" or "promote on vibes" (the counterfeit-
coin failure mode #301 closed for case minting, reopened at the repo
boundary).

Two facts constrain the design:

1. The repo already HAS a promotion organ: the release train. A change
   becomes a repo asset by landing on `dev` through a reviewed PR and
   riding the deploy/release manifests (`deploy-manifest.yaml`,
   `release-manifest.yaml`, checked by `scripts/deploy_manifest.py
   --verify` and the release receipt face). Building a second promotion
   organ would fork authority — the exact drift the no-new-organs
   doctrine (issue #137) forbids.
2. The repo already HAS the measurement instruments the bar needs: the
   case bank and settlement rows record engagements and attributions;
   the event stream (`runs/logs/kunglao-*.jsonl`) records what fired;
   the replay ruler (#294, `scripts/replay_ruler.py`) replays historical
   ledgers into deterministic TTC/order digests; the #137 format stamps
   on persisted rows make historical formats readable by field rather
   than by inference.

## Decision

Graduation is a FIVE-CRITERION GATE applied to a named artifact, whose
single enforcement point is the PR that promotes it. No new service, no
new database, no new approval workflow — the gate IS the release train.

### The five mechanical criteria

An artifact (case, hypothesis, rank term, tool wiring, prompt fragment —
see same-shape rule below) graduates when ALL five hold:

1. **Engagement — fired >= N times.** The artifact appeared in >= N real
   loop engagements (dispatch decisions / retrieval windows / rank
   feeds) across >= 1 workspace, countable from persisted rows. An
   artifact nothing ever engaged has no evidence to graduate on, however
   elegant it is.
2. **Attribution — >= K positives, zero negatives.** Of those
   engagements, >= K carry positive attribution (banked POSITIVE
   outcome, or membership in a task-terminal settlement enabling chain
   — issue #136), and ZERO carry banked negative attribution with its
   mandatory reason. One attributed counterexample vetoes; the
   failures-first doctrine (owner ruling 4) applies to promotion too.
3. **Privacy — hash-only.** The promoting PR carries hashes (sample
   sha256, target fingerprint) and synthetic fixtures only — never
   sample content, never workspace state files, never secrets (the
   standing repo rule: bins/settings/hooks are never committed).
   Verifiable mechanically by the same review a PR already gets.
4. **Replay non-regression — #294.** Replaying the historical ledgers
   of the workspaces that engaged the artifact, WITH vs WITHOUT the
   artifact active, must not regress the replay ruler's deterministic
   TTC/order digests. The stamps from issue #137 are what make those
   historical ledgers readable at replay time.
5. **Human review = the PR.** The promotion lands as a PR against the
   release train; reviewer approval is the human gate. There is no
   separate signoff organ to bypass, and no auto-promotion path.

N and K are named free parameters per artifact TYPE (declared in the
promoting PR description, earn-in tracked like #294's parameters) —
mechanical values, not judgment calls at gate time.

### Same shape for all artifact types

Every promotable artifact type goes through the SAME five criteria in
the SAME order with the SAME evidence classes (engagement rows,
attribution rows, hashes, replay digests, PR review). A type may declare
its own N/K and its own digest face, never its own criteria. No
per-type organs, no per-type fast lanes — a case graduates like a rank
term graduates like a tool wiring.

### Wiring (what this decision does NOT build)

- No graduation daemon, no promotion ledger, no gate service. The gate
  is the PR checklist against the five criteria; the evidence is read
  on demand from the named workspaces (the #137 pure faces:
  `compute_priors.py` for cross-workspace priors, `replay_ruler.py`
  for non-regression, the bank/settlement/event rows for engagement and
  attribution counts).
- The machinery that will one day CHECK these criteria mechanically is
  v0.2 work; when it exists it reads the same rows and enforces the
  same five criteria — this ADR is its spec, not its trigger.

## Directory convention (workspaces)

Workspace locations are a CONVENTION, not a registry:

- A workspace is any directory materialized by `/init` (the
  `kunglao_template_version:` stamp on `CLAUDE.md` /
  `claim-register.yaml` / `facts/_INDEX.md` marks one). The operator
  chooses where it lives; the skill resolves the GIVEN or confirmed cwd
  candidate (SKILL.md cold-start step 5) — there is no central
  registry of workspaces and none may be introduced.
- All persisted state is workspace-RELATIVE and rooted at the
  workspace: `.convergence_ledger.jsonl`, `runs/posteriors.yaml`,
  `runs/case-bank.jsonl`, `runs/value-weights.yaml`,
  `runs/logs/kunglao-<date>.jsonl`, `runs/oracle-status.json`,
  `oracle/cases/*.yaml`. Consumers resolve these by cwd-relative path.
- Cross-workspace consumers take EXPLICIT paths and discover nothing:
  `compute_priors.py <ws> [<ws>...]` refuses a nonexistent path loudly
  rather than scanning; the #294 replay ruler copies from a named
  read-only source into a sandbox. A tool that needs "the workspaces"
  must be HANDED them, every time.
- Repo-adjacent machine state that is NOT workspace state (skill
  package, hook wiring) lives under the skill install root and is
  versioned with the repo — it never reads or writes inside a
  workspace except through the explicit-path faces above.

## Consequences

- **Earning is possible but not automatic.** A workspace artifact can
  point at exactly the evidence a promotion PR needs: its engagement
  count, its attribution record, its replay digest. This is the
  v0.1.6→v0.2 path from "the loop learns in one workspace" to "the
  repo learns".
- **Historical formats stay readable.** The #137 stamps (this slice)
  are the load-bearing prerequisite: replay-based criterion 4 is only
  trustworthy if old rows self-describe (or are tolerably legacy) —
  inference-based format guessing would make criterion 4 a heuristic.
- **Promotion cost is a PR, nothing else.** No new infra to run, no
  new store to trust; conversely, the gate's enforcement is only as
  strong as PR review until the v0.2 machinery lands — accepted.
- **ADR precedent.** The ADR shape here follows the repo's first
  record, docs/adr-001-strategy-parameter-governance.md (#295): Title /
  Status / Context / Decision / Consequences, decision-first, organs
  named explicitly as built or NOT built. This file (docs/adr-002)
  continues that series; future architecture decisions follow the same
  shape.
