# -*- coding: utf-8 -*-
"""第0層：完全性の検査。「取りこぼしていないか」だけを見る。

数値の検算（E・合計）は行がそろっていることを前提にしている。行が丸ごと落ちていても
恒等式は成立してしまうので、別立てで「原本にあるものが全部入っているか」を確かめる。

実際に起きた事故:
  西日本 大学生リザルト p4（女子予選）はフッタURLの日本語が全て脱落しており、
  見出しを取りこぼすと18名36行が丸ごと欠ける状態だった。本文の見出しは無傷なので、
  フッタが読めないページは本文見出しから区分を復元する。

検査は4つ:
  1. 全ページが処理済み  … PDFの各ページがいずれかの区分に割り当てられ、行を生んでいる
  2. ページ n/N マーカー … 区分ごとに 1..N が欠番なくそろっている
  3. 順位の連続性        … 区分×ラウンドで順位が 1..N（同順位は標準のタイ規則で飛ぶ）
  4. 区分別の基準値      … 人が確認して固定した行数・人数と一致（expected_sections.json）

順位の連続性だけでは「末尾のページが落ちた」を止められない（1〜45位が連続していれば
本来60名でも通ってしまう）。実際に問題になった p4 は最終ページなので、1と2が要る。

大阪府は原本側に外部の突合相手がある（一覧ページが持つ演技明細のリンク数）。
こちらは1〜3より強い検証になるので、そのまま件数を突き合わせる。

pdfplumber が無い環境では 1・2 を skipped として報告する（黙って緑にしない）。
"""
import collections
import csv
import io
import json
import os
import re
import unicodedata

from . import club_fixes, config
from .sources import nishinihon_pdf

# 西日本は大会ごとにPDFの置き場が分かれる。第53回と第54回は区分名が同じなので、
# 検査は必ず大会（meet_id）で分けて行う。混ぜると順位も1本目/2本目も二重になる。
NISHI_PDF_DIRS = {
    'nw-2025-09-12': os.path.join(config.RAW_ROOT, '2025', '西日本トランポリン協会_PDF'),
    'nw-2026-09-04': os.path.join(config.RAW_ROOT, '2026', '西日本トランポリン協会_PDF'),
}
NISHI_LABEL = {'nw-2025-09-12': '西日本 第53回', 'nw-2026-09-04': '西日本 第54回'}
OSAKA_INDEX = os.path.join(config.RAW_ROOT, '_大阪府pweb_区分一覧.csv')
EXPECTED_SECTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'expected_sections.json')

# フッタURLの Category → CSV の種別に使う名前
CATEGORY = {'低学年': '小学生低学年', '高学年': '小学生高学年', '中学生': '中学生',
            '高校生': '高校生', '大学生': '大学生', '一般': '一般', 'オープン': 'オープン',
            # 第54回はフッタURLの Category が略さず入る
            '小学生低学年': '小学生低学年', '小学生高学年': '小学生高学年'}
ROUND = {'予選2': '予選', '予選': '予選', '決勝': '決勝'}
CAT_RE = '|'.join(sorted(CATEGORY, key=len, reverse=True))

FOOTER_RE = re.compile(r'Sex=(男子|女子).*?Category=(' + CAT_RE + r').*?Round=(予選2|予選|決勝)')
BODY_RE = re.compile(r'個人(男子|女子)(' + CAT_RE + r')(予選|決勝)')
MARKER_RE = re.compile(r'(\d+)\s*/\s*(\d+)\s*$')


def _nfkc(text):
    # PDFのフォントはCJK部首（U+2F24 など）を使うことがある。NFKCで通常の漢字に直す。
    return unicodedata.normalize('NFKC', text or '')


