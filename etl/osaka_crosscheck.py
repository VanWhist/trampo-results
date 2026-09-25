# -*- coding: utf-8 -*-
"""第1層：大阪府を2つの経路で読んで突き合わせる。

第0層（完全性）は「原本にあるものが全部入っているか」しか見ない。行がそろっていれば
値が全部ずれていても通る。大阪府はそこが特に危うかった。

  中間CSV（`_大阪府pweb_演技サマリー.csv`）は**列名が1つずれている**。
  技数列→E、E列→HD、H列→D、D列→T、T列→P、P列→合計。
  `osaka.py` はこれを位置で読み替えて直しているが、その読み替えが正しいという保証は
  「そう解釈した」だけで、破れても誰も気づけなかった。

そこで、元HTML（`osaka_html.py`）を独立に読んで突き合わせる。入力からして別物なので、
一致すれば読み替えが正しいことを**解釈ではなく2経路の一致**で示せる。

突き合わせの鍵は (大会日, 区分, 氏名, 何本目)。氏名と区分は表記ゆれ（全角空白・
文字化けの `?`）があるので正規化してから比べる。区分ページをまたいだ重複掲載
（09才～10才女子 と 10才以下女子）は `also_in_raw_categories` を鍵に足して吸収する。

2026-09-07 の実測: 1,329演技が両経路でそろい、6項目すべてで食い違い0。
"""
import collections
import io
import os
import re
import unicodedata

from . import config, normalize
from .sources import osaka_html

FIELDS = ('E', 'HD', 'D', 'T', 'Pen', 'total')
TOL = 0.0005
DOC = os.path.join(config.REPO, 'docs', '大阪府_2経路の突合.md')


def _name(text):
    # 取り込み側の氏名は名寄せ済みで、異体字（髙→高、﨑→崎）が吸収されている。
    # 元HTMLは生のままなので、同じ正規化を通してから比べる。
    return re.sub(r'\s+', '', normalize.normalize_name(text or ''))


def _category(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or '')).replace('?', '～')


def _csv_index(performances):
    """取り込み側（中間CSV経由）を鍵で引けるようにする。"""
    out = {}
    for p in performances:
        if p['source'] != 'osaka_pweb':
            continue
        keys = {_category(p['category'])}
        for raw in (p.get('also_in_raw_categories') or []):
            keys.add(_category(osaka_html._clean_category(raw)[0]))
        for cat in keys:
            out[(p['date'], cat, _name(p['athlete_name']), p['routine'])] = p
    return out


def _html_index(records):
    return {(r['date'], _category(r['category']), _name(r['athlete_name']), r['routine']): r
            for r in records}


def run(performances, rep, write_doc=True):
    """突き合わせを実行し、実行件数を返す。

    `write_doc=False` は変異テスト用。壊したデータで docs を書き換えないため。
    """
    pages, records = osaka_html.read_all()
    if not records:
        rep.note('大阪府_2経路の突合', 'skipped（元HTMLが見つからない）')
        return {}

    csv_idx = _csv_index(performances)
    # 突き合わせるのは中間CSVにもある大会だけ。自前で新しく取得した大会（中間CSVに無い）は
    # 食い違いではないので、別に件数を出す（取り込みは元HTMLの経路で別途行う）。
    csv_dates = {k[0] for k in csv_idx}
    html_only_meets = collections.Counter(r['date'] for r in records if r['date'] not in csv_dates)
    records = [r for r in records if r['date'] in csv_dates]
    html_idx = _html_index(records)
    only_csv = sorted(set(csv_idx) - set(html_idx))
    only_html = sorted(set(html_idx) - set(csv_idx))
    both = sorted(set(csv_idx) & set(html_idx))
    if html_only_meets:
        rep.note('大阪府_元HTMLのみの大会',
                 '%d大会・%d演技（中間CSVに無いので突き合わせの対象外）'
                 % (len(html_only_meets), sum(html_only_meets.values())))

    for key in only_csv:
        rep.error('大阪府_突合', '中間CSVにあって元HTMLに無い演技: %s' % (key,))
    for key in only_html:
        rep.error('大阪府_突合', '元HTMLにあって中間CSVに無い演技: %s' % (key,))

    mismatch = 0
    csv_blank = collections.Counter()
    html_blank = collections.Counter()
    filled = collections.Counter()
    for key in both:
        a, b = csv_idx[key], html_idx[key]
        # 元HTMLから補った項目は、比べても同じに決まっている。突き合わせから外す。
        from_html = set(a.get('filled_from_html') or ())
        for f in FIELDS:
            if f in from_html:
                filled[f] += 1
                continue
            x, y = a.get(f), b.get(f)
            if x is None and y is None:
                continue
            if x is None:
                csv_blank[f] += 1
                continue
            if y is None:
                html_blank[f] += 1
                continue
            if abs(x - y) > TOL:
                mismatch += 1
                rep.error('大阪府_突合',
                          '%s の %s が食い違います：中間CSV %.3f / 元HTML %.3f'
                          % (key, f, x, y))

    # 元HTMLの中だけで成り立つべき恒等式。列の意味づけはこちらで担保する。
    identity_ok = identity_ng = 0
    for r in records:
        if any(r[f] is None for f in FIELDS):
            continue
        calc = r['E'] + r['HD'] + r['D'] + r['T'] - r['Pen']
        if abs(calc - r['total']) <= 0.0015:
            identity_ok += 1
        else:
            identity_ng += 1
            rep.error('大阪府_突合', '元HTML %s %s %s %d本目 の E+H+D+T-P が Sum. と合いません'
                      % (r['date'], r['category'], r['athlete_name'], r['routine']))

    empty = [p for p in pages if p.get('error')]
    for p in empty:
        rep.note('大阪府_結果表の無いページ',
                 '%s（%s %s %s）' % (p.get('file'), p.get('date'), p.get('category'), p.get('round')))

    if write_doc:
        _write_doc(pages, records, csv_idx, only_csv, only_html, both,
                   mismatch, filled, identity_ok, identity_ng)

    rep.note('大阪府_2経路の突合',
             '%d演技を照合 → 値の食い違い %d／取り込み側だけ %d／元HTMLだけ %d'
             '（うち %d演技ぶんは元HTMLから補った値なので照合の対象外）'
             % (len(both), mismatch, len(only_csv), len(only_html), filled['total']))
    return {'大阪府_突合': len(both), '大阪府_恒等式': identity_ok,
            '大阪府_HTMLページ': len(pages) - len(empty)}


