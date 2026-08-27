// api.js — request entry point module (post-recovery form)
function sendRequest(path, payload) {
  var sign = buildSignature(payload, "s3cr3t");
  var url = "https://api.example.com" + path + "?sign=" + encodeURIComponent(sign);
  return fetch(url);
}
