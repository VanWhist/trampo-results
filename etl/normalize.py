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
# 渡邊/渡辺・齋/斎・齊/斉・曾/曽 は実データで統合される組が無く、入れても効かないので入れない。
#   髙橋/高橋・宮﨑/宮崎・畦﨑/畦崎・髙垣/高垣・古瀨/古瀬・草ヶ谷/草ケ谷 の7組で確認済み
NAME_VARIANTS = {
    '﨑': '崎',
    '髙': '高',
    '瀨': '瀬',
    'ヶ': 'ケ',      # 草ヶ谷 剛 と 草ケ谷 剛（同一人物・所属だけ違う）
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


# 国際大会の Representing は「JPN」「KAZ, 1」のような国コード。所属クラブではない。
COUNTRY_CODE = re.compile(r'^[A-Z]{3}(, ?\d+)?$')

_JUDGE_MERGE = None


def judge_id(name):
    """審判のIDも氏名だけを鍵にする。

    大会ごとのIDにすると、同じ審判が大会ごとに別人になってしまい、
    「大会をまたいだ同一審判の追跡」という審判データを持つ意味が失われる。
    表記ゆれ（日本語／ローマ字）の統合は judge_overrides.json で人が指定する。
    """
    global _JUDGE_MERGE
    if _JUDGE_MERGE is None:
        _JUDGE_MERGE = load_judge_overrides()
    manual = _JUDGE_MERGE.get(name)
    if manual:
        return manual
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


def load_judge_overrides():
    """審判の表記ゆれの手動統合。

    国内大会は日本語表記、国際大会はローマ字表記なので、両方で審判をしている人は
    そのままだと別IDになる（山本 宜史 と YAMAMOTO Norifumi など）。
    読みを機械的に当てにいくと別人を混ぜる危険があるので、人が確認して1行足す形にする。
    候補は docs/審判の表記ゆれ候補.md にまとめてある。
    """
    if not os.path.exists(config.JUDGE_OVERRIDES):
        return {}
    with io.open(config.JUDGE_OVERRIDES, encoding='utf-8') as fh:
        data = json.load(fh)
    mapping = {}
    for entry in data.get('merge', []):
        for name in entry.get('names', []):
            mapping[normalize_name(name)] = entry['judge_id']
    return mapping


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
            'disciplines': set(),
            'n_performances': 0,
        })
        a['names_seen'].add(p['athlete_name'])
        a['n_performances'] += 1
        a['disciplines'].add(p['discipline'])
        a['meets'].add(p['meet_id'])
        a['sources'].add(p['source'])
        # 国際大会の「所属」は JPN・KAZ のような国コードで、クラブ名ではない。
        # 所属履歴（転籍が見える表示）に混ぜると意味が壊れるので外す。
        if p['club'] and not COUNTRY_CODE.match(p['club']):
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
            # Phase 1 の画面は個人種目しか出さない。DMT・タンブリング・シンクロだけの選手は
            # 選手ページに1件も並ばないので、空の画面を出さずに理由を書けるようにする。
            'has_individual': config.PHASE1_DISCIPLINE in a['disciplines'],
            'disciplines': sorted(a['disciplines']),
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
