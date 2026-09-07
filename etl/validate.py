# -*- coding: utf-8 -*-
"""ETLの自動検証。更新のたびに `N records passed / M warnings / K errors` を出す。

方針:
  ・Eは式から導出しない。印字値を採用し、式は許容幅つきの検算＋「要確認」フラグに使う
  ・合計も完全一致を要求せず、許容幅を持たせてフラグを立てる
"""
import collections
import io
import json
import os

from . import completeness, config, osaka_crosscheck

# 各ソースの期待件数（個人種目）。実装指示書 第9章の受け入れ基準の数字。
# 大会が増えるとここは増えるので、判定は「大会ごとの件数」（etl/expected_counts.json）で行う。
EXPECTED = {
    'sporttech': 5969,
    'osaka_pweb': 1293,   # 予選1,027＋決勝266。重複掲載36件を除いた数
    'nishinihon': 913,
}


class Report(object):
    def __init__(self):
        self.passed = 0
        self.warnings = []
        self.errors = []
        self.notes = collections.OrderedDict()
        # 実行件数。0件のまま緑にしないためのゲートに使う。
        self.checks = collections.OrderedDict()

    def warn(self, kind, message):
        self.warnings.append((kind, message))

    def error(self, kind, message):
        self.errors.append((kind, message))

    def note(self, key, value):
        self.notes[key] = value

    def summary(self):
        return '%d records passed / %d warnings / %d errors' % (
            self.passed, len(self.warnings), len(self.errors))


