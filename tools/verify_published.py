# -*- coding: utf-8 -*-
"""公開しているリザルト（data/）が原本と一致しているかを、ETLとは別の読み方で確かめる。

    python tools/verify_published.py            # 全部
    python tools/verify_published.py --no-live  # 本番サイトと sporttech への問い合わせをしない

**ETL のコード（etl.sources など）は使わない。** 同じコードで確かめると、同じ間違いを見逃す。
原本は次の方法で読み直す。
  sporttech   … 生JSONを自前で合体して読む（etl/sources/sporttech.py とは別に書いた）
  西日本 第53回 … 変換済みCSVを直接読む
  西日本 第54回 … PDFを**行テキストと小数の桁の形**で読む（ETLは語の座標で読んでいる）
  大阪府       … 元HTMLを自前の正規表現で読む
ほかに、公開データ同士の整合（年別・大会別・選手別のファイルが同じ中身か、合計の式）、
本番サイトのファイルが手元と同じか、保存した原本がいまの sporttech と同じか（抜き取り）を見る。
"""
import argparse
import collections
import csv
import glob
import gzip
import hashlib
import io
import json
import os
import random
import re
import sys
import unicodedata
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, 'data')
RAW = os.environ.get('TRAMPO_RAW_ROOT') or os.path.normpath(
    os.path.join(REPO, os.pardir, 'トランポリンルール', '大会リザルト'))
LIVE = 'https://vanwhist.github.io/trampo-results/data/'
UA = {'User-Agent': 'trampo-results verification (personal, non-commercial)'}
TOL = 0.0005

# sporttech の画面プログラムにある公式の対応表（2026-09-25 に確認）
STAGE_KIND = {0: '予選', 1: '準々決勝', 2: '準決勝', 3: '決勝', 4: '団体準決勝',
              5: '団体決勝', 6: '予選2', 7: '決勝2', 8: '決勝1'}
PLACEHOLDERS = (0, 100)
# 異体字（公開側の氏名は吸収済み）。比べる前に両方をそろえる
# 異体字。公開側は ETL が吸収済み（etl/normalize.py の NAME_VARIANTS と同じ4つ）。
# ここに無い文字の違いは、そのまま不一致として出す
VARIANTS = {'髙': '高', '﨑': '崎', '瀨': '瀬', 'ヶ': 'ケ'}


def jload(path):
    with io.open(path, encoding='utf-8-sig') as fh:
        return json.load(fh)


def norm_name(s):
    s = unicodedata.normalize('NFKC', s or '')
    for a, b in VARIANTS.items():
        s = s.replace(a, b)
    return re.sub(r'\s+', '', s)


def close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= TOL


class Result:
    def __init__(self, name):
        self.name = name
        self.checked = 0
        self.bad = []

    def ok(self):
        self.checked += 1

    def fail(self, msg):
        self.checked += 1
        self.bad.append(msg)


# ---- 公開データ ------------------------------------------------------------------

def published():
    comps = jload(os.path.join(DATA, 'competitions.json'))
    rows = []
    for p in sorted(glob.glob(os.path.join(DATA, 'performances', '*.json'))):
        if '-other' in p:
            continue
        rows += jload(p)
    return comps, rows


# ---- 1. sporttech ------------------------------------------------------------------

def _merge(folder):
    keys = ('Athletes', 'Competitions', 'Stages', 'Groups', 'Performances', 'Frames')
    model = {k: {} for k in keys}
    for path in [os.path.join(folder, 'event.json')] + sorted(glob.glob(os.path.join(folder, 'stage_*.json'))):
        if not os.path.exists(path):
            continue
        doc = jload(path)
        for k in keys:
            for ident, v in (doc.get(k) or {}).items():
                model[k].setdefault(ident, v)
    return model


def _pre2017(meta):
    rules = meta.get('rules') or ''
    if rules:
        return not re.search(r'20(1[7-9]|[2-9]\d)', rules)
    return meta['date'] < '2017-03'


