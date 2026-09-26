// chain payload (family chain-js, seed 37006, gradient L3)
// synthetic fixture minted by scripts/eval_chain.py - NOT malware.
var FP0 = 0x650c26e3, FP1 = 0x63e7ad37, FP2 = 0xb5e14bad, SALT = 0x304a31eb;
var CFG_HEX = '0f8f3c705ee76512aa821db7dbffdb711a13f6be5e220892ae3298a9f0eee7f3c915072b72bd729f10ac865167fc0081438edf17b4aa3e911efc3226b1e47cacded250a7dd3a68003bf210ccde385516482df79c4bb8c5646a9d514dfc8cf04c483c95e1b0bd51ce770b3a89ed104ad214f564d0675a3c46d05329b2580019189dd3ad3c85bc5a7ac2722307e4c08da486b447d12e3a27b4d2e58fb57a515719082d9a6d6b6e13874ba08bc7167b13c56ef2604ef5';
var LEGACY_LICENSE_KEY = '67df8bc79f3be691b1642a4d31d14635cef41bbd6467ad271ac58b6be270be43';
var INTEG = 0xe09d5017, CORRUPT = 0xa03e65bf, GATE_DT = 525, GD = 7;
var SEL_KEY = 0xf4;
var LEGACY_P = {c0: 0xe6ff664f, c1: 0xf42084a9, c2: 0xf22b4837, rot: 26, odd: 0xa510a0a7, odd2: 0x5e04c491};
function _rotl(x, r) { r &= 31;
  return r ? (((x << r) | (x >>> (32 - r))) >>> 0) : (x >>> 0); }
function _arx(w, rc) {
  var a = w[0], b = w[1], c = w[2], d = w[3];
  a = (a + d) >>> 0; b ^= _rotl(a, (rc[0] & 15) + 1);
  c = (c + b) >>> 0; d ^= _rotl(c, (rc[1] & 15) + 1);
  a = (a + b) >>> 0; c ^= _rotl(a, (rc[2] & 15) + 1);
  d = (d + c) >>> 0; b ^= _rotl(d, (rc[3] & 15) + 1);
  return [a, b, c, d];
}
var RC = [[1094493037, 721202259, 4047745281, 2326551627], [1766164229, 783789411, 3689401643, 4104647317], [2600946889, 3209407403, 2980071119, 1953514381], [2533342425, 3659974993, 358312947, 1308685973], [2813956567, 4120570889, 1503243245, 771057841], [1908374615, 3000559423, 655784413, 3496495749], [3052866443, 4088617313, 1417555845, 355539481], [3572321601, 179799917, 3659735905, 1759640061]];
function _kdfWords() {
  var w = [(FP0 ^ RC[0][0]) | 1, (FP1 ^ RC[0][1]) >>> 0,
           (FP2 ^ RC[0][2]) >>> 0, (SALT ^ RC[0][3]) >>> 0];
  for (var r = 0; r < 8; r++) {
    w = _arx(w, RC[r % 8]);
    w[r % 4] = (w[r % 4] ^ (((r + 1) * 0x2545F491) >>> 0)) >>> 0;
  }
  return w;
}
function _blk(keyW, ctr) {
  var w = [keyW[0], keyW[1], keyW[2], (keyW[3] ^ ctr) >>> 0];
  for (var r = 0; r < 6; r++) w = _arx(w, RC[(r + 2) % 8]);
  return w;
}
function _decryptHex(hex) {
  var keyW = _kdfWords(), out = [];
  for (var off = 0, ctr = 0; off < hex.length; off += 32, ctr++) {
    var ks = _blk(keyW, ctr);
    for (var j = 0; j < 32 && off + j < hex.length; j += 2) {
      var bi = j >> 1;
      var b = parseInt(hex.substr(off + j, 2), 16);
      out.push(b ^ ((ks[bi >> 2] >>> ((3 - (bi & 3)) * 8)) & 255));
    }
  }
  return String.fromCharCode.apply(null, out);
}
function _cfgOf(hex) { return JSON.parse(_decryptHex(hex).slice(4)); }
function _bytes(s) {
  var o = [];
  for (var i = 0; i < s.length; i++) o.push(s.charCodeAt(i) & 255);
  return o;
}
function _unhex(h) {
  var o = [];
  for (var i = 0; i < h.length; i += 2)
    o.push(parseInt(h.substr(i, 2), 16));
  return o;
}
function _core(p, data, lane) {
  var c0 = p.c0, c1 = p.c1;
  if (lane) {
    c0 = (c0 ^ _rotl(Math.imul(p.odd, lane) >>> 0, 3)) >>> 0;
    c1 = (c1 + Math.imul(p.odd2, lane)) >>> 0;
  }
  var a = c0, b = c1, acc = p.c2;
  for (var i = 0; i < data.length; i++) {
    a = (a + data[i]) >>> 0;
    a = _rotl((a ^ b) >>> 0, p.rot);
    b = (b + a) >>> 0;
    acc = (acc ^ _rotl((a + acc) >>> 0, 3)) >>> 0;
  }
  var h1 = Math.imul(acc, p.odd) >>> 0;
  var h2 = Math.imul(_rotl((h1 ^ b) >>> 0, 7), p.odd) >>> 0;
  return ('00000000' + h1.toString(16)).slice(-8) +
         ('00000000' + h2.toString(16)).slice(-8);
}
function _mac(keyHex, data) {
  var w = [];
  for (var i = 0; i < 4; i++)
    w.push(parseInt(keyHex.substr(i * 8, 8), 16) >>> 0);
  var padded = data.slice();
  padded.push(0x80);
  while (padded.length % 4 !== 0) padded.push(0);
  for (var off = 0, k = 0; off < padded.length; off += 4, k++) {
    w[0] = (w[0] ^ (((padded[off] << 24) | (padded[off + 1] << 16) |
                     (padded[off + 2] << 8) | padded[off + 3]) >>> 0)) >>> 0;
    w = _arx(w, RC[k % 8]);
  }
  w = _arx(w, RC[0]);
  w = _arx(w, RC[1]);
  return ('00000000' + ((w[0] ^ w[2]) >>> 0).toString(16)).slice(-8) +
         ('00000000' + ((w[1] ^ w[3]) >>> 0).toString(16)).slice(-8);
}
// junk wedges stripped - clean analysis form
var TRUE_P = _cfgOf(CFG_HEX).core;

function derive(req) {
  var data = _unhex(String(req.payload));
  var lane = (req.lane | 0) || 0;
  var integNow = INTEG;
  var t0 = Date.now();
  var gd = GD;
  while (gd-- > 0) { debugger; }
  if (Date.now() - t0 > GATE_DT) { integNow = (INTEG ^ CORRUPT) >>> 0; }
  var sel = ((FP0 ^ integNow) >>> 0) & 255;
  if (sel === SEL_KEY) { return _core(TRUE_P, data, lane); }
  return _core(LEGACY_P, data, lane);
}
module.exports = { derive: derive };
