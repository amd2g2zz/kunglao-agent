/* shield-max v4.7.2 — ACME metrics anti-bot build. obfuscated; sourcemap withheld */
(function () {
  var _0xd9 = ['L2NoYWxsZW5nZQ==', 'L3ZlcmlmeQ==', 'c2hpZWxkLWludGVncml0eS1zdHViLXY0Ljc='];
  var _0xq = function (_0xi) { return atob(_0xd9[_0xi]); };
  // field canonicalization (sorted k=v joined) — order is contractual
  function _0xcanon(_0xf) {
    var _0xk = Object.keys(_0xf); _0xk.sort();
    var _0xo = [];
    for (var _0xi = 0; _0xi < _0xk.length; _0xi++) _0xo.push(_0xk[_0xi] + '=' + _0xf[_0xk[_0xi]]);
    return _0xo.join('|');
  }
  function _0xsh(_0xs) {
    var K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    function rr(v,n){return (v>>>n)|(v<<(32-n));}
    var H=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    var u=unescape(encodeURIComponent(_0xs)),b=[];for(var i=0;i<u.length;i++)b.push(u.charCodeAt(i));
    var bl=b.length*8;b.push(0x80);while(b.length%64!==56)b.push(0);
    var hi=Math.floor(bl/0x100000000),lo=bl>>>0;
    for(i=3;i>=0;i--)b.push((hi>>>(i*8))&255);for(i=3;i>=0;i--)b.push((lo>>>(i*8))&255);
    for(var j=0;j<b.length;j+=64){var w=new Array(64);
      for(i=0;i<16;i++)w[i]=(b[j+i*4]<<24)|(b[j+i*4+1]<<16)|(b[j+i*4+2]<<8)|b[j+i*4+3];
      for(i=16;i<64;i++){var s0=rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>>3),s1=rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)|0;}
      var a=H[0],q=H[1],c=H[2],d=H[3],e=H[4],f=H[5],g=H[6],h=H[7];
      for(i=0;i<64;i++){var S1=rr(e,6)^rr(e,11)^rr(e,25),ch=(e&f)^(~e&g),t1=(h+S1+ch+K[i]+w[i])|0,S0=rr(a,2)^rr(a,13)^rr(a,22),mj=(a&q)^(a&c)^(q&c),t2=(S0+mj)|0;h=g;g=f;f=e;e=(d+t1)|0;d=c;c=q;q=a;a=(t1+t2)|0;}
      H[0]=(H[0]+a)|0;H[1]=(H[1]+q)|0;H[2]=(H[2]+c)|0;H[3]=(H[3]+d)|0;H[4]=(H[4]+e)|0;H[5]=(H[5]+f)|0;H[6]=(H[6]+g)|0;H[7]=(H[7]+h)|0;}
    var o='';for(i=0;i<8;i++)o+=('00000000'+(H[i]>>>0).toString(16)).slice(-8);return o;
  }
  var _0xIG = _0xsh(_0xq(2)).slice(0, 12);
  setInterval(function () { if (_0xsh(_0xq(2)).slice(0, 12) !== _0xIG) { try { delete window.__shieldMaxState; } catch (e) {} } }, 2000);
  function _0xzero(_0xhex) { var n = 0; for (var i = 0; i < _0xhex.length; i++) { var v = parseInt(_0xhex[i], 16); if (v === 0) { n += 4; continue; } if (v < 2) n += 3; else if (v < 4) n += 2; else if (v < 8) n += 1; break; } return n; }
  function _0xmix(_0xfph, _0xsalt, _0xver) {
    var _0xs16 = BigInt('0x' + _0xsh(_0xfph + _0xsalt).slice(0, 16));
    var M = (1n << 64n) - 1n, _0xr;
    if (_0xver === 1) {
      _0xr = ((_0xs16 ^ 0x5A5A5A5An) * 0x9E3779B1n) & M;
      return ((_0xr << 13n) | (_0xr >> 51n)) & M;
    }
    _0xr = (((_0xs16 + 0x1337C0DEn) & M) * 0x85EBCA6Bn) & M;
    return ((_0xr >> 7n) | (_0xr << 57n)) & M;
  }
  function _0xcollect() {
    return { ua: navigator.userAgent, platform: navigator.platform,
             lang: (navigator.languages || [navigator.language]).join(','),
             screen: screen.width + 'x' + screen.height,
             tz: String(new Date().getTimezoneOffset()),
             depth: String(screen.colorDepth) };
  }
  function _0xauto() {
    if (navigator.webdriver) return true;
    if (window.__playwright || window.__pwInit || window.__selenium_unwrapped) return true;
    if (document.__cdc_QuoteContext || (window.chrome && window.chrome.cdc_adoQpoasdffa)) return true;
    try { null[0]; } catch (e) { if (e.stack && /puppeteer|playwright/i.test(e.stack)) return true; }
    return false;
  }
  function _0xrun() {
    if (_0xauto()) { document.getElementById('out').textContent = 'ERR unsupported'; return; }
    fetch(_0xq(0)).then(function (r) { return r.json(); }).then(function (ch) {
      var _0xf = _0xcollect();
      var _0xfph = _0xsh(_0xcanon(_0xf));
      var _0xs2 = _0xmix(_0xfph, ch.salt, ch.ver).toString();
      var _0xn = 0;
      while (_0xzero(_0xsh(ch.sid + ':' + ch.salt + ':' + _0xn + ':' + _0xs2)) < ch.difficulty) _0xn++;
      return fetch(_0xq(1), { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nonce: String(_0xn), fields: _0xf, salt: ch.salt,
          difficulty: ch.difficulty, ts: ch.ts, ver: ch.ver, sig: ch.sig }) });
    }).then(function (r) { return r.json(); }).then(function (d) {
      document.getElementById('out').textContent = d.secret_data ? 'OK ' + JSON.stringify(d) : 'ERR ' + JSON.stringify(d);
    }).catch(function (e) { document.getElementById('out').textContent = 'ERR ' + e; });
  }
  window.shieldMax = { run: _0xrun };
})();
