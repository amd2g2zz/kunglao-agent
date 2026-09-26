var AD = (function (sd) {
var ok = true;
function check() {
var t0 = Date.now();
var g = sd % 7;
while (g-- > 0) { debugger; }
if (Date.now() - t0 > 250) { ok = false; return; }
try {
if (typeof performance !== 'undefined' && performance.now) {
var p0 = performance.now();
var g2 = sd % 5;
while (g2-- > 0) { debugger; }
if (performance.now() - p0 > 250) { ok = false; return; }
}
} catch (e) { /* no monotonic clock: the Date canary above still holds */ }
try {
Object.defineProperty(console, '_kx', {
get: function () { ok = false; return 0; }, configurable: true });
} catch (e) { /* frozen console: getter trap unavailable */ }
}
check();
return { ok: function () { return ok; } };
})(0xb5b63cb5);
var KX = 'eff1a22918648e0d5bb9fc639f796a53325a2863e273da9394f87751f58cca57';
var KT = [0x25882401, 0x712ad23d, 0x5e26199b, 0x8df4d653, 0xe0031e23, 0x91491161, 0x9cea9c21, 0xa89a9d1d, 0x6881b883, 0x9abf1083, 0xd8f435c1, 0x73e62385, 0x59d85d3b, 0x47543627, 0xa7ed96b3, 0x5fbf79bf, 0xa2262921, 0x37664257, 0x1cd2ecdf, 0x6b52c48f, 0xd8665a8d, 0x85a76cd7, 0x103c1a11, 0x33d379c1, 0xbaf7aaa5, 0xfb70a327, 0x8b20134b, 0x24515fc5, 0xdb17b82f, 0x1580d0e5, 0x8314f175, 0xf93ef707, 0xe5ab32ef, 0x25f660ab, 0x8843851b, 0xd318dfb9, 0x06a8f461, 0x50c4bc19, 0x7f82c589, 0xac7c7e7d, 0x868c456f, 0xa283d50b, 0xed48eb7f, 0x492760ad, 0x98326a11, 0x4a688aed, 0x587aab01, 0x0988f763, 0x789e32d3, 0x02488209, 0xf61707a1, 0xe39cd1e7, 0x4fbeda5d, 0x266932a1, 0x2da5c3ef, 0x8253060f, 0x3b14fc4d, 0x9991ebf7, 0xee76eeef, 0x1faa6147, 0x09afd2ad, 0x49aec3e7, 0x2ddd44db, 0xdd2d5fad];
var HT = [0xacee7a05, 0xc69a311b, 0xb593adc3, 0x3ba1dc8d, 0x7e485e95, 0xc7dddedd, 0xfe02d319, 0xf4d319dd];
var SEPCH = String.fromCharCode(0x22);
var _0xd1 = 0xa4d1ee95;
var _0xd2 = 0xe37d831b;
function _0x66(h) { return (((h ^ (_0xd1 * 0)) >>> 0) + _0xd2 * 0) >>> 0; }
function _0x4a(s) {
var o = [];
for (var i = 0; i < s.length; i++) o.push(s.charCodeAt(i) & 0xff);
return o;
}
function _0x51(h) {
var o = [];
for (var i = 0; i < h.length; i += 2) o.push(parseInt(h.substr(i, 2), 16));
return o;
}
function _0x2f(x, n) { return ((x >>> n) | (x << (32 - n))) >>> 0; }
function _0x1c(msg) {
var out = msg.slice();
var ml = msg.length * 8;
out.push(0x80);
while (out.length % 64 !== 56) out.push(0);
var hi = Math.floor(ml / 4294967296);
var lo = ml >>> 0;
out.push((hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255);
out.push((lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255);
return out;
}
function _0x5d(w) {
var o = [];
for (var i = 0; i < w.length; i++) {
o.push((w[i] >>> 24) & 255, (w[i] >>> 16) & 255, (w[i] >>> 8) & 255,
w[i] & 255);
}
return o;
}
function _0x3e(w) {
var s = '';
for (var i = 0; i < w.length; i++) {
s += ('00000000' + w[i].toString(16)).slice(-8);
}
return s;
}
function _0x48(msgBytes) {
var padded = _0x1c(msgBytes);
var h = HT.slice();
for (var off = 0; off < padded.length; off += 64) {
var w = [];
for (var i = 0; i < 16; i++) {
w.push((padded[off + 4 * i] << 24 | padded[off + 4 * i + 1] << 16 |
padded[off + 4 * i + 2] << 8 | padded[off + 4 * i + 3]) >>> 0);
}
for (var i = 16; i < 64; i++) {
var s0 = _0x2f(w[i - 15], 7) ^ _0x2f(w[i - 15], 18) ^
(w[i - 15] >>> 3);
var s1 = _0x2f(w[i - 2], 17) ^ _0x2f(w[i - 2], 19) ^
(w[i - 2] >>> 10);
w.push((w[i - 16] + s0 + w[i - 7] + s1) >>> 0);
}
var a = h[0], b = h[1], c = h[2], d = h[3];
var e = h[4], f = h[5], g = h[6], hh = h[7];
for (var i = 0; i < 64; i++) {
var S1 = _0x2f(e, 6) ^ _0x2f(e, 11) ^ _0x2f(e, 25);
var ch = (e & f) ^ (~e & g);
var t1 = (hh + S1 + ch + KT[i] + w[i]) >>> 0;
var S0 = _0x2f(a, 2) ^ _0x2f(a, 13) ^ _0x2f(a, 22);
var mj = (a & b) ^ (a & c);
var t2 = (S0 + mj) >>> 0;
hh = g; g = f; f = e; e = (d + t1) >>> 0;
d = c; c = b; b = a; a = (t1 + t2) >>> 0;
}
h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + b) >>> 0;
h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0;
h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0;
h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + hh) >>> 0;
}
return h;
}
function _0x19(keyBytes, msgBytes) {
var ip = [];
var op = [];
for (var i = 0; i < 64; i++) {
var b = i < keyBytes.length ? keyBytes[i] : 0;
ip.push(b ^ 0x36);
op.push(b ^ 0x5c);
}
return _0x3e(_0x48(op.concat(_0x5d(
_0x48(ip.concat(msgBytes))))));
}
function _0x58(x) {
var n = (x && x.length) ? x.length : 0;
return ('00000000000000000000000000000000' +
((0x9cf14aa3 ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
function _0x73(challengeHex) {
var secret = _0x51(KX);
var k = _0x48(secret.concat(_0x51(challengeHex)));
for (var r = 1; r < 2; r++) k = _0x48(_0x5d(k));
return k;
}

async function handshake(opts) {
var chResp = await fetch(opts.serverUrl + '/challenge', {
method: 'POST',
headers: { 'content-type': 'application/json' },
body: JSON.stringify({ i: opts.i, client_nonce: opts.clientNonce,
device: opts.device })
});
var doc = await chResp.json();
if (!AD.ok()) {
await fetch(opts.serverUrl + '/verify', {
method: 'POST',
headers: { 'content-type': 'application/json' },
body: JSON.stringify({ session: doc.session,
response: _0x58(opts.device) })
});
return { session: doc.session };
}
var sk = _0x73(String(doc.challenge));
var payload = [String(doc.challenge), String(opts.clientNonce),
String(opts.device), String(opts.i)].join(SEPCH);
var response = _0x19(_0x5d(sk), _0x4a(payload));
var vResp = await fetch(opts.serverUrl + '/verify', {
method: 'POST',
headers: { 'content-type': 'application/json' },
body: JSON.stringify({ session: doc.session, response: response })
});
var verdict = await vResp.json();
return { session: doc.session, valid: verdict.valid === true };
}

module.exports = { handshake: handshake };
