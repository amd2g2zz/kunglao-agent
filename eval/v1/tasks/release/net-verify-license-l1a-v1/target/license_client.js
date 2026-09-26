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
})(0x2b426e63);
var KX = '58832933aee0831585e99073c8e48fdd30870f3ddfd552f9a0dceb59cd89c969';
var KT = [0x23087fd7, 0x23e5c921, 0xc46881b5, 0x64dfe57b, 0x45ea177b, 0xc0e3a6df, 0x2cf4bbf3, 0x73894965, 0xb127bbbb, 0x79627883, 0xeef8bb2d, 0x86be53a9, 0xa0bb45b5, 0xeb1ae541, 0xece0e96d, 0x07ef1d21, 0x3509df57, 0x34e82bb5, 0xe4f4c1d3, 0xbd1e5beb, 0x2719023d, 0xb07658bb, 0x7d657025, 0xbcf26bdd, 0xe79e631d, 0xa153cd47, 0x9476c559, 0x71af849d, 0x36351b11, 0x2d8ac1ef, 0xe00946db, 0xfbbb4b29, 0x4ad0c7b5, 0xd20ef2e1, 0x44222847, 0xddeac2c5, 0xa89a1227, 0xbf8c7553, 0x08357053, 0x86bcf0f9, 0x7c51bc1f, 0x38b53ccb, 0x1ba14065, 0x9ad09f7d, 0xf7c17331, 0x3e79819b, 0xbc222f97, 0x81cddff9, 0xfecaca57, 0x15a7960f, 0x20b62c4b, 0x1a690263, 0x342d0a9b, 0x7098e5b3, 0x8429c5c9, 0x6c6efbf5, 0xd77ae55f, 0x42ca74d1, 0x9c7bf091, 0xbd4ed215, 0xda0a1673, 0xc991012f, 0xf11d1f35, 0x22588c59];
var HT = [0x432971f5, 0xca18f587, 0xd53c5627, 0x5f688e01, 0xda1a5b1d, 0xd75097a9, 0xe5936a1d, 0x15c38613];
var SEPCH = String.fromCharCode(0x22);
var _0xd1 = 0x5cdb9ea5;
var _0xd2 = 0x58c91f65;
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
((0x77e3f66d ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
function _0x73(challengeHex) {
var secret = _0x51(KX);
var k = _0x48(secret.concat(_0x51(challengeHex)));
for (var r = 1; r < 3; r++) k = _0x48(_0x5d(k));
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
