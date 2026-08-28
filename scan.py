#!/usr/bin/env python3
"""Daily job scan: Greenhouse public API -> 24h / 1-2yr / target-role / US / sponsorship-safe."""
import json,re,html,sys,csv,urllib.request,concurrent.futures as cf
from datetime import datetime,timedelta

BOARDS=[b.strip() for b in open('boards.txt') if b.strip()]
ROLE=re.compile(r'\b(software|backend|back-end|frontend|front-end|full[- ]?stack|platform|infrastructure|systems?)\s+(engineer|developer)|\bsoftware development engineer\b|\bmachine learning engineer\b|\bml engineer\b|\bdata engineer\b|\bdata scientist\b|\bdata science\b|\bapplied scientist\b',re.I)
SENIOR=re.compile(r'\b(senior|sr\.?|staff|principal|lead|manager|director|head of|vp|architect|distinguished|fellow)\b',re.I)
# NB: '.' not excluded -- "U.S." breaks [^.] classes
NEG=re.compile(r'(may not be able to.{0,260}?sponsor|not\s+(be\s+)?able\s+to.{0,120}?sponsor|unable to.{0,90}?(sponsor|visa)|do(es)?\s+not\s+.{0,90}?sponsor|will not sponsor|without the need for.{0,80}?sponsorship|no (visa|immigration) sponsorship|sponsorship is not|must be a u\.?s\.? citizen|u\.?s\.? citizens? only|citizenship is required)',re.I)
STATES=set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
def is_us(l):
    l=l or ''
    if re.search(r'united states|usa|u\.s\.|remote[, -]*us\b',l,re.I): return True
    return any(t.strip() in STATES for t in re.split(r'[,;/|]',l))
def txt(j):
    c=html.unescape(j.get('content','') or ''); c=re.sub(r'<[^>]+>',' ',c); return re.sub(r'\s+',' ',c)
def exp_ok(t):
    if re.search(r'\b(new grad|university grad|entry[- ]level|recent grad|early career|graduating)\b',t,re.I): return True
    for m in re.finditer(r'(\d+)\s*\+?\s*(?:-|to|–)\s*(\d+)|(\d+)\s*\+\s*year',t):
        seg=t[max(0,m.start()-110):m.end()+60]
        if not re.search(r'experien|industry|professional',seg,re.I): continue
        lo=int(m.group(1) or m.group(3))
        if lo<=2: return True
    return False
def fetch(b):
    try:
        with urllib.request.urlopen(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs?content=true",timeout=90) as r:
            return b,json.load(r).get('jobs',[])
    except Exception as e: return b,[]
jobs=[]
with cf.ThreadPoolExecutor(12) as ex:
    for b,js in ex.map(fetch,BOARDS):
        for j in js: j['_board']=b; jobs.append(j)
def ts(s):
    try: return datetime.fromisoformat(s)
    except: return None
now=max(t for t in (ts(j.get('updated_at','')) for j in jobs) if t); cut=now-timedelta(hours=24)
out=[]
for j in jobs:
    t0=ts(j.get('updated_at',''))
    if not t0 or t0<cut: continue
    if not ROLE.search(j['title']) or SENIOR.search(j['title']): continue
    if not is_us(j.get('location',{}).get('name','')): continue
    t=txt(j)
    if NEG.search(t): continue          # explicit "no sponsorship" -> discard
    if not exp_ok(t): continue          # must show 1-2yr / new-grad signal
    out.append([j['title'],j['_board'],j['location']['name'],j['absolute_url'],'','',''])
w=csv.writer(sys.stdout)
w.writerow(['Job Title','Company Name','Location','Job Link','Recommended Resume','Missing Keywords to Add','Match Score'])
w.writerows(out)
print(f"\n# scanned {len(jobs)} jobs across {len(BOARDS)} boards; {len(out)} passed",file=sys.stderr)
