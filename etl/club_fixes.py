# -*- coding: utf-8 -*-
"""西日本の所属の個別訂正。

所属は選手行の**次の行**に印字される（予選はQ2のスコアと同じ行に連結、決勝は独立行）。
長い所属は複数行に折り返され、予選のQ2行では列幅で切り詰められることがある。さらに、
同点0.00で順位が並ぶ箇所では、CSVの予選1本目に隣の選手の所属が入っていた。

印字位置・折り返し・切り詰めの規則を一般化して直そうとすると前提を誤りやすい
（実際に「印字は予選2本目だけ」「決勝には印字が無い」という一般則を立てて、どちらも誤りだった）。
そこで **PDFで1件ずつ確認したものだけ** を `nishinihon_club_fixes.json` で訂正する。

訂正が当たらなくなったら（元CSVが差し替わった等）エラーにする。黙って効かなくなるのを防ぐ。
"""
import io
import json
import os

FIXES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nishinihon_club_fixes.json')

_applied = []          # 直近の apply() で実際に書き換えた行


def _load():
    if not os.path.exists(FIXES):
        return []
    with io.open(FIXES, encoding='utf-8') as fh:
        return json.load(fh).get('fixes', [])


def _matches(fix, p):
    if fix['athlete'] != p['athlete_name']:
        return False
    for key, field in (('category', 'category'), ('round', 'round'), ('routine', 'routine')):
        if fix.get(key) is not None and fix[key] != p[field]:
            return False
    if fix.get('from') is not None and fix['from'] != p['club']:
        return False
    return True


def apply(performances):
    """訂正を当てる。書き換えた行には出どころを残す。"""
    global _applied
    _applied = []
    fixes = _load()
    for fix in fixes:
        hits = [p for p in performances if _matches(fix, p)]
        for p in hits:
            if p['club'] == fix['to']:
                continue
            _applied.append({'fix': fix, 'from': p['club'], 'row': p['performance_id'],
                             'category': p['category'], 'round': p['round'],
                             'routine': p['routine']})
            p['club_corrected_from'] = p['club']
            p['club'] = fix['to']
            p['club_source'] = 'corrected_from_pdf'
        fix['_hits'] = len(hits)
    return fixes


def check(rep, accept=False):
    """全ての訂正が当たったかを確かめ、件数を返す。"""
    fixes = _load()
    applied_by_athlete = {}
    for a in _applied:
        applied_by_athlete.setdefault(a['fix']['athlete'], []).append(a)

    for fix in fixes:
        n = len(applied_by_athlete.get(fix['athlete'], []))
        if n == 0:
            rep.error('所属の訂正', '%s の訂正が1行も当たりませんでした（%s → %s）。'
                                    '元CSVが変わった可能性があります'
                      % (fix['athlete'], fix.get('from') or '（指定なし）', fix['to']))
    rep.note('所属の訂正(西日本)', '%d件の指定で %d行を訂正（根拠: %s）'
             % (len(fixes), len(_applied),
                '、'.join(sorted({f['pdf'] for f in fixes}))))
    return len(_applied)


def applied():
    return list(_applied)
