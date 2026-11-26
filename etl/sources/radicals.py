# -*- coding: utf-8 -*-
"""PDF が漢字を「部首」の文字コードで持っているときに、ふつうの漢字へ戻す。

東日本（2022・2026年版）と西日本 第54回の PDF は、一部の漢字を CJK部首補助（U+2E80〜2EFF）や
康熙部首（U+2F00〜2FDF）の文字コードで持っている。見た目は同じだが、そのままだと
同じ選手が別人になる（⻑澤 と 長澤、⻘戶 と 青戸）。

  ・CJK部首補助は NFKC で戻らないので、実データに現れたものを RADICALS で置き換える
  ・康熙部首は NFKC で戻るが、U+2F3E（戸）・U+2FCA（黒）は日本の字ではなく「戶」「黑」になるので、
    NFKC の前に KANGXI_JP で置き換える
  ・それ以外で NFKC 後に日本で使わない字形（JIS X 0208 に無い字）になる部首が出たら止める
"""
import re
import unicodedata

# 実データに現れたもの（東日本 2026-11-27、西日本 第54回 2026-11-27 に確認）。
RADICALS = {'⻑': '長',   # ⻑ → 長
            '⻄': '西',   # ⻄ → 西
            '⻫': '斉',   # ⻫ → 斉
            '⻘': '青',   # ⻘ → 青
            '⺠': '民',   # ⺠ → 民（会場名 ヤマト市民体育館）
            '⻁': '虎',   # ⻁ → 虎（西日本 第54回 鈴木 虎汰・虎谷 京佳）
            '⻤': '鬼',   # ⻤ → 鬼（西日本 第54回 百目鬼 あずさ）
            '⻯': '竜'}   # ⻯ → 竜（西日本 第54回 天竜トランポリンクラブ）

KANGXI_JP = {chr(0x2F3E): chr(0x6238),   # ⼾ → 戸（NFKC だと 戶 U+6236 になる）
             chr(0x2FCA): chr(0x9ED2)}   # ⿊ → 黒（NFKC だと 黑 U+9ED1 になる。西日本 第54回 黒屋 澪）

RADICAL_RANGE = re.compile(r'[⺀-⻿⼀-⿟]')   # CJK部首補助・康熙部首


def to_unified(text):
    """部首の文字を置き換えてから NFKC をかけた文字列を返す。"""
    text = text or ''
    for old, new in list(KANGXI_JP.items()) + list(RADICALS.items()):
        text = text.replace(old, new)
    # 判定は「NFKC 後の字が Shift_JIS（JIS X 0208）で書けるか」。
    for ch in set(text):
        if 0x2E80 <= ord(ch) <= 0x2FDF:
            try:
                unicodedata.normalize('NFKC', ch).encode('shift_jis')
            except UnicodeEncodeError:
                raise ValueError('日本で使わない字形になる部首の文字があります'
                                 '（radicals.py の KANGXI_JP に追加が必要）: %r' % ch)
    return unicodedata.normalize('NFKC', text)     # ⽇ ⼈ ⼥（康熙部首）はここで戻る


def check_no_radicals(text, what):
    """氏名・所属に部首の文字が残っていたら止める（残ると同じ選手が別人として登録される）。"""
    if RADICAL_RANGE.search(text or ''):
        raise ValueError('部首の文字コードが%sに残っています（radicals.py の RADICALS に追加が必要）: %r'
                         % (what, text))
