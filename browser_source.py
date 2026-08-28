#!/usr/bin/env python3.11
"""Playwright-backed readers for boards that refuse plain HTTP.

Run as a SUBPROCESS (python3.11) by scan_all.py, never imported: the scanner
runs on the system python (3.7) and Playwright needs >=3.8.  Keeping it out of
process also means a hung browser can be killed without touching the scan.

Contract: prints one JSON list of normalized job dicts to stdout.
    python3.11 browser_source.py '<json spec>'
where spec = {"boards":["meta","tesla"],"max_days":3,"role_re":"...","senior_re":"..."}

All boards share ONE browser and ONE context.  Every board is wrapped so a
timeout or navigation error yields [] for that board instead of aborting.
"""
import asyncio,json,re,sys,time
from datetime import datetime,timezone

UA=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
NAV_MS=45000
BOARD_BUDGET=150       # seconds per board, hard ceiling
DETAIL_CAP=40          # most detail pages to open per board

def clean(h):
    import html as H
    c=H.unescape(h or ''); c=re.sub(r'<[^>]+>',' ',c); return re.sub(r'\s+',' ',c).strip()

# ------------------------------------------------------------------- Meta ---
async def meta(ctx,cfg):
    """metacareers.com is a Relay/GraphQL app; the job list arrives in a
    job_search_with_featured_jobs_v2 response.  We intercept it rather than
    scraping the DOM.  NOTE: that payload carries no posting date."""
    role=re.compile(cfg['role_re'],re.I); senior=re.compile(cfg['senior_re'],re.I)
    jobs={}
    pg=await ctx.new_page()
    async def on_resp(r):
        if 'graphql' not in r.url: return
        try: t=await r.text()
        except Exception: return
        if 'all_jobs' not in t: return
        try: d=json.loads(t)
        except Exception: return
        node=((d.get('data') or {}).get('job_search_with_featured_jobs_v2') or {})
        for j in (node.get('all_jobs') or []):
            if j.get('id'): jobs[j['id']]=j
    pg.on('response',on_resp)
    try:
        await pg.goto("https://www.metacareers.com/jobs",wait_until='domcontentloaded',timeout=NAV_MS)
        await pg.wait_for_timeout(9000)
    except Exception as e:
        sys.stderr.write("  meta: nav failed: %r\n"%e)
    sys.stderr.write("  meta: %d jobs in listing\n"%len(jobs))
    keep=[j for j in jobs.values()
          if role.search(j.get('title') or '') and not senior.search(j.get('title') or '')]
    sys.stderr.write("  meta: %d after title filter\n"%len(keep))
    out=[]; now=datetime.now(timezone.utc)
    for j in keep[:DETAIL_CAP]:
        url="https://www.metacareers.com/jobs/%s/"%j['id']
        text=''
        try:
            await pg.goto(url,wait_until='domcontentloaded',timeout=NAV_MS)
            await pg.wait_for_timeout(1200)
            text=clean(await pg.inner_text('body'))
        except Exception: pass
        out.append(dict(src='META',co='meta',title=(j.get('title') or '').strip(),
                        loc='; '.join(j.get('locations') or []),url=url,
                        ts=now.isoformat(),text=text,datekind='undated'))
    await pg.close()
    return out

# ------------------------------------------------------------------ Tesla ---
async def tesla(ctx,cfg):
    """tesla.com/careers sits behind Akamai Bot Manager, which rejects headless
    Chromium (403 Access Denied) as well as plain HTTP.  Kept so the attempt is
    logged; returns [] rather than pretending."""
    pg=await ctx.new_page()
    try:
        r=await pg.goto("https://www.tesla.com/careers/search/",wait_until='domcontentloaded',timeout=NAV_MS)
        st=r.status if r else None
        sys.stderr.write("  tesla: status=%s\n"%st)
        if st and st>=400: await pg.close(); return []
        await pg.wait_for_timeout(6000)
        hrefs=await pg.eval_on_selector_all('a','e=>e.map(x=>x.href).filter(h=>/careers\\/job\\//.test(h))')
        sys.stderr.write("  tesla: %d job links\n"%len(hrefs))
    except Exception as e:
        sys.stderr.write("  tesla: failed %r\n"%e)
    await pg.close(); return []

BOARDS={'meta':meta,'tesla':tesla}

async def main():
    cfg=json.loads(sys.argv[1]) if len(sys.argv)>1 else {}
    cfg.setdefault('role_re',r'engineer|developer|scientist')
    cfg.setdefault('senior_re',r'\b(senior|staff|principal|lead|manager|director)\b')
    names=[b for b in cfg.get('boards',list(BOARDS)) if b in BOARDS]
    out=[]
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        sys.stderr.write("playwright unavailable: %r\n"%e); print("[]"); return
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
        ctx=await browser.new_context(user_agent=UA,locale='en-US',
            viewport={'width':1440,'height':900},
            extra_http_headers={'Accept-Language':'en-US,en;q=0.9'})
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        for n in names:                       # one context, shared by every board
            t0=time.time()
            try:
                rows=await asyncio.wait_for(BOARDS[n](ctx,cfg),timeout=BOARD_BUDGET)
                out.extend(rows)
                sys.stderr.write("  %s: %d rows in %.0fs\n"%(n,len(rows),time.time()-t0))
            except asyncio.TimeoutError:
                sys.stderr.write("  %s: TIMEOUT after %ds -- skipped\n"%(n,BOARD_BUDGET))
            except Exception as e:
                sys.stderr.write("  %s: FAILED %r -- skipped\n"%(n,e))
        await ctx.close(); await browser.close()
    print(json.dumps(out))

if __name__=='__main__':
    asyncio.run(main())
