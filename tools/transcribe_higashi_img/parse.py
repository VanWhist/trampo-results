# -*- coding: utf-8 -*-
"""数値を読み、選手ごとの演技にする。氏名・所属の行は画像に切り出す（文字は別に読む）。

数値：字の形を digits.pkl の見本と IoU で照らし、見本ごとに人が見て決めた文字（LABELS）を当てる。
演技の行：予選の印（予選1・予選2）の行に、上下の位置が最も近い数値の行を対応させる。
"""
import json
import os
import pickle
import sys

import pdfplumber
import pypdfium2

import digits as D
import files
import lay
import meta

# 見本 #0〜#44 を digit_shapes.png で見て決めた文字
LABELS = '132407.968' '5006314892' '0005986484' '1290340074' 'DNS50'
SCALE = 6


def classify(g, step, reps):
    img = D.raster(g, step)
    hn = (g['bottom'] - g['top']) * D.REF_STEP / step
    best, bk = 0, None
    for k, r in enumerate(reps):
        if abs(r['hn'] - hn) > 1.0:
            continue
        s = D.iou(r['img'], img)
        if s > best:
            best, bk = s, k
    if bk is None or best < 0.8:
        return '?', best
    return LABELS[bk], best


def read_line(ln, step, reps, low, where):
    ws = lay.words(ln['gs'], gap=0.25 * step)
    out = []
    for w in ws:
        s = ''
        for g in w['gs']:
            ch, sc = classify(g, step, reps)
            if ch == '?':
                low.append((where, round(sc, 3)))
            s += ch
        out.append({'x0': w['x0'], 'x1': w['x1'], 'c': (w['x0'] + w['x1']) / 2, 't': s})
    return out


def crop(img, ln, path, pad=1.5, margin=60):
    """行を切り出し、周りに白い余白を足す（余白が無いと文字読み取りが端の字を落とす）。"""
    from PIL import Image
    c = img.crop((int((ln['x0'] - pad) * SCALE), int((ln['top'] - pad) * SCALE),
                  int((ln['x1'] + pad) * SCALE), int((ln['bottom'] + pad) * SCALE)))
    out = Image.new('L', (c.width + 2 * margin, c.height + 2 * margin), 255)
    out.paste(c, (margin, margin))
    out.save(path)


def parse_file(meet, fname, path, reps, crop_dir):
    cls, sex, rnd = meta.META[fname]
    doc = pypdfium2.PdfDocument(path)
    with pdfplumber.open(path) as pdf:
        L = lay.file_layout(pdf, rnd == '予選')
    cols, step = L['cols'], L['step']
    numcols = {k: v for k, v in cols.items() if k in lay.NUM_COLS}
    imgs = {}
    low, issues, out = [], [], []
    stem = '%s__%s' % (meet, os.path.splitext(fname)[0])
    for bi, b in enumerate(L['bands']):
        rec = {'band': bi, 'page': b['page'], 'rank': None, 'routines': [], 'text': [], 'agg': None}
        rk = [w['t'] for ln in b['rank'] for w in read_line(ln, step, reps, low, (fname, bi, 'rank'))]
        rec['rank'] = ''.join(rk)
        routines = []
        for part in [b] + b['cont']:
            pg = part['page']
            if pg not in imgs:
                imgs[pg] = doc[pg - 1].render(scale=SCALE).to_pil().convert('L')
            for li, ln in enumerate(part['text']):
                fn = '%s__b%03d_p%d_t%d.png' % (stem, bi, pg, li)
                crop(imgs[pg], ln, os.path.join(crop_dir, fn))
                rec['text'].append({'file': fn, 'page': pg, 'top': ln['top'], 'x0': ln['x0'], 'x1': ln['x1']})
            labels = sorted(part['label'], key=lambda l: l['top'])
            for li, ln in enumerate(part['num']):
                vals = {}
                for w in read_line(ln, step, reps, low, (fname, bi, 'num')):
                    k = min(numcols, key=lambda c: abs(numcols[c] - w['c']))
                    tol = 0.35 * step if k.startswith('S') or k in ('L', 'A') else 0.6 * step
                    if abs(numcols[k] - w['c']) > tol:
                        issues.append((fname, bi, '列の中心から離れた語', w['t'], round(w['c'] - numcols[k], 1)))
                    if k in vals:
                        issues.append((fname, bi, '同じ列に2語', k, vals[k], w['t']))
                    vals[k] = w['t']
                mid = (ln['top'] + ln['bottom']) / 2
                if labels:
                    lab = min(range(len(labels)), key=lambda i: abs((labels[i]['top'] + labels[i]['bottom']) / 2 - mid))
                    off = abs((labels[lab]['top'] + labels[lab]['bottom']) / 2 - mid)
                    if off > 3:
                        issues.append((fname, bi, '予選の印と数値の行がずれる', round(off, 1)))
                else:
                    lab = None
                routines.append({'page': pg, 'label_idx': lab, 'n_labels': len(labels), 'top': ln['top'], 'vals': vals})
            rec.setdefault('n_labels', 0)
            rec['n_labels'] += len(labels)
        rec['routines'] = routines
        out.append(rec)
    return {'meet': meet, 'file': fname, 'category': cls, 'sex': sex, 'round': rnd,
            'cols': list(numcols), 'bands': out}, low, issues


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    reps = pickle.load(open('digits.pkl', 'rb'))['reps']
    crop_dir = 'crops'
    os.makedirs(crop_dir, exist_ok=True)
    res, all_low, all_issues = [], [], []
    for meet, f, path in files.image_files():
        r, low, issues = parse_file(meet, f, path, reps, crop_dir)
        res.append(r)
        all_low += low
        all_issues += issues
    json.dump(res, open('parsed.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print('形が見本に合わない字', len(all_low), all_low[:10])
    print('問題', len(all_issues))
    for i in all_issues[:40]:
        print('  ', i)
