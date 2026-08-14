# -*- coding: utf-8 -*-
"""日本語表記とローマ字表記に分かれた同一人物の「候補」を洗い出す。

sporttech は国内大会を日本語表記、国際大会をローマ字表記で持つ。そのため
国際大会にも出るトップ層ほど、選手ページから国際大会の記録だけが抜け落ちる。

**自動では結合しない。** 候補を出すだけで、統合は
`etl/athlete_overrides.json` / `etl/judge_overrides.json` に人が書く。

候補の絞り込み条件（Vanさん指定）:
  1. 所属が JPN で、氏名がASCIIのみ（＝国際大会側のレコード）
  2. 日本語表記側と **出場大会の日付が一切重ならない**（同じ日に別々に出ていたら別人）
  3. 生年月日が一致する（**あくまで候補を絞る手掛かり。統合の鍵にはしない**）

生年月日は大会によってブレるので、一致しない組も「要確認」として残す。
読みの一致だけで自動採用はしない。
"""
import collections
import io
import os

from . import config


def _is_ascii(text):
    return all(ord(ch) < 128 for ch in text or '')


def _profiles(performances):
    """氏名ごとに、所属・出場日・生年月日・性別・演技数をまとめる。"""
    prof = collections.defaultdict(lambda: {
        'clubs': set(), 'dates': set(), 'dob': set(), 'sex': set(),
        'meets': set(), 'disciplines': set(), 'n': 0, 'best': None,
    })
    for p in performances:
        if p['source'] != 'sporttech' or len(p.get('athlete_names') or []) != 1:
            continue
        # 種目で絞らないこと。ここを個人だけにすると、DMT・タンブリング・シンクロで
        # 国際大会に出ている選手（＝分裂しているのはまさにこの層）を丸ごと取りこぼす。
        # Phase 1 の画面には出さないが、選手の同定はデータ全体で1回やっておく。
        a = prof[p['athlete_name']]
        a['disciplines'].add(p['discipline'])
        a['n'] += 1
        a['dates'].add(p['date'])
        a['meets'].add(p['meet_id'])
        if p['club']:
            a['clubs'].add(p['club'])
        if p.get('birth_date'):
            a['dob'].add(p['birth_date'])
        if p.get('sex'):
            a['sex'].add(p['sex'])
        if p.get('total') is not None and (a['best'] is None or p['total'] > a['best']):
            a['best'] = p['total']
    return prof


def _exact_dob(dates):
    """生年月日のうち、日付まで入っているものだけを返す。

    sporttech には月日が 01-01 の「年だけ分かっている」レコードが188件ある。
    これを一致判定に使うと、同じ年に生まれた別人を大量に拾ってしまう。
    """
    return {d for d in dates if d[5:] != '01-01'}


def surname_readings(overrides):
    """人が承認した統合から「ローマ字の姓 → 漢字の姓」の対応表を作る。

    読みを機械で当てにいくことはできないが、**すでに人が承認した組**から読みを
    覚えることはできる。一度 ISHIDA=石田 を承認しておけば、次に別の ISHIDA さんが
    出てきたとき「石田姓で同じ生年の選手が1人だけか」を機械で確かめられる。

    生年月日が YYYY-01-01（生年しか分からない）のレコードは日付で絞れないので、
    この表があるかどうかで取りこぼすかどうかが決まる。
    """
    table = collections.defaultdict(set)
    for entry in overrides.get('merge', []):
        names = entry.get('names', [])
        rom = [n for n in names if _is_ascii(n)]
        jpn = [n for n in names if not _is_ascii(n)]
        if len(rom) != 1 or len(jpn) != 1:
            continue
        rom_surname = rom[0].split(' ')[0].upper()
        jpn_surname = jpn[0].split(' ')[0]
        if rom_surname and jpn_surname:
            table[rom_surname].add(jpn_surname)
    return table


