---
id: F007-sample-digest
type: fact
schema_rev: 2
title: "Anchored-sample digest extracted by the harvested script"
status: PROVEN
verify_status: passes
created: 2026-10-01
last_reviewed: 2026-10-01
source: static-decompile
confidence: high
claim_id: C-004
boundary_type: confirmed
promotion_gate: ""
provenance:
  - {role: sample_raw, path: bins/sample.bin, content_sha256: "8a091f8c7cf24346b19168931dbd5789fefc0dc06f07d1832140566b1830bef1", credibility: A1}
  - {role: recompute_script, path: scripts/byte_digest.py, content_sha256: "0000000000000000000000000000000000000000000000000000000000000000", credibility: A2}
  - {role: disassembled_s, path: evidence/dump.txt, content_sha256: "1111111111111111111111111111111111111111111111111111111111111111", credibility: A2}
claim: "Anchored-sample digest extracted by the harvested script"
reproduce: "python ../scripts/byte_digest.py ../bins/sample.bin"
expected: "digest=8a091f8c7cf24346b19168931dbd5789fefc0dc06f07d1832140566b1830bef1"
verified: 2026-10-01
---

Fixture fact for the script-harvest chain: the worker ran
scripts/byte_digest.py against the anchored sample and the digest line
it produced is the fact payload (success-trace discriminator input).
