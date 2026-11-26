# -*- coding: utf-8 -*-
"""東日本トランポリン協会のリザルトPDFを読む（東日本選手権・イーストジャパン、2022〜）。

読むファイルは etl/higashinihon_files.json に固定してある（協会サイトの各大会の結果ページから
リンクされているものだけ。古いアップロードや画像だけのPDFは読まない）。

集計ソフトの世代で、表の形が3通りある。どれも列見出しの行があるので、**列は見出しの
x座標で決める**（値が0の列が印字されないことがあるため、空白で分けると列がずれる）。

  2022（第46回）  Rank Name Rtn S1..S10 Lnd Exe Diff ToF HD Pen Score Best
                  順位・氏名・1本目が同じ行、所属＋2本目が次の行
  2023〜2025      Rank 氏名 S1..S10 L A Exe Diff ToF HD Pen Score Best|Total（「順位表」）
                  氏名に読み仮名「（…）」が付き、長いと折り返す
  2026〜          Rank Name Round S1..S10 L Exe Diff ToF HD Pen Score Best|Total
                  見出しに「Dev. Hirotaka.H」。氏名が上・所属が下で、順位はその間に
                  中央揃え（予選は1本目と2本目の間）

そのほかの決まり（どれも実物で踏んだもの）:
  ・Best は2本のうち良いほう、Total は2本の合計。どちらも選手の値なので両方の演技に持たせる
  ・演技していない2本目は全項目 0.00 で印字される（2022）。減点が1つも無く Score が0の行は演技に数えない
  ・順位の無い「DNS」の行（2026）は棄権。演技が無いので選手にしない
  ・ブラウザで印刷したPDFは、ページの上下に URL・「1/2」・印刷日時が入る。読み飛ばす
  ・珍しい漢字の姓は別の字体で数pt上に出る（合寳 / 凛菜）。順位の行の直上4pt以内ならつなぐ
  ・2026年版のページ末尾は行が詰められ、1本の減点と点数が別の行に分かれる。つなぎ直す
  ・Pen の空欄はソフトハイフン（U+00AD）で印字される
"""
import collections
import io
import json
import os
import re
import unicodedata

from .. import config

FILES_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'higashinihon_files.json')
SOURCE = 'higashinihon'

ROW_TOL = 2.5          # これ以内の top は同じ視覚行
NUM_RE = re.compile(r'^-?\d+(?:\.\d+)?$')
ROUND_RE = re.compile(r'(Q\d|予選\d|決勝\d)')
FOOTER_RE = re.compile(r'T-product|signature|All Rights Reserved')
# ブラウザで印刷したPDFのページ上端・下端（URL、「1/2」、印刷日時と表題）
PRINT_RE = re.compile(r'https?://|順位表_|^\d+/\d+$|^\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{2}')

LABELS = [('Rank', 'rank'), ('Name', 'name'), ('氏名', 'name'), ('Rtn', 'rtn'), ('Round', 'rtn')]
LABELS += [('S%d' % i, 'S%d' % i) for i in range(1, 11)]
LABELS += [('Lnd', 'L'), ('L', 'L'), ('A', 'A'), ('Exe', 'Exe'), ('Di', 'Diff'), ('ToF', 'ToF'),
           ('HD', 'HD'), ('Pen', 'Pen'), ('Score', 'Score'), ('Best', 'Best'), ('Total', 'Total')]
VALUE_KEYS = ['S%d' % i for i in range(1, 11)] + ['L', 'A', 'Exe', 'Diff', 'ToF', 'HD', 'Pen', 'Score']


def load_manifest():
    with io.open(FILES_JSON, encoding='utf-8') as fh:
        return json.load(fh)