def find_candidates(performances, merged_names, readings=None):
    """(候補リスト, 統合済み件数) を返す。

    merged_names … すでに overrides で統合済みの氏名の集合
    readings     … 承認済みの統合から作った「ローマ字の姓 → 漢字の姓」対応表
    """
    readings = readings or {}
    prof = _profiles(performances)
    romanized = [n for n, a in prof.items()
                 if _is_ascii(n) and any('JPN' in c for c in a['clubs'])]
    japanese = [n for n in prof if not _is_ascii(n)]

    candidates = []
    already = 0
    for rom in sorted(romanized):
        if rom in merged_names:
            already += 1
            continue
        r = prof[rom]
        exact = _exact_dob(r['dob'])
        hits, loose_hits = [], []
        for jp in japanese:
            j = prof[jp]
            if r['dates'] & j['dates']:
                continue                      # 同じ日に別々に出ている＝別人
            if r['sex'] and j['sex'] and not (r['sex'] & j['sex']):
                continue                      # 男女が違えば別人
            if exact and (exact & _exact_dob(j['dob'])):
                hits.append(jp)
            elif not exact and ({d[:4] for d in r['dob']} & {d[:4] for d in j['dob']}):
                # 生年月日が「年だけ」のときは日付で絞れない。生年と男女だけで拾い、
                # 自己ベストの高い順に並べて「要確認」として出す（国際大会に出るのは上位層）。
                loose_hits.append(jp)
        # 生年しか分からないときの絞り込み。順に効かせる。
        reason = '生年月日が一致'
        by_surname, by_discipline = [], []
        if not exact and not hits:
            # ① 承認済みの統合から覚えた「ローマ字の姓→漢字の姓」で同姓に絞る
            kanji = readings.get(rom.split(' ')[0].upper(), set())
            if kanji:
                by_surname = [n for n in loose_hits
                              if any(n.startswith(k + ' ') or n == k for k in kanji)]
                if len(by_surname) == 1:
                    hits, reason = by_surname, '同姓・同生年に他候補なし'
            # ② 種目で絞る。タンブリングの選手が国内で個人に出ることはまずないので、
            #    「同じ種目・同じ生年で1人だけ」ならかなり強い手掛かりになる。
            if not hits and r['disciplines']:
                by_discipline = [n for n in loose_hits
                                 if prof[n]['disciplines'] & r['disciplines']]
                if len(by_discipline) == 1:
                    hits, reason = by_discipline, '同種目・同生年に他候補なし'
                else:
                    loose_hits = by_discipline or loose_hits

        loose_hits.sort(key=lambda n: prof[n]['best'] or 0, reverse=True)
        candidates.append({
            'romanized': rom,
            'romanized_n': r['n'],
            'romanized_meets': len(r['meets']),
            'romanized_dates': sorted(r['dates']),
            'romanized_disciplines': sorted(r['disciplines']),
            'dob': sorted(r['dob']),
            'dob_year_only': not exact,
            'reason': reason,
            'matches': [_brief(prof, jp) for jp in sorted(hits)],
            'loose_matches': [_brief(prof, jp) for jp in loose_hits[:5]],
            'loose_total': len(loose_hits),
        })
    return candidates, already


def _brief(prof, name):
    return {
        'name': name,
        'n': prof[name]['n'],
        'meets': len(prof[name]['meets']),
        'clubs': sorted(prof[name]['clubs'])[:2],
        'dob': sorted(prof[name]['dob']),
        'best': prof[name]['best'],
    }


