#!/usr/bin/env python3
"""US-only job scan across Greenhouse + Lever + Ashby public APIs.
Filters: posted/updated <=24h, role family, non-senior, US location,
         1-2yr or new-grad experience, no explicit 'we don't sponsor'."""
import json,re,html,sys,csv,urllib.request,concurrent.futures as cf
from datetime import datetime,timedelta,timezone

ROLE=re.compile(r'\b(software|backend|back-end|frontend|front-end|full[- ]?stack|platform|infrastructure|systems?|applied|research)\s+(engineer|developer|scientist)|\bsoftware development engineer\b|\bmachine learning engineer\b|\bml engineer\b|\bai engineer\b|\bdata engineer\b|\bdata scientist\b|\bdata science\b|\banalytics engineer\b|\bswe\b',re.I)
SENIOR=re.compile(r'\b(senior|sr\.?|staff|principal|lead|manager|director|head|vp|architect|distinguished|fellow|intern|internship|phd)\b',re.I)
NEG=re.compile(r'(may not be able to.{0,260}?sponsor|not\s+(be\s+)?able\s+to.{0,140}?sponsor|unable to.{0,90}?(sponsor|visa)|do(es)?\s+not\s+.{0,90}?sponsor|will not (be able to )?sponsor|cannot sponsor|without the need for.{0,90}?sponsorship|no (visa |immigration )?sponsorship|sponsorship is not|not (currently )?(provide|offer|considering).{0,60}sponsor|must be a u\.?s\.? citizen|u\.?s\.? citizens? only|citizenship is required|active .{0,30}security clearance|top secret)',re.I)
POS=re.compile(r'(sponsorship (is )?(available|provided|offered)|we (will |do |can |are able to |are happy to )?sponsor|happy to sponsor|able to sponsor|visa sponsorship|stem opt|international students|h-?1b transfer)',re.I)
NEWGRAD=re.compile(r'\b(new grad|university grad|entry[- ]level|recent grad|early career|graduating|campus hire|early[- ]in[- ]career)\b',re.I)
STATES=set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
NONUS=re.compile(r'\b(canada|toronto|vancouver|montreal|ontario|london|uk|united kingdom|ireland|dublin|germany|berlin|munich|france|paris|spain|madrid|barcelona|netherlands|amsterdam|poland|warsaw|krakow|india|bangalore|bengaluru|hyderabad|pune|mumbai|delhi|singapore|japan|tokyo|australia|sydney|melbourne|israel|tel aviv|brazil|sao paulo|mexico|argentina|china|shanghai|beijing|korea|seoul|sweden|stockholm|denmark|copenhagen|norway|oslo|finland|switzerland|zurich|italy|portugal|lisbon|romania|bucharest|czech|prague|emea|apac|latam)\b',re.I)

def is_us(loc):
    l=(loc or '').strip()
    if not l: return False
    if NONUS.search(l) and not re.search(r'united states|,\s*us\b|\busa\b',l,re.I): return False
    if re.search(r'united states|\busa\b|u\.s\.|remote[ ,-]*us\b|\bus\b\s*$|,\s*us\b',l,re.I): return True
    return any(t.strip() in STATES for t in re.split(r'[,;/|()]',l))

def clean(h):
    c=html.unescape(h or ''); c=re.sub(r'<[^>]+>',' ',c); return re.sub(r'\s+',' ',c)

def exp_ok(t):
    found=None
    for m in re.finditer(r'(\d{1,2})\s*\+?\s*(?:-|to|–|—)\s*(\d{1,2})\s*\+?\s*year|(\d{1,2})\s*\+\s*year|\b(\d{1,2})\s+year',t):
        seg=t[max(0,m.start()-120):m.end()+70]
        if not re.search(r'experien|industry|professional|working',seg,re.I): continue
        lo=int(m.group(1) or m.group(3) or m.group(4))
        if lo<=2:
            if found is None: found='%s yr min'%lo
        else: return False,'requires %d+ yrs'%lo
    if found: return True,found
    if NEWGRAD.search(t): return True,'new-grad/entry'
    return False,'no 1-2yr signal'


import glob,os
def _load(p):
    try: return json.load(open(p))
    except Exception: return None

