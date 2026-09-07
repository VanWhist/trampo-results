// 大会ページ：大会 → 区分×ラウンド → 公式PDFと同じ並びの結果表。
//
// 一覧の汎用テーブル（合計・D・E・T・HD だけ）ではなく、**PDFの見た目に合わせる**。
// リザルトを見慣れている人が、紙と同じ順序で目を走らせられるようにするため。
//
//   Rank Name  S1 S2 … S10  Lnd  Exe  Diff  ToF  HD  Pen  Score
//   1 中田 悠暉  6 6 4 4 4 6 5 6 6 6  4  14.30 17.3 15.75 9.10 0.0 56.45
//     金沢学院大学クラブ
//
// 予選は1選手2行（1本目・2本目）で、順位と予選合計は2行にまたがる。PDFと同じ。
//
// ソースによって出せる列が違う（大阪府には順位も所属も無い、決勝は合計・D・Tも無い）。
// 中身が全部空の列は出さない。空欄は「—」で、0点ではないことが分かるようにする。
//
// **S値の意味がソースで違う**：西日本は技ごとの減点、sporttechは中央2審判の減点の和。
// 同じ見た目の表に混ぜると誤解のもとなので、必ず注記を出す。

import * as data from './data.js';
import {
  el, clear, num, sourceBadge, mountNav, downloadCsv, errorBox,
  isNarrow, onWidthChange, noteLayers, scrollToTop,
} from './ui.js';
import { openDetail } from './detail.js';

const state = { meetId: null, category: null, round: null, showAllAthletes: false };

// スマホは1選手ぶんで1画面近く使う。100名の区分（小学生高学年女子予選）だと
// ページの高さが4万pxを超えて、区分を選び直すことも戻ることもできなくなる。
// 並び順は公式のまま、**表示だけ**を切る（一覧ページの50件ずつと同じ考え方）。
const MOBILE_CHUNK = 30;
let meet = null;
let rows = [];
let details = {};
let manifest = null;

const ROUND_ORDER = ['予選', '準決勝', '決勝'];

// S値の単位はソースで違う。表の下に必ず出す。
const UNIT_NOTE = {
  nishinihon: 'S1〜S10 と着地は、技ごとの減点（0.1点単位）です。公式PDFの印字と同じ並びです。',
  sporttech: 'S1〜S10 と着地は「中央2審判の減点の和」（0.1点単位）です。'
    + '西日本のS値（技ごとの減点）とは意味が違うので、そのまま比べないでください。',
  osaka_pweb: 'S1〜S10 と着地は「中央2審判の減点の和」（0.1点単位）です。'
    + 'この大会は審判ごとの減点も公開されているので、演技の詳細で見られます。',
};

// ---- 区分・ラウンドの選択 ---------------------------------------------------

function sections() {
  const out = new Map();
  for (const r of rows) {
    const key = r.round || '';
    if (!out.has(key)) out.set(key, new Set());
    out.get(key).add(r.category);
  }
  return out;
}

function renderPicker() {
  const map = sections();
  const roundBox = clear(document.getElementById('rounds'));
  const rounds = [...map.keys()].sort(
    (a, b) => ROUND_ORDER.indexOf(a) - ROUND_ORDER.indexOf(b));
  for (const rnd of rounds) {
    roundBox.append(el('button', {
      class: 'chip', 'aria-pressed': String(state.round === rnd),
      text: (rnd || '（ラウンド不明）') + '（' + map.get(rnd).size + '区分）',
      onclick: () => {
        state.round = rnd;
        state.category = null;
        state.showAllAthletes = false;
        render();
      },
    }));
  }

  const catBox = clear(document.getElementById('categories'));
  if (!state.round) {
    catBox.append(el('p', { class: 'meta', text: 'まずラウンドを選んでください。' }));
    return;
  }
  for (const cat of [...map.get(state.round)].sort()) {
    const n = rows.filter((r) => r.round === state.round && r.category === cat).length;
    catBox.append(el('button', {
      class: 'cat-btn', 'aria-pressed': String(state.category === cat),
      // スマホだと区分の一覧が画面いっぱいで、選んでも結果が下に隠れたまま。
      // 選んだら結果まで運ぶ。
      onclick: () => {
        state.category = cat;
        state.showAllAthletes = false;
        render();
        scrollToResult();
      },
    }, [
      el('span', { class: 'cat-name', text: cat }),
      el('span', { class: 'cat-n', text: n + '演技' }),
    ]));
  }
}

/** 区分を選んだあと、結果表の先頭まで運ぶ。 */
function scrollToResult() {
  scrollToTop(document.getElementById('result-card'));
}

// ---- 結果表 -----------------------------------------------------------------