def write_report(candidates, already, path):
    """候補一覧を docs に書き出す（審判側と同じ形式・貼り付け用JSONつき）。"""
    confident = [c for c in candidates if len(c['matches']) == 1]
    ambiguous = [c for c in candidates if len(c['matches']) > 1]
    unmatched = [c for c in candidates if not c['matches']]

    out = []
    out.append('# 選手の表記ゆれ候補（同一人物が2つのIDに分かれている可能性）')
    out.append('')
    out.append('**このファイルは `python -m etl.build` が毎回作り直します。手で編集しても上書きされます。**')
    out.append('')
    out.append('**Vanさんの確認をお願いしたい件です。** 確認できたら `etl/athlete_overrides.json` の')
    out.append('`merge` に書き足して `python -m etl.build` を回すと統合されます。こちらで勝手には結合していません。')
    out.append('')
    out.append('## 何が起きているか')
    out.append('')
    out.append('sporttech は、**国内大会では日本語表記、国際大会ではローマ字表記**で選手名を持っています。')
    out.append('氏名を鍵にしている以上、両方に出ている選手は別々のIDになります。')
    out.append('')
    out.append('**影響が大きいのは、抜けるのがW杯・アジア選手権に出るトップ層**だという点です。')
    out.append('選手ページを開くと、国際大会の記録だけが載っていない状態になります。')
    out.append('')
    out.append('| | |')
    out.append('|---|---|')
    out.append('| 統合の候補（未処理） | %d名 |' % len(candidates))
    out.append('| うち日本語表記側の候補が1人に絞れたもの | %d名 |' % len(confident))
    out.append('| 候補が複数あり要確認 | %d名 |' % len(ambiguous))
    out.append('| 生年月日が「年だけ」で絞れないもの | %d名 |' % len(unmatched))
    out.append('| すでに overrides で統合済み | %d名 |' % already)
    out.append('')
    out.append('## 候補の絞り方')
    out.append('')
    out.append('1. 所属が `JPN` で氏名がASCIIのみ（＝国際大会側のレコード）')
    out.append('2. 日本語表記側と **出場大会の日付が一切重ならない**（同じ日に別々に出ていたら別人）')
    out.append('3. 男女が食い違わない')
    out.append('4. 生年月日が一致する。ただし **`YYYY-01-01` は「生年しか分かっていない」**ものとして')
    out.append('   日付の一致判定には使わない（そういうレコードが188件あります）')
    out.append('5. 生年しか分からない場合は、**すでに承認済みの統合から覚えた「ローマ字の姓→漢字の姓」**を')
    out.append('   使い、同姓・同生年の選手が1人だけならその人を候補にする')
    out.append('6. それでも決まらない場合は**種目**で絞る。タンブリングの選手が国内で個人に出ることは')
    out.append('   まずないので、同じ種目・同じ生年で1人だけなら強い手掛かりになる')
    out.append('')
    out.append('**種目では絞っていません。** 個人だけを見ると、DMT・タンブリング・シンクロで')
    out.append('国際大会に出ている選手（分裂しているのはまさにこの層）を丸ごと取りこぼします。')
    out.append('')
    out.append('生年月日は**候補を絞る手掛かりとしてだけ**使っています。統合の鍵にはしていません')
    out.append('（大会によってブレるためです）。読みの一致だけで自動採用はしていません。')
    out.append('')

    if confident:
        out.append('## 候補が1人に絞れたもの（%d名）' % len(confident))
        out.append('')
        out.append('| ローマ字表記 | 種目 | 国際 | 日本語表記の候補 | 国内 | 生年月日 | 絞り込めた理由 |')
        out.append('|---|---|---|---|---|---|---|')
        for c in confident:
            m = c['matches'][0]
            out.append('| %s | %s | %d大会 | %s | %d大会 | %s | %s |' % (
                c['romanized'], '・'.join(c['romanized_disciplines']),
                c['romanized_meets'], m['name'], m['meets'],
                '／'.join(m['dob']), c['reason']))
        out.append('')
        out.append('### 貼り付け用（`etl/athlete_overrides.json` の `merge`）')
        out.append('')
        out.append('```json')
        out.append('{')
        out.append('  "split": [],')
        out.append('  "merge": [')
        lines = []
        for c in confident:
            m = c['matches'][0]
            lines.append('    { "athlete_id": "a-%s", "names": ["%s", "%s"] }'
                         % (_slug(c['romanized']), m['name'], c['romanized']))
        out.append(',\n'.join(lines))
        out.append('  ]')
        out.append('}')
        out.append('```')
        out.append('')

    if ambiguous:
        out.append('## 候補が複数あるもの（%d名）— 人が選んでください' % len(ambiguous))
        out.append('')
        for c in ambiguous:
            out.append('- **%s**（%d大会・生年月日 %s）'
                       % (c['romanized'], c['romanized_meets'], '／'.join(c['dob'])))
            for m in c['matches']:
                out.append('  - %s（%d大会・%s・生年月日 %s）'
                           % (m['name'], m['meets'], '／'.join(m['clubs']) or '所属なし',
                              '／'.join(m['dob'])))
        out.append('')

    if unmatched:
        out.append('## 生年月日で絞れなかったもの（%d名）— Vanさんの記憶で判断してください' % len(unmatched))
        out.append('')
        out.append('sporttech には**月日が 01-01 の「生まれた年しか分かっていない」レコードが188件**あります。')
        out.append('この選手たちがそれに当たるため、生年月日での絞り込みが効きません。')
        out.append('生年と男女が合う国内選手を、自己ベストの高い順に5人まで出しています')
        out.append('（国際大会に出るのは上位層なので、上のほうにいる可能性が高いという理由です）。')
        out.append('**読みが合うかどうかは機械では見ていません。**')
        out.append('')
        for c in unmatched:
            out.append('### %s' % c['romanized'])
            out.append('')
            out.append('- 国際 %d大会（%s）／生年 %s／%s'
                       % (c['romanized_meets'], '、'.join(c['romanized_dates']),
                          '・'.join(sorted({d[:4] for d in c['dob']})) or '不明',
                          'ローマ字表記のみ'))
            if not c['loose_matches']:
                out.append('- 生年と男女が合う国内選手は見つかりませんでした（統合不要と思われます）')
            else:
                out.append('- 生年と男女が合う国内選手 %d名のうち、自己ベスト上位5名：'
                           % c['loose_total'])
                for m in c['loose_matches']:
                    out.append('  - %s（%d大会・%s・自己ベスト %s）'
                               % (m['name'], m['meets'],
                                  '／'.join(m['clubs']) or '所属なし',
                                  ('%.2f' % m['best']) if m['best'] else '—'))
            out.append('')

    out.append('## 統合したあと')
    out.append('')
    out.append('```bash')
    out.append('python -m etl.build')
    out.append('python -m etl.acceptance')
    out.append('```')
    out.append('')
    out.append('統合すると選手ページに国際大会の記録が並び、出場大会数と自己ベストが変わります。')

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out) + '\n')


def _slug(romanized):
    return romanized.lower().replace(' ', '-')