def _write_doc(pages, records, csv_idx, only_csv, only_html, both,
               mismatch, filled, identity_ok, identity_ng):
    meets = osaka_html.meets(pages)
    lines = [
        '# 大阪府：2つの経路の突き合わせ', '',
        '取り込みは中間CSV経由（`etl/sources/osaka.py`）。それとは別に元HTMLを直接読み',
        '（`etl/sources/osaka_html.py`）、値が一致するかを毎回確かめています。',
        '入力そのものが違うので、一致すれば中間CSVの列の読み替えが正しいことを、',
        '解釈ではなく2経路の一致として示せます。', '',
        '## 結果', '',
        '| 項目 | 値 |', '|---|---|',
        '| 照合した演技 | %d |' % len(both),
        '| 値の食い違い | **%d** |' % mismatch,
        '| 取り込み側だけにある演技 | %d |' % len(only_csv),
        '| 元HTMLだけにある演技 | %d |' % len(only_html),
        '| 元HTMLでの恒等式 `E+H+D+T-P == Sum.` | ok %d / ng %d |' % (identity_ok, identity_ng),
        '| うち元HTMLから補った値（照合の対象外） | %d |' % filled['total'],
        '',
        '## 元HTMLから取り込みに補った値', '',
        '中間CSVに無く、元HTMLにあったもの。**上書きはしていません**（空欄だけを埋める）。', '',
        '| 項目 | 件数 | 備考 |', '|---|---|---|',
        '| 順位 | %d | 取り込み側は全件が空欄 |'
        % sum(1 for r in records if r['rank'] is not None),
        '| 所属 | %d | 切り詰めのない完全形。%d件は所属セルのリンク（`wsyozoku=`）から、'
        '残り%d件は決勝ページにリンクが無いので同じ大会の予選ページから移した |'
        % (sum(1 for r in records if r['club']),
           sum(1 for r in records if r['club_full']),
           sum(1 for r in records if r.get('club_from_same_meet'))),
        '| 決勝の得点内訳 | %d | D・T・P・合計。中間CSVは決勝が空欄 |' % filled['total'],
        '',
        '## 原本にある大会', '',
        '| 期日 | 大会 | 会場 | 結果のあるページ |', '|---|---|---|---|',
    ]
    for m in meets.values():
        lines.append('| %s | %s | %s | %d |' % (m['date'], m['name'], m['venue'], m['pages']))
    empty = [p for p in pages if p.get('error')]
    lines += ['', '## 結果表が無いページ', '',
              '見出しだけで表が印字されていないページです。取り込み側にも該当データはありません。',
              '結果のあるページが1枚も無い大会は、上の表にも出てきません。', '',
              '| 期日 | 大会 | 区分 | ラウンド |', '|---|---|---|---|']
    for p in sorted(empty, key=lambda x: (x.get('date') or '', x.get('file') or '')):
        lines.append('| %s | %s | %s | %s |'
                     % (p.get('date', ''), p.get('meet_name', ''),
                        p.get('category', ''), p.get('round', '')))
    lines.append('')
    with io.open(DOC, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))
