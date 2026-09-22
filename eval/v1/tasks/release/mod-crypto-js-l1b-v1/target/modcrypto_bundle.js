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
})(0xc719a225);
var KX = '64e152afce92f837062f942b6f1a9175c69d551badc35afbab3873632bdab62f';
var KT = [0xb0daa443, 0x64b3210b, 0x8029b361, 0x28c0e9c7, 0xc83c4bb1, 0xfe4a81a3, 0x6c332745, 0x19cea97b, 0xd60c37cf, 0x9a296b4b, 0x7da17c89, 0x0f7d4407, 0xc306e229, 0x2cface49, 0x5486da4b, 0x6e9de057, 0x0cbe9b27, 0xcf454eab, 0x6e83ff03, 0x56196fef, 0xb9606b6d, 0x16bbda01, 0x8f51778d, 0x9af836a1, 0x046b2f0b, 0x02c0895f, 0x0e5b01eb, 0x83ea0c77, 0x90de7e91, 0x35fc6b9d, 0x05e16907, 0xf4e4958f, 0xe52ec7cf, 0x4161d7cb, 0xac313ba3, 0xb22cf557, 0xa3c348d9, 0x5f319187, 0xcd8feb2d, 0xe6bef9cb, 0x1521c00d, 0x76e9d461, 0xdcd6ab61, 0x2bc8e947, 0xc07e7c0b, 0xddcfe02f, 0xc5b5cda1, 0x1c40d1ef, 0x48ff9245, 0x9bd1ca1d, 0xb74058b3, 0x6d688741, 0x248a4ae9, 0x7508754f, 0x1bb3a6bd, 0xd95af831, 0xd9f5c3cd, 0x0ec10237, 0x8d32fb63, 0x152903d9, 0xa2bda787, 0x6ee4d305, 0x740ade7f, 0x42e3cf45];
var HT = [0xace4f125, 0x90beab13, 0xd231f57b, 0xfeca6a8d, 0x2bd7aa57, 0x627508e3, 0xc4749b89, 0xa9b89e5f];
var SEPCH = String.fromCharCode(0x26);
var _0xd1 = 0xb276c80f;
var _0xd2 = 0x4c3d9d6b;
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
((0x5bb40009 ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
function sign(input) {
if (!AD.ok()) return _0x58(input);
return _0x19(_0x51(KX), _0x4a(String(input)));
}

module.exports = { sign: sign };

if (typeof require !== 'undefined' && require.main === module) {
console.log(JSON.stringify({ in: 'alpha', out: sign('alpha') }));
}
