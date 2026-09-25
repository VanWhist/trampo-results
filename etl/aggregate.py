# -*- coding: utf-8 -*-
"""事前集計。ブラウザで毎回計算させないために、ここで計算しきる。

ジャッジ分析の指標は「生の平均E」ではなく **パネル内差** を使う。
    審判差 = その審判のE − 同じ演技のパネル中央値
生の平均を使うと「強い選手を多く担当した審判の平均が高い」だけになる。
"""
import collections
import statistics

from . import config


# 予選の次に進んだラウンド（ここに出た選手を「予選通過者」とする）。
# 予選2（Stage.Kind=6）は全日本選手権・W杯の2段目（各区分24名前後）で、名前は予選でも
# 予選を通過した選手だけが出る。以前「準決勝」と表示していたラウンドと同じもの
ADVANCED_ROUNDS = ('予選2', '準々決勝', '準決勝', '決勝', '決勝1', '決勝2')


def _median(values):
    return statistics.median(values) if values else None


def judge_panel_diff(performances, panels, judges):
    """審判ごとのパネル差を集計する。

    母集団の条件は画面から切り替えられるよう、3通りをあらかじめ計算しておく。
      all        … 個人・審判が特定できる全演技
      complete   … 上のうち完遂（技数10）のみ
      qualified  … さらに「同一大会・同一区分で決勝に出場した選手」の演技のみ（既定）
    """
    # 「予選通過者」＝予選の次のラウンド（予選2・準決勝・決勝など）に進んだ選手。
    # 全日本選手権・W杯は 予選 → 予選2（24名）→ 決勝8名 の3段構成なので、
    # 決勝だけを見ると通過者を8名に絞りすぎてしまう。
    advanced = set()
    for p in performances:
        if p['round'] in ADVANCED_ROUNDS and p.get('athlete_id'):
            advanced.add((p['meet_id'], p['category'], p['athlete_id']))

    populations = {'all': [], 'complete': [], 'qualified': []}
    for p in performances:
        if p['discipline'] != config.PHASE1_DISCIPLINE:
            continue
        panel = panels.get(p.get('panel_key') or '')
        if not panel or not panel.get('e_slots'):
            continue
        marks = {label: v for label, v in (p.get('judge_E') or {}).items()
                 if panel['e_slots'].get(label)}
        if len(marks) < 3:
            continue                      # 中央値が意味を持たない
        median = _median(list(marks.values()))
        rows = []
        for label, value in marks.items():
            rows.append({
                'judge_key': panel['e_slots'][label],
                'diff': round(value - median, 4),
                'meet_id': p['meet_id'],
                'season': p['date'][:4],
                'category': p['category'],
                'sex': p.get('sex', ''),
                'round': p['round'],
                'level': p.get('level', ''),
            })
        populations['all'].extend(rows)
        if p['n_elements'] == 10:
            populations['complete'].extend(rows)
            if (p['meet_id'], p['category'], p.get('athlete_id')) in advanced:
                populations['qualified'].extend(rows)

    out = {}
    for pop_name, rows in populations.items():
        by_judge = collections.defaultdict(list)
        for r in rows:
            by_judge[r['judge_key']].append(r)
        entries = []
        for judge_key, items in by_judge.items():
            diffs = [i['diff'] for i in items]
            n = len(diffs)
            mean = sum(diffs) / n
            info = judges.get(judge_key, {})
            enough = n >= config.JUDGE_MIN_N
            if not enough:
                trend = 'データ不足'
            elif mean <= config.JUDGE_STRICT:
                trend = '辛め'
            elif mean >= config.JUDGE_LENIENT:
                trend = '甘め'
            else:
                trend = '中立'
            entries.append({
                'judge_id': judge_key,
                'name': info.get('name', ''),
                'club': info.get('club', ''),
                'n': n,
                'n_meets': len(set(i['meet_id'] for i in items)),
                'n_seasons': len(set(i['season'] for i in items)),
                'categories': sorted(set(i['category'] for i in items)),
                'levels': sorted(set(i['level'] for i in items if i['level'])),
                # 母数が閾値未満の審判は傾向値そのものを出さない
                'mean_diff': round(mean, 4) if enough else None,
                'median_diff': round(_median(diffs), 4) if enough else None,
                'sd': round(statistics.pstdev(diffs), 4) if enough and n > 1 else None,
                'trend': trend,
                'has_trend': enough,
            })
        entries.sort(key=lambda e: (-e['n'], e['name']))
        out[pop_name] = entries
    return out


