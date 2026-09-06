# -*- coding: utf-8 -*-
"""大阪府（トランポリン応援団 / trampoline.pweb.jp）のCSVから演技レコードを組み立てる。

このソースの注意点（README 2026-08-08 の訂正を反映）:
  1. `_大阪府pweb_演技サマリー.csv` の列名は信用しない。実際は1つずつずれている
     （技数列→E、E列→HD、H列→D、D列→T、T列→P、P列→合計、Sum列は空）
  2. サマリーCSVは予選のみ（1,063演技）。決勝266演技は統合CSVにしかなく、
     D・T・合計・順位が存在しない。取れないものは空欄にして数を数える
  3. 減点の単位が2種類ある。E行＝中央2審判の和、E1〜E4行＝審判1人ぶん。混ぜると約2倍ずれる
  4. `data_quality == 'corrupted'` はサイトのPHPバグで表示が壊れた行。集計から除外する
  5. 所属と順位の列がそもそも存在しない
"""
import collections
import csv
import io
import re

from .. import config

MEET_PREFIX = 'os'
CATEGORY_SUFFIXES = ('予選成績', '決勝成績', '結果成績')
# ラウンドは区分名の末尾ではなく round 列から決める。
# 「結果成績」（国スポ選考会）は決勝が無く1・2本目だけなので、末尾で判定すると決勝になってしまう。
ROUND_BY_COLUMN = {'1Rtn': '予選', '2Rtn': '予選', 'Final': '決勝'}


