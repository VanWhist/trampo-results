# -*- coding: utf-8 -*-
"""生JSONから作った演技レコードを、検証済みCSV（v2）と1件ずつ突き合わせる回帰テスト。

CSV は運用チャットが実データで検証したもの。ここが食い違ったら、まず自分の式と列を疑う。
"""
import collections
import csv
import io
import sys

from . import config
from .sources import sporttech

sys.stdout.reconfigure(encoding='utf-8')


def _f(text):
    text = (text or '').strip()
    if text == '':
        return None
    try:
        return float(text)
    except ValueError:
        return None


def main():
    comps, perfs, judges, panels = sporttech.load_all()
    print('生JSONから抽出した演技:', len(perfs))
    by_disc = collections.Counter(p['discipline'] for p in perfs)
    print('種目別:', dict(by_disc))

    rows = list(csv.DictReader(
        io.open(config.CSV_SPORTTECH, encoding='utf-8-sig', newline='')))
    print('CSVレコード:', len(rows))
    print('CSV種目別:', dict(collections.Counter(r['種目'] for r in rows)))

    # 2026-05-23 には4大会あるので、日付だけでは一意にならない
    idx = {(p['date'], p['meet_name'], p['frame_id']): p for p in perfs}
    csv_keys = set()
    diffs = collections.Counter()
    samples = collections.defaultdict(list)
    unmatched_csv = []

    for r in rows:
        key = (r['大会日'], r['大会名'], int(r['FrameID']))
        csv_keys.add(key)
        p = idx.get(key)
        if p is None:
            unmatched_csv.append(key)
            continue

        def cmp(field, csv_col, tol=0.0005):
            a, b = p[field], _f(r[csv_col])
            if a is None and b is None:
                return
            if a is None or b is None or abs(a - b) > tol:
                diffs[field] += 1
                if len(samples[field]) < 3:
                    samples[field].append((key, p['athlete_name'], a, b))

        if p['discipline'] == '個人':
            for field, col in (('total', '合計'), ('D', 'D'), ('E', 'E'),
                               ('T', 'T'), ('HD', 'HD')):
                cmp(field, col)
        csv_disc = {'D2': 'DMT', 'D3': 'TUM'}.get(r['種目'], r['種目'])
        if csv_disc != p['discipline']:
            diffs['discipline'] += 1
            if len(samples['discipline']) < 5:
                samples['discipline'].append((key, p['athlete_name'], p['discipline'], csv_disc))
        # 意図的な差異:
        #  ・CSV は Stage.Kind=6 を "Kind6" のまま出力している。こちらは「準決勝」と判定する
        #    （予選→24名→決勝8名の構造で確認済み）
        #  ・CSV は NElements キーの無い失格フレームの技数を 0 と書いている。
        #    指示書どおり「技数は空欄」にするので None のままにする
        csv_round = r['ラウンド'] or ''
        our_round = p['round'] or ('Kind%s' % p['round_raw'])
        if csv_round == 'Kind6' and p['round'] == '準決勝':
            our_round = 'Kind6'
        if csv_round != our_round:
            diffs['round'] += 1
            if len(samples['round']) < 5:
                samples['round'].append((key, p['round'], p['round_raw'], r['ラウンド']))
        if (r['選手'] or '').strip() != p['athlete_name']:
            diffs['name'] += 1
            if len(samples['name']) < 5:
                samples['name'].append((key, p['athlete_name'], r['選手']))
        n_csv = _f(r['技数'])
        if (n_csv is None) != (p['n_elements'] is None) or (
                n_csv is not None and p['n_elements'] is not None and int(n_csv) != p['n_elements']):
            diffs['n_elements'] += 1
            if len(samples['n_elements']) < 5:
                samples['n_elements'].append((key, p['n_elements'], n_csv))

        # 位置別減点：CSVは技数を超えた位置を「未算入減点」に隔離している
        for i in range(10):
            want = _f(r['位置%d_中央2和' % (i + 1)])
            got = p['deduct_positions'][i]
            if got is None and (want in (None, 0.0)):
                continue
            if got is None or want is None or abs(got - want) > 0.0005:
                diffs['deduct_pos'] += 1
                if len(samples['deduct_pos']) < 3:
                    samples['deduct_pos'].append((key, p['athlete_name'], i + 1, got, want))
                break
        want_l = _f(r['着地_中央2和'])
        if want_l is not None and abs((p['deduct_landing'] or 0) - want_l) > 0.0005:
            diffs['landing'] += 1
        want_u = _f(r['未算入減点_中央2和'])
        if want_u is not None and abs((p['deduct_unaccounted'] or 0) - want_u) > 0.0005:
            diffs['unaccounted'] += 1
            if len(samples['unaccounted']) < 5:
                samples['unaccounted'].append((key, p['athlete_name'], p['deduct_unaccounted'], want_u))

        # 審判別E
        for slot, label in config.E_SLOTS.items():
            want_e = _f(r['審判別%s' % label])
            got_e = p['judge_E'].get(label)
            want_e = None if want_e in (None, 0.0, 100.0) else want_e / 10.0
            if (got_e is None) != (want_e is None) or (
                    got_e is not None and want_e is not None and abs(got_e - want_e) > 0.005):
                diffs['judge_%s' % label] += 1
                if len(samples['judge']) < 5:
                    samples['judge'].append((key, label, got_e, want_e))

    extra = [k for k in idx if k not in csv_keys]
    print('\n--- 突合結果 ---')
    print('CSVにあってJSON側に無い:', len(unmatched_csv), unmatched_csv[:5])
    print('JSON側にあってCSVに無い:', len(extra), extra[:5])
    if not diffs:
        print('全項目一致')
    for field, n in diffs.most_common():
        print('  差異 %-14s %d 件  例: %s' % (field, n, samples.get(field.split('_')[0], samples.get(field, []))[:2]))
    print('\n審判:', len(judges), 'パネル:', len(panels))


if __name__ == '__main__':
    main()
