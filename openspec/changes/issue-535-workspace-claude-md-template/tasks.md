# Tasks

- [x] T1. Rewrite core section to ≤50 lines (37 landed) — anchor: `test_core_section_within_50_lines`, `test_core_section_does_not_embed_dynamic_state`.
- [x] T2. 9-row cold-start pointer table replacing inline state — anchor: `test_core_section_pointer_table_has_nine_rows`.
- [x] T3. `## Loop enforcement (persistent channel)` block (convergence_check + heartbeat TTL 35 min + oracle verdict + post-compact re-entry) — anchor: `test_renders_loop_enforcement_block`.
- [x] T4. 6-carrier memory contract table + Write criteria (5) + When-to-skip list — anchors: `test_six_carrier_memory_contract_present`, `test_write_criteria_and_no_write_list_present`, `test_no_blanket_write_instructions`.
- [x] T5. Pointer-resolvability test running the REAL init (not a renderer glob) — anchor: `test_cold_start_pointers_resolve_after_real_init`.
- [x] T6. `pytest tests/test_workspace_claude_md_template_535.py` — 10 passed.
- [x] T7. `ruff check tests/test_workspace_claude_md_template_535.py` — clean (templates/ and fixtures are .md, not lint targets).
- [x] T8. `python scripts/release_receipt.py --check` — exit 0.
- [x] T9. Full suite — 3226 passed / 7 skipped / 2 failed (both pre-existing, caused by sibling .worktrees; proven at pristine HEAD via git stash -u).
- [x] T10. Regenerate golden fixtures with pinned sentinels (SKILL_DIR sentinel, Python 3.11.0) — `test_renderer_unify.py` 16 passed.
- [x] T11. openspec validate strict pass.
- [ ] T12. PR against dev; never merge to master without explicit user approval.
