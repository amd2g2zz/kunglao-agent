// CONSTRUCTED eval target (family key-rotation-js, per-session, tier misdirection).
// NOT malware; no real workspace data: a seeded synthetic fixture minted by
// scripts/eval_misdirection.py.

var T0 = [0x09e13ebb, 0xfa31b117, 0x7ce53fa5, 0x621d6aa1, 0xc8ce13d3, 0xad9f5be3, 0x5a423e21, 0xf8e80803];
var T1 = [0x533131ff, 0xe814e475, 0x2206f25d, 0x017680c3, 0xf6e5575f, 0x43405f19, 0xbd9af82b, 0x47a84765, 0xac55e4b3, 0x36ad64eb, 0x4c28f48d, 0x22f7fd4d, 0x6505088f, 0x5c997cd5, 0x487b945d, 0xf558993b, 0x6a75ca71, 0x512452f5, 0x5cf0cde3, 0x3213f87f, 0xf4f956b7, 0xbeea6e87, 0xa06dbae1, 0xcd8c3ffb, 0x8504f9fd, 0x52befd35, 0xad2311cf, 0x16b3b559, 0x6803a8d9, 0xbd6a586b, 0x7680f8f9, 0x2055a8d7, 0x5cbfd9a3, 0xaf23d0b5, 0x822087fd, 0x6dd9ef2b, 0x7e036cef, 0x8b98de97, 0x5b5373c3, 0xbf438b69, 0x9fef5117, 0xbfe3a095, 0x5e3417cb, 0x7f0150ff, 0x9c456f71, 0x12512f4d, 0xe95a5317, 0xa5c11841, 0x4e3df2af, 0x2d2191dd, 0xb2c31cc7, 0x61a8af79, 0x30f3576d, 0x4e2def57, 0x68286659, 0xdaf62c8b, 0xc1555bcf, 0x923de205, 0xa6c3700f, 0xb730b0bd, 0xac9de34f, 0xb2067fd5, 0x3804dae1, 0x91e71555];
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

var KX = 'e0d06bebe7f7530f1575973f4423600dd74b1beb9ea96221e90d81bb14e0aac7';
function deriveSessionKey(sessionId) {
  return _digest(_u(KX).concat(_u64be(sessionId >>> 0))
    .slice(0, 40)).slice(0, 64);
}
function sign(sessionId, payloadHex) {
  var key = _u(deriveSessionKey(sessionId));
  return _hmacHex(key, _u(payloadHex));
}

module.exports = { sign: sign };

if (typeof require !== 'undefined' && require.main === module) {
  var a = sign(0, 'aabb'), b = sign(1, 'aabb');
  console.log(JSON.stringify({ session0: a, session1: b,
    derivation_point: 'deriveSessionKey' }));
}
