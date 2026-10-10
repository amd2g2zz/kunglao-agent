#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compute_priors.py — the #420 Phase-2 adapter shim (CLI + re-exports).

The prior math lives in ``rlvr.priors`` (issue #420 Phase 2: consolidation
into the unified RLVR package, per scripts/rlvr/README.md). This module
keeps the CLI (``main``) plus the explicit re-export surface so every
existing bare-name importer keeps working unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys

from rlvr.priors import (  # noqa: F401 — the compat surface
    BASE_ALPHA,
    BASE_BETA,
    RESULT_SCHEMA,
    _case_bank_obs,
    _posteriors_obs,
    _rollout_ledger_obs,
    _scalar_ledger_obs,
    compute_priors,
)

__all__ = [
    "RESULT_SCHEMA", "BASE_ALPHA", "BASE_BETA",
    "compute_priors",
    "_case_bank_obs", "_posteriors_obs", "_rollout_ledger_obs",
    "_scalar_ledger_obs",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compute_priors.py",
        description="issue 137: aggregate cross-workspace prior over "
                    "EXPLICITLY-NAMED workspaces (pure — writes nothing)")
    parser.add_argument("workspaces", nargs="*",
                        help="workspace directories to sum (every path must "
                             "exist; none is discovered ambiently)")
    args = parser.parse_args(argv)
    try:
        result = compute_priors(args.workspaces)
    except ValueError as exc:  # loud: bad path / degraded ledger; the
        # unknown-schema version wall (PosteriorSchemaError) is a
        # ValueError subclass and dies here too.
        print(f"compute_priors: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
