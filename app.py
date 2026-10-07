import os, re, json
from collections import defaultdict
from typing import Any
import requests
import streamlit as st
try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
except Exception:
    service_account = None
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

st.set_page_config(page_title='GTM Implementation Explorer', page_icon='🔎', layout='wide')
BASE='https://www.googleapis.com/tagmanager/v2'
SCOPE='https://www.googleapis.com/auth/tagmanager.readonly'

def flat(v):
    if isinstance(v,dict):
        return sum((flat(x) for x in v.values()),[])
    if isinstance(v,list): return sum((flat(x) for x in v),[])
    return [v] if isinstance(v,str) else []

def refs(v):
    out=[]
    for s in flat(v): out += re.findall(r'\{\{\s*([^{}]+?)\s*\}\}',s)
    return sorted(set(out))

def purpose(name, typ, kind):
    n=(name or '').lower(); t=(typ or '').lower()
    if kind=='Tag':
        if 'page' in n and 'view' in n: return 'Tracks page-view activity in the configured destination.'
        if 'form' in n and any(x in n for x in ['submit','complete','lead']): return 'Tracks a form completion or lead action for analytics/advertising measurement.'
        if any(x in n for x in ['click','cta','link']): return 'Tracks a user interaction such as a CTA, button, or link click.'
        if any(x in n for x in ['conversion','lead','purchase','transaction']): return 'Sends a conversion-related signal to the configured marketing or analytics platform.'
        if any(x in n for x in ['consent','onetrust']): return 'Supports consent-related behavior for downstream tracking.'
        return f'Executes the configured {typ} implementation when its firing conditions are met.'
    if kind=='Trigger':
        if 'custom event' in t or 'custom' in n: return 'Listens for an event signal and controls which tags are allowed to fire.'
        if 'click' in n or 'click' in t: return 'Controls tag firing based on user click behavior.'
        if 'page' in n or 'page' in t: return 'Controls tag firing based on page-load or page-location conditions.'
        return 'Defines the conditions under which one or more tags are allowed to fire.'
    if 'data layer' in t or 'dlv' in n: return 'Reads a value from the website dataLayer for use by tags or triggers.'
    if 'regex' in t: return 'Transforms or classifies an input using pattern-matching logic.'
    if 'lookup' in t: return 'Maps an input value to a configured output value.'
    if 'constant' in t: return 'Stores a reusable fixed value for use elsewhere in GTM.'
    if 'javascript' in t: return 'Calculates or returns a value using JavaScript logic.'
    return 'Provides a reusable value to tags, triggers, or other GTM components.'

def params(v):
    return [{'Key':str(p.get('key','')),'Type':str(p.get('type','')),'Value':str(p.get('value',''))} for p in (v or [])]

def conditions(x):
    rows=[]
    for k in ['filter','autoEventFilter','checkForUrl','waitForTags','selectorType']:
        v=x.get(k)
        if v:
            vals=v if isinstance(v,list) else [v]
            for a in vals: rows.append({'Condition':k,'Type':a.get('type','') if isinstance(a,dict) else '', 'Value':json.dumps(a,ensure_ascii=False) if isinstance(a,dict) else str(a)})
    return rows

class GTM:
    def __init__(self,token): self.token=token
    def get(self,path,params=None):
        r=requests.get(f'{BASE}/{path}',headers={'Authorization':f'Bearer {self.token}'},params=params or {},timeout=45)
        if not r.ok: raise RuntimeError(f'GTM API {r.status_code}: {r.text[:800]}')
        return r.json()
    def all(self,path,key):
        out=[]; tok=None
        while True:
            d=self.get(path,{'pageToken':tok} if tok else {})
            out += d.get(key,[]); tok=d.get('nextPageToken')
            if not tok:return out
    def accounts(self): return self.all('accounts','account')
    def containers(self,aid): return self.all(f'accounts/{aid}/containers','container')
    def live(self,aid,cid): return self.get(f'accounts/{aid}/containers/{cid}/versions/live')
    def workspaces(self,aid,cid): return self.all(f'accounts/{aid}/containers/{cid}/workspaces','workspace')
    def ws(self,aid,cid,wid):
        b=f'accounts/{aid}/containers/{cid}/workspaces/{wid}'
        return {'tags':self.all(f'{b}/tags','tag'),'triggers':self.all(f'{b}/triggers','trigger'),'variables':self.all(f'{b}/variables','variable')}

