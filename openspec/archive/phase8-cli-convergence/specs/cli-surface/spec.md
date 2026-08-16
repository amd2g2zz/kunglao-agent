# Spec Delta — phase8-cli-convergence
## ADDED Requirements
### Requirement: Eight-CLI user surface
The skill exposes exactly eight user-facing CLIs, each with a single responsibility and independent argparse: kunglao.py (orchestrator entry) + kunglao-decide/verify/record/monitor/init/eval/digest. Each --help exits 0.
#### Scenario: all eight CLIs respond to --help
- WHEN each of the 8 CLIs is invoked with --help
- THEN exit code is 0 (argparse contract holds, no import/syntax errors)
#### Scenario: no legacy kong-named CLI remains
- WHEN scripts/ is scanned for kong-*.py
- THEN none remain (rename was complete); kong.py legacy pre-rename entry excepted
