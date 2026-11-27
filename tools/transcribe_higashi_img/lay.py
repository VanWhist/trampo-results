# -*- coding: utf-8 -*-
"""東日本の「Microsoft Print To PDF」で出力された結果表（文字がすべて図形の輪郭）を、
選手ごとの帯 → 区域（順位・文字・予選の印・数値）→ 行 → 字 → 語 に分ける。

  部品 ：塗りつぶしの輪郭（curves）と、表の罫線でない小さな四角（rects。小数点・漢字の画の一部）
  帯   ：表の横罫線（幅 300pt 超の rect）のあいだ＝選手1人
  列   ：1ページ目の列名の行（小さな画像）を語にまとめた 21 語の中心。ファイル内の全ページに使う
  行   ：区域ごとに、部品の上下の範囲が重なるものをまとめる
  字   ：行の中で、横に重なる部品を同じ字にする
"""
import logging
import statistics

logging.disable(logging.CRITICAL)

COLS = ['Rank', 'Name'] + ['S%d' % i for i in range(1, 11)] + \
       ['L', 'A', 'Exe', 'Diff', 'ToF', 'HD', 'Pen', 'Score', 'Agg']
NUM_COLS = COLS[2:]


def header_cols(page):
    ims = sorted([i for i in page.images if 100 < i['top'] < 140], key=lambda i: i['x0'])
    ws = []
    for i in ims:
        if ws and i['x0'] - ws[-1][1] < 3.0:
            ws[-1][1] = max(ws[-1][1], i['x1'])
        else:
            ws.append([i['x0'], i['x1']])
    if len(ws) != len(COLS):
        raise ValueError('列名の語が %d（21 のはず）' % len(ws))
    return {k: (a + b) / 2 for k, (a, b) in zip(COLS, ws)}, max(i['bottom'] for i in ims)


def pieces(page):
    out = []
    for c in page.curves:
        if c.get('fill'):
            out.append({'x0': c['x0'], 'x1': c['x1'], 'top': c['top'], 'bottom': c['bottom'],
                        'pts': [(x, y) for x, y in c['pts']]})
    for r in page.rects:
        if r['width'] <= 300 and r.get('fill'):
            x0, x1, t, b = r['x0'], r['x1'], r['top'], r['bottom']
            out.append({'x0': x0, 'x1': x1, 'top': t, 'bottom': b,
                        'pts': [(x0, t), (x1, t), (x1, b), (x0, b)]})
    return out


def lines(ps):
    """上下の範囲が重なる部品を1行にまとめる。"""
    ps = sorted(ps, key=lambda p: p['top'])
    ls = []
    for p in ps:
        if ls and p['top'] < ls[-1]['bottom'] - 0.3:
            ls[-1]['ps'].append(p)
            ls[-1]['bottom'] = max(ls[-1]['bottom'], p['bottom'])
        else:
            ls.append({'top': p['top'], 'bottom': p['bottom'], 'ps': [p]})
    for ln in ls:
        ln['gs'] = glyphs(ln['ps'])
        ln['x0'] = min(p['x0'] for p in ln['ps'])
        ln['x1'] = max(p['x1'] for p in ln['ps'])
    return ls


def glyphs(ps):
    ps = sorted(ps, key=lambda p: (p['x0'], p['top']))
    gs = []
    for p in ps:
        if gs and p['x0'] < gs[-1]['x1'] - 0.05:
            g = gs[-1]
            g['cs'].append(p)
            g['x1'] = max(g['x1'], p['x1'])
            g['top'] = min(g['top'], p['top'])
            g['bottom'] = max(g['bottom'], p['bottom'])
        else:
            gs.append({'x0': p['x0'], 'x1': p['x1'], 'top': p['top'], 'bottom': p['bottom'], 'cs': [p]})
    return gs


def words(gs, gap):
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


