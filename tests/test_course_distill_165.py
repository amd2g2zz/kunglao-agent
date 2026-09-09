# -*- coding: utf-8 -*-
"""#165 course-distillation card contracts (unidbg env-filling + signature-check bypass).

RED-first contract tests for the two new re-library cards distilled from the
26-lesson course corpus (#165). Shape-level assertions only:

  (a) frontmatter: name + description present; description carries a
      when-not boundary (the #165 noise bar: every desc lets the agent
      reject a non-applicable item before opening it);
  (b) budget: each card <= 200 lines;
  (c) fences: fenced code blocks balanced;
  (d) attribution format (issue deliverable 3): the catalog tables carry
      Evidence and Variant inspiration columns and every catalog section
      pins its methodology family;
  (e) deployment preconditions (issue deliverable 2, binding): the unidbg
      card states JDK + Maven toolchain deployment and that unidbg plus its
      dependency tree are pulled from remote (clone + first-build
      dependency resolution);
  (f) corpus-identifier zero: no corpus names/titles/URLs/handles in
      any landed artifact (issue privacy rule) — matched by pre-computed
      token digests so this file itself carries no identifying literal;
  (g) dedup pointers: each card cross-references the existing card that
      owns the shared loop (native-sign-recovery) instead of duplicating it.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELIB = ROOT / "references" / "re-library"

UNIDBG_CARD = RELIB / "android/emulation/unidbg-env-filling.md"
SIGNATURE_CARD = RELIB / "android/signing/signature-check-bypass.md"

NEW_CARDS = [UNIDBG_CARD, SIGNATURE_CARD]

# Source-identifying tokens are matched by PRE-COMPUTED sha256 digests, not
# literals: the privacy rule says corpus identifiers appear ONLY in the
# issue, and this file is an artifact — a reader of the committed test
# learns nothing about any source. The digests are of the lowercased
# tokens (matching the tokenizer below) and were computed out of band:
#   hashlib.sha256(token.encode()).hexdigest()
# Coverage: the corpus's site/community names, its author handle, its
# repo name, demo-target library names, and the forum thread numbers
# observed in its article URLs (hyphenated URL fragments tokenize into
# their numeric part, so the numbers are what the set guards).
FORBIDDEN_TOKEN_HASHES = {
    "02e72597c5038cbec4e40485612739dba40d4dfa9dfdaa7c61d9d35e21e60ad7",
    "0544a4052a1e4aa4dffbadcf74bb2951b4d349dafc42a08af4f357217d81270a",
    "12fa5f8efc397f4ed1d2b8a9ed0b1278f62be6ec0396008eeb3fd55e9ce43a6b",
    "137dddc960dc3c2943234661493ca94b183a09c89bd0276f6c8c518dd344104e",
    "13b7b7a3ebc68dfd528da26043a6a14bee514785c0e90d0eba55d3ed06667c7c",
    "151bb5be7c9a4215a5dc6917bfe76e3ac9a2908f3b98f035479e5ee75aa9a5f5",
    "16a5ce10dfb48b4a06959903922f46fefb5b65e728d29f5214ff648e637812e9",
    "1b9e25aba035fe1775c133c0d2a366e21e8fb6a4cbc34563a0bba03688c008fd",
    "1da683223a10c2ff3c15d50379a7fc8ca9a4f0d20d5460b06ac623a300617925",
    "218d4de91bef596ec3f2ed11fca08f49eb79a0119982fb06621fe95bb0a60824",
    "2c2f759d92b62fd5f206a37e9a8093ca1c0da6326796060ab0eb839f3dd359f9",
    "2d2c065a1c115801966677d159d87f415dffa5e24d9a34b81d2620135ff84e9f",
    "33bc13a7c439619baf2834ceaf597dbe4cb749a3ecbb7030d447a500d78f0a47",
    "344c4721d0f731a32f6f6a07b87056d36787e4d4da34955a8457924564ce7c6d",
    "347315f7077b9bc7bcd352d0e66620e14c3b92adc8728aefe327fca3f630fccc",
    "37011420ce7f3ba0229d4d2ee16d6433e057b8c0f9fbf7317738f5ecda9daf70",
    "37cb0bd9a86f76daab68fbfe8a45eaaf8dc33d7e006a27f039aec644d1bb753a",
    "38474066778457b030bff6e413550f156d0d57da2fddf51c3894b170d1a43bcc",
    "3b76e4f1b3dce88950ab34c689ad3fa484f0a1e8a98673d584c41ea8cee9b024",
    "3b853a66f747496f12741450cb24107c25ae21326778cf381603a720d59c19fd",
    "3c05be8dab1dfc69793d1841720cca95421d654fc5808958037938b2851f7e57",
    "3e5a41940be7490857c4873265c53515d5d8593e6765a4be56ccaf0940f77058",
    "46e33b05ea7349fbc2ff791f32c2bb897d1432827fb6a54c3a8cc38966f0f6f9",
    "483d0b1c1817ddbeb90d9cdfbf23015953215f551fe8509187e7339e4606d277",
    "4b162d526a8a3e866757509c268d29a28e85885392f8d01239129a4ea6f7994c",
    "5534b1b9650da2f33220fc2df7b104c235acce83b989cc5d2ddd1aacbfeb606e",
    "56563b4650d2d244aed9c4e85858144f77213ccc5cacd49c6e73019419163e2f",
    "56e9118f92aef11c2cf6eec451d98e2d9cf37f2f2df14d826e83bd0da8ed8df7",
    "5b6b6b8353731c4bb3811cb27148c2a69137c2b032627f5e3554485880d39e6a",
    "60a95e18f3dac08ea31bd87c9f293efd95d4608158dce4347d31e06dc364ddde",
    "63ab2f9a8068e2233f0da8b1fd6654c8e3505267647094a77fb7eee9d0a2f5b8",
    "64973b1e84aa9ec1582501672198b3e97b835840ae60f121b3780d75295cea25",
    "651b1ca7fe7e15c5a540c9b16339756160cdcdb0701b14f87b5845ec241fa6d5",
    "689394e244c1c8cfeb8a82d5574804bbe6b3efbb8a5458218e3a4274f13374c0",
    "6e6e7dc43b8782e55dbc30fadb34404fed38d6411b06da477bc705906972a58f",
    "706fd611cfcf3b9be66fee1e4e7f2bf4629b45ece9cf5a989e13415060264675",
    "70918c5f3390835499edb6e793ca076948b62ac9beec79ee6c3d2efee29c802b",
    "7ad89cfee1811a0559e56c5274b2aac2fe9cd31ca54bfd5ffae024675752bb9a",
    "7c9853e210f0ac13f15afa1b40e29eabc80d2a8c45dcdad7bb4f010c9d3672f2",
    "8230d1db389557aff2f3d2700576b87c40273c1522a2e3f1aebbb8781d148834",
    "8cbcd9cfe4be89c85eb817c7a2c2bc37bde12386ca1e65a5e510259a5a64d9f5",
    "91597d49c51d9e27ce45134e061522dd577e06e74047f66dfe8aa09e5c096d70",
    "9313d2f6b1efa4df1d063a02ea7ef19cee6ec5472396343cdac0273f2b8b7f49",
    "978fc6736610b77930bf1bd6e5f47c31f32dcf8f2112891382da538acf83fa64",
    "99d2d6e2f84b7eb5ff5b51c15752d51f515b881902b9a086422f7821472a6d5f",
    "99e8f33ca19163079e0c799766cafd282d83566a0594759b8a8958c6d626e682",
    "9e377f6c716cfa05258cf5039a03b90bd4c3924b2e3f6f1631ab61b37c2a5a74",
    "a23894275e7d5a9cee112e1b3755724936850b5b8b663acfb7f9d1dcfd3c4d05",
    "a6d259179926e0f74f41d9df8e1192d2f554508b809c1fbd2cb0af9168633d79",
    "aad30358d4fd9d58e20349080968a405180f4f96f2ed5c3eb66ff10b8610a901",
    "bdb8bf858ad8c7ca509cf6612e25bd4e7c16b527e219d8365c2f971bec9b22bc",
    "c155f96d46c830e4f395993b2601e2a7b28f8eb51a200b8a3bd009ace0046814",
    "d6e7777487e9a4c54e14a2e17e1dbe647e8bc311b4ffbb15e87bb1ddc9863d20",
    "d865b2c6399218fc5eda5ad59937ed16855143402e04e29cc29ff068b58e93cf",
    "eb3cbd0fdbef785fb862c61023f1cf1e7ae9d3a2bfb9445aac5cdd949e7edae6",
    "eda0601c799577b05d6512d9a18f0d849f9f3dfe5e9e54a64346ee07fe228d74",
    "ef24693af7c95dc0467ccfa5b60c477c7225829fb4c9bd053a2dd52892ccbb15",
    "efd3fb4a957eabe3b2acdee34c91d63a0016d5646d2b65935672c2ac7d1933b9",
    "f0f0b034eaf775487f61fb57e1f6e6bd1960e55573861e110a05ed270a9e1b5f",
    "f31e93fe6cb0745d1f657cad267cc6b8f77e522833a86f5428fbabbe21f53f66",
    "f4af1cd0aced81bd634db5adfb39902d3ca01c82825fd14759c836a9171e3e2d",
    "f8925ab1e47b22b9a7afa6fcdee024afb12315f23edb639d3d03b8e15b3c2c95",
    "f98388d002f1218d9220342881ed2fec7a5f4741745d82f62f5196ca8b927b5d",
    "fa91f56c43a656e9439c7ac6c9b819c382fe09cc17e80f4e82f25fd251735549",
}


def _token_hashes(text: str) -> set[str]:
    """sha256 of every alphanumeric token in the lowercased text."""
    return {
        hashlib.sha256(tok.encode()).hexdigest()
        for tok in re.findall(r"[A-Za-z0-9_]+", text.lower())
    }


_CATALOG_ROW = re.compile(r"^\|(?!\s*[-|]).+\|", re.MULTILINE)


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def card_text() -> dict[str, str]:
    out = {}
    for card in NEW_CARDS:
        assert card.is_file(), f"card missing: {card}"
        out[card.name] = card.read_text(encoding="utf-8")
    return out


# ---------- (a) frontmatter ----------

def test_frontmatter_has_name_and_description():
    for card in NEW_CARDS:
        text = card.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{card.name}: missing frontmatter"
        fm = text.split("---\n", 2)[1]
        assert re.search(r"^name:\s*\S", fm, re.MULTILINE), f"{card.name}: no name"
        assert re.search(r"^description:\s*\S", fm, re.MULTILINE), f"{card.name}: no description"


def test_description_carries_when_not_boundary():
    """#165 noise bar: the desc must let the agent reject non-applicable items."""
    for card in NEW_CARDS:
        text = card.read_text(encoding="utf-8")
        fm = text.split("---\n", 2)[1]
        desc = re.search(r"^description:\s*(.+?)(?=^\w+:|\Z)", fm, re.MULTILINE | re.DOTALL).group(1)
        assert re.search(r"[Nn]ot (for|when|use)|Skip (this|when)|do not use", desc), (
            f"{card.name}: description lacks a when-not boundary"
        )