def check_sporttech(comps, rows):
    res = Result('sporttech：原本の生JSON と公開の全演技')
    folders = {}
    for m in glob.glob(os.path.join(RAW, '*', 'sporttech_*', '*', '_meta.json')):
        folders[jload(m)['event_id']] = os.path.dirname(m)
    pub = collections.defaultdict(dict)
    for r in rows:
        if r['meet_id'].startswith('st-'):
            pub[r['meet_id']][int(r['performance_id'].split('|f')[1])] = r
    for c in comps:
        if c['source'] != 'sporttech':
            continue
        folder = folders.get(c['event_id'])
        if not folder:
            res.fail('%s の原本フォルダが見つからない' % c['meet_id'])
            continue
        meta = jload(os.path.join(folder, '_meta.json'))
        pre = _pre2017(meta)
        m = _merge(folder)
        expected = {}
        for fid, f in m['Frames'].items():
            if f.get('State') == 0 or ('NElements' in f and f.get('NElements') == 0):
                continue
            perf = m['Performances'].get(str(f.get('PerformanceID'))) or {}
            group = m['Groups'].get(str(perf.get('GroupID'))) or {}
            stage = m['Stages'].get(str(group.get('StageID'))) or {}
            comp = m['Competitions'].get(str(stage.get('CompetitionID'))) or {}
            if comp.get('Discipline') != 0:
                continue
            expected[int(fid)] = (f, perf, stage, comp)
        got = pub.get(c['meet_id'], {})
        for fid in sorted(set(expected) - set(got)):
            res.fail('%s f%d が公開されていない' % (c['meet_id'], fid))
        for fid in sorted(set(got) - set(expected)):
            res.fail('%s f%d が原本に無いのに公開されている' % (c['meet_id'], fid))
        for fid in sorted(set(expected) & set(got)):
            f, perf, stage, comp = expected[fid]
            r = got[fid]
            marks = [v for v in (f.get('ETotalsT_G') or {}).values() if v]
            no_exec = (marks and all(v in PLACEHOLDERS for v in marks) and not f.get('MarkTTT_G')
                       and not f.get('DifficultyT_G') and not f.get('TimeTMS_G'))

            def sc(field, div):
                v = f.get(field)
                return round(v / div, 3) if isinstance(v, (int, float)) else None
            want = {
                'total': sc('MarkTTT_G', 1000.0), 'D': sc('DifficultyT_G', 10.0),
                'E': None if no_exec else sc('ETotalT_G', 10.0),
                'T': sc('TimeTMS_G', 1000.0), 'HD': None if pre else sc('Displacement_G', 100.0),
            }
            diffs = [k for k, v in want.items() if not close(v, r.get(k))]
            names = []
            for aid in (perf.get('Athletes') or []):
                a = m['Athletes'].get(str(aid)) or {}
                names.append(('%s %s' % ((a.get('Surname') or '').strip(), (a.get('GivenName') or '').strip())).strip())
            rank = perf.get('Rank_G') if perf.get('Ranked') is not False else None
            if (rank or None) != (r.get('rank') or None):
                diffs.append('rank')
            if STAGE_KIND.get(stage.get('Kind')) != r.get('round'):
                diffs.append('round')
            if (comp.get('Title') or '').strip() != r.get('category'):
                diffs.append('category')
            if len(names) == 1 and norm_name(names[0]) != norm_name(r.get('athlete_name')):
                diffs.append('name')
            if bool(pre) != bool(r.get('pre2017')):
                diffs.append('pre2017')
            if diffs:
                res.fail('%s f%d %s：%s' % (c['meet_id'], fid, r.get('athlete_name'), ', '.join(
                    '%s 原本%s／公開%s' % (k, want.get(k, {'rank': rank, 'round': STAGE_KIND.get(stage.get('Kind')),
                                                         'category': comp.get('Title'), 'name': names,
                                                         'pre2017': pre}.get(k)), r.get(k if k != 'name' else 'athlete_name'))
                    for k in diffs)))
            else:
                res.ok()
    return res


