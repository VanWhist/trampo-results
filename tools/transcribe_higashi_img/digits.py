# -*- coding: utf-8 -*-
"""数値（順位・減点・点数の列）の字を全ファイルから集め、形の重なり（IoU）でまとめて、
まとまりごとの見本を1枚の画像に並べる。字の大きさはファイルごとの列の間隔でそろえる。"""
import pickle
import sys

import numpy as np
import pdfplumber
from PIL import Image, ImageDraw, ImageFont

import files
import lay
import meta

REF_STEP = 22.0
PX0 = 8.0
W, H = 64, 96


def raster(g, step):
    px = PX0 * REF_STEP / step
    acc = np.zeros((H, W), dtype=bool)
    for c in g['cs']:
        m = Image.new('L', (W, H), 0)
        ImageDraw.Draw(m).polygon([((x - g['x0']) * px, H - 1 - (g['bottom'] - y) * px) for x, y in c['pts']], fill=1)
        acc ^= np.array(m, dtype=bool)
    return acc


def iou(a, b):
    u = np.logical_or(a, b).sum()
    return np.logical_and(a, b).sum() / u if u else 1.0


def all_layouts():
    out = []
    for meet, f, path in files.image_files():
        with pdfplumber.open(path) as pdf:
            out.append((meet, f, lay.file_layout(pdf, meta.META[f][2] == '予選')))
    return out


def number_glyphs(L):
    """(帯番号, 区域, 行, 字) を順に返す。続きのページの部分も含む。"""
    for bi, b in enumerate(L['bands']):
        for part in [b] + b['cont']:
            for zone in ('rank', 'num'):
                for li, ln in enumerate(part[zone]):
                    for gi, g in enumerate(ln['gs']):
                        yield bi, part['page'], zone, li, gi, g


def cluster(items, thr=0.8):
    reps = []
    for it in items:
        best, bk = 0, None
        for k, r in enumerate(reps):
            if abs(r['hn'] - it['hn']) > 1.0:
                continue
            s = iou(r['img'], it['img'])
            if s > best:
                best, bk = s, k
        if bk is not None and best >= thr:
            it['cl'] = bk
            reps[bk]['n'] += 1
        else:
            it['cl'] = len(reps)
            reps.append({'img': it['img'], 'hn': it['hn'], 'n': 1, 'ex': (it['file'], it['band'])})
    return reps


def sheet(reps, path):
    cols = 10
    rows = (len(reps) + cols - 1) // cols
    img = Image.new('L', (cols * (W + 40), rows * (H + 30)), 255)
    dr = ImageDraw.Draw(img)
    font = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 18)
    for k, r in enumerate(reps):
        x, y = (k % cols) * (W + 40), (k // cols) * (H + 30)
        img.paste(Image.fromarray(np.where(r['img'], 0, 255).astype('uint8')), (x + 20, y + 24))
        dr.text((x + 4, y + 2), '#%d (%d)' % (k, r['n']), fill=0, font=font)
    img.save(path)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    layouts = all_layouts()
    items = []
    for meet, f, L in layouts:
        for bi, page, zone, li, gi, g in number_glyphs(L):
            items.append({'file': f, 'band': bi, 'zone': zone, 'line': li, 'glyph': gi,
                          'hn': (g['bottom'] - g['top']) * REF_STEP / L['step'],
                          'img': raster(g, L['step'])})
    reps = cluster(items)
    print('字', len(items), 'まとまり', len(reps), [r['n'] for r in reps])
    pickle.dump({'reps': reps}, open('digits.pkl', 'wb'))
    sheet(reps, 'digit_shapes.png')
