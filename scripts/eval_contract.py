#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_contract.py — the single-source family contract for the eval ladder.

One literal table owns the per-family grading surface consumed by BOTH
grading drivers and the prompt builder:

  suffix             the candidate artifact extension the mechanical
                     checker validates (eval_checker._validate_candidate)
                     and the loop arm extracts (eval_loop_runner
                     ._candidate_suffix) and the bare arm names
                     (eval_control_arm._cand_suffix);
  response_language  the language face of that candidate artifact (the
                     bare prompt's response contract);
  target_surface     how the analysis subject materializes (text source,
                     binary image, or a network-facing protocol client).

Duplicated literal maps across the drivers were the root cause of the
bare-arm campaign's native-tier KeyError class (target-language keying
where the checker grades a python candidate). The registries in
eval_targets / eval_native_targets / eval_misdirection keep the
MECHANISM rows (seeds, models, renderers); this module keeps the GRADING
surface. tests/test_eval_contract_352.py proves all consumers derive
identical expectations for every family and refuses drift loudly.

stdlib only.
"""
from __future__ import annotations

# family -> {suffix, response_language, target_surface}
# native families ship binary artifacts but grade PURE-PYTHON candidates
# (the checker never executes native images) — that asymmetry is exactly
# what the duplicated maps got wrong.
FAMILY_CONTRACT: dict[str, dict[str, str]] = {
    # ---- smoke tier (eval_targets registry) -----------------------------
    "go-arx": {"suffix": ".go", "response_language": "Go",
               "target_surface": "text"},
    "js-sign": {"suffix": ".js", "response_language": "JavaScript",
                "target_surface": "text"},
    "py-derive": {"suffix": ".py", "response_language": "Python",
                  "target_surface": "text"},
    # ---- release tier, native ladder (eval_native_targets registry) ----
    "arm-native-kdf": {"suffix": ".py", "response_language": "Python",
                       "target_surface": "binary"},
    # win-pe-kdf commits the Go SOURCE (the PE is built at mint when the
    # toolchain exists), so its committed entry face is text
    "win-pe-kdf": {"suffix": ".py", "response_language": "Python",
                   "target_surface": "text"},
    "smc-x86": {"suffix": ".py", "response_language": "Python",
                "target_surface": "binary"},
    "mod-crypto-native": {"suffix": ".py", "response_language": "Python",
                          "target_surface": "binary"},
    # ---- release tier, web/net ladder (eval_targets registry) ----------
    "web-pack-sign": {"suffix": ".js", "response_language": "JavaScript",
                      "target_surface": "text"},
    "net-verify-license": {"suffix": ".js", "response_language": "JavaScript",
                           "target_surface": "net"},
    "req-sign": {"suffix": ".js", "response_language": "JavaScript",
                 "target_surface": "text"},
    "mod-crypto-js": {"suffix": ".js", "response_language": "JavaScript",
                      "target_surface": "text"},
    # ---- misdirection tier (eval_misdirection registry) -----------------
    # verdict families grade a schema-checked verdict DOCUMENT, not a
    # reimplementation; decoy families grade the true derivation
    # (conclusion equality) on their surface's language.
    "env-misattr-js": {"suffix": ".json", "response_language": "JSON",
                       "target_surface": "text"},
    "env-misattr-net": {"suffix": ".json", "response_language": "JSON",
                        "target_surface": "net"},
    "key-rotation-js": {"suffix": ".json", "response_language": "JSON",
                        "target_surface": "text"},
    "key-rotation-net": {"suffix": ".json", "response_language": "JSON",
                         "target_surface": "net"},
    "decoy-marker-js": {"suffix": ".js", "response_language": "JavaScript",
                        "target_surface": "text"},
    "decoy-marker-go": {"suffix": ".go", "response_language": "Go",
                        "target_surface": "text"},
    # ---- toolflex tier (eval_toolflex registry, issue 356) ---------------
    # the graded artifact is the session's answer DOCUMENT (answer.txt,
    # byte-exact against the unit's construction); the toolbox tools are
    # the measurement surface, never a graded candidate.
    "tf-chain2": {"suffix": ".txt", "response_language": "Text answer document",
                  "target_surface": "text"},
    "tf-chain3": {"suffix": ".txt", "response_language": "Text answer document",
                  "target_surface": "text"},
    "tf-chain4": {"suffix": ".txt", "response_language": "Text answer document",
                  "target_surface": "text"},
}


def require_family(family: str) -> dict[str, str]:
    """The contract row for ``family``; KeyError (loud, no silent
    fallback) when the family is unregistered."""
    return FAMILY_CONTRACT[family]


def candidate_suffix(family: str) -> str:
    """THE family→candidate-suffix face (single source for all drivers)."""
    return require_family(family)["suffix"]


_RESPONSE_BY_SUFFIX: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".go": "Go",
    ".json": "JSON document",
    ".txt": "Text answer document",
}


def response_language(suffix: str) -> str:
    """The response-language name for a candidate suffix (the bare
    prompt's contract wording)."""
    try:
        return _RESPONSE_BY_SUFFIX[suffix]
    except KeyError:
        raise KeyError(f"no response language for candidate suffix "
                       f"{suffix!r}") from None


def target_surface(family: str) -> str:
    """How the analysis subject materializes: text | binary | net."""
    return require_family(family)["target_surface"]
