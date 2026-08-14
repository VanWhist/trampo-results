// データの読み込み。
// manifest.json の dataVersion をクエリに付けて読む。付けないと、更新したのに
// ブラウザが古いJSONを使い続けて「反映されない」事故が起きる。
//
// このアプリは表示するだけで、正しさの判断（列ずれ・名寄せ・単位換算・欠測処理）は
// すべてETL側（Python）で済ませてある。ここに条件分岐を増やさないこと。

// js/ の1つ上（リポジトリのルート）を基準にする
const BASE = new URL('../', import.meta.url).href;
const cache = new Map();

let manifestPromise = null;

export function manifest() {
  if (!manifestPromise) {
    manifestPromise = fetch(BASE + 'data/manifest.json', { cache: 'no-cache' })
      .then((r) => {
        if (!r.ok) throw new Error('manifest.json が読めません (' + r.status + ')');
        return r.json();
      });
  }
  return manifestPromise;
}

async function load(path) {
  if (cache.has(path)) return cache.get(path);
  const m = await manifest();
  const p = fetch(BASE + 'data/' + path + '?v=' + encodeURIComponent(m.dataVersion))
    .then((r) => {
      if (!r.ok) throw new Error(path + ' が読めません (' + r.status + ')');
      return r.json();
    });
  cache.set(path, p);
  return p;
}

export const competitions = () => load('competitions.json');
export const athletes = () => load('athletes.json');
export const judges = () => load('judges.json');
export const panels = () => load('panels.json');
export const judgeDiff = () => load('summary/judge_panel_diff.json');
export const deductionSummary = () => load('summary/deductions.json');
export const details = (meetId) => load('details/' + meetId + '.json');

// 演技一覧は年単位で遅延ロードする。Phase 1 の画面は個人しか出さないので
// シンクロ・DMT・タンブリングのファイル（-other）は読まない。
export async function performances() {
  const m = await manifest();
  const meets = new Map((await competitions()).map((c) => [c.meet_id, c]));
  const years = await Promise.all(m.years.map((y) => load('performances/' + y + '.json')));
  const rows = [];
  for (const list of years) {
    for (const p of list) {
      const c = meets.get(p.meet_id);
      rows.push({
        ...p,
        date: c.date,
        meet_name: c.name,
        source: c.source,
        official: c.official,
        level: c.level,
        season: c.season,
      });
    }
  }
  return rows;
}

export async function athleteMap() {
  const list = await athletes();
  return new Map(list.map((a) => [a.athlete_id, a]));
}

export async function meetMap() {
  const list = await competitions();
  return new Map(list.map((c) => [c.meet_id, c]));
}
