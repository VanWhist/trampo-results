# -*- coding: utf-8 -*-
"""書き起こす画像のPDFの一覧（etl/higashinihon_files.json の image_only_files）。"""
import json
import os
import sys

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, REPO)
from etl import config  # noqa: E402  原本フォルダ（RAW_ROOT。環境変数 TRAMPO_RAW_ROOT で変えられる）

RAW = config.RAW_ROOT.replace(os.sep, '/') + '/'
MEETS = ('ej-2023-09-08', 'ej-2023-11-26', 'ej-2024-09-20')


def image_files():
    m = json.load(open(os.path.join(REPO, 'etl', 'higashinihon_files.json'), encoding='utf-8'))['meets']
    out = []
    for x in m:
        if x['meet_id'] in MEETS:
            for f in x.get('image_only_files', []):
                out.append((x['meet_id'], f, RAW + x['raw_dir'] + '/' + f))
    return out
