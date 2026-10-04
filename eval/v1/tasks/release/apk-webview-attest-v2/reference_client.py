#!/usr/bin/env python3
"""reference client (solvability proof; never staged) — both layers."""
import hashlib, hmac, json, sys, time, urllib.request, http.cookiejar

M64 = (1 << 64) - 1
UA = "Mozilla/5.0 (Macintosh) reference/3.0"
F = {"ua": UA, "platform": "MacIntel", "lang": "en-US",
     "screen": "1512x982", "tz": "-480", "depth": "30"}
MASK = bytes([0xc4, 0x2b, 0x91, 0x6f, 0x18, 0xd3, 0x7a, 0x05])


def fph():
    canon = "|".join(f"{k}={F[k]}" for k in sorted(F))
    return hashlib.sha256(canon.encode()).hexdigest()


def mix(fp, salt):
    seed = int(hashlib.sha256((fp + salt).encode()).hexdigest()[:16], 16)
    x = ((seed ^ 0x5F5F5F5F) * 0xC0FFEE11) & M64
    return ((x << 13) | (x >> 51)) & M64


def native_claim(seed: bytes, nonce: str) -> bytes:
    d = hashlib.sha256(seed + nonce.encode()).digest()
    return bytes(a ^ b for a, b in zip(d[:8], MASK))


def main():
    argv = sys.argv
    base = argv[argv.index("--base") + 1] if "--base" in argv else argv[1]
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    op.open(base + "/").read()
    ch = json.load(op.open(base + "/challenge"))
    fp = fph()
    s2 = mix(fp, ch["salt"])
    nonce = 0
    while True:
        d = hashlib.sha256(
            f"{ch['sid']}:{ch['salt']}:{nonce}:{s2}".encode()).digest()
        if (int.from_bytes(d, "big") >> (256 - ch["difficulty"])) == 0:
            break
        nonce += 1
    r1 = json.load(op.open(urllib.request.Request(
        base + "/verify",
        data=json.dumps({"nonce": str(nonce), "fields": F,
                         "salt": ch["salt"], "difficulty": ch["difficulty"],
                         "ts": ch["ts"], "sig": ch["sig"]}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})))
    if "attest_seed" not in r1:
        print(json.dumps(r1)); sys.exit(1)
    seed = bytes.fromhex(r1["attest_seed"])
    jsn = r1["js_nonce"]
    claim = native_claim(seed, jsn)
    out = json.load(op.open(urllib.request.Request(
        base + "/attest",
        data=json.dumps({"seed": r1["attest_seed"], "nonce": jsn,
                         "claimed_hex": claim.hex()}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})))
    print(json.dumps(out))
    sys.exit(0 if "secret_data" in out else 1)


if __name__ == "__main__":
    main()