# ---- 2. 西日本 --------------------------------------------------------------------

def _f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def check_nishi53(rows):
    res = Result('西日本 第53回：変換済みCSV と公開')
    path = os.path.join(RAW, '_西日本53th_全演技.csv')
    with io.open(path, encoding='utf-8-sig') as fh:
        src = list(csv.DictReader(fh))
    pub = {(r['category'], r['round'], norm_name(r['athlete_name']), r.get('routine')): r
           for r in rows if r['meet_id'] == 'nw-2025-09-12'}
    seen = set()
    for s in src:
        key = (s['種別'], s['ラウンド'], norm_name(s['選手']), int(s['演技']) if s['演技'] else None)
        r = pub.get(key)
        if r is None:
            res.fail('公開に無い：%s' % (key,))
            continue
        seen.add(key)
        # PDF は値が0の列を印字しないので、CSV の D の空欄は 0（予選1本目＝規定演技など）
        d = _f(s['D'])
        if d is None:
            d = 0.0
        want = {'total': _f(s['合計']), 'D': d, 'E': _f(s['E']), 'T': _f(s['T']), 'HD': _f(s['HD']),
                'Pen': _f(s['Pen']), 'rank': _f(s['順位']), 'n_elements': _f(s['技数'])}
        diffs = [k for k, v in want.items() if not close(v, _f(r.get(k)))]
        if diffs:
            res.fail('%s：%s' % (key, ', '.join('%s CSV%s／公開%s' % (k, want[k], r.get(k)) for k in diffs)))
        else:
            res.ok()
    for key in set(pub) - seen:
        res.fail('CSVに無いのに公開されている：%s' % (key,))
    return res


DEC = re.compile(r'^\d+\.\d+$')


def _pdf_lines(path):
    import logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out += [unicodedata.normalize('NFKC', l) for l in (page.extract_text() or '').splitlines()]
    return out


# 列の並びと小数の桁。0 の列は印字されないので、Diff と Pen は無いことがある
SLOTS = (('E', 2, True), ('D', 1, False), ('T', 2, True), ('HD', 2, True), ('Pen', 1, False),
         ('total', 2, True), ('qualifying_total', 2, False))


def _values(tokens):
    """行の小数だけを取り、列の並び（SLOTS）に順番どおり当てはめる。
    桁の形が合わない任意の列は飛ばす（その列は印字されていない＝0 か空欄）。"""
    decs = [t for t in tokens if DEC.match(t)]
    out, i = {}, 0
    for key, places, required in SLOTS:
        if i < len(decs) and len(decs[i].split('.')[1]) == places:
            out[key] = float(decs[i]); i += 1
        elif required:
            return None
    if i != len(decs):
        return None                                  # 余った小数がある＝読み違い
    out.setdefault('D', 0.0)                         # Diff は印字が無ければ 0（規定演技など）
    return out


