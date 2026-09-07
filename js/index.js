// ページ① リザルトデータベース。事実データを見る場所で、分析はしない。
//
// 入口の考え方：一覧を見せてから探させるのではなく、知りたい人・大会へ最短で到達させ、
// 必要なときだけ詳細を開く。初期表示は「最近の大会」で、いきなり全件の表は出さない。
//
// 検索・絞り込み・ソートは **常に全件** を対象にし、表示だけを50件ずつに切る。
// （以前は先頭3000件しか描画しておらず、3,001件目以降に到達できなかった。
//   ソートは全件で効いていたが、欠測を含む行は末尾に送られるため事実上見えなかった）

import * as data from './data.js';
import {
  el, clear, cell, num, sourceBadge, mountNav, downloadCsv, errorBox,
  paginate, renderPager, isNarrow, onWidthChange, noteLayers, scrollToTop, PER_PAGE,
} from './ui.js';
import { openDetail } from './detail.js';

const state = {
  q: '', year: '', meet: '', category: '', round: '', routine: '',
  sortKey: 'date', sortDir: -1, page: 1, showAll: false,
};

let rows = [];
let meets = new Map();
let athletes = [];
let manifest = null;

const SORTS = [
  ['date', '大会日', false], ['meet_name', '大会', false], ['category', '区分', false],
  ['round', 'ラウンド', false], ['routine', '演技', true], ['athlete_name', '選手', false],
  ['club', '所属', false], ['rank', '順位', true], ['total', '合計', true],
  ['D', 'D', true], ['E', 'E', true], ['T', 'T', true], ['HD', 'HD', true],
  ['n_elements', '技数', true],
];

// ---- 絞り込み ---------------------------------------------------------------

