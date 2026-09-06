# -*- coding: utf-8 -*-
"""第0層（完全性）の変異テスト。

    python -m etl.tests.test_completeness

正しいデータをわざと壊し、**どの検査が止めるか**を確かめる。各変異について
「少なくとも1つの検査がエラーを出す」ことを要求する。

とくに確かめたいのは、恒等式（E・合計）では絶対に止まらない種類の事故:
  ・ページ1枚分の行が丸ごと落ちる（西日本 大学生女子予選 p4 で実際に起きかけた）
  ・末尾のページだけ切れる（順位の連続性では止まらない。1〜45位が連続していれば通ってしまう）
  ・1選手の行が2行ズレる（点数は正しいまま氏名だけ入れ替わる）

本番と同じ順序（読み込み → 名寄せ → 検証）で流すこと。名寄せの前に件数を数えると、
表記ゆれの統合が効かず選手数が変わって誤検知する。
"""
import collections
import copy
import sys

sys.stdout.reconfigure(encoding='utf-8')

from .. import completeness, normalize, validate
from ..sources import nishinihon, osaka, sporttech


def load_baseline():
    """本番と同じ手順でレコードを作る（build.main の前半と同じ）。"""
    st_comps, st_perfs, _, _ = sporttech.load_all()
    _, os_perfs = osaka.load_all()
    _, nw_perfs = nishinihon.load_all()
    perfs = st_perfs + os_perfs + nw_perfs
    normalize.build_athletes(perfs, normalize.load_overrides())   # 氏名の正規化を先に効かせる
    return perfs


def run_checks(perfs):
    rep = validate.Report()
    completeness.run(perfs, rep, accept=False)
    return rep


def without(perfs, pred):
    return [p for p in perfs if not pred(p)]


def main():
    base = load_baseline()
    clean = run_checks(base)
    print('変異なし: %s' % ('OK（エラー0）' if not clean.errors
                          else '★エラー%d件 %s' % (len(clean.errors), clean.errors[:2])))
    all_ok = not clean.errors
    print()

    nishi = lambda cat, rnd: (lambda p: p['source'] == 'nishinihon'
                              and p['category'] == cat and p['round'] == rnd)

    # 末尾28名分（＝最終ページ相当）の順位
    tail = sorted({int(p['rank']) for p in base
                   if nishi('小学生高学年 女子', '予選')(p)})[-28:]

    def swap_two_names(perfs):
        """1選手の行を2行ズラす。点数はそのままで氏名だけ入れ替わる。"""
        out = copy.deepcopy(perfs)
        target = [p for p in out if nishi('中学生 男子', '予選')(p)]
        target.sort(key=lambda p: (int(p['rank']), p['routine'] or 0))
        for a, b in ((0, 2), (1, 3)):
            target[a]['athlete_name'], target[b]['athlete_name'] = \
                target[b]['athlete_name'], target[a]['athlete_name']
        return out

    def shift_q2(perfs):
        """2行目（所属＋Q2）を1つ隣の選手にズラす。実際に起きる事故はこの形。

        氏名だけを入れ替えるより現実的で、条件も厳しい（点数はどこかで必ず整合しなくなる）。
        """
        out = copy.deepcopy(perfs)
        rows = [p for p in out if nishi('高校生 女子', '予選')(p) and p['routine'] == 2]
        rows.sort(key=lambda p: int(p['rank']))
        moved = [rows[i]['total'] for i in range(len(rows))]
        for i, r in enumerate(rows):
            r['total'] = moved[(i + 1) % len(moved)]
        return out

    osaka_cat = [p for p in base if p['source'] == 'osaka_pweb'][0]['raw_category']
    one_osaka = [p for p in base if p['source'] == 'osaka_pweb'][5]

    cases = [
        ('ページ1枚分を丸ごと欠落（西日本 大学生女子予選 p4）',
         without(base, nishi('大学生 女子', '予選'))),
        ('末尾のページだけ欠落（西日本 小学生高学年女子予選の末尾28名）',
         without(base, lambda p: nishi('小学生高学年 女子', '予選')(p) and int(p['rank']) in tail)),
        ('途中の順位が抜ける（西日本 中学生男子予選 10〜12位）',
         without(base, lambda p: nishi('中学生 男子', '予選')(p) and int(p['rank']) in (10, 11, 12))),
        ('大阪府 1区分を丸ごと欠落',
         without(base, lambda p: p['source'] == 'osaka_pweb' and p['raw_category'] == osaka_cat)),
        ('大阪府 1演技だけ欠落',
         without(base, lambda p: p is one_osaka)),
        ('1選手の行を2行ズラす（点数は正しいまま氏名だけ入れ替わる）',
         swap_two_names(base)),
        ('2行目（Q2のスコアごと）を1つズラす',
         shift_q2(base)),
    ]

    for label, mutated in cases:
        rep = run_checks(mutated)
        kinds = sorted({k for k, _ in rep.errors})
        ok = bool(rep.errors)
        all_ok &= ok
        print('%s %-52s 止めた検査: %s' % ('OK ' if ok else 'NG ', label,
                                          '、'.join(kinds) if kinds else 'なし'))
        for _, message in rep.errors[:1]:
            print('        → %s' % message[:120])

    print()
    print('結果:', '全変異を検出' if all_ok else '★検出できない変異あり')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
