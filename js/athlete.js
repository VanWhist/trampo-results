// ページ 選手。Vanさんが一番使う画面。
// その選手の全大会の出場履歴と、所属の履歴（転籍が見える）を出す。

import * as data from './data.js';
import {
  el, rulesBadge, clear, cell, num, sourceBadge, mountNav, makeSortable, downloadCsv, errorBox,
  isNarrow, onWidthChange, noteLayers,
} from './ui.js';
import { openDetail } from './detail.js';

let athletes = [];
let perfs = [];
let meets = new Map();

function renderSearch(query) {
  const box = clear(document.getElementById('results'));
  if (!query) {
    box.append(el('p', { class: 'meta', text: '選手名を入力してください（部分一致）。' }));
    return;
  }
  const q = query.toLowerCase();
  const hits = athletes.filter((a) => a.name.toLowerCase().includes(q)
    || (a.names_seen || []).some((n) => n.toLowerCase().includes(q)));
  if (!hits.length) {
    box.append(el('p', { class: 'meta', text: '該当する選手がいません。' }));
    return;
  }
  box.append(el('p', { class: 'meta', text: hits.length + ' 名' }));
  const list = el('div', { class: 'table-wrap' }, el('table', {}, [
    el('thead', {}, el('tr', {}, [
      el('th', { class: 'no-sort', text: '選手' }),
      el('th', { class: 'no-sort', text: '所属（新しい順）' }),
      el('th', { class: 'no-sort num', text: '演技' }),
      el('th', { class: 'no-sort num', text: '大会' }),
      el('th', { class: 'no-sort', text: '' }),
    ])),
    el('tbody', {}, hits.slice(0, 200).map((a) => el('tr', {}, [
      el('td', {}, el('span', {
        class: 'link', text: a.name,
        onclick: () => { location.hash = a.athlete_id; },
      })),
      el('td', { class: 'meta', text: clubsText(a) }),
      el('td', { class: 'num', text: a.n_performances }),
      el('td', { class: 'num', text: a.n_meets }),
      el('td', { class: 'meta',
        text: a.has_individual ? '' : (a.disciplines || []).join('・') + 'のみ' }),
    ]))),
  ]));
  box.append(list);
}

function clubsText(a) {
  const h = [...(a.club_history || [])].reverse();
  if (!h.length) return '—';
  return h.map((x) => x.season + ' ' + x.clubs.join('・')).join(' ／ ');
}