function matches(p) {
  if (state.year && p.season !== state.year) return false;
  if (state.meet && p.meet_id !== state.meet) return false;
  if (state.category && p.category !== state.category) return false;
  if (state.round && p.round !== state.round) return false;
  if (state.routine && String(p.routine || '') !== state.routine) return false;
  if (state.q) {
    const q = state.q.toLowerCase();
    const hay = [p.athlete_name, p.meet_name, p.club, p.category].join(' ').toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function hasCondition() {
  // 初期表示は「最近の大会」。表を出すのは、検索・絞り込みをしたときか、
  // 「すべての記録を見る」を押したときだけ。いきなり8,175件の表は出さない。
  return !!(state.showAll || state.q || state.year || state.meet
    || state.category || state.round || state.routine);
}

function sorted(list) {
  const { sortKey: key, sortDir: dir } = state;
  return [...list].sort((a, b) => {
    const x = a[key], y = b[key];
    const xn = x === null || x === undefined || x === '';
    const yn = y === null || y === undefined || y === '';
    if (xn && yn) return 0;
    if (xn) return 1;              // 欠測は末尾。ページングにしたので最後まで送れば必ず見える
    if (yn) return -1;
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
    return String(x).localeCompare(String(y), 'ja') * dir;
  });
}

// ---- 表示 -------------------------------------------------------------------

function rowCells(p) {
  return [
    el('td', { text: p.date }),
    el('td', {}, [document.createTextNode(p.meet_name + ' '), sourceBadge(p.official)]),
    el('td', { text: p.category }),
    el('td', { text: p.round || '—' }),
    el('td', { class: 'num', text: p.routine || '—' }),
    el('td', {}, el('span', {
      class: 'link', text: p.athlete_name,
      onclick: () => { location.href = 'athlete.html#' + (p.athlete_id || ''); },
    })),
    el('td', { class: p.club ? '' : 'blank', text: p.club || '—' }),
    el('td', { class: p.rank ? 'num' : 'num blank', text: p.rank || '—' }),
    cell(p.total, 2), cell(p.D, 1), cell(p.E, 1), cell(p.T, 2), cell(p.HD, 2),
    el('td', { class: 'num', text: p.n_elements ?? '—' }),
    el('td', {}, [
      p.interrupted ? el('span', { class: 'badge flag', text: '中断' }) : null,
      ...(p.check_flags || []).map((f) => el('span', { class: 'badge flag', text: f })),
      el('span', { class: 'link', text: '詳細', onclick: () => openDetail(p, meets.get(p.meet_id)) }),
    ]),
  ];
}

function renderTable(items) {
  const head = el('tr', {}, SORTS.map(([key, label, numeric]) => el('th', {
    'data-key': key,
    class: numeric ? 'num' : '',
    'aria-sort': state.sortKey === key ? (state.sortDir === 1 ? 'ascending' : 'descending') : null,
    text: label,
    onclick: () => {
      if (state.sortKey === key) state.sortDir = -state.sortDir;
      else { state.sortKey = key; state.sortDir = numeric ? -1 : 1; }
      state.page = 1;   // 並び替えたら1ページ目へ
      render();
    },
  })).concat([el('th', { class: 'no-sort' })]));
  return el('div', { class: 'table-wrap' },
    el('table', {}, [el('thead', {}, head), el('tbody', {}, items.map((p) => el('tr', {}, rowCells(p))))]));
}

// 狭い画面では1件＝1カード。大会日・大会名・区分・順位・合計を主、D/E/T/HDを従にする。
function renderCards(items) {
  return el('div', { class: 'card-list' }, items.map((p) => el('article', { class: 'rec' }, [
    el('div', { class: 'rec-head' }, [
      el('span', { class: 'link rec-name', text: p.athlete_name,
        onclick: () => { location.href = 'athlete.html#' + (p.athlete_id || ''); } }),
      el('span', { class: 'rec-total', text: num(p.total, 2) ?? '—' }),
    ]),
    el('div', { class: 'rec-meta' }, [
      document.createTextNode(p.date + '　' + p.meet_name + ' '),
      sourceBadge(p.official),
    ]),
    el('div', { class: 'rec-tags' }, [
      el('span', { class: 'badge plain', text: p.category }),
      p.round ? el('span', { class: 'badge plain', text: p.round }) : null,
      p.routine ? el('span', { class: 'badge plain', text: p.routine + '本目' }) : null,
      p.rank ? el('span', { class: 'badge plain', text: p.rank + '位' }) : null,
      p.interrupted ? el('span', { class: 'badge flag', text: '中断' }) : null,
    ]),
    el('dl', { class: 'rec-sub' }, [
      ['D', num(p.D, 1)], ['E', num(p.E, 1)], ['T', num(p.T, 2)], ['HD', num(p.HD, 2)],
      ['技数', p.n_elements ?? null],
    ].flatMap(([k, v]) => [
      el('dt', { text: k }),
      el('dd', { class: v === null || v === undefined ? 'blank' : '', text: v ?? '—' }),
    ])),
    el('button', { class: 'chip', text: '演技の詳細',
      onclick: () => openDetail(p, meets.get(p.meet_id)) }),
  ])));
}

function render() {
  const filtered = rows.filter(matches);
  const view = paginate(sorted(filtered), state.page);
  state.page = view.page;

  const box = clear(document.getElementById('results'));
  box.append(isNarrow() ? renderCards(view.items) : renderTable(view.items));

  for (const id of ['pager-top', 'pager-bottom']) {
    renderPager(document.getElementById(id), view, rows.length, (p) => {
      state.page = p;
      render();
      document.getElementById('results-card').scrollIntoView({ block: 'start' });
    });
  }
  document.getElementById('results-title').textContent = titleFor();

  const show = hasCondition();
  document.getElementById('results-card').hidden = !show;
  document.getElementById('recent-card').hidden = show;
  document.getElementById('reset').hidden = !show;
  document.getElementById('csv').hidden = !show;
}

function titleFor() {
  if (state.meet) return (meets.get(state.meet) || {}).name || '検索結果';
  if (state.q) return '「' + state.q + '」の検索結果';
  if (state.showAll && !hasFilters()) return 'すべての記録';
  return '検索結果';
}

function hasFilters() {
  return !!(state.year || state.category || state.round || state.routine);
}

// ---- 検索候補 ---------------------------------------------------------------
// 入力に応じて選手候補を出し、押したらそのまま選手ページへ送る。

function renderSuggest() {
  const box = document.getElementById('suggest');
  const q = state.q.trim().toLowerCase();
  clear(box);
  if (q.length < 1) { box.hidden = true; return; }

  const hits = athletes
    .filter((a) => a.name.toLowerCase().includes(q)
      || (a.names_seen || []).some((n) => n.toLowerCase().includes(q)))
    .slice(0, 6);
  const meetHits = [...meets.values()]
    .filter((c) => c.name.toLowerCase().includes(q))
    .slice(0, 3);
  if (!hits.length && !meetHits.length) { box.hidden = true; return; }

  for (const a of hits) {
    const club = (a.club_history || []).slice(-1)[0];
    box.append(el('button', { class: 'suggest-item',
      onclick: () => { location.href = 'athlete.html#' + a.athlete_id; } }, [
      el('span', { class: 'sug-name', text: a.name }),
      el('span', { class: 'sug-meta',
        text: (club ? club.clubs.join('・') + '　' : '') + a.n_performances + '演技' }),
      el('span', { class: 'sug-go', text: '選手ページを見る →' }),
    ]));
  }
  for (const c of meetHits) {
    box.append(el('button', { class: 'suggest-item',
      onclick: () => { location.href = 'meet.html#' + encodeURIComponent(c.meet_id); } }, [
      el('span', { class: 'sug-name', text: c.name }),
      el('span', { class: 'sug-meta', text: c.date + '　' + c.n_individual + '演技' }),
      el('span', { class: 'sug-go', text: 'この大会を見る →' }),
    ]));
  }
  box.hidden = false;
}

// ---- 最近の大会 -------------------------------------------------------------

// 初期表示に並べる数。スマホだと1列なので、多いと下の内容まで指が届かない。
const RECENT_N = 5;
let allMeetsOpen = false;

function meetCard(c) {
  return el('button', { class: 'meet-card',
    onclick: () => { location.href = 'meet.html#' + encodeURIComponent(c.meet_id); } }, [
    el('div', { class: 'meet-date' }, [document.createTextNode(c.date + ' '), sourceBadge(c.official)]),
    el('div', { class: 'meet-name', text: c.name }),
    el('div', { class: 'meet-sub', text: c.n_individual + '演技　' + c.level
      + '　→ 公式と同じ並びで見る' }),
  ]);
}

function renderRecent() {
  const all = [...meets.values()]
    .filter((c) => c.n_individual > 0)
    .sort((a, b) => (a.date < b.date ? 1 : -1));
  const box = clear(document.getElementById('recent'));
  for (const c of (allMeetsOpen ? all : all.slice(0, RECENT_N))) box.append(meetCard(c));

  document.getElementById('recent-title').textContent =
    allMeetsOpen ? 'すべての大会' : '最近の大会';

  // 開閉のボタンは一覧の外に置く。中に入れると、開いたときに末尾まで
  // スクロールしないと閉じられない。
  const more = clear(document.getElementById('recent-more'));
  if (all.length <= RECENT_N) return;
  more.append(el('button', { class: 'more-card',
    onclick: () => {
      allMeetsOpen = !allMeetsOpen;
      renderRecent();
      if (!allMeetsOpen) scrollToTop(document.getElementById('recent-card'));
    } }, [
    el('span', { class: 'more-name', text: allMeetsOpen ? '最近の大会だけ表示' : 'すべての大会' }),
    el('span', { class: 'more-sub', text: allMeetsOpen
      ? '新しい順に ' + all.length + '大会を表示中'
      : '全 ' + all.length + '大会を新しい順に表示' }),
  ]));
}

// ---- 起動 -------------------------------------------------------------------

function fillSelect(id, values, label) {
  const sel = clear(document.getElementById(id));
  sel.append(el('option', { value: '', text: label }));
  for (const v of values) sel.append(el('option', { value: v.value, text: v.text }));
}

function buildNote() {
  const n = manifest.validation.notes;
  const slot = clear(document.getElementById('note-slot'));
  slot.append(noteLayers(
    '一部の大会では順位・所属・得点内訳が取得できません',
    [
      el('p', { class: 'meta', text: '取れなかった値は空欄（—）で表示しています。0点ではありません。' }),
      el('table', { class: 'mini' }, [
        el('thead', {}, el('tr', {}, [
          el('th', { class: 'no-sort', text: '欠測' }),
          el('th', { class: 'no-sort num', text: '件数' }),
          el('th', { class: 'no-sort', text: '理由' }),
        ])),
        el('tbody', {}, [
          ['合計点・D・T', n['欠測_合計点'], '取れなかった行'],
          ['順位', n['欠測_順位'], '大阪府の棄権（順位が付かない）'],
          ['所属', n['欠測_所属'], '所属が印字されていない行'],
          ['技数', n['欠測_技数'], '大阪府でサイトの表示が壊れていて復元できなかった行'],
        // 0件の行は出さない。0を並べても読む人の判断材料にならない。
        ].filter(([, v]) => parseInt(v, 10) > 0).map(([k, v, why]) => el('tr', {}, [
          el('td', { text: k }), el('td', { class: 'num', text: v }), el('td', { class: 'meta', text: why }),
        ]))),
      ]),
      el('p', { class: 'meta', text: '中断演技（技数10未満）は ' + n['中断演技']
        + ' あります。消していません。演技詳細では「中断（技数7）」のように明示し、'
        + '位置別・技別の平均を出すときだけ分母から外して、外した数を併記しています。' }),
    ]));
}

async function main() {
  mountNav('index.html');
  try {
    const [perfs, meetList, mf, as] = await Promise.all([
      data.performances(), data.competitions(), data.manifest(), data.athletes(),
    ]);
    meets = new Map(meetList.map((c) => [c.meet_id, c]));
    rows = perfs;
    manifest = mf;
    athletes = as.filter((a) => a.has_individual);

    buildNote();
    renderRecent();

    fillSelect('f-year', [...new Set(rows.map((p) => p.season))].sort()
      .map((v) => ({ value: v, text: v + '年' })), '年（すべて）');
    fillSelect('f-meet', meetList.filter((c) => c.n_individual > 0)
      .map((c) => ({ value: c.meet_id, text: c.date + ' ' + c.name })), '大会（すべて）');
    fillSelect('f-category', [...new Set(rows.map((p) => p.category))].sort()
      .map((v) => ({ value: v, text: v })), '区分（すべて）');
    fillSelect('f-round', [...new Set(rows.map((p) => p.round).filter(Boolean))]
      .map((v) => ({ value: v, text: v })), 'ラウンド（すべて）');
    fillSelect('f-routine', [...new Set(rows.map((p) => p.routine).filter(Boolean))].sort()
      .map((v) => ({ value: String(v), text: v + '本目' })), '演技（すべて）');

    const q = document.getElementById('q');
    q.addEventListener('input', () => {
      state.q = q.value;
      state.page = 1;
      renderSuggest();
      render();
    });
    q.addEventListener('blur', () => setTimeout(() => {
      document.getElementById('suggest').hidden = true;
    }, 180));

    for (const [id, key] of [['f-year', 'year'], ['f-meet', 'meet'],
      ['f-category', 'category'], ['f-round', 'round'], ['f-routine', 'routine']]) {
      const node = document.getElementById(id);
      node.addEventListener('change', () => { state[key] = node.value; state.page = 1; render(); });
    }

    document.getElementById('show-all').addEventListener('click', () => {
      state.showAll = true;
      state.page = 1;
      render();
      document.getElementById('results-card').scrollIntoView({ block: 'start' });
    });

    const toggle = document.getElementById('toggle-filters');
    toggle.addEventListener('click', () => {
      const box = document.getElementById('filters');
      box.hidden = !box.hidden;
      toggle.setAttribute('aria-expanded', String(!box.hidden));
      toggle.textContent = box.hidden ? '詳しく絞り込む ▼' : '絞り込みを閉じる ▲';
    });

    document.getElementById('reset').addEventListener('click', () => {
      Object.assign(state, { q: '', year: '', meet: '', category: '', round: '',
        routine: '', page: 1, showAll: false });
      for (const id of ['q', 'f-year', 'f-meet', 'f-category', 'f-round', 'f-routine']) {
        document.getElementById(id).value = '';
      }
      document.getElementById('suggest').hidden = true;
      render();
    });

    document.getElementById('csv').addEventListener('click', () => {
      const list = sorted(rows.filter(matches));
      downloadCsv('リザルト_' + manifest.dataVersion + '.csv',
        ['大会日', '大会名', '出典', '公式', '区分', 'ラウンド', '演技', '選手', '所属',
          '順位', '合計', 'D', 'E', 'T', 'HD', '技数', '中断', '要確認'],
        list.map((p) => [p.date, p.meet_name, p.source, p.official ? '公式' : '非公式',
          p.category, p.round || '', p.routine || '', p.athlete_name, p.club || '',
          p.rank || '', num(p.total, 2) ?? '', num(p.D, 1) ?? '', num(p.E, 1) ?? '',
          num(p.T, 2) ?? '', num(p.HD, 2) ?? '', p.n_elements ?? '',
          p.interrupted ? '中断' : '', (p.check_flags || []).join(' ')]));
    });

    onWidthChange(() => render());
    render();
  } catch (err) {
    document.getElementById('app').prepend(errorBox(err.message));
  }
}

main();
