import json, os, pathlib, sys, time, urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

ROOT = pathlib.Path(__file__).resolve().parent
STATE = ROOT / 'state.json'
BASE = 'https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/'
PLATFORMS = ('hackerone', 'bugcrowd', 'intigriti', 'yeswehack')
EXTRA = ('immunefi', 'cantina_bounties', 'disclose', 'self_hosted', 'cantina_contests', 'code4rena_contests', 'sherlock_contests')

def fetch(url, data=None):
    request = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), headers={'User-Agent':'bounty-alert-monitor/1.0','Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)

def send(message):
    token = os.environ['TELEGRAM_BOT_TOKEN']
    try:
        result = fetch('https://api.telegram.org/bot' + token + '/sendMessage', {'chat_id':os.environ['TELEGRAM_CHAT_ID'],'text':message,'disable_web_page_preview':True})
        if not result.get('ok'): raise RuntimeError('Telegram rejected the message')
    except Exception:
        raise RuntimeError('Telegram delivery failed') from None

def key(platform, p):
    return str(p.get('url') or p.get('handle') or p.get('id') or '').strip().lower()

def canonical(value):
    try:
        p = urlsplit(value.strip().lower())
        if p.scheme not in ('http', 'https') or not p.netloc: return ''
        return urlunsplit(('https', p.netloc.removeprefix('www.'), p.path.rstrip('/'), '', ''))
    except (ValueError, AttributeError): return ''

def extra_programs(source):
    if source == 'immunefi':
        rows = fetch('https://immunefi.com/public-api/bounties.json')
        if not isinstance(rows, list) or not rows: raise ValueError('invalid feed')
        return [{'name':p.get('project'), 'url':'https://immunefi.com/bug-bounty/'+str(p['slug'])+'/', 'max_bounty':p.get('maxBounty'), 'launch_date':p.get('launchDate'), 'kind':'Public bug bounty'} for p in rows if isinstance(p,dict) and p.get('slug') and not p.get('inviteOnly') and not p.get('isPaused')]
    if source == 'disclose':
        rows = fetch('https://raw.githubusercontent.com/disclose/diodb/master/program-list.json')
        if not isinstance(rows,list) or not rows: raise ValueError('invalid feed')
        return [{'name':p.get('program_name'), 'url':p.get('policy_url'), 'offers_bounties':True, 'launch_date':p.get('launch_date'), 'kind':'Reported paid bounty; verify terms'} for p in rows if isinstance(p,dict) and str(p.get('offers_bounty','')).lower()=='yes' and p.get('policy_url_status') != 'dead' and canonical(p.get('policy_url',''))]
    if source == 'self_hosted':
        rows = fetch('https://raw.githubusercontent.com/ashikkunjumon/Self-Hosted-Bug-Bounty-Programs/main/programs.json')
        if not isinstance(rows,list) or not rows: raise ValueError('invalid feed')
        return [{'name':p.get('domain'), 'url':p.get('policy_url'), 'offers_bounties':True, 'source_first_seen':p.get('first_seen'), 'kind':'Self-hosted; directory reports monetary reward, verify terms'} for p in rows if isinstance(p,dict) and p.get('hosting')=='self_hosted' and p.get('status')=='active' and p.get('reward')=='monetary' and not p.get('policy_dead') and canonical(p.get('policy_url') or '')]
    if source == 'cantina_bounties':
        rows=fetch('https://cantina.xyz/api/v0/bounties')
        if not isinstance(rows,list) or not rows: raise ValueError('invalid feed')
        return [{'name':p.get('name'), 'url':p.get('url'), 'kind':'Public bug bounty', 'reward_text':str(p.get('totalRewardPot') or 'unknown')+' '+str(p.get('currencyCode') or ''), 'submission_fee':p.get('submissionFee'), 'launch_date':(p.get('timeframe') or {}).get('start')} for p in rows if isinstance(p,dict) and p.get('status')=='live' and canonical(p.get('url') or '')]
    if source == 'cantina_contests':
        rows=fetch('https://cantina.xyz/api/v0/competitions')
        if not isinstance(rows,list) or not rows: raise ValueError('invalid feed')
        return [{'name':p.get('name'), 'url':p.get('url'), 'kind':'Time-limited audit contest', 'reward_text':str(p.get('totalRewardPot') or 'unknown')+' '+str(p.get('currencyCode') or ''), 'launch_date':(p.get('timeframe') or {}).get('start'), 'end_date':(p.get('timeframe') or {}).get('end')} for p in rows if isinstance(p,dict) and p.get('status') in ('live','upcoming') and canonical(p.get('url') or '')]
    if source == 'code4rena_contests':
        raw=fetch('https://code4rena.com/api/v1/audits?perPage=100')
        rows=raw.get('data',{}).get('audits')
        if not isinstance(rows,list) or not rows: raise ValueError('invalid feed')
        return [{'name':p.get('title'), 'url':'https://code4rena.com/audits/'+p['slug'], 'kind':'Time-limited audit contest', 'reward_text':p.get('formattedAmount') or 'unknown', 'launch_date':p.get('startTime'), 'end_date':p.get('endTime')} for p in rows if isinstance(p,dict) and p.get('status') in ('Active','Upcoming') and p.get('slug')]
    if source == 'sherlock_contests':
        rows=[]; page=1
        while page:
            raw=fetch('https://audits.sherlock.xyz/api/contests?per_page=100&page='+str(page))
            if not isinstance(raw,dict) or not isinstance(raw.get('items'),list): raise ValueError('invalid feed')
            rows.extend(raw['items']); page=raw.get('next_page')
            if page and (not isinstance(page,int) or page>20): raise ValueError('unexpected pagination')
        if not rows: raise ValueError('empty feed')
        return [{'name':p.get('title'), 'url':'https://audits.sherlock.xyz/contests/'+str(p['id']), 'kind':'Time-limited audit contest', 'reward_text':str(p.get('rewards') or p.get('prize_pool') or 'unknown')+' '+str(p.get('token') or ''), 'launch_date':datetime.fromtimestamp(p['starts_at'],timezone.utc).isoformat() if isinstance(p.get('starts_at'),(int,float)) else None, 'end_date':datetime.fromtimestamp(p['ends_at'],timezone.utc).isoformat() if isinstance(p.get('ends_at'),(int,float)) else None} for p in rows if isinstance(p,dict) and p.get('status') in ('RUNNING','CREATED') and not p.get('private') and p.get('id')]
    raise ValueError('unknown feed')

def describe(platform, p):
    url = p.get('url') or ('https://yeswehack.com/programs/' + str(p.get('id','')) if platform == 'yeswehack' else '')
    if p.get('offers_bounties') is False: reward = 'Unpaid disclosure program'
    elif p.get('offers_bounties') is True: reward = 'Paid bounty; check program page for amounts'
    else:
        amount = p.get('max_payout', p.get('max_bounty'))
        if isinstance(amount,dict): reward = 'Maximum listed: ' + str(amount.get('value','?')) + ' ' + str(amount.get('currency',''))
        elif isinstance(amount,(int,float)) and amount > 0: reward = 'Maximum listed: ' + str(amount) + ' (currency: check program page)'
        elif amount == 0: reward = 'No monetary maximum listed; verify program terms'
        else: reward = 'Reward unknown; check program page'
    if p.get('reward_text'): reward = 'Listed prize pool: '+str(p['reward_text'])
    dates = ''
    if p.get('launch_date'): dates += '\nReported launch/start: '+str(p['launch_date'])
    if p.get('end_date'): dates += '\nReported end: '+str(p['end_date'])
    if p.get('source_first_seen'): dates += '\nDirectory first seen: '+str(p['source_first_seen'])+' (not launch date)'
    if p.get('submission_fee') and str(p['submission_fee']) not in ('0', '0.00'): dates += '\nListed submission fee: '+str(p['submission_fee'])+'; check terms'
    return f"Newly listed: {p.get('name') or 'Unknown'}\nSource: {platform}\nType: {p.get('kind') or 'Program; check terms'}\nFirst seen by monitor: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} (not necessarily launch date){dates}\n{reward}\n{url}\nConfirm availability, scope and terms on the official page."

def main():
    state = json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else {}
    failed = False
    for platform in PLATFORMS + EXTRA:
        try:
            programs = fetch(BASE + platform + '_data.json') if platform in PLATFORMS else extra_programs(platform)
            if not isinstance(programs,list) or (platform in PLATFORMS and not programs): raise ValueError('empty or invalid feed')
            current = {key(platform,p):p for p in programs if isinstance(p,dict) and key(platform,p)}
            if not current and platform in PLATFORMS: raise ValueError('no identifiable programs')
            if platform not in state:
                state[platform] = sorted(current)
                print(platform + ': baseline saved', flush=True)
            else:
                seen = set(state[platform])
                known_urls = {canonical(item) for values in state.values() if isinstance(values,list) for item in values if isinstance(item,str)}
                for k in sorted(set(current)-seen):
                    if not canonical(k) or canonical(k) not in known_urls:
                        send(describe(platform,current[k])); time.sleep(0.1)
                    seen.add(k)
                    if canonical(k): known_urls.add(canonical(k))
                    state[platform] = sorted(seen)
                    STATE.write_text(json.dumps(state,indent=2)+'\n',encoding='utf8')
                print(platform + ': checked', flush=True)
            STATE.write_text(json.dumps(state,indent=2)+'\n',encoding='utf8')
        except Exception as exc:
            print(platform + ': check failed: ' + type(exc).__name__,file=sys.stderr,flush=True)
            failed = True
    if failed: sys.exit(1)

if __name__ == '__main__': main()
