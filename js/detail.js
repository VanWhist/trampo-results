// 演技詳細。一覧・選手ページのどちらからも開く。
//
// 表示のきまり:
//   ・技別減点はスロット1〜技数まで。技数を超えた位置は「空欄」にする（0と表示しない）
//   ・中断演技は「中断（技数6）」と明示する
//   ・審判別Eが無い大会は「審判別データなし」と明示する。無いことを隠さない

import * as data from './data.js';
import { el, clear, num, sourceBadge } from './ui.js';

let dialog = null;

function ensureDialog() {
  if (dialog) return dialog;
  dialog = el('dialog', {}, [
    el('div', { class: 'modal-head' }, [
      el('div', { id: 'detail-title' }),
      el('button', { class: 'chip', text: '閉じる', onclick: () => dialog.close() }),
    ]),
    el('div', { class: 'modal-body', id: 'detail-body' }),
  ]);
  document.body.append(dialog);
  return dialog;
}

function positionGrid(det) {
  const n = det.n_elements;
  const head = el('div', { class: 'pos-grid' });
  const vals = el('div', { class: 'pos-grid' });
  for (let i = 0; i < 10; i++) {
    head.append(el('div', { class: 'head', text: 'S' + (i + 1) }));
    const v = det.positions[i];
    // 技数を超えた位置は 0 ではなく空欄。跳んでいない技の減点を見せないため。
    vals.append(el('div', { class: 'val' + (v === null || v === undefined ? ' empty' : ''),
      text: v === null || v === undefined ? '-' : v }));
  }
  head.append(el('div', { class: 'head', text: '着地' }));
  const l = det.landing;
  vals.append(el('div', { class: 'val' + (l === null || l === undefined ? ' empty' : ''),
    text: l === null || l === undefined ? '-' : l }));
  const wrap = el('div', { class: 'table-wrap' }, [head, vals]);
  const notes = [];
  if (n !== null && n !== undefined && n < 10) {
    notes.push('技数を超えた S' + (n + 1) + '〜S10 は空欄です（跳んでいないため）。');
  }
  if (det.landing === null && n !== null && n < 10) {
    notes.push('中断演技では着地減点が実施点に加算されないため、着地も空欄です。');
  }
  if (det.unaccounted) {
    notes.push('元データに技数を超えた位置の減点が ' + det.unaccounted
      + '（0.1点単位）記録されていました。実施点にも位置別集計にも入れていません。');
  }
  const unit = det.unit === 'median2_sum_tenths'
    ? '数値は中央2審判の減点の和（0.1点単位）です。'
    : '数値は減点（0.1点単位）です。';
  notes.push(unit);
  return [wrap, el('p', { class: 'meta', text: notes.join(' ') })];
}

function judgeBlock(det, meet, panel, judgeMap) {
  const entries = Object.entries(det.judge_E || {});
  if (!entries.length) {
    return el('p', { class: 'meta', text: '審判別データなし（この大会は審判ごとのEが公開されていません）' });
  }
  const perJudge = det.judge_E_unit === 'single_judge_execution_score';
  const named = panel && panel.e_slots;
  const table = el('table', {}, [
    el('thead', {}, el('tr', {}, [
      el('th', { class: 'no-sort', text: '審判' }),
      named ? el('th', { class: 'no-sort', text: '氏名' }) : null,
      el('th', { class: 'no-sort num', text: perJudge ? '実施点（1人ぶん）' : 'E' }),
    ].filter(Boolean))),
    el('tbody', {}, entries.map(([k, v]) => {
      const jid = named ? panel.e_slots[k] : null;
      const j = jid ? judgeMap.get(jid) : null;
      return el('tr', {}, [
        el('td', { text: k }),
        named ? el('td', { class: j ? '' : 'blank',
          text: j ? j.name + (j.club ? '（' + j.club + '）' : '') : '—' }) : null,
        el('td', { class: 'num', text: num(v, 1) }),
      ].filter(Boolean));
    })),
  ]);
  const hd = Object.entries(det.judge_HD || {});
  const parts = [el('div', { class: 'table-wrap' }, table)];
  if (hd.length) {
    parts.push(el('p', { class: 'meta', text: '水平移動の審判： '
      + hd.map(([k, v]) => k + ' ' + num(v, 1)).join(' / ') }));
  }
  if (!det.panel_key) {
    // 「大会に審判名が無い」のか「このラウンドのパネル配置だけ記録が無い」のかを区別する。
    parts.push(el('p', { class: 'meta', text: meet.has_judge_names
      ? 'この大会の審判名は公開されていますが、このラウンドのパネル（どのスロットを誰が担当したか）が'
        + '元データに記録されていないため、誰の採点かは特定できません。'
      : 'この大会は審判の氏名が公開されていないため、誰の採点かは分かりません。' }));
  }
  return el('div', {}, parts);
}