def run(performances, athletes, competitions, judges, panels, name_variants_=None,
        accept_sections=False):
    rep = Report()

    # ---- 第0層：完全性 -----------------------------------------------------
    # 数値の検算は「行がそろっている」ことが前提。行が丸ごと落ちても恒等式は成立するので、
    # 先に「原本にあるものが全部入っているか」を確かめる。
    layer0 = completeness.run(performances, rep, accept_sections)
    rep.checks.update(layer0)
    rep.note('完全性の実行件数', ' / '.join('%s %s' % kv for kv in sorted(layer0.items())))

    # ---- 第1層：同じものを別経路で読んで突き合わせる -----------------------
    # 第0層は行がそろっていれば通る。値そのものが正しいかは別の読み方が要る。
    rep.checks.update(osaka_crosscheck.run(performances, rep))

    # ---- ソース別の件数 ----------------------------------------------------
    counts = collections.Counter(p['source'] for p in performances
                                 if p['discipline'] == config.PHASE1_DISCIPLINE)
    for source, expected in EXPECTED.items():
        got = counts.get(source, 0)
        base = '%d' % got
        if got != expected:
            base += '（実装時 %d）' % expected
        rep.note('件数_%s' % source, base)

    # ---- 大会ごとの件数を前回と突き合わせる --------------------------------
    # 大会が増えれば合計は増えるので、合計の一致は判定に使わない。
    # 「すでに取り込んだ大会の件数が変わっていないか」を見るのが本当のチェック。
    _check_meet_counts(rep, performances, competitions)

    # ---- 必須列 ------------------------------------------------------------
    required = ('performance_id', 'meet_id', 'date', 'source', 'discipline',
                'athlete_name', 'n_elements', 'provenance')
    seen_ids = set()
    for p in performances:
        missing = [k for k in required if k not in p]
        if missing:
            rep.error('必須列', '%s に %s が無い' % (p.get('performance_id'), missing))
            continue
        if p['performance_id'] in seen_ids:
            rep.error('重複', '演技IDが重複: %s' % p['performance_id'])
        seen_ids.add(p['performance_id'])

    # ---- 数値の検算 --------------------------------------------------------
    e_checked = e_flagged = 0
    total_checked = total_flagged = 0
    range_bad = 0
    for p in performances:
        if p['discipline'] != config.PHASE1_DISCIPLINE:
            rep.passed += 1
            continue
        p['check_flags'] = []

        # State=2 は採点が確定していないフレーム（全24大会で1件だけ）。
        # 件数を合わせるため記録は残すが、検算はかけずフラグだけ立てる。
        unscored = p.get('state') == 2
        if unscored:
            p['check_flags'].append('採点未確定')
            rep.passed += 1
            continue

        # E の検算（導出はしない）
        n = p['n_elements']
        if n is not None and p['E'] is not None and p.get('data_quality') != 'corrupted':
            positions = [v for v in p['deduct_positions'] if v is not None]
            if len(positions) == n:
                deduct = sum(positions) + (p['deduct_landing'] or 0)
                calc = 2 * n - deduct / 10.0
                e_checked += 1
                if abs(calc - p['E']) > config.TOL_E:
                    e_flagged += 1
                    p['check_flags'].append('E要確認')

        # 合計の検算
        if None not in (p['total'], p['D'], p['E'], p['T'], p['HD']):
            calc = (p['D'] + p['E'] + p['T'] + p['HD']
                    + (p['Bonus'] or 0) - (p['Pen'] or 0) - (p['DPen'] or 0))
            total_checked += 1
            gap = abs(calc - p['total'])
            if gap > config.TOL_TOTAL:
                total_flagged += 1
                p['check_flags'].append('合計要確認')
                if gap > config.TOL_TOTAL_WARN:
                    rep.error('合計', '%s %s 合計%.2f 計算%.2f' % (
                        p['date'], p['athlete_name'], p['total'], calc))
                else:
                    rep.warn('合計', '%s %s 差 %.3f' % (p['date'], p['athlete_name'], gap))

        # 値域
        for field, lo, hi in (('D', 0, 30), ('E', 0, 20), ('T', 0, 25), ('HD', 0, 10)):
            v = p[field]
            if v is not None and not (lo <= v <= hi):
                range_bad += 1
                p['check_flags'].append('%s値域外' % field)
                rep.warn('値域', '%s %s %s=%s' % (p['date'], p['athlete_name'], field, v))

        # 位置別減点の整合（技数を超えた位置に値が残っていないか）
        for i, v in enumerate(p['deduct_positions']):
            if v is not None and (n is None or i >= n):
                rep.error('位置別減点', '%s の位置%d が技数(%s)を超えて残っている'
                          % (p['performance_id'], i + 1, n))

        # E審判の人数
        n_judges = len(p.get('judge_E') or {})
        if n_judges and n_judges not in (4, 5, 6):
            rep.warn('審判人数', '%s %s E審判%d人' % (p['date'], p['athlete_name'], n_judges))

        rep.passed += 1

    rep.checks['E検算'] = e_checked
    rep.checks['合計検算'] = total_checked
    rep.note('E検算', '%d件中 %d件が要確認' % (e_checked, e_flagged))
    rep.note('合計検算', '%d件中 %d件が要確認' % (total_checked, total_flagged))

    # 実行件数ゲート：検証が1件も走っていないのに緑、という状態を作らない
    for name, n in rep.checks.items():
        if n == 0:
            rep.error('実行件数', '%s の検証が0件です。検証が走っていないまま緑になるのを防ぐため'
                                  'エラーにします' % name)
    rep.note('値域外', '%d件' % range_bad)

    # ---- 欠測の数（画面にも出す） ------------------------------------------
    individual = [p for p in performances if p['discipline'] == config.PHASE1_DISCIPLINE]
    rep.note('欠測_合計点', '%d件' % sum(1 for p in individual if p['total'] is None))
    rep.note('欠測_順位', '%d件' % sum(1 for p in individual if p['rank'] is None))
    rep.note('欠測_所属', '%d件' % sum(1 for p in individual if not p['club']))
    rep.note('欠測_技数', '%d件' % sum(1 for p in individual if p['n_elements'] is None))
    rep.note('中断演技', '%d件' % sum(1 for p in individual
                                  if p['n_elements'] is not None and p['n_elements'] < 10))
    rep.note('表示が壊れた行(大阪府)', '%d件' % sum(1 for p in individual
                                            if p.get('data_quality') == 'corrupted'))
    rep.note('採点未確定(State=2)', '%d件' % sum(1 for p in individual if p.get('state') == 2))
    rep.note('審判別Eあり', '%d件' % sum(1 for p in individual if p.get('judge_E')))
    rep.note('審判名まで特定', '%d件' % sum(1 for p in individual if p.get('panel_key')))

    # ---- 選手 --------------------------------------------------------------
    # ---- 審判の表記ゆれ（国内は日本語／国際はローマ字） ---------------------
    # 両方で審判をしている人は、そのままだと別IDになる。自動では結合せず、
    # 候補を毎回レポートに出して、人が judge_overrides.json に足せるようにする。
    jp_candidates = [j for j in judges.values()
                     if all(ord(ch) < 128 for ch in j['name']) and 'JPN' in (j['club'] or '')]
    rep.note('審判の表記ゆれ候補', '%d名（ローマ字表記で所属JPN）' % len(jp_candidates))
    for j in jp_candidates:
        rep.warn('審判の表記ゆれ',
                 '%s（所属JPN）は国内大会では日本語表記の別IDになっている可能性があります。'
                 'judge_overrides.json で統合できます' % j['name'])

    # ---- 選手の表記ゆれ（国内は日本語／国際はローマ字） ---------------------
    # 抜けるのはW杯・アジア選手権に出るトップ層なので、放置すると選手ページから
    # 国際大会の記録だけが落ちる。審判と同じく自動では結合せず、毎回候補を出す。
    if name_variants_:
        variants, already = name_variants_
        confident = [c for c in variants if len(c['matches']) == 1]
        rep.note('選手の表記ゆれ候補',
                 '%d名（うち候補が1人に絞れたもの %d名／統合済み %d名）'
                 % (len(variants), len(confident), already))
        for c in confident:
            rep.warn('選手の表記ゆれ',
                     '%s は %s と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。'
                     'athlete_overrides.json で統合できます'
                     % (c['romanized'], c['matches'][0]['name']))
        for c in variants:
            if len(c['matches']) > 1:
                rep.warn('選手の表記ゆれ',
                         '%s は候補が %d人います。docs/選手の表記ゆれ候補.md を見て選んでください'
                         % (c['romanized'], len(c['matches'])))
            elif not c['matches']:
                # 絞りきれなかったものも必ず残す。黙って消えると、
                # 「確認して統合不要と判断した」のか「見落とした」のか分からなくなる。
                rep.warn('選手の表記ゆれ',
                         '%s は日本語表記側を1人に絞れませんでした（同条件の候補 %d人）。'
                         'docs/選手の表記ゆれ候補.md を見て判断してください'
                         % (c['romanized'], c['loose_total']))

    rep.note('選手数', '%d名' % len(athletes))
    rep.note('大会数', '%d' % len(competitions))
    rep.note('審判数', '%d名' % len(judges))
    rep.note('パネル数', '%d' % len(panels))

    by_source = collections.defaultdict(set)
    for p in performances:
        if p['discipline'] == config.PHASE1_DISCIPLINE and p.get('athlete_id'):
            by_source[p['source']].add(p['athlete_id'])
    for source, ids in by_source.items():
        rep.note('選手数_%s' % source, '%d名' % len(ids))

    return rep


