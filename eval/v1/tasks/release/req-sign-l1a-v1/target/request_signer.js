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
})(0x6749cee7);
var KX = '5d6eb45946a0c74960a6587b98e2032b139d0a63fd691ac7d1706a4fb6901317';
var KT = [0x969f6a61, 0xe6cd5ba9, 0xd435962b, 0x16cf45cb, 0xb767d3ab, 0xe873b573, 0xcc6988b3, 0x1412dca3, 0xf19d1585, 0x12395671, 0x2d320b09, 0xada259e3, 0x41792cb1, 0x897a486f, 0x1429120d, 0xb58df095, 0x90f4d0a7, 0x31b3ef2d, 0xa4f7b425, 0xb96e2c4d, 0x5331742d, 0xbfbb7d4b, 0x091cfda1, 0x4425afad, 0xa9e3ca4f, 0x3fdabdbb, 0x184beb57, 0xac3245e1, 0xe1a60f95, 0x028cd49f, 0xc31b41a5, 0x8072e465, 0x2a5159f1, 0xfe07b0ff, 0x87ce161f, 0xf9cee72d, 0x18d008eb, 0x29adbeb9, 0xbafe7a25, 0xc05f9a95, 0x91150753, 0xa8148afb, 0x1b8ab3d3, 0xfa16f335, 0xee99204d, 0x4800d753, 0xdaab66b9, 0x731f4d95, 0x06f1f8ef, 0x8d7d55c7, 0x89814bc7, 0x56e27fe5, 0x93039029, 0xd5af427b, 0xc3d261c9, 0xc6201571, 0x73493eb7, 0xf7d44361, 0xf4107eeb, 0xbcaa5497, 0x25bee4e7, 0xc14ab49f, 0xcd3306af, 0x5f691ceb];
var HT = [0x987de121, 0xb739b939, 0x8020ec7f, 0xc7c279d9, 0x5df44143, 0x7bceead9, 0x2a9988d5, 0xd76bb5f1];
var SEPCH = String.fromCharCode(0x22);
var _0xd1 = 0xe0077025;
var _0xd2 = 0x3dab0f9d;
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
((0x4863a8f7 ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
function signRequest(request) {
if (!AD.ok()) return _0x58(request && request.body);
var pairs = (request.headers || []).map(function (p) {
return [String(p[0]), String(p[1])];
});
if (false) {
pairs.sort(function (x, y) {
return x[0] < y[0] ? -1 : (x[0] > y[0] ? 1 : 0);
});
}
var blob = pairs.map(function (p) { return p[0] + ':' + p[1]; })
.join(SEPCH);
var hh = _0x3e(_0x48(_0x4a(blob)));
var bodySha = _0x3e(_0x48(_0x4a(String(request.body))));
var canon = [String(request.method), hh, bodySha,
String(request.path)].join(SEPCH);
return _0x19(_0x51(KX), _0x4a(canon));
}

module.exports = { signRequest: signRequest };