def check_nishi54(rows):
    res = Result('西日本 第54回：PDF（行テキストで読み直し）と公開')
    folder = os.path.join(RAW, '2026', '西日本トランポリン協会_PDF')
    names = [n for n in sorted(os.listdir(folder)) if n.endswith('.pdf')
             and 'スタートリスト' not in n and '特別賞' not in n]
    corrected = {n.replace('_訂正.pdf', '.pdf') for n in names if n.endswith('_訂正.pdf')}
    names = [n for n in names if n not in corrected]
    pub = collections.defaultdict(list)
    for r in rows:
        if r['meet_id'] == 'nw-2026-09-04':
            pub[(r['category'], r['round'])].append(r)
    for name in names:
        m = re.match(r'54th_(.+?)(男子|女子)_(予選|決勝)', name)
        cat = '%s %s' % (m.group(1), m.group(2))
        rnd = m.group(3)
        read = []                                   # (順位, 氏名, 本目, 値)
        current = None
        pending_q = False                           # 「所属Q2」だけの行のあと、数値が次の行に来る
        numeric = lambda t: re.fullmatch(r'\d+(\.\d+)?', t) is not None
        for line in _pdf_lines(os.path.join(folder, name)):
            tokens = line.split()
            if not tokens:
                continue
            vals = _values(tokens)
            # 選手の行：順位（整数）のあとに数値でない語（氏名）が続き、値がそろっている
            if (len(tokens) > 2 and re.fullmatch(r'\d+', tokens[0]) and not numeric(tokens[1])
                    and not re.fullmatch(r'Q\d', tokens[1]) and vals is not None):
                name_tokens = []
                for t in tokens[1:]:
                    if numeric(t) or re.fullmatch(r'Q\d', t):
                        break
                    name_tokens.append(t)
                current = [int(tokens[0]), ' '.join(name_tokens), 1]
                read.append((current[0], current[1], 1, vals))
                pending_q = False
            elif current and re.search(r'Q\d', line) and vals is not None:
                current[2] += 1                     # 予選の2行目（所属Q2 …）
                read.append((current[0], current[1], current[2], vals))
                pending_q = False
            elif current and re.search(r'Q\d$', line) and vals is None:
                pending_q = True
            elif current and pending_q and vals is not None:
                current[2] += 1
                read.append((current[0], current[1], current[2], vals))
                pending_q = False
        mine = {(r.get('rank'), norm_name(r['athlete_name']), r.get('routine')): r for r in pub[(cat, rnd)]}
        got = set()
        for rank, nm, routine, v in read:
            r = mine.get((rank, norm_name(nm), routine))
            if r is None:
                res.fail('%s %s %d位 %s %d本目 が公開に無い' % (cat, rnd, rank, nm, routine))
                continue
            got.add((rank, norm_name(nm), routine))
            diffs = [k for k, x in v.items() if not close(x, r.get(k))]
            if diffs:
                res.fail('%s %s %d位 %s %d本目：%s' % (cat, rnd, rank, nm, routine,
                         ', '.join('%s PDF%s／公開%s' % (k, v[k], r.get(k)) for k in diffs)))
            else:
                res.ok()
        for k in set(mine) - got:
            res.fail('%s %s %s がPDFの行から読めない（公開にはある）' % (cat, rnd, k))
    return res


# ---- 3. 大阪府 --------------------------------------------------------------------

def _cells(tr):
    return re.findall(r'(?is)<t[dh][^>]*>(.*?)</t[dh]>', tr)


def _txt(h):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', re.sub(r'<[^>]+>', ' ', h).replace('&nbsp;', ' '))).strip()


