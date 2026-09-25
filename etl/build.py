# -*- coding: utf-8 -*-
"""ETL本体。生データを読み、正規化・事前集計して data/ にJSONを書き出す。

    python -m etl.build

生データ（大会リザルト\\ 配下）は読むだけで、絶対に書き換えない。
"""
import collections
import hashlib
import io
import json
import os
import sys
import time

from . import aggregate, config, name_variants, normalize, validate
from .sources import nishinihon, nishinihon_pdf, osaka, osaka_html, sporttech

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
    # 西日本の予選はPDFに「予選合計」が印字されている。計算せず印字値をそのまま出す。
    'qualifying_total',
    # 2017年版より前の規則の演技だけ True（HDなし・Eは1人ぶんの尺度）。今の規則は出さない
    'pre2017',
)

# 選手ページは1人ぶんの演技しか要らない。全年の演技（約2万行）を読ませないよう、
# 選手を束に分けて書き出す。束の決め方は js/data.js の athleteShard() と必ず同じにする。
ATHLETE_SHARDS = 128


def athlete_shard(athlete_id):
    """FNV-1a（32bit）で選手IDを束の番号にする。JS 側と同じ計算。"""
    h = 0x811c9dc5
    for ch in athlete_id:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xffffffff
    return h % ATHLETE_SHARDS


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(',', ':'))
    return os.path.getsize(path)


def _content_hash(sizes):
    """書き出したJSONの中身からハッシュを作る。dataVersion を決めるのに使う。"""
    h = hashlib.sha1()
    for name in sorted(sizes):
        h.update(name.encode('utf-8'))
        with io.open(os.path.join(config.DATA_OUT, *name.split('/')), 'rb') as fh:
            h.update(fh.read())
    return h.hexdigest()


def _data_version(content_hash):
    """中身が変わったら必ず別の版にする。変わっていなければ据え置く。

    dataVersion は画面がJSONを読むときのクエリに付く。日付＋連番を機械的に付けると
    同じ日の2回目のビルドで値が変わらず、更新したのにブラウザとCDNが古いJSONを
    使い続ける（2026-09-07に実際に踏んだ）。前回の中身と比べて決める。
    """
    today = time.strftime('%Y-%m-%d')
    path = os.path.join(config.DATA_OUT, 'manifest.json')
    prev = {}
    if os.path.exists(path):
        with io.open(path, encoding='utf-8') as fh:
            prev = json.load(fh)
    previous = prev.get('dataVersion', '')
    if previous and prev.get('contentHash') == content_hash:
        return previous
    seq = 1
    if previous.startswith(today + '-'):
        try:
            seq = int(previous.rsplit('-', 1)[1]) + 1
        except ValueError:
            seq = 2
    return '%s-%02d' % (today, seq)


def main(argv=None):
    started = time.time()
    argv = sys.argv[1:] if argv is None else argv
    accept = '--accept-counts' in argv
    accept_sections = '--accept-sections' in argv

    print('生データを読みます…')
    st_comps, st_perfs, judges, panels = sporttech.load_all()
    os_comps, os_perfs = osaka.load_all()
    # 中間CSVに無い順位・所属・決勝の得点内訳を、元HTMLから補う（上書きはしない）。
    # 補った項目は osaka_crosscheck の突き合わせから外れる。
    filled = osaka_html.fill_missing(os_perfs)
    if filled:
        print('  大阪府：元HTMLから補った項目 %s'
              % ' / '.join('%s %d' % kv for kv in sorted(filled.items())))
    nw_comps, nw_perfs = nishinihon.load_all()
    n54_comps, n54_perfs = nishinihon_pdf.load_all()   # 第54回はPDFを直接読む

    competitions = st_comps + os_comps + nw_comps + n54_comps
    performances = st_perfs + os_perfs + nw_perfs + n54_perfs
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
    readings = name_variants.surname_readings(overrides)
    variants, already_merged = name_variants.find_candidates(
        performances, merged_names, readings)
    name_variants.write_report(variants, already_merged, config.VARIANTS_MD)

    print('検証…')
    rep = validate.run(performances, athletes, competitions, judges, panels,
                       name_variants_=(variants, already_merged),
                       accept_sections=accept_sections)
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
        p['pre2017'] = (p.get('rules_family') or config.rules_family('', p['date']))             == config.RULES_PRE2017
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

    # 画面ごとに要る分だけ読めるよう、同じ行を大会別・選手の束別にも書く（個人のみ）。
    #   大会ページ … meets/<meet_id>.json
    #   選手ページ … by_athlete/<束の番号>.json
    individual_rows = [r for (y, suffix), items in by_year.items() if not suffix for r in items]
    by_meet_rows = collections.defaultdict(list)
    by_shard = collections.defaultdict(list)
    for r in individual_rows:
        by_meet_rows[r['meet_id']].append(r)
        if r.get('athlete_id'):
            by_shard[athlete_shard(r['athlete_id'])].append(r)
    # 前回の書き出しが残ると、消えた大会や束の古いファイルを画面が読んでしまう
    for sub in ('meets', 'by_athlete'):
        folder = os.path.join(config.DATA_OUT, sub)
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                if name.endswith('.json'):
                    os.remove(os.path.join(folder, name))
    for meet_id, items in by_meet_rows.items():
        sizes['meets/%s.json' % meet_id] = _write(
            os.path.join(config.DATA_OUT, 'meets', '%s.json' % meet_id), items)
    for shard in range(ATHLETE_SHARDS):
        sizes['by_athlete/%d.json' % shard] = _write(
            os.path.join(config.DATA_OUT, 'by_athlete', '%d.json' % shard), by_shard.get(shard, []))
    # 入口の絞り込みの選択肢。これのために全演技を読ませない
    facets = {
        'categories': sorted({r['category'] for r in individual_rows if r.get('category')}),
        'rounds': sorted({r['round'] for r in individual_rows if r.get('round')}),
        'routines': sorted({r['routine'] for r in individual_rows if r.get('routine')}),
    }

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

    content_hash = _content_hash(sizes)
    data_version = _data_version(content_hash)
    manifest = {
        'dataVersion': data_version,
        'contentHash': content_hash,
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'parserVersion': config.PARSER_VERSION,
        'displayMode': config.DISPLAY_MODE_DEFAULT,
        'phase': 1,
        'years': sorted(set(y for y, _ in by_year)),
        'facets': facets,
        'athleteShards': ATHLETE_SHARDS,
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
            'checks': rep.checks,
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
