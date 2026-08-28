#!/usr/bin/env python3
"""Pick the best-tailored resume for a posting, score the fit, and say which
keywords are missing and which resume line they belong on.

Resume text lives in resumes/*.txt (extracted from the PDFs by extract_resumes.py).
Everything here is deterministic keyword matching -- no model calls -- so it runs
inside the scan with no extra dependency or cost.
"""
import re,os,glob

# canonical skill -> (regex alternatives, resume section it belongs on)
def S(*alts): return alts
SKILLS={
 # languages
 'Python':(S(r'python'),'Programming Languages'),
 'Java':(S(r'\bjava\b(?!script)'),'Programming Languages'),
 'JavaScript':(S(r'javascript','\\bjs\\b'),'Programming Languages'),
 'TypeScript':(S(r'typescript'),'Programming Languages'),
 'Go (Golang)':(S(r'\bgolang\b',r'\bgo\b(?=\s*(?:,|/|and|programming|lang))'),'Programming Languages'),
 'C++':(S(r'c\+\+'),'Programming Languages'),
 'C#':(S(r'c#','\\.net\\b'),'Programming Languages'),
 'Scala':(S(r'\bscala\b'),'Programming Languages'),
 'Rust':(S(r'\brust\b'),'Programming Languages'),
 'Ruby':(S(r'\bruby\b'),'Programming Languages'),
 'Kotlin':(S(r'\bkotlin\b'),'Programming Languages'),
 'Swift':(S(r'\bswift\b'),'Programming Languages'),
 'R':(S(r'(?<![A-Za-z])R(?=\s*(?:,|/|\)|and\b))'),'Programming Languages'),
 'SQL':(S(r'\bsql\b'),'Programming Languages'),
 'Bash/Shell':(S(r'\bbash\b',r'shell scripting',r'\bshell\b'),'Programming Languages'),
 # web / frontend
 'React':(S(r'\breact(?:\.js)?\b'),'Software Engineering Practices'),
 'Node.js':(S(r'node\.?js'),'Software Engineering Practices'),
 'REST APIs':(S(r'\brest(?:ful)?\b',r'\bapis?\b'),'Software Engineering Practices'),
 'GraphQL':(S(r'graphql'),'Software Engineering Practices'),
 'gRPC':(S(r'\bgrpc\b'),'Systems & Distributed Computing'),
 # data / distributed
 'Apache Spark':(S(r'\bspark\b'),'Distributed Systems & Data Pipelines'),
 'Kafka':(S(r'\bkafka\b'),'Distributed Systems & Data Pipelines'),
 'Hadoop':(S(r'\bhadoop\b'),'Distributed Systems & Data Pipelines'),
 'Airflow':(S(r'\bairflow\b'),'Distributed Systems & Data Pipelines'),
 'dbt':(S(r'\bdbt\b'),'Distributed Systems & Data Pipelines'),
 'Flink':(S(r'\bflink\b'),'Distributed Systems & Data Pipelines'),
 'ETL/ELT':(S(r'\betl\b',r'\belt\b',r'data pipelines?'),'Distributed Systems & Data Pipelines'),
 'Data Modeling':(S(r'data model'),'Distributed Systems & Data Pipelines'),
 'Data Warehousing':(S(r'data warehous',r'\bsnowflake\b',r'\bredshift\b',r'\bbigquery\b'),'Databases & Storage'),
 'Streaming':(S(r'stream processing',r'real[- ]time data'),'Distributed Systems & Data Pipelines'),
 # databases
 'PostgreSQL':(S(r'postgres'),'Databases & Storage'),
 'MySQL':(S(r'\bmysql\b'),'Databases & Storage'),
 'MongoDB':(S(r'mongo'),'Databases & Storage'),
 'Cassandra':(S(r'cassandra'),'Databases & Storage'),
 'Redis':(S(r'\bredis\b'),'Databases & Storage'),
 'DynamoDB':(S(r'dynamodb'),'Databases & Storage'),
 'Elasticsearch':(S(r'elasticsearch',r'\bopensearch\b'),'Databases & Storage'),
 # cloud / infra
 'AWS':(S(r'\baws\b',r'amazon web services'),'Cloud / DevOps / MLOps'),
 'GCP':(S(r'\bgcp\b',r'google cloud'),'Cloud / DevOps / MLOps'),
 'Azure':(S(r'\bazure\b'),'Cloud / DevOps / MLOps'),
 'Kubernetes':(S(r'kubernetes',r'\bk8s\b'),'Cloud / DevOps / MLOps'),
 'Docker':(S(r'docker',r'containeriz'),'Cloud / DevOps / MLOps'),
 'Terraform':(S(r'terraform'),'Cloud / DevOps / MLOps'),
 'CI/CD':(S(r'ci/cd',r'continuous integration',r'jenkins',r'github actions'),'Software Engineering Practices'),
 'Microservices':(S(r'microservice'),'Software Engineering Practices'),
 'Distributed Systems':(S(r'distributed system'),'Systems & Distributed Computing'),
 'Linux/Unix':(S(r'\blinux\b',r'\bunix\b'),'Cloud / DevOps / MLOps'),
 'Observability':(S(r'observability',r'prometheus',r'grafana',r'datadog',r'monitoring'),'Software Engineering Practices'),
 'Multithreading':(S(r'multithread',r'concurren'),'Systems & Distributed Computing'),
 # ML / DS
 'PyTorch':(S(r'pytorch'),'Programming Languages'),
 'TensorFlow':(S(r'tensorflow'),'Programming Languages'),
 'Scikit-learn':(S(r'scikit',r'sklearn'),'Programming Languages'),
 'Pandas':(S(r'\bpandas\b'),'Programming Languages'),
 'NumPy':(S(r'\bnumpy\b'),'Programming Languages'),
 'Machine Learning':(S(r'machine learning',r'\bml\b'),'Statistics & Experimentation'),
 'Deep Learning':(S(r'deep learning',r'neural network'),'Statistics & Experimentation'),
 'NLP':(S(r'\bnlp\b',r'natural language'),'LLMs & Agentic AI Frameworks'),
 'Computer Vision':(S(r'computer vision'),'Statistics & Experimentation'),
 'Recommender Systems':(S(r'recommend(?:er|ation)',r'\branking\b'),'Statistics & Experimentation'),
 'A/B Testing':(S(r'a/b test',r'experimentation'),'Statistics & Experimentation'),
 'Causal Inference':(S(r'causal infer'),'Statistics & Experimentation'),
 'Statistics':(S(r'statistic',r'hypothesis test'),'Statistics & Experimentation'),
 'MLOps':(S(r'mlops',r'model deployment',r'model serving'),'Cloud / DevOps / MLOps'),
 'MLFlow':(S(r'mlflow'),'Cloud / DevOps / MLOps'),
 'LLMs':(S(r'\bllms?\b',r'large language model',r'generative ai',r'\bgenai\b'),'LLMs & Agentic AI Frameworks'),
 'RAG Architecture':(S(r'\brag\b',r'retrieval augmented'),'LLMs & Agentic AI Frameworks'),
 'LangChain':(S(r'langchain',r'langgraph'),'LLMs & Agentic AI Frameworks'),
 'Prompt Engineering':(S(r'prompt engineering'),'LLMs & Agentic AI Frameworks'),
 'Feature Engineering':(S(r'feature engineering',r'feature store'),'Statistics & Experimentation'),
 # BI
 'Tableau':(S(r'tableau'),'Data Visualization & BI'),
 'Power BI':(S(r'power ?bi'),'Data Visualization & BI'),
 'Data Visualization':(S(r'data visuali[sz]'),'Data Visualization & BI'),
}
_COMPILED={k:(re.compile('|'.join(a),re.I),cat) for k,(a,cat) in SKILLS.items()}

