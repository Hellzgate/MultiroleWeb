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
  }
};
