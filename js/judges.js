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
//   ・審判ランキングは作らない（既定の並びは母数順で、良し悪しの順ではない）
//   ・n・大会数・シーズン数・カテゴリを必ず併記する
//   ・「観測された採点差であり、審判の能力評価ではありません」と明記する

import * as data from './data.js';
import { el, clear, num, mountNav, downloadCsv, errorBox } from './ui.js';

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

let diff = null;
let meets = [];
let state = { pop: 'qualified', meet: '', category: '', sex: '', round: '' };

function render() {
  const entries = diff[state.pop];
  const box = clear(document.getElementById('judges'));

  const withTrend = entries.filter((e) => e.has_trend);
  const without = entries.filter((e) => !e.has_trend);

  document.getElementById('condition').textContent =
    '今見ている条件：' + POPULATIONS[state.pop].label;
  document.getElementById('condition-note').textContent = POPULATIONS[state.pop].note;
  document.getElementById('summary').textContent =
    '審判 ' + entries.length + ' 名／このうち母数100演技以上は ' + withTrend.length + ' 名'
    + '（辛め ' + withTrend.filter((e) => e.trend === '辛め').length
    + '・中立 ' + withTrend.filter((e) => e.trend === '中立').length
    + '・甘め ' + withTrend.filter((e) => e.trend === '甘め').length + '）';

  box.append(el('div', { class: 'table-wrap' }, el('table', {}, [
    el('thead', {}, el('tr', {}, [
      el('th', { class: 'no-sort', text: '審判' }),
      el('th', { class: 'no-sort', text: '所属' }),
      el('th', { class: 'no-sort num', text: 'n（演技）' }),
      el('th', { class: 'no-sort num', text: '大会' }),
      el('th', { class: 'no-sort num', text: 'シーズン' }),
      el('th', { class: 'no-sort num', text: '平均パネル差' }),
      el('th', { class: 'no-sort num', text: '中央値パネル差' }),
      el('th', { class: 'no-sort num', text: '標準偏差' }),
      el('th', { class: 'no-sort', text: '傾向' }),
      el('th', { class: 'no-sort', text: 'カテゴリ' }),
    ])),
    el('tbody', {}, entries.map((e) => el('tr', {}, [
      el('td', { text: e.name || '（氏名なし）' }),
      el('td', { class: 'meta', text: e.club || '—' }),
      el('td', { class: 'num', text: e.n }),
      el('td', { class: 'num', text: e.n_meets }),
      el('td', { class: 'num', text: e.n_seasons }),
      el('td', { class: e.has_trend ? 'num' : 'num blank',
        text: e.has_trend ? signed(e.mean_diff) : '—' }),
      el('td', { class: e.has_trend ? 'num' : 'num blank',
        text: e.has_trend ? signed(e.median_diff) : '—' }),
      el('td', { class: e.has_trend ? 'num' : 'num blank',
        text: e.has_trend ? num(e.sd, 3) : '—' }),
      el('td', {}, el('span', {
        class: 'badge ' + (e.has_trend ? 'plain' : 'flag'),
        text: e.trend,
      })),
      el('td', { class: 'meta', text: (e.categories || []).slice(0, 4).join('、')
        + ((e.categories || []).length > 4 ? ' ほか' : '') }),
    ]))),
  ])));

  if (without.length) {
    box.append(el('p', { class: 'meta',
      text: '母数が100演技に満たない ' + without.length
        + ' 名は「データ不足」として傾向値を出していません。少ない演技数では、'
        + '審判の傾向と、たまたま担当した演技のばらつきを区別できないためです。' }));
  }
}

function signed(v) {
  if (v === null || v === undefined) return '—';
  return (v >= 0 ? '+' : '') + Number(v).toFixed(3);
}

function renderCoverage() {
  const box = clear(document.getElementById('coverage'));
  const withNames = meets.filter((c) => c.has_judge_names);
  const without = meets.filter((c) => !c.has_judge_names);
  box.append(el('p', { class: 'meta',
    text: '審判の氏名が公開されているのは ' + meets.length + ' 大会中 ' + withNames.length + ' 大会です。' }));
  box.append(el('div', { class: 'notice',
    text: '下の大会は審判の氏名が公開されていないため、この分析に入っていません。'
      + 'データが無いことは、問題が無いことを意味しません。' }));
  box.append(el('ul', { class: 'meta' }, without.map((c) =>
    el('li', { text: c.date + '　' + c.name + '（' + c.source + '）' }))));
}

async function main() {
  mountNav('judges.html');
  try {
    const [d, ms, manifest] = await Promise.all([
      data.judgeDiff(), data.competitions(), data.manifest(),
    ]);
    diff = d;
    meets = ms;
    document.getElementById('dataversion').textContent =
      'データ ' + manifest.dataVersion + '／判定の閾値 平均パネル差 ±'
      + Math.abs(manifest.judgeThresholds.lenient) + '／母数の下限 '
      + manifest.judgeThresholds.minN + ' 演技';

    const picker = document.getElementById('pop');
    for (const [key, v] of Object.entries(POPULATIONS)) {
      picker.append(el('option', { value: key, text: v.label }));
    }
    picker.value = state.pop;
    picker.addEventListener('change', () => { state.pop = picker.value; render(); });

    document.getElementById('csv').addEventListener('click', () => {
      downloadCsv('ジャッジ分析_' + state.pop + '.csv',
        ['審判', '所属', 'n', '大会数', 'シーズン数', '平均パネル差', '中央値パネル差', '標準偏差', '傾向', 'カテゴリ'],
        diff[state.pop].map((e) => [e.name, e.club, e.n, e.n_meets, e.n_seasons,
          e.has_trend ? e.mean_diff : '', e.has_trend ? e.median_diff : '',
          e.has_trend ? e.sd : '', e.trend, (e.categories || []).join('｜')]));
    });

    render();
    renderCoverage();
  } catch (err) {
    document.getElementById('app').prepend(errorBox(err.message));
  }
}

main();
