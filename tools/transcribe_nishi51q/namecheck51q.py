# -*- coding: utf-8 -*-
"""検算：書き起こした氏名（姓・名）をメイリオで描き、PDF の氏名の図形と重ねて一致の度合いを見る。

姓と名を別々に、字の範囲（外接矩形）をそろえて 64px の高さに伸ばし、重なり（IoU）を出す。
字形の取り違え（昂/昴、凛/凜、齊/齋 など）は、同じ形の字を描いた場合より重なりが下がる。"""
import csv
import json
import logging
import sys

logging.disable(logging.CRITICAL)
import numpy as np
import pdfplumber
from PIL import Image, ImageDraw, ImageFont

import glyph51 as G

FONT = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 160)
H = 64


def fit(arr):
    ys, xs = np.nonzero(arr)
    if len(ys) == 0:
        return None
    return arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def to_box(arr, w):
    return np.array(Image.fromarray((arr * 255).astype('uint8')).resize((w, H))) > 127


def pdf_word(ws):
    x0 = min(w['x0'] for w in ws); x1 = max(w['x1'] for w in ws)
    t = min(w['top'] for w in ws); b = max(w['bottom'] for w in ws)
    s = 24
    W, Hh = int((x1 - x0) * s) + 4, int((b - t) * s) + 4
    acc = np.zeros((Hh, W), bool)
    for w in ws:
        for g in w['gs']:
            for c in g['cs']:
                m = Image.new('L', (W, Hh), 0)
                ImageDraw.Draw(m).polygon([((x - x0) * s + 2, (y - t) * s + 2) for x, y in c['pts']], fill=1)
                acc ^= np.array(m, bool)
    return fit(acc)


def font_word(text):
    im = Image.new('L', (200 * max(1, len(text)) + 100, 260), 0)
    ImageDraw.Draw(im).text((20, 10), text, font=FONT, fill=255)
    return fit(np.array(im) > 127)


def score(pdf_arr, text):
    f = font_word(text)
    if pdf_arr is None or f is None:
        return 0.0
    w = max(8, int(round(pdf_arr.shape[1] / pdf_arr.shape[0] * H)))
    a, b = to_box(pdf_arr, w), to_box(f, w)
    return float((a & b).sum() / max(1, (a | b).sum()))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    pdf_path, assembled, out = sys.argv[1], sys.argv[2], sys.argv[3]
    names = {(r['page'], r['band']): r['name'] for r in json.load(open(assembled, encoding='utf-8'))}
    res = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            lay = G.page_layout(page)
            if lay is None:
                continue
            club_x = 160 if lay['cols']['S1'] > 340 else 142
            for bi, b in enumerate(lay['bands']):
                n = names.get((pno, bi))
                if not n:
                    continue
                ws = [w for w in b['a'] if 80 <= w['x0'] < lay['cols']['S1'] - 8]
                groups = []
                for w in ws:
                    if groups and w['x0'] - groups[-1][-1]['x1'] < 6:
                        groups[-1].append(w)
                    else:
                        groups.append([w])
                parts = n.split(' ')
                if len(parts) != 2 or len(groups) < 2:
                    res.append((pno, bi, n, None, None))
                    continue
                # 姓＝1つ目のまとまり、名＝2つ目のまとまり（所属は3つ目以降）
                s1 = score(pdf_word(groups[0]), parts[0])
                s2 = score(pdf_word(groups[1]), parts[1])
                res.append((pno, bi, n, round(s1, 3), None if s2 is None else round(s2, 3)))
    json.dump(res, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    vals = [min(x for x in r[3:] if x is not None) for r in res if r[3] is not None]
    print('人数', len(res), '最小', min(vals), '分布', np.percentile(vals, [1, 5, 25, 50]))
    for r in sorted(res, key=lambda r: min([x for x in r[3:] if x is not None] or [0]))[:30]:
        print(r)
