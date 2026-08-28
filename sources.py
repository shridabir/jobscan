#!/usr/bin/env python3
"""Extra ATS readers for the major H-1B sponsors that are not on
Greenhouse/Lever/Ashby: Workday (CXS), Oracle Recruiting Cloud, Amazon,
Eightfold and SmartRecruiters.

Every reader returns the same normalized dict the scanner already consumes:
    dict(src, co, title, loc, url, ts, text, datekind)
"""
import json,re,html,ssl,urllib.request,urllib.parse,concurrent.futures as cf
from datetime import datetime,timedelta,timezone

UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36'
# a couple of these hosts serve an incomplete chain; we only read public postings
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE

def get(url,data=None,timeout=45,hdr=None):
    h={'User-Agent':UA,'Accept':'application/json'}
    if data is not None: h['Content-Type']='application/json'
    h.update(hdr or {})
    r=urllib.request.Request(url,data=(json.dumps(data).encode() if data is not None else None),headers=h)
    with urllib.request.urlopen(r,timeout=timeout,context=CTX) as f: return json.load(f)

def clean(h):
    c=html.unescape(h or ''); c=re.sub(r'<[^>]+>',' ',c); return re.sub(r'\s+',' ',c).strip()

def now_utc(): return datetime.now(timezone.utc)

# ---------------------------------------------------------------- Workday ---
# The list call is cheap and carries a coarse "Posted Today / Yesterday / N Days
# Ago" string.  Descriptions need a second call per job, so we filter on the
# cheap fields first and only then pull detail for the survivors.
_WD_RECENT=re.compile(r'posted\s+(today|yesterday|1\s+day\s+ago)',re.I)

def wd_age_ok(posted_on,max_days=1):
    p=(posted_on or '')
    if _WD_RECENT.search(p): return True
    m=re.search(r'posted\s+(\d+)\+?\s*days?\s+ago',p,re.I)
    return bool(m) and int(m.group(1))<=max_days

def wd(spec,title_ok=None,loc_ok=None,max_days=1,page_cap=5):
    """spec: 'tenant|wdhost|site'  e.g. 'nvidia|wd5|NVIDIAExternalCareerSite'"""
    t,hostn,site=spec.split('|')
    base="https://%s.%s.myworkdayjobs.com"%(t,hostn)
    cxs="%s/wday/cxs/%s/%s"%(base,t,site)
    stubs=[]
    for page in range(page_cap):
        try:
            d=get(cxs+"/jobs",data={"appliedFacets":{},"limit":20,"offset":page*20,"searchText":""})
        except Exception: break
        posts=d.get('jobPostings') or []
        if not posts: break
        stale=0
        for j in posts:
            if not wd_age_ok(j.get('postedOn'),max_days): stale+=1; continue
            ttl=(j.get('title') or '').strip(); loc=j.get('locationsText') or ''
            if title_ok and not title_ok(ttl): continue
            # "2 Locations" hides the real list -- keep it, detail call resolves it
            if loc_ok and 'location' not in loc.lower() and not loc_ok(loc): continue
            stubs.append((ttl,loc,j.get('externalPath') or ''))
        # postings come newest-first; once a whole page is stale we can stop
        if stale==len(posts): break
    out=[]
    def detail(s):
        ttl,loc,path=s
        try: d=get(cxs+"/job"+path)
        except Exception: return None
        i=d.get('jobPostingInfo') or {}
        try: ts=datetime.fromisoformat(i['startDate']).replace(tzinfo=timezone.utc)
        except Exception: ts=now_utc()
        return dict(src='WD',co=t,title=(i.get('title') or ttl).strip(),
                    loc=i.get('location') or loc,
                    url=i.get('externalUrl') or (base+'/'+site+'/job'+path),
                    ts=ts,text=clean(i.get('jobDescription','')),datekind='posted')
    if stubs:
        with cf.ThreadPoolExecutor(8) as ex:
            out=[r for r in ex.map(detail,stubs) if r]
    return out

