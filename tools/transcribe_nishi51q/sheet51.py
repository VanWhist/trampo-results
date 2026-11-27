import json,os,sys
from PIL import Image,ImageDraw,ImageFont
S=sys.argv[1]
res=json.load(open(os.path.join(S,'q51_names.json'),encoding='utf-8'))
import glob,collections
clubs_of=collections.defaultdict(set)
REPO=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..')
for f in glob.glob(os.path.join(REPO,'data','performances','*.json')):
    if '-other' in f: continue
    for x in json.load(open(f,encoding='utf-8')):
        if x.get('athlete_id'): clubs_of[x['athlete_name'].replace(' ','')].add((x.get('club') or '').replace(' ',''))
def risky(r):
    if r['status']!='ok' or len(r['cand'])<2 or r['cand'][1][0]>1: return False
    a,b=r['cand'][0][3],r['cand'][1][3]
    return bool(clubs_of[a] & clubs_of[b])
done={tuple(map(int,l.split('\t')[:2])) for l in open(os.path.join(S,'visual_names.tsv'),encoding='utf-8') if l.strip()}
todo=[r for r in res if (r['status']!='ok' or risky(r)) and (r['page'],r['band']) not in done]
json.dump(todo,open(os.path.join(S,'q51_todo_new.json'),'w',encoding='utf-8'),ensure_ascii=False)
font=ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc',22)
per=16; W=1100; RH=70
os.makedirs(os.path.join(S,'sheets'),exist_ok=True)
for s in range(0,len(todo),per):
    chunk=todo[s:s+per]
    sheet=Image.new('L',(W,RH*len(chunk)),255); d=ImageDraw.Draw(sheet)
    for i,r in enumerate(chunk):
        y=i*RH
        d.text((4,y+2),'#%d p%d-%d  候補:%s'%(s+i,r['page'],r['band'],' / '.join(c[3] for c in r['cand'][:3])),fill=0,font=font)
        if r['line_file']:
            im=Image.open(os.path.join(S,'fields51',r['line_file']))
            h=40; w=int(im.width*h/im.height)
            if w>W-10: w=W-10; h=int(im.height*w/im.width)
            sheet.paste(im.resize((w,h)),(4,y+28))
        d.line((0,y+RH-1,W,y+RH-1),fill=180)
    sheet.save(os.path.join(S,'sheets','s%02d.png'%(s//per)))
print(len(todo),'件',(len(todo)+per-1)//per,'枚')
