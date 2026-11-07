/* AuthPanel — 계정(auth.json) 백업 목록/수동 백업 */
window.MR = window.MR || {};

MR.authPanel = {
  load: async function () {
    var body = MR.$('authBackupBody');
    if (!body) return;
    var r = await MR.api('GET', '/api/auth/backups');
    if (r.status !== 200 || !r.data) {
      MR.$('authBackupHint').textContent = '백업 목록 조회 실패 (' + r.status + ')';
      return;
    }
    var d = r.data;
    MR.$('authBackupHint').textContent = (d.total || 0) + '개 · ' + (d.dir || '') +
      ' · 보관 ' + (d.keep || 0) + '개 / ' + (d.hours || 0) + '시간 주기' +
      (d.last ? ' · 마지막 ' + d.last : '');
    body.innerHTML = (d.items || []).map(function (x) {
      return '<tr><td><code>' + MR.esc(x.name) + '</code></td><td>' + MR.size(x.bytes) +
        '</td><td class="muted">' + MR.esc(x.at) + '</td></tr>';
    }).join('') || '<tr><td colspan="3" class="muted">백업이 없습니다.</td></tr>';
  },

  backup: async function () {
    var r = await MR.api('POST', '/api/auth/backup', {});
    var ok = r.status === 200 && r.data && r.data.ok;
    MR.$('authBackupHint').textContent = ok
      ? ('백업 완료: ' + r.data.name)
      : ('백업 실패: ' + JSON.stringify((r.data && r.data.error) || r.status));
    MR.authPanel.load();
  },

  bind: function () {
    var b = MR.$('btnAuthBackup');
    if (b) b.onclick = function () { MR.authPanel.backup(); };
    var r = MR.$('btnAuthBackupReload');
    if (r) r.onclick = function () { MR.authPanel.load(); };
  }
};
