/* BotPanel — 봇 목록: 실행 현황 · 덱 검색 · 방에 투입/중지 */
window.MR = window.MR || {};

MR.botPanel = {
  DATA: null,
  FILTER: '',
  MAN_FILTER: '',
  DECK: '',

  load: async function () {
    var r = await MR.api('GET', '/api/bots');
    if (r.status !== 200 || !r.data) {
      MR.$('botHint').textContent = '봇 상태를 읽지 못했습니다 (HTTP ' + r.status + ')';
      return;
    }
    MR.botPanel.DATA = r.data;
    MR.botPanel.render();
  },

  render: function () {
    var d = MR.botPanel.DATA;
    var hint = MR.$('botHint');
    if (!d.enabled) {
      hint.textContent = '봇 서비스가 꺼져 있습니다 (MR_BOT_URL 미설정)';
    } else if (d.error) {
      hint.textContent = '봇 서비스 연결 실패: ' + d.error;
    } else {
      hint.textContent = '실행 ' + d.running.length + ' / ' + d.max +
        ' · 덱 ' + d.decks.length + '개' + (d.windbot ? '' : ' · WindBot 준비 안 됨');
    }
    var nav = MR.$('navBots');
    if (nav) nav.textContent = '봇' + (d.running.length ? ' ' + d.running.length : '');
    MR.$('botDefaultDeck').textContent = (d.default && d.default.deck) || '—';
    MR.botPanel.renderRunning(d);
    MR.botPanel.renderRooms(d);
    MR.botPanel.renderDecks(d);
    MR.botPanel.renderManual(d);
  },

  /* 「봇 부르는 법」 표 — /api/bots 의 catalog(서버 덱 + 매뉴얼 이름/난이도) */
  renderManual: function (d) {
    var body = MR.$('botManBody');
    if (!body) return;
    var q = (MR.botPanel.MAN_FILTER || '').trim().toLowerCase();
    var rows = (d.catalog || []).filter(function (x) {
      return !q || x.deck.toLowerCase().indexOf(q) >= 0 || (x.name || '').toLowerCase().indexOf(q) >= 0;
    });
    body.innerHTML = rows.map(function (x) {
      var name = x.known ? MR.esc(x.name) : '<span class="muted">— (매뉴얼에 없음)</span>';
      return '<tr><td><code>' + MR.esc(x.deck) + '</code></td>' +
        '<td>' + name + '</td>' +
        '<td>' + MR.esc(x.difficulty || '—') + '</td>' +
        '<td><code>' + MR.esc(x.call) + '</code>' + (x.space ? ' <span class="tag">공백</span>' : '') + '</td></tr>';
    }).join('') || '<tr><td colspan="4" class="muted">해당하는 덱이 없습니다.</td></tr>';
    MR.$('botManCount').textContent = rows.length + ' / ' + (d.catalog || []).length + '개';
  },

  renderRunning: function (d) {
    var body = MR.$('botRunBody');
    MR.$('botRunCount').textContent = d.running.length ? '(' + d.running.length + ')' : '';
    body.innerHTML = d.running.map(function (b) {
      var log = (b.log || '').split('/').pop();
      return '<tr><td>#' + MR.esc(b.room) + '</td>' +
        '<td>' + MR.esc(b.deck) + '</td>' +
        '<td>' + MR.esc(b.name) + '</td>' +
        '<td>' + MR.esc(b.pid || '—') + '</td>' +
        '<td>' + MR.esc(b.uptimeText) + '</td>' +
        '<td>' + (b.alive ? '<span class="tag ok">실행</span>' : '<span class="tag err">종료</span>') + '</td>' +
        '<td class="muted" style="font-size:11px">' + MR.esc(log) + '</td>' +
        '<td><button class="sm" data-stop="' + MR.esc(b.room) + '">중지</button></td></tr>';
    }).join('') || '<tr><td colspan="8" class="muted">실행 중인 봇이 없습니다.</td></tr>';
    Array.prototype.forEach.call(body.querySelectorAll('button[data-stop]'), function (btn) {
      btn.onclick = function () { MR.botPanel.stop(Number(btn.getAttribute('data-stop'))); };
    });
  },

  renderRooms: function (d) {
    var sel = MR.$('botRoom');
    var keep = sel.value;
    sel.innerHTML = '';
    if (!d.rooms.length) {
      var o0 = document.createElement('option');
      o0.value = '';
      o0.textContent = '(열려 있는 방이 없습니다 — 게임에서 방을 먼저 만드세요)';
      sel.appendChild(o0);
      return;
    }
    d.rooms.forEach(function (r) {
      var op = document.createElement('option');
      op.value = String(r.id);
      var use = (r.users || []).length;
      op.textContent = '#' + r.id + ' · ' + (r.notes || '(이름 없음)') +
        ' · ' + use + '명 · ' + (r.started ? '진행 중' : '대기') +
        (r.bot ? ' · 봇:' + r.bot : '');
      if (!r.free) op.style.color = '#8b93a5';
      sel.appendChild(op);
    });
    var pick = d.rooms.filter(function (r) { return r.free; })[0];
    if (keep && d.rooms.some(function (r) { return String(r.id) === keep; })) sel.value = keep;
    else if (pick) sel.value = String(pick.id);
  },

  renderDecks: function (d) {
    var list = MR.$('botDeck');
    if (!list) return;
    var q = MR.botPanel.FILTER.trim().toLowerCase();
    var rows = d.decks.filter(function (x) {
      return !q || x.name.toLowerCase().indexOf(q) >= 0;
    });
    var want = MR.botPanel.DECK || (d.default && d.default.deck) || '';
    var has = rows.some(function (x) { return x.name === want; });
    if (!has && rows.length) want = rows[0].name;
    MR.botPanel.DECK = want;
    var cnt = MR.$('botDeckCount');
    if (cnt) cnt.textContent = rows.length + ' / ' + d.decks.length + '개';
    if (!rows.length) {
      list.innerHTML = '<li class="deck-empty">해당하는 덱이 없습니다</li>';
      return;
    }
    list.innerHTML = rows.map(function (x) {
      var meta = [];
      if (x.running) meta.push('실행 ' + x.running);
      if (x.missing) meta.push('파일 없음');
      var sel = (x.name === want);
      return '<li class="deck-row' + (sel ? ' sel' : '') + '" role="option" aria-selected="' + sel +
        '" data-deck="' + MR.esc(x.name) + '">' +
        '<span class="name">' + MR.esc(x.name) + '</span>' +
        (meta.length ? '<span class="meta">' + MR.esc(meta.join(' · ')) + '</span>' : '') +
        '</li>';
    }).join('');
  },

  start: async function () {
    var d = MR.botPanel.DATA || {};
    var rid = Number(MR.$('botRoom').value || 0);
    var deck = MR.botPanel.DECK || (d.default && d.default.deck) || '';
    if (!rid) { MR.$('botHint').textContent = '방을 먼저 고르세요 — 게임에서 방을 만들어야 목록에 뜹니다.'; return; }
    if (!deck) { MR.$('botHint').textContent = '덱을 고르세요.'; return; }
    MR.$('btnBotStart').disabled = true;
    var r = await MR.api('POST', '/api/bot/start', { roomId: rid, deck: deck });
    MR.$('btnBotStart').disabled = false;
    var ok = r.status === 200 && r.data && !r.data.error;
    MR.$('botHint').textContent = ok
      ? ('방 ' + rid + ' 에 ' + (r.data.deck || deck) + ' 투입' +
         (r.data.already ? ' (이미 있음)' : ' — 2~3초 뒤 목록에 표시'))
      : ('투입 실패: ' + JSON.stringify((r.data && r.data.error) || r.status));
    if (ok) setTimeout(function () { MR.botPanel.load(); }, 2500);
  },

  stop: async function (roomId) {
    var r = await MR.api('POST', '/api/bot/stop', { roomId: roomId });
    MR.$('botHint').textContent = (r.status === 200)
      ? ('방 ' + roomId + ' 봇 중지') : ('중지 실패 HTTP ' + r.status);
    setTimeout(function () { MR.botPanel.load(); }, 1200);
  },

  stopAll: async function () {
    MR.confirmBox('봇 전체 중지', '실행 중인 봇을 모두 종료합니다. 진행 중인 듀얼이 있으면 그 판은 무효가 됩니다.',
      '전체 중지', async function () {
        var r = await MR.api('POST', '/api/bot/stopall', {});
        MR.$('botHint').textContent = (r.status === 200)
          ? ('전체 중지: ' + ((r.data && r.data.stopped || []).join(', ') || '없음'))
          : ('전체 중지 실패 HTTP ' + r.status);
        MR.botPanel.load();
      });
  },

  bind: function () {
    MR.$('btnBotRefresh').onclick = function () { MR.botPanel.load(); };
    MR.$('btnBotStart').onclick = function () { MR.botPanel.start(); };
    MR.$('btnBotStopAll').onclick = function () { MR.botPanel.stopAll(); };
    MR.$('botDeckSearch').oninput = function (e) {
      MR.botPanel.FILTER = e.target.value;
      if (MR.botPanel.DATA) MR.botPanel.renderDecks(MR.botPanel.DATA);
    };
    var list = MR.$('botDeck');
    if (list) {
      list.onclick = function (e) {
        var row = e.target.closest ? e.target.closest('.deck-row') : null;
        if (!row) return;
        MR.botPanel.DECK = row.getAttribute('data-deck') || '';
        Array.prototype.forEach.call(list.querySelectorAll('.deck-row.sel'), function (r) {
          r.classList.remove('sel');
          r.setAttribute('aria-selected', 'false');
        });
        row.classList.add('sel');
        row.setAttribute('aria-selected', 'true');
      };
      list.ondblclick = function (e) {
        if (e.target.closest && e.target.closest('.deck-row')) MR.botPanel.start();
      };
    }
    MR.$('botManFilter').oninput = function (e) {
      MR.botPanel.MAN_FILTER = e.target.value;
      if (MR.botPanel.DATA) MR.botPanel.renderManual(MR.botPanel.DATA);
    };
  }
};
