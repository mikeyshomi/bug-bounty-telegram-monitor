import json, os, pathlib, sys, time, urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
STATE = ROOT / 'state.json'
BASE = 'https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/'
PLATFORMS = ('hackerone', 'bugcrowd', 'intigriti', 'yeswehack')

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
    return f"Newly listed program: {p.get('name','Unknown')}\nPlatform: {platform}\nFirst seen: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} (not necessarily launch date)\n{reward}\n{url}"

def main():
    state = json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else {}
    failed = False
    for platform in PLATFORMS:
        try:
            programs = fetch(BASE + platform + '_data.json')
            if not isinstance(programs,list) or not programs: raise ValueError('empty or invalid feed')
            current = {key(platform,p):p for p in programs if isinstance(p,dict) and key(platform,p)}
            if not current: raise ValueError('no identifiable programs')
            if platform not in state:
                state[platform] = sorted(current)
                print(platform + ': baseline saved', flush=True)
            else:
                seen = set(state[platform])
                for k in sorted(set(current)-seen):
                    send(describe(platform,current[k])); seen.add(k)
                    state[platform] = sorted(seen)
                    STATE.write_text(json.dumps(state,indent=2)+'\n',encoding='utf8')
                    time.sleep(0.1)
                print(platform + ': checked', flush=True)
            STATE.write_text(json.dumps(state,indent=2)+'\n',encoding='utf8')
        except Exception as exc:
            print(platform + ': check failed: ' + type(exc).__name__,file=sys.stderr,flush=True)
            failed = True
    if failed: sys.exit(1)

if __name__ == '__main__': main()
