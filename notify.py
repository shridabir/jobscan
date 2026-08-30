#!/usr/bin/env python3
"""Email the roles scan_all.py found, skipping anything already sent.

Reads passed.json, diffs it against seen.json, and mails only the NEW rows so a
daily run doesn't re-send yesterday's list.  seen.json is rewritten afterwards
and is what the workflow commits back to the repo.

Env:
  SMTP_USER / SMTP_PASS   credentials (Gmail needs an App Password, not the
                          account password)
  MAIL_TO                 recipient; defaults to SMTP_USER
  SMTP_HOST / SMTP_PORT   default smtp.gmail.com / 465 (implicit TLS)
  DRY_RUN=1               render and print, send nothing, don't touch seen.json
  ALWAYS_SEND=1           send even when there are no new roles
"""
import json,os,sys,html,smtplib,ssl
from email.message import EmailMessage
from datetime import datetime,timezone,timedelta

PASSED='passed.json'; SEEN='seen.json'; KEEP_DAYS=60

def load(p,default):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return default

def key(r):
    """URL is the stable identity; fall back to company+title+location."""
    return (r.get('url') or '').strip() or '|'.join(
        (r.get('co',''),r.get('title',''),r.get('loc','')))

def fmt_when(r):
    if r.get('datekind')=='undated' or not r.get('posted'): return 'date unknown'
    a=r.get('age_hours')
    rel=('%dh ago'%round(a)) if isinstance(a,(int,float)) and a<48 else (
         '%.1fd ago'%(a/24) if isinstance(a,(int,float)) else '')
    note='' if r.get('datekind')=='posted' else ', updated'
    return '%s (%s%s)'%(r['posted'],rel,note)

def render(rows):
    def esc(x): return html.escape(str(x or ''))
    parts=["<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;color:#111'>"]
    for tier,label in ((1,'Major sponsors'),(2,'Other companies')):
        grp=[r for r in rows if r.get('tier',2)==tier]
        if not grp: continue
        parts.append("<h2 style='font-size:16px;margin:18px 0 8px'>%s &mdash; %d new</h2>"%(label,len(grp)))
        for r in grp:
            spon=' &middot; <b>sponsors</b>' if r.get('pos')=='YES' else ''
            fit=''
            if r.get('resume'):
                stars='&#9679;'*int(r.get('fit') or 0)+'&#9675;'*(5-int(r.get('fit') or 0))
                add=('<br><span style="color:#8a6d1f">add: %s</span>'%esc('; '.join(r.get('add') or []))
                     ) if r.get('add') else ''
                fit=("<br><span style='font-size:12px;color:#333'>resume <b>%s</b> "
                     "<span style='color:#0b5cad;letter-spacing:1px'>%s</span> %s/5%s</span>"
                     %(esc(r['resume']),stars,esc(r.get('fit')),add))
            parts.append(
              "<div style='margin:0 0 14px;padding-left:10px;border-left:3px solid #ddd'>"
              "<a href='%s' style='font-weight:600;color:#0b5cad;text-decoration:none'>%s</a><br>"
              "<span style='color:#444'>%s &middot; %s</span><br>"
              "<span style='color:#777;font-size:12px'>%s &middot; %s%s</span>%s</div>"
              %(esc(r.get('url')),esc(r.get('title')),esc(r.get('co')),esc(r.get('loc')),
                esc(fmt_when(r)),esc(r.get('why')),spon,fit))
    parts.append("</div>")
    return ''.join(parts)

def render_text(rows):
    out=[]
    for tier,label in ((1,'MAJOR SPONSORS'),(2,'OTHER COMPANIES')):
        grp=[r for r in rows if r.get('tier',2)==tier]
        if not grp: continue
        out.append("== %s -- %d new =="%(label,len(grp)))
        for r in grp:
            out.append("%s | %s | %s"%(r.get('title'),r.get('co'),r.get('loc')))
            out.append("   %s | %s%s"%(fmt_when(r),r.get('why'),
                                       ' | SPONSORS' if r.get('pos')=='YES' else ''))
            if r.get('resume'):
                out.append("   resume: %s  %s/5%s"%(r['resume'],r.get('fit'),
                           ('  |  add: '+'; '.join(r.get('add') or [])) if r.get('add') else ''))
            out.append("   %s"%r.get('url'))
        out.append('')
    return '\n'.join(out)

