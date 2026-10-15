# tasks — issue-687-blind-settlement

## 1. RED first (TDD)

- [x] `tests/test_blind_settlement_687.py` — collection RED confirmed
      (`ModuleNotFoundError: rlvr.settlement_scorer`) before implementation
- [x] `test_settler_inputs_exclude_method_family_log`
- [x] `test_settlement_is_idempotent_byte_identical`
- [x] `test_settler_cost_enters_cost_t`
- [x] `test_producer_narrative_never_in_settler_input`
- [x] identity gate + loud cost-without-claim refusal pins

## 2. The blind settlement entry

- [x] `scripts/rlvr/settlement_scorer.py`: `settler_input` (whitelist
      build, exclusion list, identity/claim gates, hash-only artifacts)
- [x] `check_blind_input` (schema + identity + excluded-face re-scan)
- [x] `settle_blind` → reused `validate_verdict_doc` /
      `apply_trajectory_settlement` (additive `extra_resolvable` seam)
- [x] `record_settler_cost` + cost args on `settle_blind`
      (action_type=settle transition; launch-stash billing guard)
- [x] `scripts/README.md` catalogue row

## 3. Mechanical blindness (the act face)

- [x] `hooks/rt_read_barrier.py`: `SETTLER_AGENT_MARKERS` +
      `blind_act_class` (agent_type authoritative, Face B armed sessions
      arm settler envelopes too) + actor-aware REJECT messages
- [x] shared deny face gains `runs/method-family-log.jsonl` +
      `runs/q-cell-log.jsonl` (Read, Glob/Grep pattern, Bash token)
- [x] settler-family pins in `tests/test_rt_read_barrier_652.py`
      (denials, working face open, arming envelope, family registration)

## 4. The settler agent

- [x] `agents/kunglao-settler.md`: BLIND contract, verifier identity,
      deterministic ruling, validator-is-mechanical posture, the three
      structural contract markers + plan/status panels
- [x] `release-manifest.yaml` asset + `MANIFEST_AGENTS` roster pin

## 5. Verification

- [x] focused suites green: blind settlement + read barrier + scalar
      379/390 (the additive kwarg's regression wall)
- [x] `openspec validate issue-687-blind-settlement` exit 0
- [x] agents Gate 6 lint + agents hygiene green
- [x] release receipt / declaration scan green
- [x] comment/formal hygiene baselines re-emitted after the last
      comment touch; ext-scan re-run (barrier docstring first line);
      deploy manifest re-emitted last (order: ext-scan → baselines →
      deploy-manifest → mint → commit)
- [x] `detect_changes()` before committing (affected scope check)
