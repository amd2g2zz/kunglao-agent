#!/usr/bin/env python3
"""web-anticrawl-v2 engine — the dynamic adversarial shield.

Session: GET / -> sid cookie; GET /sdk.js; GET /challenge ->
{sid, salt, difficulty(18-22), ver(1|2), ts, sig}; POST /verify ->
{nonce, fields, salt, difficulty, ts, ver, sig}.

Server recomputes: fpHash = sha256('|'.join(sorted(k=v))) over the six
declared field keys; seed2 = MIX[ver](sha256(fpHash+salt)[:16]);
POW input '{sid}:{salt}:{nonce}:{seed2}' needs `difficulty` leading
zero bits. Enforced: HMAC sig echo, 120s window, sid single-use,
minimum solve latency 0.3s (timing envelope floor), fresh UA gate.

Honeypot: GET /api/config publishes a FAKE mix multiplier + claims a
fixed version — solutions built on it fail. This is the decoy lane.
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
CHALLENGED: dict[str, float] = {}
LOCK = threading.Lock()
STATE = {"ver_cursor": 0, "schedule": None,
         "diff_floor": 18, "diff_ceil": 22, "min_latency": 0.3}
FP_KEYS = ("depth", "lang", "platform", "screen", "tz", "ua")


def fp_hash(fields: dict) -> str:
    canon = "|".join(f"{k}={fields[k]}" for k in FP_KEYS if k in fields)
    return hashlib.sha256(canon.encode()).hexdigest()


def mix(fp_hex: str, salt: str, ver: int) -> int:
    seed = int(hashlib.sha256((fp_hex + salt).encode()).hexdigest()[:16], 16)
    if ver == 1:
        x = ((seed ^ 0x5A5A5A5A) * 0x9E3779B1) & M64
        return ((x << 13) | (x >> 51)) & M64
    x = (((seed + 0x1337C0DE) & M64) * 0x85EBCA6B) & M64
    return ((x >> 7) | (x << 57)) & M64


def pow_ok(inp: str, difficulty: int) -> bool:
    v = int.from_bytes(hashlib.sha256(inp.encode()).digest(), "big")
    return (v >> (256 - difficulty)) == 0


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
        elif p == "/api/config":
            # the honeypot: plausible-looking but WRONG constants
            self._send(200, json.dumps({
                "mix_multiplier": "0xDEADBEEF", "rot_bits": 11,
                "challenge_version": 1,
                "note": "stable config; do not scrape"}).encode(),
                "application/json")
        elif p == "/challenge":
            sid = self._sid()
            if not sid:
                self._send(400, b'{"error":"no_session"}',
                           "application/json")
                return
            with LOCK:
                if STATE["schedule"]:
                    ver = STATE["schedule"][STATE["ver_cursor"]
                                            % len(STATE["schedule"])]
                    STATE["ver_cursor"] += 1
                else:
                    ver = secrets.randbelow(2) + 1
                CHALLENGED[sid] = time.time()
            salt = secrets.token_hex(8)
            difficulty = STATE["diff_floor"] + secrets.randbelow(
                STATE["diff_ceil"] - STATE["diff_floor"] + 1)
            ts = int(time.time())
            sig = hmac.new(SECRET,
                           f"{sid}|{salt}|{difficulty}|{ts}|{ver}"
                           .encode(), hashlib.sha256).hexdigest()[:16]
            self._send(200, json.dumps({
                "sid": sid, "salt": salt, "difficulty": difficulty,
                "ver": ver, "ts": ts, "sig": sig}).encode(),
                "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/verify":
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
            t_issue = CHALLENGED.get(sid)
            USED.add(sid)
        if t_issue is None or time.time() - t_issue < STATE["min_latency"]:
            self._send(403, b'{"error":"too_fast"}', "application/json")
            return
        try:
            sig = hmac.new(
                SECRET, f"{sid}|{req['salt']}|{int(req['difficulty'])}|"
                        f"{int(req['ts'])}|{int(req['ver'])}".encode(),
                hashlib.sha256).hexdigest()[:16]
            if not hmac.compare_digest(sig, str(req["sig"])):
                self._send(403, b'{"error":"bad_sig"}',
                           "application/json")
                return
            if abs(time.time() - int(req["ts"])) > 120:
                self._send(403, b'{"error":"stale"}',
                           "application/json")
                return
            fph = fp_hash(req["fields"])
            seed2 = mix(fph, str(req["salt"]), int(req["ver"]))
            inp = f"{sid}:{req['salt']}:{req['nonce']}:{seed2}"
            if not pow_ok(inp, int(req["difficulty"])):
                self._send(403, b'{"error":"pow_mismatch"}',
                           "application/json")
                return
        except Exception:
            self._send(400, b'{"error":"bad_request"}',
                       "application/json")
            return
        self._send(200, json.dumps({"secret_data": uuid.uuid4().hex,
                                    "session": sid,
                                    "ver": int(req["ver"])}).encode(),
                   "application/json")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--ver-schedule", default=None)
    a = ap.parse_args()
    if a.ver_schedule:
        STATE["schedule"] = [int(x) for x in a.ver_schedule.split(",")]
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f"PORT {srv.server_address[1]}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
