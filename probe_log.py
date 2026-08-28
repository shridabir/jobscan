#!/usr/bin/env python3
"""Verbose probe harness: cookie jar, realistic headers, GET+POST, full logging.
Logs exactly what was sent and what came back (status, content-type, first 500B).
"""
import json,sys,ssl,gzip,zlib,http.cookiejar as cj,urllib.request as ur,urllib.parse,re

CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA=('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

JAR=cj.CookieJar()
OPENER=ur.build_opener(ur.HTTPCookieProcessor(JAR),ur.HTTPSHandler(context=CTX))

def hdrs(origin=None,extra=None,json_body=False):
    h={'User-Agent':UA,
       'Accept':'application/json, text/plain, */*',
       'Accept-Language':'en-US,en;q=0.9',
       'Accept-Encoding':'gzip, deflate',
       'Connection':'keep-alive'}
    if json_body: h['Content-Type']='application/json'
    if origin:
        h['Origin']=origin.rstrip('/'); h['Referer']=origin if origin.endswith('/') else origin+'/'
    h.update(extra or {})
    return h

def _decode(resp,raw):
    enc=(resp.headers.get('Content-Encoding') or '').lower()
    if 'gzip' in enc:
        try: raw=gzip.decompress(raw)
        except Exception: pass
    elif 'deflate' in enc:
        try: raw=zlib.decompress(raw)
        except Exception:
            try: raw=zlib.decompress(raw,-zlib.MAX_WBITS)
            except Exception: pass
    return raw

def probe(label,url,method='GET',body=None,origin=None,extra=None,timeout=30,quiet=False,show=500):
    """Returns (status, content_type, text, resp_headers). Never raises."""
    data=None; jb=False
    if body is not None:
        if isinstance(body,(dict,list)): data=json.dumps(body).encode(); jb=True
        elif isinstance(body,str): data=body.encode()
        else: data=body
    h=hdrs(origin,extra,json_body=jb)
    req=ur.Request(url,data=data,headers=h,method=method)
    sent="%s %s\n    headers: %s\n    body: %s"%(
        method,url,{k:v for k,v in h.items() if k not in ('Accept-Encoding','Connection')},
        (json.dumps(body)[:220] if body is not None else None))
    try:
        with OPENER.open(req,timeout=timeout) as r:
            raw=_decode(r,r.read())
            txt=raw.decode('utf-8','replace')
            st=r.status; ct=r.headers.get('Content-Type',''); rh=dict(r.headers)
    except ur.HTTPError as e:
        raw=_decode(e,e.read()); txt=raw.decode('utf-8','replace')
        st=e.code; ct=e.headers.get('Content-Type','') if e.headers else ''; rh=dict(e.headers or {})
    except Exception as e:
        st=0; ct=''; txt=repr(e); rh={}
    if not quiet:
        print("--- %s"%label)
        print("    SENT %s"%sent)
        print("    GOT  status=%s content-type=%s len=%d"%(st,ct,len(txt)))
        print("    BODY %s"%txt[:show].replace('\n',' '))
        print()
    return st,ct,txt,rh

def jget(txt):
    try: return json.loads(txt)
    except Exception: return None

def page(url,origin=None,extra=None,timeout=30):
    """GET an HTML page (for cookies / token scraping)."""
    h=hdrs(origin,extra); h['Accept']='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    req=ur.Request(url,headers=h)
    try:
        with OPENER.open(req,timeout=timeout) as r: return r.status,_decode(r,r.read()).decode('utf-8','replace'),dict(r.headers)
    except ur.HTTPError as e:
        return e.code,_decode(e,e.read()).decode('utf-8','replace'),dict(e.headers or {})
    except Exception as e:
        return 0,repr(e),{}

def cookies(): return {c.name:c.value for c in JAR}
