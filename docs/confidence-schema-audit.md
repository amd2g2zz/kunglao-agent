# Confidence Schema Audit (#124 / S2-6)

## Result: KEEP — library function with dedicated tests

`scripts/confidence_schema.py` implements ICD-203 7-tier probability ladder (PRD P4).
Has dedicated test suite (`tests/test_confidence_schema.py`). Not dead code — it's a
library utility imported by other modules when confidence validation is needed.