def _split_footer(ps, left, right):
    """右下の「©2023 T-product.All Rights Reserved.」（右寄せの1行。表の右端より右まで出る）を外す。
    返り値 (本体, 外したもの)。"""
    body, foot = [], []
    for ln in lines(ps):
        (foot if ln['x0'] > left and ln['x1'] > right else body).extend(ln['ps'])
    return body, foot


def file_layout(pdf, has_label):
    """ファイル全体を読み、帯のリストと列・尺度を返す。

    帯の上下は横罫線。ページの最後の選手は下の罫線が無いことがある（最後の罫線より下に字がある）。
    選手の途中でページが変わると、次のページの最初の罫線より上に、所属の続きなどが出る
    （順位が無い）。これは前の帯に足す。"""
    cols, head_bottom = header_cols(pdf.pages[0])
    step = (cols['S10'] - cols['S1']) / 9                 # 減点の列の間隔（ファイルごとに印刷の倍率が違う）
    s1 = cols['S1']
    rank_x1 = cols['Rank'] + 7
    num_x = s1 - 0.45 * step
    segs = []                                             # (ページ, 上, 下, 部品, 罫線より上か)
    footers = []
    for pno, page in enumerate(pdf.pages, 1):
        rules = sorted(r['top'] for r in page.rects if r['width'] > 300)
        ps, foot = _split_footer(pieces(page), cols['Exe'], cols['Agg'] + step)
        footers.append((pno, len(foot)))
        top0 = head_bottom + 1 if pno == 1 else 0
        edges = [top0] + rules + [page.height]
        for k in range(len(edges) - 1):
            t, b = edges[k], edges[k + 1]
            inside = [p for p in ps if t < (p['top'] + p['bottom']) / 2 < b]
            if not inside:
                continue
            if pno == len(pdf.pages) and k == len(edges) - 2:
                # 最後のページの最後の罫線より下は、表の外（2023年版の左下「produced by T-product 2023
                # Export CSV」）。表は罫線で閉じている。1行だけであることを確かめて外す
                if len(lines(inside)) != 1:
                    raise ValueError('最後の罫線より下に %d 行ある' % len(lines(inside)))
                footers.append((pno, len(inside)))
                continue
            segs.append((pno, t, b, inside, k == 0))
        if pno == 1:
            above = [p for p in ps if (p['top'] + p['bottom']) / 2 <= top0]
            title = above
    # 予選の印（予選1・予選2）の列：S1 の左に左端がそろう語
    label_x0 = None
    if has_label:
        cand = []
        for _, t, b, inside, _ in segs:
            zone = [p for p in inside if s1 - 2.2 * step < p['x0'] and (p['x0'] + p['x1']) / 2 < num_x]
            for ln in lines(zone):
                cand.append(round(ln['x0'], 0))
        mode = statistics.mode(cand)
        label_x0 = min(c for c in cand if abs(c - mode) <= 1.5)
    text_x1 = (label_x0 - 1.0) if label_x0 is not None else num_x
    bands = []
    for pno, t, b, inside, first in segs:
        rank = [p for p in inside if p['x1'] < rank_x1]
        text = [p for p in inside if p['x1'] >= rank_x1 and p['x1'] <= text_x1 + 0.01
                and (p['x0'] + p['x1']) / 2 < num_x]
        label = [p for p in inside if p['x1'] > text_x1 + 0.01 and (p['x0'] + p['x1']) / 2 < num_x]
        num = [p for p in inside if (p['x0'] + p['x1']) / 2 >= num_x]
        part = {'page': pno, 'top': t, 'bot': b,
                'rank': lines(rank), 'text': lines(text), 'label': lines(label), 'num': lines(num)}
        if first and pno > 1 and not rank:
            if not bands:
                raise ValueError('1ページ目より前に続きの帯')
            bands[-1]['cont'].append(part)                # 前のページの選手の続き
            continue
        part['cont'] = []
        bands.append(part)
    return {'cols': cols, 'step': step, 'label_x0': label_x0, 'text_x1': text_x1,
            'head_bottom': head_bottom, 'bands': bands, 'footers': footers, 'title': title}
