// ページ② ジャッジ分析。
//
// 主語は審判・パネル。問いは「採点のばらつきや審判間の違いはどの程度か」。
// 特定の選手を主役にしない（それはPhase 2）。
//
// 指標は生の平均Eではなく **パネル内差**：
//     審判差 = その審判のE − 同じ演技のパネル中央値
// 生の平均を使うと「強い選手を多く担当した審判の平均が高い」だけになる。
//
// 表示のきまり（Vanさん決定）:
//   ・母数100演技未満の審判は傾向値を出さず「データ不足」と表示する
//   ・審判ランキングは作らない。サマリーカードとフィルタは到達手段であって順位づけではない。
//     既定の並びは母数順で、良し悪しの順ではない
//   ・n・大会数を必ず併記する（中央値・シーズン数・カテゴリは審判の詳細へ）
//   ・「観測された採点差であり、審判の能力評価ではありません」と明記する
//
// ここは表示だけを扱う。集計ルール（パネル中央値差・母数100・±0.10・母集団の条件）は
// ETL側にあり、この画面では変更しない。

import * as data from './data.js';
import {
  el, clear, num, mountNav, downloadCsv, errorBox,
  paginate, renderPager, isNarrow, onWidthChange, noteLayers,
} from './ui.js';

const POPULATIONS = {
  qualified: {
    label: '予選通過者・完遂のみ（既定）',
    note: '準決勝または決勝に進んだ選手の演技のうち、10技を跳びきったものだけを数えています（予選の演技も含みます）。',
  },
  complete: {
    label: '完遂演技のみ',
    note: '10技を跳びきった演技だけを数えています。選手のレベルは絞っていません。',
  },
  all: {
    label: 'すべての演技',
    note: '中断した演技も含めて数えています。中断は減点が大きく出るため、審判間の差が実際より大きく見えることがあります。',
  },
};

// 数字だけでは伝わらないので、二段ラベルにして意味と「意味しないこと」を添える。
const TREND = {
  辛め: { label: '低め傾向（辛め）', cls: 'trend-low' },
  中立: { label: '標準範囲', cls: 'trend-mid' },
  甘め: { label: '高め傾向（甘め）', cls: 'trend-high' },
  データ不足: { label: 'データ不足', cls: 'trend-none' },
};

const DISCLAIMER = '※「選手の最終得点がその分だけ低くなる／高くなる」という意味ではありません。';

// 一覧の傾向バッジこそ誤解されやすいので、詳細だけに置かず、バッジのそばにも意味を添える。
function meaning(e) {
  if (!e.has_trend) {
    return '母数が ' + thresholds.minN + '演技に満たないため、傾向値を出していません。';
  }
  const d = Math.abs(e.mean_diff).toFixed(2);
  const dir = e.mean_diff < 0 ? '低い' : e.mean_diff > 0 ? '高い' : '同じ';
  return '同じ演技を見た他の審判の中心値より、平均 ' + d + '点' + dir + '採点。' + DISCLAIMER;
}

function trendBadge(e) {
  // ホバー（スマホは長押し）で全文が出るようにしておく
  return el('span', {
    class: 'badge ' + TREND[e.trend].cls, text: TREND[e.trend].label, title: meaning(e),
  });
}

/** バッジのすぐ下に置く短い1行。表を崩さない長さにする。 */
function hint(e) {
  if (!e.has_trend) return '母数 ' + thresholds.minN + '演技未満';
  const d = Math.abs(e.mean_diff).toFixed(2);
  const dir = e.mean_diff < 0 ? '低い' : e.mean_diff > 0 ? '高い' : '同じ';
  return '中心値より平均' + d + '点' + dir + '／最終得点が変わる意味ではありません';
}

let diff = null;
let rows = null;
let meets = [];
let meetMap = new Map();
let thresholds = { minN: 100, strict: -0.1, lenient: 0.1 };
const state = { pop: 'qualified', meet: '', category: '', sex: '', round: '', q: '', only: '', page: 1 };

const POP_CODE = { all: [0, 1, 2], complete: [1, 2], qualified: [2] };

function filtered() {
  return state.meet || state.category || state.sex || state.round;
}

