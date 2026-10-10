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
})(0x46da3719);
var KX = 'ec99a3c96fe04cf71ea309979fc274dfb3e9d8ff4408cbbd69970e19c2727b85';
var KT = [0xa27082e1, 0x133fe709, 0xe4c2ee59, 0xca6410d7, 0x19b683cf, 0x6e39a765, 0x9ddee99f, 0x2e7c642b, 0x4794764d, 0x347afe9d, 0x8bf5f41d, 0xac9980a1, 0x13a61f7d, 0x86bc9435, 0xb3a95cdd, 0xc3e57389, 0xa855329d, 0xbaafea6d, 0x134f7947, 0x77bee39d, 0x64316ddb, 0x3e468b0b, 0xaff1bb91, 0x57aa1e55, 0xd746724f, 0xe727f4db, 0x8340a433, 0x94cd45d5, 0xc933bc53, 0x0d61082d, 0xdab5f597, 0x8a4323bd, 0x53b37f7f, 0x09501e03, 0x41e1bb55, 0x57634a8d, 0x671f417d, 0xe499beed, 0x141c4d05, 0x9376b571, 0xcbcdae97, 0xeddf0a61, 0x99396b83, 0xa3e2218b, 0x6fe80aeb, 0xd4752b99, 0x131cda0d, 0xf4949829, 0xda095ed3, 0xe506aac9, 0x0075add9, 0x211d078f, 0x90af2ee9, 0xe4516cf5, 0x63522139, 0xe6f3d1f9, 0x932c37a5, 0xdccbd3af, 0xb43b3f2d, 0x2b9231e9, 0x2a339eef, 0x99394125, 0xbb0d79cb, 0xa98f719b];
var HT = [0x1fc7c487, 0x4e277265, 0x8aa05dad, 0xc582adbb, 0x90a2e851, 0xd8a564cf, 0xdc3711c1, 0xeabcd10b];
var SEPCH = String.fromCharCode(0x26);
var _0xd1 = 0xcb2d3917;
var _0xd2 = 0xc5addb01;
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
((0xca928f11 ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
function sign(input) {
if (!AD.ok()) return _0x58(input);
return _0x19(_0x51(KX), _0x4a(String(input)));
}

module.exports = { sign: sign };

if (typeof require !== 'undefined' && require.main === module) {
console.log(JSON.stringify({ in: 'alpha', out: sign('alpha') }));
}
