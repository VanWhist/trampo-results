import json,sys,collections,re
sys.stdout.reconfigure(encoding='utf-8')
d=json.load(open(sys.argv[1],encoding='utf-8'))
f=lambda v: float(v) if v not in (None,'') else None
bad=collections.Counter(); ex=collections.defaultdict(list); ok=0; nrt=0; dns=0
for b in d:
    rows=b['rows']
    if any('DNS' in ''.join(r.values()) for r in rows): dns+=1; continue
    if len(rows)!=2: bad['行数']+=1; ex['行数'].append((b['page'],b['band'],len(rows),rows)); continue
    tot=[]
    for k,r in enumerate(rows):
        nrt+=1
        if any(not re.fullmatch(r'\d+(\.\d+)?',v) for v in r.values()):
            bad['形']+=1; ex['形'].append((b['page'],b['band'],r)); continue
        S=[int(r['S%d'%i]) for i in range(1,11) if 'S%d'%i in r]
        n=len(S)
        if [ 'S%d'%i in r for i in range(1,11)] != [True]*n+[False]*(10-n): bad['S並び']+=1; ex['S並び'].append((b['page'],b['band'],r))
        L=int(r.get('L','0'))
        E,D,H,T,Tot=f(r.get('E')),f(r.get('D')) or 0.0,f(r.get('H')),f(r.get('Time')),f(r.get('Total'))
        if None in (E,H,T,Tot): bad['欠け']+=1; ex['欠け'].append((b['page'],b['band'],r)); continue
        if abs(E+D+H+T-Tot)>0.0015: bad['合計']+=1; ex['合計'].append((b['page'],b['band'],k,r))
        if abs(2*n-(sum(S)+L)/10-E)>0.0015: bad['E']+=1; ex['E'].append((b['page'],b['band'],k,r))
        tot.append(Tot)
    scs=rows[0].get('Score')
    if scs and not re.fullmatch(r'\d+\.\d+',scs): bad['Score形']+=1; ex['Score形'].append((b['page'],b['band'],rows)); continue
    sc=f(scs)
    if len(tot)==2 and sc is not None and abs(sum(tot)-sc)>0.0015: bad['予選の値']+=1; ex['予選の値'].append((b['page'],b['band'],tot,sc))
    if sc is None: bad['Scoreなし']+=1; ex['Scoreなし'].append((b['page'],b['band']))
print('帯',len(d),'DNS',dns,'演技',nrt,'不一致',dict(bad))
for k,v in ex.items():
    for x in v[:4]: print(k,x)
