# -*- coding: utf-8 -*-
"""rlvr/route_ledger.py — the route-attempt ledger.

An episode that ends "unsolved" must be distinguishable from an episode
that tried every declared route. This module owns that evidence:

    runs/rt-tests/<claim>/routes.json

    {
      "schema": "route-ledger/1",
      "claim": "C-004",
      "claim_kind": "static_constant",
      "declared_routes": ["disasm_constant_check"],
      "attempts": [
        {"route": "disasm_constant_check",
         "command": "disasm_constant_check.py --fact F-001 --binary bins/sample",
         "artifact": "runs/rt-tests/C-004/attempt-1.txt",
         "artifact_sha256": "<64-hex>"}
      ]
    }

Contracts:

  - DECLARED ROUTES come from the per-claim-kind ``routes:`` section of
    ``references/schemas/machine_check_map.yaml`` (the single source;
    keyed on ``claim_kind``). The ledger must declare exactly the map's
    routes for its kind — a doctored or stale declaration fails closed.
  - EVERY ATTEMPT is externally checkable: a machine-level command (the
    map's ``check_tool_markers`` tools/markers) and a workspace-relative
    artifact whose sha256 the validator RE-DERIVES from the bytes on
    disk. A digest mismatch (or a missing artifact) makes the attempt
    non-reproducible and therefore not coverage.
  - ``ROUTE_ATTEMPT_BUDGET`` is the fixed attempt budget (policy
    constant, ADR-001 posture: documented rationale, never runtime
    tuned). Reaching it is a legitimate stop (budget exhaustion); it
    pays only on a structurally valid ledger whose attempts are all
    reproducible.
  - ``classify()`` returns the classifier-facing record the disposition
    algebra consumes (``routes`` / ``attempted`` / ``budget`` /
    ``budget_exhausted``). A missing, corrupt, malformed or
    non-reproducible ledger can NEVER claim exhaustion: structural
    failures return ``routes: []`` (the classifier's
    ``_ledger_exhausted`` is the final word), and reproducibility
    failures leave the affected route un-attempted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import yaml
from kunglao_log import warn

from .disposition import _EPISODE_ID_RE  # the shared file-token contract

SCHEMA = "route-ledger/1"

#: workspace-relative root of the per-claim attempt ledgers
LEDGER_DIR = "runs/rt-tests"

#: the one ledger file name per claim
LEDGER_NAME = "routes.json"

#: the fixed attempt budget (ADR-001 posture; the three-strike convention
#: the dispatch precondition already uses — ``promotion_attempts<3``).
ROUTE_ATTEMPT_BUDGET = 3

#: the repository's executable-oracle map (routes + machine-check markers)
MACHINE_CHECK_MAP = (Path(__file__).resolve().parents[2]
                     / "references" / "schemas" / "machine_check_map.yaml")

#: a sha256 digest, lowercase hex
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class RouteLedgerError(ValueError):
    """A route-ledger write or declaration violates the contract."""


# ---------- the claim-kind route map (single source) ----------

def _load_map(path: Path | None = None) -> dict:
    """The machine-check map; missing/unparseable -> {} (fail closed)."""
    p = Path(path) if path is not None else MACHINE_CHECK_MAP
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def route_map(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """{claim_kind: declared routes} from the map's `routes:` section.

    Unknown/malformed entries are dropped (a caller that then asks for a
    kind not in the result fails closed in ``declared_routes``).
    """
    data = _load_map(path).get("routes")
    if not isinstance(data, dict):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for kind, routes in data.items():
        if not isinstance(kind, str) or not kind.strip():
            continue
        if not isinstance(routes, list) or not routes:
            continue
        cleaned = [str(r).strip() for r in routes
                   if isinstance(r, str) and str(r).strip()]
        if len(cleaned) == len(routes):
            out[kind.strip()] = tuple(cleaned)
    return out


def declared_routes(claim_kind: str, *,
                    path: Path | None = None) -> tuple[str, ...]:
    """The map's declared routes for one claim kind; unknown -> raise."""
    kind = str(claim_kind or "").strip()
    routes = route_map(path).get(kind)
    if not routes:
        raise RouteLedgerError(
            f"claim_kind {claim_kind!r} has no declared routes in "
            f"{Path(path).name if path else MACHINE_CHECK_MAP.name} "
            "(unknown kinds fail closed)")
    return routes


# ---------- paths, digests, machine-level commands ----------