function renderAthlete(id) {
  const box = clear(document.getElementById('profile'));
  const a = athletes.find((x) => x.athlete_id === id);
  if (!a) {
    box.append(el('p', { class: 'meta', text: '選手が見つかりません。' }));
    return;
  }
  const mine = perfs.filter((p) => p.athlete_id === id)
    .sort((x, y) => (x.date < y.date ? 1 : x.date > y.date ? -1 : 0));
  const s = a.summary || {};

  box.append(el('h2', { text: a.name }));
  if (a.names_seen && a.names_seen.length) {
    box.append(el('p', { class: 'meta', text: '別表記：' + a.names_seen.join('、') + '（同一人物としてまとめています）' }));
  }
  box.append(el('div', { class: 'kv' }, [
    ['出場演技', s.n_performances], ['出場大会', s.n_meets],
    ['自己ベスト', num(s.best_total, 2) ?? '—'],
    ['最高D', num(s.best_D, 1) ?? '—'],
    ['中断演技', s.n_interrupted],
  ].map(([k, v]) => el('div', {}, [
    el('div', { class: 'k', text: k }),
    el('div', { class: 'v', text: v === null || v === undefined ? '—' : v }),
  ]))));
  if (s.best_total) {
    box.append(el('p', { class: 'meta',
      text: '自己ベストは ' + s.best_total_date + '　' + s.best_total_meet + '。' }));
  }
  // 2017年より前の規則は合計の組み立てが違う（HDなし・Eを3倍）ので、自己ベストに混ぜない
  if (s.best_total_pre2017) {
    box.append(el('p', { class: 'meta',
      text: '2017年より前の規則での最高は ' + num(s.best_total_pre2017, 2) + '（'
        + s.best_total_pre2017_date + '　' + s.best_total_pre2017_meet
        + '）。規則が違うので自己ベストとは比べていません。' }));
  }

  box.append(el('h3', { text: '所属の履歴' }));
  const hist = a.club_history || [];
  if (!hist.length) {
    box.append(el('p', { class: 'meta', text: '所属が公開されている記録がありません。' }));
  } else {
    // 所属が変わらない年が続くと「2025 A → 2026 A」と同じ名前が並ぶ。
    // 見たいのは転籍なので、中身が同じ年はシーズンだけをまとめる。
    const runs = [];
    hist.forEach((x) => {
      const clubs = x.clubs.join('・');
      const last = runs[runs.length - 1];
      if (last && last.clubs === clubs) last.seasons.push(x.season);
      else runs.push({ seasons: [x.season], clubs: clubs });
    });
    box.append(el('p', {}, runs.map((r, i) => el('span', {}, [
      i ? ' → ' : '',
      el('strong', { text: r.seasons.length > 1
        ? r.seasons[0] + '〜' + r.seasons[r.seasons.length - 1] : r.seasons[0] }),
      ' ' + r.clubs,
    ]))));
  }
  // 所属は「属性」であって名寄せの鍵ではない。転籍しても同じ選手として扱う。
  box.append(el('p', { class: 'meta', text: '選手の同定は氏名だけで行っています（所属・生年月日は鍵にしていません）。' }));

  if (!a.has_individual) {
    box.append(el('div', { class: 'notice',
      text: 'この選手は個人種目の記録がありません（' + (a.disciplines || []).join('・')
        + 'のみ）。この画面は個人種目だけを表示しています。' }));
  }

  const missing = mine.filter((p) => p.total === null || p.total === undefined).length;
  const interrupted = mine.filter((p) => p.interrupted).length;
  if (missing || interrupted) {
    box.append(noteLayers(
      '一部の演技は合計点などが取得できていません',
      [
        missing ? el('p', { class: 'meta', text: '合計点・D・Tが公開されていない演技が ' + missing
          + ' 件あります（大阪府の決勝は明細ページしかないため）。空欄（—）で表示しています。0点ではありません。' }) : null,
        interrupted ? el('p', { class: 'meta', text: '中断した演技が ' + interrupted
          + ' 件あります。消していません。演技詳細で「中断（技数7）」のように明示し、'
          + '技数を超えた位置は空欄にしています。' }) : null,
      ].filter(Boolean)));
  }

  const wrap = clear(document.getElementById('history'));
  const renderCards = (list) => el('div', { class: 'card-list' }, list.map((p) => el('article', { class: 'rec' }, [
    el('div', { class: 'rec-head' }, [
      el('span', { class: 'rec-name', text: p.date }),
      el('span', { class: 'rec-total', text: num(p.total, 2) ?? '—' }),
    ]),
    el('div', { class: 'rec-meta' }, [document.createTextNode(p.meet_name + ' '), sourceBadge(p.official)]),
    el('div', { class: 'rec-tags' }, [
      el('span', { class: 'badge plain', text: p.category }),
      p.round ? el('span', { class: 'badge plain', text: p.round }) : null,
      p.routine ? el('span', { class: 'badge plain', text: p.routine + '本目' }) : null,
      p.rank ? el('span', { class: 'badge plain', text: p.rank + '位' }) : null,
      p.interrupted ? el('span', { class: 'badge flag', text: '中断' }) : null,
      rulesBadge(p),
    ]),
    el('dl', { class: 'rec-sub' }, [
      ['D', num(p.D, 1)], ['E', num(p.E, 1)], ['T', num(p.T, 2)], ['HD', num(p.HD, 2)],
      ['技数', p.n_elements ?? null],
    ].map(([k, v]) => el('div', {}, [
      el('dt', { text: k }),
      el('dd', { class: v === null || v === undefined ? 'blank' : '', text: v ?? '—' }),
    ]))),
    el('button', { class: 'chip', text: '演技の詳細', onclick: () => openDetail(p, meets.get(p.meet_id)) }),
  ])));

  document.getElementById('csv').onclick = () => downloadCsv(
    a.name + '_出場履歴.csv',
    ['大会日', '大会名', '出典', '区分', 'ラウンド', '演技', '所属', '順位', '合計', 'D', 'E', 'T', 'HD', '技数'],
    mine.map((p) => [p.date, p.meet_name, p.official ? '公式' : '非公式', p.category,
      p.round || '', p.routine || '', p.club || '', p.rank || '',
      num(p.total, 2) ?? '', num(p.D, 1) ?? '', num(p.E, 1) ?? '', num(p.T, 2) ?? '',
      num(p.HD, 2) ?? '', p.n_elements ?? '']));
  document.getElementById('csv').hidden = false;

  // 狭い画面ではカード表示。表の横スクロールは最終手段。
  if (isNarrow()) {
    wrap.append(renderCards([...mine]));
    return;
  }
  wrap.append(el('div', { class: 'table-wrap' }, el('table', { id: 'htable' }, [
    el('thead', {}, el('tr', {}, [
      ['date', '大会日'], ['meet_name', '大会'], ['category', '区分'], ['round', 'ラウンド'],
      ['routine', '演技'], ['rank', '順位'], ['total', '合計'], ['D', 'D'], ['E', 'E'],
      ['T', 'T'], ['HD', 'HD'], ['n_elements', '技数'],
    ].map(([key, label]) => el('th', {
      'data-key': key,
      'data-numeric': ['routine', 'rank', 'total', 'D', 'E', 'T', 'HD', 'n_elements'].includes(key) ? '1' : null,
      class: ['routine', 'rank', 'total', 'D', 'E', 'T', 'HD', 'n_elements'].includes(key) ? 'num' : '',
      text: label,
    })).concat([el('th', { class: 'no-sort' })]))),
    el('tbody', { id: 'hbody' }),
  ])));

  const render = (list) => {
    const tbody = clear(document.getElementById('hbody'));
    for (const p of list) {
      const meet = meets.get(p.meet_id);
      tbody.append(el('tr', {}, [
        el('td', { text: p.date }),
        el('td', {}, [document.createTextNode(p.meet_name + ' '), sourceBadge(p.official)]),
        el('td', { text: p.category }),
        el('td', { text: p.round || '—' }),
        el('td', { class: 'num', text: p.routine || '—' }),
        el('td', { class: p.rank ? 'num' : 'num blank', text: p.rank || '—' }),
        cell(p.total, 2), cell(p.D, 1), cell(p.E, 1), cell(p.T, 2), cell(p.HD, 2),
        el('td', { class: 'num', text: p.n_elements ?? '—' }),
        el('td', {}, [
          p.interrupted ? el('span', { class: 'badge flag', text: '中断' }) : null,
          rulesBadge(p),
          el('span', { class: 'link', text: ' 詳細', onclick: () => openDetail(p, meet) }),
        ]),
      ]));
    }
  };
  makeSortable(document.getElementById('htable'), mine, render, { key: 'date', dir: -1 });
}

