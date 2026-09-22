---
claim_id: C-NNN
blocker_type: B1a  # B1a (infra unwritable) | B1b (workers all failed, writable) | B2 (user stop) | orphan (fact with no intent)
reason: ""
created: 2026-01-01  # ISO YYYY-MM-DD — fill at creation
observed: ""  # v2 #340 MANDATORY: the exact command + verbatim error bytes
attributed: ""  # v2 #340 MANDATORY: your diagnosis — name the LAYER, never a "dead" verdict
probe_evidence: ""  # v2 #340: differential probe output justifying an environment-capability attribution (e.g. `su -c id` stdout/stderr bytes). MANDATORY non-empty whenever the text says "no root / unavailable / not supported / cannot use" — error text alone is NEVER sufficient; the write gate (hooks/write_guard.py + scripts/blocker_lint.py) REJECTS the write without it
expires: 12  # v2 #340 MANDATORY: ticks this premise stays trusted without re-verification (int; default 12) or an ISO timestamp — the tick marks an unrefreshed premise stale (forced re-derivation)
---

# Blocker <id>

- **claim**: C-NNN
- **missing**: <what evidence/tool/authorization is needed>
- **classification**: B1a / B1b / B2 / orphan
- **context**: <how the orchestrator got here — for post-hoc audit>

## Resolution path
- <what would unblock: e.g. "user authorizes VM detonation" / "external CTI query allowed" / "tooling fixed">

## History (append-only)
- <ts> created — this section is append-only: add later lines below, never
  rewrite or delete earlier ones (SUSPECT / stale markers are appended here
  mechanically by premise_gate #340; a marked premise forces re-derivation
  before any consumer may rely on it again)
