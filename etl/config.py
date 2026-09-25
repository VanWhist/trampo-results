# -*- coding: utf-8 -*-
"""ETL全体の設定。パスと定数だけを置く。

このETLは「正しさ」をすべてここ（Python側）に閉じ込める。
アプリ（js/）は正規化済みJSONを表示するだけで、条件分岐を持たない。
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# ---- 入力（読むだけ。絶対に書き換えない） ----------------------------------
# 生データの置き場所。既定はリポジトリの1つ上の「トランポリンルール\大会リザルト」。
# 別の場所に置いている場合は環境変数 TRAMPO_RAW_ROOT で指定する。
#     Windows PowerShell:  $env:TRAMPO_RAW_ROOT = "D:\...\大会リザルト"
#     Git Bash:            export TRAMPO_RAW_ROOT="/d/.../大会リザルト"
# 個人のフォルダ構成をリポジトリに残さないため、絶対パスは直接書かない。
RAW_ROOT = os.environ.get('TRAMPO_RAW_ROOT') or os.path.normpath(
    os.path.join(REPO, os.pardir, 'トランポリンルール', '大会リザルト'))

# 生データにある年をすべて読む。年を足すたびにここを直す運用にすると、
# 取得したのに取り込まれていない年が黙って出る（2026-09-25 に2015〜2024年を追加）。
SPORTTECH_KINDS = (('sporttech_国内大会', '国内'), ('sporttech_国際大会', '国際'))


def sporttech_dirs():
    if not os.path.isdir(RAW_ROOT):
        return []
    years = sorted(y for y in os.listdir(RAW_ROOT) if re.fullmatch(r'\d{4}', y))
    return [(y, folder, kind) for y in years for folder, kind in SPORTTECH_KINDS]


# ---- 採点規則の世代 ----------------------------------------------------------
# sporttech は大会ごとに規則の版を持つ（'TRA FIG 2022' / 'TRA FIG 2017' / 'TRA FIG' など）。
# 2017年版より前（'TRA FIG'・'TRA DEN'・'TRA FIG WCh' など）は得点の組み立てが違う。
#   ・水平移動（HD）が存在しない
#   ・E は審判1人ぶんの尺度（10点満点）で、合計には3倍して入る
#       合計 = D + T + 3×E + Bonus − Pen − DPen      （旧規則 4,534演技で100%成立）
#   ・技ごとの減点も1人ぶんの尺度。今の「中央2審判の和」とは単位が違う（混ぜると約2倍ずれる）
# 2026-09-25 に 2015〜2026年の全大会で式を確かめて決めた。
RULES_CURRENT = 'current'      # FIG 2017年版以降
RULES_PRE2017 = 'pre2017'


def rules_family(rules, date):
    """規則の版の文字列から世代を返す。版が無い（以前の取得）ときは開催日で決める。"""
    if rules:
        return RULES_CURRENT if re.search(r'20(1[7-9]|[2-9]\d)', rules) else RULES_PRE2017
    return RULES_CURRENT if (date or '') >= '2017-03' else RULES_PRE2017

CSV_SPORTTECH = os.path.join(RAW_ROOT, '_sporttech_全演技_ジャッジ別_v2.csv')
CSV_OSAKA_JUDGE = os.path.join(RAW_ROOT, '_大阪府pweb_ジャッジ明細_統合.csv')
CSV_OSAKA_SUMMARY = os.path.join(RAW_ROOT, '_大阪府pweb_演技サマリー.csv')
CSV_NISHI = os.path.join(RAW_ROOT, '_西日本53th_全演技.csv')

# ---- 出力 ------------------------------------------------------------------
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
# Stage.Kind の意味。sporttech の画面プログラム（static/TRA/script.min.js）にある対応表:
#   Qualification 0 / QuarterFinal 1 / SemiFinal 2 / Final 3 / TeamSemiFinal 4 /
#   TeamFinal 5 / Qualification2 6 / Final2 7 / Final1 8          （2026-09-25 に確認）
#
#   0 … 予選、3 … 決勝（v2 CSV と全件一致で確定）
#   1・2・4・5・7・8 … 上の公式の対応表どおり。2015〜2017年の大会で 1・2 が出る
#   6 … **公式の名前は「Qualification2（予選2）」。** Phase 1 では構造（各区分24名前後で
#        予選→6→決勝）から「準決勝」と推定して表示していた。どちらにするかは未決
#        （表示と、ジャッジ分析の「予選通過者」の定義に関わるため、決めるまで変えない）
STAGE_KIND = {0: '予選', 1: '準々決勝', 2: '準決勝', 3: '決勝', 4: '団体準決勝',
              5: '団体決勝', 6: '準決勝', 7: '決勝2', 8: '決勝1'}

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
