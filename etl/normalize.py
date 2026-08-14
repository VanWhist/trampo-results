# -*- coding: utf-8 -*-
"""氏名の正規化と選手の名寄せ。

名寄せの鍵は **氏名（フルネーム）だけ**（Vanさん決定 2026-08-07）。
所属も生年月日も鍵にしない。実データでの分裂率は
  氏名のみ 0% / 氏名＋生年月日 6.7% / 氏名＋所属 10.7%。

同姓同名の別人は現データで1件も確認できていない。自動で賢く判定しようとせず、
`etl/athlete_overrides.json` に人が1行足せば直る形にしてある。
"""
import hashlib
import io
import json
import os
import re
import unicodedata

from . import config

# 旧字体・異体字の揺れ。**実データで同一人物の表記ゆれを確認できた分だけ**変換する。
# 推測で広げると、本当に別姓の選手（澤田/沢田など）を誤って1人にまとめてしまう。
#   髙橋/高橋・宮﨑/宮崎・畦﨑/畦崎・髙垣/高垣・古瀨/古瀬 の6組で確認済み
NAME_VARIANTS = {
    '﨑': '崎',
    '髙': '高',
    '瀨': '瀬',
}

# 所属は人物の同定に使わないので、表示をそろえる目的でもう少し広く吸収してよい。
CLUB_VARIANTS = dict(NAME_VARIANTS)
CLUB_VARIANTS.update({'慶應': '慶応'})


def normalize_name(raw):
    """前後の空白除去／全角スペースを半角に／連続空白を1つに／既知の異体字を吸収。"""
    if not raw:
        return ''
    text = unicodedata.normalize('NFKC', raw)
    text = text.replace('　', ' ').replace('\r', ' ').replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    for old, new in NAME_VARIANTS.items():
        text = text.replace(old, new)
    return text


def normalize_club(raw):
    """所属の表記ゆれをならす。鍵には使わないが、履歴表示のため見た目を揃える。"""
    if not raw:
        return ''
    text = unicodedata.normalize('NFKC', raw)
    text = text.replace('　', ' ').replace('\r', ' ').replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    for old, new in CLUB_VARIANTS.items():
        text = text.replace(old, new)
    return text


def athlete_id(name):
    """氏名から安定したIDを作る。選手が増えても既存IDが動かないようハッシュにする。"""
    digest = hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]
    return 'a-%s' % digest


def judge_id(name):
    """審判のIDも氏名だけを鍵にする。

    大会ごとのIDにすると、同じ審判が大会ごとに別人になってしまい、
    「大会をまたいだ同一審判の追跡」という審判データを持つ意味が失われる。
    """
    digest = hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]
    return 'j-%s' % digest


def load_overrides():
    if not os.path.exists(config.OVERRIDES):
        return {'split': [], 'merge': []}
    with io.open(config.OVERRIDES, encoding='utf-8') as fh:
        data = json.load(fh)
    data.setdefault('split', [])
    data.setdefault('merge', [])
    return data


def build_athletes(performances, overrides):
    """演技レコードに athlete_id を振り、選手一覧を作って返す。

    シンクロなど複数名が1レコードに入る種目は選手として登録しない
    （選手名が「A / B」の連結になっていて、そのまま登録すると架空の選手ができる）。
    """
    merge_map = {}
    for entry in overrides['merge']:
        for name in entry.get('names', []):
            merge_map[normalize_name(name)] = entry['athlete_id']

    split_map = {}
    for entry in overrides['split']:
        name = normalize_name(entry['name'])
        for group in entry.get('groups', []):
            for meet in group.get('meets', []):
                split_map[(name, meet)] = group['athlete_id']

    athletes = {}
    for p in performances:
        p['athlete_name'] = normalize_name(p['athlete_name'])
        p['club'] = normalize_club(p['club'])
        p['athlete_names'] = [normalize_name(n) for n in p['athlete_names']]

        if len(p['athlete_names']) != 1:
            p['athlete_id'] = None       # シンクロ等。選手ページは作らない
            continue

        name = p['athlete_name']
        aid = split_map.get((name, p['date'])) or merge_map.get(name) or athlete_id(name)
        p['athlete_id'] = aid

        a = athletes.setdefault(aid, {
            'athlete_id': aid,
            'name': name,
            'names_seen': set(),
            'clubs': {},          # season -> set(club)
            'meets': set(),
            'sources': set(),
            'birth_dates': set(),
            'n_performances': 0,
        })
        a['names_seen'].add(p['athlete_name'])
        a['n_performances'] += 1
        a['meets'].add(p['meet_id'])
        a['sources'].add(p['source'])
        if p['club']:
            a['clubs'].setdefault(p['date'][:4], set()).add(p['club'])
        if p.get('birth_date'):
            a['birth_dates'].add(p['birth_date'])

    out = []
    for a in athletes.values():
        entry = {
            'athlete_id': a['athlete_id'],
            'name': a['name'],
            # 所属は「属性」。年ごとに履歴として持つ（例 2025 アベノジュニア → 2026 阪南大学クラブ）
            'club_history': [{'season': s, 'clubs': sorted(c)}
                             for s, c in sorted(a['clubs'].items())],
            'sources': sorted(a['sources']),
            'n_meets': len(a['meets']),
            'n_performances': a['n_performances'],
        }
        others = sorted(n for n in a['names_seen'] if n != a['name'])
        if others:
            entry['names_seen'] = others      # 異体字などで表記が揺れていた場合のみ持つ
        if len(a['birth_dates']) > 1:
            # 生年月日は大会によってブレる。鍵にも表示にも使わないので、
            # 「ブレている」という事実だけ残す。
            entry['birth_date_conflict'] = True
        out.append(entry)
    out.sort(key=lambda x: x['name'])
    return out