/** 1選手ぶんの行をまとめる（予選は1本目・2本目の2行）。 */
function groupByAthlete(list) {
  const by = new Map();
  for (const r of list) {
    const key = r.athlete_id || r.athlete_name;
    if (!by.has(key)) by.set(key, []);
    by.get(key).push(r);
  }
  const groups = [...by.values()];
  for (const g of groups) g.sort((a, b) => (a.routine || 0) - (b.routine || 0));
  groups.sort((a, b) => {
    const ra = a[0].rank, rb = b[0].rank;
    if (ra && rb) return ra - rb;
    if (ra) return -1;
    if (rb) return 1;
    // 順位が無いソース（大阪府）は合計の高い順。無ければ氏名順
    const ta = Math.max(...a.map((x) => x.total ?? -1));
    const tb = Math.max(...b.map((x) => x.total ?? -1));
    if (ta !== tb) return tb - ta;
    return a[0].athlete_name.localeCompare(b[0].athlete_name, 'ja');
  });
  return groups;
}

/** その区分で中身のある列だけを出す。 */
function activeColumns(list) {
  const has = (key) => list.some((r) => r[key] !== null && r[key] !== undefined);
  return {
    rank: list.some((r) => r.rank),
    routine: list.some((r) => (r.routine || 0) > 1),
    D: has('D'), E: has('E'), T: has('T'), HD: has('HD'),
    // Pen は 0.0 でもPDFに印字されるので、値があれば列を出す（0を隠さない）
    Pen: has('Pen'),
    Bonus: list.some((r) => r.Bonus),
    total: has('total'),
    qualifying: list.some((r) => r.qualifying_total !== null && r.qualifying_total !== undefined),
  };
}

function cellNum(v, digits) {
  const t = num(v, digits);
  return el('td', { class: t === null ? 'num blank' : 'num', text: t === null ? '—' : t });
}

function renderTable(list) {
  const col = activeColumns(list);
  const groups = groupByAthlete(list);

  const head = [];
  if (col.rank) head.push(el('th', { class: 'no-sort num', text: 'Rank' }));
  head.push(el('th', { class: 'no-sort', text: 'Name' }));
  if (col.routine) head.push(el('th', { class: 'no-sort', text: 'Rtn' }));
  for (let i = 1; i <= 10; i++) head.push(el('th', { class: 'no-sort num s-col', text: 'S' + i }));
  head.push(el('th', { class: 'no-sort num s-col', text: 'Lnd' }));
  if (col.E) head.push(el('th', { class: 'no-sort num', text: 'Exe' }));
  if (col.D) head.push(el('th', { class: 'no-sort num', text: 'Diff' }));
  if (col.T) head.push(el('th', { class: 'no-sort num', text: 'ToF' }));
  if (col.HD) head.push(el('th', { class: 'no-sort num', text: 'HD' }));
  if (col.Bonus) head.push(el('th', { class: 'no-sort num', text: 'Bonus' }));
  if (col.Pen) head.push(el('th', { class: 'no-sort num', text: 'Pen' }));
  if (col.total) head.push(el('th', { class: 'no-sort num', text: 'Score' }));
  if (col.qualifying) head.push(el('th', { class: 'no-sort num', text: 'Total' }));
  head.push(el('th', { class: 'no-sort' }));

  const body = el('tbody');
  for (const g of groups) {
    g.forEach((r, i) => {
      const det = details[r.performance_id] || {};
      const tr = el('tr', { class: i ? 'pdf-sub' : 'pdf-main' });
      if (col.rank && i === 0) {
        tr.append(el('td', { class: 'num rank', rowspan: g.length, text: r.rank || '' }));
      }
      // 公式PDFと同じ置き方。予選（2本）は1行目に氏名・2行目に所属、
      // 決勝（1本）は1つのセルに氏名と所属を積む。
      if (i === 0) {
        tr.append(el('td', {}, [
          el('span', {
            class: 'link', text: r.athlete_name,
            onclick: () => { location.href = 'athlete.html#' + (r.athlete_id || ''); },
          }),
          g.length === 1 && r.club ? el('div', { class: 'club', text: r.club }) : null,
        ]));
      } else {
        // 所属が無いソース（大阪府）では毎行「—」を出さない。注記で1回言えば足りる
        tr.append(el('td', { class: 'club', text: r.club || '' }));
      }
      if (col.routine) {
        tr.append(el('td', { class: 'rtn', text: r.routine ? 'Q' + r.routine : '' }));
      }
      const n = r.n_elements;
      for (let k = 0; k < 10; k++) {
        const v = (det.positions || [])[k];
        const empty = v === null || v === undefined;
        tr.append(el('td', {
          class: 's-col num' + (empty ? ' blank' : ''),
          title: empty && n !== null && n !== undefined && k >= n ? '技数を超えた位置（跳んでいない）' : null,
          text: empty ? '' : v,
        }));
      }
      const l = det.landing;
      tr.append(el('td', { class: 's-col num' + (l === null || l === undefined ? ' blank' : ''),
        text: l === null || l === undefined ? '' : l }));
      if (col.E) tr.append(cellNum(r.E, 2));
      if (col.D) tr.append(cellNum(r.D, 1));
      if (col.T) tr.append(cellNum(r.T, 2));
      if (col.HD) tr.append(cellNum(r.HD, 2));
      if (col.Bonus) tr.append(cellNum(r.Bonus, 1));
      if (col.Pen) tr.append(cellNum(r.Pen, 1));
      if (col.total) tr.append(cellNum(r.total, 2));
      if (col.qualifying && i === 0) {
        tr.append(el('td', { class: 'num total', rowspan: g.length,
          text: num(g[0].qualifying_total, 2) ?? '—' }));
      }
      tr.append(el('td', {}, [
        r.interrupted ? el('span', { class: 'badge flag', text: '中断' }) : null,
        ...(r.check_flags || []).map((f) => el('span', { class: 'badge flag', text: f })),
        el('span', { class: 'link', text: '詳細', onclick: () => openDetail(r, meet) }),
      ]));
      body.append(tr);
    });
  }
  return el('div', { class: 'table-wrap' },
    el('table', { class: 'pdf-table' }, [el('thead', {}, el('tr', {}, head)), body]));
}

