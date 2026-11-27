# -*- coding: utf-8 -*-
"""西日本トランポリン協会の古いリザルトPDF（第47回 2019・第51回 2023 決勝）を読む。

どちらの PDF も、日本語の字（氏名・所属・見出し）を文字コードではなく埋め込みフォントの
字形番号だけで持っていて、そのままでは「(cid:1234)」としか取り出せない。字形の輪郭を
PC の同じ書体と照らして作った対応表（etl/nishinihon_cid_maps.json、tools/build_cid_maps.py が
作る）で文字に戻してから読む。PDF が差し替わっていたら（SHA-256 が違えば）止める。

■ 第47回（2019-09-20〜22、輪島市サンアリーナ）
  決勝のPDF（9/22 付）に、予選の全区分・決勝の全区分・オープン決勝が入っている。
  予選のPDF（9/21 付）は予選だけで、決勝のPDFが所属「金沢ジャンパーズクラブ」・氏名「増崎」を
  訂正した版になっているので、**決勝のPDFだけを読む**（予選のPDFは独立照合で見比べる）。
  列：Rank Name S1..S10 L A Escr Hscr Dscr Tscr R.Total Pen. Total
    予選は「Q1 の値 → 順位・氏名 → Q2 の値 → 所属」、決勝は「順位・氏名・F・値 → 所属」の並び。
    Escr=E、Hscr=HD、Dscr=D、Tscr=T。R.Total は演技の点（減点前）、Pen. は Q2 の行にだけある。
    予選の Total（Q2 の行）は2本の合計＝予選の値。続きのページには見出しも列名も無い。
  オープンは予選の明細が無い（最終ページの「予選結果」は合計点だけ）ので、決勝だけを取り込む。

■ 第51回（2023-09-29〜10-01、熊取町）決勝
  sporttech の採点システムが出力した書式。列：順位 氏名 所属 S1..S10 L E D H Time Total Score。
  英字の書体と日本語の書体で字の上端が 3.7pt ずれるので、順位の行と氏名の行は同じ1行として読む
  （所属「焼津高校Saltar」も、日本語の部分と英字の部分が別の行に見える）。
  減点のある演技は Total が「–0.2→6.380」の形になる。
  予選のPDFは文字が図形の輪郭（ベクター）になっていて取り出せないので、書き起こした CSV
  （etl/nishinihon_51q_transcription.csv、手順は tools/transcribe_nishi51q/README.md）を読む。
  PDF の SHA-256 が書き起こしたときと違えば止める。読むときにも点の式を全部確かめる。
"""
import collections
import hashlib
import io
import json
import os
import re
import unicodedata

from .. import config
from .nishinihon_pdf import _record
from .radicals import to_unified

MAPS_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'nishinihon_cid_maps.json')

MEETS = [
    {'meet_id': 'nw-2019-09-20', 'date': '2019-09-20', 'season': '2019',
     'name': '第47回西日本トランポリン競技選手権大会', 'level': '国内', 'venue': '輪島市サンアリーナ',
     'layout': '47', 'raw_dir': '2019/西日本トランポリン協会_PDF',
     'file': '47th_WestJapanTRA_Final_results.pdf'},
    {'meet_id': 'nw-2023-09-29', 'date': '2023-09-29', 'season': '2023',
     'name': '第51回西日本トランポリン競技選手権大会', 'level': '国内', 'venue': '熊取町',
     'layout': '51', 'raw_dir': '2023/西日本トランポリン協会_PDF',
     'file': '51th_WestJapanTRA_Final_results.pdf'},
]

CATEGORIES = ('小学生低学年', '小学生高学年', '中学生', '高校生', '大学生', '一般', 'オープン')
CAT_RE = re.compile(r'(' + '|'.join(CATEGORIES) + r') ?(男子|女子)')
CID_RE = re.compile(r'^\(cid:(\d+)\)$')
NUM_RE = re.compile(r'^\d+(\.\d+)?$')


def _load_maps():
    with io.open(MAPS_JSON, encoding='utf-8') as fh:
        return json.load(fh)['pdfs']


