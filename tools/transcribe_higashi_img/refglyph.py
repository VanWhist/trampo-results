# -*- coding: utf-8 -*-
"""取り違えやすい字（凛/凜 など）を、同じ書体（M PLUS 1p）の文字のPDFにある実物の字と重ねて比べる。

参照：東日本の文字のPDF（etl/higashinihon_files.json の files）から、対象の字の位置を取り、
その範囲を画像にする。比べる側：画像のPDFの氏名の行から、字の位置を順番で切り出す。
どちらも字の外接矩形に合わせて 64×64 に伸ばし、IoU を出す。"""
import json
import logging
import os
import sys

logging.disable(logging.CRITICAL)
import numpy as np
import pdfplumber
import pypdfium2
from PIL import Image, ImageFilter

import files
import lay
import meta

RAW = files.RAW
S = 8


def norm(img):
    a = np.array(img.convert('L')) < 128
    ys, xs = np.nonzero(a)
    if len(ys) == 0:
        return None
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    im = Image.fromarray((a * 255).astype('uint8')).resize((64, 64)).filter(ImageFilter.MaxFilter(5))
    return np.array(im) > 127


def iou(a, b):
    return float((a & b).sum() / max(1, (a | b).sum()))


def refs(chars):
    m = json.load(open(files.REPO + '/etl/higashinihon_files.json', encoding='utf-8'))['meets']
    out = {c: [] for c in chars}
    for meet in m:
        for f in meet['files']:
            path = RAW + meet['raw_dir'] + '/' + f
            if not os.path.exists(path):
                continue
            doc = None
            with pdfplumber.open(path) as pdf:
                for pno, page in enumerate(pdf.pages):
                    hits = [c for c in page.chars if c['text'] in chars and 'MPLUS' in c['fontname']]
                    if not hits:
                        continue
                    doc = doc or pypdfium2.PdfDocument(path)
                    img = doc[pno].render(scale=S).to_pil()
                    for c in hits:
                        if len(out[c['text']]) >= 3:
                            continue
                        g = norm(img.crop((int(c['x0'] * S), int(c['top'] * S), int(c['x1'] * S), int(c['bottom'] * S))))
                        if g is not None:
                            out[c['text']].append((f, g))
    return out


def target_glyphs(fname, band, page_idx=0):
    """画像のPDFの帯の氏名の行の字（横に重なる部品のまとまり。偏と旁が離れる字は分かれる）を返す。"""
    path = dict((f, p) for _, f, p in files.image_files())[fname]
    with pdfplumber.open(path) as pdf:
        L = lay.file_layout(pdf, meta.META[fname][2] == '予選')
        b = L['bands'][band]
        ln = b['text'][0]
        doc = pypdfium2.PdfDocument(path)
        img = doc[b['page'] - 1].render(scale=S).to_pil()
    return img, ln


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    pairs = sys.argv[1]                       # 例 "凛凜"
    R = refs(set(pairs))
    print({c: len(v) for c, v in R.items()})
    m = json.load(open('matched.json', encoding='utf-8'))
    for spec in sys.argv[2:]:                 # i:x0:x1  （氏名の行の中で比べる字の範囲、pt）
        i, x0, x1 = spec.split(':')
        r = m[int(i)]
        img, ln = target_glyphs(r['file'], r['band'])
        g = norm(img.crop((int(float(x0) * S), int((ln['top'] - 0.5) * S), int(float(x1) * S), int((ln['bottom'] + 0.5) * S))))
        print(i, {c: [round(iou(g, rg), 3) for _, rg in v] for c, v in R.items()})
