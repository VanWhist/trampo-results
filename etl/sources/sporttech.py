# -*- coding: utf-8 -*-
"""sporttech.io の生JSONから演技レコードを組み立てる。

実データで確認済みの落とし穴（すべてここで処理する）:
  1. stage_<N>.json は関連ステージのデータを重複して持つ → FrameID でデデュープ
  2. State==0 は除外。NElements が明示的に0 の枠も除外（State 3/4 どちらも）
     NElements キー自体が無いケースは「出場記録」として含める（技数は空欄）
  3. 種目は親 Competition の Discipline を使う（Performance.Discipline は 0 固定の例がある）
  4. 大会名・日付・国内国際は _meta.json を正とする（EventTitle_G は国際大会で表記が違う）
  5. 単位換算（個人トランポリンのみ）
  6. Deducts_G は [S1〜S10, L, A] の12要素。技数を超えた位置の減点は「未算入」に隔離する
  7. ETotalsT_G のスロット n → E(n+1)。有効値は 0・100 を除いたもの
"""
import glob
import hashlib
import io
import json
import os

from .. import config, normalize


def _load(path):
    with io.open(path, encoding='utf-8-sig') as fh:
        return json.load(fh)


def _merge_meet(meet_dir):
    """1大会ぶんの stage_*.json と event.json を1つのモデルにまとめる。

    stage ファイルは互いに重複したデータを持つので、ID をキーに先勝ちで統合する。
    """
    model = {k: {} for k in ('Athletes', 'Competitions', 'Stages', 'Groups',
                             'Performances', 'Frames', 'Judges', 'JudgesPanels')}
    files = [os.path.join(meet_dir, 'event.json')]
    files += sorted(glob.glob(os.path.join(meet_dir, 'stage_*.json')))
    for path in files:
        if not os.path.exists(path):
            continue
        doc = _load(path)
        for key in model:
            for ident, value in (doc.get(key) or {}).items():
                if ident not in model[key]:
                    model[key][ident] = value
    return model


def _num(value):
    return value if isinstance(value, (int, float)) else None


def _is_ascii(text):
    return all(ord(ch) < 128 for ch in text or '')


# 国内大会の Competition には SexCategory が入っていない（国際大会だけ入る）。
# 区分名から補う。フィルタにも、表記ゆれ候補の絞り込みにも使う。
_SEX_WORDS = (
    ('female', ('女子', "Women", 'Female', 'WOMEN')),
    ('male', ('男子', 'Men', 'Male', 'MEN')),
)


def _sex(comp):
    raw = (comp.get('SexCategory') or '').strip().lower()
    if raw in ('male', 'female'):
        return raw
    title = comp.get('Title') or ''
    for sex, words in _SEX_WORDS:
        if any(w in title for w in words):
            return sex
    return ''


def _deducts(frame):
    """Deducts_G（12要素）を位置別に開く。

    戻り値: (positions[10], landing, extra_a, unaccounted)
      positions … スロット1〜技数のみ。技数を超えた位置は None（0と区別する）
      unaccounted … 技数を超えた位置に入っていた非ゼロの減点の合計
    """
    raw = frame.get('Deducts_G') or {}
    values = [raw.get(str(i), 0) or 0 for i in range(12)]
    n = frame.get('NElements')
    positions = []
    unaccounted = 0
    for i in range(10):
        if n is None:
            positions.append(None)
        elif i < n:
            positions.append(values[i])
        else:
            # 中断した演技では跳んでいない位置に 0 が入る。さらに中断した技の減点が
            # 技数を超えた位置に記録されることがある。どちらも位置別集計には使わない。
            positions.append(None)
            unaccounted += values[i]

    # 着地減点が実施点に乗るのは10技完遂のときだけ（§19.9 / README §0）。
    # 中断演技のスロット10は実施点に入らないので「未算入」に隔離する。
    if n == 10:
        landing = values[10]
    else:
        landing = None
        unaccounted += values[10]

    # スロット11（A）は全24大会で非ゼロが2件しかなく、意味が特定できていない。
    # 位置別集計には使わず、未算入としてだけ数える。
    unaccounted += values[11]
    return positions, landing, values[11], unaccounted


def _judges(frame):
    """ETotalsT_G から審判別Eと審判別HDを取り出す（プレースホルダ除去済み）。"""
    raw = frame.get('ETotalsT_G') or {}
    judge_e, judge_hd = {}, {}
    for slot, label in config.E_SLOTS.items():
        v = raw.get(str(slot))
        if v is not None and v not in config.JUDGE_PLACEHOLDERS:
            judge_e[label] = round(v / 10.0, 2)
    for slot, label in config.HD_SLOTS.items():
        v = raw.get(str(slot))
        if v is not None and v not in config.JUDGE_PLACEHOLDERS:
            judge_hd[label] = round(v / 10.0, 2)
    return judge_e, judge_hd