def decoded_pages(pdf_path, rel):
    """ページごとに、字形番号を文字に戻した字（pdfplumber の char）の一覧を返す。"""
    import pdfplumber
    entry = _load_maps().get(rel)
    if entry is None:
        raise ValueError('字の対応表がありません（tools/build_cid_maps.py で作る）: %s' % rel)
    sha = hashlib.sha256(open(pdf_path, 'rb').read()).hexdigest()
    if sha != entry['sha256']:
        raise ValueError('PDF が対応表を作ったときと違います（tools/build_cid_maps.py で作り直す）: %s' % rel)
    fonts = entry['fonts']
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            chars = []
            for c in page.chars:
                m = CID_RE.match(c['text'])
                if m:
                    t = fonts.get(c['fontname'], {}).get(m.group(1))
                    if t is None:
                        raise ValueError('対応表に無い字: %s p%d %s %s' % (rel, pno, c['fontname'], c['text']))
                    c = dict(c, text=t)
                chars.append(c)
            yield pno, chars


def visual_lines(chars, tol):
    """字を上端の近さで行にまとめ、行ごとに語（間が 1pt を超えたら別の語）の一覧を返す。"""
    chars = sorted(chars, key=lambda c: (c['top'], c['x0']))
    groups = []
    for c in chars:
        if groups and c['top'] - groups[-1][0] <= tol:
            groups[-1][1].append(c)
        else:
            groups.append([c['top'], [c]])
    lines = []
    for top, cs in groups:
        cs.sort(key=lambda c: c['x0'])
        words, cur, last = [], None, None
        for c in cs:
            if c['text'].strip() == '':
                if cur:
                    words.append(cur)
                cur, last = None, c['x1']
                continue
            if cur is not None and c['x0'] - last <= 1.0:
                cur['text'] += c['text']
                cur['x1'] = c['x1']
            else:
                if cur:
                    words.append(cur)
                cur = {'text': c['text'], 'x0': c['x0'], 'x1': c['x1']}
            last = c['x1']
        if cur:
            words.append(cur)
        for w in words:
            w['text'] = to_unified(w['text'])
        lines.append((top, words))
    return lines


