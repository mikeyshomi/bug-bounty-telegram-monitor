import hashlib, html, json, os, pathlib, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
STATE = ROOT / 'jobs_state.json'
MAX_INITIAL = 5
INTERVALS = {'himalayas': 86400, 'jobicy': 3600, 'remotive': 21600}
ROLE = re.compile(r'\b(help[ -]?desk|service desk|desktop support|it support|technical support|it technician|it analyst|it intern|soc analyst|security analyst|cybersecurity analyst|cyber security analyst|security operations analyst|security support|information security analyst|incident response analyst|cybersecurity intern|cyber security intern|information security intern|security operations intern|cybersecurity specialist|cybersecurity technician|security engineer)\b', re.I)
TOO_SENIOR = re.compile(r'\b(senior|sr\.?|staff|principal|lead|manager|director|head of|architect|chief|tier[ -]?(?:iii|3)|level[ -]?(?:iii|3))\b', re.I)
BLOCKER = re.compile(r'\b(?:must|require[ds]?|minimum(?: of)?|at least)\s+(?:have\s+)?(?:a\s+)?(?:minimum(?: of)?\s+)?(?:[4-9]|\d{2,})\s*\+?\s*years?\b|\b(?:[4-9]|\d{2,})\s*\+\s*years?\b', re.I)
OTHER_LANGUAGE = re.compile(r'\b(?:german|french|spanish|portuguese|dutch|italian|mandarin|japanese|korean|arabic|polish)\b', re.I)
REGION_TITLE = re.compile(r'\b(?:europe(?:an)?|united states|u\.?s\.?a\.?|united kingdom|u\.?k\.?|canada|australia|apac|latam)\b',re.I)
LANG_REQUIREMENT = re.compile(r'\b(?:fluent|fluency|native|proficien(?:cy|t)|required|must speak|bilingual)\b.{0,35}\b(?:german|french|spanish|portuguese|dutch|italian|mandarin|japanese|korean|arabic|polish)\b|\b(?:german|french|spanish|portuguese|dutch|italian|mandarin|japanese|korean|arabic|polish)\b.{0,25}\b(?:required|fluency|fluent|proficiency|native)\b',re.I)
SKILLS = ('windows', 'linux', 'network', 'python', 'microsoft 365', 'burp suite', 'wireshark', 'splunk', 'nmap', 'troubleshoot', 'phishing', 'security', 'documentation')

def fetch(url, payload=None):
    req=urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers={'User-Agent':'Remote-job-alert-monitor/1.0', 'Accept':'application/json', 'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=45) as response: return json.load(response)

def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', str(value or '')))).strip()

def identity(company,title):
    key=re.sub(r'[^a-z0-9]+',' ',(company+' '+title).lower()).strip()
    return hashlib.sha256(key.encode()).hexdigest()

def valid_role(title, seniority, text):
    region_only = REGION_TITLE.search(title) and not re.search(r'\b(?:hours?|time\s*zones?|shifts?)\b', title, re.I)
    return bool(ROLE.search(title)) and not TOO_SENIOR.search(title+' '+seniority) and not BLOCKER.search(text) and not OTHER_LANGUAGE.search(title) and not region_only and not LANG_REQUIREMENT.search(text)

def nigeria(job):
    loc=job.get('locationRestrictions',[])
    names=[str(x.get('name') or x.get('alpha2') or '') if isinstance(x,dict) else str(x) for x in loc]
    if names and not any(x.lower() in ('nigeria','ng') for x in names): return False
    return True

def make(source,title,company,url,text,location,date,seniority='',salary='',guid='',employment=''):
    title,company,text,seniority=map(plain,(title,company,text,seniority))
    if not title or not company or not url or not valid_role(title,seniority,text): return None
    matched=[s for s in SKILLS if s in text.lower()][:5]
    return {'id':identity(company,title),'source':source,'title':title,'company':company,'url':url,'location':location,'date':str(date or 'Not provided'),'seniority':seniority or 'Not specified','salary':plain(salary) or 'Not stated','skills':matched,'guid':guid,'employment':plain(employment) or 'Not specified'}

def candidates(source):
    out=[]
    if source=='himalayas':
        # The data is cached for 24h. Limit each focused query to recent results.
        for query in ('it support','help desk','technical support','security analyst','soc analyst','cybersecurity intern','information security intern'):
            for page in (1,2,3):
                q=urllib.parse.urlencode({'q':query,'country':'NG','sort':'recent','page':page})
                data=fetch('https://himalayas.app/jobs/api/search?'+q)
                if not isinstance(data.get('jobs'),list): raise ValueError('invalid Himalayas response')
                for j in data['jobs']:
                    if not nigeria(j): continue
                    levels=j.get('seniority') or []
                    if any(re.search(r'mid|senior|manager|director|executive',str(x),re.I) for x in levels) and not any('entry' in str(x).lower() for x in levels): continue
                    date=datetime.fromtimestamp(j['pubDate'],timezone.utc).isoformat() if isinstance(j.get('pubDate'),(int,float)) else ''
                    salary=' '.join(str(x) for x in (j.get('currency'), j.get('minSalary'), j.get('maxSalary'),j.get('salaryPeriod')) if x is not None) if j.get('minSalary') is not None or j.get('maxSalary') is not None else ''
                    item=make(source,j.get('title'),j.get('companyName'),j.get('applicationLink'),j.get('description'), 'Nigeria eligible in board data; verify employer restrictions',date,', '.join(levels),salary,j.get('guid',''),j.get('employmentType',''))
                    if item: out.append(item)
                if len(data['jobs'])<20: break
    elif source=='jobicy':
        for tag in ('support','security'):
            cursor=None
            for _ in range(5):
                args={'count':200,'tag':tag}
                if cursor: args['cursor']=cursor
                data=fetch('https://jobicy.com/api/jobs?'+urllib.parse.urlencode(args))
                if not isinstance(data.get('jobs'),list) or data.get('success') is False: raise ValueError('invalid Jobicy response')
                for j in data['jobs']:
                    loc=plain(j.get('jobGeo')).lower()
                    if not any(t in loc for t in ('nigeria','anywhere','worldwide','global','africa')): continue
                    item=make(source,j.get('jobTitle'),j.get('companyName'),j.get('url'),j.get('jobDescription'), 'Nigeria eligibility unverified; board location: '+loc,j.get('pubDate'),j.get('jobLevel'), ' '.join(str(j.get(k) or '') for k in ('salaryCurrency','salaryMin','salaryMax','salaryPeriod')),str(j.get('id','')),', '.join(j.get('jobType') or []))
                    if item: out.append(item)
                cursor=data.get('nextCursor')
                if not cursor: break
    elif source=='remotive':
        data=fetch('https://remotive.com/api/remote-jobs')
        if not isinstance(data.get('jobs'),list): raise ValueError('invalid Remotive response')
        for j in data['jobs']:
            loc=plain(j.get('candidate_required_location')).lower()
            if not any(t in loc for t in ('nigeria','worldwide','anywhere','global','africa')): continue
            item=make(source,j.get('title'),j.get('company_name'),j.get('url'),j.get('description'),'Board location: '+loc+'; verify Nigeria eligibility',j.get('publication_date'),'',j.get('salary'),'',j.get('job_type',''))
            if item: out.append(item)
    return out

def recent(date):
    try:
        d=datetime.fromisoformat(date.replace('Z','+00:00'))
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc)-d).total_seconds() <= 7*86400
    except (ValueError,TypeError): return False

