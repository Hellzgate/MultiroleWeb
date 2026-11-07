/* ReplayPanel — replays/*.yrpX 목록 + 다운로드 */
window.MR = window.MR || {};

MR.replayPanel = {
  load: async function () {
    var r = await MR.api('GET', '/api/replays');
    if (r.status !== 200 || !r.data) return;
    MR.$('repDir').textContent = r.data.dir || '';
    MR.$('repBody').innerHTML = (r.data.items || []).map(function (it) {
      return '<tr><td>' + MR.esc(it.name) + '</td><td>' + MR.size(it.bytes) + '</td><td>' + it.mtime + '</td>' +
        '<td><a class="tag" href="/api/replay?name=' + encodeURIComponent(it.name) + '">내려받기</a></td></tr>';
    }).join('') || '<tr><td colspan="4" class="muted">리플레이가 없습니다.</td></tr>';
  },

  bind: function () {
    MR.$('btnRep').onclick = MR.replayPanel.load;
  }
};
