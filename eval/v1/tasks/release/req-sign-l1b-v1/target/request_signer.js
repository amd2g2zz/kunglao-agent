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
})(0xc7882da9);
var KX = '00ac3a872fcada73d383a5cb5a35215fa005425b98cf1819666e04bb200dcb9b';
var KT = [0x0956f269, 0xce7744cf, 0x74953bc1, 0x31a2cb1d, 0xe4253097, 0x7aa063d7, 0xc2051b05, 0xeb21e22d, 0x73aea607, 0xdcc3c6a9, 0xd749e321, 0x948a3417, 0xa167fccd, 0xd9e85c2d, 0xfa983083, 0xb212a0c5, 0x36a026ef, 0x25702b1d, 0xd5353871, 0x1e292eb3, 0x1b27fc71, 0xc9f7e22d, 0x69786fcf, 0x3a99c24b, 0x46b3d9d3, 0x56c730b7, 0x96b443e9, 0x2cbea187, 0xad4e820d, 0x0ee109ed, 0x4aca293b, 0xd0506365, 0xedba8c77, 0x8fb68855, 0x30624659, 0x6a13482d, 0xd0d0928f, 0x2d5171bf, 0x07523625, 0x5b426201, 0x12a44d11, 0x81d61c9f, 0x8f77e077, 0x8498cb1f, 0x860d0165, 0x995744b1, 0x1f951c65, 0x42076e81, 0x866a0c93, 0x9ed93291, 0x17a507e1, 0x6e82bc69, 0x11563ac9, 0xf84410a7, 0xfff1f23b, 0x143a7cab, 0x2b8f8683, 0xd10f69cf, 0xa7b88629, 0x8aa3b439, 0x05f496db, 0x40fd7d7b, 0xdf76057b, 0xec4a5805];
var HT = [0x72f7f925, 0x10cafc67, 0x3d5cd479, 0x39d7ec73, 0xdf3e1ce7, 0x1fb92765, 0xe3b695dd, 0x88a21d21];
var SEPCH = String.fromCharCode(0x22);
var _0xd1 = 0xa0711245;
var _0xd2 = 0xd9765c29;
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
((0xcee2dfdb ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
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