# ------------------------------------------------- Oracle Recruiting Cloud ---
def orc(spec):
    """spec: 'company|host|siteNumber' e.g. 'oracle|eeho.fa.us2.oraclecloud.com|CX_45001'"""
    co,host,site=spec.split('|')
    url=("https://%s/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
         "&expand=requisitionList.secondaryLocations,flexFieldsFacet.values"
         "&finder=findReqs;siteNumber=%s,limit=200,sortBy=POSTING_DATES_DESC"%(host,site))
    try: d=get(url)
    except Exception: return []
    out=[]
    for j in (d.get('items') or [{}])[0].get('requisitionList',[]) or []:
        try: ts=datetime.fromisoformat((j.get('PostedDate') or '').replace('Z','+00:00'))
        except Exception: continue
        if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
        locs=[j.get('PrimaryLocation') or '']+[s.get('Name','') for s in (j.get('secondaryLocations') or [])]
        out.append(dict(src='ORC',co=co,title=(j.get('Title') or '').strip(),
                        loc='; '.join([x for x in locs if x]),
                        url="https://%s/hcmUI/CandidateExperience/en/sites/%s/job/%s"%(host,site,j.get('Id')),
                        ts=ts,text=clean(j.get('ShortDescriptionStr') or j.get('Description') or ''),
                        datekind='posted'))
    return out

# ----------------------------------------------------------------- Amazon ---
def amazon(_=None,max_pages=8):
    out=[]
    for page in range(max_pages):
        u=("https://www.amazon.jobs/en/search.json?radius=24km&facets[]=normalized_country_code"
           "&offset=%d&result_limit=100&sort=recent&country[]=USA&base_query="%(page*100))
        try: d=get(u)
        except Exception: break
        js=d.get('jobs') or []
        if not js: break
        for j in js:
            try: ts=datetime.strptime(j['posted_date'],'%B %d, %Y').replace(tzinfo=timezone.utc)
            except Exception: continue
            out.append(dict(src='AMZN',co='amazon',title=(j.get('title') or '').strip(),
                            loc=j.get('normalized_location') or j.get('location') or '',
                            url='https://www.amazon.jobs'+(j.get('job_path') or ''),ts=ts,
                            text=clean(' '.join([j.get('description') or '',
                                                 j.get('basic_qualifications') or '',
                                                 j.get('preferred_qualifications') or ''])),
                            datekind='posted'))
    return out

# -------------------------------------------------------------- Eightfold ---
def ef(spec,pages=3):
    """spec: 'host|domain' e.g. 'explore.jobs.netflix.net|netflix.com'"""
    host,dom=spec.split('|')
    co=dom.split('.')[0]; out=[]
    for p in range(pages):
        try: d=get("https://%s/api/apply/v2/jobs?domain=%s&start=%d&num=100&sort_by=timestamp"%(host,dom,p*100))
        except Exception: break
        pos=d.get('positions') or []
        if not pos: break
        for j in pos:
            t=j.get('t_update') or j.get('t_create')
            if not t: continue
            ts=datetime.fromtimestamp(t,tz=timezone.utc)
            out.append(dict(src='EF',co=co,title=(j.get('name') or '').strip(),
                            loc='; '.join(j.get('locations') or ([j.get('location')] if j.get('location') else [])),
                            url=j.get('canonicalPositionUrl') or '',ts=ts,
                            text=clean(j.get('job_description','')),datekind='updated'))
    return out

# --------------------------------------------------------- SmartRecruiters ---
def sr(co,pages=3):
    out=[]
    for p in range(pages):
        try: d=get("https://api.smartrecruiters.com/v1/companies/%s/postings?limit=100&offset=%d"%(co,p*100))
        except Exception: break
        content=d.get('content') or []
        if not content: break
        for j in content:
            try: ts=datetime.fromisoformat(j['releasedDate'].replace('Z','+00:00'))
            except Exception: continue
            loc=j.get('location') or {}
            out.append(dict(src='SR',co=co,title=(j.get('name') or '').strip(),
                            loc=', '.join([x for x in (loc.get('city'),loc.get('region'),loc.get('country')) if x]),
                            url="https://jobs.smartrecruiters.com/%s/%s"%(co,j.get('id')),ts=ts,
                            text='',datekind='posted'))
    return out