export async function openDetail(perf, meet, athlete) {
  const dlg = ensureDialog();
  const title = clear(document.getElementById('detail-title'));
  const body = clear(document.getElementById('detail-body'));

  const interrupted = perf.n_elements !== null && perf.n_elements !== undefined
    && perf.n_elements < 10;
  title.append(
    el('div', { text: perf.athlete_name }),
    el('div', { class: 'meta', text: meet.date + '　' + meet.name }),
    el('div', { class: 'tag-row' }, [
      el('span', { class: 'badge plain', text: perf.category }),
      perf.round ? el('span', { class: 'badge plain', text: perf.round }) : null,
      perf.routine ? el('span', { class: 'badge plain', text: perf.routine + '本目' }) : null,
      sourceBadge(meet.official),
      interrupted ? el('span', { class: 'badge flag', text: '中断（技数' + perf.n_elements + '）' }) : null,
      ...(perf.check_flags || []).map((f) => el('span', { class: 'badge flag', text: f })),
    ]),
  );

  dlg.showModal();
  body.append(el('div', { class: 'kv' }, [
    ['合計', perf.total, 2], ['D', perf.D, 1], ['E', perf.E, 1],
    ['T', perf.T, 2], ['HD', perf.HD, 2], ['Pen', perf.Pen, 1],
  ].map(([k, v, d]) => el('div', {}, [
    el('div', { class: 'k', text: k }),
    el('div', { class: 'v', text: num(v, d) ?? '—' }),
  ]))));
  if (perf.rank) body.append(el('p', { class: 'meta', text: '順位 ' + perf.rank + '位' }));
  if (perf.total === null || perf.total === undefined) {
    body.append(el('div', { class: 'notice',
      text: 'この大会・ラウンドでは合計点・D・T・順位が公開されていないため空欄です（推測では埋めていません）。' }));
  }

  body.append(el('h3', { text: '技別減点' }));
  const holder = el('div', { text: '読み込み中…' });
  body.append(holder);
  body.append(el('h3', { text: '審判別E' }));
  const judgeHolder = el('div', { text: '読み込み中…' });
  body.append(judgeHolder);

  body.append(el('h3', { text: '出典' }));
  body.append(el('p', { class: 'meta' }, [
    meet.source_url
      ? el('a', { href: meet.source_url, target: '_blank', rel: 'noopener', text: meet.source_url })
      : meet.name,
    el('br'),
    meet.official ? '公式（' + meet.source + '）'
      : '非公式の成績システム由来です。公式リザルトとして引用するときはその旨を明示してください。',
  ]));

  try {
    const all = await data.details(perf.meet_id);
    const det = all[perf.performance_id];
    clear(holder);
    clear(judgeHolder);
    if (!det) {
      holder.append(el('p', { class: 'meta', text: '技別減点なし（この大会は技ごとの減点が公開されていません）' }));
      judgeHolder.append(el('p', { class: 'meta', text: '審判別データなし' }));
      return;
    }
    for (const node of positionGrid(det)) holder.append(node);
    let panel = null;
    let judgeMap = new Map();
    if (det.panel_key) {
      const [allPanels, allJudges] = await Promise.all([data.panels(), data.judges()]);
      panel = allPanels[det.panel_key] || null;
      judgeMap = new Map(Object.entries(allJudges));
    }
    judgeHolder.append(judgeBlock(det, meet, panel, judgeMap));
  } catch (err) {
    clear(holder).append(el('p', { class: 'meta', text: '詳細を読めませんでした：' + err.message }));
    clear(judgeHolder);
  }
}
