#!/usr/bin/env python3
"""US-only job scan across every public job board we can read.

Sources: Greenhouse, Lever, Ashby (startup boards) plus Workday, Amazon,
Oracle Recruiting Cloud, Eightfold and SmartRecruiters -- which is where the
large H-1B sponsors actually post.  Boards live in boards.tsv, tagged tier 1
(major sponsors) or tier 2; tier 1 is fetched and reported first.

Filters: posted/updated <=24h, role family, non-senior, US location,
         1-2yr or new-grad experience, no explicit 'we don't sponsor'.
"""
import json,re,html,sys,os,csv,urllib.request,ssl,concurrent.futures as cf
from datetime import datetime,timedelta,timezone
import sources as SRC
try: import match as MATCH
except Exception: MATCH=None

ROLE=re.compile(r'\b(software|backend|back-end|frontend|front-end|full[- ]?stack|platform|infrastructure|systems?|applied|research)\s+(engineer|developer|scientist)|\bsoftware development engineer\b|\b(machine|deep)\s+learning\b[a-z /&-]{0,26}?\b(engineer|scientist|researcher|developer)\b|\bml\b[a-z /&-]{0,20}?\b(engineer|scientist|researcher)\b|\bmle\b|\bai\b[a-z /&-]{0,18}?\b(engineer|scientist|researcher)\b|\bdata\s+engineer\b|\bdata\s+scien(tist|ce)\b|\banalytics\s+engineer\b|\bquant(?:itative)?\s+(?:research(?:er)?|developer|analyst|engineer)\b|\bswe\b',re.I)
SENIOR=re.compile(r'\b(senior|sr\.?|staff|principal|lead|manager|director|head|vp|architect|distinguished|fellow|intern|internship|phd)\b|\bph\.\s?d\.?|\b(recruiter|sourcer|talent)\b',re.I)
NEG=re.compile(r'(may not be able to.{0,260}?sponsor|not\s+(be\s+)?able\s+to.{0,140}?sponsor|unable to.{0,90}?(sponsor|visa)|do(es)?\s+not\s+.{0,90}?sponsor|will not (be able to )?sponsor|cannot sponsor|without the need for.{0,90}?sponsorship|no (visa |immigration )?sponsorship|sponsorship is not|not (currently )?(provide|offer|considering).{0,60}sponsor|must be a u\.?s\.? citizen|u\.?s\.? citizens? only|citizenship is required|active .{0,30}security clearance|top secret)',re.I)
POS=re.compile(r'(sponsorship (is )?(available|provided|offered)|we (will |do |can |are able to |are happy to )?sponsor|happy to sponsor|able to sponsor|visa sponsorship|stem opt|international students|h-?1b transfer)',re.I)
NEWGRAD=re.compile(r'\b(new grad|university grad|entry[- ]level|recent grad|early career|graduating|campus hire|early[- ]in[- ]career)\b',re.I)
STATES=set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
# some boards (iCIMS, Workday) spell the state out -- accept both forms
STATE_NAMES=set("""alabama alaska arizona arkansas california colorado connecticut delaware florida georgia
hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota
mississippi missouri montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont
virginia washington wisconsin wyoming""".split())|{'new hampshire','new jersey','new mexico','new york',
'north carolina','north dakota','rhode island','south carolina','south dakota','west virginia',
'district of columbia'}
NONUS=re.compile(r'\b(canada|toronto|vancouver|montreal|ontario|london|uk|united kingdom|ireland|dublin|germany|berlin|munich|france|paris|spain|madrid|barcelona|netherlands|amsterdam|poland|warsaw|krakow|india|bangalore|bengaluru|hyderabad|pune|mumbai|delhi|singapore|japan|tokyo|australia|sydney|melbourne|israel|tel aviv|brazil|sao paulo|mexico|argentina|china|shanghai|beijing|korea|seoul|sweden|stockholm|denmark|copenhagen|norway|oslo|finland|switzerland|zurich|italy|portugal|lisbon|romania|bucharest|czech|prague|emea|apac|latam)\b',re.I)

def is_us(loc):
    l=(loc or '').strip()
    if not l: return False
    if NONUS.search(l) and not re.search(r'united states|,\s*us\b|\busa\b',l,re.I): return False
    if re.search(r'united states|\busa\b|u\.s\.|remote[ ,-]*us\b|\bus\b\s*$|,\s*us\b',l,re.I): return True
    for t in re.split(r'[,;/|()]',l):
        t=t.strip()
        if t in STATES: return True
        if t.lower() in STATE_NAMES: return True
    return False