def _claim_token(claim) -> str:
    if not isinstance(claim, str) or not _EPISODE_ID_RE.fullmatch(claim):
        raise RouteLedgerError(
            "claim must be a safe file token (letters, digits, '.', '_', '-')")
    return claim


def ledger_path(ws, claim: str) -> Path:
    """``<ws>/runs/rt-tests/<claim>/routes.json`` (claim is a file token)."""
    return Path(ws) / LEDGER_DIR / _claim_token(claim) / LEDGER_NAME


def _artifact_file(ws, artifact) -> tuple[str, Path]:
    """Validate a workspace-relative artifact reference -> (rel, full).

    Absolute paths and traversal are refused: the ledger may only cite
    bytes inside the workspace it describes."""
    if not isinstance(artifact, str) or not artifact.strip():
        raise RouteLedgerError("artifact must be a non-empty path string")
    rel = Path(artifact.strip())
    if rel.is_absolute():
        raise RouteLedgerError("artifact must be workspace-relative")
    root = Path(ws).resolve()
    full = (root / rel).resolve()
    try:
        full.relative_to(root)
    except ValueError as exc:
        raise RouteLedgerError("artifact escapes the workspace") from exc
    return rel.as_posix(), full


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _machine_markers(path: Path | None = None) -> tuple[frozenset, tuple]:
    section = _load_map(path).get("check_tool_markers")
    if not isinstance(section, dict):
        return frozenset(), ()
    tools = frozenset(str(t).lower() for t in (section.get("tools") or [])
                      if isinstance(t, str))
    markers = tuple(str(m) for m in (section.get("markers") or [])
                    if isinstance(m, str))
    return tools, markers


def machine_level_command(command, *, path: Path | None = None) -> bool:
    """True when the command is a machine check, not prose.

    The tool/marker vocabulary is the map's ``check_tool_markers`` section
    (the same single source ``kunglao_verify`` enforces); a sentence like
    "I read the decompiler" is not an attempt.
    """
    if not isinstance(command, str) or not command.strip():
        return False
    tools, markers = _machine_markers(path)
    tokens = command.split()
    first = tokens[0].lower()
    if first.endswith(".exe"):
        first = first[:-4]
    elif first.endswith(".py"):
        first = first[:-3]
    first = re.sub(r"^[./\\]+", "", first)
    if first in tools:
        return True
    return any(marker in command for marker in markers)


# ---------- validation ----------

def _nonempty_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def _attempt_evidence(ws, attempt: dict) -> str | None:
    """None when the attempt is reproducible, else the reason it is not."""
    command = attempt.get("command")
    if not machine_level_command(command):
        return "command is not machine-level (not reproducible)"
    try:
        _rel, full = _artifact_file(ws, attempt.get("artifact"))
    except RouteLedgerError as exc:
        return f"artifact invalid: {exc} (not reproducible)"
    digest = attempt.get("artifact_sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        return "artifact_sha256 must be 64 lowercase hex (not reproducible)"
    try:
        actual = _sha256_file(full)
    except OSError:
        return "artifact unreadable or missing (not reproducible)"
    if actual != digest:
        return "artifact_sha256 does not match the bytes on disk " \
               "(not reproducible)"
    return None


def _incomplete(reason: str, **extra) -> dict:
    """The classifier-facing shape of a ledger that cannot claim coverage."""
    return {
        "routes": [],
        "attempted": [],
        "budget": ROUTE_ATTEMPT_BUDGET,
        "budget_exhausted": False,
        "attempts": 0,
        "reproducible": False,
        "errors": [reason],
        **extra,
    }


def _structure_errors(ledger: dict, claim: str | None,
                      claim_kind: str | None,
                      path: Path | None) -> tuple[list[str], tuple[str, ...],
                                                  str | None]:
    """The ledger's structural contract -> (errors, declared routes, kind)."""
    errors: list[str] = []
    if ledger.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}")
    claim_token = _nonempty_str(ledger.get("claim"))
    if claim_token is None:
        errors.append("claim must be a non-empty string")
    elif claim is not None and claim_token != claim:
        errors.append(f"claim {claim_token!r} does not match {claim!r}")
    ledger_kind = _nonempty_str(ledger.get("claim_kind"))
    if (claim_kind is not None and ledger_kind is not None
            and ledger_kind != claim_kind):
        errors.append(
            f"ledger claim_kind {ledger_kind!r} contradicts {claim_kind!r}")
    kind = _nonempty_str(claim_kind) or ledger_kind
    if kind is None:
        errors.append("claim_kind must be a non-empty string")
        return errors, (), None
    try:
        declared = declared_routes(kind, path=path)
    except RouteLedgerError as exc:
        errors.append(str(exc))
        return errors, (), kind

    raw_declared = ledger.get("declared_routes")
    if not isinstance(raw_declared, list) or any(
            _nonempty_str(r) is None for r in raw_declared):
        errors.append("declared_routes must be a list of non-empty strings")
    elif (set(str(r).strip() for r in raw_declared) != set(declared)
          or len(set(raw_declared)) != len(raw_declared)):
        errors.append(
            "declared_routes contradict the claim kind's declared routes "
            f"({sorted(declared)})")

    budget_field = ledger.get("budget")
    if budget_field is not None and budget_field != ROUTE_ATTEMPT_BUDGET:
        errors.append(
            f"budget {budget_field!r} contradicts the fixed "
            f"ROUTE_ATTEMPT_BUDGET ({ROUTE_ATTEMPT_BUDGET})")
    return errors, declared, kind


