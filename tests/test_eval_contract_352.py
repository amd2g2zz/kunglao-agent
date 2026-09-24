# -*- coding: utf-8 -*-
"""tests/test_eval_contract_352.py — single-source family contract conformance.

The family→candidate-suffix / response-language / target-surface contract
must live in ONE module (scripts/eval_contract.py) consumed by ALL three
drivers: the mechanical checker (eval_checker._validate_candidate), the
loop-arm extractor (eval_loop_runner._candidate_suffix) and the bare-arm
prompt builder (eval_control_arm._cand_suffix + response-language face).
Duplicated literal maps were the root cause of the control-arm campaign's
native-tier KeyError class; this module + this conformance suite close it.

Faces under test:
  - coverage: every family registered in any eval registry has a contract
    row (no family outside the contract);
  - parity: all three drivers derive IDENTICAL candidate suffixes per
    family, and the checker mechanically accepts exactly that suffix;
  - drift guard: an unknown family is refused everywhere (no silent
    fallback to a stale copy);
  - committed-corpus conformance: every landed task unit across every tier
    satisfies the checker through its contract suffix.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import eval_contract as ec  # noqa: E402
import eval_dataset as ds  # noqa: E402
import eval_native_targets as ntg  # noqa: E402
import eval_targets as tg  # noqa: E402

import eval_loop_runner as lr  # noqa: E402
import eval_control_arm as ca  # noqa: E402


def _all_registered_families() -> set[str]:
    families = set(tg.FAMILIES) | set(ntg.FAMILIES)
    try:
        import eval_misdirection as md
    except ImportError:  # pragma: no cover - module lands with this card
        return families
    families |= set(md.FAMILIES)
    try:
        import eval_chain as ch  # noqa: F401 - #370 chain tier registry
    except ImportError:  # pragma: no cover - module lands with its card
        return families
    return families | set(ch.FAMILIES)


class TestContractCoverage:
    def test_every_registered_family_has_a_contract_row(self):
        missing = _all_registered_families() - set(ec.FAMILY_CONTRACT)
        assert not missing, f"families outside the contract: {sorted(missing)}"

    def test_contract_rows_carry_the_three_faces(self):
        for family, row in ec.FAMILY_CONTRACT.items():
            assert row["suffix"].startswith("."), family
            assert row["response_language"], family
            assert row["target_surface"] in ("text", "binary", "net"), family

    def test_native_families_grade_python_candidates(self):
        for family in ntg.FAMILIES:
            assert ec.candidate_suffix(family) == ".py", family

    def test_web_families_grade_javascript_candidates(self):
        for family in ("web-pack-sign", "net-verify-license", "req-sign",
                       "mod-crypto-js"):
            assert ec.candidate_suffix(family) == ".js", family

    def test_binary_surface_declared_for_native_targets(self):
        for family in ("arm-native-kdf", "smc-x86", "mod-crypto-native"):
            assert ec.target_surface(family) == "binary", family
        # win-pe-kdf commits its Go source; the PE is mint-time only
        assert ec.target_surface("win-pe-kdf") == "text"


class TestDriverParity:
    """All three drivers derive identical expectations per family — the
    conformance face the acceptance contract names."""

    def test_suffix_identical_across_all_three_drivers(self):
        for family in sorted(_all_registered_families()):
            via_contract = ec.candidate_suffix(family)
            via_loop = lr._candidate_suffix({"family": family})
            via_control = ca._cand_suffix({"family": family})
            assert via_contract == via_loop == via_control, family

    def test_checker_accepts_exactly_the_contract_suffix(self, tmp_path):
        import eval_checker as chk

        for family in sorted(_all_registered_families()):
            suffix = ec.candidate_suffix(family)
            good = tmp_path / f"probe-good{suffix}"
            good.write_bytes(b"# probe\n")
            chk._validate_candidate(good, family)  # raises on drift

    def test_checker_refuses_a_wrong_suffix_per_family(self, tmp_path):
        import eval_checker as chk

        for family in sorted(_all_registered_families()):
            suffix = ec.candidate_suffix(family)
            wrong = next(s for s in (".go", ".js", ".py", ".json")
                         if s != suffix)
            bad = tmp_path / f"probe-bad{wrong}"
            bad.write_bytes(b"# probe\n")
            with pytest.raises(chk.Refusal):
                chk._validate_candidate(bad, family)

    def test_unknown_family_refused_not_crashed(self, tmp_path):
        import eval_checker as chk

        cand = tmp_path / "probe.py"
        cand.write_bytes(b"# probe\n")
        with pytest.raises(chk.Refusal):
            chk._validate_candidate(cand, "no-such-family")
        with pytest.raises(KeyError):
            ec.candidate_suffix("no-such-family")

    def test_response_language_follows_the_contract(self):
        for family in sorted(_all_registered_families()):
            suffix = ec.candidate_suffix(family)
            assert ca._response_language(family) == \
                ec.response_language(suffix), family


class TestCommittedCorpusConformance:
    def test_every_landed_unit_passes_through_its_contract_suffix(
            self, tmp_path):
        import eval_checker as chk

        seen = set()
        for tier in ds.TIERS:
            for d in ds.iter_task_dirs(tier=tier):
                family = ds.load_task(d)["family"]
                seen.add(family)
                suffix = ec.candidate_suffix(family)
                cand = tmp_path / f"{tier}-{family}-probe{suffix}"
                cand.write_bytes(b"# probe\n")
                chk._validate_candidate(cand, family)
        assert seen, "the landed corpus must not be empty"

    def test_binary_surface_matches_committed_bytes(self):
        """Units whose contract face is `binary` must carry real images;
        win-pe-kdf commits its Go source, so it stays `text`."""
        native_units = [d for d in ds.iter_task_dirs(tier="release")
                        if ds.load_task(d)["family"] in ntg.FAMILIES]
        assert native_units, "native ladder units must be present"
        for d in native_units:
            task = ds.load_task(d)
            entry = d / task["workspace_scaffold"]["entry"]
            head = entry.read_bytes()[:4]
            surface = ec.target_surface(task["family"])
            if surface == "binary":
                assert head[:4] == b"\x7fELF" or head[:2] == b"MZ", d.name
            else:
                assert task["family"] == "win-pe-kdf", d.name
                entry.read_text(encoding="utf-8")