def _check_meet_counts(rep, performances, competitions):
    """大会ごとの個人演技数を前回のスナップショットと比べる。

    ・すでに取り込んだ大会の件数が変わった → **エラー**（取りこぼしか二重取り込み）
    ・大会が増えた                       → 警告（新しい大会を足したのだから正常）
    ・大会が消えた                       → **エラー**（生データを消したか読めていない）

    新しい大会を足したあと、内容を確認してから次のコマンドで基準を更新する:
        python -m etl.build --accept-counts
    """
    got = collections.Counter()
    for p in performances:
        if p['discipline'] == config.PHASE1_DISCIPLINE:
            got[p['meet_id']] += 1
    names = {c['meet_id']: '%s %s' % (c['date'], c['name']) for c in competitions}

    if not os.path.exists(config.EXPECTED_COUNTS):
        rep.note('大会別件数の基準', '未作成（今回の結果を基準として保存します）')
        _write_counts(got)
        return

    with io.open(config.EXPECTED_COUNTS, encoding='utf-8') as fh:
        expected = json.load(fh).get('meets', {})

    added, changed, removed = [], [], []
    for meet_id, n in sorted(got.items()):
        if meet_id not in expected:
            added.append((meet_id, n))
        elif expected[meet_id] != n:
            changed.append((meet_id, expected[meet_id], n))
    for meet_id, n in sorted(expected.items()):
        if meet_id not in got:
            removed.append((meet_id, n))

    for meet_id, before, after in changed:
        rep.error('大会別件数', '%s の個人演技が %d件 → %d件 に変わりました。'
                  '取りこぼしか二重取り込みの可能性があります'
                  % (names.get(meet_id, meet_id), before, after))
    for meet_id, n in removed:
        rep.error('大会別件数', '%s（%d件）が今回は読めていません' % (meet_id, n))
    for meet_id, n in added:
        rep.warn('大会別件数', '%s を新しく取り込みました（個人 %d件）。'
                 '内容を確認したら `python -m etl.build --accept-counts` で基準を更新してください'
                 % (names.get(meet_id, meet_id), n))

    rep.note('大会別件数', '既存 %d大会は前回と一致／新規 %d大会／消えた大会 %d'
             % (len(got) - len(added) - len(changed), len(added), len(removed)))