def verify(j):
    if j['source']=='himalayas':
        p=urllib.parse.urlsplit(j['guid'])
        if p.netloc!='himalayas.app' or not p.path.startswith('/companies/'): return 'Board listing status unverified'
        try:
            detail=fetch('https://himalayas.app/jobs/api'+p.path)
            return 'Open according to Himalayas' if isinstance(detail.get('job'),dict) else 'Board listing status unverified'
        except urllib.error.HTTPError as e:
            return 'closed' if e.code == 410 else 'Board listing status unverified'
        except Exception: return 'Board listing status unverified'
    if j['source']=='jobicy' and j['guid']:
        try:
            detail=fetch('https://jobicy.com/api/jobs/status?ids='+urllib.parse.quote(j['guid']))
            status=detail['jobs'][0]['status']
            return 'Open according to Jobicy' if status=='active' else ('closed' if status=='closed' else 'Board listing status unverified')
        except Exception: return 'Board listing status unverified'
    return 'Listed by Remotive; employer status unverified'

def send(message):
    try:
        token=os.environ['TELEGRAM_BOT_TOKEN']
        result=fetch('https://api.telegram.org/bot'+token+'/sendMessage',{'chat_id':os.environ['TELEGRAM_CHAT_ID'],'text':message,'disable_web_page_preview':True})
        if not result.get('ok'): raise RuntimeError()
    except Exception: raise RuntimeError('Telegram delivery failed') from None

def message(j,status):
    label='Last updated' if j['source']=='himalayas' else 'Published'
    fit=', '.join(j['skills']) if j['skills'] else 'Role title matches your target; review skills and requirements'
    return f"Remote job lead: {j['title']} — {j['company']}\n{j['location']}\nEmployment: {j['employment']}\nLevel: {j['seniority']}\n{label}: {j['date']}\nSalary: {j['salary']}\nPotential skill overlap: {fit}\n{status}; eligibility and fit need your review.\nSource: {j['source'].title()}\n{j['url']}"

def save(state): STATE.write_text(json.dumps(state,indent=2)+'\n',encoding='utf8')

def main():
    state=json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else {'seen':[],'checked':{},'initialized':False}
    seen=set(state['seen']); first=not state['initialized']; sent=0; failures=[]
    for source,interval in INTERVALS.items():
        now=int(time.time())
        if now-state['checked'].get(source,0)<interval: continue
        try:
            found=candidates(source)
            state['checked'][source]=now; save(state)
            for j in found:
                if j['id'] in seen or not recent(j['date']): continue
                if sent>=MAX_INITIAL: continue
                status=verify(j)
                if status=='closed': continue
                send(message(j,status)); sent+=1; seen.add(j['id']); state['seen']=sorted(seen); save(state)
            print(source+': checked',flush=True)
        except Exception as e:
            print(source+': failed: '+type(e).__name__,file=sys.stderr,flush=True); failures.append(source)
    if not failures: state['initialized']=True
    save(state)
    if failures: sys.exit(1)

if __name__=='__main__': main()