// 絞り込みがあるときは、事前集計ではなく生データから平均を取り直す。
// 組み合わせが多すぎて事前に全通り計算できないため。19,000行なので数ミリ秒で終わる。
function recompute() {
  const pops = POP_CODE[state.pop];
  const mi = state.meet ? rows.meets.indexOf(state.meet) : -1;
  const ci = state.category ? rows.categories.indexOf(state.category) : -1;
  const ri = state.round ? rows.rounds.indexOf(state.round) : -1;
  const si = state.sex ? rows.sexes.indexOf(state.sex) : -1;

  const acc = new Map();
  for (const r of rows.rows) {
    if (!pops.includes(r[6])) continue;
    if (mi >= 0 && r[2] !== mi) continue;
    if (ci >= 0 && r[3] !== ci) continue;
    if (si >= 0 && r[4] !== si) continue;
    if (ri >= 0 && r[5] !== ri) continue;
    let a = acc.get(r[0]);
    if (!a) { a = { diffs: [], meets: new Set(), cats: new Set() }; acc.set(r[0], a); }
    a.diffs.push(r[1] / 1000);
    a.meets.add(r[2]);
    a.cats.add(rows.categories[r[3]]);
  }

  const out = [];
  for (const [ji, a] of acc) {
    const j = rows.judges[ji];
    const n = a.diffs.length;
    const mean = a.diffs.reduce((s, v) => s + v, 0) / n;
    const s = [...a.diffs].sort((x, y) => x - y);
    const med = n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
    const sd = Math.sqrt(a.diffs.reduce((t, v) => t + (v - mean) ** 2, 0) / n);
    const enough = n >= thresholds.minN;
    const trend = !enough ? 'データ不足'
      : mean <= thresholds.strict ? '辛め'
      : mean >= thresholds.lenient ? '甘め' : '中立';
    out.push({
      judge_id: j.judge_id, name: j.name, club: j.club, n,
      n_meets: a.meets.size,
      n_seasons: new Set([...a.meets].map((i) => (meetMap.get(rows.meets[i]) || {}).season)).size,
      categories: [...a.cats].sort(),
      mean_diff: enough ? mean : null,
      median_diff: enough ? med : null,
      sd: enough ? sd : null,
      trend, has_trend: enough,
    });
  }
  out.sort((a, b) => b.n - a.n || a.name.localeCompare(b.name, 'ja'));
  return out;
}

function base() {
  return filtered() ? recompute() : diff[state.pop];
}

function visible(entries) {
  let list = entries;
  if (state.only) list = list.filter((e) => e.has_trend && e.trend === state.only);
  if (state.q) {
    const q = state.q.toLowerCase();
    list = list.filter((e) => (e.name || '').toLowerCase().includes(q)
      || (e.club || '').toLowerCase().includes(q));
  }
  return list;
}

function signed(v, digits = 3) {
  if (v === null || v === undefined) return '—';
  return (v >= 0 ? '+' : '') + Number(v).toFixed(digits);
}

// ---- サマリーカードと到達ボタン ---------------------------------------------

function renderSummary(entries) {
  const withTrend = entries.filter((e) => e.has_trend);
  const count = (t) => withTrend.filter((e) => e.trend === t).length;

  clear(document.getElementById('summary')).append(
    card('分析対象', entries.length + '名', '審判が特定できた演技があるすべての審判'),
    card('十分なデータあり', withTrend.length + '名',
      thresholds.minN + '演技以上。これ未満は傾向値を出しません'),
    card('そのうち傾向が明確', null, null, el('div', { class: 'sum-split' }, [
      pill('低め', count('辛め'), 'trend-low'),
      pill('標準', count('中立'), 'trend-mid'),
      pill('高め', count('甘め'), 'trend-high'),
    ])),
  );

  const quick = clear(document.getElementById('quick'));
  const btn = (label, only) => el('button', {
    class: 'chip', 'aria-pressed': String(state.only === only),
    text: label,
    onclick: () => { state.only = state.only === only ? '' : only; state.page = 1; render(); },
  });
  quick.append(
    btn('低め' + count('辛め') + '名を見る', '辛め'),
    btn('高め' + count('甘め') + '名を見る', '甘め'),
    el('button', {
      class: 'chip', 'aria-pressed': String(!state.only), text: '全審判を見る',
      onclick: () => { state.only = ''; state.page = 1; render(); },
    }),
  );
}

