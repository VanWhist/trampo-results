# -*- coding: utf-8 -*-
"""同じ大会の文字のPDF（2023東日本の決勝・2023イーストジャパンの他区分）を ETL の読み方で読み、
氏名・所属の正解の参照にする。"""
import json
import logging
import os
import sys

import files  # noqa: F401  （リポジトリを import できるようにする）
logging.disable(logging.CRITICAL)
import pdfplumber
from etl import config
from etl.sources import higashinihon_pdf as H

out = {}
for m in H.load_manifest()['meets']:
    if m['meet_id'] not in ('ej-2023-09-08', 'ej-2023-11-26'):
        continue
    for f in m['files']:
        with pdfplumber.open(os.path.join(config.RAW_ROOT, *m['raw_dir'].split('/'), f)) as pdf:
            head, cols, ath = H.parse_pdf(pdf)
        out[m['meet_id'] + '|' + f] = [
            {'rank': a['rank'], 'name': H.clean_name(a['name']), 'raw': a['name'], 'club': a['club'],
             'n': len(a['routines']), 'agg': a['agg'], 'scores': [r.get('Score') for r in a['routines']]}
            for a in ath]
        print(m['meet_id'], f, len(ath), cols[-1])
json.dump(out, open('ejtext.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=0)
