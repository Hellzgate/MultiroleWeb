/* Util — DOM/표시/모달 공용 헬퍼 */
window.MR = window.MR || {};

MR.$ = function (id) { return document.getElementById(id); };

MR.esc = function (s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
};

MR.dur = function (sec) {
  if (!sec && sec !== 0) return '—';
  var d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600),
      m = Math.floor(sec % 3600 / 60), s = sec % 60;
  if (d) return d + '일 ' + h + '시간';
  if (h) return h + '시간 ' + m + '분';
  if (m) return m + '분 ' + s + '초';
  return s + '초';
};

MR.size = function (n) {
  if (n === null || n === undefined) return '—';
  var u = ['B', 'KB', 'MB', 'GB'], i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : n) + ' ' + u[i];
};

/* 경로("repos.0.webhookPort") 기반 get/set */
MR.setPath = function (obj, path, val) {
  var parts = path.split('.'), cur = obj;
  for (var i = 0; i < parts.length - 1; i++) cur = cur[parts[i]];
  cur[parts[parts.length - 1]] = val;
};
MR.getPath = function (obj, path) {
  return path.split('.').reduce(function (a, k) { return (a == null ? undefined : a[k]); }, obj);
};

/* 설정 화면 상단 배너 */
MR.toast = function (kind, msg, list) {
  var b = MR.$('cfgBanner');
  b.className = 'banner ' + kind;
  b.classList.remove('hidden');
  b.innerHTML = '<div><b>' + MR.esc(msg) + '</b>' +
    (list && list.length ? '<ul class="errlist">' +
      list.map(function (x) { return '<li>' + MR.esc(x) + '</li>'; }).join('') + '</ul>' : '') +
    '</div>';
};

/* 확인 모달 */
MR._modalOk = null;
MR.confirmBox = function (title, html, okLabel, cb) {
  MR.$('mTitle').textContent = title;
  MR.$('mBody').innerHTML = '<p>' + html + '</p>';
  MR.$('mOk').textContent = okLabel || '확인';
  MR._modalOk = cb;
  MR.$('modal').classList.add('on');
};

MR.bindModal = function () {
  MR.$('mCancel').onclick = function () {
    MR.$('modal').classList.remove('on');
    MR._modalOk = null;
  };
  MR.$('mOk').onclick = async function () {
    MR.$('modal').classList.remove('on');
    var fn = MR._modalOk;
    MR._modalOk = null;
    if (fn) await fn();
  };
};