let perfsFor = null;          // perfs が誰の演技か（同じ選手なら読み直さない）

async function route() {
  const id = location.hash.replace(/^#/, '');
  document.getElementById('search-card').hidden = !!id;
  document.getElementById('athlete-card').hidden = !id;
  document.getElementById('history').hidden = !id;
  if (!id) return;
  if (perfsFor !== id) {
    clear(document.getElementById('profile')).append(
      el('p', { class: 'meta', text: '読み込んでいます…' }));
    try {
      perfs = await data.athleteRows(id);
      perfsFor = id;
    } catch (err) {
      document.getElementById('app').prepend(errorBox(err.message));
      return;
    }
  }
  renderAthlete(id);
}

async function main() {
  mountNav('athlete.html');
  try {
    // 演技は選手を開いたときに、その選手の分だけ読む（全年を読むとスマホで重い）
    const [as, ms] = await Promise.all([data.athletes(), data.competitions()]);
    athletes = as;
    meets = new Map(ms.map((c) => [c.meet_id, c]));
    const q = document.getElementById('q');
    q.addEventListener('input', () => renderSearch(q.value.trim()));
    window.addEventListener('hashchange', route);
    onWidthChange(() => route());     // 表↔カードの切り替え
    renderSearch('');
    route();
  } catch (err) {
    document.getElementById('app').prepend(errorBox(err.message));
  }
}

main();