def judge_diff_rows(performances, panels, judges):
    """審判差の生データを、画面で絞り込めるだけの粒度で持たせる。

    指示書7-4の「大会・区分・男女・ラウンドで絞り込む」は、組み合わせが多すぎて
    事前に全通り計算できない。1行＝1審判×1演技のパネル差だけを渡し、絞り込みが
    かかったときだけブラウザ側で平均を取り直す（既定の表示は事前集計を使う）。

    列名を毎行くり返さないよう、値は配列で持つ。
        [審判の番号, 差×1000, 大会の番号, 区分の番号, 男女, ラウンドの番号, 母集団]
        母集団 … 0=全演技のみ / 1=完遂 / 2=完遂かつ予選通過者
    """
    advanced = set()
    for p in performances:
        if p['round'] in ADVANCED_ROUNDS and p.get('athlete_id'):
            advanced.add((p['meet_id'], p['category'], p['athlete_id']))

    judge_ids, meet_ids, categories, rounds = [], [], [], []
    index = {}

    def idx(bucket, key):
        k = (id(bucket), key)
        if k not in index:
            index[k] = len(bucket)
            bucket.append(key)
        return index[k]

    rows = []
    for p in performances:
        if p['discipline'] != config.PHASE1_DISCIPLINE:
            continue
        panel = panels.get(p.get('panel_key') or '')
        if not panel or not panel.get('e_slots'):
            continue
        marks = {label: v for label, v in (p.get('judge_E') or {}).items()
                 if panel['e_slots'].get(label)}
        if len(marks) < 3:
            continue
        median = _median(list(marks.values()))
        if p['n_elements'] != 10:
            pop = 0
        elif (p['meet_id'], p['category'], p.get('athlete_id')) in advanced:
            pop = 2
        else:
            pop = 1
        m = idx(meet_ids, p['meet_id'])
        c = idx(categories, p['category'])
        r = idx(rounds, p['round'] or '')
        s = {'male': 1, 'female': 2}.get(p.get('sex'), 0)
        for label, value in marks.items():
            rows.append([idx(judge_ids, panel['e_slots'][label]),
                         int(round((value - median) * 1000)), m, c, s, r, pop])

    return {
        'columns': ['judge', 'diff_x1000', 'meet', 'category', 'sex', 'round', 'pop'],
        'judges': [{'judge_id': j, 'name': judges.get(j, {}).get('name', ''),
                    'club': judges.get(j, {}).get('club', '')} for j in judge_ids],
        'meets': meet_ids,
        'categories': categories,
        'rounds': rounds,
        'sexes': ['', 'male', 'female'],
        'rows': rows,
    }


def athlete_summary(performances):
    """選手ごとの自己ベストなど。画面で毎回走査しないための事前計算。"""
    by_athlete = collections.defaultdict(list)
    for p in performances:
        if p['discipline'] != config.PHASE1_DISCIPLINE or not p.get('athlete_id'):
            continue
        by_athlete[p['athlete_id']].append(p)

    out = {}
    for aid, items in by_athlete.items():
        # 自己ベストは今の規則（2017年版以降）の演技だけで出す。旧規則は合計の組み立てが
        # 違う（HDなし・Eを3倍）ので、同じ土俵で最大値を取ると意味が無い。
        current = [p for p in items if _family(p) == config.RULES_CURRENT]
        old = [p for p in items if _family(p) == config.RULES_PRE2017]
        totals = [p['total'] for p in current if p['total'] is not None]
        ds = [p['D'] for p in current if p['D'] is not None]
        scored = [p for p in current if p['total'] is not None]
        best = max(scored, key=lambda p: p['total']) if scored else None
        old_scored = [p for p in old if p['total'] is not None]
        old_best = max(old_scored, key=lambda p: p['total']) if old_scored else None
        out[aid] = {
            'n_performances': len(items),
            'n_meets': len(set(p['meet_id'] for p in items)),
            'first_date': min(p['date'] for p in items),
            'last_date': max(p['date'] for p in items),
            'best_total': max(totals) if totals else None,
            'best_total_meet': best['meet_name'] if best else None,
            'best_total_date': best['date'] if best else None,
            'best_D': max(ds) if ds else None,
            'n_interrupted': sum(1 for p in items
                                 if p['n_elements'] is not None and p['n_elements'] < 10),
            'n_missing_total': sum(1 for p in items if p['total'] is None),
            'n_pre2017': len(old),
            'best_total_pre2017': old_best['total'] if old_best else None,
            'best_total_pre2017_meet': old_best['meet_name'] if old_best else None,
            'best_total_pre2017_date': old_best['date'] if old_best else None,
        }
    return out


def _family(p):
    return p.get('rules_family') or config.rules_family('', p['date'])


def deduction_summary(performances):
    """位置別の減点分布。スロット1〜技数までしか使わない。

    中断演技を集計から外したぶんは必ず数え、画面に併記できるようにする。
    """
    used = collections.defaultdict(list)
    excluded = 0
    other_unit = 0
    interrupted_at = collections.Counter()
    for p in performances:
        if p['discipline'] != config.PHASE1_DISCIPLINE:
            continue
        # 単位が違う減点（旧規則の1人ぶんの尺度など）を平均に混ぜると約半分に引っ張られる
        if p.get('deduct_unit') != 'median2_sum_tenths':
            if any(v is not None for v in p['deduct_positions']):
                other_unit += 1
            continue
        n = p['n_elements']
        if n is None:
            excluded += 1
            continue
        if n < 10:
            excluded += 1
            interrupted_at[n] += 1     # 中断は「どの位置で止まったか」として別に数える
            continue
        for i, v in enumerate(p['deduct_positions']):
            if v is not None:
                used[i + 1].append(v)
    return {
        'by_position': {str(k): {
            'n': len(v),
            'mean': round(sum(v) / len(v), 3) if v else None,
        } for k, v in sorted(used.items())},
        'n_excluded': excluded,
        'n_other_unit': other_unit,
        'unit': 'median2_sum_tenths',
        'interrupted_at': {str(k): v for k, v in sorted(interrupted_at.items())},
    }
