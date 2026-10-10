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
})(0x8760adeb);
var KX = '1f630651e44b7dfbbd53fca75a95ec518d2f5d5fc619760b9c8d40f1c27758d5';
var KT = [0x4196e6db, 0x10255d8f, 0x5a12a565, 0x11487d6f, 0x87764cb5, 0x3aa48301, 0x206d4285, 0x6c512299, 0xb1113c01, 0x64fc8c19, 0x7322c5ed, 0x233476d1, 0xa3175893, 0x159951ff, 0x13247a43, 0x86848145, 0x408cdaf1, 0xd698d431, 0x602db889, 0x79c2856b, 0xbe668ed9, 0x5888cd99, 0xe0c53bb5, 0x6300c855, 0xd748ed8b, 0x4412855d, 0x5ec8f54b, 0x1e15418f, 0x410ffeb9, 0xa49f74e7, 0x4eecf275, 0x7815a79b, 0x6bec5c27, 0x8d05bb8f, 0x09a9556f, 0xe97f8ba5, 0xe0f94ce9, 0xb8040895, 0x783727b7, 0x673e4f61, 0x46114e95, 0xb59a8f49, 0x26a9d529, 0xf8c06c33, 0x8a888a15, 0xfc172cf3, 0x36bb7339, 0xf0987725, 0x3d9313c7, 0x5f93d2a9, 0x0a5b197b, 0xecf0ca7b, 0x2897d2d5, 0x16854899, 0x0d589b47, 0x004b19a9, 0x43dfab2b, 0x5710bf87, 0x0a7d6561, 0x1daf0223, 0x8e3ccc3d, 0x453065f5, 0x9f2060cd, 0xbb0ae655];
var HT = [0xd1f8d625, 0xb674fb77, 0x44fe6de5, 0x54ee4157, 0xeff7708b, 0x4913bf5f, 0xab36ae77, 0x204c171b];
var SEPCH = String.fromCharCode(0x24);
var _0xd1 = 0x7f73178b;
var _0xd2 = 0x75e219c1;
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
((0x5d15a88f ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
function sign(request) {
if (!AD.ok()) return _0x58(request && request.body);
var bodySha = _0x3e(_0x48(_0x4a(String(request.body))));
var canon = [String(request.method), String(request.path), bodySha,
String(request.seq)].join(SEPCH);
return _0x19(_0x51(KX), _0x4a(canon));
}

module.exports = { sign: sign };