def gh(b):
    out=[]; d=_load('d_gh/%s.json'%b)
    if not d: return out
    for j in d.get('jobs',[]):
        try: ts=datetime.fromisoformat(j['updated_at']).astimezone(timezone.utc)
        except Exception: continue
        out.append(dict(src='GH',co=b,title=(j.get('title') or '').strip(),loc=j.get('location',{}).get('name',''),
                        url=j.get('absolute_url'),ts=ts,text=clean(j.get('content','')),datekind='updated'))
    return out

def lv(b):
    out=[]; d=_load('d_lv/%s.json'%b)
    if not isinstance(d,list): return out
    for j in d:
        try: ts=datetime.fromtimestamp(j['createdAt']/1000,tz=timezone.utc)
        except Exception: continue
        cats=j.get('categories') or {}
        locs=[cats.get('location','')]+(cats.get('allLocations') or [])
        body=' '.join([j.get('descriptionPlain','') or '',j.get('additionalPlain','') or '']+
                      [clean(x.get('content','')) for x in (j.get('lists') or [])])
        out.append(dict(src='LV',co=b,title=(j.get('text') or '').strip(),loc='; '.join([x for x in locs if x]),
                        url=j.get('hostedUrl'),ts=ts,text=re.sub(r'\s+',' ',body),datekind='posted'))
    return out

def ab(b):
    out=[]; d=_load('d_ab/%s.json'%b)
    if not d: return out
    for j in d.get('jobs',[]):
        if not j.get('isListed',True): continue
        try: ts=datetime.fromisoformat(j['publishedAt'].replace('Z','+00:00')).astimezone(timezone.utc)
        except Exception: continue
        locs=[j.get('location','') or '']+[(s.get('location','') or '') for s in (j.get('secondaryLocations') or [])]
        ctry=((j.get('address') or {}).get('postalAddress') or {}).get('addressCountry','')
        out.append(dict(src='AB',co=b,title=(j.get('title') or '').strip(),
                        loc='; '.join([x for x in locs if x])+((' ['+ctry+']') if ctry else ''),
                        url=j.get('jobUrl'),ts=ts,text=re.sub(r'\s+',' ',j.get('descriptionPlain','') or ''),datekind='posted'))
    return out

tasks=[(gh,b) for b in open('gh_live.txt').read().split()] + \
      [(lv,b) for b in open('lv_live.txt').read().split()] + \
      [(ab,b) for b in open('ab_live.txt').read().split()]
jobs=[]
with cf.ThreadPoolExecutor(16) as ex:
    for r in ex.map(lambda t:t[0](t[1]),tasks): jobs.extend(r)

now=max(j['ts'] for j in jobs); cut=now-timedelta(hours=24)
sys.stderr.write("boards=%d  jobs=%d  anchor=%s\n"%(len(tasks),len(jobs),now))
stage={'24h':0,'role':0,'us':0,'exp':0,'spons':0}
rows=[]
for j in jobs:
    if j['ts']<cut: continue
    stage['24h']+=1
    if not ROLE.search(j['title']) or SENIOR.search(j['title']): continue
    stage['role']+=1
    if not is_us(j['loc']): continue
    stage['us']+=1
    ok,why=exp_ok(j['text'])
    if not ok: continue
    stage['exp']+=1
    if NEG.search(j['text']): continue
    stage['spons']+=1
    j['why']=why; j['pos']='YES' if POS.search(j['text']) else 'silent'
    rows.append(j)
sys.stderr.write("  in 24h: %d -> role: %d -> US: %d -> exp 1-2y: %d -> sponsorship-safe: %d\n"%(
    stage['24h'],stage['role'],stage['us'],stage['exp'],stage['spons']))
json.dump([dict(src=r['src'],co=r['co'],title=r['title'],loc=r['loc'],url=r['url'],
                ts=r['ts'].isoformat(),why=r['why'],pos=r['pos'],text=r['text'][:6000]) for r in rows],
          open('passed.json','w'),indent=1)
for r in sorted(rows,key=lambda x:(x['co'],x['title'])):
    print("[%s/%s] %s | %s | %s | %s | sponsor:%s"%(r['src'],r['co'],r['title'],r['loc'][:48],r['why'],r['datekind'],r['pos']))
    print("        %s"%r['url'])
