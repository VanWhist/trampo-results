# -*- coding: utf-8 -*-
"""西日本トランポリン協会のリザルトPDFを直接読む（第54回・2026〜）。

第53回（2025）は変換済みCSVを受け取っていたが、第54回はCSVが無いのでPDFを読む。
ファイル構成も変わっている。

  第53回: 1PDF＝複数区分（8本）／列は Rank Name S1..S10 Lnd Exe Diff ToF HD Pen Score
  第54回: 1PDF＝1区分×1ラウンド（26本）／予選に Rtn 列と Total 列が追加

**列の割り当ては x 座標で行う。** 値が0の列はPDFに印字されないため、
テキストを空白で分割すると列がずれる（第53回で実際に踏んだ落とし穴）。
見出し行の各列の位置を取り、データ側の各語をいちばん近い列に入れる。
こうすると「印字されていない＝そのセルが空」として素直に扱える。

  1 中田 悠暉 Q1 4 2 2 2 3 1 0 3 6 5 3 16.90 16.19 9.80 0.0 42.89 102.60
                                          ↑ Diff（規定演技で0）が印字されていない

そのほかの決まり:
  ・`_訂正.pdf` があれば、そちらを正とする（元のファイルは読まない）
  ・`決勝スタートリスト` は結果ではないので読まない
  ・所属は選手行の次の行。予選はQ2行の先頭、決勝は独立行（長いと折り返す）
"""
import collections
import os
import re
import unicodedata

from .. import config

PDF_DIR_2026 = os.path.join(config.RAW_ROOT, '2026', '西日本トランポリン協会_PDF')

MEET = {
    'meet_id': 'nw-2026-09-04',
    'date': '2026-09-04',
    'name': '第54回西日本トランポリン競技選手権大会',
    'level': '国内',
    'season': '2026',
    'venue': 'いしかわ総合スポーツセンター',
}

CATEGORY_WORDS = ('小学生低学年', '小学生高学年', '低学年', '高学年',
                  '中学生', '高校生', '大学生', '一般', 'オープン')
CATEGORY_LABEL = {'低学年': '小学生低学年', '高学年': '小学生高学年'}
HEADING_RE = re.compile(r'個人(男子|女子)(' + '|'.join(CATEGORY_WORDS) + r')(予選|決勝)?')

# 見出しの語 → レコードの項目。'Di' は PDF 上で 'Di ' と切れて出ることがある。
COLUMNS = [('Rank', 'rank'), ('Name', 'name'), ('Rtn', 'rtn')]
COLUMNS += [('S%d' % i, 'S%d' % i) for i in range(1, 11)]
COLUMNS += [('Lnd', 'Lnd'), ('Exe', 'Exe'), ('Di', 'Diff'), ('ToF', 'ToF'),
            ('HD', 'HD'), ('Pen', 'Pen'), ('Score', 'Score'), ('Total', 'Total')]

ROW_TOL = 2.5          # これ以内の top は同じ視覚行（氏名は数値行と 0.9pt ずれる）
DATE_RE = re.compile(r'\d{4}/\d{2}/\d{2}$')      # 継続ページ上端の日付行


def _n(text):
    # 見出しの Diff は 'Di' + NUL のように制御文字が混じる。先に落とす。
    text = ''.join(ch for ch in (text or '') if ch == ' ' or ch >= ' ')
    return unicodedata.normalize('NFKC', text).strip()


