/* ConfigForm — config.json 을 폼으로 자동 렌더 + 저장/재시작 */
window.MR = window.MR || {};

MR.configForm = {
  OBJ_ARRAY_KEYS: null,

  /* ---------- 스칼라 / 목록 ---------- */
  scalar: function (key, val, path) {
    var wrap = document.createElement('div');
    if (typeof val === 'boolean') {
      var l = document.createElement('label');
      l.className = 'chk';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = val;
      cb.onchange = function () {
        MR.setPath(MR.state.MODEL, path, cb.checked);
        l.lastChild.textContent = cb.checked ? '켜짐 (true)' : '꺼짐 (false)';
      };
      l.appendChild(cb);
      l.appendChild(document.createTextNode(val ? '켜짐 (true)' : '꺼짐 (false)'));
      wrap.appendChild(l);
      return wrap;
    }
    if (typeof val === 'number') {
      var inp = document.createElement('input');
      inp.type = 'number';
      inp.value = val;
      inp.oninput = function () {
        MR.setPath(MR.state.MODEL, path, inp.value === '' ? 0 : Number(inp.value));
      };
      wrap.appendChild(inp);
      return wrap;
    }
    var txt = document.createElement('input');
    txt.type = 'text';
    txt.value = val === null ? '' : String(val);
    txt.oninput = function () { MR.setPath(MR.state.MODEL, path, txt.value); };
    if (String(val || '').length > 40) txt.style.minWidth = '100%';
    wrap.appendChild(txt);
    return wrap;
  },

  list: function (key, arr, path) {
    var wrap = document.createElement('div');
    var ta = document.createElement('textarea');
    ta.spellcheck = false;
    ta.value = arr.map(function (x) {
      return (typeof x === 'object') ? JSON.stringify(x) : String(x);
    }).join('\n');
    ta.oninput = function () {
      var out = ta.value.split('\n').map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; })
        .map(function (s) {
          if (s.charAt(0) === '{' || s.charAt(0) === '[') {
            try { return JSON.parse(s); } catch (e) { return s; }
          }
          return s;
        });
      MR.setPath(MR.state.MODEL, path, out);
    };
    wrap.appendChild(ta);
    var h = document.createElement('span');
    h.className = 'hint';
    h.textContent = '한 줄에 하나씩.';
    wrap.appendChild(h);
    return wrap;
  },

  /* ---------- 행 / 섹션 / 객체 배열 ---------- */
  row: function (key, path, val) {
    var row = document.createElement('div');
    row.className = 'row';
    var lab = document.createElement('label');
    var k = document.createElement('span');
    k.className = 'key';
    k.textContent = key;
    lab.appendChild(k);
    if (MR.state.DOCS[key]) {
      var h = document.createElement('span');
      h.className = 'hint';
      h.textContent = MR.state.DOCS[key];
      lab.appendChild(h);
    }
    row.appendChild(lab);
    var ctl = document.createElement('div');
    ctl.appendChild(Array.isArray(val) ? MR.configForm.list(key, val, path) : MR.configForm.scalar(key, val, path));
    row.appendChild(ctl);
    return row;
  },

  section: function (key, path, obj) {
    var fs = document.createElement('fieldset');
    var lg = document.createElement('legend');
    lg.className = 'key';
    lg.textContent = key;
    fs.appendChild(lg);
    if (MR.state.DOCS[key]) {
      var h = document.createElement('span');
      h.className = 'hint';
      h.style.marginLeft = '8px';
      h.textContent = MR.state.DOCS[key];
      fs.appendChild(h);
    }
    fs.appendChild(MR.configForm.object(obj, path));
    return fs;
  },

  objectArray: function (key, path, arr) {
    var box = document.createElement('div');
    box.className = 'arr-sec';
    var head = document.createElement('div');
    head.className = 'arr-head';
    head.innerHTML = '<span class="key">' + MR.esc(key) + '</span> <span class="tag">' + arr.length + '개</span>' +
      (MR.state.DOCS[key]
        ? '<span class="hint" style="flex:1;margin-left:8px">' + MR.esc(MR.state.DOCS[key]) + '</span>'
        : '<span style="flex:1"></span>');
    var add = document.createElement('button');
    add.className = 'sm';
    add.textContent = '+ 항목 추가';
    add.onclick = function () {
      var tpl = arr.length ? JSON.parse(JSON.stringify(arr[arr.length - 1])) : {};
      arr.push(tpl);
      MR.configForm.render();
    };
    head.appendChild(add);
    box.appendChild(head);

    arr.forEach(function (item, idx) {
      var it = document.createElement('div');
      it.className = 'item';
      var ih = document.createElement('div');
      ih.className = 'itemhead';
      var label = (item && typeof item.name === 'string') ? item.name : (key + '[' + idx + ']');
      ih.innerHTML = '<span><b>' + MR.esc(label) + '</b> <span class="muted">' + key + '[' + idx + ']</span></span>';
      var del = document.createElement('button');
      del.className = 'sm danger';
      del.textContent = '삭제';
      del.onclick = function () { arr.splice(idx, 1); MR.configForm.render(); };
      ih.appendChild(del);
      it.appendChild(ih);
      it.appendChild(MR.configForm.object(item || {}, path + '.' + idx));
      box.appendChild(it);
    });
    return box;
  },

  object: function (obj, path) {
    var frag = document.createDocumentFragment();
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      var p = path ? path + '.' + k : k;
      if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
        frag.appendChild(MR.configForm.section(k, p, v));
      } else if (Array.isArray(v) && (MR.configForm.OBJ_ARRAY_KEYS.has(k) ||
                 (v.length && typeof v[0] === 'object' && v[0] !== null))) {
        frag.appendChild(MR.configForm.objectArray(k, p, v));
      } else {
        frag.appendChild(MR.configForm.row(k, p, v));
      }
    });
    var wrap = document.createElement('div');
    wrap.appendChild(frag);
    return wrap;
  },

  render: function () {
    var host = MR.$('cfgForm');
    host.innerHTML = '';
    if (!MR.state.MODEL) return;
    host.appendChild(MR.configForm.object(MR.state.MODEL, ''));
    MR.$('cfgPath').textContent = MR.state.MODEL_PATH || '';
  },

  /* ---------- 서버 통신 ---------- */
  load: async function () {
    var r = await MR.api('GET', '/api/config');
    if (r.status === 401) { location.reload(); return; }
    if (r.status !== 200) {
      MR.toast('err', '설정을 읽을 수 없습니다', (r.data && r.data.error) || []);
      return;
    }
    var S = MR.state;
    S.MODEL = r.data.config;
    S.DOCS = r.data.docs || {};
    S.MODEL_PATH = r.data.path || '';
    MR.configForm.render();
    if (r.data.warnings && r.data.warnings.length) {
      MR.toast('warn', '경고 ' + r.data.warnings.length + '건 (저장은 가능)', r.data.warnings);
    } else if (r.data.pendingRestart) {
      MR.toast('warn', '설정 파일이 저장되어 있지만 실행 중인 서버에는 아직 반영되지 않았습니다.');
    } else {
      MR.$('cfgBanner').classList.add('hidden');
    }
  },

  save: async function () {
    if (!MR.state.MODEL) return false;
    var r = await MR.api('PUT', '/api/config', MR.state.MODEL);
    if (r.status === 200) {
      MR.toast('ok', '저장했습니다. 적용하려면 [지금 적용(재시작)] 을 누르세요.');
      MR.$('pendPill').classList.remove('hidden');
      if (r.data && r.data.warnings && r.data.warnings.length) {
        MR.toast('warn', '저장됨 · 경고 ' + r.data.warnings.length + '건', r.data.warnings);
      }
      return true;
    }
    MR.toast('err', '저장 실패 — 수정 후 다시 시도하세요', (r.data && r.data.error) || []);
    return false;
  },

  restart: async function () {
    var r = await MR.api('POST', '/api/restart');
    if (r.status === 200) {
      MR.state.RESTARTING = true;
      MR.toast('info', '재시작 중… (수 초) 실행 중인 방은 끊깁니다.');
      setTimeout(MR.header.refresh, 1500);
      setTimeout(MR.header.refresh, 4000);
      return;
    }
    if (r.status === 409) {
      var c = r.data.clients || {};
      var txt = Object.keys(c).map(function (k) { return '  · 포트 ' + k + ' : ' + c[k] + '개'; }).join('<br>');
      MR.confirmBox('진행 중인 접속이 있습니다',
        '재시작하면 <b>진행 중인 듀얼이 모두 끊깁니다.</b><br><br>' + txt + '<br><br>계속할까요?',
        '그래도 재시작', async function () {
          var r2 = await MR.api('POST', '/api/restart?force=1');
          if (r2.status === 200) MR.toast('info', '재시작 중… (강제)');
          else MR.toast('err', '재시작 실패', (r2.data && r2.data.error) || []);
        });
      return;
    }
    MR.toast('err', '재시작 실패', (r.data && (r.data.message || r.data.error)) || []);
  },

  /* ---------- 버튼 ---------- */
  bind: function () {
    MR.configForm.OBJ_ARRAY_KEYS = new Set(['repos']);
    MR.$('btnSave').onclick = MR.configForm.save;
    MR.$('btnApply').onclick = async function () {
      if (await MR.configForm.save()) await MR.configForm.restart();
    };
    MR.$('btnReload').onclick = MR.configForm.load;
    MR.$('btnRaw').onclick = function () {
      var w = MR.$('rawWrap');
      w.classList.toggle('hidden');
      if (!w.classList.contains('hidden')) MR.$('rawText').value = JSON.stringify(MR.state.MODEL, null, '\t');
    };
    MR.$('btnRawCancel').onclick = function () { MR.$('rawWrap').classList.add('hidden'); };
    MR.$('btnRawApply').onclick = async function () {
      var obj;
      try { obj = JSON.parse(MR.$('rawText').value); }
      catch (e) { MR.toast('err', 'JSON 오류: ' + e.message); return; }
      MR.state.MODEL = obj;
      if (await MR.configForm.save()) {
        MR.configForm.render();
        MR.$('rawWrap').classList.add('hidden');
      }
    };
  }
};
