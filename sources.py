#!/usr/bin/env python3
"""Extra ATS readers for the major H-1B sponsors that are not on
Greenhouse/Lever/Ashby: Workday (CXS), Phenom, Oracle Recruiting Cloud,
Amazon, Eightfold and SmartRecruiters.

Every reader returns the normalized dict the scanner already consumes:
    dict(src, co, title, loc, url, ts, text, datekind)

These boards are far bigger than the startup boards (Amazon alone posts
thousands a day) and most of them only expose the job description behind a
second per-job request.  So each reader takes the scanner's cheap predicates
(`title_ok`, `loc_ok`) plus a freshness window, applies them to the listing
fields first, and only then pays for the detail call on the survivors.
"""
import json,re,html,ssl,time,urllib.request,urllib.error,urllib.parse,concurrent.futures as cf
from datetime import datetime,timedelta,timezone

UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36'
# a few of these hosts serve an incomplete cert chain; we only read public postings
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE

import http.cookiejar as _cj
JAR=_cj.CookieJar()
OPENER=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR),
                                   urllib.request.HTTPSHandler(context=CTX))

def _open(req,timeout):
    with OPENER.open(req,timeout=timeout) as f:
        raw=f.read()
        if (f.headers.get('Content-Encoding') or '').lower()=='gzip':
            import gzip; raw=gzip.decompress(raw)
        return raw

def get(url,data=None,timeout=45,hdr=None,tries=3):
    h={'User-Agent':UA,'Accept':'application/json'}
    if data is not None: h['Content-Type']='application/json'
    h.update(hdr or {})
    body=json.dumps(data).encode() if data is not None else None
    for i in range(tries):
        r=urllib.request.Request(url,data=body,headers=h)
        try: return json.loads(_open(r,timeout).decode('utf-8','replace'))
        except urllib.error.HTTPError as e:
            # these boards rate-limit when several readers run at once
            if e.code in (429,503) and i<tries-1: time.sleep(2*(i+1)); continue
            raise

def clean(h):
    c=html.unescape(h or ''); c=re.sub(r'<[^>]+>',' ',c); return re.sub(r'\s+',' ',c).strip()

def iso(t):
    """Parse ISO-8601 with a trailing Z and any fractional-second precision (py3.7 safe)."""
    if not t: return None
    t=t.strip().replace('Z','+00:00')
    # '+0000' / '-0500' -> '+00:00' (py<3.11 fromisoformat needs the colon)
    t=re.sub(r'([+-]\d{2})(\d{2})$',r'\1:\2',t)
    m=re.match(r'^(.*?\.)(\d+)(.*)$',t)
    if m: t=m.group(1)+(m.group(2)+'000000')[:6]+m.group(3)
    try: d=datetime.fromisoformat(t)
    except Exception: return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def _yes(_): return True
def _pmap(fn,items,workers=8):
    if not items: return []
    with cf.ThreadPoolExecutor(workers) as ex: return [r for r in ex.map(fn,items) if r]

# ---------------------------------------------------------------- Workday ---
# The listing carries a coarse "Posted Today / Yesterday / N Days Ago" string;
# descriptions need one call per job, so we filter on the listing first.
_WD_RECENT=re.compile(r'posted\s+(today|yesterday|1\s+day\s+ago)',re.I)

def _wd_fresh(posted_on,max_days):
    p=posted_on or ''
    if _WD_RECENT.search(p): return True
    m=re.search(r'posted\s+(\d+)\+?\s*days?\s+ago',p,re.I)
    return bool(m) and int(m.group(1))<=max_days

