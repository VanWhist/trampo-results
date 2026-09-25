# -*- coding: utf-8 -*-
"""大阪府の成績システム（トランポリン応援団 / trampoline.pweb.jp）から大会の生HTMLを取得する。

    python tools/fetch_osaka.py --lists            # 成績一覧ページだけ（先にこちら）
    python tools/fetch_osaka.py --details          # 保存済みの一覧から、演技ごとの明細ページ
    python tools/fetch_osaka.py --lists --since 2016 --wait 3

**相手は小さな運営サーバ。** 1回ずつ間隔を空けて取りに行く（既定3秒）。
明細は演技1本ごとに1ページあり数が多いので、一覧とは分けて、時間を置いて取る。

守ること:
  ・既存のファイルには書き込まない（あれば飛ばす）。途中で止まっても続きから再開できる
  ・何をいつどこから取ったかを大会フォルダの _provenance.csv に残す（SHA-256つき）
  ・スタートリストは結果ではないので取らない
  ・テスト用の大会（システムテスト・デモ・スコアシステム比較）は取らない

手順は 2026-09-25 に実際の大会で確かめたもの:
  1. result.php?taikaicode=0 に i01=<大会> ・ entry=選択完了 を POST（セッションを使う）
  2. 同じURLに i11=<区分> ・ entry5=区分選択完了 を POST（entry を送ると大会選択に戻る）
  3. 一覧の Sum. 列のリンク result.php?taikaicode=..&wsyozoku=A2&wmeisai=<本目><氏名> を GET
     （氏名は生の文字で入っているので、バイト列のまま URL エンコードする）
"""
import argparse
import csv
import datetime
import hashlib
import http.cookiejar
import io
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etl import config  # noqa: E402

BASE = 'https://www.trampoline.pweb.jp/php/result.php?taikaicode=0'
PHP = 'https://www.trampoline.pweb.jp/php/'
UA = {'User-Agent': 'trampo-results archive (personal, non-commercial)'}
SKIP_MEETS = ('システムテスト', 'デモ大会', 'スコアシステム比較')
SKIP_CATEGORIES = ('ｽﾀｰﾄ', 'スタート')


class Site:
    def __init__(self, wait):
        self.wait = wait
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.count = 0

    def get(self, url, data=None):
        """1回取りに行く。接続を切られたら待ち時間を延ばし、3回続いたら止まる。

        2026-09-25 に、短時間に続けてアクセスしたところで接続を強制的に切られた。
        相手の防御に当たったと考えて、押し切らずに引く。
        """
        body = urllib.parse.urlencode(data).encode('utf-8') if data else None
        for attempt, backoff in enumerate((0, 120, 600)):
            if backoff:
                print('    接続できないので %d 秒待ってやり直す（%d回目）' % (backoff, attempt + 1),
                      flush=True)
                time.sleep(backoff)
            try:
                with self.op.open(urllib.request.Request(url, data=body, headers=UA),
                                  timeout=120) as r:
                    raw = r.read()
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
                last = err
        else:
            raise SystemExit('3回続けて接続できなかったので止める（相手の負担を避ける）: %s' % last)
        self.count += 1
        time.sleep(self.wait)
        return raw


def _text(raw):
    return raw.decode('utf-8', 'replace')


def _options(html, name):
    sel = re.search(r'(?is)<select[^>]*name="%s".*?</select>' % name, html)
    if not sel:
        return []
    # OPTION は大文字で閉じタグが無い。次の OPTION か </select> までを1件とする
    return [(v, re.sub(r'\s+', ' ', t).strip()) for v, t in re.findall(
        r'(?is)<option[^>]*value=["]?([^"\s>]+)["]?[^>]*>(.*?)(?=<option|</select>)', sel.group(0))
        if v != '--']


def _safe(name):
    name = unicodedata.normalize('NFKC', name)
    name = name.replace('?', '_')                      # 元HTMLの文字化け（～）
    name = re.sub(r'[\\/:*"<>|\s　]+', '', name)
    return name


def meet_dir(date, name):
    return os.path.join(config.RAW_ROOT, date[:4], '大阪府_pweb', '%s_%s' % (date, _safe(name)))


def _provenance(folder, row):
    path = os.path.join(folder, '_provenance.csv')
    new = not os.path.exists(path)
    with io.open(path, 'a', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['file', 'method', 'url', 'form', 'bytes', 'sha256', 'fetched_at'])
        w.writerow(row)