function card(title, value, note, extra) {
  return el('div', { class: 'sum-card' }, [
    el('div', { class: 'sum-title', text: title }),
    value ? el('div', { class: 'sum-value', text: value }) : null,
    extra || null,
    note ? el('div', { class: 'sum-note', text: note }) : null,
  ]);
}

function pill(label, n, cls) {
  return el('span', { class: 'sum-pill ' + cls }, [
    el('span', { class: 'sum-pill-label', text: label }),
    el('span', { class: 'sum-pill-n', text: n }),
  ]);
}

// ---- 一覧（6列） -------------------------------------------------------------

const COLUMNS = ['審判', '演技数(n)', '大会数', '平均パネル差', 'ばらつき', '傾向'];

function renderTable(items) {
  return el('div', { class: 'table-wrap' }, el('table', {}, [
    el('thead', {}, el('tr', {}, COLUMNS.map((c, i) =>
      el('th', { class: 'no-sort' + (i >= 1 && i <= 4 ? ' num' : ''), text: c })))),
    el('tbody', {}, items.map((e) => el('tr', {}, [
      el('td', {}, [
        el('span', { class: 'link', text: e.name || '（氏名なし）', onclick: () => openJudge(e) }),
        e.club ? el('div', { class: 'meta small', text: e.club }) : null,
      ]),
      el('td', { class: 'num', text: e.n }),
      el('td', { class: 'num', text: e.n_meets }),
      el('td', { class: e.has_trend ? 'num' : 'num blank', text: e.has_trend ? signed(e.mean_diff) : '—' }),
      el('td', { class: e.has_trend ? 'num' : 'num blank', text: e.has_trend ? num(e.sd, 3) : '—' }),
      el('td', {}, [
        trendBadge(e),
        el('div', { class: 'meta small trend-hint', text: hint(e) }),
      ]),
    ]))),
  ]));
}

function renderCards(items) {
  return el('div', { class: 'card-list' }, items.map((e) => el('article', { class: 'rec' }, [
    el('div', { class: 'rec-head' }, [
      el('span', { class: 'link rec-name', text: e.name || '（氏名なし）', onclick: () => openJudge(e) }),
      trendBadge(e),
    ]),
    el('div', { class: 'meta small trend-hint', text: hint(e) }),
    e.club ? el('div', { class: 'rec-meta', text: e.club }) : null,
    el('dl', { class: 'rec-sub' }, [
      ['演技数(n)', e.n], ['大会数', e.n_meets],
      ['平均パネル差', e.has_trend ? signed(e.mean_diff) : null],
      ['ばらつき', e.has_trend ? num(e.sd, 3) : null],
    ].flatMap(([k, v]) => [
      el('dt', { text: k }),
      el('dd', { class: v === null || v === undefined ? 'blank' : '', text: v ?? '—' }),
    ])),
    el('button', { class: 'chip', text: 'この審判の詳細', onclick: () => openJudge(e) }),
  ])));
}

// ---- 審判の詳細 -------------------------------------------------------------

let dialog = null;

