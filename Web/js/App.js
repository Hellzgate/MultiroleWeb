/* App — 탭 전환 + 부트스트랩 */
window.MR = window.MR || {};

MR.app = {
  showTab: function (tab) {
    MR.state.TAB = tab;
    document.querySelectorAll('nav button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    ['config', 'status', 'logs', 'replays', 'bots'].forEach(function (t) {
      MR.$('tab-' + t).classList.toggle('hidden', t !== tab);
    });
    if (tab === 'status') MR.statusPanel.load();
    if (tab === 'logs') { MR.logPanel.load(); MR.logPanel.start(); } else { MR.logPanel.stop(); }
    if (tab === 'replays') MR.replayPanel.load();
    if (tab === 'bots') MR.botPanel.load();
  },

  bind: function () {
    document.querySelectorAll('nav button').forEach(function (btn) {
      btn.onclick = function () { MR.app.showTab(btn.dataset.tab); };
    });
    MR.bindModal();
    MR.header.bind();
    MR.configForm.bind();
    MR.frontPanel.bind();
    MR.authPanel.bind();
    MR.statusPanel.bind();
    MR.logPanel.bind();
    MR.replayPanel.bind();
    MR.botPanel.bind();
  },

  boot: function () {
    MR.app.bind();
    MR.configForm.load();
    MR.frontPanel.load();
    MR.frontPanel.loadRooms();
    MR.frontPanel.loadAccess();
    MR.authPanel.load();
    MR.header.refresh();
    setInterval(MR.header.refresh, 5000);
  }
};

MR.app.boot();
