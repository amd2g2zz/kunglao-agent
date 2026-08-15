# tools/crypto — crypto / hash tool home

This directory is the `crypto` category's tool home: local CLIs for cryptography-related tools (encrypt/decrypt/decode/hash routines). It currently holds 1 registered tool + 1 algorithm library:

| File | Tool (id) | Responsibility |
|---|---|---|
| `crypto-tool.py` | `crypto-tool` | 8-algorithm encrypt/decrypt/decode CLI: chacha / xor-add / rolling-xor / lzss / lzma-raw / rsa-unpad / go-byte-transform / va-to-off (issue #285 absorption) |
| `algorithms.py` | — (imported by crypto-tool) | algorithm implementation library (chacha/lzma_raw_decompress etc., fully parameterized); not a CLI, not registered in the index |
| `__init__.py` | — | package marker |

## Relation to the index docs

A worker reads `tools/_index-crypto.md` first (the 6-segment contract entry for `crypto-tool`: Purpose/Usage/Inputs/Outputs/exit code/when_not, with directly copyable usage); this README only explains the in-home file division and history. The machine contract is `tools/_INDEX.yaml`.

## Contract essentials

- Three-state exit codes (#277): 0 success / 1 negative finding (trial decryption missed) / 2 error (with guidance).
- The `--self-check` subcommand validates environment dependencies; run it before trial decryption.
- `--json` emits a single JSON object; `--reproduce` emits field=value lines (kunglao L1 mechanical gate).
- lzma-raw is no longer absorbed as a separate script: the `crypto-tool.py lzma-raw` subcommand (dict_size/lc/lp/pb/size fully parameterized) already covers the same capability, avoiding duplication.