def wd(spec,title_ok=_yes,loc_ok=_yes,max_days=1,page_cap=6):
    """spec: 'tenant|wdhost|site' e.g. 'nvidia|wd5|NVIDIAExternalCareerSite'"""
    t,hostn,site=spec.split('|')
    base="https://%s.%s.myworkdayjobs.com"%(t,hostn)
    cxs="%s/wday/cxs/%s/%s"%(base,t,site)
    stubs=[]
    for page in range(page_cap):
        try: d=get(cxs+"/jobs",data={"appliedFacets":{},"limit":20,"offset":page*20,"searchText":""})
        except Exception: break
        posts=d.get('jobPostings') or []
        if not posts: break
        stale=0
        for j in posts:
            if not _wd_fresh(j.get('postedOn'),max_days): stale+=1; continue
            ttl=(j.get('title') or '').strip(); loc=j.get('locationsText') or ''
            if not title_ok(ttl): continue
            # "2 Locations" hides the real list -- keep it, the detail call resolves it
            if 'location' not in loc.lower() and not loc_ok(loc): continue
            stubs.append((ttl,loc,j.get('externalPath') or ''))
        if stale==len(posts): break     # listing is newest-first
    def detail(s):
        ttl,loc,path=s
        try: d=get(cxs+path)
        except Exception: return None
        i=d.get('jobPostingInfo') or {}
        try: ts=datetime.fromisoformat(i['startDate']).replace(tzinfo=timezone.utc)
        except Exception: return None
        return dict(src='WD',co=t,title=(i.get('title') or ttl).strip(),loc=i.get('location') or loc,
                    url=i.get('externalUrl') or (base+'/'+site+path),ts=ts,
                    text=clean(i.get('jobDescription','')),datekind='posted')
    return _pmap(detail,stubs)

# ------------------------------------------------------------------ Phenom ---
_PH_BODY={"lang":"en_us","deviceType":"desktop","country":"us","pageName":"search-results",
 "ddoKey":"refineSearch","sortBy":"Most recent","subsearch":"","jobs":True,"counts":True,
 "all_fields":["category","country","state","city"],"clearAll":False,"jdsource":"facets",
 "isSliderEnable":False,"pageId":"page37","siteType":"external","keywords":""}

def ph(spec,title_ok=_yes,loc_ok=_yes,max_days=1,page_cap=4):
    """spec: 'company|careers-host' e.g. 'cisco|careers.cisco.com'"""
    co,host=spec.split('|')
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    stubs=[]
    for p in range(page_cap):
        b=dict(_PH_BODY,**{"from":p*50,"size":50})
        try: d=get("https://%s/widgets"%host,data=b)
        except Exception: break
        jobs=((d.get('refineSearch') or {}).get('data') or {}).get('jobs') or []
        if not jobs: break
        for j in jobs:
            try: ts=datetime.fromisoformat((j.get('postedDate') or '').replace('Z','+00:00'))
            except Exception: continue
            if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
            if ts<cut: continue
            ttl=(j.get('title') or '').strip(); loc=j.get('location') or j.get('cityState') or ''
            if not title_ok(ttl) or not loc_ok(loc): continue
            stubs.append((ttl,loc,ts,j.get('jobSeqNo'),j.get('applyUrl') or ''))
    def detail(s):
        ttl,loc,ts,seq,apply_url=s
        text=''
        if seq:
            try:
                d=get("https://%s/widgets"%host,data=dict(_PH_BODY,**{
                    "ddoKey":"jobDetail","jobSeqNo":seq,"pageName":"job-details"}))
                jd=(d.get('jobDetail') or {}).get('data',{}).get('job',{}) or {}
                text=clean(jd.get('description','')+' '+(jd.get('qualifications') or ''))
            except Exception: pass
        return dict(src='PH',co=co,title=ttl,loc=loc,url=apply_url,ts=ts,text=text,datekind='posted')
    return _pmap(detail,stubs)

