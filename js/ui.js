// 画面まわりの小さな共通部品。フレームワークは使わない。

/** その要素の先頭まで運ぶ。上部のヘッダは position: sticky なので、その高さぶん避ける。
 *
 * scrollIntoView({block:'start'}) だと要素の上端が画面の上端に来るので、見出しが
 * ヘッダの下に隠れる（スマホでヘッダ87px）。高さは画面幅で変わるので実測する。
 * 動きを減らす設定の人にはアニメーションしない。
 */
export function scrollToTop(node) {
  if (!node || node.hidden) return;
  const header = document.querySelector('header.site');
  const gap = (header ? header.getBoundingClientRect().height : 0) + 8;
  const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? 'auto' : 'smooth';
  window.scrollTo({ top: Math.max(0, window.scrollY + node.getBoundingClientRect().top - gap),
                    behavior: behavior });
}


export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

// 取れなかった値は「0」ではなく空欄にする。推測で埋めない。
export function num(v, digits = 2) {
  if (v === null || v === undefined || v === '') return null;
  return Number(v).toFixed(digits);
}

export function cell(value, digits = 2) {
  const text = num(value, digits);
  return el('td', { class: text === null ? 'num blank' : 'num', text: text === null ? '—' : text });
}

export function sourceBadge(official) {
  return el('span', {
    class: 'badge ' + (official ? 'official' : 'unofficial'),
    text: official ? '公式' : '非公式',
  });
}

export function navbar(active) {
  const links = [
    ['index.html', 'リザルト'],
    ['athlete.html', '選手'],
    ['judges.html', 'ジャッジ分析'],
    ['about.html', 'データについて'],
  ];
  return el('header', { class: 'site' }, [
    el('h1', { text: 'トランポリン大会リザルト' }),
    el('nav', {}, links.map(([href, label]) =>
      el('a', { href, class: href === active ? 'active' : '', text: label }))),
  ]);
}

export function mountNav(active) {
  document.body.prepend(navbar(active));
}

export function errorBox(message) {
  return el('div', { class: 'notice', text: 'データを読めませんでした：' + message });
}

// 表のソート。全列クリックで昇順・降順を切り替える。
export function makeSortable(table, rows, render, initial) {
  let key = initial ? initial.key : null;
  let dir = initial ? initial.dir : 1;
  const heads = [...table.tHead.rows[0].cells];

  function apply() {
    if (key) {
      const sorted = [...rows].sort((a, b) => {
        const x = a[key], y = b[key];
        const xn = x === null || x === undefined || x === '';
        const yn = y === null || y === undefined || y === '';
        if (xn && yn) return 0;
        if (xn) return 1;              // 欠測は常に末尾
        if (yn) return -1;
        if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
        return String(x).localeCompare(String(y), 'ja') * dir;
      });
      render(sorted);
    } else {
      render(rows);
    }
    for (const h of heads) {
      const hk = h.dataset.key;
      if (!hk) continue;
      if (hk === key) h.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
      else h.removeAttribute('aria-sort');
    }
  }

  for (const h of heads) {
    if (!h.dataset.key) { h.classList.add('no-sort'); continue; }
    h.addEventListener('click', () => {
      if (key === h.dataset.key) dir = -dir;
      else { key = h.dataset.key; dir = h.dataset.numeric ? -1 : 1; }
      apply();
    });
  }
  apply();
  return { update(next) { rows = next; apply(); } };
}

// ---- ページング -------------------------------------------------------------
// 検索・絞り込み・ソートは常に全件を対象にし、**表示だけ**を切り出す。
// 以前は先頭3000件だけを描画していたため、3,001件目以降にどうやっても到達できず、
// 欠測を含む行（ソートで末尾に送られる）が事実上見えなくなっていた。
export const PER_PAGE = 50;

export function paginate(list, page, perPage = PER_PAGE) {
  const pages = Math.max(1, Math.ceil(list.length / perPage));
  const current = Math.min(Math.max(1, page), pages);
  const start = (current - 1) * perPage;
  return {
    items: list.slice(start, start + perPage),
    page: current,
    pages,
    from: list.length ? start + 1 : 0,
    to: Math.min(start + perPage, list.length),
    total: list.length,
  };
}

/** 「8,175件中 132件　1–50件を表示　‹ 前へ 1 / 3 次へ ›」 */
export function renderPager(node, view, grandTotal, onGo) {
  clear(node);
  const n = (v) => v.toLocaleString('ja-JP');
  node.append(el('span', { class: 'pager-count' }, [
    el('strong', { text: n(grandTotal) + '件中 ' + n(view.total) + '件' }),
    document.createTextNode(view.total
      ? '　' + n(view.from) + '–' + n(view.to) + '件を表示'
      : '　該当なし'),
  ]));
  if (view.pages <= 1) return;
  node.append(el('span', { class: 'pager-nav' }, [
    el('button', { class: 'chip', text: '‹ 前へ', disabled: view.page <= 1,
      onclick: () => onGo(view.page - 1) }),
    el('span', { class: 'pager-pos', text: view.page + ' / ' + view.pages }),
    el('button', { class: 'chip', text: '次へ ›', disabled: view.page >= view.pages,
      onclick: () => onGo(view.page + 1) }),
    el('button', { class: 'chip', text: '最後 »', disabled: view.page >= view.pages,
      onclick: () => onGo(view.pages) }),
  ]));
}

// ---- 狭い画面ではカード表示に切り替える -------------------------------------
// 表の横スクロールは最終手段。1件＝1カードにして、主な情報だけを大きく出す。
const NARROW = window.matchMedia('(max-width: 700px)');

export function isNarrow() {
  return NARROW.matches;
}

export function onWidthChange(fn) {
  const handler = () => fn(NARROW.matches);
  if (NARROW.addEventListener) NARROW.addEventListener('change', handler);
  else NARROW.addListener(handler);
}

// ---- 注記の3層構造 -----------------------------------------------------------
// 注記は消さない。毎回全文を通過させるのをやめるだけ。
//   第1層 … 一行だけ常時表示
//   第2層 … クリックで展開
//   第3層 … 「データについて」ページ
export function noteLayers(headline, detailNodes, aboutAnchor) {
  const body = el('div', { class: 'note-body', hidden: true }, detailNodes);
  const toggle = el('button', {
    class: 'link-button', text: '詳しく見る',
    onclick: () => {
      body.hidden = !body.hidden;
      toggle.textContent = body.hidden ? '詳しく見る' : '閉じる';
    },
  });
  return el('div', { class: 'note' }, [
    el('div', { class: 'note-head' }, [
      el('span', { class: 'note-icon', text: 'ⓘ' }),
      el('span', { text: headline }),
      toggle,
      aboutAnchor === false ? null
        : el('a', { class: 'note-more', href: 'about.html', text: 'データについて' }),
    ]),
    body,
  ]);
}

export function downloadCsv(filename, header, rows) {
  const esc = (v) => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const body = [header, ...rows].map((r) => r.map(esc).join(',')).join('\r\n');
  // Excelで文字化けしないようBOMを付ける
  const blob = new Blob(['﻿' + body], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
