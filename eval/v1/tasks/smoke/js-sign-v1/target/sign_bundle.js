// sign_bundle.js — #299 CONSTRUCTED eval target (family js-sign, eval-v1).
// NOT malware; no real workspace data: an obfuscated-style signer bundle
// seeded by eval_targets.py. Two of the four 32-bit constants below are
// load-bearing (C1, C2); the D-constants are decoys.
// Contract: module.exports.sign(inputString) -> 8-hex-char lowercase.
var _0x4b = ['round', 'fold'];
var C1 = 0x0d4a86e1;
var C2 = 0x3a4a86b9;
var D1 = 0x06b7ad91;
var D2 = 0xabb69d2f;

function _0x2f(h, b) {
  h = (h ^ b) >>> 0;
  h = ((h << 5) | (h >>> 27)) >>> 0;
  return (h + C2) >>> 0;
}

function _0x7a(h) {
  return (((h ^ (h >>> 16)) >>> 0) + D2 * 0) >>> 0;
}

function sign(input) {
  var h = C1;
  for (var i = 0; i < input.length; i++) {
    h = _0x2f(h, input.charCodeAt(i) & 0xff);
  }
  h = _0x7a(h);
  return ('00000000' + h.toString(16)).slice(-8);
}

module.exports = { sign: sign, _table: _0x4b };

if (typeof require !== 'undefined' && require.main === module) {
  console.log(JSON.stringify({ in: 'alpha', out: sign('alpha') }));
  console.log(JSON.stringify({ in: 'bravo', out: sign('bravo') }));
}