function openJudge(e) {
  if (!dialog) {
    dialog = el('dialog', {}, [
      el('div', { class: 'modal-head' }, [
        el('div', { id: 'judge-title' }),
        el('button', { class: 'chip', text: '閉じる', onclick: () => dialog.close() }),
      ]),
      el('div', { class: 'modal-body', id: 'judge-body' }),
    ]);
    document.body.append(dialog);
  }
  const title = clear(document.getElementById('judge-title'));
  const body = clear(document.getElementById('judge-body'));
  title.append(
    el('div', { text: e.name || '（氏名なし）' }),
    e.club ? el('div', { class: 'meta', text: e.club }) : null,
  );

  // 二段ラベル。数字の意味と、意味しないことを添える。
  body.append(el('div', { class: 'trend-block ' + TREND[e.trend].cls }, [
    el('div', { class: 'trend-label', text: TREND[e.trend].label }),
    e.has_trend
      ? el('div', {}, [
        el('div', { class: 'trend-value', text: '平均パネル差 ' + signed(e.mean_diff, 2) }),
        el('div', { class: 'trend-desc', text: '同じ演技を見た他の審判の中心値より、平均 '
          + Math.abs(e.mean_diff).toFixed(2) + '点'
          + (e.mean_diff < 0 ? '低い' : e.mean_diff > 0 ? '高い' : '同じ') + '採点' }),
        el('div', { class: 'trend-warn', text: DISCLAIMER }),
      ])
      : el('div', { class: 'trend-desc', text: '母数が ' + thresholds.minN
        + '演技に満たないため、傾向値は出していません。少ない演技数では、審判の傾向と、'
        + 'たまたま担当した演技のばらつきを区別できないためです。' }),
  ]));

  body.append(el('h3', { text: '内訳' }));
  body.append(el('div', { class: 'kv' }, [
    ['演技数 n', e.n], ['大会数', e.n_meets], ['シーズン数', e.n_seasons],
    ['中央値パネル差', e.has_trend ? signed(e.median_diff, 2) : '—'],
    ['ばらつき（標準偏差）', e.has_trend ? num(e.sd, 3) : '—'],
  ].map(([k, v]) => el('div', {}, [
    el('div', { class: 'k', text: k }), el('div', { class: 'v', text: v ?? '—' }),
  ]))));

  body.append(el('h3', { text: '担当したカテゴリ' }));
  body.append(el('div', { class: 'tag-row' },
    (e.categories || []).map((c) => el('span', { class: 'badge plain', text: c }))));

  body.append(el('h3', { text: '今見ている条件' }));
  body.append(el('p', { class: 'meta', text: conditionText() }));
  body.append(el('p', { class: 'meta', text: '観測された採点差であり、審判の能力評価ではありません。' }));
  dialog.showModal();
}

// ---- 条件表示 ---------------------------------------------------------------

function conditionText() {
  const extra = [
    state.meet ? '大会：' + ((meetMap.get(state.meet) || {}).name || state.meet) : null,
    state.category ? '区分：' + state.category : null,
    state.sex ? '男女：' + (state.sex === 'male' ? '男子' : '女子') : null,
    state.round ? 'ラウンド：' + state.round : null,
  ].filter(Boolean);
  return POPULATIONS[state.pop].label + (extra.length ? '／' + extra.join('／') : '');
}

// ---- 描画 -------------------------------------------------------------------

function render() {
  const entries = base();
  renderSummary(entries);

  const list = visible(entries);
  const view = paginate(list, state.page);
  state.page = view.page;

  const box = clear(document.getElementById('judges'));
  box.append(isNarrow() ? renderCards(view.items) : renderTable(view.items));
  if (!list.length) {
    box.append(el('p', { class: 'meta', text: '条件に当てはまる審判がいません。' }));
  }

  for (const id of ['pager-top', 'pager-bottom']) {
    renderPager(document.getElementById(id), view, entries.length, (p) => {
      state.page = p; render();
      document.getElementById('list-title').scrollIntoView({ block: 'start' });
    });
  }

  const only = state.only ? TREND[state.only].label + 'の審判' : '審判一覧';
  document.getElementById('list-title').textContent = state.q ? '「' + state.q + '」の検索結果' : only;
  document.getElementById('condition').textContent = '今見ている条件：' + conditionText();
  document.getElementById('condition-note').textContent = POPULATIONS[state.pop].note;

  const short = entries.filter((e) => !e.has_trend).length;
  if (short && !state.only) {
    box.append(el('p', { class: 'meta', text: '母数が ' + thresholds.minN + '演技に満たない '
      + short + '名は「データ不足」として傾向値を出していません。' }));
  }
}

function renderCoverage() {
  const box = clear(document.getElementById('coverage'));
  const withNames = meets.filter((c) => c.has_judge_names);
  const without = meets.filter((c) => !c.has_judge_names);
  box.append(el('p', { class: 'meta',
    text: '審判の氏名が公開されているのは ' + meets.length + ' 大会中 ' + withNames.length + ' 大会です。'
      + 'データが無いことは、問題が無いことを意味しません。' }));
  box.append(el('ul', { class: 'meta' }, without.map((c) =>
    el('li', { text: c.date + '　' + c.name + '（' + c.source + '）' }))));
}

function fill(id, pairs, label) {
  const sel = clear(document.getElementById(id));
  sel.append(el('option', { value: '', text: label }));
  for (const [value, text] of pairs) sel.append(el('option', { value, text }));
}

