# -*- coding: utf-8 -*-
"""大阪府（トランポリン応援団 / trampoline.pweb.jp）の元HTMLを直接読む。

**いまの取り込み（`osaka.py`）は中間CSV経由で、この経路とは入力からして別。**
2つを突き合わせるのが目的で、まだ取り込みには使わない（`osaka_crosscheck.py`）。
片方を捨ててしまうと、突き合わせの機会そのものが無くなる。

中間CSVには無くて、元HTMLにはあるもの:
  ・順位（CSV側は全1,293件が空欄）
  ・所属（同上。しかも**リンクのURLに完全な名前が入っている**ので切り詰められていない）
  ・決勝の得点内訳（CSV側は266演技ぶんが欠測）
  ・大会そのもの（同じ日に別の大会が2つある日があり、CSVには片方しか入っていない）

表の作り:
  ・値は `<br>` で区切られる。予選は1セルに1本目と2本目が入る
      <td>15.800<br>15.400</td>
  ・列は E H D T P Sum. Total で、印字どおり。恒等式 E+H+D+T-P == Sum. が成り立つ
  ・所属セルは <a href="...&wsyozoku=B2アベノジュニアトランポリンクラブ"> で、
    表示は「アベノジ」と切り詰められているがURLは完全形。全551件で
    「表示はURLの先頭一致」を確認済み
  ・決勝ページは2段見出し（予選／決勝／Total ＋ E H D T P Sum.）で、1行11セル。
    こちらは所属がリンクになっておらず、切り詰めた表示しか無い
"""
import collections
import os
import re
import unicodedata

from .. import config

MEET_PREFIX = 'os'
SKIP_WORDS = ('戻る', 'ｽﾀｰﾄ', 'スタート')

CLUB_PREFIX_RE = re.compile(r'^[A-Z]\d')       # wsyozoku の先頭2文字（実測 A2 / B2 のみ）
HEAD_QUAL = ('順位', '氏名', '所属', 'E', 'H', 'D', 'T', 'P', 'Sum.', 'Total')
HEAD_FINAL = ('順位', '氏名', '所属', '予選', '決勝', 'Total')

# 見出しの末尾 → ラウンド。「結果成績」は国スポ選考会で、決勝が無く1・2本目だけ。
ROUND_BY_SUFFIX = {'予選成績': '予選', '決勝成績': '決勝', '結果成績': '予選'}

# 順位の欄に入る数字以外の値。想定外の語が来たら行ごと落ちるので、増えたら気づける。
RANK_NOTES = ('棄権',)


def _n(text):
    """タグを外して正規化する。全角空白と &nbsp; は半角にそろえる。"""
    text = re.sub(r'(?is)<script.*?</script>', ' ', text or '')
    text = re.sub(r'(?is)<style.*?</style>', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&nbsp;', ' ').replace('　', ' ').replace('﻿', '')
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).strip()


