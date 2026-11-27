# -*- coding: utf-8 -*-
"""読んだ氏名・所属を、既存の選手名・所属（公開データ）と同じ大会の文字のPDFに突き合わせる。

氏名：文字読み取りの結果（空白・読み仮名を除く）が既存の選手名と1字も違わなければ採用（how=ocr+db）。
所属：既存の所属のうち、文字読み取りとの編集距離が最小のものを候補にする（距離0以外は目で確かめる）。
既存の選手名は、この取り込みより前の data/athletes.json（2026-11-27 時点）を使った。取り込んだ後に実行し直すと、
目で決めた氏名も「既存の選手名と一致」として自動で通ってしまうので、やり直すときは取り込み前の版で実行する。
"""
import collections
import json
import os
import re
import sys
import unicodedata

from files import REPO
VARIANTS = {'﨑': '崎', '髙': '高', '瀨': '瀬', 'ヶ': 'ケ'}          # etl/normalize.py NAME_VARIANTS
PREF_RE = re.compile(r'\[[^\[\]]*[都道府県]\]$')


def ocr_lines(fn):
    p = os.path.join('ocr', os.path.splitext(fn)[0] + '.json')
    raw = open(p, encoding='utf-8-sig').read().strip()
    if not raw:
        return ''
    d = json.loads(raw)
    if isinstance(d, dict):
        d = [d]
    return ''.join(l['text'] for l in d)


def norm(s):
    s = unicodedata.normalize('NFKC', s or '').replace(' ', '')
    for a, b in VARIANTS.items():
        s = s.replace(a, b)
    return s


def norm_club(s):
    s = norm(s)
    s = PREF_RE.sub('', s)
    # 長音・ハイフンの読み違い（- と ー）、エ と 工、カ と 力 はそろえて比べる
    return s.replace('-', 'ー').replace('工', 'エ').replace('力', 'カ').replace('口', 'ロ')


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def split_name(lines):
    """氏名の行（読み仮名が折り返していれば2行）と所属の行に分ける。読み仮名も返す。"""
    name = lines[0]
    rest = lines[1:]
    if '(' in norm(name) and ')' not in norm(name) and rest:
        name += rest[0]
        rest = rest[1:]
    n = norm(name)
    m = re.search(r'\((.*?)\)?$', n)
    reading = m.group(1) if m else ''
    n = re.sub(r'\(.*$', '', n)
    return n, reading, ''.join(rest)


def main():
    res = json.load(open('parsed.json', encoding='utf-8'))
    ath = json.load(open(REPO + '/data/athletes.json', encoding='utf-8'))
    pool = collections.defaultdict(set)                 # 正規化した氏名 → 表示の氏名
    clubs_of = collections.defaultdict(set)
    all_clubs = set()
    for a in ath:
        k = norm(a['name'])
        pool[k].add(a['name'])
        for h in a['club_history']:
            for c in h['clubs']:
                clubs_of[k].add(c)
                all_clubs.add(c)
    ref = json.load(open('ejtext.json', encoding='utf-8'))
    for key, rows in ref.items():
        for r in rows:
            k = norm(r['name'])
            pool[k].add(r['name'])
            clubs_of[k].add(r['club'])
            all_clubs.add(r['club'])
    out = []
    for f in res:
        for b in f['bands']:
            lines = [ocr_lines(t['file']) for t in b['text']]
            name, reading, club_raw = split_name(lines)
            rec = {'meet': f['meet'], 'file': f['file'], 'band': b['band'], 'rank': b['rank'],
                   'ocr_name': name, 'reading': reading, 'ocr_club': club_raw, 'lines': lines,
                   'crops': [t['file'] for t in b['text']]}
            if name in pool:
                rec['name'] = sorted(pool[name])[0]
                rec['how'] = 'ocr+db'
            else:
                cands = sorted(pool, key=lambda k: lev(k, name))[:3]
                rec['name'] = ''
                rec['cands'] = [(sorted(pool[k])[0], lev(k, name)) for k in cands]
            nc = norm_club(club_raw)
            pref = sorted(clubs_of.get(norm(rec['name']), set()) or all_clubs,
                          key=lambda c: lev(norm_club(c), nc))
            best = pref[0] if pref else ''
            d = lev(norm_club(best), nc) if best else 99
            if d > 0:
                best2 = min(all_clubs, key=lambda c: lev(norm_club(c), nc))
                if lev(norm_club(best2), nc) < d:
                    best, d = best2, lev(norm_club(best2), nc)
            rec['club'] = best
            rec['club_dist'] = d
            out.append(rec)
    # 通し番号（decisions.tsv の番号はこれ）と、目で確かめる行：氏名が決まらない・所属が読み取りと完全には
    # 一致しない・決めた所属がその選手の既存の所属に無い
    need = []
    for i, r in enumerate(out):
        r['_i'] = i
        why = []
        if not r['name']:
            why.append('name')
        elif r['club'] not in clubs_of[norm(r['name'])]:
            why.append('club-not-known')
        if r['club_dist'] > 0:
            why.append('clubdist%d' % r['club_dist'])
        r['_why'] = why
        if why:
            need.append(r)
    json.dump(out, open('matched.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    json.dump(need, open('need.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print('目で確かめる', len(need))
    n_auto = sum(1 for r in out if r['name'])
    n_club0 = sum(1 for r in out if r['club_dist'] == 0)
    print('選手', len(out), '氏名 自動', n_auto, '所属 距離0', n_club0)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
