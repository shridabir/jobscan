#!/usr/bin/env python3
"""Refresh resumes/*.txt from the resume PDFs.

match.py reads the extracted text, not the PDFs, so CI needs no PDF library.
Run this locally whenever you update a resume:

    python3 extract_resumes.py                 # uses the paths below
    python3 extract_resumes.py SWE=/path/a.pdf DS=/path/b.pdf

Needs: pip install pypdf
"""
import os,re,sys,glob

HOME=os.path.expanduser('~')
# newest full-time variant of each family; internship resumes are excluded
# because the scanner filters internships out anyway
DEFAULTS={
 'SWE':'Downloads/ShrirangDabir_FullTime_Resume_SWE (4).pdf',
 'DS' :'Downloads/ShrirangDabir_FullTime_Resume_DS (3).pdf',
 'DE' :'Downloads/ShrirangDabir_FullTime_Resume_DE.pdf',
 'DS_Finance':'Downloads/ShrirangDabir_FullTime_Resume_DS_Finance.pdf',
}

def newest(pattern):
    hits=sorted(glob.glob(os.path.join(HOME,pattern)),key=os.path.getmtime,reverse=True)
    return hits[0] if hits else None

def main(argv):
    try:
        from pypdf import PdfReader
    except ImportError:
        print("pypdf missing -- pip install pypdf"); return 1
    src=dict(DEFAULTS)
    for a in argv:
        if '=' in a:
            k,v=a.split('=',1); src[k]=v
    os.makedirs('resumes',exist_ok=True)
    for tag,rel in sorted(src.items()):
        p=rel if os.path.isabs(rel) else os.path.join(HOME,rel)
        if not os.path.exists(p):
            # fall back to the newest file of that family
            p=newest('Downloads/*FullTime*%s*.pdf'%tag) or ''
        if not p or not os.path.exists(p):
            print("  MISSING  %-11s %s"%(tag,rel)); continue
        txt='\n'.join((pg.extract_text() or '') for pg in PdfReader(p).pages)
        txt=re.sub(r'[ \t]+',' ',txt)
        open(os.path.join('resumes','%s.txt'%tag),'w').write(txt)
        print("  wrote    %-11s %-52s %d chars"%(tag,os.path.basename(p),len(txt)))
    return 0

if __name__=='__main__': sys.exit(main(sys.argv[1:]))
