#!/usr/bin/env python3
"""reference client (solvability proof; never staged)."""
import hashlib, json, sys, urllib.request, http.cookiejar


def main():
    argv = sys.argv
    base = argv[argv.index("--base") + 1] if "--base" in argv else argv[1]
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", "Mozilla/5.0 (Macintosh) literef/1.0")]
    op.open(base + "/").read()
    ch = json.load(op.open(base + "/challenge"))
    nonce = 0
    while True:
        d = hashlib.sha256(
            f"{ch['prefix']}|{ch['sid']}|{nonce}".encode()).digest()
        if (int.from_bytes(d, "big") >> (256 - ch["difficulty"])) == 0:
            break
        nonce += 1
    req = urllib.request.Request(
        base + "/verify",
        data=json.dumps({"nonce": str(nonce), "prefix": ch["prefix"],
                         "difficulty": ch["difficulty"],
                         "ts": ch["ts"]}).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Macintosh) literef/1.0"})
    out = json.load(op.open(req))
    print(json.dumps(out))
    sys.exit(0 if "secret_data" in out else 1)


if __name__ == "__main__":
    main()