# ------------------------------------------------- Oracle Recruiting Cloud ---
def orc(spec,title_ok=_yes,loc_ok=_yes,max_days=1):
    """spec: 'company|host|siteNumber' e.g. 'oracle|eeho.fa.us2.oraclecloud.com|CX_45001'"""
    co,host,site=spec.split('|')
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    url=("https://%s/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
         "&expand=requisitionList.secondaryLocations,flexFieldsFacet.values"
         "&finder=findReqs;siteNumber=%s,limit=200,sortBy=POSTING_DATES_DESC"%(host,site))
    try: items=(get(url).get('items') or [{}])[0].get('requisitionList') or []
    except Exception: return []
    stubs=[]
    for j in items:
        try: ts=datetime.fromisoformat((j.get('PostedDate') or '').replace('Z','+00:00'))
        except Exception: continue
        if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
        if ts<cut: continue
        locs=[j.get('PrimaryLocation') or '']+[s.get('Name','') for s in (j.get('secondaryLocations') or [])]
        loc='; '.join([x for x in locs if x]); ttl=(j.get('Title') or '').strip()
        if not title_ok(ttl) or not loc_ok(loc): continue
        stubs.append((ttl,loc,ts,j.get('Id')))
    def detail(s):
        ttl,loc,ts,jid=s
        text=''
        try:
            d=get("https://%s/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                  "?expand=all&onlyData=true&finder=ById;Id=%s,siteNumber=%s"%(host,jid,site))
            it=(d.get('items') or [{}])[0]
            text=clean((it.get('ExternalDescriptionStr') or '')+' '+(it.get('ExternalQualificationsStr') or ''))
        except Exception: pass
        return dict(src='ORC',co=co,title=ttl,loc=loc,ts=ts,text=text,datekind='posted',
                    url="https://%s/hcmUI/CandidateExperience/en/sites/%s/job/%s"%(host,site,jid))
    return _pmap(detail,stubs)

# ----------------------------------------------------------------- Amazon ---
def amazon(_=None,title_ok=_yes,loc_ok=_yes,max_days=1,max_pages=20):
    """amazon.jobs exposes the full description in the listing, so no detail call."""
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    out=[]; stale_pages=0
    for page in range(max_pages):
        u=("https://www.amazon.jobs/en/search.json?result_limit=100&offset=%d&sort=recent"
           "&normalized_country_code[]=USA&base_query="%(page*100))
        try: js=(get(u).get('jobs') or [])
        except Exception: break
        if not js: break
        fresh_here=0
        for j in js:
            try: ts=datetime.strptime(j['posted_date'],'%B %d, %Y').replace(tzinfo=timezone.utc)
            except Exception: continue
            if ts<cut: continue
            fresh_here+=1
            ttl=(j.get('title') or '').strip()
            loc=j.get('normalized_location') or j.get('location') or ''
            if not title_ok(ttl) or not loc_ok(loc): continue
            out.append(dict(src='AMZN',co='amazon',title=ttl,loc=loc,ts=ts,datekind='posted',
                url='https://www.amazon.jobs'+(j.get('job_path') or ''),
                text=clean(' '.join([j.get('description') or '',j.get('basic_qualifications') or '',
                                     j.get('preferred_qualifications') or '']))))
        stale_pages=stale_pages+1 if fresh_here==0 else 0
        if stale_pages>=3: break     # sort=recent is only roughly ordered
    return out

# -------------------------------------------------------------- Eightfold ---
def ef(spec,title_ok=_yes,loc_ok=_yes,max_days=1,pages=3):
    """spec: 'host|domain' e.g. 'explore.jobs.netflix.net|netflix.com'"""
    host,dom=spec.split('|'); co=dom.split('.')[0]
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    stubs=[]
    for p in range(pages):
        try: d=get("https://%s/api/apply/v2/jobs?domain=%s&start=%d&num=100&sort_by=timestamp"%(host,dom,p*100))
        except Exception: break
        pos=d.get('positions') or []
        if not pos: break
        for j in pos:
            t=j.get('t_update') or j.get('t_create')
            if not t: continue
            ts=datetime.fromtimestamp(t,tz=timezone.utc)
            if ts<cut: continue
            ttl=(j.get('name') or '').strip()
            loc='; '.join(j.get('locations') or ([j.get('location')] if j.get('location') else []))
            if not title_ok(ttl) or not loc_ok(loc): continue
            stubs.append((ttl,loc,ts,j.get('id'),j.get('canonicalPositionUrl') or ''))
    def detail(s):
        ttl,loc,ts,jid,url=s
        text=''
        try: text=clean(get("https://%s/api/apply/v2/jobs/%s?domain=%s"%(host,jid,dom)).get('job_description',''))
        except Exception: pass
        return dict(src='EF',co=co,title=ttl,loc=loc,url=url,ts=ts,text=text,datekind='updated')
    return _pmap(detail,stubs)

# --------------------------------------------------------- SmartRecruiters ---
def sr(co,title_ok=_yes,loc_ok=_yes,max_days=1,pages=3):
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    stubs=[]
    for p in range(pages):
        try: content=get("https://api.smartrecruiters.com/v1/companies/%s/postings?limit=100&offset=%d"%(co,p*100)).get('content') or []
        except Exception: break
        if not content: break
        for j in content:
            try: ts=datetime.fromisoformat(j['releasedDate'].replace('Z','+00:00'))
            except Exception: continue
            if ts<cut: continue
            l=j.get('location') or {}
            loc=', '.join([x for x in (l.get('city'),l.get('region'),l.get('country')) if x])
            ttl=(j.get('name') or '').strip()
            if not title_ok(ttl) or not loc_ok(loc): continue
            stubs.append((ttl,loc,ts,j.get('id')))
    def detail(s):
        ttl,loc,ts,jid=s
        text=''
        try:
            d=get("https://api.smartrecruiters.com/v1/companies/%s/postings/%s"%(co,jid))
            secs=(d.get('jobAd') or {}).get('sections') or {}
            text=clean(' '.join((secs.get(k) or {}).get('text','') for k in
                                ('companyDescription','jobDescription','qualifications','additionalInformation')))
        except Exception: pass
        return dict(src='SR',co=co,title=ttl,loc=loc,ts=ts,text=text,datekind='posted',
                    url="https://jobs.smartrecruiters.com/%s/%s"%(co,jid))
    return _pmap(detail,stubs)


# ------------------------------------------------------------------ Google ---
# careers.google.com is server-rendered: the results are in an AF_initDataCallback
# blob, descriptions included, with a true publish epoch.  No API key needed.
_AF=re.compile(r"AF_initDataCallback\((\{.*?\})\);",re.S)

def _html(url,timeout=45,hdr=None):
    h={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
       'Accept-Language':'en-US,en;q=0.9'}
    h.update(hdr or {})
    r=urllib.request.Request(url,headers=h)
    return _open(r,timeout).decode('utf-8','replace')

def goog(_=None,title_ok=_yes,loc_ok=_yes,max_days=1,page_cap=8):
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    out=[]
    for pg in range(1,page_cap+1):
        u=("https://www.google.com/about/careers/applications/jobs/results"
           "?sort_by=date&location=United%%20States&page=%d"%pg)
        try: html_=_html(u)
        except Exception: break
        blob=None
        for b in _AF.findall(html_):
            if "'ds:1'" in b: blob=b; break
        if not blob: break
        m=re.search(r"data:(\[.*\]), sideChannel",blob,re.S)
        if not m: break
        try: jobs=json.loads(m.group(1))[0] or []
        except Exception: break
        if not jobs: break
        fresh=0
        for j in jobs:
            try: ts=datetime.fromtimestamp(j[12][0],tz=timezone.utc)
            except Exception: continue
            if ts<cut: continue
            fresh+=1
            ttl=(j[1] or '').strip()
            locs=[x[0] for x in (j[9] or []) if x and x[0]]
            loc='; '.join(locs)
            if not title_ok(ttl) or not loc_ok(loc): continue
            body=' '.join(clean((x[1] if isinstance(x,list) and len(x)>1 else '') or '')
                          for x in (j[3],j[4],j[10],j[19]))
            # j[2] is the sign-in/apply link; the results permalink is friendlier
            url=("https://www.google.com/about/careers/applications/jobs/results/%s"%j[0]) if j[0] else (j[2] or '')
            out.append(dict(src='GOOG',co=(j[7] or 'google').lower(),title=ttl,loc=loc,
                            url=url,ts=ts,text=re.sub(r'\s+',' ',body).strip(),datekind='posted'))
        if fresh==0: break        # sorted by date, so an all-stale page ends it
    return out

# ------------------------------------------------------------------- Apple ---
# jobs.apple.com is a React-Router SSR app; results (and a true postDateInGMT)
# live in window.__staticRouterHydrationData.  The /api/v1 endpoints need auth,
# the hydration path does not.  jobSummary is a teaser -> detail call for the body.
_HYD=re.compile(r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("(.*?)"\);',re.S)

def _apple_hydrate(url):
    try: h=_html(url,hdr={'Referer':'https://jobs.apple.com/'})
    except Exception: return None
    m=_HYD.search(h)
    if not m: return None
    try: return json.loads(json.loads('"%s"'%m.group(1)))
    except Exception: return None

def appl(_=None,title_ok=_yes,loc_ok=_yes,max_days=1,page_cap=6):
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    stubs=[]
    for pg in range(1,page_cap+1):
        d=_apple_hydrate("https://jobs.apple.com/en-us/search?sort=newest"
                         "&location=united-states-USA&page=%d"%pg)
        if not d: break
        sr=(d.get('loaderData') or {}).get('search') or {}
        res=sr.get('searchResults') or []
        if not res: break
        fresh=0
        for j in res:
            ts=iso(j.get('postDateInGMT'))
            if ts is None or ts<cut: continue
            fresh+=1
            ttl=(j.get('postingTitle') or '').strip()
            locs=[', '.join([x for x in (l.get('city'),l.get('stateProvince'),l.get('countryName')) if x])
                  for l in (j.get('locations') or [])]
            loc='; '.join([x for x in locs if x])
            if not title_ok(ttl) or not loc_ok(loc): continue
            slug=j.get('transformedPostingTitle') or ''
            stubs.append((ttl,loc,ts,j.get('positionId') or j.get('id'),slug,j.get('jobSummary') or ''))
        if fresh==0: break
    def detail(s):
        ttl,loc,ts,pid,slug,summary=s
        url="https://jobs.apple.com/en-us/details/%s/%s"%(pid,slug)
        text=clean(summary)
        # /api/v1/jobDetails only answers once the search page has set cookies,
        # which the listing loop above has already done on the shared jar.
        try:
            d=get("https://jobs.apple.com/api/v1/jobDetails/%s?locale=en-us"%pid,
                  hdr={'Referer':url}).get('res') or {}
            parts=[d.get(k) or '' for k in ('jobSummary','description','keyQualifications',
                                            'minimumQualifications','preferredQualifications',
                                            'educationAndExperience')]
            body=clean(' '.join(p for p in parts if isinstance(p,str)))
            if len(body)>len(text): text=body
            locs=[', '.join([x for x in (l.get('city'),l.get('stateProvince'),
                                         (l.get('countryName') or '')) if x])
                  for l in (d.get('locations') or [])]
            if any(locs): loc='; '.join([x for x in locs if x])
        except Exception: pass
        return dict(src='APPL',co='apple',title=ttl,loc=loc,url=url,ts=ts,text=text,datekind='posted')
    return _pmap(detail,stubs,workers=6)


# -------------------------------------------------------------- Microsoft ---
# The search API is NOT on careers.microsoft.com -- it lives on
# apply.careers.microsoft.com (an Eightfold "pcsx" backend) and answers plain
# GETs.  Listing has a true postedTs epoch; the body needs a details call.
def msft(_=None,title_ok=_yes,loc_ok=_yes,max_days=1,page_cap=6):
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    H={'Referer':'https://jobs.careers.microsoft.com/','Origin':'https://jobs.careers.microsoft.com'}
    stubs=[]
    for pg in range(page_cap):
        u=("https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query="
           "&location=United%%20States&start=%d&num=20&sort_by=timestamp&domain_source=careers"%(pg*20))
        try: pos=((get(u,hdr=H).get('data') or {}).get('positions')) or []
        except Exception: break
        if not pos: break
        fresh=0
        for j in pos:
            try: ts=datetime.fromtimestamp(int(j.get('postedTs') or j.get('creationTs')),tz=timezone.utc)
            except Exception: continue
            if ts<cut: continue
            fresh+=1
            ttl=(j.get('name') or '').strip(); loc='; '.join(j.get('locations') or [])
            if not title_ok(ttl) or not loc_ok(loc): continue
            stubs.append((ttl,loc,ts,j.get('id')))
        if fresh==0: break     # sort_by=timestamp, so an all-stale page ends it
    def detail(s):
        ttl,loc,ts,pid=s
        text=''
        try:
            d=get("https://apply.careers.microsoft.com/api/pcsx/position_details"
                  "?position_id=%s&domain=microsoft.com&hl=en"%pid,hdr=H).get('data') or {}
            text=clean(d.get('jobDescription') or '')
        except Exception: pass
        return dict(src='MSFT',co='microsoft',title=ttl,loc=loc,ts=ts,text=text,datekind='posted',
                    url="https://jobs.careers.microsoft.com/global/en/job/%s"%pid)
    return _pmap(detail,stubs)

# -------------------------------------------------------------------- IBM ---
# www-api.ibm.com/search/api/v2 answers POST only (a GET 404s) and returns the
# description in the listing.  NOTE: the index exposes no posting-date field,
# so IBM rows are marked datekind='undated' -- they carry no real timestamp.
def ibm(_=None,title_ok=_yes,loc_ok=_yes,max_days=1,page_cap=4):
    now=datetime.now(timezone.utc); out=[]
    for pg in range(page_cap):
        body={"appId":"careers","scopes":["careers2"],"query":{"bool":{"must":[]}},
              "size":50,"from":pg*50,"sort":[{"_score":"desc"},{"pageviews":"desc"}],
              "lang":"zz","localeSelector":{},"sm":{"query":"","lang":"zz"},
              "_source":["_id","title","url","description","field_keyword_05",
                         "field_keyword_08","field_keyword_17","field_keyword_18"]}
        try: hits=((get("https://www-api.ibm.com/search/api/v2",data=body,
                        hdr={'Referer':'https://www.ibm.com/'}).get('hits') or {}).get('hits')) or []
        except Exception: break
        if not hits: break
        for h in hits:
            j=h.get('_source') or {}
            ttl=(j.get('title') or '').strip(); loc=j.get('field_keyword_05') or ''
            if not title_ok(ttl) or not loc_ok(loc): continue
            out.append(dict(src='IBM',co='ibm',title=ttl,loc=loc,ts=now,
                            url=j.get('url') or '',text=clean(j.get('description') or ''),
                            datekind='undated'))
    return out


# ----------------------------------------------------- Goldman Sachs (GS) ---
# higher.gs.com is a Next.js app over a public GraphQL gateway.  The listing
# query carries no timestamp and neither does the role detail, so GS rows are
# marked datekind='undated'.  Body text comes from the _next/data detail route.
_GS_Q=("query GetRoles($searchQueryInput: RoleSearchQueryInput!) {"
       " roleSearch(searchQueryInput: $searchQueryInput) { totalCount items {"
       " roleId corporateTitle jobTitle jobFunction"
       " locations { primary state country city } status division } } }")

def _gs_build_id():
    try:
        m=re.search(r'"buildId":"([^"]+)"',_html("https://higher.gs.com/roles?page=1"))
        return m.group(1) if m else None
    except Exception: return None

def gs(_=None,title_ok=_yes,loc_ok=_yes,max_days=1,page_cap=6):
    now=datetime.now(timezone.utc); stubs=[]
    for pg in range(page_cap):
        body={"operationName":"GetRoles","variables":{"searchQueryInput":{
                "page":{"pageSize":50,"pageNumber":pg},
                "sort":{"sortStrategy":"RELEVANCE","sortOrder":"DESC"},
                "filters":[],"experiences":["EARLY_CAREER","PROFESSIONAL"],"searchTerm":""}},
              "query":_GS_Q}
        try:
            d=get("https://api-higher.gs.com/gateway/api/v1/graphql",data=body,
                  hdr={'Origin':'https://higher.gs.com','Referer':'https://higher.gs.com/'})
            items=((d.get('data') or {}).get('roleSearch') or {}).get('items') or []
        except Exception: break
        if not items: break
        for j in items:
            ttl=(j.get('jobTitle') or '').strip()
            loc='; '.join(', '.join([x for x in (l.get('city'),l.get('state'),l.get('country')) if x])
                          for l in (j.get('locations') or []))
            if not title_ok(ttl) or not loc_ok(loc): continue
            stubs.append((ttl,loc,j.get('roleId') or ''))
    bid=_gs_build_id() if stubs else None
    def detail(s):
        ttl,loc,rid=s
        num=rid.split('_')[0]
        url="https://higher.gs.com/roles/%s"%num
        text=''
        if bid:
            try:
                d=get("https://higher.gs.com/_next/data/%s/roles/%s.json?roleId=%s"%(bid,num,num))
                role=((d.get('pageProps') or {}).get('role')) or {}
                text=clean(role.get('descriptionHtml') or '')
            except Exception: pass
        return dict(src='GS',co='goldmansachs',title=ttl,loc=loc,url=url,ts=now,
                    text=text,datekind='undated')
    return _pmap(detail,stubs,workers=6)


# ------------------------------------------------------------------ iCIMS ---
# iCIMS tenants front their board with a careers site that exposes
# /api/jobs -- one call returns title, a true posted_date, location AND the
# full description, so there is no per-job detail fetch at all.
# Sorting newest-first is supported, so a stale page ends the walk.
def ic(spec,title_ok=_yes,loc_ok=_yes,max_days=1,page_cap=8):
    """spec: 'company|careers-host'  e.g. 'garmin|careers.garmin.com'"""
    co,host=spec.split('|')
    cut=datetime.now(timezone.utc)-timedelta(days=max_days+1)
    out=[]
    for pg in range(1,page_cap+1):
        u=("https://%s/api/jobs?limit=100&page=%d&sortBy=posted_date&descending=true"%(host,pg))
        try: js=(get(u,hdr={'Referer':'https://%s/'%host}).get('jobs')) or []
        except Exception: break
        if not js: break
        fresh=0
        for raw in js:
            j=raw.get('data') if isinstance(raw,dict) and 'data' in raw else raw
            ts=iso(j.get('posted_date') or j.get('create_date'))
            if ts is None or ts<cut: continue
            fresh+=1
            ttl=(j.get('title') or '').strip()
            loc=j.get('full_location') or ', '.join(
                [x for x in (j.get('city'),j.get('state'),j.get('country')) if x])
            if not title_ok(ttl) or not loc_ok(loc): continue
            body=' '.join(str(j.get(k) or '') for k in
                          ('description','responsibilities','qualifications'))
            out.append(dict(src='IC',co=co,title=ttl,loc=loc,ts=ts,datekind='posted',
                            url="https://%s/jobs/%s"%(host,j.get('req_id') or j.get('slug') or ''),
                            text=clean(body)))
        if fresh==0: break     # newest-first, so an all-stale page ends it
    return out

READERS=dict(WD=wd,PH=ph,ORC=orc,AMZN=amazon,EF=ef,SR=sr,GOOG=goog,APPL=appl,MSFT=msft,IBM=ibm,GS=gs,IC=ic)
