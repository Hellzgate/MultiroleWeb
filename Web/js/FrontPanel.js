/* FrontPanel — LAN 방 기본값(머큐리 프론트) 편집 + 금지/제한 목록 + 도움말 */
window.MR = window.MR || {};

MR.frontPanel = {
  FIELDS: [
    { key: 'default_room', label: '기본 방 이름', type: 'text', hint: '비밀번호 칸이 비었을 때' },
    { key: 'lp', label: '시작 LP', type: 'number', min: 100, max: 40000 },
    { key: 'hand', label: '시작 패', type: 'number', min: 1, max: 10 },
    { key: 'draw', label: '턴당 드로우', type: 'number', min: 1, max: 10 },
    { key: 'time', label: '제한 시간(초)', type: 'number', min: 30, max: 6000 },
    { key: 'best', label: '승부 방식', type: 'select', options: [['1', '단판'], ['3', '3판 2선승']] },
    { key: 'mr', label: '마스터 룰', type: 'select', hint: '기본 5 = 최신(2020)',
      options: [['5', 'MR5 (2020, 최신)'], ['4', 'MR4'], ['3', 'MR3'], ['2', 'MR2'], ['1', 'MR1'], ['0', '표시 안 함']] },
    { key: 'main_min', label: '메인 덱 최소', type: 'number', min: 0, max: 60 },
    { key: 'main_max', label: '메인 덱 최대', type: 'number', min: 0, max: 60 },
    { key: 'extra_max', label: '엑스트라 최대', type: 'number', min: 0, max: 15 },
    { key: 'side_max', label: '사이드 최대', type: 'number', min: 0, max: 15 },
    { key: 'mode', label: '허용 카드', type: 'select',
      options: [['ocg', 'OCG'], ['tcg', 'TCG'], ['both', 'OCG + TCG'], ['pre', 'OCG + TCG + 프리릴리즈'], ['any', '사용자 정의']] },
    { key: 'tag', label: '태그 듀얼', type: 'select', options: [['0', '1:1'], ['1', '2:2']] }
  ],

  MODEL: {},
  BANLISTS: [],

  field: function (f, room) {
    var row = document.createElement('div');
    row.className = 'row';
    var lab = document.createElement('label');
    lab.textContent = f.label;
    if (f.hint) lab.title = f.hint;   /* 라벨에 붙이면 줄바꿈으로 행이 흐트러진다 → 툴팁으로 */
    var wrap = document.createElement('div');
    var el;
    if (f.type === 'select') {
      el = document.createElement('select');
      f.options.forEach(function (o) {
        var op = document.createElement('option');
        op.value = o[0];
        op.textContent = o[1];
        el.appendChild(op);
      });
      el.value = String(room[f.key] === undefined ? f.options[0][0] : room[f.key]);
      el.onchange = function () { MR.frontPanel.MODEL[f.key] = el.value; };
    } else if (f.type === 'check') {
      var lbl = document.createElement('label');
      lbl.className = 'chk';
      el = document.createElement('input');
      el.type = 'checkbox';
      el.checked = !!Number(room[f.key]);
      el.onchange = function () {
        MR.frontPanel.MODEL[f.key] = el.checked ? 1 : 0;
        lbl.lastChild.textContent = el.checked ? '켜짐 (검사 안 함)' : '꺼짐 (서버가 검사)';
      };
      lbl.appendChild(el);
      lbl.appendChild(document.createTextNode(Number(room[f.key]) ? '켜짐 (검사 안 함)' : '꺼짐 (서버가 검사)'));
      wrap.appendChild(lbl);
      row.appendChild(lab);
      row.appendChild(wrap);
      return row;
    } else {
      el = document.createElement('input');
      el.type = f.type;
      if (f.min !== undefined) el.min = f.min;
      if (f.max !== undefined) el.max = f.max;
      el.value = room[f.key] === undefined ? '' : room[f.key];
      el.oninput = function () {
        MR.frontPanel.MODEL[f.key] = (f.type === 'number')
          ? (el.value === '' ? 0 : Number(el.value))
          : el.value;
      };
    }
    el.id = 'front_' + f.key;
    wrap.appendChild(el);
    row.appendChild(lab);
    row.appendChild(wrap);
    return row;
  },

  banlistRow: function (room) {
    var row = document.createElement('div');
    row.className = 'row';
    var lab = document.createElement('label');
    lab.textContent = '금지/제한 목록';
    lab.title = '방을 만들 때 이 목록으로 금지/제한을 적용합니다';
    var wrap = document.createElement('div');
    var sel = document.createElement('select');
    sel.id = 'front_banlist';
    var opt0 = document.createElement('option');
    opt0.value = '';
    opt0.textContent = '(사용 안 함 — N/A)';
    sel.appendChild(opt0);
    MR.frontPanel.BANLISTS.forEach(function (b) {
      var op = document.createElement('option');
      op.value = b.selector;
      op.textContent = b.section + '  [' + b.file + ']  (' + b.cards + '장, ' +
        ('00000000' + (b.hash >>> 0).toString(16)).slice(-8) + ')';
      sel.appendChild(op);
    });
    var cur = room.banlist || '';
    sel.value = cur;
    if (sel.value !== cur) {              // 저장된 값이 목록에 없으면 표시용으로 추가
      var op2 = document.createElement('option');
      op2.value = cur;
      op2.textContent = cur + ' (파일 없음?)';
      sel.appendChild(op2);
      sel.value = cur;
    }
    sel.onchange = function () { MR.frontPanel.MODEL.banlist = sel.value; };
    wrap.appendChild(sel);
    row.appendChild(lab);
    row.appendChild(wrap);
    return row;
  },

  render: function (data) {
    var room = data.room || {};
    MR.frontPanel.BANLISTS = data.banlists || [];
    /* MODEL 을 현재값으로 먼저 채운다 → 저장(PUT)이 항상 전체 값을 보내므로
       한 항목만 바꿔도 나머지 설정이 기본값으로 되돌아가지 않는다. */
    var model = {};
    MR.frontPanel.FIELDS.forEach(function (f) {
      var v = room[f.key];
      model[f.key] = (f.type === 'number') ? Number(v === undefined ? 0 : v) : v;
    });
    model.banlist = room.banlist || '';
    model.nocheck = Number(room.nocheck);
    MR.frontPanel.MODEL = model;
    var form = MR.$('frontForm');
    form.innerHTML = '';
    MR.frontPanel.FIELDS.forEach(function (f) {
      form.appendChild(MR.frontPanel.field(f, room));
    });
    form.appendChild(MR.frontPanel.banlistRow(room));
    var nocheck = { key: 'nocheck', label: '덱 확인하지 않기', hint: '커스텀 카드/프리릴리즈를 쓰려면 켜 둔다', type: 'check' };
    form.appendChild(MR.frontPanel.field(nocheck, room));
  },

  load: async function () {
    var r = await MR.api('GET', '/api/front');
    if (r.status !== 200 || !r.data) {
      MR.$('frontHint').textContent = '불러오기 실패 (' + r.status + ')';
      return;
    }
    MR.frontPanel.render(r.data);
    var hint = (r.data.enabled ? '프론트 :' + r.data.frontPort + ' ' : '프론트 꺼짐 ') +
      '· 금지목록 ' + (r.data.banlists || []).length + '개 · 파일 ' + (r.data.path || '');
    var b = await MR.api('GET', '/api/bot');
    if (b.status === 200 && b.data) {
      if (!b.data.enabled) {
        hint += ' · 봇 꺼짐';
      } else if (b.data.error) {
        hint += ' · 봇 서비스 연결 실패';
      } else {
        var s = b.data.status || {};
        var run = (s.bots || []).length;
        hint += ' · 봇 ' + run + '/' + (s.max || 0) + ' 실행 중 (덱 ' + (s.decks || 0) + '개)';
      }
    }
    MR.$('frontHint').textContent = hint;
  },

  save: async function () {
    var body = { room: Object.assign({}, MR.frontPanel.MODEL) };
    var r = await MR.api('PUT', '/api/front', body);
    if (r.status === 200 && r.data && r.data.ok) {
      MR.frontPanel.reload();
      MR.$('frontHint').textContent = '적용됨 (즉시 반영) · 금지목록 해시 0x' +
        ('00000000' + ((r.data.banlistHash >>> 0) || 0).toString(16)).slice(-8);
    } else {
      var msg = (r.data && (r.data.error || r.data.message)) || ('HTTP ' + r.status);
      MR.$('frontHint').textContent = '저장 실패: ' + JSON.stringify(msg);
    }
  },

  reload: async function () {
    var r = await MR.api('GET', '/api/front');
    if (r.status === 200 && r.data) MR.frontPanel.render(r.data);
  },


  bind: function () {
    /* 도움말의 서버 주소는 보고 있는 주소로 채운다(저장소에는 자리표시자만) */
    var addr = MR.$('frontAddr');
    if (addr && location.hostname) addr.textContent = location.hostname;
    MR.$('btnFrontSave').onclick = function () { MR.frontPanel.save(); };
    MR.$('btnFrontReload').onclick = function () { MR.frontPanel.load(); };
    var rr = MR.$('btnRoomRefresh');
    if (rr) rr.onclick = function () { MR.frontPanel.loadRooms(); };
    var ar = MR.$('btnAccessReload');
    if (ar) ar.onclick = function () { MR.frontPanel.loadAccess(); };
  }
};

