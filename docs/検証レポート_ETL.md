# ETL検証レポート

dataVersion: `2026-08-14-01`

```
10706 records passed / 11 warnings / 0 errors
```

## 集計

| 項目 | 値 |
|---|---|
| 件数_sporttech | 5969 |
| 件数_osaka_pweb | 1293 |
| 件数_nishinihon | 913 |
| 大会別件数 | 既存 25大会は前回と一致／新規 0大会／消えた大会 0 |
| E検算 | 8158件中 0件が要確認 |
| 合計検算 | 7908件中 0件が要確認 |
| 値域外 | 0件 |
| 欠測_合計点 | 266件 |
| 欠測_順位 | 1293件 |
| 欠測_所属 | 1293件 |
| 欠測_技数 | 9件 |
| 中断演技 | 1203件 |
| 表示が壊れた行(大阪府) | 15件 |
| 採点未確定(State=2) | 1件 |
| 審判別Eあり | 7261件 |
| 審判名まで特定 | 3662件 |
| 審判の表記ゆれ候補 | 1名（ローマ字表記で所属JPN） |
| 選手の表記ゆれ候補 | 14名（うち候補が1人に絞れたもの 10名／統合済み 0名） |
| 選手数 | 1639名 |
| 大会数 | 30 |
| 審判数 | 169名 |
| パネル数 | 149 |
| 選手数_sporttech | 1187名 |
| 選手数_osaka_pweb | 234名 |
| 選手数_nishinihon | 391名 |

## 警告（11件）

- 選手の表記ゆれ … 10件
- 審判の表記ゆれ … 1件

<details><summary>内訳</summary>

- 審判の表記ゆれ AIDA Yasushi（所属JPN）は国内大会では日本語表記の別IDになっている可能性があります。judge_overrides.json で統合できます
- 選手の表記ゆれ KISHI Daiki は 岸 大貴 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ MATSUMOTO Yusei は 松本 悠生 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ MISAWA Yuka は 三澤 優華 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ MIYANO Hayato は 宮野 隼人 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ MORI Hikaru は 森 ひかる と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ NISHIOKA Ryusei は 西岡 隆成 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ SAKURAI Ena は 櫻井 愛菜 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ SAWADA Momo は 澤田 守杏 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ TANAKA Saki は 田中 沙季 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます
- 選手の表記ゆれ UNNO Hiroto は 海野 大透 と同一人物の可能性があります（生年月日一致・出場日の重なりなし）。athlete_overrides.json で統合できます

</details>
