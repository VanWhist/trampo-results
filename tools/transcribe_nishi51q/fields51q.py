# -*- coding: utf-8 -*-
"""試作：氏名欄（姓＋名）と所属欄を、選手ごとに1枚ずつ切り出す。列の位置はページごとに語の左端の
分布から決める（帯の半数以上に現れる位置を列とし、右から3つを 姓・名・所属 とする）。"""
import collections
import json
import logging
import os
import sys

logging.disable(logging.CRITICAL)
import pdfplumber
import pypdfium2

import glyph51 as G

SCALE = 6


def main(pdf_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    doc = pypdfium2.PdfDocument(pdf_path)
    meta = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            lay = G.page_layout(page)
            if lay is None:
                continue
            first_num = lay['cols']['S1'] - 8
            bands = [[w for w in b['a'] if w['x0'] < first_num] for b in lay['bands']]
            # 列の位置は2種類（S1 が 351pt のページと 313pt のページ）。どちらも 氏名＝80〜140pt、所属＝140pt〜
            sur, club = 80, 140
            img = doc[pno - 1].render(scale=SCALE).to_pil().convert('L')
            for bi, ws in enumerate(bands):
                # 所属の列はページの書式で決まる（S1 が 351pt の書式は 167pt、313pt の書式は 148pt から）
                club_x = 160 if lay['cols']['S1'] > 340 else 142
                rank_ws = [w for w in ws if w['x0'] < sur]
                name_ws = [w for w in ws if sur <= w['x0'] < club_x]
                club_ws = [w for w in ws if w['x0'] >= club_x]
                rec = {'page': pno, 'band': bi, 'n_rank_words': len(rank_ws)}
                for key, group in (('name', name_ws), ('club', club_ws), ('line', rank_ws + name_ws + club_ws)):
                    if not group:
                        rec[key] = None
                        continue
                    x0 = min(w['x0'] for w in group) - 2
                    x1 = max(w['x1'] for w in group) + 2
                    y0 = min(w['top'] for w in group) - 2
                    y1 = max(w['bottom'] for w in group) + 2
                    fn = 'p%02d_b%02d_%s.png' % (pno, bi, key)
                    img.crop((int(x0 * SCALE), int(y0 * SCALE), int(x1 * SCALE), int(y1 * SCALE))).save(
                        os.path.join(out_dir, fn))
                    rec[key] = fn
                    rec[key + '_gap'] = [round(b['x0'] - a['x1'], 1) for a, b in zip(group, group[1:])]
                meta.append(rec)
    json.dump(meta, open(os.path.join(out_dir, '_fields.json'), 'w', encoding='utf-8'))
    print(len(meta))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
