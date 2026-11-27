# -*- coding: utf-8 -*-
"""試作：組み立てた第51回予選を確定し、検算・決勝名簿との照合・順位の並びを確かめ、CSV に書き出す。"""
import collections
import csv
import json
import os
import re
import sys
import unicodedata

sys.stdout.reconfigure(encoding='utf-8')
S, REPO, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
a = json.load(open(os.path.join(S, 'q51_assembled.json'), encoding='utf-8'))
cvis = {}
for line in open(os.path.join(S, 'q51_clubvisual_pb.tsv'), encoding='utf-8'):
    p, b, c = line.rstrip('\n').split('\t')
    cvis[(int(p), int(b))] = c

TRUNC = {'神辺スポーツセンタ*': '神辺スポーツセンター'}
# 既存の所属から自動で選んだときに、空白の有無だけ印字と違う表記を選んでしまうもの。
# このPDFの印字は空白なし（49ページ 長澤 萌栞、2・5・13・33ページで画像を見て確認）
SPACING = {'forte TC': 'forteTC'}
f = lambda v: float(v) if v not in (None, '') else None
problems = []
rows_out = []
for r in a:
    key = (r['page'], r['band'])
    club = cvis.get(key, r.get('club'))
    note = []
    if club in TRUNC:
        club = TRUNC[club]
        note.append('所属は欄で切れて印字（神辺スポーツセンタ）。既存の表記にそろえた')
    club = unicodedata.normalize('NFKC', SPACING.get(club, club))
    name = unicodedata.normalize('NFKC', r['name'])
    rank = r['rank_raw'].rstrip('.')
    if not re.fullmatch(r'\d+', rank):
        problems.append(('順位', key, r['rank_raw']))
        continue
    if r['dns']:
        rows_out.append({'category': r['category'], 'rank': int(rank), 'name': name, 'club': club, 'dns': 1,
                         'page': r['page'], 'how': r['how'], 'note': ''})
        continue
    score = f(r['rows'][0].get('Score'))
    tots = []
    for k, v in enumerate(r['rows'], 1):
        tot = v.get('Total')
        if tot and not re.fullmatch(r'\d+\.\d+', tot):
            tot = None                          # PDF が「…」と印字（欄に入りきらない）
        e, d, h, t = f(v.get('E')), f(v.get('D')) or 0.0, f(v.get('H')), f(v.get('Time'))
        S_ = [int(v['S%d' % i]) for i in range(1, 11) if 'S%d' % i in v]
        L = int(v['L']) if 'L' in v else None
        calc = None if None in (e, h, t) else round(e + d + h + t, 3)
        if tot is None:
            if calc is None:
                tots.append(None)
                rows_out.append(None)
                continue
            other = [f(x.get('Total')) for j, x in enumerate(r['rows'], 1) if j != k]
            if score is not None and other and other[0] is not None and abs(score - other[0] - calc) > 0.0015:
                problems.append(('…の合計', key, k))
            note_k = note + ['合計は PDF で「…」。E+D+H+T と予選の値−もう1本の合計で確かめた値']
            tot_v = calc
        else:
            tot_v = f(tot)
            note_k = list(note)
        if e is None and tot_v == 0:
            tots.append(0.0)
            continue                            # 演技していない枠（合計 0）
        n = len(S_)
        if calc is None or abs(calc - tot_v) > 0.0015:
            problems.append(('合計', key, k))
        if abs(2 * n - (sum(S_) + (L or 0)) / 10 - e) > 0.0015:
            problems.append(('E', key, k))
        tots.append(tot_v)
        rows_out.append({'category': r['category'], 'rank': int(rank), 'name': name, 'club': club, 'dns': 0,
                         'routine': k, **{'S%d' % i: (S_[i - 1] if i <= n else '') for i in range(1, 11)},
                         'L': '' if L is None else L, 'E': e, 'D': '' if v.get('D') is None else d, 'H': h,
                         'Time': t, 'Total': tot_v, 'Score': score, 'page': r['page'], 'how': r['how'],
                         'note': '／'.join(note_k)})
    if score is not None and None not in tots and abs(sum(tots) - score) > 0.0015:
        problems.append(('予選の値', key, tots, score))
rows_out = [x for x in rows_out if x]
print('問題', len(problems), problems[:10])

# 順位の並び（区分ごと、1から。同順位は次の順位を飛ばす）
by = collections.defaultdict(list)
for x in rows_out:
    if x.get('routine', 1) == 1 or x['dns']:
        by[x['category']].append(x['rank'])
for c, rs in by.items():
    rs = sorted(rs)
    ok = rs[0] == 1 and all(b == a or b == i + 1 for i, (a, b) in enumerate(zip(rs, rs[1:]), 1))
    if not ok:
        print('順位の並び', c, rs[:15], '...')

# 決勝名簿との照合（予選 1〜10位 と 決勝の選手）
fin = collections.defaultdict(set)
for r in json.load(open(os.path.join(REPO, 'data', 'performances', '2023.json'), encoding='utf-8')):
    if r['meet_id'] == 'nw-2023-09-29':
        fin[r['category']].add(r['athlete_name'].replace(' ', ''))
norm = lambda s: s.replace(' ', '').replace('髙', '高').replace('﨑', '崎')
for c in sorted(by):
    top = {norm(x['name']) for x in rows_out if x['category'] == c and x['rank'] <= 10 and not x['dns']}
    fn = {norm(n) for n in fin.get(c, set())}
    if top != fn:
        print('決勝名簿', c, '予選だけ', sorted(top - fn), '決勝だけ', sorted(fn - top))
cols = ['category', 'rank', 'name', 'club', 'dns', 'routine'] + ['S%d' % i for i in range(1, 11)] + \
       ['L', 'E', 'D', 'H', 'Time', 'Total', 'Score', 'page', 'how', 'note']
with open(OUT, 'w', encoding='utf-8', newline='') as fh:
    w = csv.DictWriter(fh, cols)
    w.writeheader()
    for x in rows_out:
        w.writerow(x)
print('書き出し', len(rows_out), '行', collections.Counter(x['dns'] for x in rows_out))