# which resume family a posting leans toward, by title
FAMILY=[('DE',re.compile(r'\bdata engineer|\betl\b|data platform|data pipeline|analytics engineer',re.I)),
        ('DS',re.compile(r'data scien|\bstatistic|quantitative|research scientist|applied scientist|experimentation',re.I)),
        ('ML',re.compile(r'machine learning|\bml\b|\bmle\b|deep learning|\bai\b|nlp|computer vision|recommend',re.I)),
        ('SWE',re.compile(r'.',re.I))]

def load_resumes(d='resumes'):
    out={}
    for p in sorted(glob.glob(os.path.join(d,'*.txt'))):
        tag=os.path.splitext(os.path.basename(p))[0]
        try: out[tag]=open(p,encoding='utf-8',errors='replace').read()
        except Exception: pass
    return out

def skills_in(text):
    t=text or ''
    return {k for k,(rx,_) in _COMPILED.items() if rx.search(t)}

def family_of(title):
    for tag,rx in FAMILY:
        if rx.search(title or ''): return tag
    return 'SWE'

# map a family to the resume files that serve it, best first
PREF={'SWE':['SWE','DE','DS'],'ML':['DS','SWE','DE'],
      'DS':['DS','DS_Finance','SWE'],'DE':['DE','SWE','DS']}

