/* shield-lite sdk v1.2 — (c) ACME metrics. minified+light guard build */
(function () {
  var _0xa = ['UWwybQ==', 'OHNLMGVW', 'dzdmX3h6OQ==', 'L3ZlcmlmeQ==', 'L2NoYWxsZW5nZQ==', 'c2lk', 'dHM=', 'c2ln', 'c2VjcmV0X2RhdGE=', 'NmQxZjBiOWFjMg=='];
  var _0xd = function (i) { return typeof atob === 'function' ? atob(_0xa[i]) : ''; };
  // runtime key assembly (order matters; do not inline)
  var _0xk = [_0xd(2), _0xd(0), _0xd(1)].join('');
  var _0xpad = [];
  (function () { var h = _0xd(9); for (var i = 0; i < h.length; i += 2) _0xpad.push(parseInt(h.substr(i, 2), 16)); })();
  function _0xs(msgBytes) {
    var full = new Uint8Array(_0xpad.length + msgBytes.length);
    full.set(_0xpad); full.set(msgBytes, _0xpad.length);
    return crypto.subtle.importKey('raw', new TextEncoder().encode(_0xk),
      { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']).then(function (k) {
        return crypto.subtle.sign('HMAC', k, full);
      });
  }
  function _0xh(buf) { var v = new Uint8Array(buf), s = ''; for (var i = 0; i < v.length; i++) s += ('0' + v[i].toString(16)).slice(-2); return s; }
  function _0xrun() {
    if (navigator.webdriver) return;
    fetch(_0xd(4)).then(function (r) { return r.json(); }).then(function (ch) {
      return _0xs(new TextEncoder().encode(ch[_0xd(6)] + '|' + ch[_0xd(5)])).then(function (sig) {
        return fetch(_0xd(3), { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ts: ch[_0xd(6)], sig: _0xh(sig) }) });
      });
    }).then(function (r) { return r.json(); }).then(function (d) {
      var el = document.getElementById('out');
      if (d[_0xd(8)]) { el.textContent = 'OK ' + JSON.stringify(d); }
      else { el.textContent = 'ERR ' + JSON.stringify(d); }
    }).catch(function (e) { document.getElementById('out').textContent = 'ERR ' + e; });
  }
  window.shieldLite = { run: _0xrun };
})();