def read_nishinihon_pages(meet_id):
    """西日本PDFの全ページを読み、(種別, ラウンド) と n/N マーカーを返す。

    フッタURLから区分を取り、読めなければ本文の見出しから復元する。
    どちらからも取れないページは section=None で返し、呼び出し側がエラーにする。
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    import logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)

    directory = NISHI_PDF_DIRS[meet_id]
    if not os.path.isdir(directory):
        return []
    pages = []
    # 読むファイルの決め方（訂正版を正とする・特別賞とスタートリストは結果ではない）は
    # 取り込み側と同じものを使う。別々に書くと食い違う。
    for name in nishinihon_pdf.result_pdfs(directory):
        path = os.path.join(directory, name)
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                lines = [l for l in _nfkc(page.extract_text() or '').splitlines() if l.strip()]
                footer = lines[-1] if lines else ''
                section, via = None, None
                m = FOOTER_RE.search(footer)
                if m:
                    section = ('%s %s' % (CATEGORY[m.group(2)], m.group(1)), ROUND[m.group(3)])
                    via = 'footer'
                else:
                    for line in lines:
                        b = BODY_RE.search(line.replace(' ', ''))
                        if b:
                            section = ('%s %s' % (CATEGORY[b.group(2)], b.group(1)), ROUND[b.group(3)])
                            via = 'body'
                            break
                mk = MARKER_RE.search(footer)
                pages.append({
                    'file': name, 'page': i, 'section': section, 'via': via,
                    'marker': (int(mk.group(1)), int(mk.group(2))) if mk else None,
                })
    return pages


def _load_expected():
    if not os.path.exists(EXPECTED_SECTIONS):
        return None
    with io.open(EXPECTED_SECTIONS, encoding='utf-8') as fh:
        return json.load(fh)


def _sections_from_perfs(perfs, source, meet_id=None):
    """ETL出力側の区分×ラウンドごとの行数・選手数・順位集合。

    meet_id を渡すとその大会だけを見る。西日本は第53回と第54回で区分名が同じなので、
    渡さないと順位も1本目/2本目も二重に数えてしまう。
    """
    out = collections.defaultdict(
        lambda: {'rows': 0, 'athletes': set(), 'ranks': collections.defaultdict(set)})
    for p in perfs:
        if p['source'] != source:
            continue
        if meet_id is not None and p['meet_id'] != meet_id:
            continue
        s = out[(p['category'], p['round'] or '')]
        s['rows'] += 1
        s['athletes'].add(p['athlete_name'])
        if p.get('rank'):
            s['ranks'][int(p['rank'])].add(p['athlete_name'])
    return out


def check_rank_continuity(sections, rep, label):
    """順位が 1..N か。同順位があるぶんは次の順位が飛ぶ（1,2,2,4）のを正とする。

    タイを考慮しないと、17位が2名いる大学生女子予選のような区分で誤検知する。
    """
    checked = 0
    for (cat, rnd), s in sorted(sections.items()):
        if not s['ranks']:
            continue
        checked += 1
        expect, pos = set(), 1
        for rk in sorted(s['ranks']):
            expect.add(pos)
            pos += len(s['ranks'][rk])
        got = set(s['ranks'])
        if got != expect:
            rep.error('完全性', '%s %s %s の順位が連続していません（%d名／順位 %s／期待 %s）'
                      % (label, cat, rnd, len(s['athletes']),
                         sorted(got)[:12], sorted(expect)[:12]))
    return checked


def check_nishinihon(perfs, rep):
    """西日本：全ページ処理済み・n/N マーカー・順位の連続性。大会ごとに見る。"""
    counts = {'ページ': 0, '区分': 0, '順位': 0}
    for meet_id in sorted(NISHI_PDF_DIRS):
        for k, v in _check_nishinihon_meet(perfs, rep, meet_id).items():
            counts[k] += v
    return counts


def _check_nishinihon_meet(perfs, rep, meet_id):
    counts = {'ページ': 0, '区分': 0, '順位': 0}
    label = NISHI_LABEL[meet_id]
    sections = _sections_from_perfs(perfs, 'nishinihon', meet_id)
    if not sections:
        return counts
    counts['順位'] = check_rank_continuity(sections, rep, label)

    pages = read_nishinihon_pages(meet_id)
    if pages is None:
        rep.note('完全性_西日本のページ検査', 'skipped（pdfplumber が無い）')
        rep.warn('完全性', '%s のページ検査を実行できませんでした（pdfplumber 未導入）。'
                           '順位の連続性だけを確認しています' % label)
        return counts

    counts['ページ'] = len(pages)
    by_section = collections.defaultdict(list)
    for pg in pages:
        if pg['section'] is None:
            rep.error('完全性', '%s %s p%d の区分を特定できません（フッタも本文見出しも読めない）。'
                                'このページの行が丸ごと落ちている可能性があります'
                      % (label, pg['file'], pg['page']))
            continue
        by_section[pg['section']].append(pg)

    for section, pgs in sorted(by_section.items()):
        cat, rnd = section
        counts['区分'] += 1
        markers = [p['marker'] for p in pgs if p['marker']]
        if len(markers) != len(pgs):
            rep.warn('完全性', '%s %s %s にページ番号が読めないページがあります' % (label, cat, rnd))
        if markers:
            totals = {t for _, t in markers}
            if len(totals) > 1:
                rep.error('完全性', '%s %s %s のページ総数が一致しません %s'
                          % (label, cat, rnd, sorted(totals)))
            else:
                total = totals.pop()
                got = sorted(n for n, _ in markers)
                if got != list(range(1, total + 1)):
                    rep.error('完全性', '%s %s %s のページが欠けています（%d/%d ページ、番号 %s）'
                              % (label, cat, rnd, len(got), total, got))
        s = sections.get(section)
        if not s or not s['rows']:
            rep.error('完全性', '%s %s %s は PDF に %d ページありますが、取り込んだ行が0です'
                      % (label, cat, rnd, len(pgs)))
        via_body = [p for p in pgs if p['via'] == 'body']
        if via_body:
            rep.note('完全性_フッタ破損',
                     '%s %s %s p%d はフッタURLの日本語が脱落しており、本文見出しから区分を復元'
                     % (label, cat, rnd, via_body[0]['page']))

    for section in sections:
        if section not in by_section:
            rep.error('完全性', '%s %s %s は取り込まれていますが、対応するPDFページがありません'
                      % ((label,) + section))
    return counts


def check_nishinihon_pairs(perfs, rep):
    """西日本 予選：Total == Q1 + Q2 と、1選手＝2行の構造。

    これが第0層でいちばん効く検査。PDFの1行目末尾に印字されている Total は、その選手の
    Q1とQ2のスコアの和なので、**1行目と2行目を結びつける**。

    実際に起きる事故は「氏名だけが入れ替わる」ではなく「2行目（所属＋Q2）が別の選手に
    くっつく」（予選は1選手＝2行で、ページ末尾で分断されることがある）。その場合 Q2 が
    別人のものになるので、この恒等式が破れる。実測で391名すべて成立。
    """
    counts = {'合計照合': 0, '構造': 0}
    by = collections.defaultdict(list)
    for p in perfs:
        # 大会で分ける。分けないと第53回と第54回の同姓同名が1人にまとまり、
        # 1本目・2本目が4行に見えてしまう。
        if p['source'] == 'nishinihon' and p['round'] == '予選':
            by[(NISHI_LABEL.get(p['meet_id'], p['meet_id']),
                p['category'], p['athlete_name'])].append(p)

    for (label, cat, name), rs in sorted(by.items()):
        counts['構造'] += 1
        routines = sorted(r['routine'] for r in rs if r['routine'])
        if routines != [1, 2]:
            rep.error('完全性', '%s %s %s の予選が1本目・2本目でそろっていません（%s）'
                      % (label, cat, name, routines))
            continue
        totals = {r.get('qualifying_total') for r in rs}
        scores = [r['total'] for r in rs]
        if len(totals) != 1 or None in totals or None in scores:
            rep.warn('完全性', '%s %s %s は予選合計を照合できません' % (label, cat, name))
            continue
        counts['合計照合'] += 1
        want = totals.pop()
        got = round(sum(scores), 2)
        if abs(want - got) > 0.005:
            rep.error('完全性', '%s %s %s の予選合計が合いません：印字 %.2f / 1本目+2本目 %.2f。'
                                '2行目（所属とQ2）が別の選手に付いている可能性があります'
                      % (label, cat, name, want, got))
    return counts


def check_club_consistency(perfs, rep):
    """同じ大会の中で、1人の選手が複数の所属で現れないか。

    所属が変わるのは大会をまたいだ転籍なので、大会内での不一致だけを見る。
    """
    by = collections.defaultdict(set)
    for p in perfs:
        if p['club']:
            by[(p['meet_id'], p['athlete_name'])].add(p['club'])
    n = 0
    for (meet_id, name), clubs in sorted(by.items()):
        n += 1
        if len(clubs) <= 1:
            continue
        # 一方が他方の前方一致で長いだけなら、PDFの列幅で切れているだけで矛盾ではない
        longest = max(clubs, key=len)
        if all(longest.startswith(c) for c in clubs):
            continue
        rep.warn('完全性', '%s の %s に所属が複数あります %s（同一大会内）'
                 % (meet_id, name, sorted(clubs)))
    return {'所属の一貫性': n}


def read_finals_clubs():
    """決勝ページの所属を、折り返しを結合して読む。

    予選はQ2のスコアと同じ行なので列幅で切れるが、**決勝は所属が独立行なので折り返せる**。
    つまり決勝ページには完全形がある。これが切り詰め判定の参照表になる（sporttechより良い。
    同じ大会・同じクラブなので誤爆しない）。

    注意: 決勝ページでは選手名と所属が別行になるので、単純に連続行を結合すると名前が混ざる。
    **所属列の右端のx座標**で絞る（そのページで最も多く現れる x1 が所属列の右端）。
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    import logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)

    full = set()
    for name in sorted(os.listdir(NISHI_PDF_DIRS['nw-2025-09-12'])):
        if not name.lower().endswith('.pdf') or '特別賞' in name:
            continue
        with pdfplumber.open(os.path.join(NISHI_PDF_DIRS['nw-2025-09-12'], name)) as pdf:
            for page in pdf.pages:
                if 'Q2' in (page.extract_text() or ''):
                    continue                   # 予選ページは切り詰められているので参照にしない
                lines = collections.defaultdict(list)
                for w in page.extract_words():
                    lines[round(w['top'], 1)].append(w)
                segs = [(top, sorted(lines[top], key=lambda w: w['x0'])) for top in sorted(lines)]
                cand = [(top, ws) for top, ws in segs
                        if not ws[0]['text'][0].isdigit()
                        and len(''.join(w['text'] for w in ws)) > 2]
                if not cand:
                    continue
                edge = collections.Counter(round(ws[-1]['x1'], 1)
                                           for _, ws in cand).most_common(1)[0][0]
                club_lines = [(top, _nfkc(''.join(w['text'] for w in ws)))
                              for top, ws in cand if abs(round(ws[-1]['x1'], 1) - edge) <= 1.5]
                current, prev_top = None, None
                for top, text in club_lines:
                    if prev_top is not None and top - prev_top < 12:
                        current += text        # 折り返しの続き（行間が狭い）
                    else:
                        if current:
                            full.add(current)
                        current = text
                    prev_top = top
                if current:
                    full.add(current)
    return full