/* ---------------------------------------------------------------- *
 * 현재 방 목록 + 봇 즉시 투입
 * ---------------------------------------------------------------- */
MR.frontPanel.loadRooms = async function () {
  var r = await MR.api('GET', '/api/rooms');
  var body = MR.$('roomBotBody');
  if (!body) return;
  body.innerHTML = '';
  if (r.status !== 200 || !r.data) {
    MR.$('roomBotHint').textContent = '방 목록 조회 실패 (' + r.status + ')';
    return;
  }
  var rooms = r.data.rooms || [];
  var g = r.data.ghost || {};
  var ghosts = rooms.filter(function (x) { return x.ghost; }).length;
  MR.$('roomBotHint').textContent = rooms.length + '개 방' +
    (ghosts ? ' · 유령 ' + ghosts + '개(자동 정리 ' + (g.enabled ? 'ON' : 'OFF') + ')' : '');
  rooms.forEach(function (room) {
    var tr = document.createElement('tr');
    tr.innerHTML = '<td>' + MR.esc(room.id) + '</td>' +
      '<td>' + MR.esc(room.notes || '(이름 없음)') + '</td>' +
      '<td>' + MR.esc((room.users || []).join(', ')) + '</td>' +
      '<td class="muted" style="font-size:11.5px">' + MR.esc((room.ips || []).join(', ') || '—') + '</td>' +
      '<td>' + (room.started ? '진행 중' : '대기') +
      (room.ghost ? ' <span class="tag err">유령</span>' : '') + '</td>';
    var tdDeck = document.createElement('td');
    var inp = document.createElement('input');
    inp.type = 'text';
    inp.value = 'raisemoon';
    inp.style.minWidth = '120px';
    tdDeck.appendChild(inp);
    tr.appendChild(tdDeck);
    var tdBtn = document.createElement('td');
    var b1 = document.createElement('button');
    b1.textContent = '봇 투입';
    b1.className = 'sm';
    b1.onclick = function () { MR.frontPanel.botStart(room.id, inp.value); };
    var b2 = document.createElement('button');
    b2.textContent = '중지';
    b2.className = 'sm';
    b2.style.marginLeft = '6px';
    b2.onclick = function () { MR.frontPanel.botStop(room.id); };
    var b3 = document.createElement('button');
    b3.textContent = '방 닫기';
    b3.className = 'sm danger';
    b3.style.marginLeft = '6px';
    b3.title = '남은 세션을 끊고 봇을 중지해 방을 닫습니다';
    b3.onclick = function () {
      MR.confirmBox('방 닫기', '방 ' + room.id + ' 의 세션을 끊고 봇을 중지합니다. 진행 중인 듀얼이면 그 판이 끊깁니다.',
        '방 닫기', function () { MR.frontPanel.roomClose(room.id); });
    };
    tdBtn.appendChild(b1);
    tdBtn.appendChild(b2);
    tdBtn.appendChild(b3);
    tr.appendChild(tdBtn);
    body.appendChild(tr);
  });
};

