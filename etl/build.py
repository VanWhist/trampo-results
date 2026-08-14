# -*- coding: utf-8 -*-
"""ETL本体。生データを読み、正規化・事前集計して data/ にJSONを書き出す。

    python -m etl.build

生データ（大会リザルト\\ 配下）は読むだけで、絶対に書き換えない。
"""
import collections
import io
import json
import os
import sys
import time

from . import aggregate, config, name_variants, normalize, validate
from .sources import nishinihon, osaka, sporttech

sys.stdout.reconfigure(encoding='utf-8')

# 演技一覧に載せる列。
# 技別減点と審判別Eは演技詳細でしか使わないので、大会単位の details/ に分けて遅延ロードする。
# （年ファイルに入れると2025年だけで5MBを超え、iPhoneでの初回表示が重くなる）
# meet_name / date / source / official / level は competitions.json から meet_id で引けるので入れない。
PERF_FIELDS = (
    'performance_id', 'meet_id', 'discipline', 'category', 'sex', 'round', 'routine',
    'athlete_id', 'athlete_name', 'club',
    'rank', 'total', 'D', 'E', 'T', 'HD', 'Bonus', 'Pen', 'DPen', 'n_elements',
    'has_deduction_detail', 'has_judge_detail', 'interrupted',
    'check_flags', 'data_quality',
)


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(',', ':'))
    return os.path.getsize(path)


