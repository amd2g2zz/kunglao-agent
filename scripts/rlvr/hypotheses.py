# -*- coding: utf-8 -*-
"""rlvr.hypotheses — layer-scoped hypotheses + counterexample refinement
(entropy reduction: a mismatch NARROWS the search, it is not a failed
attempt).

The conflation this cures: when md5(plaintext) != captured, the system
could not tell whether the FAMILY (is it MD5 at all?), the PRIMITIVE
(are the round function / constants right?), or the COMPOSITION
(concatenation / padding / encoding order) was wrong — an over-wide
conclusion ("not MD5") became permanent and option-death pushed the
whole family down even when only the concatenation was wrong.

Three falsifiable layers (the closed vocabulary):
  - ``family``      which hash/cipher family produced the reference
                    structure (decided by constants: constants_ref);
  - ``primitive``   the core transform of that family is intact
                    (decided by a known-answer test);
  - ``composition`` how the primitive's outputs are assembled to match
                    the capture (padding, concatenation order,
                    encoding, counter mode).

Faces:
  - ``refine_on_mismatch(family_match, kat_pass)`` — the CEGAR-shaped
    refinement: evidence structure mechanically localizes the fault to
    ONE layer and names the re-search sub-space. Never "everywhere".
  - ``mint_hypothesis(layer, family, statement)`` — register a
    hypothesis AT THE LAYER WHERE IT IS FALSIFIABLE. The registry is
    reopenable by construction: hypotheses carry status but this face
    only MINTS (refutation transitions belong to the hypothesis store
    carrier; the over-wide-conclusion permanence is addressed by
    minting the REFINEMENT as a fresh open hypothesis rather than
    resurrecting a terminal one).
  - ``layer_death_cells(rows, layer_of)`` — termination accounting
    keyed (kind, family, LAYER): a composition-layer failure never
    piles onto the primitive-layer cell (the option-death conflation).
  - ``covering_matrix(variables, strength)`` — the t-way covering
    machinery (previously verification-only via
    replay_equivalence.required_combos) on the SEARCH side: enumerate
    the transformation space to try before spending attempts.

Pure module: no workspace IO, no store, no gate. Fail-open at the
boundaries (unknown layer -> unscoped bucket; malformed rows skipped
with one canonical warn).
"""
from __future__ import annotations

from dataclasses import dataclass

from kunglao_log import warn  # canonical warn: ONE implementation

# the closed layer vocabulary — the three falsifiable altitudes.
LAYERS: tuple[str, ...] = ("family", "primitive", "composition")
# the explicit bucket for failure rows with no layer attribution —
# absence is honest, never silently folded into a named layer.
LAYER_UNSCOPED = "unscoped"


@dataclass(frozen=True)
class Refinement:
    """One counterexample refinement: the named layer to re-search and
    the sub-space within it. ``family`` carries the identified family
    when the refinement presupposes one (primitive/composition), else
    None (the family layer IS the open question)."""

    layer: str
    subspace: str
    family: str | None


@dataclass(frozen=True)
class Hypothesis:
    """A layer-scoped hypothesis: open at the altitude where evidence
    can falsify it. Status is carried but this face never TRANSITIONS
    it (mint-only; the store carrier owns the state machine)."""

    layer: str
    family: str | None
    statement: str
    status: str = "open"


def refine_on_mismatch(*, family_match: str | None,
                       kat_pass: bool) -> Refinement:
    """CEGAR refinement from a recorded mismatch's evidence structure.

    The decision tree is mechanical (no narration):
      - no family matched the constant set -> the FAMILY layer is
        wrong (or the table is new): re-search the constant-diff space;
      - family matched but the known-answer test FAILS -> the
        PRIMITIVE is wrong (mutated round function / poisoned core):
        re-search primitive variants OF THAT FAMILY;
      - family + primitive confirmed but the digest still mismatches ->
        the COMPOSITION (padding / concatenation / encoding) is wrong:
        re-search assembly orders over the confirmed primitive. The
        family is NOT refuted — this is the issue's md5(plaintext)
        != captured case where option-death used to kill the family."""
    if family_match is None:
        return Refinement(
            layer="family",
            subspace="constant-set diff over all reference families "
                     "(rlvr.constants_ref FAMILIES)",
            family=None)
    if not kat_pass:
        return Refinement(
            layer="primitive",
            subspace=f"{family_match} primitive variants (round function, "
                     f"constant poisoning, byte order) — family constants "
                     f"already match, do NOT re-litigate the family",
            family=str(family_match))
    return Refinement(
        layer="composition",
        subspace=f"{family_match} composition orders (padding scheme, "
                 f"concatenation order, input encoding, counter mode) — "
                 f"primitive verified by KAT, only assembly is open",
        family=str(family_match))


def mint_hypothesis(*, layer: str, family: str | None,
                    statement: str) -> Hypothesis:
    """Register an OPEN hypothesis at a named layer.

    A layer outside the closed vocabulary raises (producer error — the
    whole point is that hypotheses live at DISCRIMINABLE layers)."""
    if layer not in LAYERS:
        raise ValueError(
            f"unknown layer {layer!r}; closed vocabulary: {', '.join(LAYERS)}")
    stmt = str(statement).strip()
    if not stmt:
        raise ValueError("hypothesis statement must be non-empty")
    return Hypothesis(layer=layer, family=family, statement=stmt,
                      status="open")


def layer_death_cells(rows: list[dict],
                      layer_of: dict[str, str]) -> dict[tuple[str, str, str], int]:
    """Termination accounting keyed (kind, family, layer).

    ``rows`` are failure attributions carrying kind + method_family
    (the obstacle-row shape); ``layer_of`` maps family -> layer. A
    family with no attribution lands in LAYER_UNSCOPED (honest
    absence). Malformed rows (missing kind/family) are skipped with one
    canonical warn — a bad row never fabricates a cell."""
    cells: dict[tuple[str, str, str], int] = {}
    for row in rows:
        if not isinstance(row, dict):
            warn("hypotheses.death_cells", f"non-dict row {type(row).__name__}")
            continue
        kind = str(row.get("kind") or "")
        family = str(row.get("method_family") or "")
        if not kind or not family:
            warn("hypotheses.death_cells",
                 f"row missing kind/method_family: {sorted(row)}")
            continue
        layer = str(layer_of.get(family) or LAYER_UNSCOPED)
        key = (kind, family, layer)
        cells[key] = cells.get(key, 0) + 1
    return cells


def covering_matrix(variables: dict, strength: int = 2) -> list[dict]:
    """The t-way covering matrix over the SEARCH space (T5: the
    covering-array machinery wired into search, not only verification).

    Delegates combo generation to replay_equivalence.required_combos —
    ONE implementation of the t-way enumeration, consumed at both the
    verification face (coverage_errors) and the search face (candidate
    enumeration). Returns one dict per required combination (values
    decoded from the canonical form back to the declared domain
    members). An empty variable set returns [] (nothing to cover)."""
    if not isinstance(variables, dict) or not variables:
        return []
    if not isinstance(strength, int) or strength < 1:
        raise ValueError(f"strength must be a positive int, got {strength!r}")
    import json
    from replay_equivalence import required_combos

    out: list[dict] = []
    for combo in required_combos(variables, strength):
        row: dict = {}
        for var, canon in combo:
            try:
                row[var] = json.loads(canon)
            except ValueError:  # non-JSON domain member: keep canonical
                row[var] = canon
        out.append(row)
    return out