def _f(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _int(text):
    v = _f(text)
    if v is None:
        return None
    if v != int(v):
        raise ValueError('整数のはずの値が小数: %r' % text)
    return int(v)


def _category(cat, sex):
    return '%s %s' % (cat, sex)


# ---- 第47回 -----------------------------------------------------------------

FOOTER_47 = re.compile(r'^\d{4}/\d+/\d+ 西日本トランポリン協会 \d+ / \d+$')
COLS_47 = ['S%d' % i for i in range(1, 11)] + ['L', 'A', 'Escr', 'Hscr', 'Dscr', 'Tscr',
                                               'R.Total', 'Pen.', 'Total']


def _items_47(chars, heading, header):
    """1ページの行を、値の行・順位の行・文字だけの行に分ける。続きのページは前の見出しと列位置を使う。"""
    lines = visual_lines(chars, tol=2.5)
    # 結果のページには下端に「2019/9/22 西日本トランポリン協会 n / 45」がある。無いページ
    # （賞の発表・オープンの予選合計の一覧）は結果ではないので読まない。
    if not any(FOOTER_47.match(' '.join(w['text'] for w in ws)) for _, ws in lines):
        return None, None, []
    if any('個人競技' in ''.join(w['text'] for w in ws) for _, ws in lines):
        header = None            # 新しい区分のページ：列名の行より上（大会名など）は読まない
    items = []
    for top, words in lines:
        text = ''.join(w['text'] for w in words)
        if '個人競技' in text:
            heading = text
            continue
        if words and words[0]['text'] == 'Rank':
            header = {w['text']: (w['x0'] + w['x1']) / 2 for w in words}
            missing = [k for k in ['Rank', 'Name'] + COLS_47 if k not in header]
            if missing:
                raise ValueError('列名が足りない: %s' % missing)
            continue
        if header is None or FOOTER_47.match(' '.join(w['text'] for w in words)):
            continue                                     # 列名より上・下端の日付とページ
        marker, vals, textw = None, {}, []
        for w in words:
            if w['text'] in ('Q1', 'Q2', 'F'):
                if marker:
                    raise ValueError('印が2つある行: %r' % text)
                marker = w['text']
                continue
            center = (w['x0'] + w['x1']) / 2
            if NUM_RE.match(w['text']) and center >= header['S1'] - 8:
                col = min(COLS_47, key=lambda k: abs(header[k] - center))
                if col in vals:
                    raise ValueError('同じ列に値が2つ: %s %r' % (col, text))
                vals[col] = w['text']
            else:
                textw.append(w)
        rank = None
        if textw and (re.match(r'^\d+$', textw[0]['text']) or textw[0]['text'] == '棄権') \
                and textw[0]['x1'] < header['Name'] - 5:
            rank = textw.pop(0)['text']
        if any((w['x0'] + w['x1']) / 2 >= header['S1'] - 8 for w in textw):
            raise ValueError('値の列に文字がある行: %r' % text)
        items.append({'top': top, 'marker': marker, 'vals': vals, 'rank': rank,
                      'text': ' '.join(w['text'] for w in textw)})
    return heading, header, items


def _blocks_47(items):
    """順位の行ごとに、前後の値の行と所属の行をまとめる。

    所属の行（値も印も無い文字だけの行）までをその選手とし、そのあとの行（次の選手の Q1 の値）は
    次の選手の前に付ける。"""
    ranks = [k for k, it in enumerate(items) if it['rank'] is not None]
    if not ranks:
        if any(it['vals'] for it in items):
            raise ValueError('順位の無いページに値がある')
        return []
    if any(not it['vals'] and not it['marker'] and it['text'] for it in items[:ranks[0]]):
        raise ValueError('ページの先頭に、どの選手のものか分からない文字がある')
    out, carry = [], items[:ranks[0]]
    for n, k in enumerate(ranks):
        hi = ranks[n + 1] if n + 1 < len(ranks) else len(items)
        seg = items[k + 1:hi]
        t = next((m for m, it in enumerate(seg)
                  if not it['vals'] and not it['marker'] and it['text']), None)
        if t is None:
            mine, rest = seg, []
        else:
            e = t
            while e < len(seg) and not seg[e]['vals'] and not seg[e]['marker'] and seg[e]['text']:
                e += 1
            mine, rest = seg[:e], seg[e:]
        out.append((items[k], carry, mine))
        carry = rest
    if any(it['vals'] for it in carry):
        raise ValueError('ページの最後に、どの選手のものか分からない値がある')
    return out


def _routine_47(vals, page):
    s = [_int(vals.get('S%d' % i)) for i in range(1, 11)]
    n = sum(1 for v in s if v is not None)
    if s[:n] != [v for v in s if v is not None]:
        raise ValueError('減点の並びに空きがある: %r' % vals)
    rt_total = _f(vals.get('R.Total'))
    pen = _f(vals.get('Pen.'))
    return {'S': s, 'Lnd': _int(vals.get('L')), 'A': _int(vals.get('A')),
            'Exe': _f(vals.get('Escr')), 'Diff': _f(vals.get('Dscr')), 'ToF': _f(vals.get('Tscr')),
            'HD': _f(vals.get('Hscr')), 'Pen': pen,
            'Score': None if rt_total is None else round(rt_total - (pen or 0.0), 3),
            'RTotal': rt_total, 'Total': _f(vals.get('Total')), 'page': page}


def athletes_47(pdf_path, rel):
    out = []
    heading = header = None
    for pno, chars in decoded_pages(pdf_path, rel):
        heading, header, items = _items_47(chars, heading, header)
        if header is None:
            continue
        for rank_it, before, after in _blocks_47(items):
            m = CAT_RE.search(heading or '')
            if not m:
                raise ValueError('見出しが読めない: %r' % heading)
            rnd = '予選' if '予選' in heading else '決勝'    # オープンは見出しに予選・決勝が無い（決勝）
            seq = [it for it in before + [rank_it] + after if it['vals'] or it['marker']]
            texts = [it['text'] for it in after if not it['vals'] and not it['marker'] and it['text']]
            routines = [_routine_47(it['vals'], pno) for it in seq if it['vals']]
            markers = [it['marker'] for it in seq if it['vals']]
            out.append({'page': pno, 'category': _category(m.group(1), m.group(2)), 'round': rnd,
                        'rank': rank_it['rank'], 'name': rank_it['text'], 'club': ''.join(texts),
                        'routines': routines, 'markers': markers})
    return out


def _check_47(a):
    """1選手の値の式と並びを確かめる（合わなければ止める）。"""
    rs = a['routines']
    where = '%s %s %s位 %s' % (a['category'], a['round'], a['rank'], a['name'])
    if a['rank'] == '棄権':
        if rs:
            raise ValueError('棄権なのに値がある: ' + where)
        return
    want = 2 if a['round'] == '予選' else 1
    if len(rs) != want:
        raise ValueError('演技の数が %d（%d のはず）: %s' % (len(rs), want, where))
    if a['round'] == '予選' and [m for m in a['markers'] if m] not in (['Q1', 'Q2'], []):
        raise ValueError('Q1・Q2 の印の順がおかしい: ' + where)
    for r in rs:
        parts = [r['Exe'], r['HD'], r['Diff'], r['ToF']]
        if None in parts or r['RTotal'] is None:
            raise ValueError('E・HD・D・T のどれかが無い: ' + where)
        if abs(sum(parts) - r['RTotal']) > 0.0015:
            raise ValueError('E+HD+D+T が R.Total と合わない: ' + where)
    last = rs[-1]
    if last['Total'] is None or last['Pen'] is None:
        raise ValueError('最後の行に Pen・Total が無い: ' + where)
    if abs(sum(r['RTotal'] for r in rs) - last['Pen'] - last['Total']) > 0.0015:
        raise ValueError('R.Total の和 − Pen が Total と合わない: ' + where)
    if any(r['Total'] is not None or r['Pen'] is not None for r in rs[:-1]):
        raise ValueError('1本目の行に Pen・Total がある: ' + where)


# ---- 第51回決勝（sporttech の書式） --------------------------------------------

COLS_51 = ['S%d' % i for i in range(1, 11)] + ['L', 'E', 'D', 'H', 'Time', 'Total', 'Score']
RANK_51 = re.compile(r'^(\d+)\.$')
PEN_TOTAL = re.compile(r'^[–-](\d+\.\d+)→(\d+\.\d+)$')


def athletes_51(pdf_path, rel):
    out = []
    for pno, chars in decoded_pages(pdf_path, rel):
        cat, header, rows = None, None, []
        for top, words in visual_lines(chars, tol=4.5):
            text = ' '.join(w['text'] for w in words)
            m = CAT_RE.search(text)
            if header is None:
                if m:
                    if cat:
                        raise ValueError('見出しの区分が2つある p%d' % pno)
                    cat = _category(m.group(1), m.group(2))
                elif words and words[0]['text'] == 'S1':
                    header = {w['text']: w['x0'] for w in words}
                    missing = [k for k in COLS_51 if k not in header]
                    if missing:
                        raise ValueError('列名が足りない: %s' % missing)
                continue
            if text.startswith('Generated by sporttech.io'):
                continue
            if not words or not RANK_51.match(words[0]['text']):
                raise ValueError('読めない行 p%d: %r' % (pno, text))
            vals, textw = {}, []
            for w in words[1:]:
                pm = PEN_TOTAL.match(w['text'])
                if pm:
                    vals['Pen'], vals['Total'] = pm.group(1), pm.group(2)
                elif NUM_RE.match(w['text']) and w['x0'] >= header['S1'] - 6:
                    col = min(COLS_51, key=lambda k: abs(header[k] - w['x0']))
                    if col in vals:
                        raise ValueError('同じ列に値が2つ p%d: %r' % (pno, text))
                    vals[col] = w['text']
                elif w['x0'] < header['S1'] - 6:
                    textw.append(w)
                else:
                    raise ValueError('値の列に文字 p%d: %r' % (pno, text))
            rows.append({'rank': RANK_51.match(words[0]['text']).group(1), 'vals': vals,
                         'words': textw, 'page': pno})
        if not rows:
            continue
        if cat is None:
            raise ValueError('区分の見出しが無い p%d' % pno)
        # 所属の列の位置：各行の3語目（氏名は姓・名の2語）の左端のいちばん左（ページで共通）
        club_x = min(r['words'][2]['x0'] for r in rows if len(r['words']) > 2)
        for r in rows:
            name = [w['text'] for w in r['words'] if w['x0'] < club_x - 3]
            club = [w['text'] for w in r['words'] if w['x0'] >= club_x - 3]
            if len(name) != 2:
                raise ValueError('氏名が姓・名の2語でない p%d: %r' % (pno, name))
            v = r['vals']
            s = [_int(v.get('S%d' % i)) for i in range(1, 11)]
            out.append({'page': r['page'], 'category': cat, 'round': '決勝', 'rank': r['rank'],
                        'name': ' '.join(name), 'club': ' '.join(club),
                        'routines': [{'S': s, 'Lnd': _int(v.get('L')), 'A': None,
                                      'Exe': _f(v.get('E')), 'Diff': _f(v.get('D')),
                                      'ToF': _f(v.get('Time')), 'HD': _f(v.get('H')),
                                      'Pen': _f(v.get('Pen')), 'Score': _f(v.get('Score')),
                                      'Total': _f(v.get('Total')), 'page': r['page']}]})
    return out


def _check_51(a):
    r = a['routines'][0]
    where = '%s %s位 %s' % (a['category'], a['rank'], a['name'])
    n = sum(1 for v in r['S'] if v is not None)
    if r['S'][:n] != [v for v in r['S'] if v is not None]:
        raise ValueError('減点の並びに空きがある: ' + where)
    if None in (r['Exe'], r['ToF'], r['HD'], r['Total'], r['Score']):
        raise ValueError('E・T・H・Total・Score のどれかが無い: ' + where)
    parts = r['Exe'] + (r['Diff'] or 0.0) + r['HD'] + r['ToF'] - (r['Pen'] or 0.0)
    if abs(parts - r['Total']) > 0.0015 or r['Total'] != r['Score']:
        raise ValueError('E+D+H+T−Pen が Total・Score と合わない: ' + where)


# ---- 第51回予選（書き起こし CSV） ----------------------------------------------

QUAL51 = {'rel': '2023/西日本トランポリン協会_PDF/51th_WestJapanTRA_Qualification_results.pdf',
          'sha256': '62ef6b14073bb319af68026bcca2f716c32287f750cfd18d396bdcb521d97d0c',
          'csv': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'nishinihon_51q_transcription.csv')}


