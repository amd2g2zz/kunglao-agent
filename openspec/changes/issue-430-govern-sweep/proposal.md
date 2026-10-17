# issue-430-govern-sweep — silent coercion sites speak

## Why

The #430 sweep (site list verified at dev tip) found 16 state-handling
sites coercing corrupt/unreadable input to a default (0 / None / {} /
[] / False) with NO governed trace — the canonical face (issue 275
batch-3) is fail-open + ONE rate-limited kunglao_log.warn. Three of
them are the issue's named sites; the strongest is the shared
activation face (a corrupt state silently sleeps every gate).

## What Changes

1. Each silent site gains `kunglao_log.warn(op, reason)` — the return
   value is UNCHANGED (the fail-open posture stays; only the silence
   ends).
2. The cold-start split: where a MISSING file is the routine case (the
   q-cell log, the consolidated ledger, the status-first state, the
   challenge active-round) the
   FileNotFoundError branch stays SILENT and only the exists-but-
   unreadable class warns — a fresh workspace must not spam.
3. `_parse_signoff` is reclassified NOT-A-TARGET (its `{}` is plain
   no-match control flow, no except branch).
4. The eight-site "exists-but-unreadable OSError gap" family row
   (ledger/posteriors/marl/source_reliability/strategy_store/triples/
   state/feature_prior — all with documented tolerant contracts) is a
   named follow-up, not silent scope creep.
