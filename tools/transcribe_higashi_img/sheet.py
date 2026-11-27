# -*- coding: utf-8 -*-
"""目で確かめる一覧：選手ごとに、氏名・所属の行の画像と、候補の文字を並べる。"""
import json
import sys

from PIL import Image, ImageDraw, ImageFont

FONT = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 22)
ROW_H = 46


def strip_margin(im):
    # crop() で足した白い余白を外す
    bbox = Image.eval(im, lambda v: 255 - v).getbbox()
    return im.crop(bbox) if bbox else im


def fit(im, h):
    im = strip_margin(im)
    return im.resize((max(1, int(im.width * h / im.height)), h))


def make(rows, path, keyfn):
    W = 1900
    blocks = []
    for r in rows:
        ims = [fit(Image.open('crops/' + c).convert('L'), 34) for c in r['crops']]
        blocks.append((r, ims))
    H = sum(ROW_H * max(1, len(ims)) + 10 for _, ims in blocks) + 10
    sheet = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(sheet)
    y = 5
    for r, ims in blocks:
        d.text((5, y + 6), keyfn(r), fill='black', font=FONT)
        yy = y
        for k, im in enumerate(ims):
            sheet.paste(im.convert('RGB'), (130, yy + 4))
            yy += ROW_H
        d.text((1000, y + 6), '氏名: ' + (r.get('name') or '?'), fill='blue', font=FONT)
        d.text((1000, y + 6 + ROW_H), '所属: ' + r['club'], fill='darkgreen', font=FONT)
        y += ROW_H * max(2, len(ims)) + 10
        d.line([(0, y - 5), (W, y - 5)], fill=(200, 200, 200))
    sheet = sheet.crop((0, 0, W, y + 5))
    sheet.save(path)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    rows = json.load(open(sys.argv[1], encoding='utf-8'))
    per = int(sys.argv[3])
    for k in range(0, len(rows), per):
        make(rows[k:k + per], '%s_%02d.png' % (sys.argv[2], k // per), lambda r: '%d' % r['_i'])
    print((len(rows) + per - 1) // per)
