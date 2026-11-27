# -*- coding: utf-8 -*-
"""試作：数値の列の字（数字・小数点）を全ページから集め、形の重なり（IoU）でまとめて、
まとまりごとの見本を1枚の画像に並べる。"""
import json
import logging
import pickle
import sys

logging.disable(logging.CRITICAL)
import numpy as np
import pdfplumber
from PIL import Image, ImageDraw, ImageFont

import glyph51 as G

PX = 8          # 1pt あたりの画素
W, H = 64, 96   # 字の画像の大きさ（左下を字の左端・下端にそろえる）


def raster(g):
    img = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(img)
    # 偶奇則で塗る：輪郭ごとに XOR
    acc = np.zeros((H, W), dtype=bool)
    for c in g['cs']:
        m = Image.new('L', (W, H), 0)
        ImageDraw.Draw(m).polygon([((x - g['x0']) * PX, H - 1 - (g['bottom'] - y) * PX) for x, y in c['pts']], fill=1)
        acc ^= np.array(m, dtype=bool)
    return acc


def iou(a, b):
    u = np.logical_or(a, b).sum()
    return np.logical_and(a, b).sum() / u if u else 1.0


def collect(pdf_path):
    items = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            lay = G.page_layout(page)
            if lay is None:
                continue
            first_num = lay['cols']['S1'] - 8
            for bi, b in enumerate(lay['bands']):
                for half in ('a', 'b'):
                    for wi, w in enumerate(b[half]):
                        if w['x0'] < first_num:
                            continue
                        for gi, g in enumerate(w['gs']):
                            items.append({'page': pno, 'band': bi, 'half': half, 'word': wi, 'glyph': gi,
                                          'w': g['x1'] - g['x0'], 'h': g['bottom'] - g['top'],
                                          'img': raster(g)})
    return items


def cluster(items, thr=0.8):
    reps = []
    for it in items:
        best, bi = 0, None
        for k, r in enumerate(reps):
            if abs(r['h'] - it['h']) > 1.0:
                continue
            s = iou(r['img'], it['img'])
            if s > best:
                best, bi = s, k
        if bi is not None and best >= thr:
            it['cl'] = bi
            reps[bi]['n'] += 1
            it['score'] = best
        else:
            it['cl'] = len(reps)
            it['score'] = 1.0
            reps.append({'img': it['img'], 'h': it['h'], 'n': 1})
    return reps


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    items = collect(sys.argv[1])
    reps = cluster(items)
    print('字', len(items), 'まとまり', len(reps), [r['n'] for r in reps])
    pickle.dump({'items': items, 'reps': reps}, open(sys.argv[2], 'wb'))
    # 見本の一覧
    cols = 10
    rows = (len(reps) + cols - 1) // cols
    sheet = Image.new('L', (cols * (W + 40), rows * (H + 30)), 255)
    dr = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 18)
    except OSError:
        font = None
    for k, r in enumerate(reps):
        x, y = (k % cols) * (W + 40), (k // cols) * (H + 30)
        sheet.paste(Image.fromarray(np.where(r['img'], 0, 255).astype('uint8')), (x + 20, y + 24))
        dr.text((x + 4, y + 2), '#%d (%d)' % (k, r['n']), fill=0, font=font)
    sheet.save(sys.argv[3])
