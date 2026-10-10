// CONSTRUCTED eval target (family web-pack-sign, rung l0, eval-v1.1, #332).
// NOT malware; no real workspace data: every constant below is
// minted by scripts/eval_targets.py from the unit seed. The
// derivation core is the generator's mod-crypto cipher (mutated
// SHA-256 + HMAC) — stock crypto is wrong by construction.
// anti-debug surface (owner addition):
// silent-wrong on trip, silent-clean otherwise
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
})(0x1cc45c3f);
var KX = '9a257857de450f61a101dc719f4b5c4b783e71ff1bf13e1909f18a139b770047';
var KT = [0xfd12c069, 0x4cb7afe3, 0xec6c79a3, 0xce7c50ad, 0x0008c191, 0x89499305, 0x8a858da5, 0x80e933ab, 0x4f548563, 0x49c6c6fd, 0x8aeb7abf, 0x8c688a4f, 0x490e2c9b, 0xcda1dc15, 0x249d547b, 0xe3d0f02f, 0xfef81e71, 0x5ab8965f, 0x9bca48b9, 0x1aff1e49, 0x4ec45d47, 0x73703a71, 0x249526c9, 0x7ecdad29, 0x22ecd987, 0x00c0adcf, 0x0293c701, 0x01e18fb9, 0xa794d757, 0x1652c085, 0x77a0cc89, 0x44c73ac1, 0x10c81327, 0xa660a8ab, 0xb5d884d1, 0x0f3e3201, 0x69bb14d1, 0xb1691113, 0xd4e818f3, 0x9a176c85, 0x23e547e5, 0xf5c89d1f, 0x5a63f383, 0x050da32d, 0xbf370663, 0x77b11941, 0x6c435bef, 0xd47e07ab, 0x823230bd, 0xa1d11cfd, 0x655ec77b, 0x31413f3f, 0xe204f571, 0x70ec2c35, 0xd8fce2fd, 0x2bd768cf, 0x127b4987, 0xfca83d87, 0x70612ba7, 0x17bceae1, 0xc1b52e37, 0x235f325d, 0x6fcea83b, 0x2a36a54f];
var HT = [0xb83705fd, 0xf896e95f, 0x87e980fb, 0xa4dc3dc1, 0x8573213b, 0xbaeb32bd, 0x5c198df5, 0x4c011967];
var SEPCH = String.fromCharCode(0x22);
function _bytesOf(s) {
  var o = [];
  for (var i = 0; i < s.length; i++) o.push(s.charCodeAt(i) & 0xff);
  return o;
}
function _unhex(h) {
  var o = [];
  for (var i = 0; i < h.length; i += 2) o.push(parseInt(h.substr(i, 2), 16));
  return o;
}
function _rotr32(x, n) { return ((x >>> n) | (x << (32 - n))) >>> 0; }
function _pad(msg) {
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
function _wordsToBytes(w) {
  var o = [];
  for (var i = 0; i < w.length; i++) {
    o.push((w[i] >>> 24) & 255, (w[i] >>> 16) & 255, (w[i] >>> 8) & 255,
      w[i] & 255);
  }
  return o;
}
function _hexWords(w) {
  var s = '';
  for (var i = 0; i < w.length; i++) {
    s += ('00000000' + w[i].toString(16)).slice(-8);
  }
  return s;
}
function _digest(msgBytes) {
  var padded = _pad(msgBytes);
  var h = HT.slice();
  for (var off = 0; off < padded.length; off += 64) {
    var w = [];
    for (var i = 0; i < 16; i++) {
      w.push((padded[off + 4 * i] << 24 | padded[off + 4 * i + 1] << 16 |
        padded[off + 4 * i + 2] << 8 | padded[off + 4 * i + 3]) >>> 0);
    }
    for (var i = 16; i < 64; i++) {
      var s0 = _rotr32(w[i - 15], 7) ^ _rotr32(w[i - 15], 18) ^
        (w[i - 15] >>> 3);
      var s1 = _rotr32(w[i - 2], 17) ^ _rotr32(w[i - 2], 19) ^
        (w[i - 2] >>> 10);
      w.push((w[i - 16] + s0 + w[i - 7] + s1) >>> 0);
    }
    var a = h[0], b = h[1], c = h[2], d = h[3];
    var e = h[4], f = h[5], g = h[6], hh = h[7];
    for (var i = 0; i < 64; i++) {
      var S1 = _rotr32(e, 6) ^ _rotr32(e, 11) ^ _rotr32(e, 25);
      var ch = (e & f) ^ (~e & g);
      var t1 = (hh + S1 + ch + KT[i] + w[i]) >>> 0;
      var S0 = _rotr32(a, 2) ^ _rotr32(a, 13) ^ _rotr32(a, 22);
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
function _hmacHex(keyBytes, msgBytes) {
  var ip = [];
  var op = [];
  for (var i = 0; i < 64; i++) {
    var b = i < keyBytes.length ? keyBytes[i] : 0;
    ip.push(b ^ 0x36);
    op.push(b ^ 0x5c);
  }
  return _hexWords(_digest(op.concat(_wordsToBytes(
    _digest(ip.concat(msgBytes))))));
}
function _wrongOut(x) {
  var n = (x && x.length) ? x.length : 0;
  return ('00000000000000000000000000000000' +
    ((0xf9ad58a7 ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
function sign(request) {
  if (!AD.ok()) return _wrongOut(request && request.body);
  var bodySha = _hexWords(_digest(_bytesOf(String(request.body))));
  var canon = [String(request.method), String(request.path), bodySha,
    String(request.seq)].join(SEPCH);
  return _hmacHex(_unhex(KX), _bytesOf(canon));
}

module.exports = { sign: sign };
