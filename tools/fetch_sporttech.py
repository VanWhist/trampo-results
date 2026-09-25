# -*- coding: utf-8 -*-
"""sporttech.io から大会の生データを取得して、生データフォルダに保存する。

    python -m tools.fetch_sporttech <event_id> [<event_id> ...]
    python -m tools.fetch_sporttech --registry docs/大会台帳_たたき台.csv --since 2015

**ETL（etl/）は生データを読むだけ。取得はこちらの役目。** 両者を分けておく。

守ること:
  ・既存の大会フォルダには**書き込まない**（あればスキップ）。原本は一度保存したら変えない
  ・取れるものは全部取る。いま画面に出さない項目（審判名・種目の別）も捨てない
    （取った時点で捨てたものは、後から取り戻せないことがある）
  ・公開APIに1件ずつ、間隔を空けて取りに行く
  ・何をいつどこから取ったかを _meta.json に残す（取得URL・日時・SHA-256）

保存の形は既存の生データに合わせる。取り込み側（etl/sources/sporttech.py）は
event.json と stage_*.json を合体して読むので、全部入りの event.json を1つ置けば足りる。
実際の大会で、既存の生データと取り込み結果が一致することを確かめてから使う（--verify）。
"""
import argparse
import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etl import config  # noqa: E402

API = 'https://sporttech.io/events/%s/ovs/api/event?'
# fetch_group_performances が無いと演技とフレームが返ってこない（2026-09-25 に確認）
QUERY = '&'.join('%s=true' % k for k in (
    'fetch_event_competitions', 'fetch_competition_stages', 'fetch_stage_groups',
    'fetch_group_performances', 'fetch_performance_athletes', 'fetch_performance_frames',
    'fetch_event_judges', 'fetch_event_judges_panels', 'fetch_judges_panel_judges',
    'fetch_stage_medalists', 'fetch_event_videos'))
LIST_API = 'https://sporttech.io/api/events/?fetch_organizations=true&year=%d'
UA = {'User-Agent': 'trampo-results archive (personal, non-commercial)'}
WAIT = 1.5          # 秒。小さなサービスなので間隔を空ける
JAPAN = 392         # sporttech の country_id


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _safe(name):
    """フォルダ名に使えない文字と括弧を _ にする（既存フォルダの付け方に合わせる）。"""
    name = re.sub(r'[\\/:*?"<>|【】\s]+', '_', name)
    return re.sub(r'_+', '_', name).strip('_')


def event_index(years):
    """event_id → 一覧APIの情報（開始日・名前・国内か）。"""
    out = {}
    for year in years:
        j = json.loads(_get(LIST_API % year))
        orgs = j.get('organization') or {}
        for e in (j.get('event') or {}).values():
            host = next((o for o in e.get('organizations') or [] if o.get('participation') == 'host'),
                        (e.get('organizations') or [None])[0])
            org = orgs.get(host['organization_id']) if host else {}
            out[e['event_id']] = {
                'date': e['begin_date'][:10], 'end': e['end_date'][:10],
                'name': e.get('en_name') or '', 'rules': e.get('rules') or '',
                'domestic': (org or {}).get('country_id') == JAPAN,
                'sport': e.get('sport'),
            }
        time.sleep(WAIT)
    return out


def target_dir(info, root=None):
    root = root or config.RAW_ROOT
    kind = '国内' if info['domestic'] else '国際'
    return os.path.join(root, info['date'][:4], 'sporttech_%s大会' % kind,
                        '%s_%s' % (info['date'], _safe(info['name'])))


def fetch(event_id, info, root=None):
    """1大会を取得して保存する。既にフォルダがあれば何もしない。"""
    dest = target_dir(info, root)
    if os.path.exists(dest):
        return 'skip', dest
    url = API % event_id + QUERY
    body = _get(url)
    doc = json.loads(body)
    if not (doc.get('Performances') and doc.get('Frames')):
        return 'empty', dest            # 演技の無い大会（中止・未入力など）はフォルダを作らない
    os.makedirs(dest)
    with io.open(os.path.join(dest, 'event.json'), 'wb') as fh:
        fh.write(body)
    meta = {
        'event_id': event_id, 'date': info['date'], 'end_date': info['end'],
        'name': info['name'], 'kind': '国内' if info['domestic'] else '国際',
        'rules': info['rules'],
        'ovs_url': 'https://sporttech.io/events/%s/ovs/event/TRA' % event_id,
        'stages': sorted(int(s) for s in (doc.get('Stages') or {})),
        'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'fetched_from': url,
        'sha256': hashlib.sha256(body).hexdigest(),
        'counts': {k: len(doc.get(k) or {}) for k in
                   ('Athletes', 'Performances', 'Frames', 'Judges', 'JudgesPanels', 'Stages')},
        'fetcher': 'trampo-results/tools/fetch_sporttech.py',
    }
    with io.open(os.path.join(dest, '_meta.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return 'ok', dest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('event_ids', nargs='*')
    ap.add_argument('--registry', help='大会台帳のCSV。原本が sporttech で未取得のものを取る')
    ap.add_argument('--since', type=int, default=2015)
    ap.add_argument('--root', help='保存先（検証用に別の場所へ）')
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')

    ids = list(args.event_ids)
    if args.registry:
        with io.open(args.registry, encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                if (r['原本'] == 'sporttech' and r['手元の原本'] == '×'
                        and int(r['開始日'][:4]) >= args.since):
                    ids.append(r['識別子'])
    years = range(args.since, datetime.date.today().year + 1)
    index = event_index(years)
    results = {'ok': 0, 'skip': 0, 'empty': 0, 'error': 0}
    for n, eid in enumerate(ids, start=1):
        info = index.get(eid)
        if info is None:
            print('  ×  %s 一覧に見つからない' % eid)
            results['error'] += 1
            continue
        try:
            status, dest = fetch(eid, info, args.root)
        except Exception as e:           # 1件の失敗で全体を止めない。件数で報告する
            status, dest = 'error', str(e)
        results[status] += 1
        print('%3d/%d %-5s %s %s' % (n, len(ids), status, info['date'], info['name'][:40]))
        if status == 'error':
            print('       ', dest)
        time.sleep(WAIT)
    print('結果', results)
    return 0 if not results['error'] else 1


if __name__ == '__main__':
    sys.exit(main())
