#!/usr/bin/env python3
"""reference client (solvability proof; never staged).

Reimplements the SDK: canonical fields, both mix transforms, PoW.
Note the timing-envelope floor (0.3s) — real discovery latency covers
it; a pure solver may need a deliberate beat on trivial difficulties.
"""
import hashlib, json, sys, time, urllib.request, http.cookiejar

M64 = (1 << 64) - 1
UA = "Mozilla/5.0 (Macintosh) reference/2.0"
FIELDS = {"ua": UA, "platform": "MacIntel", "lang": "en-US",
          "screen": "1512x982", "tz": "-480", "depth": "30"}


def fp_hash(fields):
    canon = "|".join(f"{k}={fields[k]}" for k in sorted(fields))
    return hashlib.sha256(canon.encode()).hexdigest()


def mix(fp_hex, salt, ver):
    seed = int(hashlib.sha256((fp_hex + salt).encode()).hexdigest()[:16], 16)
    if ver == 1:
        x = ((seed ^ 0x5A5A5A5A) * 0x9E3779B1) & M64
        return ((x << 13) | (x >> 51)) & M64
    x = (((seed + 0x1337C0DE) & M64) * 0x85EBCA6B) & M64
    return ((x >> 7) | (x << 57)) & M64


def main():
    argv = sys.argv
    base = argv[argv.index("--base") + 1] if "--base" in argv else argv[1]
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    op.open(base + "/").read()
    ch = json.load(op.open(base + "/challenge"))
    t0 = time.time()
    fph = fp_hash(FIELDS)
    s2 = mix(fph, ch["salt"], ch["ver"])
    nonce = 0
    while True:
        d = hashlib.sha256(
            f"{ch['sid']}:{ch['salt']}:{nonce}:{s2}".encode()).digest()
        if (int.from_bytes(d, "big") >> (256 - ch["difficulty"])) == 0:
            break
        nonce += 1
    if time.time() - t0 < 0.35:  # respect the timing envelope
        time.sleep(0.35 - (time.time() - t0))
    req = urllib.request.Request(
        base + "/verify",
        data=json.dumps({"nonce": str(nonce), "fields": FIELDS,
                         "salt": ch["salt"], "difficulty": ch["difficulty"],
                         "ts": ch["ts"], "ver": ch["ver"],
                         "sig": ch["sig"]}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})
    out = json.load(op.open(req))
    print(json.dumps(out))
    sys.exit(0 if "secret_data" in out else 1)


if __name__ == "__main__":
    main()
