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
    if (f.hint) {
      var h = document.createElement('span');
      h.className = 'muted';
      h.style.marginLeft = '6px';
      h.textContent = '(' + f.hint + ')';
      lab.appendChild(h);
    }
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
    lab.appendChild(document.createTextNode(' '));
    var hint = document.createElement('span');
    hint.className = 'muted';
    hint.style.marginLeft = '6px';
    hint.textContent = '(방을 만들 때 이 목록으로 금지/제한 적용)';
    lab.appendChild(hint);
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
    MR.$('frontHint').textContent = (r.data.enabled ? '프론트 :' + r.data.frontPort + ' ' : '프론트 꺼짐 ') +
      '· 금지목록 ' + (r.data.banlists || []).length + '개 · 파일 ' + (r.data.path || '');
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
  }
};