# 2022・2026年版のPDFは、一部の漢字を「部首」の文字コード（CJK部首補助）で持っている。
# 見た目は同じだが NFKC では統合漢字に戻らないため、同じ選手が別人になってしまう
# （⻑澤 と 長澤）。実データに現れたものだけを対応させる（2026-11-27 確認）。
RADICALS = {'\u2ed1': '\u9577',   # ⻑ → 長
            '\u2ec4': '\u897f',   # ⻄ → 西
            '\u2eeb': '\u6589',   # ⻫ → 斉
            '\u2ed8': '\u9752'}   # ⻘ → 青


# 康熙部首は NFKC で統合漢字に戻るが、U+2F3E（戸の部首）だけは日本の「戸」（U+6238）ではなく
# 「戶」（U+6236）になる（保戸塚・瀬戸・戸田・江戸崎が別表記になった）。NFKC の前に置き換える。
KANGXI_JP = {chr(0x2F3E): chr(0x6238)}
SOFT_HYPHEN = chr(0x00AD)                # Pen 空欄の印


# 合字「fi」が NUL として取り出される語（PDFの画面表示で確認、2026-11-27）。見出しの
# 'Di'+NUL（Diff の ff）以外で、ここに無い NUL が氏名・所属に出たら止める。
LIGATURES = {'s\x00da': 'sfida', 'bon\x00re': 'bonfire'}
# PDFの文字データそのものが化けている所属（画面にも「?」と出る）。正しい表記に直す。
CLUB_FIXES = {'Fiert?s': 'Fiertés', 'PiCTuRES:qu?': 'PiCTuRES:quÉ'}


def _n(text):
    text = text or ''
    for old, new in LIGATURES.items():
        text = text.replace(old, new)
    bad = [tok for tok in text.split() if '\x00' in tok and not tok.startswith('Di')]
    if bad:
        raise ValueError('合字の取り出しに失敗した語があります（LIGATURES に追加が必要）: %r' % bad)
    # 見出しの Diff は 'Di' + NUL のように制御文字が混じる。先に落とす。
    text = ''.join(ch for ch in text if ch == ' ' or ch >= ' ')
    text = text.replace(SOFT_HYPHEN, '')
    for old, new in KANGXI_JP.items():
        text = text.replace(old, new)
    # 康熙部首のうち NFKC で日本で使わない字形になるもの（戸→戶 のような）が残っていたら止める。
    # 判定は「NFKC 後の字が Shift_JIS（JIS X 0208）で書けるか」。黑・黃・靑などはここで止まる。
    for ch in set(text):
        if 0x2F00 <= ord(ch) <= 0x2FDF:
            try:
                unicodedata.normalize('NFKC', ch).encode('shift_jis')
            except UnicodeEncodeError:
                raise ValueError('日本で使わない字形になる部首の文字があります（KANGXI_JP に追加が必要）: '
                                 '%r' % ch)
    text = unicodedata.normalize('NFKC', text)       # ⽇ ⼈ ⼥（康熙部首）はここで戻る
    for old, new in RADICALS.items():
        text = text.replace(old, new)
    return text.strip()


