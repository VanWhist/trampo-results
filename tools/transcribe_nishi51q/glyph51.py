# -*- coding: utf-8 -*-
"""試作：第51回西日本 予選PDF（文字が図形の輪郭）を、表の帯・行・語・字に分ける。

  帯   ：表の横罫線（幅 300pt 超の rect）のあいだ＝選手1人
  行   ：帯の上半分（順位・氏名・所属・1本目の値・予選の値）と下半分（2本目の値）
  字   ：輪郭を x 順に並べ、横に重なるものを同じ字にする（数字の穴は外側の輪郭に含まれる）
  語   ：字のすき間が GAP を超えたら別の語
列名の行（最初の罫線の上）の語を S1 S2 … Score に順に対応させ、数値の語を列に割り当てる。
"""
import collections
import json
import logging
import sys

logging.disable(logging.CRITICAL)
import pdfplumber

GAP = 1.6
HEADERS = ['S%d' % i for i in range(1, 11)] + ['L', 'E', 'D', 'H', 'Time', 'Total', 'Score']


def contours(page):
    out = []
    for c in page.curves:
        if not c.get('fill'):
            continue
        out.append({'x0': c['x0'], 'x1': c['x1'], 'top': c['top'], 'bottom': c['bottom'],
                    'pts': [(x, y) for x, y in c['pts']], 'color': tuple(c['non_stroking_color'] or ())})
    return out


def glyphs(cs):
    cs = sorted(cs, key=lambda c: (c['x0'], c['top']))
    gs = []
    for c in cs:
        if gs and c['x0'] < gs[-1]['x1'] - 0.05:
            g = gs[-1]
            g['cs'].append(c)
            g['x1'] = max(g['x1'], c['x1'])
            g['top'] = min(g['top'], c['top'])
            g['bottom'] = max(g['bottom'], c['bottom'])
        else:
            gs.append({'x0': c['x0'], 'x1': c['x1'], 'top': c['top'], 'bottom': c['bottom'], 'cs': [c]})
    return gs


def words(gs, gap=GAP):
    ws = []
    for g in gs:
        if ws and g['x0'] - ws[-1]['x1'] <= gap:
            w = ws[-1]
            w['gs'].append(g)
            w['x1'] = max(w['x1'], g['x1'])
            w['top'] = min(w['top'], g['top'])
            w['bottom'] = max(w['bottom'], g['bottom'])
        else:
            ws.append({'x0': g['x0'], 'x1': g['x1'], 'top': g['top'], 'bottom': g['bottom'], 'gs': [g]})
    return ws


def page_layout(page):
    rules = sorted({round(r['top'], 2) for r in page.rects if r['width'] > 300})
    cs = contours(page)
    if len(rules) < 2:
        return None
    # 列名の行：最初の罫線のすぐ上（12pt 以内）にある輪郭
    head = [c for c in cs if rules[0] - 12 < (c['top'] + c['bottom']) / 2 < rules[0]]
    hw = words(glyphs(head), gap=4.0)        # 列名は字間が広い（「T ime」）
    if len(rules) < 2 or len(hw) < len(HEADERS):
        return None                                   # 白紙のページなど
    hw = hw[-len(HEADERS):]                           # 列名の行は S1〜Score だけ（ページで位置が違う）
    if len(hw) != len(HEADERS):
        raise ValueError('列名の語の数が %d（%d のはず）' % (len(hw), len(HEADERS)))
    cols = {h: (w['x0'] + w['x1']) / 2 for h, w in zip(HEADERS, hw)}
    bands = []
    for k in range(len(rules) - 1):
        top, bot = rules[k], rules[k + 1]
        mid = (top + bot) / 2
        inside = [c for c in cs if top < (c['top'] + c['bottom']) / 2 < bot]
        upper = [c for c in inside if (c['top'] + c['bottom']) / 2 < mid]
        lower = [c for c in inside if (c['top'] + c['bottom']) / 2 >= mid]
        bands.append({'top': top, 'bot': bot, 'a': words(glyphs(upper)), 'b': words(glyphs(lower))})
    # 表の最後の行の下には罫線が無い。最後の罫線より下（下端の注記より上）に字があれば、帯を1つ足す
    h = rules[1] - rules[0]
    top = rules[-1]
    rest = [c for c in cs if c['top'] > top + 0.5 and c['bottom'] < 490]
    if rest:
        bot = top + h
        if max(c['bottom'] for c in rest) > bot:
            raise ValueError('最後の罫線の下の字が帯1つ分に収まらない')
        mid = (top + bot) / 2
        upper = [c for c in rest if (c['top'] + c['bottom']) / 2 < mid]
        lower = [c for c in rest if (c['top'] + c['bottom']) / 2 >= mid]
        bands.append({'top': top, 'bot': bot, 'a': words(glyphs(upper)), 'b': words(glyphs(lower))})
    return {'cols': cols, 'bands': bands, 'rules': rules}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    with pdfplumber.open(sys.argv[1]) as pdf:
        lay = page_layout(pdf.pages[int(sys.argv[2]) - 1])
    print({k: round(v, 1) for k, v in lay['cols'].items()})
    for b in lay['bands'][:4]:
        print('a', [(round(w['x0'], 1), len(w['gs'])) for w in b['a']])
        print('b', [(round(w['x0'], 1), len(w['gs'])) for w in b['b']])
