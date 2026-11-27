# -*- coding: utf-8 -*-
"""試作：第51回 予選の全選手を組み立てる（区分・順位・氏名・所属・2本の値・予選の値）。"""
import collections
import glob
import json
import logging
import os
import pickle
import re
import sys
import unicodedata

logging.disable(logging.CRITICAL)
import pdfplumber

import glyph51 as G
from parse51q import classify

sys.stdout.reconfigure(encoding='utf-8')
S, REPO, PDF = sys.argv[1], sys.argv[2], sys.argv[3]

CATS = [(range(1, 4), '小学生低学年 女子'), (range(4, 7), '小学生低学年 男子'), (range(7, 17), '小学生高学年 女子'),
        (range(17, 23), '小学生高学年 男子'), (range(23, 32), '中学生 女子'), (range(32, 37), '中学生 男子'),
        (range(37, 42), '高校生 女子'), (range(42, 44), '高校生 男子'), (range(44, 46), '大学生 女子'),
        (range(46, 49), '大学生 男子'), (range(49, 50), '一般 女子'), (range(50, 51), '一般 男子')]
cat_of = {p: c for r, c in CATS for p in r}

reps = pickle.load(open(os.path.join(S, 'digits51.pkl'), 'rb'))['reps']
raw = {(b['page'], b['band']): b for b in json.load(open(os.path.join(S, 'q51_raw.json'), encoding='utf-8'))}
names = {(r['page'], r['band']): r for r in json.load(open(os.path.join(S, 'q51_names.json'), encoding='utf-8'))}
visual = {}
for line in open(os.path.join(S, 'visual_names.tsv'), encoding='utf-8'):
    p, b, n, c = line.rstrip('\n').split('\t')
    visual[(int(p), int(b))] = (n.rstrip('?'), c)

# 既存の選手の所属
clubs_of = collections.defaultdict(collections.Counter)
for f in glob.glob(os.path.join(REPO, 'data', 'performances', '*.json')):
    if '-other' in f:
        continue
    for r in json.load(open(f, encoding='utf-8')):
        if r.get('athlete_id'):
            clubs_of[r['athlete_name']][r.get('club') or ''] += 1


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def pick_club(name, ocr_texts):
    """既存の所属のうち、読んだ所属（所属欄・1行の残り）にいちばん近いもの。"""
    best = (99, None)
    for c in clubs_of[name]:
        cc = re.sub(r'\W', '', c)
        for t in ocr_texts:
            t = re.sub(r'\W', '', t)
            if not t:
                continue
            d = lev(t[:len(cc) + 2], cc)
            best = min(best, (d / max(len(cc), 1), c))
    return best


ranks = {}
with pdfplumber.open(PDF) as pdf:
    for pno, page in enumerate(pdf.pages, 1):
        lay = G.page_layout(page)
        if lay is None:
            continue
        for bi, b in enumerate(lay['bands']):
            # 順位の欄（Q の列より左、x<58pt）の語をすべてつなぐ（「11.」が「1」「1.」に分かれることがある）
            ws = [w for w in b['a'] if w['x1'] < 58]
            s = ''.join(classify(g, reps)[0] or '?' for w in ws for g in w['gs'])
            ranks[(pno, bi)] = s

out, flags = [], collections.Counter()
for key in sorted(raw):
    b = raw[key]
    rows = b['rows']
    rec = {'page': key[0], 'band': key[1], 'category': cat_of[key[0]], 'rank_raw': ranks.get(key)}
    if key in visual:
        rec['name'], rec['club'] = visual[key]
        rec['how'] = 'visual'
    else:
        n = names[key]
        rec['name'] = n['name']
        club = pick_club(n['name'], [n['ocr_club'], n['ocr_line'][len(n['cand'][0][3]):] if n['cand'] else ''])
        rec['club'] = club[1] if club[0] <= 0.25 else None
        rec['club_d'] = round(club[0], 2)
        rec['how'] = 'ocr+db'
        if rec['club'] is None:
            flags['所属が決まらない'] += 1
    rec['dns'] = any('DNS' in ''.join(r.values()) for r in rows)
    rec['rows'] = rows
    out.append(rec)
json.dump(out, open(os.path.join(S, 'q51_assembled.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print(len(out), dict(flags), collections.Counter(r['how'] for r in out))
for r in out:
    if r.get('club') is None:
        print(r['page'], r['band'], r['name'], names[(r['page'], r['band'])]['ocr_club'], clubs_of[r['name']].most_common(3))
