/* StatusPanel — /api/status (카드/표) + 저장소 갱신([전체 갱신] / 리포별 [갱신]) + 결과 표시 */
window.MR = window.MR || {};

MR.statusPanel = {
  _fresh: false,          /* 방금 갱신한 결과를 보여준 상태(로드 시 덮어쓰지 않는다) */

  card: function (title, rows) {
    return '<div class="card"><h3>' + title + '</h3>' +
      rows.map(function (r) { return '<div class="kv"><b>' + r[0] + '</b><span>' + r[1] + '</span></div>'; }).join('') +
      '</div>';
  },

  /* 상태 탭 안의 배너 (cfgBanner 는 설정 탭에 있어서 따로 둔다) */
  banner: function (kind, msg, list) {
    var b = MR.$('syncBanner');
    if (!b) return;
    b.className = 'banner ' + kind;
    b.classList.remove('hidden');
    b.innerHTML = '<div><b>' + MR.esc(msg) + '</b>' +
      (list && list.length ? '<ul class="errlist">' +
        list.map(function (x) { return '<li>' + MR.esc(x) + '</li>'; }).join('') + '</ul>' : '') +
      '</div>';
  },

  secs: function (ms) { return ((ms || 0) / 1000).toFixed(1) + '초'; },

  /* 표의 '결과' 칸 */
  resultTag: function (r) {
    if (!r) return '<span class="muted">—</span>';
    if (r.ok === false) return '<span class="tag err">실패</span>';
    if (r.changed) {
      var n = r.commitCount || r.fileCount || 0;
      return '<span class="tag warn">+' + n + (r.commitCount ? ' 커밋' : ' 파일') + '</span>';
    }
    return '<span class="tag ok">변경 없음</span>';
  },

  /* 갱신 결과 카드 — repo 별 카드 + 커밋/파일/로그 */
  renderResults: function (results, summary, title) {
    var box = MR.$('syncResult');
    var card = MR.$('syncCard');
    if (!box || !card) return;
    if (!results || !results.length) { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    MR.$('syncSummary').textContent = (title || '') +
      (summary ? ' · ' + summary.total + '개 중 ' + summary.changed + '개 변경 · 실패 ' +
        summary.failed + ' · ' + MR.statusPanel.secs(summary.durationMs) : '');

    box.innerHTML = results.map(function (r) {
      var failed = r.ok === false;
      var head = '<div class="sync-head"><b>' + MR.esc(r.name) + '</b>' +
        (failed ? '<span class="tag err">실패</span>'
                : (r.changed ? '<span class="tag warn">갱신됨</span>' : '<span class="tag ok">변경 없음</span>')) +
        (r.changed && r.from ? ' <code>' + MR.esc(r.from) + ' → ' + MR.esc(r.to || '?') + '</code>'
                             : (r.head ? ' <code>' + MR.esc(r.head) + '</code>' : '')) +
        ' <span class="muted">' + (r.commitCount || 0) + ' 커밋 · ' + (r.fileCount || 0) + ' 파일 · ' +
        MR.statusPanel.secs(r.durationMs) + '</span></div>';

      var sub = '<div class="sync-sub">' + MR.esc(r.at || '') + '</div>';
      if (failed) {
        sub += '<div class="sync-sub bad">' + MR.esc(r.error || '실패') + '</div>';
      }

      var commits = '';
      if (r.commits && r.commits.length) {
        commits = '<ul class="sync-list">' + r.commits.map(function (c) {
          return '<li><code>' + MR.esc(c.hash) + '</code> ' + MR.esc(c.subject) + '</li>';
        }).join('') +
          (r.commitCount > r.commits.length
            ? '<li class="muted">… 외 ' + (r.commitCount - r.commits.length) + '개 커밋</li>' : '') +
          '</ul>';
      }

      var files = '';
      if (r.files && r.files.length) {
        var shown = r.files.slice(0, 8);
        files = '<ul class="sync-list">' + shown.map(function (f) {
          return '<li><span class="muted">' + MR.esc(f.status) + '</span> ' + MR.esc(f.path) + '</li>';
        }).join('') +
          (r.fileCount > shown.length
            ? '<li class="muted">… 외 ' + (r.fileCount - shown.length) + '개 파일</li>' : '') +
          '</ul>';
      }

      var logLines = '';
      if (r.log && r.log.length) {
        logLines = '<pre class="sync-log">' + r.log.map(function (x) {
          return (x.error ? '! ' : '· ') + x.text;
        }).map(MR.esc).join('\n') + '</pre>';
      }

      return '<div class="sync-item' + (failed ? ' err' : '') + '">' + head + sub + commits + files + logLines + '</div>';
    }).join('');
  },

  /* /api/status 의 마지막 전체 갱신 기록을 요약 카드로 */
  renderLastAll: function (lastAll) {
    if (!lastAll || !lastAll.repos) return;
    var asResults = lastAll.repos.map(function (r) {
      return { name: r.name, ok: r.ok, changed: r.changed, from: r.from, to: r.to,
               head: r.to, commitCount: r.commitCount, fileCount: r.fileCount,
               error: r.error, at: lastAll.at, durationMs: 0, commits: [], files: [], log: [] };
    });
    MR.statusPanel.renderResults(asResults,
      { total: lastAll.total, changed: lastAll.changed, failed: lastAll.failed, durationMs: 0 },
      '마지막 전체 갱신 ' + (lastAll.at || ''));
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

    MR.$('repoBody').innerHTML = (st.repos || []).map(function (r) {
      var last = r.lastSync;
      var when = last ? MR.esc(last.at || '') : (r.fetched || '—');
      var title = last ? ('갱신 ' + (last.at || '') + (last.error ? ' · ' + last.error : '') +
                          (last.changed && last.from ? ' · ' + last.from + ' → ' + last.to : ''))
                       : '이 패널에서 아직 갱신하지 않았습니다(fetch 기록만 있음)';
      return '<tr><td>' + MR.esc(r.name) + '</td><td><code>' + MR.esc(r.head || '—') + '</code></td>' +
        '<td title="' + MR.esc(title) + '">' + when + '</td>' +
        '<td>' + MR.statusPanel.resultTag(last) + '</td>' +
        '<td class="muted">' + MR.esc(r.path) + '</td>' +
        '<td><button class="sm" data-sync="' + MR.esc(r.name) + '">갱신</button></td></tr>';
    }).join('') || '<tr><td colspan="6" class="muted">리포가 없습니다.</td></tr>';

    MR.$('provBody').innerHTML = st.providers.map(function (p) {
      return '<tr><td>' + MR.esc(p.name) + '</td><td>' + p.files + '</td><td class="muted">' + MR.esc(p.repos.join(', ')) + '</td></tr>';
    }).join('') || '<tr><td colspan="3" class="muted">없음</td></tr>';

    if (!MR.statusPanel._fresh && st.sync && st.sync.lastAll) {
      MR.statusPanel.renderLastAll(st.sync.lastAll);
    }
  },

  /* name 이 없으면 전체 갱신 */
  sync: async function (name) {
    var all = !name;
    var label = all ? '전체 갱신' : "'" + name + "' 갱신";
    var btnAll = MR.$('btnSyncAll');
    var buttons = document.querySelectorAll('#repoBody button[data-sync]');
    if (btnAll) { btnAll.disabled = true; btnAll.textContent = '갱신 중…'; }
    for (var i = 0; i < buttons.length; i++) buttons[i].disabled = true;
    MR.statusPanel.banner('info', label + ' 중…', ['웹훅으로 git fetch + reset 을 실행합니다. 저장소 크기에 따라 수십 초 걸릴 수 있습니다.']);

    var r = await MR.api('POST', '/api/sync', all ? {} : { name: name });

    if (btnAll) { btnAll.disabled = false; btnAll.textContent = '전체 갱신'; }
    for (var j = 0; j < buttons.length; j++) buttons[j].disabled = false;

    if (r.status !== 200 || !r.data) {
      MR.statusPanel.banner('err', label + ' 실패',
        [(r.data && (r.data.error || r.data.message)) || ('HTTP ' + r.status + ' — 네트워크/인증을 확인하세요')]);
      MR.statusPanel.load();
      return;
    }

    var s = r.data.summary || {};
    var results = r.data.results || [];
    MR.statusPanel._fresh = true;
    MR.statusPanel.renderResults(results, s, label + ' · ' + (s.at || ''));

    if (s.failed) {
      MR.statusPanel.banner('err', label + ' — ' + s.failed + '개 실패',
        results.filter(function (x) { return x.ok === false; })
               .map(function (x) { return x.name + ': ' + (x.error || '실패') + ' (아래 결과·로그 탭 참고)'; }));
    } else if (s.changed) {
      MR.statusPanel.banner('ok', s.changed + '개 저장소가 갱신되었습니다 (' + MR.statusPanel.secs(s.durationMs) + ')',
        results.filter(function (x) { return x.changed; })
               .map(function (x) { return x.name + ': ' + x.from + ' → ' + x.to +
                    ' (+' + x.commitCount + ' 커밋, ' + x.fileCount + ' 파일)'; }));
    } else {
      MR.statusPanel.banner('info', '변경 없음 — 이미 최신입니다 (' + MR.statusPanel.secs(s.durationMs) + ')', []);
    }
    MR.statusPanel.load();
  },

  bind: function () {
    MR.$('btnStatus').onclick = MR.statusPanel.load;
    var all = MR.$('btnSyncAll');
    if (all) all.onclick = function () { MR.statusPanel.sync(null); };
    MR.$('repoBody').addEventListener('click', function (ev) {
      var t = ev.target;
      if (t && t.dataset && t.dataset.sync) MR.statusPanel.sync(t.dataset.sync);
    });
  }
};