def _save(folder, filename, raw, method, url, form):
    with io.open(os.path.join(folder, filename), 'wb') as fh:
        fh.write(raw)
    _provenance(folder, [filename, method, url, form, len(raw), hashlib.sha256(raw).hexdigest(),
                         datetime.datetime.now().isoformat(timespec='seconds')])


def meets(site, since, until):
    top = _text(site.get(BASE))
    out = []
    for value, label in _options(top, 'i01'):
        m = re.match(r'(\d{8})\s+(.*)', label)
        if not m or any(s in label for s in SKIP_MEETS):
            continue
        d = '%s-%s-%s' % (m.group(1)[:4], m.group(1)[4:6], m.group(1)[6:])
        if not (since <= int(d[:4]) <= until):
            continue
        out.append((value, d, m.group(2).strip()))
    return out


def fetch_lists(site, since, until, skip_existing_meets=True):
    done = 0
    for value, date, name in meets(site, since, until):
        folder = meet_dir(date, name)
        if skip_existing_meets and os.path.isdir(folder) and not os.path.exists(
                os.path.join(folder, '_provenance.csv')):
            print('  既存の大会（以前の収集）なので触らない:', os.path.basename(folder))
            continue
        os.makedirs(folder, exist_ok=True)
        site.get(BASE)                                  # セッションを大会選択の状態に戻す
        page = _text(site.get(BASE, {'i01': value, 'entry': '選択完了'}))
        cats = _options(page, 'i11')
        saved = 0
        for n, (cval, clabel) in enumerate(cats, start=1):
            if any(s in clabel for s in SKIP_CATEGORIES):
                continue
            filename = '%02d_%s.html' % (n, _safe(clabel))
            if os.path.exists(os.path.join(folder, filename)):
                continue
            raw = site.get(BASE, {'i11': cval, 'entry5': '区分選択完了'})
            _save(folder, filename, raw, 'POST', BASE,
                  'i01=%s(%s) i11=%s(%s)' % (value, date, cval, clabel))
            saved += 1                                  # 区分は続けて選べる（選び直し不要。実測済み）
        done += 1
        print('  %s %-40s 区分 %d（保存 %d）' % (date, name[:40], len(cats), saved), flush=True)
    return done


def fetch_details(site, since, until):
    """保存済みの成績一覧から、演技ごとの明細ページを取る。"""
    total = 0
    for year in range(since, until + 1):
        root = os.path.join(config.RAW_ROOT, str(year), '大阪府_pweb')
        if not os.path.isdir(root):
            continue
        for folder in sorted(os.listdir(root)):
            path = os.path.join(root, folder)
            if not os.path.exists(os.path.join(path, '_provenance.csv')):
                continue                                # 以前の収集のフォルダは触らない
            for name in sorted(os.listdir(path)):
                if not name.endswith('.html') or name.startswith('detail_'):
                    continue
                raw = open(os.path.join(path, name), 'rb').read()
                for href in re.findall(rb'href="(result\.php\?taikaicode=[^"]*wmeisai=[^"]+)"', raw):
                    href = href.replace(b'&amp;', b'&')
                    key = hashlib.sha1(href).hexdigest()[:12]
                    filename = 'detail_%s_%s.html' % (name[:2], key)
                    if os.path.exists(os.path.join(path, filename)):
                        continue
                    url = PHP + urllib.parse.quote(href, safe=b'/?=&')
                    _save(path, filename, site.get(url), 'GET', url, name)
                    total += 1
            print('  %s 明細 累計 %d' % (folder[:50], total), flush=True)
    return total


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--lists', action='store_true')
    ap.add_argument('--details', action='store_true')
    ap.add_argument('--since', type=int, default=2016)
    ap.add_argument('--until', type=int, default=2024)
    ap.add_argument('--wait', type=float, default=10.0)   # 3秒で遮断されたため余裕を持たせる
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    site = Site(args.wait)
    if args.lists:
        print('成績一覧: %d 大会' % fetch_lists(site, args.since, args.until))
    if args.details:
        print('明細: %d ページ' % fetch_details(site, args.since, args.until))
    print('アクセス回数', site.count)


if __name__ == '__main__':
    main()
