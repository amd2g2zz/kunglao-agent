// reference candidate: the true derivation (self-check)
var T0 = [0x317b6523, 0x19076f0d, 0xaac80163, 0x7df65635, 0x5c79df9f, 0x3dd19141, 0xbd61cba9, 0x63229153];
var T1 = [0xf60dec4d, 0x6457b4dd, 0xcf789acf, 0x7e1f00a3, 0x5bae2eed, 0x6ef05c8f, 0x6d3c6df3, 0xbb98f085, 0x8bdb8503, 0xa1548f8f, 0x331aa8a9, 0x2cc53d57, 0x6a5d7083, 0x57f0669b, 0xaed0f365, 0xf7c400bf, 0x11d756d9, 0x857a6c25, 0x37a85167, 0x9ee800c7, 0x97c05db3, 0x951cb809, 0xb0ae1b5b, 0x41ff8461, 0x2d9f88fd, 0x863a58c1, 0x378702a7, 0x07c75625, 0x860e9fcb, 0x45553cb7, 0xf79ac653, 0xda1924fb, 0xd4b7ba1d, 0x46494f25, 0xdf858f21, 0xbb1d4a53, 0x3401db27, 0x715a1d4d, 0xc39053a1, 0xd033ef95, 0x4372ab0d, 0x67209757, 0xd0fa4537, 0x74c28497, 0x3aa20e1f, 0x5002f69f, 0xa3de82ab, 0xf9c33749, 0x4c63e557, 0x7f656b09, 0xb886a231, 0xd748fbfd, 0x376500a1, 0x1a2faa07, 0xc33d87ef, 0xac0d7469, 0xb2edbac3, 0x83793fb1, 0xc7c51969, 0x80714ed7, 0x93b3ff27, 0x10291ee5, 0x366b1fab, 0x17e6731d];
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

var SEED_HEX = '0fc717eb09c9cd97';
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