def _write_counts(counts):
    os.makedirs(os.path.dirname(config.EXPECTED_COUNTS), exist_ok=True)
    with io.open(config.EXPECTED_COUNTS, 'w', encoding='utf-8') as fh:
        json.dump({
            '_comment': '大会ごとの個人演技数。ETLが前回と比べて取りこぼしを検知するために使う。'
                        '新しい大会を足したら `python -m etl.build --accept-counts` で更新する。',
            'meets': dict(sorted(counts.items())),
        }, fh, ensure_ascii=False, indent=2)


def accept_counts(performances):
    """新しい大会の件数を基準として受け入れる（--accept-counts）。"""
    counts = collections.Counter()
    for p in performances:
        if p['discipline'] == config.PHASE1_DISCIPLINE:
            counts[p['meet_id']] += 1
    _write_counts(counts)
    return len(counts)


def write_report(rep, path, data_version):
    lines = []
    lines.append('# ETL検証レポート')
    lines.append('')
    lines.append('dataVersion: `%s`' % data_version)
    lines.append('')
    lines.append('```')
    lines.append(rep.summary())
    lines.append('```')
    lines.append('')
    lines.append('## 集計')
    lines.append('')
    lines.append('| 項目 | 値 |')
    lines.append('|---|---|')
    for k, v in rep.notes.items():
        lines.append('| %s | %s |' % (k, v))
    lines.append('')
    if rep.errors:
        lines.append('## エラー（%d件）' % len(rep.errors))
        lines.append('')
        for kind, message in rep.errors[:200]:
            lines.append('- **%s** %s' % (kind, message))
        lines.append('')
    if rep.warnings:
        lines.append('## 警告（%d件）' % len(rep.warnings))
        lines.append('')
        counts = collections.Counter(k for k, _ in rep.warnings)
        for kind, n in counts.most_common():
            lines.append('- %s … %d件' % (kind, n))
        lines.append('')
        lines.append('<details><summary>内訳</summary>')
        lines.append('')
        for kind, message in rep.warnings[:300]:
            lines.append('- %s %s' % (kind, message))
        lines.append('')
        lines.append('</details>')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