# ---------- (b) budget ----------

def test_cards_within_200_line_budget():
    for card in NEW_CARDS:
        n = len(card.read_text(encoding="utf-8").splitlines())
        assert n <= 200, f"{card.name}: {n} lines exceeds the 200-line budget"


# ---------- (c) fences ----------

def test_code_fences_balanced():
    for card in NEW_CARDS:
        text = card.read_text(encoding="utf-8")
        n = text.count("```")
        assert n % 2 == 0, f"{card.name}: unbalanced code fences ({n})"


# ---------- (d) attribution format ----------

def test_catalog_tables_carry_evidence_and_variant_columns():
    for card in NEW_CARDS:
        text = card.read_text(encoding="utf-8")
        assert "Evidence" in text, f"{card.name}: catalog rows missing Evidence count"
        assert "Variant inspiration" in text, (
            f"{card.name}: catalog rows missing Variant inspiration field"
        )


def test_every_catalog_section_pins_methodology_family(card_text):
    """Attribution deliverable 3: each catalog section names its house family."""
    expectations = {
        UNIDBG_CARD.name: 4,   # log-decode / stubbing-loop / env-integrity / interposition sections
        SIGNATURE_CARD.name: 2,  # acquisition-channel / countermeasure-ladder sections
    }
    for name, minimum in expectations.items():
        text = card_text[name]
        n = len(re.findall(r"^\*\*Family:", text, re.MULTILINE))
        assert n >= minimum, f"{name}: only {n} family attributions (need >= {minimum})"