def main():
    rows=load(PASSED,[])
    if not isinstance(rows,list):
        sys.stderr.write("passed.json is not a list\n"); return 1
    seen=load(SEEN,{})
    if not isinstance(seen,dict): seen={}
    now=datetime.now(timezone.utc)
    new=[r for r in rows if key(r) not in seen]
    # majors first, then newest first, undated last -- same ordering as the
    # terminal report in scan_all.py
    def order(r):
        try: ts=datetime.fromisoformat(r['ts']).timestamp()
        except Exception: ts=0
        return (r.get('tier',2), r.get('datekind')=='undated', -ts)
    new.sort(key=order)
    sys.stderr.write("passed=%d  already seen=%d  new=%d\n"%(len(rows),len(rows)-len(new),len(new)))

    dry=(os.environ.get('DRY_RUN') or '').strip()=='1'
    if not new and (os.environ.get('ALWAYS_SEND') or '').strip()!='1':
        sys.stderr.write("nothing new -- no email sent\n")
        if not dry: save_seen(seen,rows,now)
        return 0

    if new:
        subject="jobscan: %d new role%s (%d major)"%(
            len(new),'' if len(new)==1 else 's',sum(1 for r in new if r.get('tier',2)==1))
    else:
        subject="jobscan: no new roles today"
    note=("%d role%s currently match in the scanned window; all of them were in "
          "an earlier email."%(len(rows),'' if len(rows)==1 else 's')) if rows else \
         "Nothing matched the filters in the scanned window."
    body_txt=render_text(new) or ("No new roles since the last email.\n%s\n"%note)
    body_html=render(new) or (
        "<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px'>"
        "<p>No new roles since the last email.</p>"
        "<p style='color:#777;font-size:12px'>%s</p></div>"%note)

    if dry:
        print("SUBJECT:",subject); print(); print(body_txt)
        sys.stderr.write("DRY_RUN=1 -- not sending, seen.json untouched\n")
        return 0

    # NB: an unset GitHub secret arrives as an EMPTY string, not as absent, so
    # every lookup must fall back on falsiness rather than on os.environ default.
    env=lambda k,d=None: (os.environ.get(k) or '').strip() or d
    user=env('SMTP_USER'); pw=env('SMTP_PASS')
    to=env('MAIL_TO') or user
    if not (user and pw and to):
        sys.stderr.write("ERROR missing SMTP_USER / SMTP_PASS / MAIL_TO -- cannot send\n")
        return 2
    msg=EmailMessage()
    msg['Subject']=subject; msg['From']=user; msg['To']=to
    msg.set_content(body_txt); msg.add_alternative(body_html,subtype='html')

    hostn=env('SMTP_HOST','smtp.gmail.com')
    try: port=int(env('SMTP_PORT','465'))
    except ValueError: port=465
    ctx=ssl.create_default_context()
    try:
        if port==587:
            with smtplib.SMTP(hostn,port,timeout=60) as s:
                s.starttls(context=ctx); s.login(user,pw); s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(hostn,port,context=ctx,timeout=60) as s:
                s.login(user,pw); s.send_message(msg)
    except Exception as e:
        sys.stderr.write("ERROR sending mail: %r\n"%(e,)); return 3
    sys.stderr.write("sent %d new role(s) to %s\n"%(len(new),to))
    save_seen(seen,rows,now)
    return 0

def save_seen(seen,rows,now):
    for r in rows: seen.setdefault(key(r),now.isoformat())
    cutoff=now-timedelta(days=KEEP_DAYS)
    kept={}
    for k,v in seen.items():
        try: t=datetime.fromisoformat(v)
        except Exception: t=now
        if t.tzinfo is None: t=t.replace(tzinfo=timezone.utc)
        if t>=cutoff: kept[k]=v
    with open(SEEN,'w') as f: json.dump(kept,f,indent=1,sort_keys=True)
    sys.stderr.write("seen.json: %d entries (pruned %d older than %dd)\n"%(
        len(kept),len(seen)-len(kept),KEEP_DAYS))

if __name__=='__main__': sys.exit(main())
