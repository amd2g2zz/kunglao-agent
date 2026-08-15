# Design — code-owned completion gate (#55)

## Design Decisions

### D1. Layering: declaration-time GATE, complementary to #43 (runtime), #44 (per-turn), #54 (detector)

#55 operates at a distinct layer from the three existing termination defenses:

| Layer | Issue | When it runs | What it reads | Action |
|---|---|---|---|---|
| Runtime drift | #43 | per loop iteration | `.convergence_ledger.jsonl` signature rotation | report SPINNING |
| Per-turn re-anchor | #44 | on Agent-tool completion (hook) | ledger + claim-register + facts + workers | inject context |
| Declaration detector | #54 | on the closing utterance (offline / hook-input) | declaration TEXT + task_text | report fingerprints |
| Completion GATE (THIS) | #55 | at session termination (Stop hook) | task-oracle.yaml + open_items ledger | **BLOCK termination** |

#43/#44 read MECHANICAL STATE and never block. #54 reads the declaration TEXT
and reports fingerprints but explicitly does NOT block (its design.md R2 scopes
the Stop hook to #55). #55 is the missing layer: it reads the user's
PRE-REGISTERED goal (the oracle) + the open-items ledger and BLOCKS the session
from ending until the oracle is satisfied. This is why #55 MUST own the exit
decision: the detector (#54) can only flag; the gate (#55) refuses.

### D2. task-oracle.yaml schema (a sibling artifact, NOT a replacement)

The oracle sits beside `claim-register.yaml` (the RE claim state machine) and
`task_spec.yaml` (the orchestrator's question space). It is the META-WORK
anchor — what the USER asked of THIS run, verbatim. Schema (YAML, parsed with
`yaml.safe_load`):

```yaml
task_text: "重检测当前分析是否存在矛盾、遗漏和gap。如果存在就需要继续全面分析"
acceptance:                          # falsifiable 'done' criteria (documentary)
  - "every gap G1-G6 has a closed fact or an explicit user defer"
  - "no item re-tiered to a level not present in task_text"
open_items:                          # the items that must be resolved
  - id: "G4"
    desc: "SetupFromBytes persistence path @0x1402ef400 unresolved in CF-3"
    closed_by: ""                    # empty ⇒ not yet closed
    closed_at: ""
  - id: "#10"
    desc: "F039 refuted parenthetical not propagated"
    closed_by: "commit 1ed7343"      # non-empty ⇒ resolved by completion
    closed_at: "2026-08-11T12:00:00Z"
deferrals:                           # items the USER explicitly dropped
  - item: "G5"
    authorized_by: "用户"            # MUST be a user (see D3); agent ⇒ exit 2
    reason: "user said 'G5 不用查' at turn 14"
    at: "2026-08-11T12:05:00Z"
```

Resolution rule (D5 details): an `open_item` is **resolved** iff (a) its
`closed_by` is a non-empty string, OR (b) its `id` appears in `deferrals[]`
with a user-authorized `authorized_by`. Any unresolved item ⇒ exit 1.

`acceptance[]` is documentary: the gate cannot mechanically verify a
falsifiable criterion. It echoes the criteria in the PASS reason but the HARD
gate is `open_items`. An oracle with empty `acceptance` is allowed (the gate
still enforces open_items); an oracle with empty/missing `task_text` is exit 3
(D6).

### D3. user-vs-agent signature discrimination (MECHANICAL, the core anti-self-defer)

The #54 failure was the agent self-deferring (#10-#12 "deferred" with no user
decision point). The gate must reject agent-authored authorizations
mechanically — no LLM judgment. Mechanism:

A deferral is **user-authorized** iff ALL hold:
1. `authorized_by` is present and non-empty (after `strip()`).
2. `authorized_by.casefold()` is NOT in `AGENT_IDENTIFIERS`:
   `{"agent", "claude", "ai", "self", "assistant", "llm", "kong", "kunglao",
   "worker", "verifier", "orchestrator", "auto", "system", "bot", "me"}`.
3. If a `source` field is present on the defer, it equals `"user"` (exactly);
   `source: "agent"` ⇒ rejected even if `authorized_by` looks user-like.

Any defer failing this ⇒ **exit 2**. This catches the literal #54 case
(`authorized_by: "agent"` or empty) AND the subtle case (an agent filling
`authorized_by: "claude"`). The affirmative `source: user` is an optional
belt-and-suspenders marker; the primary check is the deny-list, which is the
stronger direction (the agent cannot talk its way past a deny-list by picking a
new user-like name that happens to not be listed — ANY non-agent identifier
passes, because the gate's job is to refuse AGENT self-signing, not to
enumerate every possible user).

Accepted user identifiers include `"用户"`, `"user"`, `"hr"`, a person's name,
a commit SHA — anything not in the agent deny-list. The regression (acceptance
2) has ZERO defers, so exit 2 does not fire there. Acceptance 4 uses
`authorized_by: "用户"` ⇒ user-authorized ⇒ PASS; the same defer with
`authorized_by: "agent"` ⇒ exit 2.

Why not an allowlist of user identifiers (option c)? An allowlist requires
pre-registering every user handle and breaks the moment a new collaborator
appears; it also can't distinguish "hr the user" from "hr the agent
impersonating". The deny-list is the robust direction: the threat model is
specifically the AGENT self-signing, so we deny agent identifiers and accept
everything else.

Why not a signed token (option b) or a conversation-turn reference (option d)?
Both add machinery (token minting, transcript parsing) for a problem the
deny-list solves with a 14-entry set. A turn reference would require the gate
to parse the transcript and identify authorship — re-introducing LLM/semantic
judgment the issue explicitly forbids. The deny-list is the simplest mechanical
mechanism that rejects the documented failure.

### D4. #54 integration: OPTIONAL reason-enhancement, NOT a separate exit code

The gate MAY run `scripts/premature_termination_detect.py::detect()` on the
closing declaration and fold its fired fingerprints into the exit-1/exit-2
reason. This is the documented consumption path (#54 design.md R2: "#55 will
consume this detector's JSON report").

Decision: **integrate as a reason-enhancement, optional, not a separate exit
code.** Concretely: `judge(oracle, declaration_text=None)` — when
`declaration_text` is supplied AND the gate has already resolved to exit 1 or
2, it runs `detect(declaration_text, task_text)` and appends
`[declaration fingerprints: F1, F2, ...]` to the reason. The detector's
findings NEVER change the exit code (the oracle is the ground truth; the
detector is corroborating color). When `declaration_text` is None (the common
case — the Stop hook does not always have the declaration text), the detector
is not run and the reason is oracle-only.

Why optional / not a separate exit code? (a) The oracle is the deterministic
ground truth — a clean declaration must not override an unsatisfied oracle, and
a flagged declaration must not invent a new exit path the oracle doesn't
support. (b) The Stop hook does not reliably have the declaration text in its
stdin payload (Stop hooks receive `session_id` / `transcript_path` / `cwd`, not
the agent's final utterance as a string); making it mandatory would couple the
gate to transcript-file parsing. (c) #54's design.md already scopes the
detector as "report-only"; folding its output into the reason is exactly that
contract.

### D5. Precedence: exit 3 > exit 2 > exit 1 > exit 0

The gate checks in this order; the first hit wins:

1. **exit 3** — oracle is None, OR `task_text` missing/empty. Refuse to run:
   no anchor ⇒ no valid completion judgment. This is the structural fix for
   #54's F1 self-anchoring (the agent cannot produce its own anchor).
2. **exit 2** — a deferral record is not user-authorized (D3). The agent
   self-deferred. Reported BEFORE exit 1 because it is the more diagnostic
   #54 signal (the smoking gun), even if other items also remain open.
3. **exit 1** — one or more `open_items` unresolved (not closed, not
   user-deferred). The reason lists every unresolved item id + desc.
4. **exit 0** — task_text present, zero unresolved items, zero unsigned defers.

The regression (acceptance 2) has 6 open_items, zero defers ⇒ exit 3 passes
(task_text present), exit 2 passes (no defers), exit 1 fires (6 unresolved).
Correct.

### D6. task_text verbatim enforcement (exit 3, the anti-self-anchor)

`task_text` is the anchor. The gate refuses to run without it (exit 3). This is
mechanical: `task_text` must be a non-empty string after `strip()`. Empty
string, whitespace-only, missing key, or None oracle ⇒ exit 3. The agent
cannot substitute its own summary (the #54 F1 failure) because the gate will
not judge against a summary — only against a non-empty anchor.

The companion property (not enforced by code, enforced by workflow): the
orchestrator registers the oracle at TASK START (Phase 0), copying the user's
instruction verbatim. A task_text edited at close-time to match what the agent
actually did is a process violation the gate cannot detect mechanically (it
would need the original instruction); the mitigation is the workflow convention
+ the option to supply `declaration_text` so #54's F1 (declaration quotes the
agent's summary, not the task_text anchors) fires as a reason fingerprint.

### D7. "全面/comprehensive" extended check (zero-tolerance + reason clause)

When `task_text` contains a comprehensiveness keyword, the gate applies a
strictly-zero-tolerance open_items policy AND surfaces the mandate in the
reason. Keyword set (case-insensitive ascii): `["全面", "comprehensive",
"all", "every", "所有", "逐项", "exhaustive"]`.

Concretely, when the keyword is present AND exit 1 fires, the reason prepends:
`[全面/comprehensive mandate — zero-tolerance: task demands exhaustive
coverage; no item may be re-tiered or deferred without user sign-off]` before
the unclosed-items list. The 2026-08-11 task_text contains "全面分析" ⇒ the
regression reason carries this clause.

Mechanical parity: the base resolution rule is ALREADY zero-tolerance (any
unresolved item ⇒ exit 1; there is no "minor item" exception at baseline, by
design — such an exception would be LLM discretion, which is what #55
eliminates). The keyword's distinct effects are: (a) the reason surfaces the
comprehensiveness mandate so a human reviewing the block sees that exhaustive
coverage was demanded; (b) the gate additionally rejects agent-authored
DEFER_REASONS that contain self-invented tier language (the #54 F2 fingerprint
applied to defer records) — a defer whose `reason` matches a tier keyword
(`备注级|记录即可|deferred|low-priority|nice-to-have|out-of-scope`) is treated
as self-invented and pushed to exit 2 even if `authorized_by` looks user-like.
This gives the comprehensiveness check real teeth for the exact #54 pattern
(G4-G6 re-tiered to "备注级").

Note: a genuine user defer ("G5 不用查" — acceptance 4) contains NO tier keyword
and passes. The anti-re-tiering rule fires ONLY on self-invented tier language
in the defer reason, which a user instruction does not contain.

### D8. Activation gating + FAIL_OPEN (mirror state_anchor #44)

The Stop hook must not block non-kunglao sessions or trap the agent in an
infinite stop-block loop. Activation matrix:

| kunglao activated | oracle file exists | task_text non-empty | gate action |
|---|---|---|---|
| no | — | — | pass-through (exit 0) — not a kunglao session |
| yes | no | — | pass-through (exit 0) — gate is opt-in via oracle presence (D9) |
| yes | yes | no | **exit 3** — malformed oracle, refuse self-anchor |
| yes | yes | yes | **enforce** (exit 0/1/2 per D5) |

`stop_hook_active` (Claude Code sets this true on the SECOND stop attempt after
a block): when true ⇒ pass-through (exit 0). This prevents the gate from
trapping the agent in an infinite block loop — after one block the agent gets a
second stop attempt to, e.g., register a proper oracle or fix the items;
blocking forever would deadlock the session.

Activation is STRICT (mirror `hook_activation.is_active_strict`): default-
inactive. `.hook_state.json` must exist, `completion_gate` must be in
`active_hooks`, and the activation must not be expired. No activation file ⇒
pass-through (the hook sleeps, like state_anchor / worker_pulse).

FAIL_OPEN: any exception in the shim (unparseable stdin, missing oracle read
error, judge exception) ⇒ pass-through (exit 0, empty stdout). A completion-
gate failure must never deadlock the session. The pure `judge()` function does
NOT fail open (it returns exit 3 on bad input) — only the shim does.

### D9. Activated + no-oracle ⇒ pass-through (the scope decision)

The issue's design point 5 raises the tension: should "activated + no oracle"
block (exit 3) or pass (exit 0)? The issue author's suggested resolution is
"the gate only activates when ACTIVATED AND an oracle file exists" — i.e.
oracle presence is part of the activation condition.

Decision: **activated + no oracle file ⇒ pass-through (exit 0).** Rationale:
(a) it matches the issue author's stated resolution; (b) kunglao-agent has
many sub-turns (dispatch, monitor, verify) where a Stop fires but no task is
being closed — blocking those would deadlock the orchestrator between
dispatches; (c) the workflow convention (register the oracle at Phase 0) is
enforced socially/by the orchestrator's Phase 0, not by blocking every
oracle-less stop; (d) the exit-3 "refuse self-anchor" semantics still apply
fully when an oracle IS present but malformed (empty task_text) — that is the
genuine self-anchor fingerprint.

The tradeoff: an agent could skip registering the oracle and terminate freely.
This is accepted: the gate is a safety net for tasks that DID register an
oracle (the intended workflow for any non-trivial task), not a mandate that
every kunglao turn register one. The #54 detector (D4) catches the
declaration-text fingerprints even without an oracle when a declaration is
supplied.

### D10. Hook placement: scripts/ gate logic + hooks/ Stop shim

Repo convention (verified): PostToolUse/PreToolUse hooks live in `hooks/`
(worker_pulse, state_anchor, dispatch_gate, heartbeat_touch, worker_budget);
heavier gate logic + CLI live in `scripts/` (convergence_check,
premature_termination_detect, priority). #55 follows the same split:

- `scripts/completion_gate.py` — `judge()` pure function + `main()` CLI. Lives
  in scripts/ alongside premature_termination_detect.py (its closest analog:
  pure function + CLI, no workspace state). Unit-tested directly via
  `tests/test_completion_gate.py`.
- `hooks/completion_gate.py` — thin Stop-hook shim (resolve workspace,
  activation gate, find oracle, call judge, emit block decision). Lives in
  hooks/ alongside state_anchor.py (its closest hook analog: stdin payload →
  activate → call logic → emit). Mirrors state_anchor's `_resolve_workspace` +
  `_kunglao_active` + FAIL_OPEN structure.

`wire_up_settings.py` registers `hooks/completion_gate.py` under a new `Stop`
section (the existing `_ensure` handles PreToolUse/PostToolUse with matchers;
Stop hooks have no matcher, so a `_ensure_stop` variant dedupes by command
basename).

## Rejected alternatives

### R1 (rejected): put all logic in hooks/completion_gate.py, no scripts/ file

Rejected: the gate logic (judge + CLI) is independently useful — runnable from
CI, from a manual `python scripts/completion_gate.py <oracle>` check, and
unit-testable without stdin harnessing. Coupling it to the hook shim would
force every test and every CI run to construct a Stop payload. The
scripts/+hooks/ split matches the repo convention (convergence_check is in
scripts/, worker_pulse in hooks/) and mirrors #54's placement.

### R2 (rejected): make #54's detector a separate exit code (exit 4 = declaration fingerprints)

Rejected: (a) the oracle is the deterministic ground truth — a declaration
fingerprint must not override it; (b) exit 4 would be unreachable when the
declaration text is unavailable (the common Stop-hook case), making it a
fragile extra code; (c) #54's design.md R2 explicitly scopes the detector as
report-only and names #55 as the consumer that folds it into the reason. D4's
reason-enhancement is the documented contract.

### R3 (rejected): allowlist of user identifiers instead of a deny-list (D3)

Rejected: see D3. An allowlist is brittle (new collaborator ⇒ can't defer),
can't distinguish user-from-agent-impersonating, and solves the wrong problem.
The threat model is the AGENT self-signing; deny agent identifiers, accept the
rest.

### R4 (rejected): block on activated + no oracle (the strict alternative to D9)

Rejected: see D9. It would deadlock the orchestrator between dispatches (every
sub-turn Stop would block), contradict the issue author's stated resolution,
and add no real safety (the workflow registers the oracle at Phase 0 for any
non-trivial task). Pass-through + exit-3-on-malformed-oracle covers the genuine
self-anchor risk without the deadlock.

### R5 (rejected): verify acceptance[] criteria semantically (LLM judgment)

Rejected: the entire point of #55 is to remove LLM discretion from the
completion judgment. Mechanically verifying "every gap has a closed fact"
requires reading the fact base and reasoning about whether each criterion is
met — that is the LLM discretion the gate exists to eliminate. The gate treats
open_items as the mechanical proxy (each closed or user-deferred) and echoes
acceptance as documentary. A future change could add mechanical acceptance
checks (e.g. "fact F-NNN exists for gap G-N") but that is out of scope here.