def _rows(path):
    with io.open(path, encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


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


def _clean_category(raw):
    """「個人競技 11才?12才男子　決勝成績」→ '11才～12才男子'"""
    text = (raw or '').replace('　', ' ').strip()
    text = text.replace('?', '～')          # 元HTMLの文字化け（～）
    for suffix in CATEGORY_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    text = re.sub(r'^個人競技\s*', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _sex(category):
    if '女子' in category:
        return 'female'
    if '男子' in category:
        return 'male'
    return ''


def _meet_id(date):
    return '%s-%s' % (MEET_PREFIX, date)


def load_all():
    """(competitions, performances) を返す。審判は氏名が公開されていないので作らない。"""
    judge_rows = _rows(config.CSV_OSAKA_JUDGE)
    summary_rows = _rows(config.CSV_OSAKA_SUMMARY)

    # ---- 統合CSV を 1演技 = 7行 にまとめる ---------------------------------
    perf_rows = collections.OrderedDict()
    for r in judge_rows:
        key = (r['大会日'], r['区分'], r['選手'], r['演技'])
        perf_rows.setdefault(key, {})[r['審判']] = r

    # ---- サマリーCSV（予選のみ）を引けるようにする -------------------------
    summary = {}
    for r in summary_rows:
        key = (r['大会日'], r['区分'], r['選手'], r['演技'])
        # 列名は信用しない。位置で読む。
        summary[key] = {
            'E': _f(r['技数']), 'HD': _f(r['E']), 'D': _f(r['H']),
            'T': _f(r['D']), 'Pen': _f(r['T']), 'total': _f(r['P']),
        }

    competitions = {}
    performances = []
    for key, rows in perf_rows.items():
        date, raw_category, name, routine = key
        e_row = rows.get('E')
        if e_row is None:
            continue
        meet_name = e_row['大会名']
        meet_id = _meet_id(date)
        competitions.setdefault(meet_id, {
            'meet_id': meet_id,
            'date': date,
            'name': meet_name,
            'level': '地方',
            'season': date[:4],
            'source': 'osaka_pweb',
            'official': config.SOURCES['osaka_pweb']['official'],
            'source_url': config.SOURCES['osaka_pweb']['base_url'],
            'event_id': '',
            'fetched_at': e_row.get('fetched_at', ''),
            'raw_dir': '',
        })

        category = _clean_category(raw_category)
        round_label = ROUND_BY_COLUMN.get(e_row.get('round'))
        n = _i(e_row.get('skill_count'))
        quality_bad = any(r.get('data_quality') == 'corrupted' for r in rows.values())
        n_source = e_row.get('skill_count_source') or 'unknown'

        positions, unaccounted = [], 0
        for i in range(10):
            v = _f(e_row.get('S%d' % (i + 1)))
            if n is None or i >= n:
                positions.append(None)
                unaccounted += v or 0
            else:
                positions.append(v)
        landing_raw = _f(e_row.get('L')) or 0
        if n == 10:
            landing = landing_raw
        else:
            landing = None
            unaccounted += landing_raw

        # 審判ごとの実施点（審判1人ぶんの減点。E行とは単位が違う）
        judge_e = {}
        for label in ('E1', 'E2', 'E3', 'E4'):
            r = rows.get(label)
            if r is None:
                continue
            v = _f(r.get('合計'))
            if v is not None:
                judge_e[label] = v
        judge_hd = {}
        for label, out in (('E5', 'HD1'), ('E6', 'HD2')):
            r = rows.get(label)
            if r is None:
                continue
            v = _f(r.get('合計'))
            if v is not None:
                judge_hd[out] = v

        s = summary.get(key)
        e_printed = s['E'] if s else _f(e_row.get('合計'))
        hd_printed = s['HD'] if s else None
        hd_derived = False
        if hd_printed is None and len(judge_hd) == 2:
            # 決勝はサマリーCSVが無いためHDの印字値が取れない。
            # HD = (HD1 + HD2) / 2 は予選1,063演技すべてで成立したので、この規則で復元し
            # derived フラグを立てる（推測ではなく実データで確認した規則）。
            hd_printed = round((judge_hd['HD1'] + judge_hd['HD2']) / 2.0, 2)
            hd_derived = True

        performances.append({
            'performance_id': '%s|%s|%s|%s' % (meet_id, raw_category, name, routine),
            'meet_id': meet_id,
            'date': date,
            'meet_name': meet_name,
            'source': 'osaka_pweb',
            'official': config.SOURCES['osaka_pweb']['official'],
            'discipline': '個人',
            'category': category,
            # 完全性チェックで一覧ページ（区分一覧CSV）と突き合わせるため、原本の区分名も残す
            'raw_category': raw_category,
            'sex': _sex(category),
            'age_group': '',
            'round': round_label,
            'round_raw': e_row.get('round'),
            'routine': _i(routine),
            'athlete_name': name,
            'athlete_names': [name],
            'club': '',            # 大阪府のデータには所属が無い
            'birth_date': None,
            'rank': None,          # 順位も無い
            'total': s['total'] if s else None,
            'D': s['D'] if s else None,
            'E': e_printed,
            'T': s['T'] if s else None,
            'HD': hd_printed,
            'HD_derived': hd_derived,
            'Bonus': None,
            'Pen': s['Pen'] if s else None,
            'DPen': None,
            'n_elements': n,
            'n_elements_source': n_source,
            'deduct_positions': positions,
            'deduct_landing': landing,
            'deduct_extra_a': None,
            'deduct_unaccounted': unaccounted,
            'deduct_unit': 'median2_sum_tenths',
            'judge_E': judge_e,
            'judge_E_unit': 'single_judge_execution_score',   # E行とは単位が違う
            'judge_HD': judge_hd,
            'panel_key': None,     # 審判の氏名が公開されていない
            'state': None,
            'stage_id': None,
            'frame_id': None,
            'perf_id_raw': None,
            'data_quality': 'corrupted' if quality_bad else 'ok',
            'verification': e_row.get('verification', ''),
            'raw': {},
            'provenance': {
                'source': 'osaka_pweb',
                'source_url': e_row.get('source_url') or config.SOURCES['osaka_pweb']['base_url'],
                'raw_filename': '_大阪府pweb_ジャッジ明細_統合.csv',
                'imported_at': e_row.get('fetched_at', ''),
                'parser_version': config.PARSER_VERSION,
                'correction_flag': '列名ずれ補正（サマリーCSV）' if s else '',
                'upstream_parser': e_row.get('parser_version', ''),
                'sha256': e_row.get('sha256', ''),
            },
        })

    performances = _dedupe_categories(performances)
    return list(competitions.values()), performances


def _dedupe_categories(performances):
    """区分ページをまたいで同じ演技が2回載っている分を1件にまとめる。

    2025-05-10 の「09才～10才女子」と「10才以下女子」のように、範囲が重なる区分の
    ページが両方公開されていることがある。値は完全に同一なので、片方だけを残し、
    もう一方の区分名は `also_in_categories` に持たせて情報を落とさない。
    """
    kept = {}
    order = []
    for p in performances:
        p['also_in_categories'] = []
        # 実施点Eまで一致していれば同じ演技とみなす。
        # 表示が壊れた行（php_warning）では技数の復元可否が区分ページによって違うので、
        # 情報量の多いほうを残す。
        key = (p['meet_id'], p['athlete_name'], p['routine'], p['E'])
        first = kept.get(key)
        p['also_in_raw_categories'] = []
        if first is None:
            kept[key] = p
            order.append(p)
            continue
        if _richness(p) > _richness(first):
            p['also_in_categories'] = first['also_in_categories'] + [first['category']]
            p['also_in_raw_categories'] = first['also_in_raw_categories'] + [first['raw_category']]
            order[order.index(first)] = p
            kept[key] = p
        else:
            first['also_in_categories'].append(p['category'])
            first['also_in_raw_categories'].append(p['raw_category'])
    return order


def _richness(p):
    """情報量の多さ。技数が分かっていて、その由来が Skils行 のものを優先する。"""
    score = 0
    if p['n_elements'] is not None:
        score += 2
    if p.get('n_elements_source') == 'skils_row':
        score += 1
    if p['total'] is not None:
        score += 1
    return score