def check_osaka(comps, rows):
    """元HTMLを読み直して公開と比べる。

    同じ演技が2つの区分ページに載っていることがある（2025-05-10 の「09才～10才女子」と
    「10才以下女子」、18名×2本）。ETL は1回だけ取り込むので、そういう演技は
    「公開に1件だけあり、どちらのページの値ともそろっている」ことを確かめる。"""
    res = Result('大阪府：元HTML と公開')
    dates = {c['date'] for c in comps if c['source'] == 'osaka_pweb'}
    pub = {}
    for r in rows:
        if r['meet_id'].startswith('os-'):
            cat = re.sub(r'\s+', '', unicodedata.normalize('NFKC', r['category']))
            pub[(r['meet_id'][3:], cat, norm_name(r['athlete_name']), r['routine'])] = r
    entries = collections.defaultdict(list)          # (日付, 氏名, 本目) → [(区分, 値)]
    for path in glob.glob(os.path.join(RAW, '*', '大阪府_pweb', '*', '*.html')):
        base = os.path.basename(path)
        if any(w in base for w in ('戻る', 'ｽﾀｰﾄ', 'スタート')) or base.startswith('detail_'):
            continue
        raw = io.open(path, encoding='utf-8', errors='replace').read()
        t = _txt(raw)
        md = re.search(r'期日[：:](\d{4})年(\d{1,2})月(\d{1,2})日', t)
        mh = re.search(r'【(.*?)】', t)
        if not md or not mh:
            continue
        date = '%s-%02d-%02d' % (md.group(1), int(md.group(2)), int(md.group(3)))
        if date not in dates:
            continue                                # まだ取り込んでいない大会（自前で新しく取った分）
        head = mh.group(1)
        final = head.endswith('決勝成績')
        cat = re.sub(r'(予選成績|決勝成績|結果成績)$', '', head)
        cat = re.sub(r'^個人競技', '', cat)
        # 元HTMLの「～」は文字化けで「?」。公開側と同じ手順（NFKC→空白除去）でそろえる
        cat = re.sub(r'\s+', '', unicodedata.normalize('NFKC', cat.replace('?', '～')))
        for tr in re.findall(r'(?is)<tr[^>]*>(.*?)</tr>', raw):
            cs = _cells(tr)
            if len(cs) not in (10, 11):
                continue
            rank = _txt(cs[0])
            if not (rank.isdigit() or rank == '棄権'):
                continue
            name = norm_name(_txt(cs[1]))
            vals = [[_txt(x) for x in re.split(r'(?i)<br\s*/?>', c) if _txt(x)] for c in cs[3:]]
            if final and len(cs) == 11:
                routines = [(3, [vals[k][0] if vals[k] else None for k in range(1, 7)])]
            else:
                n = max(len(v) for v in vals[:6])
                routines = [(i + 1, [vals[k][i] if i < len(vals[k]) else None for k in range(6)]) for i in range(n)]
            for routine, (e, h, d, tt, p, sm) in routines:
                want = {'E': _f(e), 'HD': _f(h), 'D': _f(d), 'T': _f(tt), 'Pen': _f(p), 'total': _f(sm),
                        'rank': int(rank) if rank.isdigit() else None}
                entries[(date, name, routine)].append((cat, want))
    seen = set()
    duplicated = 0
    for (date, name, routine), items in entries.items():
        keys = [(date, cat, name, routine) for cat, _ in items]
        found = [k for k in keys if k in pub]
        if not found:
            res.fail('公開に無い：%s' % (keys[0],))
            continue
        if len(found) > 1:
            res.fail('同じ演技が公開に2件ある：%s' % (found,))
            continue
        r = pub[found[0]]
        seen.add(found[0])
        if len(items) > 1:
            duplicated += 1
        for cat, want in items:
            # 重複掲載のもう一方は順位が区分ごとに違うので、順位は公開の区分のページでだけ比べる
            fields = [k for k in want if k != 'rank' or (date, cat, name, routine) == found[0]]
            diffs = [k for k in fields if not close(want[k], _f(r.get(k)) if k != 'rank' else r.get(k))]
            if diffs:
                res.fail('%s（%s のページ）：%s' % (found[0], cat, ', '.join(
                    '%s HTML%s／公開%s' % (k, want[k], r.get(k)) for k in diffs)))
            else:
                res.ok()
    for key in set(pub) - seen:
        res.fail('HTMLに無いのに公開されている：%s' % (key,))
    if duplicated:
        print('      （2つの区分ページに重複して載っていた演技 %d 本は、公開の1件と両方のページの値を照合）'
              % duplicated)
    return res


# ---- 4. 公開データの中の整合 ----------------------------------------------------------