MR.frontPanel.botStart = async function (roomId, deck) {
  var r = await MR.api('POST', '/api/bot/start', { roomId: roomId, deck: deck });
  var ok = r.status === 200 && r.data && !r.data.error;
  MR.$('roomBotHint').textContent = ok
    ? ('방 ' + roomId + ' 에 ' + (r.data.deck || deck) + ' 투입' + (r.data.already ? ' (이미 있음)' : ''))
    : ('투입 실패: ' + JSON.stringify((r.data && r.data.error) || r.status));
  MR.frontPanel.loadRooms();
};

MR.frontPanel.roomClose = async function (roomId) {
  var r = await MR.api('POST', '/api/rooms/close', { roomId: roomId });
  var res = (r.data && r.data.result) || {};
  MR.$('roomBotHint').textContent = (r.status === 200)
    ? ('방 ' + roomId + ' 닫기 요청 — 세션 ' + (res.kicked || 0) + '개 종료 · 봇 ' + (res.stopped ? '중지' : '없음'))
    : ('닫기 실패 HTTP ' + r.status);
  setTimeout(function () { MR.frontPanel.loadRooms(); }, 1500);
};

MR.frontPanel.botStop = async function (roomId) {
  var r = await MR.api('POST', '/api/bot/stop', { roomId: roomId });
  MR.$('roomBotHint').textContent = (r.status === 200) ? ('방 ' + roomId + ' 봇 중지') : ('중지 실패 ' + r.status);
  MR.frontPanel.loadRooms();
};

/* 접속 이력(access.log) — 최근 100건 */
MR.frontPanel.loadAccess = async function () {
  var body = MR.$('accessBody');
  if (!body) return;
  var r = await MR.api('GET', '/api/access?tail=100');
  if (r.status !== 200 || !r.data) {
    MR.$('accessHint').textContent = '접속 이력 조회 실패 (' + r.status + ')';
    return;
  }
  var items = r.data.items || [];
  MR.$('accessHint').textContent = items.length + '건 · ' + (r.data.path || '');
  body.innerHTML = items.slice().reverse().map(function (x) {
    return '<tr><td class="muted" style="font-size:11.5px">' + MR.esc((x.ts || '').replace('T', ' ')) + '</td>' +
      '<td>' + MR.esc(x.ev || '') + '</td>' +
      '<td>' + MR.esc(x.ip || '—') + '</td>' +
      '<td class="muted" style="font-size:11.5px">' + MR.esc(x.pseudo || '—') + '</td>' +
      '<td>' + MR.esc(x.room === undefined ? '—' : x.room) + '</td>' +
      '<td>' + MR.esc(x.name || '—') + '</td>' +
      '<td class="muted">' + MR.esc(x.why || '') + '</td></tr>';
  }).join('') || '<tr><td colspan="7" class="muted">기록이 없습니다.</td></tr>';
};
