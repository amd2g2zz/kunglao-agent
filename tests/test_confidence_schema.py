"""RED tests for ICD-203 7-tier confidence ladder (issue #27, PRD P4).

TDD: these tests import confidence_schema which does NOT exist yet → RED.

Covers:
  RED1: 7-tier enum values are all valid (accepted by validate_confidence)
  RED2: invalid values are rejected (ValueError)
  RED3: legacy 3-tier → 7-tier mapping correctness
  RED4: validate_confidence accepts legacy values (auto-maps + returns new)
"""
from __future__ import annotations

import pytest


# =====================================================================
# RED1: all 7 ICD-203 tiers are valid
# =====================================================================

@pytest.mark.parametrize("tier", [
    "almost_certain",
    "very_likely",
    "likely",
    "roughly_even",
    "unlikely",
    "very_unlikely",
    "almost_no_chance",
])
def test_seven_tiers_all_valid(tier):
    """Each of the 7 ICD-203 probability tiers must pass validation."""
    from confidence_schema import validate_confidence
    result = validate_confidence(tier)
    assert result == tier, f"validate_confidence({tier!r}) should return {tier!r}"


# =====================================================================
# RED2: invalid values rejected
# =====================================================================

@pytest.mark.parametrize("bad", [
    "definitely",       # not a tier
    "confirmed",        # legacy — handled separately, not a 7-tier name
    "highly_likely",    # legacy
    "suspected",        # legacy
    "",
    "ALMOST_CERTAIN",   # case-sensitive
    None,
    42,
])
def test_invalid_values_rejected(bad):
    """Non-7-tier values that aren't legacy-mapped must raise ValueError."""
    from confidence_schema import validate_confidence
    with pytest.raises(ValueError):
        validate_confidence(bad)


# =====================================================================
# RED3: legacy 3-tier → 7-tier mapping
# =====================================================================

def test_legacy_confirmed_maps_to_almost_certain():
    from confidence_schema import map_legacy_confidence
    assert map_legacy_confidence("confirmed") == "almost_certain"


def test_legacy_highly_likely_maps_to_very_likely():
    from confidence_schema import map_legacy_confidence
    assert map_legacy_confidence("highly_likely") == "very_likely"


def test_legacy_suspected_maps_to_roughly_even():
    from confidence_schema import map_legacy_confidence
    assert map_legacy_confidence("suspected") == "roughly_even"


def test_map_legacy_rejects_unknown():
    from confidence_schema import map_legacy_confidence
    with pytest.raises(ValueError):
        map_legacy_confidence("definitely")


def test_map_legacy_passes_through_7_tier():
    """map_legacy_confidence on a 7-tier value returns it unchanged."""
    from confidence_schema import map_legacy_confidence
    assert map_legacy_confidence("unlikely") == "unlikely"
    assert map_legacy_confidence("almost_no_chance") == "almost_no_chance"


# =====================================================================
# RED4: normalize_confidence accepts legacy + new, always returns 7-tier
# =====================================================================

def test_normalize_legacy_returns_7tier():
    from confidence_schema import normalize_confidence
    assert normalize_confidence("confirmed") == "almost_certain"
    assert normalize_confidence("highly_likely") == "very_likely"
    assert normalize_confidence("suspected") == "roughly_even"


def test_normalize_new_returns_unchanged():
    from confidence_schema import normalize_confidence
    assert normalize_confidence("almost_certain") == "almost_certain"
    assert normalize_confidence("very_unlikely") == "very_unlikely"


def test_normalize_rejects_invalid():
    from confidence_schema import normalize_confidence
    with pytest.raises(ValueError):
        normalize_confidence("definitely")


# =====================================================================
# Bonus: LEGACY_MAP and NEW_TIERS constants are well-formed
# =====================================================================

def test_new_tiers_has_seven_values():
    from confidence_schema import NEW_TIERS
    assert len(NEW_TIERS) == 7
    assert NEW_TIERS[0] == "almost_certain"
    assert NEW_TIERS[-1] == "almost_no_chance"


def test_legacy_map_has_three_entries():
    from confidence_schema import LEGACY_MAP, NEW_TIERS
    assert len(LEGACY_MAP) == 3
    for v in LEGACY_MAP.values():
        assert v in NEW_TIERS
