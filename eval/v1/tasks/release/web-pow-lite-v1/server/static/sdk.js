/* powguard-lite v0.9 — (c) ACME metrics build */
(function () {
  var _0xa = ['L3ZlcmlmeQ==', 'L2NoYWxsZW5nZQ==', 'c2lk', 'cHJlZml4', 'ZGlmZmljdWx0eQ==', 'dHM=', 'bm9uY2U=', 'c2VjcmV0X2RhdGE=', 'fA==', 'c2hhLTI1Ng=='];
  var _0xd = function (i) { return atob(_0xa[i]); };
  function _0xh(s) { // sync sha256 hex via a compact inlined implementation
    var K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    function rr(v, n) { return (v >>> n) | (v << (32 - n)); }
    var H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    var utf8 = unescape(encodeURIComponent(s)), bytes = [];
    for (var i = 0; i < utf8.length; i++) bytes.push(utf8.charCodeAt(i));
    var bitLen = bytes.length * 8;
    bytes.push(0x80);
    while (bytes.length % 64 !== 56) bytes.push(0);
    var hi = Math.floor(bitLen / 0x100000000), lo = bitLen >>> 0;
    for (i = 3; i >= 0; i--) bytes.push((hi >>> (i * 8)) & 255);
    for (i = 3; i >= 0; i--) bytes.push((lo >>> (i * 8)) & 255);
    for (var j = 0; j < bytes.length; j += 64) {
      var w = new Array(64);
      for (i = 0; i < 16; i++) w[i] = (bytes[j+i*4]<<24)|(bytes[j+i*4+1]<<16)|(bytes[j+i*4+2]<<8)|bytes[j+i*4+3];
      for (i = 16; i < 64; i++) { var s0=rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>>3), s1=rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>>10); w[i]=(w[i-16]+s0+w[i-7]+s1)|0; }
      var a=H[0],b=H[1],c=H[2],d=H[3],e=H[4],f=H[5],g=H[6],h=H[7];
      for (i = 0; i < 64; i++) { var S1=rr(e,6)^rr(e,11)^rr(e,25), ch=(e&f)^(~e&g), t1=(h+S1+ch+K[i]+w[i])|0, S0=rr(a,2)^rr(a,13)^rr(a,22), mj=(a&b)^(a&c)^(b&c), t2=(S0+mj)|0; h=g; g=f; f=e; e=(d+t1)|0; d=c; c=b; b=a; a=(t1+t2)|0; }
      H[0]=(H[0]+a)|0; H[1]=(H[1]+b)|0; H[2]=(H[2]+c)|0; H[3]=(H[3]+d)|0; H[4]=(H[4]+e)|0; H[5]=(H[5]+f)|0; H[6]=(H[6]+g)|0; H[7]=(H[7]+h)|0;
    }
    var out = '';
    for (i = 0; i < 8; i++) out += ('00000000' + (H[i] >>> 0).toString(16)).slice(-8);
    return out;
  }
  function _0xzeroBits(hex) {
    var n = 0;
    for (var i = 0; i < hex.length; i++) {
      var v = parseInt(hex[i], 16);
      if (v === 0) { n += 4; continue; }
      if (v < 2) n += 3; else if (v < 4) n += 2; else if (v < 8) n += 1;
      break;
    }
    return n;
  }
  function _0xrun() {
    if (navigator.webdriver) return;
    fetch(_0xd(1)).then(function (r) { return r.json(); }).then(function (ch) {
      var base = ch[_0xd(3)] + _0xd(8) + ch[_0xd(2)] + _0xd(8), nonce = 0, hex;
      do { hex = _0xh(base + nonce); nonce++; }
      while (_0xzeroBits(hex) < ch[_0xd(4)]);
      return fetch(_0xd(0), { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nonce: String(nonce - 1), prefix: ch[_0xd(3)],
          difficulty: ch[_0xd(4)], ts: ch[_0xd(5)] }) });
    }).then(function (r) { return r.json(); }).then(function (d) {
      document.getElementById('out').textContent =
        d[_0xd(7)] ? 'OK ' + JSON.stringify(d) : 'ERR ' + JSON.stringify(d);
    }).catch(function (e) { document.getElementById('out').textContent = 'ERR ' + e; });
  }
  window.powGuard = { run: _0xrun };
})();
