#!/usr/bin/env python3
"""Find and validate new company boards, then print boards.tsv lines.

  python3 discover.py gh stripe airbnb          # probe Greenhouse slugs
  python3 discover.py wd nvidia|wd5|SiteName    # probe a Workday triple
  python3 discover.py ic garmin|careers.garmin.com  # probe an iCIMS careers site
  python3 discover.py phenom careers.cisco.com  # Phenom site -> underlying Workday triple

The phenom mode is the useful one for big employers: most Fortune-500 career
sites are Phenom front-ends whose applyUrl leaks the real Workday tenant/site,
which we can then read directly (with full descriptions) via sources.wd().
"""
import sys,re,concurrent.futures as cf
from sources import get

_PH={"lang":"en_us","deviceType":"desktop","country":"us","pageName":"search-results",
 "ddoKey":"refineSearch","sortBy":"","subsearch":"","from":0,"jobs":True,"counts":True,
 "all_fields":["category","country","state","city"],"size":10,"clearAll":False,
 "jdsource":"facets","isSliderEnable":False,"pageId":"page37","siteType":"external","keywords":""}

def gh(s):
    try: return len(get("https://boards-api.greenhouse.io/v1/boards/%s/jobs"%s).get('jobs',[]))
    except Exception: return -1
def lv(s):
    try:
        d=get("https://api.lever.co/v0/postings/%s?mode=json"%s); return len(d) if isinstance(d,list) else -1
    except Exception: return -1
def ab(s):
    try: return len(get("https://api.ashbyhq.com/posting-api/job-board/%s"%s).get('jobs',[]))
    except Exception: return -1
def sr(s):
    try: return int(get("https://api.smartrecruiters.com/v1/companies/%s/postings?limit=1"%s).get('totalFound',0))
    except Exception: return -1
def ic(spec):
    """spec: 'company|careers-host' -- iCIMS careers front-end exposing /api/jobs."""
    try:
        host=spec.split('|')[-1]
        d=get("https://%s/api/jobs?limit=1"%host,hdr={'Referer':'https://%s/'%host})
        return int(d.get('totalCount') or d.get('count') or 0)
    except Exception: return -1

def wd(spec):
    try:
        t,h,site=spec.split('|')
        return int(get("https://%s.%s.myworkdayjobs.com/wday/cxs/%s/%s/jobs"%(t,h,t,site),
                       data={"appliedFacets":{},"limit":1,"offset":0,"searchText":""}).get('total',0))
    except Exception: return -1
def ef(spec):
    try:
        host,dom=spec.split('|')
        return int(get("https://%s/api/apply/v2/jobs?domain=%s&start=0&num=1"%(host,dom)).get('count',0))
    except Exception: return -1

def phenom(host):
    """Return (totalHits, workday_triple_or_None) for a Phenom careers host."""
    try:
        d=get("https://%s/widgets"%host,data=_PH)
        r=d.get('refineSearch') or {}
        jobs=(r.get('data') or {}).get('jobs') or []
        for j in jobs:
            m=re.search(r'https://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/([^/]+)/',j.get('applyUrl') or '')
            if m: return r.get('totalHits',0),'%s|%s|%s'%(m.group(1),m.group(2),m.group(3))
        return r.get('totalHits',0),None
    except Exception: return -1,None


# A large employer whose board returns almost nothing usually means the site id
# points at one slice of their reqs (e.g. experienced-hire only) rather than the
# whole board.  There's no employee-count feed here, so this is a curated list of
# the >10k-headcount employers jobscan tracks; extend it as boards are added.
LARGE={'amazon','google','microsoft','apple','meta','ibm','oracle','intel','cisco','dell','hp','hpe',
 'nvidia','salesforce','adobe','qualcomm','micron','broadcom','amat','kla','marvell','cadence','nxp',
 'workday','zoom','ebay','paypal','visa','mastercard','amex','capitalone','citi','bankofamerica','ghr',
 'jpmorgan','goldmansachs','morganstanley','wf','wellsfargo','usbank','truist','pnc','bny','statestreet',
 'schwab','fidelity','blackrock','nasdaq','cme','spgi','spglobal','moodys','target','walmart','cvshealth',
 'boeing','3m','danaher','agilent','abbott','pfizer','astrazeneca','novartis','stryker','baxter','uber',
 'netflix','netapp','tesla','garmin','jhuapl','sig','bosch','siemens','sap','accenture','deloitte'}
MIN_EXPECTED=25

def guard_small(company,n,src,spec):
    if n>0 and n<MIN_EXPECTED and company.lower() in LARGE:
        print("# WARNING %s returned only %d postings via %s (%s)."%(company,n,src,spec))
        print("#         A >10k-employee company should list far more -- the site id is")
        print("#         probably wrong or points at one slice (e.g. experienced-hire only).")
        return True
    return False

MODES=dict(gh=(gh,'GH'),lv=(lv,'LV'),ab=(ab,'AB'),sr=(sr,'SR'),wd=(wd,'WD'),ef=(ef,'EF'),ic=(ic,'IC'))

if __name__=='__main__':
    if len(sys.argv)<3: print(__doc__); sys.exit(1)
    mode,items=sys.argv[1],sys.argv[2:]
    if mode=='phenom':
        with cf.ThreadPoolExecutor(8) as ex:
            for h,(tot,trip) in zip(items,ex.map(phenom,items)):
                if tot and tot>0:
                    print("# %s  %d jobs"%(h,tot))
                    if trip and wd(trip)>0: print("1\tWD\t%s\t%s"%(trip,trip.split('|')[0]))
                    else: print("#   no readable Workday behind it (Phenom-only)")
    else:
        fn,src=MODES[mode]
        with cf.ThreadPoolExecutor(8) as ex:
            for it,n in zip(items,ex.map(fn,items)):
                if n>0:
                    co=it.split('|')[0]
                    guard_small(co,n,src,it)
                    print("1\t%s\t%s\t%s"%(src,it,co))
                else:   print("# dead: %s"%it)
