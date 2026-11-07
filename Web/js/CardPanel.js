/* CardPanel — cdb 카드 검색 + 갱신 확인 */
window.MR = window.MR || {};

MR.cardPanel = {
  load: function () {
    MR.cardPanel.loadChanges();
    MR.cardPanel.search();
  },

  loadChanges: async function () {
    var r = await MR.api('GET', '/api/cards/changes');
    if (r.status !== 200 || !r.data) { MR.$('cardChangeSummary').textContent = '조회 실패'; return; }
    var d = r.data;
    MR.$('cardFiles').innerHTML = (d.files || []).map(function (f) {
      return '<tr><td><code>' + MR.esc(f.name) + '</code></td><td>' + MR.size(f.bytes) +
        '</td><td class="muted">' + MR.esc(f.mtime) + '</td></tr>';
    }).join('') || '<tr><td colspan="3" class="muted">cdb 없음</td></tr>';

    var c = d.counts;
    if (!c) {
      MR.$('cardChangeSummary').textContent = '아직 스냅샷 없음';
      MR.$('cardChanges').innerHTML = '<span class="muted">저장소를 한 번 갱신하면 기준 스냅샷이 자동으로 만들어집니다.</span>';
      return;
    }
    MR.$('cardChangeSummary').textContent = '(' + (d.at || '') + ' 기준)';
    var html = '<div>전체 <b>' + c.total + '</b>장 · ' +
      '추가 <b style="color:#9ff0bd">' + c.added + '</b> · ' +
      '변경 <b style="color:#f7dc9c">' + c.changed + '</b> · ' +
      '삭제 <b style="color:#f7b4b4">' + c.removed + '</b></div>';

    function rows(list, fmt) {
      if (!list || !list.length) return '';
      return '<ul style="margin:6px 0 0;padding-left:18px">' +
        list.slice(0, 20).map(fmt).join('') +
        (list.length > 20 ? '<li class="muted">외 ' + (list.length - 20) + '장</li>' : '') + '</ul>';
    }
    html += rows(d.added, function (x) {
      return '<li>+ <code>' + x.id + '</code> ' + MR.esc(x.name || '') + '</li>';
    });
    html += rows(d.changed, function (x) {
      return '<li>~ <code>' + x.id + '</code> ' + MR.esc(x.name || '') +
        ' <span class="muted">(' + MR.esc((x.fields || []).join(', ')) + ')</span></li>';
    });
    html += rows(d.removed, function (id) {
      return '<li>- <code>' + id + '</code></li>';
    });
    MR.$('cardChanges').innerHTML = html;
  },

  _seq: 0,

  search: async function () {
    var q = (MR.$('cardQuery') || {}).value || '';
    var seq = ++MR.cardPanel._seq;
    var r = await MR.api('GET', '/api/cards?limit=100&q=' + encodeURIComponent(q));
    if (seq !== MR.cardPanel._seq) return;      // 탭 진입 시의 빈 검색이 뒤늦게 도착해 덮어쓰는 것 방지
    if (r.status !== 200 || !r.data) {
      MR.$('cardHint').textContent = '검색 실패 (' + r.status + ')';
      return;
    }
    var items = r.data.items || [];
    MR.$('cardHint').textContent = (r.data.files || []).length + '개 cdb';
    MR.$('cardCount').textContent = items.length ? '(' + items.length + ')' : '';
    MR.$('cardBody').innerHTML = items.map(function (x) {
      return '<tr data-cid="' + x.id + '" style="cursor:pointer"><td><code>' + x.id + '</code></td>' +
        '<td>' + MR.esc(x.name) + '</td>' +
        '<td class="muted">' + MR.esc(x.kind) + '</td>' +
        '<td>' + (x.level === undefined || x.level === null ? '' : x.level) + '</td>' +
        '<td class="muted">' + (x.atk || 0) + ' / ' + (x.def || 0) + '</td>' +
        '<td class="muted" style="font-size:11.5px">' + MR.esc(x.src || '') +
        (x.mtime ? '<br>' + MR.esc(x.mtime) : '') + '</td>' +
        '<td class="muted" style="font-size:11.5px">' + MR.esc(x.desc || '') + '</td></tr>';
    }).join('') || '<tr><td colspan="7" class="muted">결과 없음</td></tr>';
    Array.prototype.forEach.call(MR.$('cardBody').querySelectorAll('tr[data-cid]'), function (tr) {
      tr.onclick = function () { MR.cardPanel.detail(tr.getAttribute('data-cid')); };
    });
  },

  detail: async function (cid) {
    var r = await MR.api('GET', '/api/cards/' + cid);
    var box = MR.$('cardDetail');
    if (r.status !== 200 || !r.data) { box.textContent = '상세 조회 실패 (' + r.status + ')'; return; }
    var d = r.data;
    var str = [];
    for (var i = 1; i <= 5; i++) {
      if (d['str' + i]) str.push('<div>#' + i + ' ' + MR.esc(d['str' + i]) + '</div>');
    }
    box.innerHTML = '<div style="color:#e6e9ef;font-size:14px;margin-bottom:6px"><b>' +
      MR.esc(d.name) + '</b> <code>' + d.id + '</code> ' +
      '<span class="tag">' + MR.esc(d.kind) + '</span>' +
      (d.attr ? ' <span class="tag">' + MR.esc(d.attr) + '</span>' : '') +
      (d.race ? ' <span class="tag">' + MR.esc(d.race) + '</span>' : '') + '</div>' +
      '<div style="white-space:pre-wrap;line-height:1.6">' + MR.esc(d.desc || '') + '</div>' +
      (str.length ? '<div style="margin-top:8px;color:#8b93a7;font-size:12px">' + str.join('') + '</div>' : '') +
      '<div class="muted" style="margin-top:8px">출처 ' + MR.esc((d.cdb || {}).name || '?') +
      ' · 갱신 ' + MR.esc((d.cdb || {}).mtime || '?') + '</div>';
  },

  snapshot: async function () {
    var r = await MR.api('POST', '/api/cards/snapshot', {});
    MR.$('cardChangeSummary').textContent = (r.status === 200 && r.data && r.data.ok)
      ? '스냅샷 저장됨' : '스냅샷 실패';
    MR.cardPanel.loadChanges();
  },

  bind: function () {
    MR.$('btnCardSearch').onclick = function () { MR.cardPanel.search(); };
    MR.$('cardQuery').onkeydown = function (e) { if (e.key === 'Enter') MR.cardPanel.search(); };
    MR.$('btnCardChanges').onclick = function () { MR.cardPanel.loadChanges(); };
    MR.$('btnCardSnapshot').onclick = function () { MR.cardPanel.snapshot(); };
  }
};