def check_internal(comps, rows):
    res = Result('公開データの中の整合（年別・大会別・選手別・合計の式・件数・自己ベスト）')
    manifest = jload(os.path.join(DATA, 'manifest.json'))
    dump = lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False)
    year_rows = collections.Counter(dump(r) for r in rows)
    meet_rows = collections.Counter()
    for p in glob.glob(os.path.join(DATA, 'meets', '*.json')):
        meet_rows.update(dump(r) for r in jload(p))
    shard_rows = collections.Counter()
    for p in glob.glob(os.path.join(DATA, 'by_athlete', '*.json')):
        shard_rows.update(dump(r) for r in jload(p))
    with_athlete = collections.Counter({k: v for k, v in year_rows.items() if '"athlete_id"' in k})
    for label, other, base in (('大会別', meet_rows, year_rows), ('選手別', shard_rows, with_athlete)):
        if other == base:
            res.ok()
        else:
            res.fail('年別と%sで中身が違う：年別だけ %d 行／%sだけ %d 行'
                     % (label, sum((base - other).values()), label, sum((other - base).values())))
    # 選手の束の計算（JS と同じ FNV-1a）で正しい束に入っているか
    shards = manifest['athleteShards']
    for p in glob.glob(os.path.join(DATA, 'by_athlete', '*.json')):
        n = int(os.path.basename(p)[:-5])
        for r in jload(p):
            h = 0x811c9dc5
            for ch in r['athlete_id']:
                h ^= ord(ch)
                h = (h * 0x01000193) & 0xffffffff
            if h % shards != n:
                res.fail('%s が束 %d に入っている（正しくは %d）' % (r['athlete_id'], n, h % shards))
                break
        else:
            res.ok()
    # 大会の演技数
    per_meet = collections.Counter(r['meet_id'] for r in rows)
    for c in comps:
        if c.get('n_individual', 0) != per_meet.get(c['meet_id'], 0):
            res.fail('%s の演技数 competitions %s／実際 %s' % (c['meet_id'], c.get('n_individual'), per_meet.get(c['meet_id'], 0)))
        else:
            res.ok()
    # 合計の式（規則ごと）
    for r in rows:
        if r.get('total') is None or r.get('E') is None or r.get('D') is None or r.get('T') is None:
            continue
        extra = (r.get('Bonus') or 0) - (r.get('Pen') or 0) - (r.get('DPen') or 0)
        if r.get('pre2017'):
            calc = r['D'] + r['T'] + 3 * r['E'] + extra
        elif r.get('HD') is None:
            continue
        else:
            calc = r['D'] + r['E'] + r['T'] + r['HD'] + extra
        if abs(calc - r['total']) > 0.005:
            if {'合計要確認', '採点未確定'} & set(r.get('check_flags') or []):
                res.ok()                               # 検証レポートで既に要確認として出しているもの
            else:
                res.fail('%s 合計%.3f 式%.3f（要確認の印が無い）' % (r['performance_id'], r['total'], calc))
        else:
            res.ok()
    # 自己ベスト（今の規則の演技の最大）
    best = collections.defaultdict(lambda: None)
    for r in rows:
        if r.get('athlete_id') and not r.get('pre2017') and r.get('total') is not None:
            b = best[r['athlete_id']]
            best[r['athlete_id']] = r['total'] if b is None else max(b, r['total'])
    for a in jload(os.path.join(DATA, 'athletes.json')):
        s = a.get('summary') or {}
        if not a.get('has_individual'):
            continue
        if close(s.get('best_total'), best.get(a['athlete_id'])):
            res.ok()
        else:
            res.fail('%s %s 自己ベスト 公開%s／演技から%s' % (a['athlete_id'], a['name'], s.get('best_total'), best.get(a['athlete_id'])))
    return res


# ---- 5. 本番サイト ---------------------------------------------------------------

def _get(url):
    req = urllib.request.Request(url, headers=dict(UA, **{'Accept-Encoding': 'gzip'}))
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            body = gzip.decompress(body)
    return body


