"""confidence_schema — ICD-203 7-tier probability ladder (PRD P4, issue #27).

ICD-203 Tradecraft #2 requires a 7-tier probability ladder. The legacy
3-tier system (confirmed / highly_likely / suspected) is mapped to the
new tiers for backward compatibility.

New tiers (high → low):
    almost_certain   — ~95%+  ("almost certain")
    very_likely      — ~80%   ("highly likely")
    likely           — ~65%   ("likely")
    roughly_even     — ~50%   ("roughly even chance")
    unlikely         — ~35%   ("unlikely")
    very_unlikely    — ~20%   ("very unlikely")
    almost_no_chance — ~5%-   ("almost no chance")

Legacy mapping (PRD Open Question #2 resolution):
    confirmed       → almost_certain
    highly_likely   → very_likely
    suspected       → roughly_even
"""
from __future__ import annotations

# The 7 ICD-203 probability tiers, ordered from highest to lowest confidence.
NEW_TIERS = (
    "almost_certain",
    "very_likely",
    "likely",
    "roughly_even",
    "unlikely",
    "very_unlikely",
    "almost_no_chance",
)

# Legacy 3-tier → new 7-tier mapping.
LEGACY_MAP: dict[str, str] = {
    "confirmed": "almost_certain",
    "highly_likely": "very_likely",
    "suspected": "roughly_even",
}

# Combined set of all accepted input values (legacy + new).
_ALL_ACCEPTED = frozenset(NEW_TIERS) | frozenset(LEGACY_MAP.keys())


def validate_confidence(value: str) -> str:
    """Validate a *new* 7-tier confidence value.

    Returns the value unchanged if it is one of the 7 tiers.
    Raises ValueError for any other value (including legacy values —
    use normalize_confidence() to auto-map legacy values).
    """
    if value in NEW_TIERS:
        return value
    raise ValueError(
        f"invalid confidence tier {value!r}; "
        f"expected one of {NEW_TIERS}"
    )


def map_legacy_confidence(value: str) -> str:
    """Map a legacy 3-tier confidence to the new 7-tier.

    If *value* is already a 7-tier name, returns it unchanged.
    If *value* is a legacy name, returns the mapped 7-tier name.
    Raises ValueError for unknown values.
    """
    if value in NEW_TIERS:
        return value
    if value in LEGACY_MAP:
        return LEGACY_MAP[value]
    raise ValueError(
        f"unknown confidence value {value!r}; "
        f"expected one of {sorted(_ALL_ACCEPTED)}"
    )


def normalize_confidence(value: str) -> str:
    """Accept legacy or new confidence values, always return a 7-tier name.

    This is the recommended entry point for consuming confidence values
    from arbitrary sources (fact files, claim-register, etc.).
    """
    if value in NEW_TIERS:
        return value
    if value in LEGACY_MAP:
        return LEGACY_MAP[value]
    raise ValueError(
        f"unknown confidence value {value!r}; "
        f"expected one of {sorted(_ALL_ACCEPTED)}"
    )
