REVIEWER=kunglao-worker
VERDICT=APPROVED
Maker side of maker-checker: the consolidated claim-layer rules (BLIND, derive independently, state own finding first, report every divergence as DIFF) are unchanged; the added verdict-layer section is additive and does not loosen any constraint on how my facts get attacked. doubt_checker.py removal is safe — its verifier_sign_off enforcement survives in blind_gate.py (check_proven_gate + inference gate), and hook_activation no longer registers the dead hook. Zero consumers remain in scripts/hooks/agents.
