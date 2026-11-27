# Design

## Context

The seal's contract (additive `seal` key, fail-closed learner filter,
warn-and-ride unarmed posture, fixed key path with no env override) is
frozen by the seal card and its pin suite; this change adds the arming
program AROUND it and must not perturb it. Three constraints shaped
the design:

1. The key is HOST-LOCAL state at a fixed path outside the workspace —
   the same posture as the stop-sanction and review-gate keys. A
   declared path that is not the fixed path can therefore never arm
   the live channel, and the face must say so honestly (a split
   resolution — signing under one key, checking under another — is the
   exact failure the no-env-override posture exists to prevent).
2. The rollout ledger core must never seal on its own (the seal wall:
   producers seal at write, consumers filter at read). But the host
   emits its rows THROUGH the ledger's write faces, where the row dict
   is constructed inside the ledger — the producer cannot touch the
   row between construction and append.
3. The startup warn's once-marker is workspace-state-keyed; an armed
   period that later loses its key must not ride a stale silence.

## Goals / Non-Goals

Goals:
- One provisioning face, idempotent, non-destructive, key-silent in
  every observable output (status dict, stdout, logs).
- The step-credit host's emitted rows (identity + settlement
  amendment) sealed before the ledger write when armed; unarmed rows
  byte-identical legacy plus the ONE notice.
- A startup face that tells the operator the truth in both postures:
  armed -> one INFO line with the sealed-row count; unarmed -> the
  legacy warn, unchanged.
- Disarm is loud: a lost key after an armed period re-warns (fresh
  process AND mid-process), never rides the old silence.

Non-Goals:
- No sealing of OTHER settlement-family producers (the blind wire's
  task-kind rows are a separate slice's surface; nothing reads them
  through the learner filter today).
- No env override for the key path (the fixed-path posture stands).
- No changes to sign/verify/record_sha (the frozen-bytes contract).
- No SKILL.md changes (the seal is operator state, not an agent
  contract).

## Decisions

### D1 — producer-injected signer on the ledger write faces
`rl.record` / `rl.settle` gain `sign=None`: a row->row callable applied
to the exact dict handed to the consolidated append, AFTER the schema
lint (the lint is additive-key tolerant; the seal is an additive key).
Default None keeps every existing producer byte-identical. The host
passes the channel's signer unconditionally — `sign_row` IS the
posture: armed it seals; unarmed it returns the row unchanged and
fires the one notice. This keeps the seal wall (the core imports no
seal module, decides nothing about sealing) while letting the producer
seal before the write. The settlement dedupe compares the settlement
block only, so a sealed amendment dedupes against its unsealed
predecessor (no ledger churn on arming).

### D2 — idempotent, never-destructive keygen
`provision()` mirrors the review-gate key-init (secrets.token_bytes(32).hex(),
mode applied AT CREATION via `os.open(..., 0o600)` — no crash window
ever leaves a wider key on disk — and parent dirs created). An existing
sufficient key returns `created: False` with the untouched bytes and
gets its MODE HARDENED to 0600 when a wider file is found (a failed
hardening reports `armed: false` with the loud note — the status never
claims an armed channel whose key mode could not be guaranteed); a
short/broken key file is refused with the by-hand removal path
(auto-overwrite would silently rotate the key and orphan every seal
minted under it). A declared path writes there and reports the LIVE
channel's posture honestly: only a declared path that IS the module's
key path arms. A declared path inside a git work tree is called out in
the note (the fixed key path lives outside the repo; an in-repo key
must never enter history).

### D3 — the startup face is state-transition-keyed
Armed: the first seal operation fires one INFO milestone
(`ARMED (<n> sealed rows)`, count read from the workspace's
experience + settlement families, honest zero on any failure) and
clears the once-marker's entry. Unarmed: the legacy warn. A posture
memo observes armed/unarmed at every sign/filter entry and re-opens
both faces on a flip — so a mid-process key removal warns again, and
a fresh process after a disarm warns because the armed period cleared
the marker (a state the marker never recorded). The marker reset
resolves its workspace the way the diagnostics layer's LEDGER face
already does (explicit workspace > pinned registration > cwd walk-up):
an UNPINNED armed process must still clear a stale key a
previously-pinned process persisted — the mixed-pin sequence is
exactly the silent-disarm hole this closes. The count face
resolves the workspace through the same resolution instead of
re-deriving its own.

### D4 — CLI rc contract
`kunglao seal provision` exits 0 only when the LIVE channel is armed;
a declared-path provisioning (or a short-key refusal, or a write
failure) exits 1 with the note naming the repair. The operator face
prints the path + a short sha256 id; the key material never appears in
any output.

## Risks / Trade-offs

- [Armed host, unsealed settlement-family producers — FULL INVENTORY]
  the seal wall's read faces only bite when a learner reads a family
  through the filter; no production reader filters the settlement
  family through `trusted_rows` today (the learner filter is
  prefix-scoped to the q-cell observation rows). Producer inventory,
  sealed-or-deferred:
  - SEALED by this change (the scalar module's three settlement
    writers): `settle_round_credit` (identity + amendment),
    `settle_workspace_scalars` (tier-scalar amendments),
    `apply_trajectory_settlement` (trajectory/v3, the blind-settler
    score path).
  - DEFERRED, same class, documented: `rlvr/reward.py` (the task /
    self_distill identity-row record faces and the band-amendment
    settle) and `scripts/verification_ladder.py` (the
    mainline_decision record + settle faces). The first
    settlement-family read face behind the seal wall MUST wire these
    producers in the same change (fail-closed reads starve on their
    unsealed rows otherwise) — that read face is a separate slice's
    surface.
- [One extra ledger read per process] the armed face's count reads two
  family files once per process (gated). Mitigation: best-effort,
  honest-zero on ANY family-read failure (a partial count is neither
  the zero nor the total), never on the hot write path more than once.
- [Marker write on arming] the armed face clears the once-marker — a
  workspace write from a status face. Mitigation: fail-open, one small
  JSON file, the same write the warn face already performs; a strictly
  read-only caller takes that one small write on the read path (the
  read faces' docstrings say so — the stores themselves stay
  untouched).

## Migration Plan

None needed: unarmed behavior is byte-identical (the signer is a no-op
unarmed); arming is operator action (`kunglao seal provision`), not a
migration.

## Open Questions

None — the slice spec fixed the scope (host wiring + provisioning +
startup face; no SKILL.md changes).