def _athlete_name(athlete):
    surname = (athlete.get('Surname') or '').strip()
    given = (athlete.get('GivenName') or '').strip()
    if surname and given:
        return '%s %s' % (surname, given)
    return (surname or given).strip()


def extract(meet_dir, year, kind_label):
    """1大会ぶんの (competition, performances, judges, panels) を返す。"""
    meta = _load(os.path.join(meet_dir, '_meta.json'))
    model = _merge_meet(meet_dir)

    group_stage = {int(gid): g.get('StageID') for gid, g in model['Groups'].items()}
    meet_id = 'st-%s' % meta['date'] + ('-%s' % _slug(meta['name']))

    competition = {
        'meet_id': meet_id,
        'date': meta['date'],
        'name': meta['name'],
        'level': meta.get('kind') or kind_label,     # 国内 / 国際
        'season': str(year),
        'source': 'sporttech',
        'official': config.SOURCES['sporttech']['official'],
        'source_url': meta.get('ovs_url', ''),
        'event_id': meta.get('event_id', ''),
        'fetched_at': meta.get('fetched_at', ''),
        'raw_dir': os.path.basename(meet_dir),
    }

    # ---- 審判（Phase 2 の器。埋まる大会は今すぐ埋める） --------------------
    # 審判IDは選手と同じく **氏名だけ** を鍵にする。大会ごとのIDにすると
    # 同じ審判が大会ごとに別人になり、「大会をまたいだ追跡」ができなくなる。
    judges = {}
    local_to_global = {}
    for jid, j in model['Judges'].items():
        name = normalize.normalize_name(_athlete_name(j))
        if not name:
            continue                     # 氏名のない枠は作らない（推測で埋めない）
        key = normalize.judge_id(name)
        local_to_global[int(jid)] = key
        judges[key] = {
            'judge_id': key,
            'name': name,
            'club': normalize.normalize_club(j.get('Representing') or ''),
            'meets': [meet_id],
        }

    panels = {}
    for pid, panel in model['JudgesPanels'].items():
        slots = panel.get('Judges') or []
        entry = {'panel_id': int(pid), 'title': panel.get('Title', ''),
                 'meet_id': meet_id, 'slots': {}}
        for slot, local_id in enumerate(slots):
            if local_id is None or local_id < 0:
                continue
            entry['slots'][str(slot)] = local_to_global.get(local_id)
        # E判定の対応のみ確定している。他のスロットの役割は未特定なので raw のまま持つ。
        entry['e_slots'] = {label: entry['slots'].get(str(slot))
                            for slot, label in config.E_SLOTS.items()
                            if entry['slots'].get(str(slot))}
        panels['%s|panel%s' % (meet_id, pid)] = entry

    stage_panel = {}
    for sid, st in model['Stages'].items():
        pid = st.get('JudgesPanelID', -1)
        stage_panel[int(sid)] = ('%s|panel%s' % (meet_id, pid)) if pid is not None and pid >= 0 else None

    # ---- 演技 ---------------------------------------------------------------
    performances = []
    for fid, frame in model['Frames'].items():
        state = frame.get('State')
        if state == 0:
            continue
        has_n = 'NElements' in frame
        n_elements = frame.get('NElements')
        if has_n and not n_elements:
            continue        # 未使用枠。State 3（未出場）・State 4（失格）とも除外
        if not has_n:
            n_elements = None    # 出場記録として残すが技数は空欄

        perf = model['Performances'].get(str(frame.get('PerformanceID')))
        if perf is None:
            continue
        stage_id = group_stage.get(perf.get('GroupID'))
        stage = model['Stages'].get(str(stage_id)) or {}
        comp = model['Competitions'].get(str(stage.get('CompetitionID'))) or {}

        discipline = config.DISCIPLINE.get(comp.get('Discipline'), '不明')
        individual = discipline == config.PHASE1_DISCIPLINE

        athlete_ids = perf.get('Athletes') or []
        names, clubs = [], []
        birth = None
        for aid in athlete_ids:
            a = model['Athletes'].get(str(aid)) or {}
            names.append(_athlete_name(a))
            clubs.append((a.get('Representing') or '').strip())
            if birth is None:
                birth = (a.get('DateOfBirth') or '')[:10] or None

        kind = stage.get('Kind')
        round_label = config.STAGE_KIND.get(kind)

        # 単位換算は個人トランポリンでのみ検証済み。他種目は生値のみ保持する。
        def scaled(field, div):
            v = _num(frame.get(field))
            return round(v / div, 3) if (individual and v is not None) else None

        positions, landing, extra_a, unaccounted = _deducts(frame)
        judge_e, judge_hd = _judges(frame)
        panel_key = stage_panel.get(stage_id)

        performances.append({
            'performance_id': '%s|f%s' % (meet_id, fid),
            'meet_id': meet_id,
            'date': meta['date'],
            'meet_name': meta['name'],
            'source': 'sporttech',
            'official': config.SOURCES['sporttech']['official'],
            'discipline': discipline,
            'category': (comp.get('Title') or '').strip(),
            'sex': _sex(comp),
            'age_group': (comp.get('AgeGroup') or '').strip(),
            'round': round_label,
            'round_raw': kind,
            'routine': None,        # 生JSONに本数の明示がないので後段で採番する
            'athlete_name': names[0] if len(names) == 1 else ' / '.join(names),
            'athlete_names': names,
            'club': clubs[0] if len(clubs) == 1 else ' / '.join(clubs),
            'birth_date': birth,    # 保存はするが名寄せの鍵にも表示にも使わない
            'rank': perf.get('Rank_G') if perf.get('Ranked') is not False else None,
            'total': scaled('MarkTTT_G', 1000.0),
            'D': scaled('DifficultyT_G', 10.0),
            'E': scaled('ETotalT_G', 10.0),
            'T': scaled('TimeTMS_G', 1000.0),
            'HD': scaled('Displacement_G', 100.0),
            'Bonus': scaled('BonusT', 10.0),
            'Pen': scaled('PenaltyT', 10.0),
            'DPen': scaled('DPenaltyT', 10.0),
            'n_elements': n_elements,
            'deduct_positions': positions,
            'deduct_landing': landing,
            'deduct_extra_a': extra_a,
            'deduct_unaccounted': unaccounted,
            'deduct_unit': 'median2_sum_tenths',
            'judge_E': judge_e,
            'judge_HD': judge_hd,
            'panel_key': panel_key,
            'state': state,
            'stage_id': stage_id,
            'frame_id': int(fid),
            'perf_id_raw': frame.get('PerformanceID'),
            'raw': {
                'Mark': frame.get('MarkTTT_G'), 'D': frame.get('DifficultyT_G'),
                'E': frame.get('ETotalT_G'), 'T': frame.get('TimeTMS_G'),
                'HD': frame.get('Displacement_G'), 'Bonus': frame.get('BonusT'),
                'Pen': frame.get('PenaltyT'), 'DPen': frame.get('DPenaltyT'),
            },
            'provenance': {
                'source': 'sporttech',
                'source_url': meta.get('ovs_url', ''),
                'raw_filename': '%s/stage_%s.json' % (os.path.basename(meet_dir), stage_id),
                'imported_at': meta.get('fetched_at', ''),
                'parser_version': config.PARSER_VERSION,
                'correction_flag': '',
            },
        })

    _number_routines(performances)
    return competition, performances, judges, panels