def measure_club_widths():
    """予選Q2行に印字された所属の文字幅を測る（一次スクリーニング）。

    所属はQ2列に対して右詰めで印字されるので、**列幅いっぱいまで伸びているもの＝
    切り詰められたもの**と幅で当たりを付けられる。トークンは「所属＋Q2」と連結している。
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    import logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)

    out = []
    for name in sorted(os.listdir(NISHI_PDF_DIRS['nw-2025-09-12'])):
        if not name.lower().endswith('.pdf') or '特別賞' in name:
            continue
        with pdfplumber.open(os.path.join(NISHI_PDF_DIRS['nw-2025-09-12'], name)) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                words = page.extract_words()
                for tok in [w for w in words if w['text'].endswith('Q2')]:
                    pre = [w for w in words
                           if abs(w['top'] - tok['top']) < 3 and w['x1'] <= tok['x0'] + 0.5]
                    club = ''.join(w['text'] for w in sorted(pre, key=lambda w: w['x0']))
                    club = _nfkc(club + tok['text'][:-2])
                    x0 = min([w['x0'] for w in pre] + [tok['x0']])
                    out.append({'width': round(tok['x1'] - x0, 1), 'club': club,
                                'pdf': name, 'page': page_no})
    return out


# 一次スクリーニングの閾値。決勝突合で切り詰めと確定した3件がすべて 101.1pt 以上で、
# 予選Q2列の実測最大は 110.6pt。100pt に置くと確定3件を確実に含む。
TRUNCATION_WIDTH = 100.0


def check_truncated_clubs(perfs, rep):
    """所属の切り詰めを2段で判定する。**直さない。数と一覧を残すだけ。**

      一次: 予選Q2行の幅が TRUNCATION_WIDTH 以上（候補）
      確定: 決勝ページの完全形と突き合わせ（同一形＝完全 / 前方一致で長い＝切り詰め）

    決勝に出ていない選手は参照が無いので「未確定」。予選のみに出場した選手の長い所属は、
    PDF内に完全形が存在しないため、この方法でも復元できない（西日本の所属の精度の上限）。
    """
    rows = measure_club_widths()
    finals = read_finals_clubs()
    if rows is None or finals is None:
        rep.note('所属の切り詰め(西日本)', 'skipped（pdfplumber が無い）')
        return 0

    # 決勝に出ていない選手のための二次参照。sporttechの所属は構造化された完全な文字列。
    other_clubs = {_nfkc(p['club']) for p in perfs
                   if p['source'] == 'sporttech' and p['club']
                   and len(p.get('athlete_names') or []) == 1}

    verdicts = collections.OrderedDict()
    for r in rows:
        if r['width'] < TRUNCATION_WIDTH:
            continue
        club = r['club']
        entry = verdicts.setdefault(club, {'width': r['width'], 'rows': 0,
                                           'verdict': None, 'full': None})
        entry['rows'] += 1
        if entry['verdict']:
            continue
        if club in finals:
            entry['verdict'] = 'complete'
        else:
            longer = sorted([f for f in finals if f != club and f.startswith(club)], key=len)
            if longer:
                entry['verdict'], entry['full'] = 'truncated', longer[0]
            elif club in other_clubs:
                # 決勝に参照が無くても、他ソースに**完全一致**する所属名があれば完結している。
                # 前方一致は使わない（シンクロの連結所属で誤爆するため）。
                entry['verdict'] = 'complete_elsewhere'
            else:
                entry['verdict'] = 'unknown'

    counts = collections.Counter(v['verdict'] for v in verdicts.values())
    rep.note('所属の切り詰め(西日本)',
             '候補%d種類 → 切り詰め %d / 完全 %d / 未確定 %d（予選 %d行を実測、決勝の完全形 %d種類）'
             % (len(verdicts), counts['truncated'],
                counts['complete'] + counts['complete_elsewhere'], counts['unknown'],
                len(rows), len(finals)))
    if counts['truncated']:
        rep.warn('所属の切り詰め',
                 '西日本で切り詰められた所属が %d種類あります（決勝ページの完全形と突合して確定）。'
                 '訂正済みかどうかは docs/西日本_所属の切り詰め.md' % counts['truncated'])
    if counts['unknown']:
        rep.warn('所属の切り詰め',
                 '西日本で判定できない所属が %d種類あります（決勝に出ていないため参照が無い）'
                 % counts['unknown'])
    _write_truncation_doc(rows, verdicts, finals)
    return len(rows)


def _write_truncation_doc(rows, verdicts, finals):
    counts = collections.Counter(v['verdict'] for v in verdicts.values())
    label = {'truncated': '**切り詰め**', 'complete': '完全（決勝に同一形）',
             'complete_elsewhere': '完全（sporttechに完全一致）',
             'unknown': '決勝に無し（未確定）'}
    lines = ['# 西日本の所属の切り詰め（測定と確定）', '',
             '**このファイルは `python -m etl.build` が毎回作り直します。**', '',
             '西日本の所属は、予選ではQ2のスコアと同じ行に印字されるため、'
             '**列幅を超えると切り詰められます**。決勝は所属が独立した行に印字されるので'
             '折り返すことができ、完全形が残ります。', '',
             '## 2段で判定しています', '',
             '1. **一次スクリーニング（幅）**：予選Q2行の所属の幅が %.0fpt 以上を候補にする。'
             '所属は右詰めで印字されるので、列幅いっぱい＝切り詰めの疑い。予選 %d 行すべてを実測。'
             '閾値の根拠は、決勝突合で切り詰めと確定した件がすべて 101.1pt 以上だったこと'
             '（実測の最大は 110.6pt）' % (TRUNCATION_WIDTH, len(rows)),
             '2. **確定（決勝突合）**：決勝ページから折り返しを結合して読んだ完全形 %d種類と'
             '突き合わせる。同一形なら完全、前方一致で長い形があれば切り詰め。'
             '同じ大会・同じクラブなので誤爆しない' % len(finals), '',
             '幅だけでは候補しか出せませんが、決勝突合は白黒がつきます。', '',
             '## 結果（候補 %d種類 → 切り詰め %d / 完全 %d / 未確定 %d）'
             % (len(verdicts), counts['truncated'],
                counts['complete'] + counts['complete_elsewhere'], counts['unknown']), '',
             '| 幅(pt) | 予選での所属 | 行数 | 判定 | 完全形 |', '|---:|---|---:|---|---|']
    for club, v in sorted(verdicts.items(), key=lambda x: -x[1]['width']):
        lines.append('| %.1f | %s | %d | %s | %s |'
                     % (v['width'], club, v['rows'], label[v['verdict']], v['full'] or '—'))
    lines += ['', '切り詰めと確定したものは `etl/nishinihon_club_fixes.json` で訂正しています'
                  '（根拠として決勝ページのファイル名とページ番号を記録）。', '',
              '## この方法の限界', '',
              '- **予選にしか出場していない選手の長い所属**は、決勝に参照が無いので確定できません。'
              'その所属が実際に切り詰められていた場合、**完全形はPDFのどこにも存在しません**。'
              'ここが西日本の所属の精度の上限で、読み取り側では回復できません',
              '- 切り詰められていても列幅に達しない所属は、一次スクリーニングに掛かりません', '',
              '以前は sporttech の所属名との前方一致で測っていましたが、'
              'シンクロの連結所属で誤爆し、既知の実例（谷口 遼平）も検出できなかったため、'
              'この2段の方法に置き換えました。']
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'docs', '西日本_所属の切り詰め.md')
    with io.open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')


def check_osaka(perfs, rep):
    """大阪府：一覧ページが持つ演技数（外部の数）と取り込み件数を突き合わせる。"""
    counts = {'区分': 0}
    if not os.path.exists(OSAKA_INDEX):
        rep.warn('完全性', '大阪府の区分一覧CSVが見つかりません。件数照合を実行できませんでした')
        return counts
    with io.open(OSAKA_INDEX, encoding='utf-8-sig', newline='') as fh:
        index = list(csv.DictReader(fh))

    expected = {}
    for row in index:
        n = int(row['RoutineDetails'] or 0)
        if n > 0:
            expected[(row['Dir'][:10], row['Title'])] = n

    got = collections.Counter()
    for p in perfs:
        if p['source'] != 'osaka_pweb':
            continue
        got[(p['date'], p['raw_category'])] += 1
        # 区分ページをまたいだ重複掲載は1件にまとめてあるので、元の区分でも数え直す
        for other in p.get('also_in_raw_categories') or []:
            got[(p['date'], other)] += 1

    for key, n in sorted(expected.items()):
        counts['区分'] += 1
        g = got.get(key, 0)
        if g != n:
            rep.error('完全性', '大阪府 %s %s：一覧ページの演技数 %d に対し取り込み %d 件'
                      % (key[0], key[1], n, g))
    for key in sorted(got):
        if key not in expected:
            rep.error('完全性', '大阪府 %s %s は取り込まれていますが一覧ページにありません' % key)
    return counts


def check_baseline(perfs, rep, accept=False):
    """区分別の行数・人数を、人が確認して固定した基準と突き合わせる。

    元の変換が正しいことは保証しない。次回以降の取りこぼしを止めるためのもの。
    """
    # 鍵に大会を含める。含めないと大会を1つ足しただけで既存の区分の値が全部動き、
    # 「増えたぶん」と「取りこぼし」を見分けられなくなる。
    meets = collections.defaultdict(set)
    for p in perfs:
        meets[p['source']].add(p['meet_id'])
    current = {}
    for source in ('higashinihon', 'nishinihon', 'osaka_pweb', 'sporttech'):
        for meet_id in sorted(meets.get(source, ())):
            for (cat, rnd), s in _sections_from_perfs(perfs, source, meet_id).items():
                current['%s|%s|%s|%s' % (source, meet_id, cat, rnd)] = {
                    'rows': s['rows'], 'athletes': len(s['athletes'])}

    saved = _load_expected()
    if saved is None or accept:
        with io.open(EXPECTED_SECTIONS, 'w', encoding='utf-8') as fh:
            json.dump({'_comment': '区分×ラウンドごとの行数と選手数。人が確認して固定した基準値。'
                                   '元の変換が正しいことは保証しないが、次回以降の取りこぼしは止まる。'
                                   '`python -m etl.build --accept-sections` で更新する。',
                       'sections': current}, fh, ensure_ascii=False, indent=1, sort_keys=True)
        rep.note('完全性_区分別基準', '%d区分を基準として保存しました' % len(current))
        return len(current)

    base = saved.get('sections', {})
    for key, cur in sorted(current.items()):
        old = base.get(key)
        if old is None:
            rep.warn('完全性', '%s は新しい区分です（%d行／%d名）。内容確認後 `--accept-sections` で登録してください'
                     % (key.replace('|', ' '), cur['rows'], cur['athletes']))
        elif old != cur:
            rep.error('完全性', '%s の件数が変わりました：%d行/%d名 → %d行/%d名'
                      % (key.replace('|', ' '), old['rows'], old['athletes'],
                         cur['rows'], cur['athletes']))
    for key, old in sorted(base.items()):
        if key not in current:
            rep.error('完全性', '%s が今回の取り込みにありません（%d行/%d名）'
                      % (key.replace('|', ' '), old['rows'], old['athletes']))
    return len(current)


def check_wrapped_clubs(rep):
    """第54回以降のPDF：列からあふれた所属が、切り詰めではなく折り返されているか。

    第53回は列幅を超えた所属が黙って切り詰められていた（決勝ページの完全形と突き合わせ
    3件を確定）。第54回のPDFは同じ所属を2行に折り返して印字するので、行をつなげば
    情報は落ちない。ただし**折り返す実装だと決めつけない**。PDFごとに「実際に折り返しが
    起きた幅」を測り、折り返さずにその幅へ達している所属があれば切り詰めの疑いとして出す。

    疑いが出ても訂正はしない。完全形がPDFのどこにも無い可能性があるため、
    件数と一覧を出すところまでにする。
    """
    measured = nishinihon_pdf.measure_club_lines()
    if measured is None:
        rep.note('完全性_第54回の所属', 'skipped（pdfplumber が無い）')
        return 0
    checked = suspects = 0
    for m in measured:
        if not m['wrapped']:
            continue        # このPDFでは折り返しが起きておらず、幅の基準を取れない
        limit = min(width for width, _ in m['wrapped'])
        for width, club in m['single']:
            checked += 1
            if width >= limit - 1:
                suspects += 1
                rep.warn('完全性', '西日本 第54回 %s の所属「%s」は折り返さずに'
                                   '折り返し幅 %.1fpt に達しています（切り詰めの疑い）'
                         % (m['file'], club, limit))
    rep.note('所属の折り返し(西日本 第54回)',
             '折り返しが起きたPDF %d本で幅を実測し、1行の所属 %d件を照合 → 切り詰めの疑い %d件'
             % (sum(1 for m in measured if m['wrapped']), checked, suspects))
    return checked


def run(perfs, rep, accept=False):
    """第0層をまとめて実行し、実行件数を返す。0件で緑にしないための数でもある。"""
    counts = {}
    for k, v in check_nishinihon(perfs, rep).items():
        counts['西日本_' + k] = v
    for k, v in check_nishinihon_pairs(perfs, rep).items():
        counts['西日本_' + k] = v
    counts.update(check_club_consistency(perfs, rep))
    counts['所属の訂正'] = club_fixes.check(rep, accept)
    counts['所属の切り詰め疑い'] = check_truncated_clubs(perfs, rep)
    counts['所属の折り返し(第54回)'] = check_wrapped_clubs(rep)
    for k, v in check_osaka(perfs, rep).items():
        counts['大阪府_' + k] = v
    counts['区分別基準'] = check_baseline(perfs, rep, accept)
    return counts
