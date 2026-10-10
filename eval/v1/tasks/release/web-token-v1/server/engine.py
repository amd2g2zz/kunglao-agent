#!/usr/bin/env python3
"""web-token-v1 engine — time-bound signed token (light adversarial).

GET  /          -> index.html + sid cookie
GET  /sdk.js    -> the obfuscated SDK (static bytes; also staged as capture/)
GET  /challenge -> {sid, ts}
POST /verify    -> {ts, sig}; server recomputes the mutated HMAC over
                   pad || ts || sid with the SDK-assembled key.
Token freshness: 60s window; sid single-use (replay dead).
UA sanity: a browser-ish User-Agent is required (naive scripts rejected).
"""
from __future__ import annotations
import hashlib, hmac, json, secrets, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# ground truth (mirrors what the SDK assembles at runtime)
KEY = "w7f_xz9Ql2m8sK0eV"          # assembled from shards in the SDK
PAD = bytes.fromhex("6d1f0b9ac2")   # mutated pad prepended to the message
USED: set[str] = set()
LOCK = threading.Lock()
STATIC = Path(__file__).resolve().parent / "static"


def sign(ts: int, sid: str) -> str:
    msg = PAD + f"{ts}|{sid}".encode()
    return hmac.new(KEY.encode(), msg, hashlib.sha256).hexdigest()


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
            self._send(200, json.dumps({"sid": sid, "ts": int(time.time())})
                       .encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/verify":
            self._send(404, b"not found", "text/plain")
            return
        ua = (self.headers.get("User-Agent") or "")
        if not ("Mozilla/" in ua and "(" in ua):
            self._send(403, b'{"error":"non_browser_ua"}',
                       "application/json")
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n))
            ts, sig = int(req["ts"]), str(req["sig"])
        except Exception:
            self._send(400, b'{"error":"bad_request"}', "application/json")
            return
        sid = self._sid()
        if not sid:
            self._send(400, b'{"error":"no_session"}', "application/json")
            return
        with LOCK:
            if sid in USED:
                self._send(403, b'{"error":"replayed"}',
                           "application/json")
                return
            USED.add(sid)
        if abs(time.time() - ts) > 60:
            self._send(403, b'{"error":"stale"}', "application/json")
            return
        if not hmac.compare_digest(sign(ts, sid), sig):
            self._send(403, b'{"error":"bad_signature"}',
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