// 狭い画面では表を横スクロールさせず、1選手1カードにする。
function renderCards(groups) {
  return el('div', { class: 'card-list' }, groups.map((g) => {
    const first = g[0];
    return el('article', { class: 'rec' }, [
      el('div', { class: 'rec-head' }, [
        el('span', {}, [
          first.rank ? el('span', { class: 'rec-rank', text: first.rank + '位 ' }) : null,
          el('span', { class: 'link rec-name', text: first.athlete_name,
            onclick: () => { location.href = 'athlete.html#' + (first.athlete_id || ''); } }),
        ]),
        el('span', { class: 'rec-total',
          text: num(first.qualifying_total ?? first.total, 2) ?? '—' }),
      ]),
      first.club ? el('div', { class: 'rec-meta', text: first.club }) : null,
      ...g.map((r) => {
        const det = details[r.performance_id] || {};
        const S = (det.positions || []).map((v) => (v === null || v === undefined ? '·' : v));
        return el('div', { class: 'rec-routine' }, [
          el('div', { class: 'rec-routine-head' }, [
            el('span', { text: g.length > 1 ? 'Q' + r.routine : '演技' }),
            el('span', { class: 'num', text: num(r.total, 2) ?? '—' }),
            r.interrupted ? el('span', { class: 'badge flag', text: '中断' }) : null,
          ]),
          el('div', { class: 'rec-s', text: S.join(' ') + '  ｜ 着地 '
            + (det.landing ?? '·') }),
          el('dl', { class: 'rec-sub' }, [
            ['Exe', num(r.E, 2)], ['Diff', num(r.D, 1)], ['ToF', num(r.T, 2)],
            ['HD', num(r.HD, 2)], ['Pen', num(r.Pen, 1)],
          ].map(([k, v]) => el('div', {}, [
            el('dt', { text: k }),
            el('dd', { class: v === null ? 'blank' : '', text: v ?? '—' }),
          ]))),
          el('button', { class: 'chip', text: '演技の詳細', onclick: () => openDetail(r, meet) }),
        ]);
      }),
    ]);
  }));
}