def _f(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


# ---- 区分・ラウンド（ファイル名から） ----------------------------------------

_SHORT = re.compile(r'^\d{4}([ab])([mw])([qf])result$')      # 2025: 2025amqresult
_LONG = re.compile(r'個人_?([A-E]|DJ|DS|園児)(?:クラス)?_?(男子|女子)_?(予選|決勝)'
                   r'|個人_?(男子|女子)_?([A-E]|DJ|DS|園児)クラス_?(予選|決勝)')


def section_of(filename):
    """ファイル名から (クラス, 男女, ラウンド) を返す。読めなければ None。"""
    stem = unicodedata.normalize('NFKC', os.path.splitext(filename)[0])
    m = _SHORT.match(stem)
    if m:
        return (m.group(1).upper(), {'m': '男子', 'w': '女子'}[m.group(2)],
                {'q': '予選', 'f': '決勝'}[m.group(3)])
    m = _LONG.search(stem.replace('-手作業', '').replace('-1', ''))
    if m:
        if m.group(1):
            return m.group(1), m.group(2), m.group(3)
        return m.group(5), m.group(4), m.group(6)
    return None


# ---- PDFの読み取り ------------------------------------------------------------

def _visual_rows(page):
    words = [dict(w, text=_n(w['text'])) for w in page.extract_words()]
    words = [w for w in words if w['text']]
    rows = []
    for w in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if rows and abs(w['top'] - rows[-1]['top']) <= ROW_TOL:
            rows[-1]['words'].append(w)
        else:
            rows.append({'top': w['top'], 'words': [w]})
    for r in rows:
        r['words'].sort(key=lambda w: w['x0'])
    return rows


def _header(rows):
    for i, r in enumerate(rows):
        texts = [w['text'] for w in r['words']]
        if 'Rank' in texts and 'S1' in texts and 'Score' in texts:
            cols = []
            for w in r['words']:
                for label, key in LABELS:
                    if w['text'] == label or (label == 'Di' and w['text'].startswith('Di')):
                        cols.append({'key': key, 'x0': w['x0'], 'x1': w['x1'],
                                     'c': (w['x0'] + w['x1']) / 2})
                        break
            return i, cols
    return None, None


def _split_row(r, cols):
    """1行を (順位, 文字の断片, ラウンド記号, 値の辞書) に分ける。

    文字の断片は (x0, 文字) の組。同じ所属が数pt上下にずれて2つの視覚行に割れることが
    あり、あとで左から順に並べ直すのに x0 を使う。
    """
    by = {c['key']: c for c in cols}
    rank_right = by['rank']['x1'] + 6
    first_num = by['rtn']['x0'] - 4 if 'rtn' in by else by['S1']['x0'] - 4
    numeric = [c for c in cols if c['key'] in VALUE_KEYS + ['Best', 'Total']]
    rank, texts, rnd, vals = None, [], None, collections.defaultdict(list)
    for w in r['words']:
        t = w['text']
        cx = (w['x0'] + w['x1']) / 2
        if w['x1'] <= rank_right:
            if re.fullmatch(r'\d+\.?', t):
                rank = int(t.rstrip('.'))
            continue                                   # 'Q'（通過の印）など
        if NUM_RE.match(t) and cx >= first_num:
            best = min(numeric, key=lambda c: abs(c['c'] - cx))
            vals[best['key']].append(t)
            continue
        # 数値でない語。ラウンド記号は単独の語のことも、所属に続けて1語になっていること
        # （…クラブQ2、sfidaQ2）も、所属の折り返しの途中に挟まることもある（…体操決勝2部）。
        # 位置で決めると、所属が長くて Rtn 列に食い込んだとき語ごと捨ててしまうので、
        # 文字で切り分けてから残りを所属・氏名の断片にする。
        m = ROUND_RE.search(t)
        if m:
            rnd = m.group(1)
            t = (t[:m.start()] + t[m.end():]).strip()
        if t == 'Q':
            continue                                   # 予選通過の印。氏名の後ろに出る版がある（2022）
        if t:
            texts.append((w['x0'], t))
    vals = {k: (v[0] if len(v) == 1 else ' '.join(v)) for k, v in vals.items()}
    return rank, texts, rnd, vals


def _is_anchor(it):
    # 順位のある行、または順位の無い「DNS」（棄権）の行
    return it['rank'] is not None or any(t.endswith('DNS') for _, t in it['texts'])


def _merge_split_rows(items):
    out = []
    for it in items:
        # 姓だけ数pt上に出た氏名を、直下の順位の行につなぐ
        if out and _is_anchor(it) and it['texts'] and not out[-1]['vals'] \
                and not _is_anchor(out[-1]) and it['top'] - out[-1]['top'] < 4.0:
            it = dict(it, texts=out.pop()['texts'] + it['texts'])
        # 1本の演技の減点と点数が別の行に分かれたものをつなぐ
        if out and it['top'] - out[-1]['top'] < 4.0:
            a, b = out[-1], it
            a_s = any(k.startswith('S') for k in a['vals'] if k != 'Score')
            b_s = any(k.startswith('S') for k in b['vals'] if k != 'Score')
            if a_s != b_s and ('Score' in a['vals']) != ('Score' in b['vals']) \
                    and not set(a['vals']) & set(b['vals']) - {'Best', 'Total'}:
                vals = dict(a['vals'])
                vals.update(b['vals'])
                out[-1] = {'top': a['top'], 'page': a['page'], 'vals': vals,
                           'rank': a['rank'] if a['rank'] is not None else b['rank'],
                           'texts': a['texts'] + b['texts'], 'rnd': a['rnd'] or b['rnd']}
                continue
        out.append(it)
    return out


def _group_page(items, athletes, page_no, centered):
    """1ページの行を選手ごとにまとめ、athletes（前ページまで）に足していく。"""
    items = _merge_split_rows([it for it in items if it['texts'] or it['vals']])
    anchors = [it for it in items if _is_anchor(it)]
    if not anchors:
        if athletes:                               # 表の続きだけのページ
            athletes[-1]['lines'].extend(items)
        return
    new = [{'rank': a['rank'], 'lines': []} for a in anchors]
    if not centered:
        # 順位の行に氏名がある版：順位の行から次の順位の行の手前までが1人
        pre = {'lines': []}                        # 1ページ目の最初の順位より上
        cur = athletes[-1] if athletes else pre
        for it in items:
            if _is_anchor(it):
                cur = new[anchors.index(it)]
            cur['lines'].append(it)
        # 順位の行に氏名が無い選手（2行の氏名が上にはみ出した）は、直前の文字だけの行を引き取る
        prev = athletes[-1] if athletes else pre
        for a_it, a in zip(anchors, new):
            if not a_it['texts']:
                while prev['lines'] and not prev['lines'][-1]['vals'] and \
                        a_it['top'] - prev['lines'][-1]['top'] < 12 and \
                        prev['lines'][-1]['page'] == page_no:
                    a['lines'].insert(0, prev['lines'].pop())
            prev = a
    else:
        # 順位が氏名と所属の間に中央揃えで印字される版（2026〜）：最寄りの順位
        first_top = anchors[0]['top']
        for it in items:
            if it['top'] < first_top and athletes and (it['rnd'] or '').endswith('2'):
                athletes[-1]['lines'].append(it)   # 前ページの選手の2本目
                continue
            min(zip(anchors, new), key=lambda an: abs(an[0]['top'] - it['top']))[1]['lines'].append(it)
    athletes.extend(new)


def _join_wrapped(parts):
    """折り返した所属をつなぐ。英字どうしの境目だけ空白を入れる（Queen / Rouge）。"""
    out = ''
    for p in parts:
        if out and re.match(r'[A-Za-z]', p[:1]) and re.search(r'[A-Za-z]$', out):
            out += ' '
        out += p
    return out


def parse_pdf(pdf):
    """1本のPDFを選手のリストにして返す。各選手は rank・name・club・routines・agg を持つ。"""
    athletes = []
    cols = None
    centered = False
    heading = _n(' '.join((pdf.pages[0].extract_text() or '').splitlines()[:6]))
    for page_no, page in enumerate(pdf.pages, start=1):
        rows = _visual_rows(page)
        hi, pc = _header(rows)
        if pc:
            cols, start = pc, hi + 1
            centered = 'Hirotaka' in heading
        else:
            start = 0
        if cols is None:
            continue
        items = []
        for r in rows[start:]:
            text = ' '.join(w['text'] for w in r['words'])
            if FOOTER_RE.search(text):
                break
            if PRINT_RE.search(text):
                continue
            rank, texts, rnd, vals = _split_row(r, cols)
            items.append({'top': r['top'], 'rank': rank, 'texts': texts, 'rnd': rnd,
                          'vals': vals, 'page': page_no})
        _group_page(items, athletes, page_no, centered)
    out = []
    for a in athletes:
        lines = sorted(a['lines'], key=lambda it: (it['page'], it['top']))
        frags = _fragments(lines)
        # 読み仮名「（…）」が折り返していたら、閉じ括弧までを氏名に戻す
        while len(frags) > 1 and frags[0].count('(') > frags[0].count(')'):
            frags[0:2] = [frags[0] + frags[1]]
        routines = [dict(it['vals'], rnd=it['rnd'], page=it['page']) for it in lines
                    if any(k in it['vals'] for k in VALUE_KEYS)]
        agg = next((it['vals'][k] for it in lines for k in ('Best', 'Total') if k in it['vals']),
                   None)
        club = _join_wrapped(frags[1:])
        for old, new in CLUB_FIXES.items():
            club = club.replace(old, new)
        out.append({'rank': a['rank'], 'name': frags[0] if frags else '',
                    'club': club,
                    'routines': [r for r in routines if _performed(r)], 'agg': _f(agg)})
    return heading, ([c['key'] for c in cols] if cols else []), out


def _fragments(lines):
    """文字の断片を行ごとの文字列にする。top の差が3.5pt未満の行は同じ行として、
    左から順に並べ直す（所属が2.6ptずれて2つの視覚行に割れた例：テン・フォーティー）。"""
    groups = []
    for it in lines:
        if not it['texts']:
            continue
        if groups and groups[-1]['page'] == it['page'] and it['top'] - groups[-1]['top'] < 3.5:
            groups[-1]['texts'] += it['texts']
        else:
            groups.append({'page': it['page'], 'top': it['top'], 'texts': list(it['texts'])})
    return [' '.join(t for _, t in sorted(g['texts'], key=lambda xt: xt[0])) for g in groups]


def _performed(rt):
    """演技していない2本目（全項目0.00）は演技に数えない。"""
    if any(rt.get('S%d' % i) is not None for i in range(1, 11)):
        return True
    return (_f(rt.get('Score')) or 0) > 0


RADICAL_RANGE = re.compile(r'[\u2e80-\u2eff\u2f00-\u2fdf]')   # CJK部首補助・康熙部首


def clean_name(raw):
    """氏名から読み仮名「（…）」と棄権の印を外す。"""
    name = re.sub(r'\(.*?\)', '', raw or '')
    name = re.sub(r'\s*DNS$', '', name)
    name = name.strip()
    if RADICAL_RANGE.search(name):
        # RADICALS に無い部首の文字が残っていると、同じ選手が別人として登録される。
        # 黙って進めず止める（対応表に足してから回し直す）。
        raise ValueError('部首の文字コードが氏名に残っています（RADICALS に追加が必要）: %r' % name)
    return name


# ---- レコード -----------------------------------------------------------------

def load_all():
    """(competitions, performances) を返す。PDFが無ければ空。"""
    try:
        import pdfplumber
    except ImportError:
        return [], []
    import logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)

    competitions, performances = [], []
    for meet in load_manifest()['meets']:
        if not meet['include']:
            continue
        folder = os.path.join(config.RAW_ROOT, *meet['raw_dir'].split('/'))
        if not os.path.isdir(folder):
            continue
        perfs = []
        labels = {}                       # 区分|ラウンド → 'Best'（良いほう）／'Total'（合計）
        seq = 0
        for name in meet['files']:
            sec = section_of(name)
            if sec is None:
                raise ValueError('区分が読めないファイル名: %s' % name)
            cls, sex, rnd = sec
            category = '%sクラス %s' % (cls, sex)
            with pdfplumber.open(os.path.join(folder, name)) as pdf:
                _, cols, athletes = parse_pdf(pdf)
            if not cols:
                raise ValueError('列見出しが見つからない（画像のPDF？）: %s' % name)
            for key in ('Best', 'Total'):
                if key in cols:
                    labels['%s|%s' % (category, rnd)] = key
            for a in athletes:
                if not a['routines']:
                    continue                              # 棄権
                for i, rt in enumerate(a['routines'], start=1):
                    seq += 1
                    perfs.append(_record(meet, seq, a, rt, _routine_no(rt, i, len(a['routines'])),
                                         category, rnd, name))
        if perfs:
            competitions.append({
                'meet_id': meet['meet_id'], 'date': meet['date'], 'name': meet['name'],
                'level': '国内', 'season': meet['date'][:4],
                'source': SOURCE, 'official': config.SOURCES[SOURCE]['official'],
                'source_url': meet['post_url'],
                'event_id': '', 'fetched_at': '', 'raw_dir': meet['raw_dir'],
                # 予選の選手の値が「良いほう」か「合計」か。PDFの列見出しのとおり（画面の見出しに使う）
                'qualifying_labels': labels,
            })
            performances.extend(perfs)
    return competitions, performances


