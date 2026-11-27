# -*- coding: utf-8 -*-
"""数値（parsed.json）と氏名・所属（matched.json ＋ 目で決めた decisions.tsv）を合わせて、
演技ごとの CSV（etl/higashinihon_img_transcription.csv）を書き出す。"""
import csv
import json
import sys

import check
import meta

COLS = ['meet_id', 'file', 'page', 'category', 'sex', 'round', 'rank', 'name', 'club', 'status', 'routine'] + \
       ['S%d' % i for i in range(1, 11)] + ['L', 'A', 'Exe', 'Diff', 'ToF', 'HD', 'Pen', 'Score',
                                            'agg', 'agg_kind', 'how_name', 'how_club']


# 既存の所属から選んだ表記を、この大会の印字に合わせる（所属ごとに1つの画像で確かめた。clubs_*.png）
CLUB_PRINTED = {
    ('*', 'Atsugibonfire'): 'Atsugi bonfire',
    ('*', '慶応義塾大学'): '慶應義塾大学',
    ('ej-2023-09-08', '大館市トランポリンクラブ'): '大館トランポリンクラブ',
    ('ej-2024-09-20', 'Les Fiertes'): 'LesFiertes',
    ('ej-2023-11-26', 'トランポリン チームラビット'): 'トランポリンチームラビット',
}


def decisions(path='decisions.tsv'):
    d = {}
    for line in open(path, encoding='utf-8'):
        if line.startswith('#') or not line.strip():
            continue
        p = line.rstrip('\n').split('\t')
        d[int(p[0])] = (p[1] if len(p) > 1 else '', p[2] if len(p) > 2 else '')
    return d


def main(out_path):
    res = json.load(open('parsed.json', encoding='utf-8'))
    errs, n = check.check(res)                 # 検算（_status と agg_kind も付く）
    if errs:
        raise SystemExit('検算の不一致 %d 件' % len(errs))
    matched = json.load(open('matched.json', encoding='utf-8'))
    dec = decisions()
    by = {(m['file'], m['band']): m for m in matched}
    rows = []
    for f in res:
        kind = meta.AGG[f['file']]
        if f.get('agg_kind') and f['agg_kind'] != kind:
            raise SystemExit('列見出し %s と計算 %s が合わない: %s' % (kind, f['agg_kind'], f['file']))
        for b in f['bands']:
            m = by[(f['file'], b['band'])]
            name, club = dec.get(m['_i'], ('', ''))
            how_n = 'visual' if name else 'ocr+db'
            how_c = 'visual' if club else ('ocr+db' if m['club_dist'] == 0 else 'visual')
            name = name or m['name']
            club = club or m['club']
            printed = CLUB_PRINTED.get((f['meet'], club), CLUB_PRINTED.get(('*', club), club))
            if printed != club:
                club, how_c = printed, 'visual'      # 所属ごとの画像で印字と比べて直した
            if not name or not club:
                raise SystemExit('氏名か所属が空: %r' % m)
            base = {'meet_id': f['meet'], 'file': f['file'], 'page': b['page'], 'category': f['category'],
                    'sex': f['sex'], 'round': f['round'], 'rank': b['rank'], 'name': name, 'club': club,
                    'how_name': how_n, 'how_club': how_c, 'agg_kind': kind or ''}
            agg = next((v['Agg'] for _, v in check.routines_of(b) if 'Agg' in v), '')
            status = b.get('_status', '')
            if status:
                rows.append(dict(base, status=status, agg=agg))
                continue
            for no, v in check.routines_of(b):
                if set(v) <= {'Agg'}:
                    continue                       # 演技していない本目
                r = dict(base, status='', routine=no, agg=agg)
                for k in COLS:
                    if k in v:
                        r[k] = v[k]
                rows.append(r)
    with open(out_path, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in COLS})
    print('行', len(rows), '演技', sum(1 for r in rows if not r['status']), '棄権など', sum(1 for r in rows if r['status']))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main(sys.argv[1] if len(sys.argv) > 1 else 'transcription.csv')
