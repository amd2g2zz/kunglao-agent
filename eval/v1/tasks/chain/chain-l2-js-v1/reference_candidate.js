// CONSTRUCTED candidate (kunglao eval #370) — chain candidate (family chain-js, seed 37003)
// synthetic fixture; NOT malware.
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
var RC = [[1698935243, 3197337467, 2192492701, 3328782435], [4322011, 1562739283, 4190144605, 3314304145], [1592656057, 79621667, 4012199049, 4121911], [2569781033, 82965749, 3160927469, 3250854089], [1958713929, 1894108613, 2149846709, 4204779661], [2144994285, 1347086395, 3309561753, 1391266833], [1897206343, 2074414933, 276072529, 1650089137], [583766289, 842063657, 583623889, 3978065155]];
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
function _unusedDecrypt(hex) {
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
function _unusedCfgOf(hex) { return JSON.parse(_decryptHex(hex).slice(4)); }
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
var TRUE_P = {c0: 0xf655a4ef, c1: 0x39f28007, c2: 0x9e40e9bf, rot: 25, odd: 0xc9882fbb, odd2: 0x43f0498b};
function derive(req) {
  var lane = (req.lane | 0) || 0;
  return _core(TRUE_P, _unhex(String(req.payload)), lane);
}
module.exports = { derive: derive };