def _routine_no(rt, index, n_routines):
    """何本目か。PDFの印（Q2・予選2・決勝2）を正とする。1本目が0点で落ちた選手の
    2本目を「1本目」にしないため。印が無ければ並び順（1本だけなら1）。"""
    m = re.search(r'(\d)$', rt.get('rnd') or '')
    if m:
        return int(m.group(1))
    return index if n_routines > 1 else 1


def _record(meet, seq, athlete, rt, routine_no, category, round_label, pdf_name):
    s = [_f(rt.get('S%d' % i)) for i in range(1, 11)]
    n = sum(1 for v in s if v is not None)
    positions, unaccounted = [], 0
    for k in range(10):
        v = s[k]
        if v is None or k >= n:
            positions.append(None)
            unaccounted += v or 0
        else:
            positions.append(v)
    L = _f(rt.get('L'))
    if n == 10:
        landing = L
    else:
        landing = None                # 中断した演技は着地減点が乗らない（§19.9）
        unaccounted += L or 0
    diff = _f(rt.get('Diff'))
    d_implicit_zero = diff is None
    name = clean_name(athlete['name'])
    if RADICAL_RANGE.search(athlete['club'] or ''):
        raise ValueError('部首の文字コードが所属に残っています（RADICALS に追加が必要）: %r'
                         % athlete['club'])
    flags = []
    if d_implicit_zero:
        flags.append('D空欄を0として採用')
    if '-手作業' in pdf_name:
        flags.append('協会が手作業で作った結果表')
    return {
        'performance_id': '%s|%04d' % (meet['meet_id'], seq),
        'meet_id': meet['meet_id'], 'date': meet['date'], 'meet_name': meet['name'],
        'source': SOURCE, 'official': config.SOURCES[SOURCE]['official'],
        'discipline': '個人', 'category': category,
        'sex': 'female' if '女子' in category else ('male' if '男子' in category else ''),
        'age_group': '', 'round': round_label, 'round_raw': round_label,
        'routine': routine_no,
        'athlete_name': name, 'athlete_names': [name],
        'club': athlete['club'], 'birth_date': None, 'rank': athlete['rank'],
        'total': _f(rt.get('Score')),
        'D': 0.0 if d_implicit_zero else diff, 'D_implicit_zero': d_implicit_zero,
        'E': _f(rt.get('Exe')), 'T': _f(rt.get('ToF')), 'HD': _f(rt.get('HD')),
        'Bonus': None, 'Pen': _f(rt.get('Pen')), 'DPen': None,
        'n_elements': n,
        'deduct_positions': positions, 'deduct_landing': landing,
        'deduct_extra_a': _f(rt.get('A')), 'deduct_unaccounted': unaccounted,
        'deduct_unit': 'median2_sum_tenths',
        'judge_E': {}, 'judge_HD': {}, 'panel_key': None,
        'state': None, 'stage_id': None, 'frame_id': None, 'perf_id_raw': None,
        'qualifying_total': athlete['agg'],
        'raw': {},
        'provenance': {
            'source': SOURCE,
            'source_url': meet['post_url'],
            'raw_filename': '%s p%d' % (pdf_name, rt['page']),
            'imported_at': '', 'parser_version': config.PARSER_VERSION,
            'correction_flag': '／'.join(flags),
        },
    }
