# -*- coding: utf-8 -*-
"""文字コードの対応が無い PDF（西日本 第47回・第51回決勝）の字の対応表を作る。

これらの PDF は日本語の字を埋め込みフォントの字形番号（CID）だけで持っていて、
ToUnicode（字形番号→文字）の表が無い。そのままでは文字として取り出せない。

ここでは OCR は使わない。PDF に埋め込まれた字形の輪郭（座標・フラグ・輪郭の区切り）が、
Windows に入っている同じ書体の字形の輪郭と**完全に一致する**ものを探して、文字を決める。

  1) 同じ字形番号の字形が、輪郭まで一致する → その字形の文字
  2) 番号は違うが、輪郭が完全に一致する字形がある → その字形の文字
  3) どちらも無い → 止める（推測で埋めない）

輪郭の無い字形（空白）は ' ' にする。1つの字形に複数の文字コードがある（互換漢字など）ときは
統合漢字を選ぶ。

作った表は etl/nishinihon_cid_maps.json に置く。ETL と独立照合はこの表を読む
（PC の書体が無くても作り直せるようにするため）。PDF の SHA-256 も記録し、PDF が
差し替わったら ETL が止まるようにしている。

    python tools/build_cid_maps.py          # 表を作り直す（Windows の書体が必要）
"""
import collections
import hashlib
import io
import json
import logging
import os
import sys

from fontTools.ttLib import TTCollection, TTFont
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1

logging.disable(logging.CRITICAL)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etl import config  # noqa: E402

OUT = os.path.join(ROOT, 'etl', 'nishinihon_cid_maps.json')

# 対象の PDF（RAW_ROOT からの相対パス）
PDFS = [
    '2019/西日本トランポリン協会_PDF/47th_WestJapanTRA_Final_results.pdf',
    '2019/西日本トランポリン協会_PDF/47th_WestJapanTRA_Qualification_results.pdf',
    '2023/西日本トランポリン協会_PDF/51th_WestJapanTRA_Final_results.pdf',
]

FONTS_DIR = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts')
INSTALLED = {   # PDF のフォント名に含まれる語 → (ファイル, コレクション内の番号)
    'HGSGothicM': ('HGRGM.TTC', 2),
    'MS-PGothic': ('msgothic.ttc', 2),
    'MS-Mincho': ('msmincho.ttc', 1),
    'YuGothic-Regular': ('YuGothR.ttc', 0),
    'YuGothic-Bold': ('YuGothB.ttc', 0),
    'Meiryo': ('meiryo.ttc', 0),
}


def glyph_key(font, gname):
    """字形の輪郭を要約する（座標・フラグ・輪郭の区切り。部品の組み合わせは部品ごと）。"""
    g = font['glyf'][gname]
    if g.isComposite():
        parts = [(c.glyphName, getattr(c, 'x', 0), getattr(c, 'y', 0)) for c in g.components]
        sub = tuple((glyph_key(font, n), x, y) for n, x, y in parts)
        return hashlib.sha1(repr(('C', sub)).encode()).hexdigest()
    if not hasattr(g, 'coordinates') or g.numberOfContours == 0:
        return 'EMPTY'
    data = (tuple(g.coordinates), tuple(g.flags), tuple(g.endPtsOfContours))
    return hashlib.sha1(repr(data).encode()).hexdigest()


_cache = {}


def installed_index(key):
    if key not in _cache:
        path, idx = INSTALLED[key]
        font = TTCollection(os.path.join(FONTS_DIR, path)).fonts[idx]
        rev = collections.defaultdict(set)
        for cp, gname in font.getBestCmap().items():
            rev[gname].add(cp)
        order = font.getGlyphOrder()
        by_shape = collections.defaultdict(set)
        for gname in order:
            if gname in rev:
                by_shape[glyph_key(font, gname)] |= rev[gname]
        _cache[key] = (font, order, rev, by_shape)
    return _cache[key]


def pick(cps):
    """同じ字形に複数の文字コードがあるときは、統合漢字→かな→拡張A→全角の順に選ぶ。"""
    cps = sorted(cps)
    for lo, hi in ((0x4E00, 0x9FFF), (0x3040, 0x30FF), (0x3400, 0x4DBF), (0xFF00, 0xFFEF)):
        inside = [c for c in cps if lo <= c <= hi]
        if inside:
            return chr(inside[0])
    return chr(cps[0])


def used_cids(pdf_path):
    """文字として取り出せず「(cid:番号)」で出てくる字を、フォントごとに集める。"""
    import re
    import pdfplumber
    used = collections.defaultdict(set)
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for c in page.chars:
                m = re.fullmatch(r'\(cid:(\d+)\)', c['text'])
                if m:
                    used[c['fontname']].add(int(m.group(1)))
    return used


def decode_fonts(pdf_path):
    """「(cid:番号)」で出てくる字のあるフォントごとに {字形番号: 文字} と、決まらなかった番号を返す。"""
    used = used_cids(pdf_path)
    doc = PDFDocument(PDFParser(open(pdf_path, 'rb')))
    out = {}
    for page in PDFPage.create_pages(doc):
        for _, ref in (resolve1(page.resources.get('Font')) or {}).items():
            f = resolve1(ref)
            base = str(f.get('BaseFont')).strip("/'")
            if base in out or base not in used:
                continue
            df = resolve1(f.get('DescendantFonts'))
            if not df:
                continue
            fd = resolve1(resolve1(df[0])['FontDescriptor'])
            ff = fd.get('FontFile2')
            key = next((k for k in INSTALLED if k in base), None)
            if ff is None or key is None:
                raise SystemExit('対応する書体が分からないフォント: %s' % base)
            sub = TTFont(io.BytesIO(resolve1(ff).get_data()))
            font, order, rev, by_shape = installed_index(key)
            table, unresolved = {}, []
            glyphs = sub.getGlyphOrder()
            for gid in sorted(used[base]):
                gname = glyphs[gid] if gid < len(glyphs) else '.notdef'
                if gname == '.notdef':
                    unresolved.append(gid)
                    continue
                k = glyph_key(sub, gname)
                if k == 'EMPTY':
                    table[gid] = ' '
                elif gid < len(order) and order[gid] in rev and glyph_key(font, order[gid]) == k:
                    table[gid] = pick(rev[order[gid]])
                elif k in by_shape:
                    table[gid] = pick(by_shape[k])
                else:
                    unresolved.append(gid)
            out[base] = (table, unresolved)
    missing = set(used) - set(out)
    if missing:
        raise SystemExit('埋め込みフォントの見つからない字があります: %s' % sorted(missing))
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    result = {'_comment': __doc__.strip().splitlines()[0] + '（tools/build_cid_maps.py が作る。手で直さない）',
              'pdfs': {}}
    for rel in PDFS:
        path = os.path.join(config.RAW_ROOT, *rel.split('/'))
        sha = hashlib.sha256(open(path, 'rb').read()).hexdigest()
        fonts = {}
        for base, (table, unresolved) in sorted(decode_fonts(path).items()):
            # 輪郭の無い字形（空白）は ' '。輪郭があるのに一致する字形が無いものは止める。
            if unresolved:
                raise SystemExit('%s の %s に、輪郭の一致する字形が無い字が %d 個あります: %s'
                                 % (rel, base, len(unresolved), unresolved[:10]))
            fonts[base] = {str(g): c for g, c in sorted(table.items())}
            print('%s  %s  %d 字' % (os.path.basename(rel), base, len(table)))
        result['pdfs'][rel] = {'sha256': sha, 'fonts': fonts}
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write('\n')
    print('書き出し:', OUT)


if __name__ == '__main__':
    main()
