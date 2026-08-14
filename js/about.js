// 「データについて」ページ＝注記の第3層。
// 各画面には要点1行だけを出し、詳しい話はここに集約する。注記を消したわけではない。

import * as data from './data.js';
import { el, clear, mountNav, errorBox, sourceBadge } from './ui.js';

function table(head, body) {
  return el('div', { class: 'table-wrap' }, el('table', {}, [
    el('thead', {}, el('tr', {}, head.map((h, i) =>
      el('th', { class: 'no-sort' + (i ? ' num' : ''), text: h })))),
    el('tbody', {}, body.map((r) => el('tr', {}, r.map((c, i) =>
      el('td', { class: i ? 'num' : '', text: c }))))),
  ]));
}

async function main() {
  mountNav('about.html');
  try {
    const [m, comps] = await Promise.all([data.manifest(), data.competitions()]);
    const n = m.validation.notes;

    clear(document.getElementById('status')).append(el('div', { class: 'kv' }, [
      ['データ更新日', m.dataVersion],
      ['大会', m.counts.competitions],
      ['選手', m.counts.athletes.toLocaleString('ja-JP')],
      ['演技（個人）', m.counts.individual.toLocaleString('ja-JP')],
      ['演技（全種目）', m.counts.performances.toLocaleString('ja-JP')],
      ['審判', m.counts.judges],
    ].map(([k, v]) => el('div', {}, [
      el('div', { class: 'k', text: k }), el('div', { class: 'v', text: v }),
    ]))));

    const src = clear(document.getElementById('sources'));
    for (const [key, s] of Object.entries(m.sources)) {
      const list = comps.filter((c) => c.source === key);
      src.append(el('p', {}, [
        el('strong', { text: s.label }), ' ',
        sourceBadge(s.official), ' ',
        el('span', { class: 'meta', text: list.length + '大会／個人 '
          + list.reduce((t, c) => t + c.n_individual, 0).toLocaleString('ja-JP') + '演技' }),
      ]));
    }

    clear(document.getElementById('meets')).append(el('details', {}, [
      el('summary', { text: '収録している大会の一覧（' + comps.length + '大会）' }),
      table(['大会日 / 大会名 / 出典', '個人演技', '審判名'],
        comps.map((c) => [c.date + '　' + c.name + '（' + (c.official ? '公式' : '非公式') + '）',
          c.n_individual, c.has_judge_names ? 'あり' : 'なし'])),
    ]));

    clear(document.getElementById('missing')).append(table(
      ['欠測', '件数'],
      [['合計点・D・T（大阪府の決勝）', n['欠測_合計点']],
        ['順位（大阪府）', n['欠測_順位']],
        ['所属（大阪府）', n['欠測_所属']],
        ['技数（大阪府の表示が壊れていた行）', n['欠測_技数']],
        ['中断演技（技数10未満）', n['中断演技']],
        ['表示が壊れた行（集計から除外）', n['表示が壊れた行(大阪府)']]]));

    clear(document.getElementById('etl')).append(
      el('pre', { class: 'code', text: m.validation.summary }),
      table(['項目', '値'], Object.entries(n).map(([k, v]) => [k, v])),
      el('p', { class: 'meta', text: 'parser ' + m.parserVersion + '／生成 ' + m.generatedAt
        + '／Phase ' + m.phase }),
      el('p', { class: 'meta', text: '警告（warnings）は「人が見て決めること」の置き場です。'
        + 'エラー（errors）が0でない状態のデータは公開していません。' }),
    );
  } catch (err) {
    document.getElementById('app').prepend(errorBox(err.message));
  }
}

main();
