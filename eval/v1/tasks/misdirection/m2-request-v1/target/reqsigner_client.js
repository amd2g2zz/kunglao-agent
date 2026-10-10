// CONSTRUCTED eval target (family key-rotation-net, per-request, tier misdirection).
// NOT malware; no real workspace data: a seeded synthetic fixture minted by
// scripts/eval_misdirection.py.

var T0 = [0x66892413, 0x02663b15, 0xdc55ce75, 0xb80ce575, 0x70ecd3c7, 0xd9595c27, 0xc27ab7e9, 0x046ea0d5];
var T1 = [0xa6e40b11, 0x40a24449, 0xa625c4ff, 0x7bf978d7, 0xa1ebe16b, 0xb4e9e0f3, 0x8f6d284b, 0xcab986e7, 0x52f13a3b, 0x93994727, 0xf48db86d, 0x8a4061bd, 0xae7e1c95, 0x3ef993e3, 0x4ebdb53f, 0xf17d039f, 0xcc5e13e7, 0xf2c9d6cf, 0xa998339d, 0xedbb26d1, 0xa5a4d465, 0x4e1016a9, 0x84be463d, 0xfa9690e3, 0x6c5679f1, 0xe65eefd1, 0xaaaf15ab, 0xf13c7ec5, 0x784d9457, 0x8874cef9, 0x80f16903, 0xcfa1e699, 0x2032b58b, 0x3cb41553, 0xd881dcef, 0xbe8b913d, 0xe8831123, 0x7201f99f, 0xead5d51d, 0x8d33490b, 0x7ac50349, 0xad038eed, 0x29e67f1b, 0x9c645e13, 0x9a1cdebb, 0xa93669ab, 0x16291409, 0x46b3c32d, 0x250c3cdb, 0xf7d9f1cd, 0xef947ce7, 0x9a4757dd, 0x17a7ae0f, 0x41497055, 0x813bc911, 0xa9498edb, 0x4b071cd1, 0x870421f9, 0x579723d9, 0x47360415, 0x2b70a933, 0x9b427d33, 0x183e1b7d, 0x0a7ce9af];
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

var KX = 'a633e40f1cbd807301e43bcd7b5db109b7742617c1d62bc74f4f8e470812f84d';
var DEVICE = 'e03fcb855928';
function deriveRequestKey(reqIndex) {
  return _digest(_u(KX).concat(_u64be(reqIndex >>> 0))
    .slice(0, 40)).slice(0, 64);
}
function sign(reqIndex, payloadHex) {
  return _hmacHex(_u(deriveRequestKey(reqIndex)), _u(payloadHex));
}

async function handshake(opts) {
  var payload = String(opts.payload || '');
  var v = await fetch(opts.serverUrl + '/v1/stream', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ i: opts.i, req_index: opts.reqIndex,
      device: DEVICE, payload: payload,
      signature: sign(opts.reqIndex, payload) }) });
  var doc = await v.json();
  return { session: doc.session, valid: doc.valid === true };
}

module.exports = { handshake: handshake, sign: sign };
