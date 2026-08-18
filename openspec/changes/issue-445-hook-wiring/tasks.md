# Tasks — issue #445 hook wiring unification

## 1. SDD

- [x] 1.1 `openspec/changes/issue-445-hook-wiring/proposal.md` (issue #445 as requirement source)
- [x] 1.2 `design.md` — D1 canonical writer, D2 alias degradation + caller migration, D3 kicker relation, D4 init self-check FAIL, D5 layer self-check, D6 static enforcement, D7 rejected alternatives
- [x] 1.3 `tasks.md` (this file)

## 2. RED (tests/test_hook_registration_entry.py — all three acceptance criteria)

- [x] 2.1 AC1 single entry: canonical declaration exists; wire_up_settings() is a
      DeprecationWarning alias delegating to register_hooks; AST scan — only
      hook_activation constructs `{"matcher": ...}` entries (RED: 3 more modules do)
- [x] 2.2 AC2 self-check: register_hooks self-check passes on a clean write;
      `--wire-up` CLI exits 1 with `FAIL:` on layer mismatch (RED: always 0);
      selfcheck_registration flags dropped entries + wrong layer (RED: no such function)
- [x] 2.3 AC2 init FAIL: deploy_hooks runs the self-check; mismatch →
      RC_HOOK_WIRING=7 via hook_deploy_rc (RED: no check, no rc)
- [x] 2.4 AC3 kicker relation: REGISTRATION_RELATION names the canonical entry
      (RED: absent); kicker entries byte-equal build_hook_entry output
      (RED: hand-rolled); init _ensure uses the canonical builder (RED: hand-rolled)
- [x] 2.5 RED commit — new file fails with every listed assertion red

## 3. GREEN

- [x] 3.1 hook_activation: move writer verbatim into register_hooks; add
      build_hook_entry / selfcheck_registration / declarations / error class;
      main --wire-up → FAIL + exit 1 on self-check mismatch
- [x] 3.2 wire_up_settings: writer code removed; deprecated alias delegating;
      registry untouched
- [x] 3.3 external_kicker: REGISTRATION_RELATION; _canonical → build_hook_entry
- [x] 3.4 kunglao-init: _ensure → build_hook_entry; deploy_hooks self-check;
      RC_HOOK_WIRING = 7 + hook_deploy_rc; initialize maps mismatch to FAIL
- [x] 3.5 quick gate `-m "not load_sensitive"`: zero NEW failures vs baseline
      (baseline on dev: 16 pre-existing failures, unrelated domains)

## 4. REFACTOR + docs

- [x] 4.1 stale path descriptions re-pointed: hooks/env_check_gate.py,
      hooks/recall_inject.py, hooks/state_anchor.py, references/cold-start-contract.md,
      skills/kunglao-agent/SKILL.md, scripts/README.md
- [x] 4.2 re-run quick gate after refactor
- [x] 4.3 `.review/RUNBOOK.md` (change list / test map / risks / migration notes)