def _attempts_check(ws, attempts: list, declared: tuple[str, ...],
                    kind: str | None) -> tuple[list[str], list[str],
                                               dict[str, bool], bool]:
    """Per-attempt structural + reproducibility check.

    Returns (structural errors, evidence errors, per-route reproducible
    map, all_reproducible).
    """
    structural: list[str] = []
    evidence: list[str] = []
    per_route: dict[str, bool] = {}
    all_reproducible = True
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            structural.append(f"attempts[{index}] must be an object")
            continue
        route = _nonempty_str(attempt.get("route"))
        if route is None:
            structural.append(
                f"attempts[{index}].route must be a non-empty string")
            continue
        if declared and route not in declared:
            structural.append(
                f"attempts[{index}].route {route!r} is not declared for "
                f"{kind!r}")
            continue
        reason = _attempt_evidence(ws, attempt)
        if reason is not None:
            all_reproducible = False
            evidence.append(f"{route}: {reason}")
            per_route.setdefault(route, False)
            continue
        per_route[route] = True
    return structural, evidence, per_route, all_reproducible


def validate(ws, ledger, *, claim: str | None = None,
             claim_kind: str | None = None,
             path: Path | None = None) -> dict:
    """Validate one ledger against its claim kind + the fixed budget.

    Returns the classifier-facing record (the disposition algebra reads
    ``routes`` / ``attempted`` / ``budget`` / ``budget_exhausted``) plus
    diagnostics (``attempts``, ``reproducible``, ``errors``). Structural
    failures blank ``routes`` (fail closed); non-reproducible attempts
    keep the declaration but never count as coverage.
    """
    if not isinstance(ledger, dict):
        return _incomplete("ledger must be a JSON object")
    structural, declared, kind = _structure_errors(
        ledger, claim, claim_kind, path)
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        structural.append("attempts must be a list")
        attempts = []
    elif len(attempts) > ROUTE_ATTEMPT_BUDGET:
        structural.append(
            f"{len(attempts)} attempts exceed the fixed "
            f"ROUTE_ATTEMPT_BUDGET ({ROUTE_ATTEMPT_BUDGET})")
    attempt_structural, evidence, per_route, all_reproducible = (
        _attempts_check(ws, attempts, declared, kind))
    structural.extend(attempt_structural)

    if structural:
        return _incomplete("; ".join(structural + evidence))

    attempted = sorted(route for route, ok in per_route.items() if ok)
    # the budget leg pays only when EVERY spent attempt is reproducible —
    # a ledger of unverifiable attempts can never claim exhaustion.
    budget_exhausted = (len(attempts) >= ROUTE_ATTEMPT_BUDGET
                        and all_reproducible and not evidence)
    return {
        "routes": list(declared),
        "attempted": attempted,
        "budget": ROUTE_ATTEMPT_BUDGET,
        "budget_exhausted": bool(budget_exhausted),
        "attempts": len(attempts),
        "reproducible": bool(attempts) and all_reproducible and not evidence,
        "errors": evidence,
    }


def classify(ws, claim: str) -> dict:
    """Read + validate the claim's ledger -> the classifier-facing record.

    Absent/corrupt ledgers read as incomplete evidence (routes: []), never
    as exhaustion.
    """
    path = ledger_path(ws, claim)
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _incomplete("missing ledger", path=str(path))
    except (OSError, ValueError) as exc:
        return _incomplete(f"unreadable ledger: {type(exc).__name__}: {exc}",
                           path=str(path))
    if isinstance(ledger, dict) and ledger.get("claim") not in (None, claim):
        return _incomplete(
            f"ledger claim {ledger.get('claim')!r} does not match the "
            f"ledger path ({claim!r})", path=str(path))
    result = validate(ws, ledger, claim=claim)
    result["path"] = str(path)
    return result