def athletes_51q():
    """書き起こし CSV から予選の選手（2本ずつ）を返す。点の式が合わなければ止める。"""
    import csv
    path = os.path.join(config.RAW_ROOT, *QUAL51['rel'].split('/'))
    if not os.path.exists(path):
        return []
    if hashlib.sha256(open(path, 'rb').read()).hexdigest() != QUAL51['sha256']:
        raise ValueError('第51回予選のPDFが書き起こしたときと違います（tools/transcribe_nishi51q で作り直す）')
    by = collections.OrderedDict()
    with io.open(QUAL51['csv'], encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            if row['dns'] == '1':
                continue
            key = (row['category'], int(row['rank']), row['name'])
            by.setdefault(key, []).append(row)
    out = []
    for (cat, rank, name), rows in by.items():
        where = '第51回予選 %s %d位 %s' % (cat, rank, name)
        if len({r['club'] for r in rows}) != 1 or len({r['Score'] for r in rows}) != 1:
            raise ValueError('所属か予選の値が行で違う: ' + where)
        score = float(rows[0]['Score'])
        routines = []
        for r in rows:
            s = [int(r['S%d' % i]) if r['S%d' % i] != '' else None for i in range(1, 11)]
            n = sum(1 for v in s if v is not None)
            if s[:n] != [v for v in s if v is not None]:
                raise ValueError('減点の並びに空きがある: ' + where)
            L = int(r['L']) if r['L'] != '' else None
            e, h, t, tot = float(r['E']), float(r['H']), float(r['Time']), float(r['Total'])
            d = float(r['D']) if r['D'] != '' else None
            if abs(2 * n - (sum(v for v in s if v is not None) + (L or 0)) / 10 - e) > 0.0015:
                raise ValueError('E が減点の合計と合わない: ' + where)
            if abs(e + (d or 0.0) + h + t - tot) > 0.0015:
                raise ValueError('E+D+H+T が Total と合わない: ' + where)
            routines.append({'routine': int(r['routine']), 'S': s, 'Lnd': L, 'A': None, 'Exe': e,
                             'Diff': d, 'ToF': t, 'HD': h, 'Pen': None, 'Score': tot, 'Total': tot,
                             'page': int(r['page']), 'how': r['how'], 'note': r['note']})
        # 1本目を演技していない選手（合計 0）は1本目の行が無い。予選の値は残りの合計と同じ
        if abs(sum(x['Total'] for x in routines) - score) > 0.0015:
            raise ValueError('2本の合計が予選の値と合わない: ' + where)
        out.append({'category': cat, 'round': '予選', 'rank': rank, 'name': name,
                    'club': rows[0]['club'], 'routines': routines, 'qualifying_total': score})
    return out


# ---- まとめ ------------------------------------------------------------------

def load_all():
    """(competitions, performances) を返す。PDF が無ければ空。"""
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        return [], []
    import logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)

    competitions, performances = [], []
    for meet in MEETS:
        rel = '%s/%s' % (meet['raw_dir'], meet['file'])
        path = os.path.join(config.RAW_ROOT, *rel.split('/'))
        if not os.path.exists(path):
            continue
        if meet['layout'] == '47':
            athletes = athletes_47(path, rel)
            for a in athletes:
                _check_47(a)
        else:
            athletes = athletes_51(path, rel)
            for a in athletes:
                _check_51(a)
        seq = 0
        for a in athletes:
            if a['rank'] == '棄権' or not a['routines']:
                continue
            a['rank'] = int(a['rank'])
            a['name'] = unicodedata.normalize('NFKC', a['name']).strip()
            a['club'] = unicodedata.normalize('NFKC', a['club']).strip()
            a['qualifying_total'] = a['routines'][-1]['Total'] if a['round'] == '予選' else None
            for i, rt in enumerate(a['routines'], start=1):
                seq += 1
                rec = _record(seq, a, rt, i, a['category'], a['round'], meet['file'],
                              len(a['routines']), meet=meet, extra_a=rt.get('A'),
                              flags=['字形番号を対応表で文字に戻して読んだ'])
                rec['provenance']['source_url'] = config.SOURCES['nishinihon']['base_url']
                performances.append(rec)
        if meet['layout'] == '51':
            # 予選は書き起こし CSV から。演技の番号は決勝のあとに続ける（決勝の ID を変えない）
            for a in athletes_51q():
                for rt in a['routines']:
                    seq += 1
                    how = ('文字読み取りが既存の選手名と一致' if rt['how'] == 'ocr+db'
                           else '氏名・所属を画像で確認')
                    flags = ['図形の文字を書き起こした（数字は字の形の照合、%s）' % how]
                    if rt['note']:
                        flags.append(rt['note'])
                    rec = _record(seq, a, rt, rt['routine'], a['category'], '予選',
                                  QUAL51['rel'].split('/')[-1], 2, meet=meet, flags=flags)
                    rec['provenance']['source_url'] = config.SOURCES['nishinihon']['base_url']
                    performances.append(rec)
        competitions.append({
            'meet_id': meet['meet_id'], 'date': meet['date'], 'name': meet['name'],
            'level': meet['level'], 'season': meet['season'],
            'source': 'nishinihon', 'official': config.SOURCES['nishinihon']['official'],
            'source_url': config.SOURCES['nishinihon']['base_url'],
            'event_id': '', 'fetched_at': '', 'raw_dir': meet['raw_dir'],
        })
    return competitions, performances