function renderResult() {
  const card = document.getElementById('result-card');
  if (!state.round || !state.category) { card.hidden = true; return; }
  card.hidden = false;

  const list = rows.filter((r) => r.round === state.round && r.category === state.category);
  document.getElementById('result-title').textContent =
    state.category + '　' + state.round;

  const box = clear(document.getElementById('result'));
  const groups = groupByAthlete(list);
  const cut = isNarrow() && !state.showAllAthletes && groups.length > MOBILE_CHUNK;
  box.append(isNarrow()
    ? renderCards(cut ? groups.slice(0, MOBILE_CHUNK) : groups)
    : renderTable(list));
  if (cut) {
    box.append(el('button', { class: 'more-card',
      onclick: () => { state.showAllAthletes = true; renderResult(); } }, [
      el('span', { class: 'more-name',
        text: '残り ' + (groups.length - MOBILE_CHUNK) + ' 名を表示' }),
      el('span', { class: 'more-sub',
        text: '全 ' + groups.length + ' 名。並びは公式リザルトのまま' }),
    ]));
  }

  const notes = [UNIT_NOTE[meet.source] || ''];
  const col = activeColumns(list);
  if (!col.rank) notes.push('このソースには順位がありません（合計の高い順に並べています）。');
  if (!list.some((r) => r.club)) notes.push('このソースには所属がありません。');
  if (!col.total) notes.push('このラウンドは合計点・D・T が公開されていません。空欄（—）は0点ではありません。');
  const interrupted = list.filter((r) => r.interrupted).length;
  if (interrupted) {
    notes.push('中断した演技が ' + interrupted + ' 件あります。跳んでいない位置のSは空欄です。');
  }
  document.getElementById('result-note').textContent = notes.filter(Boolean).join(' ');

  document.getElementById('csv').onclick = () => downloadCsv(
    meet.name + '_' + state.category + '_' + state.round + '.csv',
    ['順位', '選手', '所属', '演技', ...Array.from({ length: 10 }, (_, i) => 'S' + (i + 1)),
      '着地', 'Exe', 'Diff', 'ToF', 'HD', 'Pen', 'Score', 'Total'],
    groupByAthlete(list).flatMap((g) => g.map((r) => {
      const det = details[r.performance_id] || {};
      return [r.rank || '', r.athlete_name, r.club || '', r.routine || '',
        ...Array.from({ length: 10 }, (_, i) => {
          const v = (det.positions || [])[i];
          return v === null || v === undefined ? '' : v;
        }),
        det.landing ?? '', num(r.E, 2) ?? '', num(r.D, 1) ?? '', num(r.T, 2) ?? '',
        num(r.HD, 2) ?? '', num(r.Pen, 1) ?? '', num(r.total, 2) ?? '',
        num(r.qualifying_total, 2) ?? ''];
    })));
}

function render() {
  renderPicker();
  renderResult();
  updateFab();
}

/** スマホで結果を読み進めたあと、区分の一覧まで戻れるようにする。
 *  区分の一覧が画面から出たときだけ出す（出しっぱなしにすると結果の邪魔になる）。 */
function updateFab() {
  // HTMLだけ古いものがキャッシュに残っていると、このボタンが無い状態でJSが動く。
  // 落とさずに、ボタンが無いだけの画面として成立させる。
  const fab = document.getElementById('back-to-picker');
  if (!fab) return;
  const picker = document.getElementById('picker-card');
  const card = document.getElementById('result-card');
  fab.hidden = !(isNarrow() && !card.hidden
    && picker.getBoundingClientRect().bottom < 0);
}

// ---- 起動 -------------------------------------------------------------------

async function main() {
  mountNav('index.html');
  const fab = document.getElementById('back-to-picker');
  if (fab) fab.onclick = () => scrollToTop(document.getElementById('picker-card'));
  window.addEventListener('scroll', updateFab, { passive: true });
  state.meetId = decodeURIComponent(location.hash.replace(/^#/, ''));
  try {
    const [comps, mf] = await Promise.all([data.competitions(), data.manifest()]);
    manifest = mf;
    meet = comps.find((c) => c.meet_id === state.meetId);
    if (!meet) {
      document.getElementById('app').prepend(errorBox('大会が見つかりません: ' + state.meetId));
      return;
    }

    clear(document.getElementById('meet-head')).append(
      el('h2', { text: meet.name }),
      el('p', { class: 'meta' }, [
        document.createTextNode(meet.date + '　' + meet.level + '　'),
        sourceBadge(meet.official),
        document.createTextNode('　個人 ' + meet.n_individual + '演技'),
      ]),
      meet.source_url
        ? el('p', { class: 'meta' },
          el('a', { href: meet.source_url, target: '_blank', rel: 'noopener', text: '出典を見る' }))
        : null,
    );

    clear(document.getElementById('note-slot')).append(noteLayers(
      '公式リザルトと同じ並びで表示しています',
      [
        el('p', { class: 'meta', text: 'S1〜S10 は技ごとの位置、Lnd は着地です。'
          + '中断した演技では、跳んでいない位置は空欄にしています（0ではありません）。' }),
        el('p', { class: 'meta', text: UNIT_NOTE[meet.source] || '' }),
        el('p', { class: 'meta', text: meet.official
          ? 'このデータは公式リザルト由来です。'
          : 'このデータは大会運営の成績システム由来で、協会公式サイトのものではありません。'
            + '引用するときはその旨を明示してください。' }),
      ]));

    const all = await data.performances();
    rows = all.filter((r) => r.meet_id === state.meetId);
    try {
      details = await data.details(state.meetId);
    } catch (err) {
      details = {};                      // 技別減点が無い大会（そのまま空欄で出す）
    }

    // 既定は決勝から。無ければ最初のラウンド。
    const map = sections();
    state.round = map.has('決勝') ? '決勝' : [...map.keys()][0] || null;

    onWidthChange(() => { renderResult(); updateFab(); });
    window.addEventListener('hashchange', () => location.reload());
    render();
  } catch (err) {
    document.getElementById('app').prepend(errorBox(err.message));
  }
}

main();
