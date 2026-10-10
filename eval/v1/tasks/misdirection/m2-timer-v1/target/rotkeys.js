// CONSTRUCTED eval target (family key-rotation-js, timer, tier misdirection).
// NOT malware; no real workspace data: a seeded synthetic fixture minted by
// scripts/eval_misdirection.py.

var T0 = [0xa57f54e3, 0x2e780527, 0x052d8a93, 0xb3c03e11, 0x905eabd3, 0x081c8ba1, 0xd9bed38f, 0x559d47f9];
var T1 = [0xaae51dfd, 0xd27b326d, 0xb103356b, 0xecfbde93, 0x5df7906b, 0xd8304427, 0x33ab4895, 0x6bb9a939, 0xcd776cef, 0xb736b1db, 0xcece9f85, 0xc174db23, 0x04cc1ec3, 0xd3c12de5, 0x2a7c10f9, 0x51a13975, 0x43628cb9, 0x3efb796b, 0x634ae8e3, 0x337bd11d, 0x6786d301, 0x67b8818d, 0xe989a493, 0xccc3c02d, 0xea23ff4d, 0x7732cd13, 0x141a930b, 0xd98dd537, 0x9a09ea95, 0x98cc17b9, 0x59f04721, 0x22d14679, 0xbb497465, 0xe24e5625, 0x1fab73a1, 0xc08acde3, 0x289d2a59, 0x1c1ffa47, 0x8d958979, 0x526d817b, 0x70f3ee59, 0x4b2e8561, 0x24b48887, 0xafd986b3, 0xd967de5f, 0xdcff803d, 0x5371c429, 0x21c9903f, 0x602a0b27, 0x16dc5589, 0xfbc9b89b, 0xbc517203, 0x69d0b06f, 0xe873919b, 0xdf59ea33, 0xae6e6145, 0x7949bfd1, 0x1e2fd1ad, 0xad771fd3, 0x08506651, 0xa8888dbf, 0x1f221ef5, 0xa31c1b45, 0xaaf5bb69];
function _r(x, n) { return ((x >>> n) | (x << (32 - n))) >>> 0; }
function _u(h) {
  var o = [];
  for (var i = 0; i < h.length; i += 2) o.push(parseInt(h.substr(i, 2), 16));
  return o;
}
function _h2(w) {
  var s = '';
  for (var i = 0; i < w.length; i++)
    s += ('00000000' + w[i].toString(16)).slice(-8);
  return s;
}
function _b2w(b) {
  var w = [];
  for (var i = 0; i < b.length; i++)
    w.push((b[i] << 24 | b[i + 1] << 16 | b[i + 2] << 8 | b[i + 3]) >>> 0), i += 3;
  return w;
}
function _pad(msg) {
  var out = msg.slice();
  var ml = msg.length * 8;
  out.push(0x80);
  while (out.length % 64 !== 56) out.push(0);
  var hi = Math.floor(ml / 4294967296), lo = ml >>> 0;
  out.push((hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255);
  out.push((lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255);
  return out;
}
function _digest(msgBytes) {
  var padded = _pad(msgBytes);
  var h = T0.slice();
  for (var off = 0; off < padded.length; off += 64) {
    var w = _b2w(padded.slice(off, off + 64));
    for (var i = 16; i < 64; i++) {
      var s0 = _r(w[i - 15], 7) ^ _r(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      var s1 = _r(w[i - 2], 17) ^ _r(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w.push((w[i - 16] + s0 + w[i - 7] + s1) >>> 0);
    }
    var a = h[0], b = h[1], c = h[2], d = h[3];
    var e = h[4], f = h[5], g = h[6], hh = h[7];
    for (var i = 0; w && i < 64; i++) {
      var S1 = _r(e, 6) ^ _r(e, 11) ^ _r(e, 25);
      var ch = (e & f) ^ (~e & g);
      var t1 = (hh + S1 + ch + T1[i] + w[i]) >>> 0;
      var S0 = _r(a, 2) ^ _r(a, 13) ^ _r(a, 22);
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
  return _h2(h);
}
function _b2hex(b) {
  var s = '';
  for (var i = 0; i < b.length; i++) s += ('0' + b[i].toString(16)).slice(-2);
  return s;
}
function _hmacHex(keyBytes, msgBytes) {
  var ip = [], op = [];
  for (var i = 0; i < 64; i++) {
    var b = i < keyBytes.length ? keyBytes[i] : 0;
    ip.push(b ^ 0x36); op.push(b ^ 0x5c);
  }
  var inner = _u(_digest(ip.concat(msgBytes)));
  return _digest(op.concat(inner));
}
function _u64be(n) {
  var hi = Math.floor(n / 4294967296), lo = n >>> 0;
  return [(hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255,
          (lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255];
}

var KX = 'a0e34db3a6950601e555837fca04a479e228b1f1cdbec967039a1e49d9d1662d';
var WINDOW_TICKS = 33;
function windowOf(tick) {
  return Math.floor(tick / WINDOW_TICKS);
}
function deriveWindowKey(windowIndex) {
  return _digest(_u(KX).concat(_u64be(windowIndex >>> 0))
    .slice(0, 40)).slice(0, 64);
}
function sign(tick, payloadHex) {
  var key = _u(deriveWindowKey(windowOf(tick)));
  return _hmacHex(key, _u(payloadHex));
}

module.exports = { sign: sign };

if (typeof require !== 'undefined' && require.main === module) {
  var a = sign(0, 'aabb'), b = sign(1, 'aabb');
  console.log(JSON.stringify({ session0: a, session1: b,
    derivation_point: 'deriveWindowKey' }));
}