def title_ok(t): return bool(ROLE.search(t)) and not SENIOR.search(t)
def loc_ok(l):   return (not l) or is_us(l)   # blank/ambiguous resolved by the detail call

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

def get(u,t=90):
    req=urllib.request.Request(u,headers={'User-Agent':SRC.UA})
    with urllib.request.urlopen(req,timeout=t,context=SRC.CTX) as r: return json.load(r)

# ------------------------- the three original startup-board readers ---------
def gh(b,**kw):
    out=[]
    try: d=get("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true"%b)
    except Exception: return out
    for j in d.get('jobs',[]):
        try: ts=datetime.fromisoformat(j['updated_at']).astimezone(timezone.utc)
        except Exception: continue
        out.append(dict(src='GH',co=b,title=(j.get('title') or '').strip(),loc=j.get('location',{}).get('name',''),
                        url=j.get('absolute_url'),ts=ts,text=clean(j.get('content','')),datekind='updated'))
    return out

def lv(b,**kw):
    out=[]
    try: d=get("https://api.lever.co/v0/postings/%s?mode=json"%b)
    except Exception: return out
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

def ab(b,**kw):
    out=[]
    try: d=get("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true"%b)
    except Exception: return out
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

READERS=dict(GH=gh,LV=lv,AB=ab,**SRC.READERS)


# ---------------------------------------------------------- job-level dedupe ---
# A company can be live on two boards at once (clickhouse is on Greenhouse AND
# Ashby, neon on Lever AND Ashby, ...) with partially disjoint contents, so we
# keep every board and collapse duplicates per JOB instead of per board.
_STATES={'alabama':'al','alaska':'ak','arizona':'az','arkansas':'ar','california':'ca','colorado':'co',
 'connecticut':'ct','delaware':'de','florida':'fl','georgia':'ga','hawaii':'hi','idaho':'id','illinois':'il',
 'indiana':'in','iowa':'ia','kansas':'ks','kentucky':'ky','louisiana':'la','maine':'me','maryland':'md',
 'massachusetts':'ma','michigan':'mi','minnesota':'mn','mississippi':'ms','missouri':'mo','montana':'mt',
 'nebraska':'ne','nevada':'nv','new hampshire':'nh','new jersey':'nj','new mexico':'nm','new york':'ny',
 'north carolina':'nc','north dakota':'nd','ohio':'oh','oklahoma':'ok','oregon':'or','pennsylvania':'pa',
 'rhode island':'ri','south carolina':'sc','south dakota':'sd','tennessee':'tn','texas':'tx','utah':'ut',
 'vermont':'vt','virginia':'va','washington':'wa','west virginia':'wv','wisconsin':'wi','wyoming':'wy',
 'district of columbia':'dc'}
_DROP_LOC={'united states','united states of america','usa','us','u s','remote','onsite','hybrid',
 'multiple locations','remote us','remote usa','us remote','usa remote','remote united states',
 'anywhere','various','flexible'}

def norm_title(t):
    t=(t or '').lower()
    t=re.sub(r'\(.*?\)',' ',t)                 # "(Remote)", "(L2)" etc
    t=re.sub(r'[^a-z0-9 ]+',' ',t)
    return re.sub(r'\s+',' ',t).strip()

def norm_loc(l):
    l=(l or '').lower()
    for full,ab in _STATES.items(): l=re.sub(r'\b%s\b'%re.escape(full),ab,l)
    parts=re.split(r'[;/|,\n]+',l)
    toks=set()
    for p in parts:
        p=re.sub(r'[^a-z0-9 ]+',' ',p); p=re.sub(r'\s+',' ',p).strip()
        if p and p not in _DROP_LOC: toks.add(p)
    return '|'.join(sorted(toks))

def date_quality(j):
    """exact > approx > first_seen > undated."""
    dk=j.get('datekind')
    if dk=='undated': return 0
    if dk=='first_seen': return 1
    t=j['ts']
    if dk=='posted' and (t.hour,t.minute)!=(0,0): return 3      # real clock time
    return 2                                                    # date-only, or updated_at

def dedupe(jobs):
    best={}
    for j in jobs:
        key=(str(j.get('cokey') or j.get('co') or '').lower(),norm_title(j['title']),norm_loc(j['loc']))
        cur=best.get(key)
        if cur is None: best[key]=j; continue
        # better date wins; ties break on the newer timestamp, then longer text
        rank=lambda x:(date_quality(x),x['ts'].timestamp() if date_quality(x) else 0,len(x.get('text') or ''))
        if rank(j)>rank(cur): best[key]=j
    return list(best.values())