def token():
    if service_account and 'gcp_service_account' in st.secrets:
        c=service_account.Credentials.from_service_account_info(dict(st.secrets['gcp_service_account']),scopes=[SCOPE]); c.refresh(Request()); return c.token
    return st.secrets.get('GTM_ACCESS_TOKEN',os.getenv('GTM_ACCESS_TOKEN',''))

def model(tags,triggers,variables):
    tb={str(x.get('triggerId')):x for x in triggers}; vb={x.get('name'):x for x in variables}
    vu=defaultdict(list); vr={}
    for v in variables:
        vr[v.get('name','')]=refs(v)
        for r in vr[v.get('name','')]: vu[r].append(('Variable',v.get('name','')))
    for t in tags:
        for r in refs(t): vu[r].append(('Tag',t.get('name','')))
    for t in triggers:
        for r in refs(t): vu[r].append(('Trigger',t.get('name','')))
    tu=defaultdict(list)
    for t in tags:
        ids=(t.get('firingTriggerId',[]) or [])+(t.get('blockingTriggerId',[]) or [])
        t['_firing']=[tb[str(i)] for i in (t.get('firingTriggerId',[]) or []) if str(i) in tb]
        for i in ids:
            if str(i) in tb: tu[str(i)].append(t)
    return {'tb':tb,'vb':vb,'vu':vu,'vr':vr,'tu':tu}

def diff(live,ws):
    o={}
    for k in ['tags','triggers','variables']:
        a={x.get('name'):x for x in live[k]}; b={x.get('name'):x for x in ws[k]}
        o[k]={'added':sorted(set(b)-set(a)),'removed':sorted(set(a)-set(b)),'changed':sorted(n for n in set(a)&set(b) if json.dumps(a[n],sort_keys=True)!=json.dumps(b[n],sort_keys=True))}
    return o

def ai(q,ctx):
    if OpenAI is None: raise RuntimeError('Install the openai package.')
    key=st.secrets.get('OPENAI_API_KEY',os.getenv('OPENAI_API_KEY',''))
    if not key: raise RuntimeError('OPENAI_API_KEY is not configured.')
    client=OpenAI(api_key=key); mdl=st.secrets.get('OPENAI_MODEL',os.getenv('OPENAI_MODEL','gpt-6-luna'))
    text=json.dumps(ctx,ensure_ascii=False)
    if len(text)>120000:text=text[:120000]+'\n[context truncated]'
    r=client.responses.create(model=mdl,instructions='You are a senior GTM implementation analyst. Use only the supplied container context for factual claims. Explain business purpose and technical flow. Trace tag→trigger→variable→data source→parameter→destination. For impact questions name affected components. Label recommendations clearly. Never invent configuration.',input=f'GTM CONTEXT:\n{text}\n\nQUESTION:\n{q}')
    return r.output_text

def service_ok(): return service_account is not None and 'gcp_service_account' in st.secrets

st.title('🔎 GTM Implementation Explorer')
st.write('Read a GTM container as implementation documentation: what each tag does, when it fires, which variables it uses, where values come from, and what components are linked.')
with st.sidebar:
    st.header('Connection')
    cid_in=st.text_input('GTM Container ID',placeholder='GTM-XXXXXXX')
    st.caption('Read-only: the app does not publish or modify GTM.')
    if service_ok(): st.success('Google service-account credentials detected.')
    else: st.warning('Configure GTM_ACCESS_TOKEN or a Google service account in Streamlit secrets.')

if 'data' not in st.session_state: st.session_state.data=None
if st.button('Analyze Container',type='primary',disabled=not cid_in):
    try:
        tk=token()
        if not tk: st.error('No GTM credential found.'); st.stop()
        g=GTM(tk); target=cid_in.strip().upper(); found=None
        for a in g.accounts():
            aid=str(a.get('accountId'))
            for c in g.containers(aid):
                if str(c.get('publicId','')).upper()==target or str(c.get('containerId',''))==target.replace('GTM-',''):
                    found=(aid,c); break
            if found:break
        if not found: raise RuntimeError(f'Container {cid_in} was not found for this credential.')
        aid,c=found; cid=str(c['containerId']); live=g.live(aid,cid)
        items={'tags':live.get('tag',[]),'triggers':live.get('trigger',[]),'variables':live.get('variable',[])}
        m=model(items['tags'],items['triggers'],items['variables']); ws=g.workspaces(aid,cid)
        st.session_state.data={'g':g,'aid':aid,'cid':cid,'container':c,'live':live,'items':items,'m':m,'workspaces':ws}
        st.success('Container analyzed.')
    except Exception as e: st.error(str(e))

