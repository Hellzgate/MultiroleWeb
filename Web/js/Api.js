/* Api — fetch 래퍼(쿠키 동일 출처) + JSON + 일시적 실패 재시도 */
window.MR = window.MR || {};

MR.sleep = function (ms) {
  return new Promise(function (r) { setTimeout(r, ms); });
};

/* GET 은 일시적 5xx/네트워크 오류를 2회까지 재시도한다.
   (로컬 HTTP 프록시가 동시 요청 중 일부를 502 로 떨어뜨리는 사례가 실측됨)
   POST/PUT 은 중복 실행 위험이 있어 재시도하지 않는다. */
MR.api = async function (method, path, body) {
  var attempts = (method === 'GET') ? 3 : 1;
  var lastErr = null;
  for (var i = 0; i < attempts; i++) {
    var opt = { method: method, headers: {}, credentials: 'same-origin' };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    try {
      var res = await fetch(path, opt);
      if (res.status >= 500 && i < attempts - 1) {
        await MR.sleep(200 * (i + 1));
        continue;
      }
      var data = null;
      try { data = await res.json(); } catch (e) { data = null; }
      return { status: res.status, data: data };
    } catch (e) {
      lastErr = e;
      if (i < attempts - 1) await MR.sleep(200 * (i + 1));
    }
  }
  return { status: 0, data: null, error: lastErr };
};
