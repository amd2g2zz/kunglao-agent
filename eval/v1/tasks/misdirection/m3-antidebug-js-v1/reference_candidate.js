// reference candidate: the true derivation (self-check)
var T0 = [0x39bf6029, 0xb5505c37, 0xdacb577d, 0xea73bfa1, 0xdc2c11a1, 0x15d8279b, 0xb1288119, 0x87105f11];
var T1 = [0x329dfe2d, 0x2f89ed59, 0x32511961, 0x4c9af465, 0x225b8d6f, 0xed1dc41d, 0x13ce93cd, 0xd169aea9, 0xbb07866b, 0x66b3c665, 0x03c11085, 0xd119fcc9, 0xa942cc99, 0xe515b3a9, 0xeade684d, 0xde17f2c7, 0xaca7bedb, 0x925907bb, 0x9666b38d, 0x229d37f3, 0x3543f157, 0xd6c25355, 0x4b570d17, 0x86730465, 0xf540cbf1, 0x33727e7f, 0x762385cd, 0xedff708f, 0x83ccc8a3, 0x024a9d63, 0x68b67b3d, 0x8ed653e9, 0xe74554a9, 0x01fb1de1, 0x6802262b, 0x5fb4e7d5, 0xecac0aaf, 0xbc621379, 0x70c7dd57, 0x764cc533, 0x2d072539, 0x6b1d63d7, 0xcd44d789, 0x57478015, 0x99a71be1, 0xf32ee707, 0xd554c8ed, 0xcd9dfcc7, 0x6ab7e237, 0x0eaea2a3, 0x7c178757, 0x552244cf, 0xebab2dd9, 0x591d7bc1, 0xd9b964d9, 0xba1a1fed, 0xd3f6b58d, 0xbec537f3, 0x42dc38b5, 0x54e3114d, 0x4d5ba5f1, 0x94bdff0b, 0xe007789f, 0xd889dba5];
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

var SEED_HEX = '093919df53b56501';
function deriveKeyInternal() {
  return _digest(_u(SEED_HEX)).slice(0, 64);
}
function sign(input) {
  return _hmacHex(_u(deriveKeyInternal()),
    _bytesOf(String(input)));
}
function _bytesOf(s) {
  var o = [];
  for (var i = 0; i < s.length; i++)
    o.push(s.charCodeAt(i) & 0xff);
  return o;
}
module.exports = { sign: sign };