d=st.session_state.data
if d:
    live,items,m,ws=d['live'],d['items'],d['m'],d['workspaces']
    st.divider(); st.subheader(d['container'].get('name','GTM Container')); st.caption(f"{d['container'].get('publicId',cid_in)} · Live version {live.get('containerVersionId','unknown')}")
    st.markdown('## 1. Current implementation')
    st.write(f"The live container contains **{len(items['tags'])} tags**, **{len(items['triggers'])} triggers**, and **{len(items['variables'])} variables**.")
    a,b,c=st.columns(3); a.metric('Tags',len(items['tags'])); b.metric('Triggers',len(items['triggers'])); c.metric('Variables',len(items['variables']))
    tabs=st.tabs(['🏷️ Tags','⚡ Triggers','🔧 Variables','🧩 Workspaces','🤖 AI Assistant'])
    with tabs[0]:
        q=st.text_input('Search tags',key='ts'); arr=[x for x in items['tags'] if not q or q.lower() in x.get('name','').lower()]
        names=[x.get('name','Unnamed') for x in arr]
        if names:
            sel=st.selectbox('Select a tag',names); t=next(x for x in arr if x.get('name')==sel)
            st.markdown(f'## 🏷️ {t.get("name","Unnamed tag")}'); st.caption(f"Tag: {t.get('type','Unknown')}"); st.info(purpose(t.get('name',''),t.get('type',''),'Tag'))
            firing=[x.get('name','') for x in t.get('_firing',[])]; blocking=[m['tb'].get(str(i),{}).get('name',str(i)) for i in t.get('blockingTriggerId',[]) or []]
            st.markdown('### Linked triggers'); st.write('**Firing:**',', '.join(firing) if firing else 'None found'); st.write('**Blocking:**',', '.join(blocking) if blocking else 'None found')
            r=refs(t); st.markdown('### Variables referenced'); st.dataframe([{'Variable':x,'Known':x in m['vb'],'Purpose':purpose(x,m['vb'].get(x,{}).get('type',''),'Variable')} for x in r],use_container_width=True,hide_index=True) if r else st.write('No variable references detected.')
            st.markdown('### Parameters / configuration'); st.dataframe(params(t.get('parameter')),use_container_width=True,hide_index=True) if t.get('parameter') else st.write('No tag parameters exposed.')
            with st.expander('Raw GTM configuration'): st.code(json.dumps({k:v for k,v in t.items() if not k.startswith('_')},indent=2,ensure_ascii=False),'json')
    with tabs[1]:
        q=st.text_input('Search triggers',key='trs'); arr=[x for x in items['triggers'] if not q or q.lower() in x.get('name','').lower()]; names=[x.get('name','Unnamed') for x in arr]
        if names:
            sel=st.selectbox('Select a trigger',names); t=next(x for x in arr if x.get('name')==sel); st.markdown(f'## ⚡ {t.get("name","Unnamed trigger")}'); st.caption(f"Trigger: {t.get('type','Unknown')}"); st.info(purpose(t.get('name',''),t.get('type',''),'Trigger'))
            st.markdown('### Conditions / configuration'); rows=conditions(t); st.dataframe(rows,use_container_width=True,hide_index=True) if rows else st.code(json.dumps(t,indent=2,ensure_ascii=False),'json')
            r=refs(t); st.markdown('### Variables used by this trigger'); st.dataframe([{'Variable':x,'Purpose':purpose(x,m['vb'].get(x,{}).get('type',''),'Variable')} for x in r],use_container_width=True,hide_index=True) if r else st.write('No variable references detected.')
            linked=m['tu'].get(str(t.get('triggerId')),[]); st.markdown(f'### Tags linked to this trigger ({len(linked)})'); st.dataframe([{'Tag':x.get('name',''),'Type':x.get('type',''),'Purpose':purpose(x.get('name',''),x.get('type',''),'Tag')} for x in linked],use_container_width=True,hide_index=True) if linked else st.warning('No tags reference this trigger.')
            with st.expander('Raw trigger configuration'): st.code(json.dumps(t,indent=2,ensure_ascii=False),'json')
    with tabs[2]:
        q=st.text_input('Search variables',key='vs'); arr=[x for x in items['variables'] if not q or q.lower() in x.get('name','').lower()]; names=[x.get('name','Unnamed') for x in arr]
        if names:
            sel=st.selectbox('Select a variable',names); v=next(x for x in arr if x.get('name')==sel); name=v.get('name','Unnamed variable'); st.markdown(f'## 🔧 {name}'); st.caption(f"Variable: {v.get('type','Unknown')}"); st.info(purpose(name,v.get('type',''),'Variable'))
            deps=m['vr'].get(name,[]); st.markdown('### Variable dependencies'); st.dataframe([{'Variable':x,'Purpose':purpose(x,m['vb'].get(x,{}).get('type',''),'Variable')} for x in deps],use_container_width=True,hide_index=True) if deps else st.write('No variable-to-variable references detected.')
            users=m['vu'].get(name,[]); st.markdown(f'### Tags / triggers / variables using this variable ({len(users)})'); st.dataframe([{'Component type':k,'Component':n} for k,n in users],use_container_width=True,hide_index=True) if users else st.warning('No references detected.')
            st.markdown('### Configuration'); st.dataframe(params(v.get('parameter')),use_container_width=True,hide_index=True) if v.get('parameter') else st.write('No parameters exposed.')
            with st.expander('Raw variable configuration'): st.code(json.dumps(v,indent=2,ensure_ascii=False),'json')
    with tabs[3]:
        st.markdown('## Workspace changes'); st.write('Each workspace is compared with the current live implementation.')
        for w in ws:
            with st.expander(f"{w.get('name','Unnamed workspace')} · ID {w.get('workspaceId')}"):
                try:
                    wi=d['g'].ws(d['aid'],d['cid'],str(w['workspaceId'])); dd=diff(items,wi)
                    for k,label in [('tags','Tags'),('triggers','Triggers'),('variables','Variables')]:
                        x=dd[k]; st.markdown(f'**{label}:** Added {len(x["added"])} · Changed {len(x["changed"])} · Removed {len(x["removed"])}')
                        if x['added']: st.write('Added:',', '.join(x['added']))
                        if x['changed']: st.write('Changed:',', '.join(x['changed']))
                        if x['removed']: st.write('Removed:',', '.join(x['removed']))
                except Exception as e: st.warning(str(e))
    with tabs[4]:
        st.markdown('## Ask about this implementation')
        if 'chat' not in st.session_state: st.session_state.chat=[]
        for msg in st.session_state.chat:
            with st.chat_message(msg['role']): st.markdown(msg['content'])
        q=st.chat_input('e.g. What tags depend on CD - Sector and what happens if I change it?')
        if q:
            st.session_state.chat.append({'role':'user','content':q}); st.chat_message('user').markdown(q)
            with st.chat_message('assistant'):
                try:
                    ctx={'container':{'name':d['container'].get('name'),'publicId':d['container'].get('publicId'),'liveVersion':live.get('containerVersionId')},'tags':[{'name':x.get('name'),'type':x.get('type'),'triggers':[z.get('name') for z in x.get('_firing',[])],'variables':refs(x),'parameters':params(x.get('parameter'))} for x in items['tags']],'triggers':[{'name':x.get('name'),'type':x.get('type'),'variables':refs(x),'linkedTags':[z.get('name') for z in m['tu'].get(str(x.get('triggerId')),[])]} for x in items['triggers']],'variables':[{'name':x.get('name'),'type':x.get('type'),'dependencies':m['vr'].get(x.get('name'),[]),'usedBy':m['vu'].get(x.get('name'),[]),'parameters':params(x.get('parameter'))} for x in items['variables']],'workspaces':ws}
                    ans=ai(q,ctx); st.markdown(ans); st.session_state.chat.append({'role':'assistant','content':ans})
                except Exception as e: st.error(str(e))
else:
    st.info('Enter a GTM Container ID and click Analyze Container.')
