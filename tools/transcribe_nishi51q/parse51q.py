# -*- coding: utf-8 -*-
"""試作：第51回西日本 予選PDF（文字が図形の輪郭）を読む。

数値：字の形を digits51.pkl の見本と IoU で照らし、見本ごとに人が見て決めた文字（LABELS）を当てる。
氏名・所属：語ごとに画像を切り出す（文字は Windows の文字読み取りで別に読む）。
検算：E+D+H+Time=Total、Total(1本目)+Total(2本目)=Score、E=2×技の数−(S の合計+L)/10。
"""
import collections
import json
import logging
import os
import pickle
import sys

logging.disable(logging.CRITICAL)
import numpy as np
import pdfplumber
import pypdfium2

import glyph51 as G
from digits51 import iou, raster

# 見本 #0〜#51 を画像で見て決めた文字（digits51_sheet.png）
LABELS = '241307.98.' '6853509658' '2.074.8DNS' '6S08961537' '4942357DNS' 'S4'
SCALE = 4


def classify(g, reps):
    img = raster(g)
    h = g['bottom'] - g['top']
    best, bk, second = 0, None, 0
    for k, r in enumerate(reps):
        if abs(r['h'] - h) > 1.0:
            continue
        s = iou(r['img'], img)
        if s > best:
            best, second, bk = s, best, k
        elif s > second:
            second = s
    if bk is None or best < 0.8:
        return None, best
    return LABELS[bk], best


def read(pdf_path, reps, crop_dir):
    os.makedirs(crop_dir, exist_ok=True)
    doc = pypdfium2.PdfDocument(pdf_path)
    out, low = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            lay = G.page_layout(page)
            if lay is None:
                continue
            img = doc[pno - 1].render(scale=SCALE).to_pil().convert('L')
            cols = lay['cols']
            first_num = cols['S1'] - 8
            for bi, b in enumerate(lay['bands']):
                rec = {'page': pno, 'band': bi, 'text': [], 'rows': []}
                for half in ('a', 'b'):
                    vals = collections.defaultdict(str)
                    for wi, w in enumerate(b[half]):
                        if w['x0'] < first_num:
                            if half == 'b':
                                rec.setdefault('text_b', []).append(w)
                                continue
                            # 文字の語：画像を切り出す
                            name = 'p%02d_b%02d_w%02d.png' % (pno, bi, wi)
                            pad = 1.0
                            img.crop((int((w['x0'] - pad) * SCALE), int((w['top'] - pad) * SCALE),
                                      int((w['x1'] + pad) * SCALE), int((w['bottom'] + pad) * SCALE))).save(
                                os.path.join(crop_dir, name))
                            rec['text'].append({'x0': w['x0'], 'x1': w['x1'], 'file': name, 'n': len(w['gs'])})
                            continue
                        center = (w['x0'] + w['x1']) / 2
                        col = min(cols, key=lambda k: abs(cols[k] - center))
                        s = ''
                        for g in w['gs']:
                            ch, sc = classify(g, reps)
                            if ch is None:
                                low.append((pno, bi, half, col, sc))
                                ch = '?'
                            s += ch
                        vals[col] += s
                    if vals:
                        rec['rows'].append(dict(vals))
                out.append(rec)
    return out, low


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    reps = pickle.load(open(sys.argv[2], 'rb'))['reps']
    out, low = read(sys.argv[1], reps, sys.argv[4])
    json.dump(out, open(sys.argv[3], 'w', encoding='utf-8'), ensure_ascii=False, default=str)
    print('帯', len(out), '形が見本に合わない字', len(low), low[:10])
