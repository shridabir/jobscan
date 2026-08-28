#!/usr/bin/env python3
"""Probe candidate boards for major H-1B-sponsoring employers across every ATS
we can read publicly. Writes validated slugs to *_live.txt / wd_live.txt etc."""
import json,sys,urllib.request,urllib.error,concurrent.futures as cf,itertools,ssl

UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36'
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE

def req(url,data=None,timeout=25,hdr=None):
    h={'User-Agent':UA,'Accept':'application/json'}
    if data is not None: h['Content-Type']='application/json'
    h.update(hdr or {})
    r=urllib.request.Request(url,data=(json.dumps(data).encode() if data is not None else None),headers=h)
    with urllib.request.urlopen(r,timeout=timeout,context=CTX) as f: return json.load(f)

# ---------- per-ATS probes: return job count or -1 ----------
def p_gh(s):
    try: return len(req("https://boards-api.greenhouse.io/v1/boards/%s/jobs"%s).get('jobs',[]))
    except Exception: return -1
def p_lv(s):
    try:
        d=req("https://api.lever.co/v0/postings/%s?mode=json"%s); return len(d) if isinstance(d,list) else -1
    except Exception: return -1
def p_ab(s):
    try: return len(req("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true"%s).get('jobs',[]))
    except Exception: return -1
def p_sr(s):
    try: return int(req("https://api.smartrecruiters.com/v1/companies/%s/postings?limit=1"%s).get('totalFound',0))
    except Exception: return -1
def p_wd(triple):
    t,wd,site=triple
    try:
        d=req("https://%s.%s.myworkdayjobs.com/wday/cxs/%s/%s/jobs"%(t,wd,t,site),
              data={"appliedFacets":{},"limit":1,"offset":0,"searchText":""})
        return int(d.get('total',0))
    except Exception: return -1
def p_ef(pair):
    host,dom=pair
    try:
        d=req("https://%s/api/apply/v2/jobs?domain=%s&start=0&num=1"%(host,dom))
        return int(d.get('count',0))
    except Exception: return -1

def run(fn,items,label,workers=24):
    live=[]
    with cf.ThreadPoolExecutor(workers) as ex:
        for it,n in zip(items,ex.map(fn,items)):
            if n>0:
                live.append(it); sys.stderr.write("  OK %-46s %d\n"%(it if isinstance(it,str) else '/'.join(it),n))
    sys.stderr.write("%s: %d/%d live\n"%(label,len(live),len(items)))
    return live
