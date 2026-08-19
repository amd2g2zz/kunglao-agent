# failure-lessons library (issue #41)

Global, cross-sample lesson store for the method-ladder's lessons rung
(`scripts/failure_analysis_gate.py`, #495 rung 1). This directory is
**runtime-populated**: `--lessons` aggregates closed-loop failure analyses
(`analyses/failure-*.yaml`) into dated lesson files here, in the DEPLOYED
skill copy — the repo ships only this README as the indexable face.

- **Search**: `python scripts/failure_analysis_gate.py <ws> --search
  "<keywords>"` (keyword/token overlap, no embeddings); retrieval also runs
  automatically at failure time (`similar_lessons` inside the gate).
- **Domain rule**: the library is GLOBAL (cross-sample, never
  per-workspace); each lesson carries claim_topic / outcome / next_method.
- **Registration**: this README is the catalog entry
  (`references/_INDEX.md` "failure-lessons" row) and is pinned in
  `references/_INDEX.yaml`; runtime lesson files exist only in deployed
  copies and are never pinned.
