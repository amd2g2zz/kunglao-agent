---
name: release-checklist
about: Version release gate (maintainer use)
labels: release
---
- [ ] CHANGELOG section finalized (waves folded)
- [ ] six version sources aligned; `release_receipt.py --check` rc=0
- [ ] milestone open issues == {this checklist}
- [ ] USER GATE: tag approved
- [ ] USER GATE: dev -> master merge approved
- [ ] USER GATE: GitHub Release published
