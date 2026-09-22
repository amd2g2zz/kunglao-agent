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
})(0x37e050c7);
var KX = '05cbb66d7d9cf03dbecc3c115e8195bb2129fb5d35aaa407c2523faf0744968d';
var KT = [0xa8987953, 0x88fe5aa3, 0x12b91bd5, 0x2b43c095, 0xcf61d22d, 0xf4f99723, 0x36f2c325, 0x54eef2b7, 0x2fd52ce5, 0x971faf3b, 0x96ea01a3, 0xc25d2b7d, 0xe02d4c3d, 0xd4d0c369, 0xab84e1fd, 0x6a177e93, 0x1527fb09, 0x5b5c2b41, 0xcabcd145, 0xe8e5cd17, 0x68c02dd3, 0xa59b4e9b, 0xe23b494b, 0x1198c517, 0x910f9fd3, 0xb4ff51e9, 0x37ac251f, 0x3b0f2ed3, 0x5f9f7013, 0x10373503, 0xf54b59a1, 0xc70f3519, 0x9e877a19, 0x9df15e81, 0xfc3bdc5d, 0xf9513595, 0x680aca03, 0x8059a235, 0xd37b4dd1, 0x201323ef, 0x3a55fe05, 0xdbcdc64f, 0xa3ccdbdd, 0x7da6c585, 0x05719203, 0x221933e7, 0xf99bbb3f, 0x7ade4327, 0x7cbea5c7, 0x3d6f8cb3, 0x14d676cb, 0xf6d52229, 0xbe066e3f, 0xe1c43637, 0x27ead229, 0x7a08a7eb, 0xd0e4e6d5, 0xfb99bfad, 0x6e09ab15, 0x80a3edb1, 0xb21e6231, 0xaf7be3b1, 0x25ec2b09, 0x6218d989];
var HT = [0x52a4a097, 0xb6356987, 0xb1f1a5c3, 0x64105103, 0x445c9867, 0x7ce700cd, 0x579666e9, 0x0a7882ed];
var SEPCH = String.fromCharCode(0x22);
var _0xd1 = 0xe9911473;
var _0xd2 = 0xdd8179e3;
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
((0x2873c565 ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
function sign(request) {
if (!AD.ok()) return _0x58(request && request.body);
var bodySha = _0x3e(_0x48(_0x4a(String(request.body))));
var canon = [String(request.method), String(request.path), bodySha,
String(request.seq)].join(SEPCH);
return _0x19(_0x51(KX), _0x4a(canon));
}

module.exports = { sign: sign };
