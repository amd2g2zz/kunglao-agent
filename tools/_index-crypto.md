# crypto domain index (tool layer)

> Domain: encryption/decryption/encoding/hashing tools. When a worker is dispatched to cipher-identification/decoding/hash tasks, read this file first, then load on demand. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml).

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `crypto-tool` | 8-algorithm encrypt/decrypt/decode CLI (chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off) | Read when an encryption/encoding/compression layer is identified; not for schemes outside these 8 algorithm families |
| `cipher_identify` | Captured-param cipher-shape classifier (charset × length × entropy → ranked family candidates + next checks) | Read when facing an opaque captured param/sign/cookie blob and the algorithm family is unknown; not a decoder — classify first, then decode via `crypto-tool` |

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

### cipher_identify

- **Purpose**: Classify an opaque captured parameter (sign token, cookie blob, encrypted payload) into ranked crypto family candidates from its shape — charset × decoded length × Shannon entropy — each with a concrete next check (locate key/IV, try HMAC, test SM3/SM4, …).
- **Usage**:
  ```bash
  python tools/crypto/cipher_identify.py "e10adc3949ba59abbe56e057f20f883e"
  ```
- **Inputs**: One captured param string (positional) or `--in <file>` (text, single token, whitespace-trimmed).
- **Outputs**: stdout JSON: `charset` / `decoded_byte_len` / `entropy_bits_per_byte` / `printable_ratio` + `candidates` ranked [{family, confidence, why, next_check}] over md5/md4-ntlm/sha-1/sha-224/sha-256/sm3/sha-384/sha-512/sha3-512/aes/des-family/sm4/rsa-modulus/jwt/uuid/unix-timestamp/base64-text.
- **exit code**: 0 = classification produced (empty candidates for unrecognized garbage is a valid answer) / 2 = bad tool input (no sample, whitespace inside token, unreadable or undecodable file — fail loud, no guessing).
- **when_not**: Not a decoder or proof — perform the actual decode/verify with `crypto-tool`; do not use on already-identified algorithms (consistent with _INDEX.yaml when_not).
