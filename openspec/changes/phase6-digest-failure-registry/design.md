# Design — phase6-digest

Six sections (design-spec §3.6):
- head: schema version + anchor version (f+c+r counts) + reconcile timestamp
- sec_a: task_spec primary questions/scope/constraints/depth
- sec_b: claims index (C-NN | status | conclusion | anchor)
- sec_c: verified facts with unit field VERBATIM (numeric fidelity)
- sec_d: architectural conclusions (reasoning chain preserved, not collapsed)
- sec_e: failure rules structured (WHEN → THEN | anchor)
- sec_f: pointer table (on-demand read targets)

Mechanical, no LLM. Pure function except head timestamp. New-bar-prepend (lost-in-the-middle mitigation).
