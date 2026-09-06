# -*- coding: utf-8 -*-
"""西日本トランポリン協会（第53回西日本選手権）のCSVから演技レコードを組み立てる。

注意点:
  1. 値が0の列はPDFに印字されないため、変換後CSVでも空欄になっている。
     とくに予選1本目のDは規定演技なので大半が空欄＝0。欠測ではない
  2. 審判別のデータは無い（技ごとの減点までしか取れない）
  3. L列は §20.2.2 で説明できない値（L=4）を含む。恒等式には効くが、
     「着地減点」と決めつけて分析に使わないこと
  4. 所属は**選手行の次の行**に印字される（予選はQ2のスコアと同じ行に連結、決勝は独立行）。
     長い所属は複数行に折り返され、予選のQ2行では列幅で切り詰められることがある。
     さらに、同点0.00で順位が並ぶ箇所では、CSVの予選1本目に隣の選手の所属が入っている。
     一般則で直そうとすると前提を誤るので、**PDFで個別に確認した分だけ**
     `nishinihon_club_fixes.json` で訂正する。
"""
import csv
import io

from .. import club_fixes, config

MEET_ID = 'nw-2025-09-12'


def _f(text):
    text = (text or '').strip()
    if text == '':
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _i(text):
    v = _f(text)
    return int(v) if v is not None else None


def load_all():
    with io.open(config.CSV_NISHI, encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))

    first = rows[0]
    competition = {
        'meet_id': MEET_ID,
        'date': first['大会日'],
        'name': first['大会名'],
        'level': first['国内国際'],
        'season': first['年'],
        'source': 'nishinihon',
        'official': config.SOURCES['nishinihon']['official'],
        'source_url': config.SOURCES['nishinihon']['base_url'],
        'event_id': '',
        'fetched_at': '',
        'raw_dir': '2025/西日本トランポリン協会_PDF',
    }

    performances = []
    for i, r in enumerate(rows):
        n = _i(r['技数'])
        positions, unaccounted = [], 0
        for k in range(10):
            v = _f(r['S%d' % (k + 1)])
            if n is None or k >= n:
                positions.append(None)
                unaccounted += v or 0
            else:
                positions.append(v)
        landing_raw = _f(r['L']) or 0
        if n == 10:
            landing = landing_raw
        else:
            landing = None
            unaccounted += landing_raw

        # PDFは0を印字しないので、空欄のDは欠測ではなく0（予選1本目＝規定演技）。
        d_raw = _f(r['D'])
        d_implicit_zero = d_raw is None
        category = (r['種別'] or '').strip()

        performances.append({
            'performance_id': '%s|%04d' % (MEET_ID, i),
            'meet_id': MEET_ID,
            'date': r['大会日'],
            'meet_name': r['大会名'],
            'source': 'nishinihon',
            'official': config.SOURCES['nishinihon']['official'],
            'discipline': (r['種目'] or '個人').strip(),
            'category': category,
            'sex': 'female' if '女子' in category else ('male' if '男子' in category else ''),
            'age_group': '',
            'round': (r['ラウンド'] or '').strip() or None,
            'round_raw': (r['ラウンド'] or '').strip(),
            'routine': _i(r['演技']),
            'athlete_name': (r['選手'] or '').strip(),
            'athlete_names': [(r['選手'] or '').strip()],
            'club': (r['所属'] or '').strip(),
            'birth_date': None,
            'rank': _i(r['順位']),
            'total': _f(r['合計']),
            'D': 0.0 if d_implicit_zero else d_raw,
            'D_implicit_zero': d_implicit_zero,
            'E': _f(r['E']),
            'T': _f(r['T']),
            'HD': _f(r['HD']),
            'Bonus': None,
            'Pen': _f(r['Pen']),
            'DPen': None,
            'n_elements': n,
            'deduct_positions': positions,
            'deduct_landing': landing,
            'deduct_extra_a': None,
            'deduct_unaccounted': unaccounted,
            'deduct_unit': 'median2_sum_tenths',
            'judge_E': {},          # 審判別データなし
            'judge_HD': {},
            'panel_key': None,
            'state': None,
            'stage_id': None,
            'frame_id': None,
            'perf_id_raw': None,
            'qualifying_total': _f(r['予選合計']),
            'raw': {},
            'provenance': {
                'source': 'nishinihon',
                'source_url': config.SOURCES['nishinihon']['base_url'],
                'raw_filename': r['PDFページ'],
                'imported_at': '',
                'parser_version': config.PARSER_VERSION,
                'correction_flag': 'D空欄を0として採用（規定演技）' if d_implicit_zero else '',
            },
        })
    club_fixes.apply(performances)
    return [competition], performances


