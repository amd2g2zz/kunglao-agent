// reference candidate: the true derivation (self-check)
var T0 = [0x8feb73a3, 0x494ce7fd, 0x9926332d, 0x784ad7ad, 0xf8e1068b, 0x35969b1b, 0x1afc2937, 0x774f14b7];
var T1 = [0xb579e507, 0x737eee59, 0xa30bfdc5, 0xe52f6acd, 0x19a942b1, 0x71df6575, 0x1652b909, 0x116dbe09, 0x41acc67f, 0x02b8ce1d, 0x7924b371, 0x876c55c7, 0xff881715, 0x696d531d, 0xd64ee887, 0xede83a97, 0xd1445d3d, 0x98557cc7, 0xa2b247ef, 0x81bd4315, 0xffa9e305, 0xe659b16f, 0xf339a35b, 0xee0f42df, 0x0c36c031, 0x5c578b21, 0xa2bf369b, 0xa69aaa25, 0x381e1e31, 0xd7cc6fd1, 0xd8f81539, 0x52d1fb21, 0xa7bef76d, 0xb0114a6f, 0x7f08891f, 0x0bcc6a87, 0x993a8fa1, 0x9e0bc535, 0xf251b515, 0xbf29c3b1, 0xf5cce4cd, 0x92945db5, 0xa432d891, 0x8f361535, 0x70e91879, 0xa241e6dd, 0x969b2ec7, 0x5104b319, 0xa68b592b, 0x10249d53, 0xf203eb05, 0x21c5a9b1, 0x95294239, 0x7fd2559d, 0x3e4c3331, 0xb18c698d, 0xca32fc1d, 0x2ae6907d, 0x11e6e707, 0x0af8c3a1, 0x8cb102f5, 0x8917baa5, 0xeb1f0a61, 0x9d9c0c23];
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

var SEED_HEX = '0f93cd91bbf5b3a5';
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