def _f(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def result_pdfs(directory=None):
    """読むべきPDFを決める。訂正版があれば元のファイルは読まない。

    完全性の検査（etl/completeness.py）も同じ決め方でページを数える必要があるため、
    ディレクトリを受け取れるようにしてある。二重に書くと片方だけ直して食い違う。
    """
    directory = PDF_DIR_2026 if directory is None else directory
    if not os.path.isdir(directory):
        return []
    names = [n for n in sorted(os.listdir(directory)) if n.lower().endswith('.pdf')]
    names = [n for n in names if 'スタートリスト' not in n and '特別賞' not in n]
    corrected = {n.replace('_訂正.pdf', '.pdf') for n in names if n.endswith('_訂正.pdf')}
    out = []
    for n in names:
        if n in corrected:
            continue                      # 訂正版があるので元は読まない
        out.append(n)
    return out


def _visual_rows(page):
    """語を視覚的な行にまとめる（top が近いものは同じ行）。"""
    words = [dict(w, text=_n(w['text'])) for w in page.extract_words()]
    words = [w for w in words if w['text']]
    rows = []
    for w in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if rows and abs(w['top'] - rows[-1]['top']) <= ROW_TOL:
            rows[-1]['words'].append(w)
            rows[-1]['top'] = min(rows[-1]['top'], w['top'])
        else:
            rows.append({'top': w['top'], 'words': [w]})
    for r in rows:
        r['words'].sort(key=lambda w: w['x0'])
    return rows


def _header(rows):
    """見出し行を見つけ、列の中心x座標を返す。"""
    for i, r in enumerate(rows):
        texts = [w['text'] for w in r['words']]
        if 'Rank' in texts and any(t.startswith('Score') for t in texts):
            cols = []
            for w in r['words']:
                text = w['text']
                for label, key in COLUMNS:
                    # Diff は 'Di' + NUL や 'Dif' のように切れて出るので前方一致で拾う
                    hit = text == label or (label == 'Di' and text.startswith('Di'))
                    if hit:
                        cols.append({'key': key, 'x0': w['x0'], 'x1': w['x1'],
                                     'center': (w['x0'] + w['x1']) / 2})
                        break
            return i, cols
    return None, None


def _assign(row_words, cols):
    """各語を列に入れる。値が無い列は空のまま。

    順位と氏名だけは中心座標では分けられない。順位は右詰めの数字、氏名はその右から
    左詰めで始まるので、中心で最寄りを取ると姓が順位列に吸われる（中田＝x62 が
    Rank列の中心44に近い）。左端の領域は「最初の数字だけ順位、残りは氏名」で分ける。
    """
    by_key = {c['key']: c for c in cols}
    # 数値列が始まる位置。ここより左は順位・氏名の領域。
    first_num = min((by_key[k]['x0'] for k in ('rtn', 'S1') if k in by_key), default=None)
    cell = collections.defaultdict(list)
    left = [w for w in row_words if first_num is not None
            and (w['x0'] + w['x1']) / 2 < first_num - 2]
    rest = [w for w in row_words if w not in left]

    took_rank = False
    for w in left:
        if not took_rank and 'rank' in by_key and re.fullmatch(r'\d+', w['text']):
            cell['rank'].append(w['text'])
            took_rank = True
        else:
            cell['name'].append(w['text'])

    numeric_cols = [c for c in cols if c['key'] not in ('rank', 'name')]
    for w in rest:
        center = (w['x0'] + w['x1']) / 2
        best = min(numeric_cols, key=lambda c: abs(c['center'] - center))
        cell[best['key']].append(w['text'])
    out = {k: ' '.join(v) for k, v in cell.items()}

    # 短い所属は氏名列に中央揃えで入るため、右隣の Q2 とすき間なく並んで
    # 'RISEQ2' のような1語で抽出される。中心が数値列側に寄るので Rtn 列に
    # 落ちてしまう。ここで所属と演技番号に割り戻す。
    m = re.match(r'^(.*\S)(Q\d)$', out.get('rtn', ''))
    if m:
        out['rtn'] = m.group(2)
        out['name'] = (out.get('name', '') + ' ' + m.group(1)).strip()
    return out


def _club_span(row_words):
    """所属行の先頭に並ぶ所属の語の (左端, 右端) を返す。切り詰めの測定に使う。

    行の残りは Q2 と得点なので、最初の数値／ラウンド記号で打ち切る。短い所属が
    'RISEQ2' のように Q2 と1語になっている場合は Q2 のぶんだけ右端を多めに見積もる
    （そういう所属は列の端から遠いので、切り詰めの判定には影響しない）。
    """
    x0 = x1 = None
    for w in row_words:
        if re.fullmatch(r'\d+(?:\.\d+)?', w['text']) or re.fullmatch(r'Q\d', w['text']):
            break
        if x0 is None:
            x0 = w['x0']
        x1 = w['x1']
    return (x0, x1) if x0 is not None else None


def measure_club_lines():
    """PDFごとに所属の行の幅を測る。(ファイル名, 折り返した幅, 1行で収まった幅) を返す。

    第53回は列幅を超えた所属が黙って切り詰められていた。第54回は同じ所属が2行に
    折り返して印字される。折り返しなら情報は落ちないが、そう決めつけずに毎回測る。
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    import logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)
    out = []
    for name in result_pdfs():
        with pdfplumber.open(os.path.join(PDF_DIR_2026, name)) as pdf:
            _, athletes = _parse_pdf(pdf)
        wrapped, single = [], []
        for a in athletes:
            spans = [s for s in a['club_spans'] if s]
            if len(spans) < 1:
                continue
            if len(spans) > 1:
                # 最終行以外は「そこで折り返した」幅
                wrapped += [(s[1] - s[0], a['club']) for s in spans[:-1]]
            else:
                single.append((spans[0][1] - spans[0][0], a['club']))
        out.append({'file': name, 'wrapped': wrapped, 'single': single})
    return out


def _parse_pdf(pdf):
    """1本のPDFを (区分, ラウンド, 選手) にして返す。

    **ページ単位では読めない。** 見出しと列見出しは1ページ目にしか無く、2ページ目
    以降は表の続きがいきなり始まる。しかも選手はページ境界で割れる（1本目が前の
    ページの最終行、所属＋2本目が次のページの先頭行）。列の位置と読みかけの選手を
    ページをまたいで持ち回る。
    """
    heading = None
    cols = None
    athletes = []
    for page_no, page in enumerate(pdf.pages, start=1):
        rows = _visual_rows(page)
        if heading is None:
            heading = HEADING_RE.search(_n(page.extract_text() or '').replace(' ', ''))
        head_i, page_cols = _header(rows)
        if page_cols:
            cols = page_cols
            start = head_i + 1
        else:
            start = 0                      # 継続ページ。表の続きが上端から始まる
        if cols is None:
            continue
        rank_x0 = next((c['x0'] for c in cols if c['key'] == 'rank'), 0)
        for r in rows[start:]:
            text = ' '.join(w['text'] for w in r['words'])
            if 'Export CSV' in text or 'result.php' in text or 'T-product' in text:
                break                      # フッタ
            if DATE_RE.match(r['words'][0]['text']):
                continue                   # 継続ページ上端の「2026/09/05 15:37 Result」
            cell = _assign(r['words'], cols)
            rank = _f(cell.get('rank'))
            if rank is not None and cell.get('name'):
                athletes.append({'rank': int(rank), 'name': cell['name'], 'club': '',
                                 'routines': [], 'club_lines': [], 'club_spans': []})
                _add_routine(athletes[-1], cell, page_no)
            elif athletes:
                # 表の下のフッタ（署名欄の 'signature CJP'）は順位が無いので所属行に
                # 見えてしまう。所属は氏名列に中央揃えで入るため実測でいちばん左でも
                # 54.6pt、いっぽう署名欄は順位列と同じ 33.5pt。左端で表の終わりを判る。
                if r['words'][0]['x0'] <= rank_x0 + 10:
                    break
                # 順位が無い行 = 所属行。予選はQ2の値も同じ行にある
                if cell.get('name'):
                    # 予選のQ2行は「所属Q2」と連結しているので、末尾のラウンド記号を外す
                    club = re.sub(r'Q\d$', '', cell['name']).strip()
                    if club:
                        athletes[-1]['club_lines'].append(club)
                        athletes[-1]['club_spans'].append(_club_span(r['words']))
                if any(cell.get('S%d' % i) for i in range(1, 11)) or cell.get('Score'):
                    _add_routine(athletes[-1], cell, page_no)
    for a in athletes:
        a['club'] = ''.join(a['club_lines'])
    return heading, athletes


def _add_routine(athlete, cell, page_no):
    athlete['routines'].append({
        'page': page_no,
        'rtn': cell.get('rtn') or '',
        'S': [_f(cell.get('S%d' % i)) for i in range(1, 11)],
        'Lnd': _f(cell.get('Lnd')),
        'Exe': _f(cell.get('Exe')), 'Diff': _f(cell.get('Diff')),
        'ToF': _f(cell.get('ToF')), 'HD': _f(cell.get('HD')),
        'Pen': _f(cell.get('Pen')), 'Score': _f(cell.get('Score')),
        'Total': _f(cell.get('Total')),
    })


def load_all():
    """(competitions, performances) を返す。PDFが無ければ空。"""
    try:
        import pdfplumber
    except ImportError:
        return [], []
    if not result_pdfs():
        return [], []
    import logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)

    competition = {
        'meet_id': MEET['meet_id'], 'date': MEET['date'], 'name': MEET['name'],
        'level': MEET['level'], 'season': MEET['season'],
        'source': 'nishinihon', 'official': config.SOURCES['nishinihon']['official'],
        'source_url': config.SOURCES['nishinihon']['base_url'],
        'event_id': '', 'fetched_at': '',
        'raw_dir': '2026/西日本トランポリン協会_PDF',
    }

    performances = []
    seq = 0
    for name in result_pdfs():
        path = os.path.join(PDF_DIR_2026, name)
        with pdfplumber.open(path) as pdf:
            m, athletes = _parse_pdf(pdf)
            if not m or not athletes:
                continue
            sex, cat_word, rnd = m.group(1), m.group(2), m.group(3)
            category = '%s %s' % (CATEGORY_LABEL.get(cat_word, cat_word), sex)
            round_label = rnd or '決勝'          # 決勝は見出しに「決勝」が無い版がある
            for a in athletes:
                # 予選合計は1本目の行末にしか印字されないが、選手の値であって
                # 演技の値ではない。第53回のCSVと同じく両方の行に持たせる。
                a['qualifying_total'] = next(
                    (r['Total'] for r in a['routines'] if r['Total'] is not None), None)
                for i, rt in enumerate(a['routines'], start=1):
                    seq += 1
                    performances.append(_record(
                        seq, a, rt, i, category, round_label, name,
                        len(a['routines'])))
    return ([competition] if performances else []), performances


def _record(seq, athlete, rt, index, category, round_label, pdf_name, n_routines):
    n = sum(1 for v in rt['S'] if v is not None)
    positions, unaccounted = [], 0
    for k in range(10):
        v = rt['S'][k]
        if v is None or k >= n:
            positions.append(None)
            unaccounted += v or 0
        else:
            positions.append(v)
    if n == 10:
        landing = rt['Lnd']
    else:
        landing = None
        unaccounted += rt['Lnd'] or 0

    # PDFは0を印字しないので、空欄のDiffは欠測ではなく0（予選1本目＝規定演技）
    d_implicit_zero = rt['Diff'] is None
    return {
        'performance_id': '%s|%04d' % (MEET['meet_id'], seq),
        'meet_id': MEET['meet_id'], 'date': MEET['date'], 'meet_name': MEET['name'],
        'source': 'nishinihon', 'official': config.SOURCES['nishinihon']['official'],
        'discipline': '個人', 'category': category,
        'sex': 'female' if '女子' in category else ('male' if '男子' in category else ''),
        'age_group': '', 'round': round_label, 'round_raw': round_label,
        'routine': index if n_routines > 1 else 1,
        'athlete_name': athlete['name'], 'athlete_names': [athlete['name']],
        'club': athlete['club'], 'birth_date': None, 'rank': athlete['rank'],
        'total': rt['Score'],
        'D': 0.0 if d_implicit_zero else rt['Diff'], 'D_implicit_zero': d_implicit_zero,
        'E': rt['Exe'], 'T': rt['ToF'], 'HD': rt['HD'],
        'Bonus': None, 'Pen': rt['Pen'], 'DPen': None,
        'n_elements': n,
        'deduct_positions': positions, 'deduct_landing': landing,
        'deduct_extra_a': None, 'deduct_unaccounted': unaccounted,
        'deduct_unit': 'median2_sum_tenths',
        'judge_E': {}, 'judge_HD': {}, 'panel_key': None,
        'state': None, 'stage_id': None, 'frame_id': None, 'perf_id_raw': None,
        'qualifying_total': athlete.get('qualifying_total'),
        'raw': {},
        'provenance': {
            'source': 'nishinihon',
            'source_url': config.SOURCES['nishinihon']['base_url'],
            'raw_filename': '%s p%d' % (pdf_name, rt['page']),
            'imported_at': '', 'parser_version': config.PARSER_VERSION,
            'correction_flag': ('訂正版を採用' if '_訂正' in pdf_name else '')
                               + ('／D空欄を0として採用（規定演技）' if d_implicit_zero else ''),
        },
    }
