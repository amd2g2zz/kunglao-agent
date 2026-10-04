# prior/pattern store (#518 PR-1)

The expertise-injection surface: pattern libraries and playbooks that the
dispatch face mounts into worker prompts (PR-3). Rules of the house,
enforced by scripts/eval_split_lint.py in CI:

1. FEATURE-KEYED ONLY — entries key on observable sample features
   (language, entropy, import/string signals), never on eval unit ids.
2. NO INSTANCE CONSTANTS — no key, magic, salt, seed, or expected digest
   from any unit's ground_truth. The interpolation holdout's constants
   are linted byte-for-byte (both raw and even-hex decimal-int forms).
3. Pattern-level abstraction — "string-array rotation has these shapes,
   peel with these steps", never "unit X's key is ...".
