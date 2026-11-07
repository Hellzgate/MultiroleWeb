/* StatusPanel — /api/status 를 카드/표로 표시 + 리포 즉시 갱신 */
window.MR = window.MR || {};

MR.statusPanel = {
  card: function (title, rows) {
    return '<div class="card"><h3>' + title + '</h3>' +
      rows.map(function (r) { return '<div class="kv"><b>' + r[0] + '</b><span>' + r[1] + '</span></div>'; }).join('') +
      '</div>';
  },

  load: async function () {
    var r = await MR.api('GET', '/api/status');
    if (r.status !== 200 || !r.data) return;
    var st = r.data;
    MR.header.apply(st);
    MR.$('statusTime').textContent = '갱신 ' + st.now;

    var clientRows = st.clients
      ? Object.keys(st.clients).map(function (k) { return ['포트 ' + k + ' 접속', st.clients[k] + '개']; })
      : [['접속', 'n/a (Linux 만)']];

    MR.$('statusGrid').innerHTML = [
      MR.statusPanel.card('프로세스', [
        ['상태', st.process.running ? '<span class="tag ok">실행 중</span>' : '<span class="tag err">중지</span>'],
        ['PID', st.process.pid || '—'],
        ['가동 시간', MR.dur(st.process.uptime)],
        ['재시작 횟수', st.process.restarts],
        ['마지막 종료 코드', st.process.lastExit === null ? '—' : st.process.lastExit]
      ]),
      MR.statusPanel.card('설정', [
        ['경로', MR.esc(st.config.path)],
        ['수정 시각', st.config.mtime || '—'],
        ['해시', st.config.sha256],
        ['반영 대기', st.config.pendingRestart ? '<span class="tag warn">재시작 필요</span>' : '<span class="tag ok">적용됨</span>'],
        ['오류', st.config.error ? '<span class="tag err">' + MR.esc(st.config.error) + '</span>' : '없음']
      ]),
      MR.statusPanel.card('접속 / 포트', clientRows.concat(st.ports.map(function (p) {
        return ['포트 ' + p.port, p.open ? '<span class="tag ok">LISTEN</span>' : '<span class="tag err">닫힘</span>'];
      }))),
      MR.statusPanel.card('리플레이 / 코어', [
        ['리플레이 수', st.replays.count],
        ['최근 파일', MR.esc(st.replays.latest || '—')],
        ['최근 시각', st.replays.latestTime || '—'],
        ['총 용량', MR.size(st.replays.bytes)],
        ['tmp 코어', st.cores.files.length ? MR.esc(st.cores.files[0]) : '없음']
      ])
    ].join('');

    MR.$('repoBody').innerHTML = st.repos.map(function (r) {
      return '<tr><td>' + MR.esc(r.name) + '</td><td><code>' + MR.esc(r.head || '—') + '</code></td>' +
        '<td>' + (r.fetched || '—') + '</td><td class="muted">' + MR.esc(r.path) + '</td>' +
        '<td><button class="sm" data-sync="' + MR.esc(r.name) + '">갱신</button></td></tr>';
    }).join('') || '<tr><td colspan="5" class="muted">리포가 없습니다.</td></tr>';

    MR.$('provBody').innerHTML = st.providers.map(function (p) {
      return '<tr><td>' + MR.esc(p.name) + '</td><td>' + p.files + '</td><td class="muted">' + MR.esc(p.repos.join(', ')) + '</td></tr>';
    }).join('') || '<tr><td colspan="3" class="muted">없음</td></tr>';
  },

  sync: async function (name) {
    var r = await MR.api('POST', '/api/sync', { name: name });
    if (r.status === 200) {
      MR.toast('ok', "'" + name + "' 갱신 요청 완료 (git pull)");
      setTimeout(MR.statusPanel.load, 2500);
    } else {
      MR.toast('err', '갱신 실패', (r.data && (r.data.error || r.data.message)) || []);
    }
  },

  bind: function () {
    MR.$('btnStatus').onclick = MR.statusPanel.load;
    MR.$('repoBody').addEventListener('click', function (ev) {
      var t = ev.target;
      if (t && t.dataset && t.dataset.sync) MR.statusPanel.sync(t.dataset.sync);
    });
  }
};
