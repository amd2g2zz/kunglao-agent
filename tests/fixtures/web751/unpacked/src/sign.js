// sign.js — signature assembly module (post-recovery form)
function digest(x) {
  for (var h = "", i = 0; i < x.length; i++) h = (h << 5) - h + x.charCodeAt(i) | 0;
  return ("00000000" + (h >>> 0).toString(16)).slice(-8);
}

function buildParams(params) {
  return Object.keys(params).sort().map(function (k) { return k + "=" + params[k]; }).join("&");
}

function assembleBase(base, secret) { return base + "#" + secret + "#v1"; }

function buildSignature(payload, secret) { return digest(assembleBase(buildParams(payload), secret)); }
