# -*- coding: utf-8 -*-
"""tests/test_failure_registry_530.py — issue #530 disposition lock:
failure-registry.yaml template deleted.

The template shipped via release-manifest.yaml but had zero writers
(design-spec §3.6 sec_e writer was never implemented; kunglao-init
SCAFFOLD_FILES does not seed it). digest_build.py reads only the
*workspace* copy fail-soft, so no runtime path requires the template.

These anchors prevent the tombstone from re-shipping without a writer.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "state" / "failure-registry.yaml"
MANIFEST = ROOT / "release-manifest.yaml"
DEDUP_LOCK = ROOT / "tests" / "test_dedup_319.py"


def test_failure_registry_template_removed():
    assert not TEMPLATE.exists(), (
        f"{TEMPLATE} still exists; delete per #530 decision "
        "(no writer exists; design-spec §3.6 unimplemented — the template was "
        "a tombstone that init never seeded)"
    )


def test_failure_registry_not_in_release_manifest():
    text = MANIFEST.read_text(encoding="utf-8")
    assert "failure-registry.yaml" not in text, (
        "release-manifest.yaml still lists failure-registry.yaml; "
        "drop the asset entry alongside the template deletion"
    )


def test_dedup_319_inventory_lock_updated():
    """test_dedup_319.py's STATE_TEMPLATE_NAMES must drop the deleted template,
    otherwise its single-source lock fails on a file that no longer exists.
    (Checks the quoted tuple-entry form — a prose comment documenting the
    retirement is fine, a re-added inventory entry is not.)"""
    text = DEDUP_LOCK.read_text(encoding="utf-8")
    assert '"failure-registry.yaml"' not in text, (
        "tests/test_dedup_319.py still requires templates/state/"
        "failure-registry.yaml — update STATE_TEMPLATE_NAMES in lockstep"
    )
