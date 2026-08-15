# crypto domain index (tool layer)

> Domain: encryption/decryption/encoding/hashing tools. When a worker is dispatched to cipher-identification/decoding/hash tasks, read this file first, then load on demand. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml).

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `crypto-tool` | 8-algorithm encrypt/decrypt/decode CLI (chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off) | Read when an encryption/encoding/compression layer is identified; not for schemes outside these 8 algorithm families |

## Contract entries

### crypto-tool

- **Purpose**: Apply one of the 8 algorithm families (chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off) to a ciphertext byte string and emit the plaintext layer.
- **Usage**:
  ```bash
  python tools/crypto/crypto-tool.py chacha --in <ciphertext-file> --key <32-byte-hex> --nonce <12-byte-hex>
  ```
- **Inputs**: Ciphertext byte string (`--in <PATH>` or `--in-hex <HEX>`) + subcommand (one of the 8 algorithms; chacha needs `--key`/`--nonce`); optional `--json` / `--reproduce` / `--self-check`.
- **Outputs**: Plaintext/transformed bytes (text by default; `--json` emits a single JSON object; `--reproduce` emits field=value lines for the L1 mechanical gate).
- **exit code**: 0 success / 1 negative finding (trial decryption missed) / 2 error (usage or missing environment, with guidance).
- **when_not**: Not for encryption schemes outside the 8 algorithm families; run `--self-check` first to validate the environment (consistent with _INDEX.yaml when_not).
