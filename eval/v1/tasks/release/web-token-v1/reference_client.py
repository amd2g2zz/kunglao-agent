#!/usr/bin/env python3
"""reference client (corpus-side solvability proof; never staged)."""
import hashlib, hmac, json, sys, time, urllib.request, http.cookiejar

PAD = bytes.fromhex("6d1f0b9ac2")
KEY = "w7f_xz9Ql2m8sK0eV"


def main():
    base = sys.argv[1]
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent",
                      "Mozilla/5.0 (Macintosh) literef/1.0")]
    op.open(base + "/").read()
    ch = json.load(op.open(base + "/challenge"))
    ts = ch["ts"]
    msg = PAD + f"{ts}|{ch['sid']}".encode()
    sig = hmac.new(KEY.encode(), msg, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        base + "/verify", data=json.dumps({"ts": ts, "sig": sig}).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Macintosh) literef/1.0"})
    out = json.load(op.open(req))
    print(json.dumps(out))
    sys.exit(0 if "secret_data" in out else 1)


if __name__ == "__main__":
    main()