def _f(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _cells(row_html):
    return re.findall(r'(?is)<t[dh][^>]*>(.*?)</t[dh]>', row_html)


def _values(cell_html):
    """セルを <br> で割って値の並びにする。空は落とす。"""
    return [v for v in (_n(p) for p in re.split(r'(?i)<br\s*/?>', cell_html)) if v]


def _club(cell_html):
    """所属を (完全形, 表示) で返す。リンクが無ければ完全形は None。"""
    shown = _n(cell_html)
    m = re.search(r'wsyozoku=([^"&]*)', cell_html)
    if not m:
        return None, shown
    full = _n(m.group(1).replace('+', ' '))
    full = CLUB_PREFIX_RE.sub('', full, count=1)
    return (full or None), shown


def _clean_category(raw):
    """「個人競技 09才?10才女子 予選成績」→ ('09才～10才女子', '予選')"""
    text = _n(raw).replace('?', '～')       # 元HTMLの文字化け（～）
    round_label = ''
    for suffix, label in ROUND_BY_SUFFIX.items():
        if text.endswith(suffix):
            round_label = label
            text = text[: -len(suffix)].strip()
            break
    text = re.sub(r'^個人競技\s*', '', text)
    return re.sub(r'\s+', ' ', text).strip(), round_label


def _meet_info(page_text):
    """ページ上部の「大会名 会場：… 期日：…」を読む。"""
    # _n() は NFKC をかけるので、全角コロンは半角になっている。両方受ける。
    m = re.search(r'(.{4,60}?)\s*会場[：:](.{2,40}?)\s*期日[：:](\d{4})年(\d{1,2})月(\d{1,2})日',
                  page_text)
    if not m:
        return None
    return {
        'name': m.group(1).strip(),
        'venue': m.group(2).strip(),
        'date': '%s-%02d-%02d' % (m.group(3), int(m.group(4)), int(m.group(5))),
    }


def result_files():
    """読むべきHTMLを年フォルダから集める。メニューとスタートリストは結果ではない。"""
    out = []
    for year in sorted(os.listdir(config.RAW_ROOT)):
        root = os.path.join(config.RAW_ROOT, year, '大阪府_pweb')
        if not os.path.isdir(root):
            continue
        for folder, _, names in os.walk(root):
            for name in sorted(names):
                if not name.lower().endswith('.html'):
                    continue
                if any(w in name for w in SKIP_WORDS):
                    continue
                out.append(os.path.join(folder, name))
    return out


def _parse_rows(table_rows, shape):
    """データ行を (順位, 氏名, 所属, 値の並び) にする。"""
    want = 10 if shape == 'qual' else 11
    out = []
    for html in table_rows:
        cells = _cells(html)
        if len(cells) != want:
            continue
        rank = _n(cells[0])
        # 順位の欄には「棄権」も入る（実測34行）。落とすと記録ごと消えるので、
        # 順位は無し・印字はそのまま残す。
        if not rank.isdigit() and rank not in RANK_NOTES:
            continue
        club_full, club_shown = _club(cells[2])
        out.append({
            'rank': int(rank) if rank.isdigit() else None,
            'rank_note': '' if rank.isdigit() else rank,
            'name': _n(cells[1]),
            'club': club_full or club_shown,
            'club_full': club_full,
            'club_shown': club_shown,
            'cells': [_values(c) for c in cells[3:]],
        })
    return out


def _records(page, athletes, shape):
    """1ページの選手行を演技レコードに開く。"""
    out = []
    for a in athletes:
        cols = a['cells']
        if shape == 'qual':
            # E H D T P Sum. Total（Total は選手につき1つ）
            n = max(len(c) for c in cols[:6]) if cols else 0
            for i in range(n):
                pick = lambda k: _f(cols[k][i]) if i < len(cols[k]) else None
                out.append(_record(page, a, i + 1, page['round'],
                                   pick(0), pick(1), pick(2), pick(3), pick(4), pick(5),
                                   _f(cols[6][0]) if cols[6] else None))
        else:
            # 予選(合計) E H D T P Sum. Total
            g = lambda k: _f(cols[k][0]) if cols[k] else None
            out.append(_record(page, a, 3, '決勝',
                               g(1), g(2), g(3), g(4), g(5), g(6), g(0)))
    return out


def _record(page, athlete, routine, round_label, e, hd, d, t, pen, total, qual_total):
    return {
        'date': page['date'], 'meet_name': page['meet_name'], 'venue': page['venue'],
        'category': page['category'], 'round': round_label, 'routine': routine,
        'athlete_name': athlete['name'], 'rank': athlete['rank'],
        'club': athlete['club'], 'club_full': athlete['club_full'],
        'club_from_same_meet': False,
        'rank_note': athlete['rank_note'],
        'club_shown': athlete['club_shown'],
        'E': e, 'HD': hd, 'D': d, 'T': t, 'Pen': pen,
        'total': total, 'qualifying_total': qual_total,
        'source_file': page['file'],
    }


def read_all():
    """(ページの一覧, 演技レコード) を返す。"""
    pages, records = [], []
    for path in result_files():
        raw = open(path, encoding='utf-8', errors='replace').read()
        info = _meet_info(_n(raw))
        heading = re.search(r'【(.*?)】', _n(raw))
        if not info or not heading:
            pages.append({'file': path, 'error': '大会名または区分の見出しが読めない'})
            continue
        category, round_label = _clean_category(heading.group(1))
        rows = re.findall(r'(?is)<tr[^>]*>(.*?)</tr>', raw)
        shape = _shape(rows)
        page = {
            'file': os.path.relpath(path, config.RAW_ROOT),
            'date': info['date'], 'meet_name': info['name'], 'venue': info['venue'],
            'category': category, 'round': round_label, 'shape': shape,
        }
        if shape is None:
            page['error'] = '結果の表が見つからない'
            pages.append(page)
            continue
        athletes = _parse_rows(rows, shape)
        page['athletes'] = len(athletes)
        recs = _records(page, athletes, shape)
        page['records'] = len(recs)
        pages.append(page)
        records += recs
    _fill_club_from_same_meet(records)
    return pages, records


def _fill_club_from_same_meet(records):
    """決勝ページの所属は切り詰めた表示しか無い。同じ大会の予選ページから完全形を移す。

    予選の所属セルはリンクになっていて `wsyozoku=` に完全形が入っているが、決勝ページは
    リンクが無い。同じ大会・同じ選手なので同一人物として扱ってよい（他のソースから
    持ってくるのとは別の話で、原本の中での補完）。
    候補が2つ以上ある選手は触らない。
    """
    from .. import normalize
    full = collections.defaultdict(set)
    for r in records:
        if r['club_full']:
            full[(r['date'], r['meet_name'], normalize.normalize_name(r['athlete_name']))].add(
                r['club_full'])
    for r in records:
        if r['club_full']:
            continue
        key = (r['date'], r['meet_name'], normalize.normalize_name(r['athlete_name']))
        names = full.get(key)
        if names and len(names) == 1:
            r['club'] = next(iter(names))
            r['club_from_same_meet'] = True


def _shape(rows):
    """見出し行から表の形を決める。'qual'（10列）か 'final'（11列）。"""
    for html in rows:
        head = tuple(_n(c).replace(' ', '') for c in _cells(html))
        if head[:3] == HEAD_QUAL[:3]:
            if head == HEAD_QUAL:
                return 'qual'
            if head == HEAD_FINAL:
                return 'final'
    return None


def meets(pages):
    """ページの一覧から大会をまとめる。同じ日に別の大会があるので日付だけでは足りない。"""
    out = collections.OrderedDict()
    for p in pages:
        if p.get('error'):
            continue
        key = (p['date'], p['meet_name'])
        m = out.setdefault(key, {'date': p['date'], 'name': p['meet_name'],
                                 'venue': p['venue'], 'meet_id': '%s-%s' % (MEET_PREFIX, p['date']),
                                 'pages': 0, 'categories': set()})
        m['pages'] += 1
        m['categories'].add((p['category'], p['round']))
    return out


def fill_missing(performances):
    """取り込み側（中間CSV経由）に無い値を、元HTMLから補う。

    **上書きはしない。** 空いているところだけを埋める。値が両方にある項目は
    `osaka_crosscheck.py` の突き合わせに残しておきたいので、触らない。
    補った項目は `filled_from_html` に残し、突き合わせ側でそれと分かるようにする。

    中間CSVには審判別の明細（S1〜S10・着地）があり、元HTMLの結果ページには無い。
    だから置き換えではなく、足りないところだけを埋める形にする。
    """
    from .. import normalize
    pages, records = read_all()
    if not records:
        return {}

    def key(date, category, name, routine):
        return (date,
                re.sub(r'\s+', '', unicodedata.normalize('NFKC', category or '')).replace('?', '～'),
                re.sub(r'\s+', '', normalize.normalize_name(name or '')),
                routine)

    index = {key(r['date'], r['category'], r['athlete_name'], r['routine']): r for r in records}
    filled = collections.Counter()
    for p in performances:
        if p['source'] != 'osaka_pweb':
            continue
        keys = [key(p['date'], p['category'], p['athlete_name'], p['routine'])]
        for raw in (p.get('also_in_raw_categories') or []):
            keys.append(key(p['date'], _clean_category(raw)[0], p['athlete_name'], p['routine']))
        r = next((index[k] for k in keys if k in index), None)
        if r is None:
            continue
        got = []
        if p.get('rank') is None and r['rank'] is not None:
            p['rank'] = r['rank']
            got.append('rank')
        if not p.get('club') and r['club']:
            p['club'] = r['club']
            got.append('club')
        for field in ('D', 'T', 'Pen', 'total'):
            if p.get(field) is None and r[field] is not None:
                p[field] = r[field]
                got.append(field)
        if p.get('qualifying_total') is None and r['qualifying_total'] is not None:
            p['qualifying_total'] = r['qualifying_total']
            got.append('qualifying_total')
        if got:
            p['filled_from_html'] = got
            p['provenance'] = dict(p.get('provenance') or {})
            p['provenance']['filled_from'] = r['source_file']
            for field in got:
                filled[field] += 1
    return dict(filled)
