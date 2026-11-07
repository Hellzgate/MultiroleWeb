/* LogPanel — 자식 프로세스 로그 tail (2초 폴링) */
window.MR = window.MR || {};

MR.logPanel = {
  load: async function () {
    var r = await MR.api('GET', '/api/logs?tail=500');
    if (r.status !== 200 || !r.data) return;
    var box = MR.$('logbox');
    var atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.textContent = (r.data.lines || []).join('\n');
    if (atBottom) box.scrollTop = box.scrollHeight;
    MR.$('logPath').textContent = r.data.path || '';
  },

  start: function () {
    MR.logPanel.stop();
    MR.state.LOGTIMER = setInterval(function () {
      if (MR.$('autoLog').checked && MR.state.TAB === 'logs') MR.logPanel.load();
    }, 2000);
  },

  stop: function () {
    if (MR.state.LOGTIMER) {
      clearInterval(MR.state.LOGTIMER);
      MR.state.LOGTIMER = null;
    }
  },

  bind: function () {
    MR.$('btnLogRefresh').onclick = MR.logPanel.load;
    MR.$('btnLogBottom').onclick = function () {
      var b = MR.$('logbox');
      b.scrollTop = b.scrollHeight;
    };
  }
};
