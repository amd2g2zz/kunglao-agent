---
name: unpacking-entropy
description: Packer identification (aplib, upx, themida classes) by section entropy and
  the staged unpacking ladder — carve, dump, rebuild imports.
domain: patterns
family: catalog
---
# Unpacking + entropy ladders

Identify the packing layer from entropy signatures: aplib-packed sections
show mid-range entropy with occasional literal runs; upx shows the classic
double-section signature; themida/vmprotect push whole-section entropy
toward 7.9+.

## Ladder

1. Entropy map over all sections (which are packed, which are stubs).
2. Carve the packed payload; run to OEP under a tracer.
3. Dump + rebuild imports; verify the rebuilt image re-runs headless.
