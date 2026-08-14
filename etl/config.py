# -*- coding: utf-8 -*-
"""ETL全体の設定。パスと定数だけを置く。

このETLは「正しさ」をすべてここ（Python側）に閉じ込める。
アプリ（js/）は正規化済みJSONを表示するだけで、条件分岐を持たない。
"""
import os

# ---- 入力（読むだけ。絶対に書き換えない） ----------------------------------
RAW_ROOT = r'<作業フォルダ>\トランポリンルール\大会リザルト'

SPORTTECH_DIRS = [
    ('2025', 'sporttech_国内大会', '国内'),
    ('2025', 'sporttech_国際大会', '国際'),
    ('2026', 'sporttech_国内大会', '国内'),
    ('2026', 'sporttech_国際大会', '国際'),
]

CSV_SPORTTECH = os.path.join(RAW_ROOT, '_sporttech_全演技_ジャッジ別_v2.csv')
CSV_OSAKA_JUDGE = os.path.join(RAW_ROOT, '_大阪府pweb_ジャッジ明細_統合.csv')
CSV_OSAKA_SUMMARY = os.path.join(RAW_ROOT, '_大阪府pweb_演技サマリー.csv')
CSV_NISHI = os.path.join(RAW_ROOT, '_西日本53th_全演技.csv')

# ---- 出力 ------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA_OUT = os.path.join(REPO, 'data')
OVERRIDES = os.path.join(HERE, 'athlete_overrides.json')
JUDGE_OVERRIDES = os.path.join(HERE, 'judge_overrides.json')
EXPECTED_COUNTS = os.path.join(HERE, 'expected_counts.json')
REPORT_MD = os.path.join(REPO, 'docs', '検証レポート_ETL.md')
VARIANTS_MD = os.path.join(REPO, 'docs', '選手の表記ゆれ候補.md')

PARSER_VERSION = '1.0.0'

# ---- 出典 ------------------------------------------------------------------
# official=True … 協会・公式運営システム / False … 非公式（引用時に明示が必要）
SOURCES = {
    'sporttech': {
        'label': 'sporttech.io（日本体操協会 計時システム）',
        'official': True,
        'base_url': 'https://sporttech.io/',
    },
    'osaka_pweb': {
        'label': 'トランポリン応援団（trampoline.pweb.jp）',
        'official': False,
        'base_url': 'https://trampoline.pweb.jp/',
    },
    'nishinihon': {
        'label': '西日本トランポリン協会',
        'official': True,
        'base_url': 'https://trampoline-west.jp/',
    },
}

# ---- 種目 ------------------------------------------------------------------
# 親Competition の Discipline を正とする（Performance側は常に0になっている例がある）
DISCIPLINE = {0: '個人', 1: 'シンクロ', 2: 'DMT', 3: 'TUM'}
# Phase 1 で画面に出すのは個人のみ。データは捨てずフィルタで外す。
PHASE1_DISCIPLINE = '個人'

# ---- ラウンド --------------------------------------------------------------
# Stage.Kind の意味。
#   0 … 予選、3 … 決勝（v2 CSV と全件一致で確定）
#   6 … 準決勝（個人でKind=6が出るのはW杯・全日本選手権など予選→準決勝→決勝の大会だけで、
#              各区分24名前後。予選通過者数と一致するため準決勝と判断した）
#   7・8 … DMT/TUM にのみ出現。Phase 1 は個人のみなので生値のまま unknown 扱いにする。
STAGE_KIND = {0: '予選', 3: '決勝', 6: '準決勝'}

# ---- E審判スロット ---------------------------------------------------------
# ETotalsT_G のスロット番号 → E番号。実データで有効値が観測されたのは 0,1,2,3,4,7 のみ。
# （スロット n → E(n+1)。E6・E7 は常に空で、6審判制では E8 に6人目が入る）
E_SLOTS = {0: 'E1', 1: 'E2', 2: 'E3', 3: 'E4', 4: 'E5', 7: 'E8'}
# ETotalsT_G のスロット 10・11 は水平移動(HD)の審判
HD_SLOTS = {10: 'HD1', 11: 'HD2'}
# 「審判なし」のプレースホルダ。10.0点ではない。
JUDGE_PLACEHOLDERS = (0, 100)

# ---- 検算の許容幅 ----------------------------------------------------------
# Eを式から導出しない。式は検算＋フラグにのみ使う。
TOL_E = 0.001          # E = 2N − (減点計)/10 の許容差
TOL_TOTAL = 0.005      # 合計 = D+E+T+HD+Bonus−Pen−DPen の許容差
TOL_TOTAL_WARN = 3.0   # これを超えたらerror、以内ならwarningで「要確認」フラグ

# ---- ジャッジ分析 ----------------------------------------------------------
JUDGE_MIN_N = 100      # 母数がこれ未満の審判は傾向値を出さない（「データ不足」）
JUDGE_STRICT = -0.10   # 平均パネル差がこれ以下 → 辛め
JUDGE_LENIENT = 0.10   # これ以上 → 甘め

# ---- 表示モード ------------------------------------------------------------
# 本アプリにおける表示モードはアクセス権限ではなく表示モードである。
# GitHub Pages上に配置したJSON・JavaScriptは利用者から直接取得可能であるため、
# 非公開であることを前提とした個人情報・分析データはビルド成果物に含めないこと。
DISPLAY_MODE_DEFAULT = 'all'   # Phase 1 は出し分けをしない（フラグだけ用意）