def load_boards(path='boards.tsv'):
    out=[]
    for line in open(path):
        if line.startswith('#') or not line.strip(): continue
        tier,src,spec,co=line.rstrip('\n').split('\t')[:4]
        out.append((int(tier),src,spec,co))
    return out

def fetch(task):
    tier,src,spec,co=task
    fn=READERS.get(src)
    if not fn: return []
    def tag(rows):
        for r in rows: r['cokey']=co      # canonical name, so GH+AB of one company collapse
        return rows
    try:
        # the big-board readers prefilter server-side; the startup readers ignore the kwargs
        return tag(fn(spec,title_ok=title_ok,loc_ok=loc_ok,max_days=MAXD) or [])
    except TypeError:
        try: return tag(fn(spec) or [])
        except Exception: return []
    except Exception: return []

# usage: scan_all.py [tier] [hours]      tier "1" = majors only, default both / 72h
args=[a for a in sys.argv[1:]]
only=next((a for a in args if a in ('1','2')),None)
HOURS=next((int(a) for a in args if a.isdigit() and a not in ('1','2')),72)
MAXD=max(1,(HOURS+23)//24)
def fetch_browser(specs,hours):
    """Run the Playwright boards in one python3.11 subprocess (Playwright needs
    >=3.8; this scanner runs on 3.7).  Out-of-process so a hung browser can be
    killed without taking the scan down -- any failure yields [] and a warning."""
    import subprocess,shutil
    if not specs: return []
    # Prefer the interpreter we're already running under when it's new enough
    # (that's the case in CI, where setup-python provides 3.11); otherwise look
    # for a suitable one on PATH.  Overridable with JOBSCAN_PY.
    py=os.environ.get('JOBSCAN_PY')
    if not py and sys.version_info>=(3,8): py=sys.executable
    if not py:
        for c in ('python3.12','python3.11','python3.10','python3.9','python3.8','python3'):
            py=shutil.which(c)
            if py: break
    cfg=json.dumps({'boards':specs,'max_days':max(1,(hours+23)//24),
                    'role_re':ROLE.pattern,'senior_re':SENIOR.pattern})
    try:
        p=subprocess.Popen([py,'browser_source.py',cfg],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        out,err=p.communicate(timeout=600)
    except Exception as e:
        sys.stderr.write("  browser boards skipped: %r\n"%e); return []
    for line in (err or b'').decode('utf-8','replace').splitlines():
        sys.stderr.write("  %s\n"%line.rstrip())
    try: rows=json.loads((out or b'[]').decode('utf-8','replace') or '[]')
    except Exception as e:
        sys.stderr.write("  browser boards: unreadable output (%r)\n"%e); return []
    for r in rows:
        r['ts']=SRC.iso(r['ts']) or datetime.now(timezone.utc)
    return rows

boards=load_boards()
if only: boards=[b for b in boards if b[0]==int(only)]

br=[b for b in boards if b[1]=='BR']
boards=[b for b in boards if b[1]!='BR']
jobs=[]
for tier in sorted({b[0] for b in boards}):
    t=[b for b in boards if b[0]==tier]
    sys.stderr.write("tier %d: fetching %d boards (%s)...\n"%(tier,len(t),
        ', '.join('%s=%d'%(s,sum(1 for x in t if x[1]==s)) for s in sorted({x[1] for x in t}))))
    got=[]
    with cf.ThreadPoolExecutor(12) as ex:
        for r in ex.map(fetch,t): got.extend(r)
    for j in got: j['tier']=tier
    cmap={(b[1],b[2]):b[3] for b in t}
    for b in t:
        pass
    for j in got: j.setdefault('cokey',j.get('co'))
    sys.stderr.write("        %d postings\n"%len(got))
    jobs.extend(got)

if br:
    sys.stderr.write("browser boards (run last): %s\n"%', '.join(b[2] for b in br))
    brrows=fetch_browser([b[2] for b in br],HOURS)
    tiers={b[2]:b[0] for b in br}
    for r in brrows: r['tier']=tiers.get(r['co'],1)
    sys.stderr.write("        %d postings\n"%len(brrows))
    jobs.extend(brrows)

if not jobs: sys.stderr.write("no postings fetched\n"); sys.exit(1)
raw_n=len(jobs)
jobs=dedupe(jobs)
sys.stderr.write("dedupe: %d postings -> %d unique (%d collapsed)\n"%(raw_n,len(jobs),raw_n-len(jobs)))
now=max(j['ts'] for j in jobs); cut=now-timedelta(hours=HOURS)
sys.stderr.write("boards=%d  jobs=%d  anchor=%s\n"%(len(boards),len(jobs),now))
stage={'24h':0,'role':0,'us':0,'exp':0,'spons':0}
rows=[]
for j in jobs:
    if j['datekind']!='undated' and j['ts']<cut: continue
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
sys.stderr.write("  in %dh: %d -> role: %d -> US: %d -> exp 1-2y: %d -> sponsorship-safe: %d\n"%(

    HOURS,stage['24h'],stage['role'],stage['us'],stage['exp'],stage['spons']))
sys.stderr.write("  majors (tier1): %d of %d\n"%(sum(1 for r in rows if r.get('tier')==1),len(rows)))

def age_h(t): return (now-t).total_seconds()/3600.0

RESUMES=MATCH.load_resumes() if MATCH else {}
if MATCH and not RESUMES:
    sys.stderr.write("  note: resumes/ is empty -- no resume advice in this run\n")
FIN=re.compile(r'bank|trading|financial|capital|invest|payment|fintech|hedge|securities',re.I)
for r in rows:
    r['resume'],r['fit'],r['add']=(None,None,[])
    if RESUMES:
        hint=bool(FIN.search(r['co']+' '+r['title']+' '+(r['text'] or '')[:2000]))
        r['resume'],r['fit'],r['add']=MATCH.evaluate(r['title'],r['text'],RESUMES,fin_hint=hint)

# the CSV the older workflow produced, regenerated from the live scan
with open('results.csv','w') as f:
    w=csv.writer(f)
    w.writerow(['Job Title','Company Name','Location','Job Link','Recommended Resume',
                'Missing Keywords to Add','Match Score'])
    for r in sorted(rows,key=lambda x:(x.get('tier',2),x['datekind']=='undated',-x['ts'].timestamp())):
        w.writerow([r['title'],r['co'],r['loc'],r['url'],r.get('resume') or '',
                    '; '.join(r.get('add') or []),r.get('fit') or ''])

json.dump([dict(tier=r.get('tier',2),src=r['src'],co=r['co'],title=r['title'],loc=r['loc'],url=r['url'],
                resume=r.get('resume'),fit=r.get('fit'),add=r.get('add') or [],
                ts=r['ts'].isoformat(),
                posted=(None if r['datekind']=='undated' else r['ts'].strftime('%Y-%m-%d %H:%M UTC')),
                age_hours=(None if r['datekind']=='undated' else round(age_h(r['ts']),1)),
                datekind=r['datekind'],
                why=r['why'],pos=r['pos'],text=r['text'][:6000])
           for r in sorted(rows,key=lambda x:(x['datekind']=='undated',-x['ts'].timestamp()))],
          open('passed.json','w'),indent=1)
def stamp(r):
    if r['datekind']=='undated': return "date unknown".ljust(19)+"      "
    a=age_h(r['ts']); t=r['ts']
    rel=("%dh ago"%round(a)) if a<48 else ("%.1fd ago"%(a/24))
    note='' if r['datekind']=='posted' else ', updated'
    # Amazon/Workday/Oracle publish a date with no clock time; don't imply midnight
    if (t.hour,t.minute)==(0,0) and r['src'] in ('AMZN','WD','ORC'):
        return "%s%12s (%s, date only%s)"%(t.strftime('%b %d'),'',rel,note)
    return "%s (%s%s)"%(t.strftime('%b %d %H:%M UTC'),rel,note)

for tier in sorted({r.get('tier',2) for r in rows}):
    grp=sorted([r for r in rows if r.get('tier',2)==tier],
               key=lambda x:(x['datekind']=='undated',-x['ts'].timestamp()))
    if not grp: continue
    print("\n=== %s -- %d role%s, newest first ==="%(
        'MAJOR SPONSORS' if tier==1 else 'OTHER COMPANIES',len(grp),'' if len(grp)==1 else 's'))
    for r in grp:
        print("%s | [%s/%s] %s | %s | %s | sponsor:%s"%(
            stamp(r),r['src'],r['co'],r['title'],r['loc'][:44],r['why'],r['pos']))
        if r.get('resume'):
            print("        resume: %s (%s/5)%s"%(r['resume'],r['fit'],
                  ('  add: '+'; '.join(r['add'])) if r.get('add') else ''))
        print("        %s"%r['url'])
