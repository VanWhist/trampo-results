// 表示モードのフラグ。
//
// Phase 1 では出し分けを実装せず、フラグだけ用意している（既定：全部表示）。
// 本人に見せる段になったら Phase 2 で切り替えを入れる。
//
// 本アプリにおける表示モードはアクセス権限ではなく表示モードである。
// GitHub Pages上に配置したJSON・JavaScriptは利用者から直接取得可能であるため、
// 非公開であることを前提とした個人情報・分析データはビルド成果物に含めないこと。

export const DISPLAY_MODE = 'all';   // 'all' | （Phase 2 で 'athlete' などを追加予定）

export function showJudgeNames() {
  return DISPLAY_MODE === 'all';
}