def check_live():
    res = Result('本番サイト：公開ファイルが手元と同じか')
    manifest = jload(os.path.join(DATA, 'manifest.json'))
    v = '?v=' + manifest['dataVersion']
    live_manifest = json.loads(_get(LIVE + 'manifest.json?x=%d' % random.randint(0, 10 ** 9)))
    if live_manifest.get('contentHash') != manifest.get('contentHash'):
        res.fail('本番の manifest の contentHash が手元と違う（本番 %s／手元 %s）'
                 % (live_manifest.get('contentHash', '')[:12], manifest.get('contentHash', '')[:12]))
        return res
    res.ok()
    for path in sorted(glob.glob(os.path.join(DATA, '**', '*.json'), recursive=True)):
        rel = os.path.relpath(path, DATA).replace(os.sep, '/')
        if rel == 'manifest.json':
            continue
        local = open(path, 'rb').read()
        try:
            live = _get(LIVE + urllib.request.quote(rel) + v)
        except Exception as e:
            res.fail('%s を取得できない：%s' % (rel, e))
            continue
        if hashlib.sha256(local).digest() == hashlib.sha256(live).digest():
            res.ok()
        else:
            res.fail('%s が本番と違う' % rel)
    return res


# ---- 6. 保存した原本がいまの sporttech と同じか（抜き取り） ------------------------------------

def check_sporttech_live(sample=10, seed=20260925):
    res = Result('sporttech：保存した原本が、いまの sporttech と同じか（%d大会の抜き取り）' % sample)
    metas = [jload(m) | {'_dir': os.path.dirname(m)}
             for m in glob.glob(os.path.join(RAW, '*', 'sporttech_*', '*', '_meta.json'))]
    by_year = collections.defaultdict(list)
    for m in metas:
        by_year[m['date'][:4]].append(m)
    rnd = random.Random(seed)
    years = sorted(by_year)
    picks = [rnd.choice(by_year[y]) for y in rnd.sample(years, min(sample, len(years)))]
    q = '&'.join('%s=true' % k for k in (
        'fetch_event_competitions', 'fetch_competition_stages', 'fetch_stage_groups',
        'fetch_group_performances', 'fetch_performance_athletes', 'fetch_performance_frames'))
    for meta in picks:
        live = json.loads(_get('https://sporttech.io/events/%s/ovs/api/event?%s' % (meta['event_id'], q)))
        saved = _merge(meta['_dir'])
        fields = ('State', 'MarkTTT_G', 'DifficultyT_G', 'ETotalT_G', 'TimeTMS_G', 'Displacement_G', 'NElements')
        lf, sf = live.get('Frames') or {}, saved['Frames']
        diff = [fid for fid in set(lf) | set(sf)
                if tuple((lf.get(fid) or {}).get(k) for k in fields) != tuple((sf.get(fid) or {}).get(k) for k in fields)]
        if diff:
            res.fail('%s %s：%d フレームが違う（例 %s）' % (meta['date'], meta['name'][:24], len(diff), diff[:3]))
        else:
            res.ok()
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-live', action='store_true')
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    comps, rows = published()
    checks = [lambda: check_sporttech(comps, rows), lambda: check_nishi53(rows),
              lambda: check_nishi54(rows), lambda: check_osaka(comps, rows),
              lambda: check_internal(comps, rows)]
    if not args.no_live:
        checks += [check_live, check_sporttech_live]
    total_bad = 0
    for run in checks:
        r = run()
        total_bad += len(r.bad)
        print('%s  %s  照合 %d／不一致 %d' % ('OK ' if not r.bad else 'NG ', r.name, r.checked, len(r.bad)), flush=True)
        for b in r.bad[:8]:
            print('      ×', b)
        if len(r.bad) > 8:
            print('      … ほか %d 件' % (len(r.bad) - 8))
    print('結果：不一致 %d 件' % total_bad)
    return 0 if not total_bad else 1


if __name__ == '__main__':
    sys.exit(main())