def main(argv=None):
    started = time.time()
    argv = sys.argv[1:] if argv is None else argv
    accept = '--accept-counts' in argv
    data_version = time.strftime('%Y-%m-%d') + '-01'

    print('生データを読みます…')
    st_comps, st_perfs, judges, panels = sporttech.load_all()
    os_comps, os_perfs = osaka.load_all()
    nw_comps, nw_perfs = nishinihon.load_all()

    competitions = st_comps + os_comps + nw_comps
    performances = st_perfs + os_perfs + nw_perfs
    print('  大会 %d / 演技 %d（全種目）' % (len(competitions), len(performances)))

    # 大会の level を演技側にも持たせる（ジャッジ分析のフィルタで使う）
    level_by_meet = {c['meet_id']: c['level'] for c in competitions}
    for p in performances:
        p['level'] = level_by_meet.get(p['meet_id'], '')
        p.setdefault('data_quality', 'ok')
        p['interrupted'] = (p['n_elements'] is not None and p['n_elements'] < 10)
        p['has_deduction_detail'] = any(v is not None for v in p['deduct_positions'])
        p.setdefault('check_flags', [])

    print('名寄せ（氏名のみを鍵にする）…')
    overrides = normalize.load_overrides()
    athletes = normalize.build_athletes(performances, overrides)
    print('  選手 %d名' % len(athletes))

    if accept:
        n = validate.accept_counts(performances)
        print('大会別件数の基準を更新しました（%d大会）' % n)

    # 日本語表記／ローマ字表記に分かれた同一人物の候補を洗い出す（自動では結合しない）
    merged_names = set()
    for entry in overrides['merge']:
        for n in entry.get('names', []):
            merged_names.add(normalize.normalize_name(n))
    variants, already_merged = name_variants.find_candidates(performances, merged_names)
    name_variants.write_report(variants, already_merged, config.VARIANTS_MD)

    print('検証…')
    rep = validate.run(performances, athletes, competitions, judges, panels,
                       name_variants_=(variants, already_merged))
    print('  ' + rep.summary())

    print('事前集計…')
    judge_diff = aggregate.judge_panel_diff(performances, panels, judges)
    ath_summary = aggregate.athlete_summary(performances)
    ded_summary = aggregate.deduction_summary(performances)

    # ---- 書き出し ----------------------------------------------------------
    print('書き出し…')
    sizes = {}

    for c in competitions:
        c['n_performances'] = sum(1 for p in performances if p['meet_id'] == c['meet_id'])
        c['n_individual'] = sum(1 for p in performances if p['meet_id'] == c['meet_id']
                                and p['discipline'] == config.PHASE1_DISCIPLINE)
        c['has_judge_names'] = any(p['meet_id'] == c['meet_id'] and p.get('panel_key')
                                   for p in performances)
    competitions.sort(key=lambda c: (c['date'], c['name']))
    sizes['competitions.json'] = _write(
        os.path.join(config.DATA_OUT, 'competitions.json'), competitions)

    for a in athletes:
        a['summary'] = ath_summary.get(a['athlete_id'], {})
    sizes['athletes.json'] = _write(
        os.path.join(config.DATA_OUT, 'athletes.json'), athletes)

    # 個人とそれ以外を別ファイルにする。Phase 1 の画面は個人しか出さないので、
    # シンクロ・DMT・タンブリングを読み込まずに済む（データは捨てない）。
    by_year = collections.defaultdict(list)
    for p in performances:
        p['has_judge_detail'] = bool(p.get('judge_E') or p.get('judge_HD'))
        suffix = '' if p['discipline'] == config.PHASE1_DISCIPLINE else '-other'
        row = {k: p.get(k) for k in PERF_FIELDS}
        # 値が無いキーは落としてJSONを小さくする。
        # ここで `v not in (None, '', [], False)` と書くと 0.0 == False のため
        # 0点（規定演技のDなど）まで消える。None と空だけを厳密に判定すること。
        row = {k: v for k, v in row.items()
               if v is not None and v != '' and v != [] and v is not False}
        by_year[(p['date'][:4], suffix)].append(row)
    for (year, suffix), items in sorted(by_year.items()):
        items.sort(key=lambda x: (x['meet_id'], x.get('category', ''),
                                  x.get('round') or '', x.get('athlete_name', ''),
                                  x.get('routine') or 0))
        name = 'performances/%s%s.json' % (year, suffix)
        sizes[name] = _write(os.path.join(config.DATA_OUT, *name.split('/')), items)

    # 大会単位の詳細（技別減点＋審判別E）。演技詳細を開いたときだけ読む。
    by_meet = collections.defaultdict(dict)
    for p in performances:
        if not (p['has_deduction_detail'] or p['has_judge_detail']):
            continue
        by_meet[p['meet_id']][p['performance_id']] = {
            'positions': p['deduct_positions'],
            'landing': p['deduct_landing'],
            'unaccounted': p['deduct_unaccounted'],
            'unit': p['deduct_unit'],
            'n_elements': p['n_elements'],
            'judge_E': p.get('judge_E') or {},
            'judge_E_unit': p.get('judge_E_unit', 'execution_score'),
            'judge_HD': p.get('judge_HD') or {},
            'panel_key': p.get('panel_key'),
        }
    for meet_id, payload in by_meet.items():
        sizes['details/%s.json' % meet_id] = _write(
            os.path.join(config.DATA_OUT, 'details', '%s.json' % meet_id), payload)

    # Phase 2 の器。sporttechで氏名が取れる大会は今すぐ埋まる。他は空のまま。
    sizes['judges.json'] = _write(os.path.join(config.DATA_OUT, 'judges.json'), judges)
    sizes['panels.json'] = _write(os.path.join(config.DATA_OUT, 'panels.json'), panels)
    sizes['summary/judge_panel_diff.json'] = _write(
        os.path.join(config.DATA_OUT, 'summary', 'judge_panel_diff.json'), judge_diff)
    sizes['summary/judge_diff_rows.json'] = _write(
        os.path.join(config.DATA_OUT, 'summary', 'judge_diff_rows.json'),
        aggregate.judge_diff_rows(performances, panels, judges))
    sizes['summary/deductions.json'] = _write(
        os.path.join(config.DATA_OUT, 'summary', 'deductions.json'), ded_summary)

    manifest = {
        'dataVersion': data_version,
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'parserVersion': config.PARSER_VERSION,
        'displayMode': config.DISPLAY_MODE_DEFAULT,
        'phase': 1,
        'years': sorted(set(y for y, _ in by_year)),
        'meetsWithDetails': sorted(by_meet.keys()),
        'counts': {
            'competitions': len(competitions),
            'athletes': len(athletes),
            'performances': len(performances),
            'individual': sum(1 for p in performances
                              if p['discipline'] == config.PHASE1_DISCIPLINE),
            'judges': len(judges),
            'panels': len(panels),
        },
        'sources': config.SOURCES,
        'judgeThresholds': {
            'minN': config.JUDGE_MIN_N,
            'strict': config.JUDGE_STRICT,
            'lenient': config.JUDGE_LENIENT,
        },
        'validation': {
            'summary': rep.summary(),
            'passed': rep.passed,
            'warnings': len(rep.warnings),
            'errors': len(rep.errors),
            'notes': rep.notes,
        },
    }
    sizes['manifest.json'] = _write(os.path.join(config.DATA_OUT, 'manifest.json'), manifest)

    os.makedirs(os.path.dirname(config.REPORT_MD), exist_ok=True)
    validate.write_report(rep, config.REPORT_MD, data_version)

    total = sum(sizes.values())
    print('\n--- 出力 ---')
    for name, size in sorted(sizes.items(), key=lambda x: -x[1])[:12]:
        print('  %-34s %8.1f KB' % (name, size / 1024.0))
    print('  ほか %d ファイル / 合計 %.1f MB' % (len(sizes), total / 1024.0 / 1024.0))
    print('\n%s' % rep.summary())
    print('検証レポート: %s' % config.REPORT_MD)
    print('%.1f秒' % (time.time() - started))
    return 0 if not rep.errors else 1


if __name__ == '__main__':
    sys.exit(main())