def test_catalog_rows_have_minimum_hit_information(card_text):
    """Hit-info contract: scenario + how + expected. Table rows must be dense
    enough to carry all three (>= 8 catalog body rows in the unidbg card,
    >= 5 in the signature card)."""
    expectations = {UNIDBG_CARD.name: 8, SIGNATURE_CARD.name: 5}
    for name, minimum in expectations.items():
        text = card_text[name]
        rows = [ln for ln in text.splitlines() if _CATALOG_ROW.match(ln)]
        assert len(rows) >= minimum, f"{name}: only {len(rows)} catalog rows (need >= {minimum})"


# ---------- (e) deployment preconditions (binding deliverable 2) ----------

def test_unidbg_card_states_deployment_preconditions():
    text = UNIDBG_CARD.read_text(encoding="utf-8")
    assert "JDK" in text, "deployment block must state the JDK requirement"
    assert "Maven" in text, "deployment block must state the Maven toolchain"
    assert re.search(r"git clone|cloned from|pulled from", text, re.IGNORECASE), (
        "deployment block must state unidbg is pulled from remote (clone)"
    )
    assert re.search(r"first build|first-build", text, re.IGNORECASE), (
        "deployment block must state first-build dependency resolution"
    )


def test_native_sign_recovery_card_untouched_by_pointer_only():
    """native-sign-recovery.md is at its 200-line budget — the deployment
    block lands in the new card and the existing card stays byte-identical
    is enforced by review; here we only assert the new card POINTS at the
    stubbing loop instead of duplicating it (dedup deliverable)."""
    text = UNIDBG_CARD.read_text(encoding="utf-8")
    assert "native-sign-recovery" in text, "unidbg card must point at the stubbing-loop card"


# ---------- (f) corpus-identifier grep-zero ----------

@pytest.mark.parametrize("artifact", [
    UNIDBG_CARD,
    SIGNATURE_CARD,
    ROOT / "templates" / "frida" / "rpc-skeleton.js.tmpl",
    ROOT / "templates" / "unidbg" / "harness.java.tmpl",
    ROOT / "scripts" / "install_unidbg.sh",
    ROOT / "scripts" / "install_unidbg.py",
])
def test_zero_corpus_identifiers(artifact: Path):
    assert artifact.is_file(), f"artifact missing: {artifact}"
    text = artifact.read_text(encoding="utf-8")
    leaked = FORBIDDEN_TOKEN_HASHES & _token_hashes(text)
    assert not leaked, f"{artifact.name}: corpus-identifying token leak (digests: {sorted(leaked)})"


# ---------- (g) signature card dedup pointers ----------

def test_signature_card_points_at_owned_families():
    text = SIGNATURE_CARD.read_text(encoding="utf-8")
    assert "stacked-protections" in text, "pinning overlaps route to stacked-protections"
    assert "anti-analysis" in text, "instrumentation-detection overlaps route to anti-analysis"