def skill_headers(tag,resumes):
    """Section headers inside the SKILLS block only -- otherwise the fallback
    happily suggests putting Kubernetes on the 'Awards & Honors' line."""
    txt=resumes.get(tag,'')
    m=re.search(r'\bSKILLS\b(.*?)(?:\n[A-Z][A-Z &]{4,}\n|$)',txt,re.S)
    block=m.group(1) if m else txt
    return re.findall(r'^([A-Z][A-Za-z &/]{3,44}):',block,re.M)

# when a resume has no line of that exact kind, these are the next best homes
ALT={'Databases & Storage':['Distributed Systems & Data Pipelines','Distributed Systems & Cloud',
                           'Systems & Distributed Computing'],
     'Distributed Systems & Data Pipelines':['Distributed Systems & Cloud','Systems & Distributed Computing',
                           'Cloud / DevOps / MLOps'],
     'Systems & Distributed Computing':['Distributed Systems & Cloud','Distributed Systems & Data Pipelines'],
     'Cloud / DevOps / MLOps':['Distributed Systems & Cloud','Distributed Systems & Data Pipelines'],
     'Software Engineering Practices':['Cloud / DevOps / MLOps','Distributed Systems & Cloud'],
     'Statistics & Experimentation':['Analytics & Visualization','Data Visualization & BI'],
     'Data Visualization & BI':['Analytics & Visualization','Statistics & Experimentation'],
     'LLMs & Agentic AI Frameworks':['AI & Agentic Tools'],
     'AI & Agentic Tools':['LLMs & Agentic AI Frameworks']}

def resume_line(tag,resumes,category):
    """The actual skills line in that resume where the keyword belongs."""
    heads=skill_headers(tag,resumes)
    if not heads: return 'Skills'
    if category in heads: return category
    for a in ALT.get(category,[]):
        if a in heads: return a
    words={w for w in category.lower().replace('/',' ').split() if len(w)>2}
    best,score=None,0
    for h in heads:
        s=len(words&{w for w in h.lower().replace('/',' ').split() if len(w)>2})
        if s>score: best,score=h,s
    # no sensible home on this resume -- say so rather than invent a line
    return best

def evaluate(title,text,resumes,fin_hint=False):
    """-> (resume_tag, score_1_to_5, [ 'Keyword -> Section line' ... ])"""
    if not resumes: return None,None,[]
    jd=skills_in(text)
    if not jd: return None,None,[]
    fam=family_of(title)
    order=[t for t in PREF.get(fam,['SWE']) if t in resumes] or sorted(resumes)
    # DS_Finance is a niche variant: only consider it for finance-flavoured DS/ML
    if not (fin_hint and fam in ('DS','ML')): order=[t for t in order if t!='DS_Finance']
    elif 'DS_Finance' in resumes: order=['DS_Finance']+[t for t in order if t!='DS_Finance']
    # weight each posting skill by how often it is mentioned, so a C++-centric
    # role is scored on C++ rather than on incidental keywords
    low=(text or '').lower()
    wt={k:1+min(4,len(_COMPILED[k][0].findall(low))) for k in jd}
    total=float(sum(wt.values())) or 1.0
    # the family decides the resume; coverage only breaks ties within it
    scored=[]
    for rank,tag in enumerate(order):
        have=skills_in(resumes[tag])
        cov=sum(w for k,w in wt.items() if k in have)/total
        scored.append((round(cov,3)-rank*0.02,cov,tag))
    scored.sort(reverse=True)
    _,cov,best=scored[0]
    have=skills_in(resumes[best])
    # rank missing skills by how prominent they are in the posting
    miss=[]
    low=(text or '').lower()
    for k in (jd-have):
        rx=_COMPILED[k][0]
        miss.append((len(rx.findall(low)),k))
    miss.sort(reverse=True)
    tips=[]
    for _,k in miss[:4]:
        line=resume_line(best,resumes,_COMPILED[k][1])
        tips.append("%s -> %s line"%(k,line) if line else "%s (no matching line yet)"%k)
    # coverage -> 1..5
    score=5 if cov>=.80 else 4 if cov>=.65 else 3 if cov>=.50 else 2 if cov>=.35 else 1
    return best,score,tips
