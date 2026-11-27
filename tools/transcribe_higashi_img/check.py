# -*- coding: utf-8 -*-
"""検算：全演技で
  Exe = 2 × 跳んだ技の数 − (S の合計 + L) ÷ 10      （L は10本跳び終えた演技だけ）
  Score = Exe + Diff + ToF + HD − Pen
  選手の値（Best／Total）= 2本の良いほう／合計（ファイルごとにどちらか一方に決まる）
  順位は選手の値の大きい順（同点は同順位）
"""
import json
import sys
from decimal import Decimal


def num(s):
    if s is None:
        return None
    if not all(c.isdigit() or c == '.' for c in s) or s.count('.') > 1:
        raise ValueError('数でない: %r' % s)
    return Decimal(s)


def routines_of(b):
    """演技に何本目かを付ける。予選の印の順（ページをまたいだら前の印の数を足す）。"""
    out = []
    offset = 0
    pages = []
    for r in b['routines']:
        if r['page'] not in pages:
            if pages:
                offset += prev_labels
            pages.append(r['page'])
        prev_labels = r['n_labels']
        no = 1 if r['label_idx'] is None else offset + r['label_idx'] + 1
        out.append((no, r['vals']))
    return out


def check(res):
    errs, n_rt = [], 0
    for f in res:
        kinds = set()
        aggs = []
        for b in f['bands']:
            where = (f['file'], b['band'], b['rank'])
            rts = routines_of(b)
            if b['rank'] == '' or not b['rank'].isdigit():
                errs.append((where, '順位が数でない'))
            scores = {}
            agg = None
            dns = False
            for no, v in rts:
                if 'Agg' in v:
                    if agg is not None:
                        errs.append((where, '選手の値が2つ'))
                    agg = num(v['Agg'])
                if v.get('Score') == 'DNS':
                    dns = True                       # 棄権（Score 欄に DNS）
                    continue
                if set(v) <= {'Agg'}:
                    continue                         # 演技していない本目（選手の値だけが同じ行に出る）
                S = [num(v.get('S%d' % i)) for i in range(1, 11)]
                n = 0
                for s in S:
                    if s is None:
                        break
                    n += 1
                if any(s is not None for s in S[n:]):
                    errs.append((where, no, 'S の途中に空欄', v))
                L = num(v.get('L')) or Decimal(0)
                A = num(v.get('A')) or Decimal(0)
                exe, diff, tof, hd = (num(v.get(k)) for k in ('Exe', 'Diff', 'ToF', 'HD'))
                pen = num(v.get('Pen')) or Decimal(0)
                sc = num(v.get('Score'))
                n_rt += 1
                if exe is None or sc is None or tof is None or hd is None:
                    errs.append((where, no, '欠けた値', v))
                    continue
                e_calc = 2 * n - (sum(S[:n]) + (L if n == 10 else 0) + A) / 10
                if n == 10 and e_calc != exe:
                    errs.append((where, no, 'Exe の式', str(e_calc), str(exe), v))
                if n < 10:
                    e2 = 2 * n - (sum(S[:n]) + L + A) / 10
                    if exe not in (e_calc, e2) and not (n == 0 and exe == 0):
                        errs.append((where, no, 'Exe の式(中断)', str(e_calc), str(exe), v))
                if exe + (diff or 0) + tof + hd - pen != sc:
                    errs.append((where, no, 'Score の式', str(exe + (diff or 0) + tof + hd - pen), str(sc), v))
                if no in scores:
                    errs.append((where, no, '同じ本目が2つ'))
                scores[no] = sc
            if agg is None:
                errs.append((where, '選手の値が無い'))
                continue
            vals = list(scores.values())
            b['_status'] = 'DNS' if dns else ('演技なし' if not vals else '')
            if not vals:
                if agg != 0:
                    errs.append((where, '演技が無いのに選手の値', str(agg)))
                continue
            mx, sm = max(vals), sum(vals)
            k = set()
            if agg == mx:
                k.add('Best')
            if agg == sm:
                k.add('Total')
            if not k:
                errs.append((where, '選手の値が合わない', str(agg), [str(x) for x in vals]))
            if len(vals) == 2:
                kinds |= k if len(k) == 1 else set()
            aggs.append((int(b['rank']) if b['rank'].isdigit() else None, agg, where))
        if len(kinds) > 1:
            errs.append((f['file'], 'Best と Total が混在', kinds))
        f['agg_kind'] = kinds.pop() if len(kinds) == 1 else None
        # 順位
        prev = None
        for i, (rk, agg, where) in enumerate(aggs):
            if prev is not None:
                prk, pagg = prev
                if agg > pagg:
                    errs.append((where, '順位が値の順でない'))
                if rk is not None and prk is not None:
                    # 同点は同順位か、規則による順位付け（例：跳躍時間の大きい方が上）で i+1
                    exp = (prk, i + 1) if agg == pagg else (i + 1,)
                    if rk not in exp:
                        errs.append((where, '順位の番号', rk, exp))
            elif rk != 1:
                errs.append((where, '1位から始まらない'))
            prev = (rk, agg)
    return errs, n_rt


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    res = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'parsed.json', encoding='utf-8'))
    errs, n = check(res)
    print('演技', n, '不一致', len(errs))
    for e in errs[:60]:
        print(' ', e)
    for f in res:
        print(f['file'][:26], f.get('agg_kind'), len(f['bands']))