function buildNote() {
  clear(document.getElementById('note-slot')).append(noteLayers(
    '同じ演技を見た審判どうしの採点の差です。審判の能力評価ではありません',
    [
      el('p', { class: 'meta', text: '指標は生の平均Eではなくパネル内差（その審判のE − 同じ演技のパネル中央値）です。'
        + '生の平均を使うと、強い選手を多く担当した審判の平均が高く出てしまうためです。' }),
      el('p', { class: 'meta', text: '順位づけはしていません。並び順は母数の多い順で、良し悪しの順ではありません。'
        + '母数100演技未満の審判は傾向値を出していません。' }),
      el('p', { class: 'meta', text: '国内大会は日本語表記、国際大会はローマ字表記で審判名が記録されているため、'
        + '両方で審判をしている人が別々に並ぶことがあります。推測で結合すると別人を混ぜる恐れがあるため、'
        + '人が確認するまで分けたままにしています。' }),
      el('p', { class: 'meta' }, el('a', { href: 'about.html', text: 'データについて（出典・欠測・分析の限界）→' })),
    ]));
}

async function main() {
  mountNav('judges.html');
  try {
    const [d, ms, manifest, rw] = await Promise.all([
      data.judgeDiff(), data.competitions(), data.manifest(), data.judgeDiffRows(),
    ]);
    diff = d; rows = rw; meets = ms;
    meetMap = new Map(ms.map((c) => [c.meet_id, c]));
    thresholds = manifest.judgeThresholds;

    buildNote();

    const toggle = document.getElementById('toggle-filters');
    toggle.addEventListener('click', () => {
      const box = document.getElementById('filters');
      box.hidden = !box.hidden;
      toggle.setAttribute('aria-expanded', String(!box.hidden));
      toggle.textContent = box.hidden ? '条件を変える ▼' : '条件を閉じる ▲';
      document.getElementById('reset').hidden = box.hidden;
    });

    const picker = clear(document.getElementById('pop'));
    for (const [key, v] of Object.entries(POPULATIONS)) {
      picker.append(el('option', { value: key, text: v.label }));
    }
    picker.value = state.pop;
    picker.addEventListener('change', () => { state.pop = picker.value; state.page = 1; render(); });

    const judgeMeets = ms.filter((c) => rows.meets.includes(c.meet_id));
    fill('f-meet', judgeMeets.map((c) => [c.meet_id, c.date + ' ' + c.name]), '大会（すべて）');
    fill('f-category', [...rows.categories].sort().map((c) => [c, c]), '区分（すべて）');
    fill('f-sex', [['male', '男子'], ['female', '女子']], '男女（すべて）');
    fill('f-round', rows.rounds.filter(Boolean).map((r) => [r, r]), 'ラウンド（すべて）');
    for (const [id, key] of [['f-meet', 'meet'], ['f-category', 'category'],
      ['f-sex', 'sex'], ['f-round', 'round']]) {
      const node = document.getElementById(id);
      node.addEventListener('change', () => { state[key] = node.value; state.page = 1; render(); });
    }

    const jq = document.getElementById('jq');
    jq.addEventListener('input', () => { state.q = jq.value.trim(); state.page = 1; render(); });

    document.getElementById('reset').addEventListener('click', () => {
      Object.assign(state, { meet: '', category: '', sex: '', round: '', q: '', only: '', page: 1 });
      for (const id of ['f-meet', 'f-category', 'f-sex', 'f-round']) {
        document.getElementById(id).value = '';
      }
      jq.value = '';
      render();
    });

    document.getElementById('csv').addEventListener('click', () => {
      const list = visible(base());
      downloadCsv('ジャッジ分析_' + state.pop + '.csv',
        ['審判', '所属', 'n', '大会数', 'シーズン数', '平均パネル差', '中央値パネル差', '標準偏差', '傾向', 'カテゴリ'],
        list.map((e) => [e.name, e.club, e.n, e.n_meets, e.n_seasons,
          e.has_trend ? e.mean_diff : '', e.has_trend ? e.median_diff : '',
          e.has_trend ? e.sd : '', TREND[e.trend].label, (e.categories || []).join('｜')]));
    });

    onWidthChange(() => render());
    render();
    renderCoverage();
  } catch (err) {
    document.getElementById('app').prepend(errorBox(err.message));
  }
}

main();
