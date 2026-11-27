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

from .. import completeness, normalize, osaka_crosscheck, validate
from ..sources import (higashinihon_pdf, nishinihon, nishinihon_old_pdf, nishinihon_pdf, osaka,
                       osaka_html, sporttech)


def load_baseline():
    """本番と同じ手順でレコードを作る（build.main の前半と同じ）。"""
    st_comps, st_perfs, _, _ = sporttech.load_all()
    _, os_perfs = osaka.load_all()
    _, nw_perfs = nishinihon.load_all()
    _, n54_perfs = nishinihon_pdf.load_all()
    _, ej_perfs = higashinihon_pdf.load_all()
    _, nwo_perfs = nishinihon_old_pdf.load_all()
    osaka_html.fill_missing(os_perfs)      # 本番と同じく元HTMLで穴を埋める
    perfs = st_perfs + os_perfs + nw_perfs + n54_perfs + ej_perfs + nwo_perfs
    normalize.build_athletes(perfs, normalize.load_overrides())   # 氏名の正規化を先に効かせる
    return perfs


def run_checks(perfs):
    rep = validate.Report()
    completeness.run(perfs, rep, accept=False)
    # 第1層も回す。氏名だけがズレる事故は第0層では止まらないので、
    # 大阪府はここ（元HTMLとの突き合わせ）が担当する。
    osaka_crosscheck.run(perfs, rep, write_doc=False)
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

    # 第53回と第54回は区分名が同じなので、大会まで指定しないと両方に当たる。
    def nishi(cat, rnd, meet_id='nw-2025-09-12'):
        return lambda p: (p['source'] == 'nishinihon' and p['meet_id'] == meet_id
                          and p['category'] == cat and p['round'] == rnd)

    def nishi54(cat, rnd):
        return nishi(cat, rnd, 'nw-2026-09-04')

    # 末尾28名分（＝最終ページ相当）の順位
    tail = sorted({int(p['rank']) for p in base
                   if nishi('小学生高学年 女子', '予選')(p)})[-28:]

    # 第54回で実際に踏んだ2つの欠陥を種にする。
    #   ・見出しも列見出しも無い継続ページを丸ごと読み飛ばしていた
    #   ・ページ境界で割れた選手の2本目（所属＋Q2）を捨てていた
    def page_of(p):
        return (p.get('provenance') or {}).get('raw_filename', '')

    cont_page = '54th_小学生高学年女子_予選.pdf p5'
    split_pages = collections.defaultdict(set)
    for p in base:
        if nishi54('小学生高学年 女子', '予選')(p):
            split_pages[p['athlete_name']].add(page_of(p))
    split_name = sorted(n for n, pgs in split_pages.items() if len(pgs) > 1)[0]

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

    def swap_osaka_names(perfs):
        """大阪府で氏名だけを入れ替える。点数は動かさない。

        第0層は行数も順位も変わらないので通ってしまう。元HTMLとの突き合わせだけが
        「その点数はその人のものではない」と言える。
        """
        out = copy.deepcopy(perfs)
        rows = [p for p in out if p['source'] == 'osaka_pweb'
                and p['date'] == '2025-05-10' and p['category'] == '11才～12才男子'
                and p['routine'] == 1]
        rows.sort(key=lambda p: p['athlete_name'])
        rows[0]['athlete_name'], rows[1]['athlete_name'] =             rows[1]['athlete_name'], rows[0]['athlete_name']
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
        ('大阪府 1選手の氏名を隣とすげ替える（点数はそのまま）',
         swap_osaka_names(base)),
        ('継続ページを丸ごと欠落（第54回 小学生高学年女子予選 p5）',
         without(base, lambda p: page_of(p) == cont_page)),
        ('ページ境界で割れた選手の2本目を欠落（第54回 %s）' % split_name,
         without(base, lambda p: nishi54('小学生高学年 女子', '予選')(p)
                 and p['athlete_name'] == split_name and p['routine'] == 2)),
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
