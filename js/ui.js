// 画面まわりの小さな共通部品。フレームワークは使わない。

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
