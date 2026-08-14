# -*- coding: utf-8 -*-
"""受け入れ基準（実装指示書 第9章）を出力済みJSONに対して機械的に確認する。

    python -m etl.acceptance

画面を見なくても検証できる項目（1〜7）をここで確認する。
8（iPhone Safari）は実機確認が必要。
"""
import io
import json
import os
import sys

from . import config

sys.stdout.reconfigure(encoding='utf-8')

OK, NG = 'OK  ', 'NG  '
results = []


def check(no, title, ok, detail=''):
    results.append((no, ok, title, detail))
    print('%s%s. %s' % (OK if ok else NG, no, title))
    if detail:
        for line in detail.splitlines():
            print('       %s' % line)


def _load(*parts):
    path = os.path.join(config.DATA_OUT, *parts)
    with io.open(path, encoding='utf-8') as fh:
        return json.load(fh)


def main():
    manifest = _load('manifest.json')
    athletes = _load('athletes.json')
    competitions = _load('competitions.json')
    perfs = []
    for year in manifest['years']:
        perfs.extend(_load('performances', '%s.json' % year))
    meets = {c['meet_id']: c for c in competitions}
    for p in perfs:
        c = meets[p['meet_id']]
        p['date'], p['meet_name'], p['source'] = c['date'], c['name'], c['source']

    # 1. ソース別の件数
    counts = {}
    for p in perfs:
        counts[p['source']] = counts.get(p['source'], 0) + 1
    expected = {'sporttech': 5969, 'osaka_pweb': 1293, 'nishinihon': 913}
    ok = all(counts.get(k) == v for k, v in expected.items())
    check('1', '個人演技数がソース別の期待値と一致',
          ok, '実測 %s\n期待 %s（大阪府は決勝266を追加し重複掲載36を除いた数）' % (counts, expected))

    # 2. 城 瑛斗が3ソースまたいで1人にまとまり、所属が履歴表示される
    shiro = [a for a in athletes if a['name'] == '城 瑛斗']
    detail = ''
    ok = len(shiro) == 1
    if ok:
        a = shiro[0]
        mine = [p for p in perfs if p.get('athlete_id') == a['athlete_id']]
        srcs = sorted(set(p['source'] for p in mine))
        clubs = ' → '.join('%s %s' % (h['season'], '/'.join(h['clubs']))
                           for h in a['club_history'])
        ok = srcs == ['nishinihon', 'osaka_pweb', 'sporttech']
        detail = '演技 %d件 / 出典 %s\n所属履歴: %s' % (len(mine), srcs, clubs)
    check('2', '「城 瑛斗」が3ソース1人分にまとまり所属が履歴表示', ok, detail)

    # 3. 森田 瑛斗・大崎 瑛斗が別人
    ids = {}
    for name in ('城 瑛斗', '森田 瑛斗', '大崎 瑛斗'):
        found = [a for a in athletes if a['name'] == name]
        ids[name] = found[0]['athlete_id'] if found else None
    ok = len(set(ids.values())) == 3 and None not in ids.values()
    check('3', '「森田 瑛斗」「大崎 瑛斗」が別人として分かれている',
          ok, '\n'.join('%s → %s' % (k, v) for k, v in ids.items()))

    # 4. 2026-07-24 全日本ジュニア 個人決勝 城 瑛斗
    target = [p for p in perfs
              if p.get('athlete_name') == '城 瑛斗' and p['date'] == '2026-07-24'
              and p.get('round') == '決勝']
    ok = len(target) == 1
    detail = ''
    if ok:
        p = target[0]
        det = _load('details', '%s.json' % p['meet_id'])[p['performance_id']]
        want_pos = [4, 3, 3, 6, 4, 4, 4, 1, 3, 4]
        ok = (abs(p['total'] - 49.83) < 0.005 and abs(p['E'] - 16.4) < 0.005
              and abs(p['D'] - 8.6) < 0.005 and abs(p['HD'] - 9.30) < 0.005
              and abs(p['T'] - 15.53) < 0.005
              and det['positions'] == want_pos and det['landing'] == 0)
        detail = ('合計%.2f / E%.1f / D%.1f / HD%.2f / T%.2f\nS1〜S10 = %s / L = %s'
                  % (p['total'], p['E'], p['D'], p['HD'], p['T'],
                     det['positions'], det['landing']))
    check('4', '2026-07-24 全日本ジュニア決勝 城 瑛斗の演技詳細が一致', ok, detail)

    # 5. 中断演技は技数を超えた位置が空欄（0ではない）
    bad = []
    checked = 0
    for meet_id in manifest['meetsWithDetails']:
        for pid, det in _load('details', '%s.json' % meet_id).items():
            n = det['n_elements']
            if n is None or n >= 10:
                continue
            checked += 1
            for i, v in enumerate(det['positions']):
                if i >= n and v is not None:
                    bad.append((pid, i + 1, v))
    check('5', '中断演技は技数を超えた位置が空欄（0と表示しない）',
          not bad, '中断演技 %d件を確認 / 違反 %d件' % (checked, len(bad)))

    # 6. n<100 の審判は「データ不足」で傾向値が出ない
    diff = _load('summary', 'judge_panel_diff.json')
    bad = [e for pop in diff.values() for e in pop
           if e['n'] < config.JUDGE_MIN_N and (e['has_trend'] or e['mean_diff'] is not None)]
    pop = diff['qualified']
    enough = [e for e in pop if e['has_trend']]
    check('6', 'n<100 の審判は「データ不足」で傾向値が出ない',
          not bad,
          '既定母集団(予選通過者×完遂) 審判 %d名 / うち n>=100 は %d名\n'
          '辛め %d名・甘め %d名・中立 %d名'
          % (len(pop), len(enough),
             sum(1 for e in enough if e['trend'] == '辛め'),
             sum(1 for e in enough if e['trend'] == '甘め'),
             sum(1 for e in enough if e['trend'] == '中立')))

    # 7. 検証レポートが errors: 0
    v = manifest['validation']
    check('7', 'ETLの検証レポートが errors: 0', v['errors'] == 0, v['summary'])

    print('\n8. iPhoneのSafariで全画面が開ける … 実機で確認が必要（自動判定できない）')
    failed = [r for r in results if not r[1]]
    print('\n%d / %d 項目が自動確認できる範囲でOK' % (len(results) - len(failed), len(results)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
