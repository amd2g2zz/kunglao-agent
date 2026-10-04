#!/usr/bin/env python3
"""apk-webview-attest-v2 engine — the WebView JS challenge layer.

GET / -> sid; GET /challenge -> {sid, salt, difficulty(10-14), ts, sig}
(single mix version: rol13((seed^0x5F5F5F5F)*0xC0FFEE11)); POST /verify
-> on success returns {attest_seed (16B hex), js_nonce}: the native
layer's required inputs. The FINAL payload comes from POST /attest
{seed, nonce, claimed_hex} where claimed must equal what the NATIVE
libattest.so computes (sha256(seed||nonce)[:8] ^ MASK) — the server
mirrors the native check; the agent must satisfy both.
"""
from __future__ import annotations
import hashlib, hmac, json, secrets, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

M64 = (1 << 64) - 1
SECRET = secrets.token_bytes(32)
STATIC = Path(__file__).resolve().parent / "static"
USED: set[str] = set()
LOCK = threading.Lock()
NATIVE_MASK = bytes([0xc4, 0x2b, 0x91, 0x6f, 0x18, 0xd3, 0x7a, 0x05])
FP_KEYS = ("depth", "lang", "platform", "screen", "tz", "ua")


def fp_hash(fields):
    canon = "|".join(f"{k}={fields[k]}" for k in FP_KEYS if k in fields)
    return hashlib.sha256(canon.encode()).hexdigest()


def mix(fp_hex, salt):
    seed = int(hashlib.sha256((fp_hex + salt).encode()).hexdigest()[:16], 16)
    x = ((seed ^ 0x5F5F5F5F) * 0xC0FFEE11) & M64
    return ((x << 13) | (x >> 51)) & M64


def native_claim(seed: bytes, nonce: str) -> bytes:
    d = hashlib.sha256(seed + nonce.encode()).digest()
    return bytes(a ^ b for a, b in zip(d[:8], NATIVE_MASK))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    def _send(self, code, body, ctype, cookie=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _sid(self):
        for part in self.headers.get("Cookie", "").split(";"):
            if part.strip().startswith("sid="):
                return part.strip()[4:]
        return None

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/":
            sid = secrets.token_hex(8)
            self._send(200, (STATIC / "index.html").read_bytes(),
                       "text/html", f"sid={sid}; Path=/")
        elif p == "/sdk.js":
            self._send(200, (STATIC / "sdk.js").read_bytes(),
                       "application/javascript")
        elif p == "/challenge":
            sid = self._sid()
            if not sid:
                self._send(400, b'{"error":"no_session"}',
                           "application/json")
                return
            salt = secrets.token_hex(8)
            difficulty = 10 + secrets.randbelow(5)
            ts = int(time.time())
            sig = hmac.new(SECRET, f"{sid}|{salt}|{difficulty}|{ts}"
                           .encode(), hashlib.sha256).hexdigest()[:16]
            self._send(200, json.dumps({
                "sid": sid, "salt": salt, "difficulty": difficulty,
                "ts": ts, "sig": sig}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        p = urlparse(self.path).path
        if p not in ("/verify", "/attest"):
            self._send(404, b"not found", "text/plain")
            return
        ua = self.headers.get("User-Agent") or ""
        if not ("Mozilla/" in ua and "(" in ua):
            self._send(403, b'{"error":"non_browser_ua"}',
                       "application/json")
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n))
        except Exception:
            self._send(400, b'{"error":"bad_request"}',
                       "application/json")
            return
        sid = self._sid()
        if not sid:
            self._send(400, b'{"error":"no_session"}',
                       "application/json")
            return
        with LOCK:
            if sid in USED:
                self._send(403, b'{"error":"replayed"}',
                           "application/json")
                return
        if p == "/verify":
            try:
                sig = hmac.new(
                    SECRET, f"{sid}|{req['salt']}|{int(req['difficulty'])}|"
                            f"{int(req['ts'])}".encode(),
                    hashlib.sha256).hexdigest()[:16]
                if not hmac.compare_digest(sig, str(req["sig"])):
                    self._send(403, b'{"error":"bad_sig"}',
                               "application/json")
                    return
                fph = fp_hash(req["fields"])
                s2 = mix(fph, str(req["salt"]))
                inp = f"{sid}:{req['salt']}:{req['nonce']}:{s2}"
                v = int.from_bytes(hashlib.sha256(inp.encode()).digest(),
                                   "big")
                if (v >> (256 - int(req["difficulty"]))) != 0:
                    self._send(403, b'{"error":"pow_mismatch"}',
                               "application/json")
                    return
            except Exception:
                self._send(400, b'{"error":"bad_request"}',
                           "application/json")
                return
            self._send(200, json.dumps({
                "attest_seed": secrets.token_hex(16),
                "js_nonce": str(req["nonce"]),
                "note": "now satisfy the native layer: POST /attest "
                        "{seed, nonce, claimed_hex}"}).encode(),
                "application/json")
            return
        # /attest — the native-mirrored final gate
        with LOCK:
            USED.add(sid)   # attest consumes too (single-use overall)
        try:
            seed = bytes.fromhex(req["seed"])
            claim = bytes.fromhex(req["claimed_hex"])
            if native_claim(seed, str(req["nonce"])) != claim or \
                    len(claim) != 8:
                self._send(403, b'{"error":"attest_mismatch"}',
                           "application/json")
                return
        except Exception:
            self._send(400, b'{"error":"bad_request"}',
                       "application/json")
            return
        self._send(200, json.dumps({"secret_data": uuid.uuid4().hex,
                                    "session": sid}).encode(),
                   "application/json")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f"PORT {srv.server_address[1]}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
