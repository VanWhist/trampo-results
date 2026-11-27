# -*- coding: utf-8 -*-
"""検算（相対）：読んだ氏名と、取り違えやすい字に置き換えた候補・既存の1字違いの選手名を、同じ条件で
メイリオで描いて PDF の図形と重ね、候補の方がよく重なるものを洗い出す。"""
import glob, json, logging, sys, collections
logging.disable(logging.CRITICAL)
import pdfplumber
import glyph51 as G
from namecheck51q import pdf_word, score
sys.stdout.reconfigure(encoding='utf-8')
PDF, ASM, REPO = sys.argv[1], sys.argv[2], sys.argv[3]
SWAP = ['凛凜', '昂昴', '齊齋斉斎', '邉邊辺', '澤沢', '嶋島', '﨑崎', '髙高', '宗崇', '眞真', '櫻桜', '濱浜',
        '國国', '廣広', '瀨瀬', '德徳', '惠恵', '祐裕', '萌萠', '琉瑠', '晃晄', '颯飒', '莉梨', '奈菜', '希稀',
        '綾彩', '遥遙', '優憂', '結絃', '大太', '己巳已', '未末', '土士', '日曰', '侑佑', '悠攸', '凪風', '咲笑',
        '紗沙', '彩採', '陽暘', '翔翊', '愛受', '花苑', '亜亞', '菜采']
alt_of = collections.defaultdict(set)
for grp in SWAP:
    for c in grp:
        alt_of[c] |= set(grp) - {c}
names = set()
for f in glob.glob(REPO + '/data/performances/*.json'):
    if '-other' in f:
        continue
    for r in json.load(open(f, encoding='utf-8')):
        if r.get('athlete_id') and '/' not in (r['athlete_name'] or ''):
            names.add(r['athlete_name'])
by_len = collections.defaultdict(list)
for n in names:
    by_len[len(n)].append(n)
def near(n):
    out = set()
    for m in by_len[len(n)]:
        if m != n and sum(a != b for a, b in zip(m, n)) == 1:
            out.add(m)
    for i, c in enumerate(n):
        for a in alt_of.get(c, ()):
            out.add(n[:i] + a + n[i + 1:])
    return out
asm = json.load(open(ASM, encoding='utf-8'))
want = {(r['page'], r['band']): r['name'] for r in asm}
flag = []
with pdfplumber.open(PDF) as pdf:
    for pno, page in enumerate(pdf.pages, 1):
        lay = G.page_layout(page)
        if lay is None:
            continue
        for bi, b in enumerate(lay['bands']):
            n = want.get((pno, bi))
            if not n or ' ' not in n:
                continue
            ws = [w for w in b['a'] if 80 <= w['x0'] < lay['cols']['S1'] - 8]
            groups = []
            for w in ws:
                if groups and w['x0'] - groups[-1][-1]['x1'] < 6:
                    groups[-1].append(w)
                else:
                    groups.append([w])
            if len(groups) < 2:
                continue
            sur, giv = n.split(' ', 1)
            arrs = (pdf_word(groups[0]), pdf_word(groups[1]))
            base = (score(arrs[0], sur), score(arrs[1], giv))
            for m in near(n):
                if ' ' not in m:
                    continue
                s2, g2 = m.split(' ', 1)
                for k, (cur, alt) in enumerate(((sur, s2), (giv, g2))):
                    if cur == alt:
                        continue
                    sc = score(arrs[k], alt)
                    if sc > base[k] + 0.01:
                        flag.append((pno, bi, n, m, round(base[k], 3), round(sc, 3)))
for f in flag:
    print(f)
print('候補の方がよく重なる', len(flag))