def _number_routines(performances):
    """同一 Performance（＝同一選手・同一ステージ）内で本数を採番する。

    Frames は演技順に ID が振られているので FrameID 昇順でよい。
    """
    groups = {}
    for p in performances:
        groups.setdefault((p['stage_id'], p['perf_id_raw']), []).append(p)
    for items in groups.values():
        for i, p in enumerate(sorted(items, key=lambda x: x['frame_id']), start=1):
            p['routine'] = i


def _slug(text):
    """大会IDに使う短い識別子。

    大会名をそのまま使うと日本語のファイル名（data/details/<meet_id>.json）になり、
    サーバや環境によってURLの扱いが変わって事故になる。ASCIIだけにする。
    大会名は competitions.json に持っているので、IDが読めなくても困らない。
    """
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:6]


def load_all():
    """全大会を読み、(competitions, performances, judges, panels) を返す。"""
    competitions, performances, judges, panels = [], [], {}, {}
    for year, folder, kind_label in config.SPORTTECH_DIRS:
        base = os.path.join(config.RAW_ROOT, year, folder)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            meet_dir = os.path.join(base, name)
            if not os.path.isdir(meet_dir):
                continue
            comp, perfs, jd, pn = extract(meet_dir, year, kind_label)
            competitions.append(comp)
            performances.extend(perfs)
            for key, judge in jd.items():
                # 同じ審判が複数大会に出るので、出場大会は足していく
                existing = judges.get(key)
                if existing is None:
                    judges[key] = judge
                    judge['names_seen'] = [judge['name']]
                    continue
                existing['meets'].extend(judge['meets'])
                if judge['name'] not in existing['names_seen']:
                    existing['names_seen'].append(judge['name'])
                # judge_overrides で日本語表記とローマ字表記を統合した場合、
                # 表示は日本語表記を優先する。国際大会の所属は国名（JPN）でしかないので、
                # 所属も日本語表記の記録側を優先する。
                if _is_ascii(existing['name']) and not _is_ascii(judge['name']):
                    existing['name'] = judge['name']
                jp_side = not _is_ascii(judge['name'])
                if judge['club'] and (jp_side or not existing['club']):
                    if jp_side or _is_ascii(existing['name']):
                        existing['club'] = judge['club']
            panels.update(pn)
    return competitions, performances, judges, panels
