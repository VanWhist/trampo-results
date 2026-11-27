# -*- coding: utf-8 -*-
"""試作：文字読み取りの氏名・所属を、既存の選手名・所属と突き合わせる。"""
import collections
import glob
import json
import os
import re
import sys
import unicodedata

sys.stdout.reconfigure(encoding='utf-8')
S, REPO = sys.argv[1], sys.argv[2]


def ocr(fn):
    if not fn:
        return ''
    try:
        d = json.load(open(os.path.join(S, 'fields51j', fn.replace('.png', '.json')), encoding='utf-8-sig'))
    except Exception:
        return ''
    if isinstance(d, dict):
        d = [d]
    t = unicodedata.normalize('NFKC', ' '.join(l['text'] for l in d))
    return re.sub(r'\s+', '', t)


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


names = collections.Counter()
clubs_of = collections.defaultdict(collections.Counter)
clubs = collections.Counter()
for f in glob.glob(os.path.join(REPO, 'data', 'performances', '*.json')):
    if '-other' in f:
        continue
    for r in json.load(open(f, encoding='utf-8')):
        if r.get('athlete_id') and '/' not in (r['athlete_name'] or ''):
            names[r['athlete_name']] += 1
            clubs_of[r['athlete_name']][r.get('club') or ''] += 1
            clubs[r.get('club') or ''] += 1
flat = {}
for n in names:
    flat.setdefault(n.replace(' ', ''), []).append(n)
club_flat = {c.replace(' ', ''): c for c in clubs if c}

meta = json.load(open(os.path.join(S, 'fields51', '_fields.json'), encoding='utf-8'))
JP = r'[^\u3040-\u30ff\u3400-\u9fffA-Za-z々ー]'


def club_ok(name, oc):
    """候補の選手の既存の所属に、読んだ所属と近いものがあるか。"""
    oc = re.sub(r'[^\w]', '', oc)
    if not oc:
        return False
    for c in clubs_of[name]:
        cc = re.sub(r'[^\w]', '', c)
        if cc and lev(oc[:len(cc)], cc) <= max(1, len(cc) // 4):
            return True
    return False


res = []
stat = collections.Counter()
for r in meta:
    on = re.sub(JP, '', ocr(r['name']))
    oc = ocr(r['club'])
    ol = ocr(r.get('line'))
    ol = re.sub(r'^[\d.\s,]*', '', ol)
    ol = re.sub(r'^[QO0I1lー.\s]{0,3}\d{0,2}', '', ol)
    ol = re.sub(JP, '', ol)
    scored = []
    for k, full in flat.items():
        da = lev(on, k)
        db = min(lev(ol[:L], k) for L in (len(k) - 1, len(k), len(k) + 1)) if ol else 99
        d = min(da, db)
        if d <= 2:
            scored.append((d, da, db, k))
    scored.sort()
    best = scored[0] if scored else (99, 99, 99, None)
    second = scored[1][0] if len(scored) > 1 else 99
    full = flat[best[3]][0] if best[3] else None
    # 所属：所属欄の読み取りと、1行の読み取りの氏名より後ろの部分の両方で見る
    rest = ol[len(best[3]):] if best[3] and best[2] <= 1 else ''
    cok = (club_ok(full, oc) or club_ok(full, rest)) if full else False
    if best[0] == 0 and second >= 1:
        status = 'ok'          # 既存の選手名と1字も違わずに一致
    elif best[0] <= 1 and second > best[0] and cok:
        status = 'fix'
    else:
        status = 'check'
    stat[status] += 1
    res.append({'page': r['page'], 'band': r['band'], 'ocr_name': on, 'ocr_line': ol, 'ocr_club': oc,
                'name': full if status != 'check' else None, 'cand': scored[:3], 'club_ok': cok,
                'status': status, 'name_file': r['name'], 'club_file': r['club'], 'line_file': r.get('line')})
json.dump(res, open(os.path.join(S, 'q51_names.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print(dict(stat))
for x in res:
    if x['status'] == 'check':
        print(x['page'], x['band'], x['ocr_name'], '|', x['ocr_line'][:22], [c[3] for c in x['cand']], x['club_ok'])
