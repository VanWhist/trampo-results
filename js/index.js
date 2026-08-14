// ページ① リザルトデータベース。事実データを見る場所で、分析はしない。

import * as data from './data.js';
import { el, clear, cell, num, sourceBadge, mountNav, makeSortable, downloadCsv, errorBox } from './ui.js';
import { openDetail } from './detail.js';

const state = { q: '', year: '', meet: '', category: '', round: '', routine: '' };
let rows = [];
let meets = new Map();
let sorter = null;

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

function renderRows(list) {
  const tbody = clear(document.getElementById('tbody'));
  const frag = document.createDocumentFragment();
  for (const p of list.slice(0, 3000)) {
    const meet = meets.get(p.meet_id);
    const tr = el('tr', {}, [
      el('td', { text: p.date }),
      el('td', {}, [
        document.createTextNode(p.meet_name + ' '),
        sourceBadge(p.official),
      ]),
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
      el('td', { class: 'num', text: p.n_elements === null || p.n_elements === undefined ? '—' : p.n_elements }),
      el('td', {}, [
        p.interrupted ? el('span', { class: 'badge flag', text: '中断' }) : null,
        ...(p.check_flags || []).map((f) => el('span', { class: 'badge flag', text: f })),
        el('span', { class: 'link', text: ' 詳細', onclick: () => openDetail(p, meet) }),
      ]),
    ]);
    frag.append(tr);
  }
  tbody.append(frag);
  const shown = Math.min(list.length, 3000);
  document.getElementById('count').textContent =
    list.length + ' 件' + (list.length > shown ? '（表示は先頭 ' + shown + ' 件）' : '');
  const missing = {
    total: list.filter((p) => p.total === null || p.total === undefined).length,
    rank: list.filter((p) => !p.rank).length,
    club: list.filter((p) => !p.club).length,
    interrupted: list.filter((p) => p.interrupted).length,
  };
  document.getElementById('missing').textContent =
    '欠測：合計点 ' + missing.total + ' 件／順位 ' + missing.rank + ' 件／所属 '
    + missing.club + ' 件　中断演技 ' + missing.interrupted + ' 件';
}

function apply() {
  const list = rows.filter(matches);
  sorter.update(list);
  return list;
}

function fillSelect(id, values, label) {
  const sel = document.getElementById(id);
  clear(sel);
  sel.append(el('option', { value: '', text: label }));
  for (const v of values) sel.append(el('option', { value: v.value, text: v.text }));
}

async function main() {
  mountNav('index.html');
  const app = document.getElementById('app');
  try {
    const [perfs, meetList, manifest] = await Promise.all([
      data.performances(), data.competitions(), data.manifest(),
    ]);
    meets = new Map(meetList.map((c) => [c.meet_id, c]));
    rows = perfs;
    document.getElementById('dataversion').textContent =
      'データ ' + manifest.dataVersion + '／' + manifest.validation.summary;

    fillSelect('f-year', [...new Set(rows.map((p) => p.season))].sort()
      .map((v) => ({ value: v, text: v + '年' })), '年（すべて）');
    fillSelect('f-meet', meetList.map((c) => ({ value: c.meet_id, text: c.date + ' ' + c.name })),
      '大会（すべて）');
    fillSelect('f-category', [...new Set(rows.map((p) => p.category))].sort()
      .map((v) => ({ value: v, text: v })), '区分（すべて）');
    fillSelect('f-round', [...new Set(rows.map((p) => p.round).filter(Boolean))]
      .map((v) => ({ value: v, text: v })), 'ラウンド（すべて）');
    fillSelect('f-routine', [...new Set(rows.map((p) => p.routine).filter(Boolean))].sort()
      .map((v) => ({ value: String(v), text: v + '本目' })), '演技（すべて）');

    sorter = makeSortable(document.getElementById('table'), rows, renderRows,
      { key: 'date', dir: -1 });

    for (const [id, key] of [['q', 'q'], ['f-year', 'year'], ['f-meet', 'meet'],
      ['f-category', 'category'], ['f-round', 'round'], ['f-routine', 'routine']]) {
      const node = document.getElementById(id);
      node.addEventListener('input', () => { state[key] = node.value; apply(); });
    }
    document.getElementById('reset').addEventListener('click', () => {
      for (const k of Object.keys(state)) state[k] = '';
      for (const id of ['q', 'f-year', 'f-meet', 'f-category', 'f-round', 'f-routine']) {
        document.getElementById(id).value = '';
      }
      apply();
    });
    document.getElementById('csv').addEventListener('click', () => {
      const list = rows.filter(matches);
      downloadCsv('リザルト_' + manifest.dataVersion + '.csv',
        ['大会日', '大会名', '出典', '公式', '区分', 'ラウンド', '演技', '選手', '所属',
          '順位', '合計', 'D', 'E', 'T', 'HD', '技数', '中断', '要確認'],
        list.map((p) => [p.date, p.meet_name, p.source, p.official ? '公式' : '非公式',
          p.category, p.round || '', p.routine || '', p.athlete_name, p.club || '',
          p.rank || '', num(p.total, 2) ?? '', num(p.D, 1) ?? '', num(p.E, 1) ?? '',
          num(p.T, 2) ?? '', num(p.HD, 2) ?? '',
          p.n_elements === null || p.n_elements === undefined ? '' : p.n_elements,
          p.interrupted ? '中断' : '', (p.check_flags || []).join(' ')]));
    });
    apply();
  } catch (err) {
    app.prepend(errorBox(err.message));
  }
}

main();
