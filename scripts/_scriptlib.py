#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_scriptlib.py — the ONE shared-primitives home for the product scripts (issue 292).

The post2 batch shipped six product scripts (~2,650 lines) of which five
imported zero shared libraries: the rate-limited fail-open WARN tracer, the
tolerant claim-register IO and the claim_deps.yaml edge write each existed
as per-script copies. This module is their single home; the guard test
(tests/test_shared_lib_guard_292.py) fails any product script that
re-defines one of these names.

Sections (one concern each, in file order):

  WARN      make_warn(tag) — the issue 275/276 fail-open tracer factory.
            Each former copy hard-coded its module name into the message;
            the factory parameterizes exactly that token and keeps the
            rate-limit state PER TAG, so every consumer's observable
            behavior (message bytes + once-per-(op, reason) suppression)
            is identical to its former private copy.
  REGISTER  tolerant claim-register.yaml IO — the fail-open read shapes
            that grew copies across plan_epistemics / target_ladder /
            claim_granularity / hypothesis_bridge. Each function ports one
            former body byte-for-byte; callers alias them under their
            former local names so call sites stay untouched.
  DEPS      ensure_dep_edge — the claim_deps.yaml DAG edge write (former
            target_ladder._ensure_dep_edge, borrowed cross-module by
            claim_granularity through a private import).

Scope discipline: only genuinely shared shapes live here. Single-consumer
helpers stay in their owners; `scripts/_boot.py` keeps its own boot-scoped
tracer (it must stay dependency-free by its import-order rule); the legacy
`warn` copies elsewhere in scripts/ and hooks/ are pre-292 rung-1 debt.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import yaml

__all__ = ["make_warn", "register_path", "claims_of", "load_register",
           "load_register_doc", "read_register_claims", "claims_from_text",
           "find_claim", "ensure_dep_edge"]


# ---------------------------------------------------------------------------
# WARN — the rate-limited fail-open tracer (issue 275 batch-3 policy)
# ---------------------------------------------------------------------------

# tag -> {op: last reason}. Per-tag state preserves the former per-module
# `_WARN_LAST` dicts exactly: two modules sharing a process never suppress
# each other's warnings.
_WARN_STATE: dict[str, dict[str, str]] = {}


def make_warn(tag: str) -> Callable[[str, str], None]:
    """Build the `[kunglao-agent] <tag> WARN (fail-open): op: reason`
    tracer with one-rate-per-(op, reason) suppression under `tag`.

    Byte-contract (pinned by tests/test_shared_primitives_292.py): the
    first (op, reason) prints once to stderr; an identical repeat is
    suppressed; a changed reason prints again."""

    def warn(op: str, reason: str) -> None:
        seen = _WARN_STATE.setdefault(tag, {})
        if seen.get(op) == reason:
            return
        seen[op] = reason
        print(f"[kunglao-agent] {tag} WARN (fail-open): "
              f"{op}: {reason}",
              file=sys.stderr)

    return warn


# ---------------------------------------------------------------------------
# REGISTER — tolerant claim-register.yaml IO
# ---------------------------------------------------------------------------

def register_path(ws: Path) -> Path:
    """The workspace's claim-register.yaml path."""
    return Path(ws) / "claim-register.yaml"


def claims_of(reg) -> list:
    """The `claims` list of a parsed register document (tolerant: a
    non-dict document or a non-list `claims` field yields [])."""
    claims = reg.get("claims") if isinstance(reg, dict) else None
    return claims if isinstance(claims, list) else []


def load_register(ws: Path) -> tuple[list, Path | None]:
    """(claims, path) of the workspace register — the target_ladder shape.

    Missing file -> ([], None); malformed YAML or a null document
    (0-byte file) -> ([], path); a readable register -> (its `claims`
    value or [], path)."""
    p = register_path(ws)
    if not p.exists():
        return [], None
    try:
        reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [], p
    return reg.get("claims") or [], p


def load_register_doc(ws: Path) -> tuple:
    """(document, path) — the whole parsed register, missing file ->
    ({}, None). Parse errors PROPAGATE: the mint/sync flows that consume
    this shape historically crashed on malformed YAML and still do
    (their own missing-file refusal checks run first)."""
    p = register_path(ws)
    if not p.exists():
        return {}, None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}, p


def read_register_claims(ws: Path) -> list[dict]:
    """Just the claims — the plan_epistemics shape: missing/unreadable/
    malformed all degrade to [] (fail-open read, never a crash)."""
    reg = register_path(ws)
    if not reg.is_file():
        return []
    try:
        data = yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    return claims_of(data)


def claims_from_text(register_text: str) -> list:
    """Parsed claims from register TEXT (fail-open: a YAML error yields [])."""
    try:
        reg = yaml.safe_load(register_text) or {}
    except yaml.YAMLError:
        return []
    return claims_of(reg)


def find_claim(claims: list, claim_id: str) -> dict | None:
    """The claim row with `id == claim_id`, or None (dict rows only)."""
    return next((c for c in claims
                 if isinstance(c, dict) and str(c.get("id") or "") == claim_id),
                None)


# ---------------------------------------------------------------------------
# DEPS — the claim_deps.yaml DAG edge
# ---------------------------------------------------------------------------

def ensure_dep_edge(ws: Path, parent_id: str, child_id: str) -> None:
    """The real DAG edge (claim_deps.yaml — the authoritative dep store).

    Idempotent: an existing parent->child edge is left untouched; a
    corrupt/unreadable deps file is rebuilt from the edge below."""
    deps_path = Path(ws) / "claim_deps.yaml"
    deps: dict = {}
    if deps_path.exists():
        try:
            loaded = yaml.safe_load(deps_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                deps = loaded
        except Exception:  # noqa: BLE001 — rebuild from the edge below
            deps = {}
    edges = deps.get("depends_on")
    if not isinstance(edges, dict):
        edges = {}
    parents = edges.get(child_id)
    if not isinstance(parents, list):
        parents = []
    if parent_id not in parents:
        parents.append(parent_id)
    edges[child_id] = parents
    deps["depends_on"] = edges
    deps_path.write_text(
        yaml.safe_dump(deps, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