def classify_workspace(ws) -> dict:
    """Aggregate every per-claim ledger under ``runs/rt-tests/*/routes.json``.

    Run-level semantics: coverage pays only when EVERY present ledger
    validates and covers its declaration (union of attempted routes);
    budget pays only when EVERY ledger spent the fixed budget. Any
    structural failure blanks the aggregate (fail closed) — one doctored
    ledger must never lend coverage to the run.
    """
    base = Path(ws) / LEDGER_DIR
    paths = sorted(base.glob(f"*/{LEDGER_NAME}")) if base.is_dir() else []
    if not paths:
        return _incomplete("no route ledgers in the workspace")
    results = [classify(ws, path.parent.name) for path in paths]
    if any(not result["routes"] for result in results):
        return _incomplete(
            "an invalid route ledger is present",
            errors=[error for result in results for error in result["errors"]])
    complete = all(set(result["routes"]) <= set(result["attempted"])
                   for result in results)
    spent = all(result["budget_exhausted"] for result in results)
    routes = sorted({route for result in results for route in result["routes"]})
    attempted = (sorted({route for result in results
                         for route in result["attempted"]})
                 if complete or spent else [])
    return {
        "routes": routes,
        "attempted": attempted,
        "budget": ROUTE_ATTEMPT_BUDGET,
        "budget_exhausted": spent,
        "attempts": sum(result["attempts"] for result in results),
        "reproducible": all(result["reproducible"] for result in results),
        "errors": [error for result in results for error in result["errors"]],
    }


# ---------- the writer ----------

def _atomic_write(path: Path, doc: dict) -> None:
    """Write the ledger through a temp file + replace (never a torn file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".routes-",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError as exc:
                # a leftover temp file is benign, but never silent
                warn("rlvr.route_ledger.cleanup",
                     f"{type(exc).__name__}: {exc}")


def record_attempt(ws, *, claim: str, claim_kind: str, route: str,
                   command: str, artifact: str) -> dict:
    """Append one reproducible route attempt to the claim's ledger.

    Refuses (``RouteLedgerError``) an unknown claim kind, an undeclared
    route, a prose command, a missing/escaping artifact, a corrupt
    existing ledger, or an attempt past the fixed budget. The artifact's
    sha256 is computed HERE (callers never supply the digest — evidence
    is derived from the bytes, not declared).
    """
    declared = declared_routes(claim_kind)
    if not isinstance(route, str) or route.strip() not in declared:
        raise RouteLedgerError(
            f"route {route!r} is not declared for claim kind "
            f"{claim_kind!r} (declared: {list(declared)})")
    if not machine_level_command(command):
        raise RouteLedgerError(
            "command is not machine-level — a prose description is not a "
            "route attempt")
    rel, full = _artifact_file(ws, artifact)
    if not full.is_file():
        raise RouteLedgerError(f"artifact {rel!r} does not exist")
    attempt = {
        "route": route.strip(),
        "command": command.strip(),
        "artifact": rel,
        "artifact_sha256": _sha256_file(full),
    }

    path = ledger_path(ws, claim)
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RouteLedgerError(
                f"existing ledger {path} is unreadable: "
                f"{type(exc).__name__}: {exc}") from exc
        checked = validate(ws, doc, claim=claim, claim_kind=claim_kind)
        if not checked["routes"]:
            raise RouteLedgerError(
                f"existing ledger {path} does not validate: "
                f"{checked['errors']}")
        doc = dict(doc)
        attempts = list(doc.get("attempts") or [])
    else:
        doc = {
            "schema": SCHEMA,
            "claim": _claim_token(claim),
            "claim_kind": claim_kind.strip(),
            "declared_routes": list(declared),
            "attempts": [],
        }
        attempts = []
    if len(attempts) >= ROUTE_ATTEMPT_BUDGET:
        raise RouteLedgerError(
            f"route-attempt budget spent ({ROUTE_ATTEMPT_BUDGET}) — the "
            "ledger cannot grow past the fixed policy budget")
    if attempt not in attempts:
        attempts.append(attempt)
    doc["attempts"] = attempts
    _atomic_write(path, doc)
    return doc
