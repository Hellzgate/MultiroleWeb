/* Header — 5초 폴링(/api/ping) 으로 상태 배지·버튼 갱신 */
window.MR = window.MR || {};

MR.header = {
  apply: function (st) {
    var p = st.process, c = st.clients || {}, S = MR.state;
    MR.$('dot').className = 'dot ' + (p.running ? 'on' : 'off');
    MR.$('stateText').textContent = p.running ? '실행 중' : (p.want ? '중지됨' : '중지(수동)');
    MR.$('pidPill').textContent = 'PID ' + (p.pid || '—');
    MR.$('upPill').textContent = '가동 ' + (p.running ? MR.dur(p.uptime) : '—');
    var cli = Object.keys(c).map(function (k) { return k + ':' + c[k]; }).join('  ');
    MR.$('cliPill').textContent = '접속 ' + (Object.keys(c).length ? cli : '—');
    MR.$('pendPill').classList.toggle('hidden', !st.config.pendingRestart);
    MR.$('btnStart').disabled = p.running;
    MR.$('btnStop').disabled = !p.running;
    S.STATUS = st;
    if (S.RESTARTING && p.running) {
      S.RESTARTING = false;
      MR.toast('ok', '재시작 완료 — PID ' + p.pid + ' · 설정이 적용되었습니다.');
    }
  },

  refresh: async function () {
    var r = await MR.api('GET', '/api/ping');
    if (r.status === 401) { location.reload(); return; }
    if (r.data) MR.header.apply(r.data);
  },

  bind: function () {
    MR.$('btnStart').onclick = async function () {
      await MR.api('POST', '/api/start');
      setTimeout(MR.header.refresh, 800);
    };
    MR.$('btnStop').onclick = function () {
      MR.confirmBox('서버 중지', 'multirole 을 중지합니다. 진행 중인 방은 끊깁니다.', '중지', async function () {
        await MR.api('POST', '/api/stop');
        setTimeout(MR.header.refresh, 1200);
      });
    };
    MR.$('btnRestart').onclick = function () { MR.configForm.restart(); };
    var lo = MR.$('btnLogout'); if (lo) lo.onclick = function () { MR.header.logout(); };
    var pw = MR.$('btnPw'); if (pw) pw.onclick = function () { MR.header.changePassword(); };
  }
};

/* 로그아웃 / 비밀번호 변경 */
MR.header.logout = async function () {
  await MR.api('POST', '/api/logout', {});
  location.href = '/';
};

MR.header.changePassword = function () {
  var html = '<input id="pwOld" type="password" placeholder="현재 비밀번호" style="width:100%;margin-bottom:6px">' +
             '<input id="pwNew" type="password" placeholder="새 비밀번호 (4자 이상)" style="width:100%;margin-bottom:6px">' +
             '<input id="pwNew2" type="password" placeholder="새 비밀번호 확인" style="width:100%">';
  MR.confirmBox('비밀번호 변경', html, '변경', async function () {
    var o = MR.$('pwOld'), n = MR.$('pwNew'), n2 = MR.$('pwNew2');
    if (!o || !n || !n2) return;
    if (n.value !== n2.value) { alert('새 비밀번호 확인이 다릅니다'); return; }
    var r = await MR.api('POST', '/api/password', { old: o.value, new: n.value });
    if (r.status === 200 && r.data && r.data.ok) {
      alert('변경되었습니다. 다시 로그인하세요.');
      MR.header.logout();
    } else {
      alert('실패: ' + JSON.stringify((r.data && r.data.error) || r.status));
    }
  });
};