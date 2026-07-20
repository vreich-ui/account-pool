"""The ADHD-friendly admin dashboard — a self-contained page served by the admin app.

Design intent (calm, low cognitive load, one thing at a time):
* ONE focal point — "Needs you now" (the approval queue) is the hero; everything else is quiet and
  collapsed behind native <details> (progressive disclosure).
* Reassurance over alarm — a persistent "Safe mode" banner when dry-run is on; attention shown in
  soft amber, never a wall of red. Every action is low-stakes and clearly labelled.
* Orientation at a glance — a small stat strip so you always know the state without hunting.
* Frictionless — big buttons, keyboard shortcuts (j/k move, a approve, c changes, r refresh),
  gentle relative times ("3m ago", "expires in 6h").

The same markup runs in two modes: served (fetches the live JSON API) or preview (reads embedded
sample data from ``window.__ACCOUNT_POOL_BOOTSTRAP__``), so it can be demoed with no backend.
"""

from __future__ import annotations

import json

STYLE = """
:root{
  --bg:#f6f7fb; --surface:#ffffff; --surface-2:#f0f2f8; --border:#e5e8f0;
  --text:#1e2233; --muted:#6b7180; --faint:#9aa0b0;
  --accent:#5b6cff; --accent-ink:#ffffff; --accent-soft:#eceeffe0;
  --ok:#1f9d78; --ok-soft:#e6f6f0; --attn:#b8791f; --attn-soft:#fbf1df;
  --radius:16px; --radius-sm:10px; --shadow:0 1px 2px rgba(24,28,45,.05),0 8px 24px rgba(24,28,45,.06);
  --maxw:760px;
}
:root[data-theme="dark"], :root:not([data-theme="light"]) {}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0e1017; --surface:#171a24; --surface-2:#1f2330; --border:#2a2f3d;
    --text:#e7e9f0; --muted:#9aa0b3; --faint:#6b7286;
    --accent:#8b97ff; --accent-ink:#0e1017; --accent-soft:#20263d;
    --ok:#4fd1a5; --ok-soft:#132a24; --attn:#e0a94a; --attn-soft:#2c2415;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px rgba(0,0,0,.35);
  }
}
:root[data-theme="dark"]{
  --bg:#0e1017; --surface:#171a24; --surface-2:#1f2330; --border:#2a2f3d;
  --text:#e7e9f0; --muted:#9aa0b3; --faint:#6b7286;
  --accent:#8b97ff; --accent-ink:#0e1017; --accent-soft:#20263d;
  --ok:#4fd1a5; --ok-soft:#132a24; --attn:#e0a94a; --attn-soft:#2c2415;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
html,body{margin:0}
body{
  background:var(--bg); color:var(--text);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased; padding:0 16px 96px;
}
.wrap{max-width:var(--maxw); margin:0 auto}
a{color:var(--accent)}
.header{display:flex; align-items:center; gap:12px; padding:22px 2px 6px}
.brand{display:flex; align-items:center; gap:10px; font-weight:680; letter-spacing:-.01em}
.dot{width:22px;height:22px;border-radius:8px;background:linear-gradient(140deg,var(--accent),#9b6bff);
  box-shadow:0 3px 10px rgba(91,108,255,.35)}
.header .spacer{flex:1}
.ghost{appearance:none;border:1px solid var(--border);background:var(--surface);color:var(--muted);
  border-radius:999px;padding:7px 12px;font-size:13px;cursor:pointer}
.ghost:hover{color:var(--text)}
.banner{display:flex;gap:10px;align-items:center;border-radius:var(--radius);padding:12px 16px;margin:10px 2px;
  background:var(--ok-soft);border:1px solid transparent;color:var(--ok);font-weight:560;font-size:14px}
.banner.live{background:var(--attn-soft);color:var(--attn)}
.banner .em{font-size:18px}
.strip{display:flex;gap:10px;margin:12px 2px 20px;flex-wrap:wrap}
.stat{flex:1;min-width:120px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:12px 14px;box-shadow:var(--shadow)}
.stat .n{font-size:26px;font-weight:720;letter-spacing:-.02em}
.stat .l{font-size:12.5px;color:var(--muted);margin-top:1px}
.stat.hot .n{color:var(--accent)}
h2.section{font-size:15px;letter-spacing:.02em;color:var(--muted);text-transform:uppercase;
  font-weight:640;margin:26px 2px 12px}
.focus-h{display:flex;align-items:baseline;gap:10px;margin:8px 2px 14px}
.focus-h h1{font-size:23px;font-weight:720;letter-spacing:-.02em;margin:0}
.pill{background:var(--accent);color:var(--accent-ink);border-radius:999px;font-size:13px;font-weight:700;
  padding:2px 10px;min-width:24px;text-align:center}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:16px 16px 14px;margin:12px 0;transition:border-color .15s,transform .05s}
.card.sel{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft),var(--shadow)}
.card .top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.chip{font-size:12px;font-weight:640;border-radius:999px;padding:3px 9px;background:var(--surface-2);
  color:var(--muted);border:1px solid var(--border)}
.chip.verb{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.who{font-weight:640}
.top .when{margin-left:auto;color:var(--faint);font-size:12.5px;white-space:nowrap}
.target{color:var(--muted);font-size:13.5px;margin:2px 0 8px;word-break:break-word}
.draft{background:var(--surface-2);border-radius:var(--radius-sm);padding:11px 13px;margin:6px 0 12px;
  font-size:14.5px;white-space:pre-wrap;word-break:break-word}
.draft .t{font-weight:640;margin-bottom:3px}
.expiry{font-size:12.5px;color:var(--attn);margin:0 0 10px}
.actions{display:flex;gap:10px;flex-wrap:wrap}
.btn{appearance:none;border:0;border-radius:12px;padding:11px 16px;font-size:14.5px;font-weight:660;
  cursor:pointer;flex:1;min-width:130px}
.btn.primary{background:var(--accent);color:var(--accent-ink)}
.btn.primary:hover{filter:brightness(1.05)}
.btn.soft{background:var(--surface-2);color:var(--text);border:1px solid var(--border)}
.btn:focus-visible,.ghost:focus-visible,.card:focus-visible{outline:3px solid var(--accent-soft);outline-offset:2px}
.reason{width:100%;margin-top:10px;border:1px solid var(--border);border-radius:10px;padding:10px 12px;
  background:var(--surface);color:var(--text);font:inherit;font-size:14px;resize:vertical;min-height:44px;display:none}
.reason.show{display:block}
.empty{text-align:center;padding:40px 16px;background:var(--surface);border:1px dashed var(--border);
  border-radius:var(--radius);color:var(--muted)}
.empty .big{font-size:30px;margin-bottom:6px}
details{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  margin:10px 0;overflow:hidden;box-shadow:var(--shadow)}
summary{cursor:pointer;padding:14px 16px;font-weight:620;list-style:none;display:flex;align-items:center;gap:8px}
summary::-webkit-details-marker{display:none}
summary .count{margin-left:auto;color:var(--faint);font-weight:560;font-size:13px}
details .body{padding:2px 16px 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.tile{border:1px solid var(--border);border-radius:12px;padding:11px 12px;background:var(--surface)}
.tile .pf{font-weight:620;text-transform:capitalize}
.tile .meta{font-size:12px;color:var(--muted);margin-top:3px}
.tier{display:inline-block;font-size:11px;font-weight:700;border-radius:999px;padding:2px 8px;margin-top:7px}
.tier.live{background:var(--ok-soft);color:var(--ok)}
.tier.draft_only{background:var(--accent-soft);color:var(--accent)}
.tier.manual{background:var(--attn-soft);color:var(--attn)}
.tier.planned{background:var(--surface-2);color:var(--faint)}
.sdot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:7px;vertical-align:middle}
.sdot.active{background:var(--ok)} .sdot.connected{background:var(--accent)}
.sdot.draft{background:var(--faint)} .sdot.suspended{background:var(--attn)} .sdot.retired{background:var(--faint)}
.acct{display:flex;align-items:center;gap:8px;padding:8px 2px;border-bottom:1px solid var(--border);font-size:14px}
.acct:last-child{border-bottom:0}
.acct .h{font-weight:580} .acct .p{color:var(--muted);font-size:12.5px;text-transform:capitalize}
.acct .st{margin-left:auto;color:var(--muted);font-size:12.5px}
.log{font-size:13px;color:var(--muted);padding:7px 2px;border-bottom:1px solid var(--border);display:flex;gap:8px}
.log:last-child{border-bottom:0}
.log .o{font-weight:680}
.log .o.allow{color:var(--ok)} .log .o.deny{color:var(--attn)} .log .o.route_to_approval{color:var(--accent)}
.log .tm{margin-left:auto;color:var(--faint);white-space:nowrap}
.foot{text-align:center;color:var(--faint);font-size:12.5px;margin:26px 2px 0}
.kbd{font-family:ui-monospace,monospace;background:var(--surface-2);border:1px solid var(--border);
  border-radius:6px;padding:1px 6px;font-size:12px;color:var(--muted)}
.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--text);color:var(--bg);
  padding:10px 18px;border-radius:999px;font-size:14px;font-weight:560;opacity:0;pointer-events:none;
  transition:opacity .2s,transform .2s;z-index:20}
.toast.show{opacity:1;transform:translateX(-50%) translateY(-4px)}
.tokrow{display:flex;gap:8px;margin:6px 2px 0}
.tokrow input{flex:1;border:1px solid var(--border);border-radius:10px;padding:9px 12px;background:var(--surface);
  color:var(--text);font:inherit;font-size:14px}
.hide{display:none!important}
@media (prefers-reduced-motion: reduce){*{transition:none!important}}
"""

BODY = """
<div class="wrap">
  <header class="header">
    <div class="brand"><span class="dot"></span><span>Account Pool</span></div>
    <span class="spacer"></span>
    <button class="ghost" id="refreshBtn" title="Refresh (r)">Refresh</button>
    <button class="ghost" id="themeBtn" title="Toggle theme">Theme</button>
  </header>

  <div id="banner" class="banner hide"></div>
  <div id="tokwrap" class="tokrow hide">
    <input id="tok" type="password" placeholder="Paste admin token to load data" autocomplete="off">
    <button class="ghost" id="tokSave">Save</button>
  </div>

  <div class="strip" id="strip"></div>

  <div class="focus-h"><h1>Needs you now</h1><span class="pill" id="needCount">0</span></div>
  <div id="approvals"></div>

  <h2 class="section">Everything else</h2>
  <details id="acctBox"><summary>Accounts <span class="count" id="acctCount"></span></summary>
    <div class="body" id="accts"></div></details>
  <details id="pfBox"><summary>Platforms <span class="count" id="pfCount"></span></summary>
    <div class="body"><div class="grid" id="platforms"></div></div></details>
  <details id="logBox"><summary>Recent activity <span class="count" id="logCount"></span></summary>
    <div class="body" id="log"></div></details>

  <p class="foot">Keys: <span class="kbd">j</span>/<span class="kbd">k</span> move ·
    <span class="kbd">a</span> approve · <span class="kbd">c</span> needs changes ·
    <span class="kbd">r</span> refresh</p>
</div>
<div class="toast" id="toast"></div>
"""

SCRIPT = r"""
const PREVIEW = window.__ACCOUNT_POOL_BOOTSTRAP__;
const $ = (s,r=document)=>r.querySelector(s);
const elc = (t,c,x)=>{const e=document.createElement(t); if(c)e.className=c; if(x!=null)e.textContent=x; return e;};
const state = {approvals:[], sel:0};

/* theme */
(function(){ const t=localStorage.getItem('ap_theme'); if(t) document.documentElement.setAttribute('data-theme',t); })();
$('#themeBtn').onclick=()=>{ const cur=document.documentElement.getAttribute('data-theme');
  const dark=cur? cur==='dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  const next=dark?'light':'dark'; document.documentElement.setAttribute('data-theme',next);
  localStorage.setItem('ap_theme',next); };

function token(){ return localStorage.getItem('ap_token')||''; }
$('#tokSave').onclick=()=>{ localStorage.setItem('ap_token',$('#tok').value.trim()); $('#tokwrap').classList.add('hide'); load(); };

function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),1600); }

async function api(path,opts){
  opts=opts||{};
  if(PREVIEW) return preview(path,opts);
  const h=Object.assign({'Content-Type':'application/json'}, opts.headers||{});
  const tk=token(); if(tk) h['Authorization']='Bearer '+tk;
  const res=await fetch(path,Object.assign({},opts,{headers:h}));
  if(res.status===401){ const e=new Error('auth'); e.code=401; throw e; }
  if(!res.ok){ const e=new Error('http '+res.status); e.code=res.status; throw e; }
  return res.status===204?null:res.json();
}
function preview(path,opts){
  const b=PREVIEW;
  if(path==='/config') return Promise.resolve(b.config);
  if(path==='/inventory') return Promise.resolve(b.inventory);
  if(path==='/approvals') return Promise.resolve(b.approvals.slice());
  if(path==='/accounts') return Promise.resolve(b.accounts);
  if(path==='/platforms') return Promise.resolve(b.platforms);
  if(path==='/audit') return Promise.resolve(b.audit);
  if(/\/decide$/.test(path)){ const id=path.split('/')[2];
    b.approvals=b.approvals.filter(a=>a.approval_id!==id); b.inventory.open_approvals=b.approvals.length;
    return Promise.resolve({action_state:'done'}); }
  return Promise.resolve(null);
}

function ago(iso){ if(!iso) return ''; const s=(Date.now()-Date.parse(iso))/1000;
  if(s<45) return 'just now'; if(s<3600) return Math.round(s/60)+'m ago';
  if(s<86400) return Math.round(s/3600)+'h ago'; return Math.round(s/86400)+'d ago'; }
function until(iso){ if(!iso) return ''; const s=(Date.parse(iso)-Date.now())/1000;
  if(s<=0) return 'expired'; if(s<3600) return 'expires in '+Math.max(1,Math.round(s/60))+'m';
  if(s<86400) return 'expires in '+Math.round(s/3600)+'h'; return 'expires in '+Math.round(s/86400)+'d'; }

function renderStrip(inv){
  const s=$('#strip'); s.innerHTML='';
  const active=(inv.by_status&&inv.by_status.active)||0;
  const items=[['Accounts',inv.total||0,false],['Active',active,false],['Needs you',inv.open_approvals||0,true]];
  for(const [l,n,hot] of items){ const d=elc('div','stat'+(hot&&n?' hot':'')); const nn=elc('div','n',String(n));
    d.append(nn, elc('div','l',l)); s.append(d); }
}

function renderApprovals(list){
  state.approvals=list; if(state.sel>=list.length) state.sel=Math.max(0,list.length-1);
  $('#needCount').textContent=String(list.length);
  const box=$('#approvals'); box.innerHTML='';
  if(!list.length){ const e=elc('div','empty'); e.append(elc('div','big','✓'),
    elc('div',null,'Nothing needs you right now.'),
    elc('div','l','Agents keep working; anything that needs a human lands here.')); box.append(e); return; }
  list.forEach((a,i)=>box.append(card(a,i)));
  selectCard(state.sel);
}
function card(a,i){
  const c=elc('div','card'); c.dataset.i=i; c.tabIndex=0;
  const top=elc('div','top');
  top.append(elc('span','chip', (a.platform||'?')));
  if(a.verb) top.append(elc('span','chip verb', a.verb));
  top.append(elc('span','who', '@'+(a.handle||a.account_id||'account')));
  top.append(elc('span','when', ago(a.created_at)));
  c.append(top);
  if(a.target) c.append(elc('div','target', '→ '+a.target));
  if(a.draft){ const d=elc('div','draft'); if(a.draft.title) d.append(elc('div','t',a.draft.title));
    d.append(document.createTextNode(a.draft.body||'')); c.append(d); }
  else if(a.summary) c.append(elc('div','target', a.summary));
  if(a.expires_at){ const ex=elc('div','expiry', a.expired?'expired — can no longer be approved':until(a.expires_at)); c.append(ex); }
  const acts=elc('div','actions');
  const ap=elc('button','btn primary','Approve'); ap.onclick=()=>decide(a,'approve');
  const ch=elc('button','btn soft','Needs changes');
  const reason=elc('textarea','reason'); reason.placeholder='Optional note on what to change…';
  ch.onclick=()=>{ if(!reason.classList.contains('show')){ reason.classList.add('show'); reason.focus(); }
    else decide(a,'request_changes',reason.value); };
  acts.append(ap,ch); c.append(acts,reason);
  c.addEventListener('click',()=>{ state.sel=i; selectCard(i); });
  return c;
}
function selectCard(i){ document.querySelectorAll('.card').forEach((c,j)=>c.classList.toggle('sel',j===i));
  const c=document.querySelector('.card[data-i="'+i+'"]'); if(c) c.scrollIntoView({block:'nearest'}); }

async function decide(a,decision,reason){
  try{ await api('/approvals/'+a.approval_id+'/decide',{method:'POST',
      body:JSON.stringify({decision,decided_by:'you',reason:reason||null})});
    toast(decision==='approve'?'Approved ✓':'Sent back for changes'); await refresh(); }
  catch(e){ toast(e.code===401?'Add your admin token first':'Could not save'); if(e.code===401) needToken(); }
}

function renderAccounts(list){
  $('#acctCount').textContent=list.length; const box=$('#accts'); box.innerHTML='';
  if(!list.length){ box.append(elc('div','l','No accounts yet.')); return; }
  list.forEach(a=>{ const r=elc('div','acct');
    r.append(Object.assign(elc('span','sdot '+a.status),{}) );
    const h=elc('span','h','@'+a.handle); const p=elc('span','p',a.platform);
    r.append(h,p,elc('span','st',a.status)); box.append(r); });
}
function renderPlatforms(list){
  $('#pfCount').textContent=list.length; const g=$('#platforms'); g.innerHTML='';
  list.forEach(p=>{ const t=elc('div','tile'); t.append(elc('div','pf',p.platform));
    t.append(elc('div','meta',(p.verbs||[]).join(' · ')||'—'));
    t.append(elc('span','tier '+p.tier, p.tier.replace('_',' '))); g.append(t); });
}
function renderLog(list){
  $('#logCount').textContent=list.length; const box=$('#log'); box.innerHTML='';
  if(!list.length){ box.append(elc('div','l','No activity yet.')); return; }
  list.slice(0,40).forEach(e=>{ const r=elc('div','log');
    r.append(elc('span','o '+e.outcome, e.verb));
    r.append(elc('span',null, e.message||e.denial_code||''));
    r.append(elc('span','tm', ago(e.ts))); box.append(r); });
}

function renderBanner(cfg){
  const b=$('#banner'); b.classList.remove('hide');
  if(cfg.dry_run){ b.className='banner'; b.innerHTML='<span class="em">✓</span>'+
    '<span>Safe mode — nothing is posted for real. Turn off dry-run to go live.</span>'; }
  else { b.className='banner live'; b.innerHTML='<span class="em">⚡</span>'+
    '<span>Live mode — approved actions post for real ('+(cfg.environment||'')+').</span>'; }
}
function needToken(){ $('#tokwrap').classList.remove('hide'); $('#tok').focus(); }

async function refresh(){
  const [inv,appr,acc,pf,log]=await Promise.all([
    api('/inventory'),api('/approvals'),api('/accounts'),api('/platforms'),api('/audit')]);
  renderStrip(inv); renderApprovals(appr); renderAccounts(acc); renderPlatforms(pf); renderLog(log);
}
async function load(){
  try{ const cfg=await api('/config'); renderBanner(cfg);
    if(cfg.auth_required && !token() && !PREVIEW){ needToken(); }
  }catch(e){}
  try{ await refresh(); }
  catch(e){ if(e.code===401){ needToken(); } }
}

document.addEventListener('keydown',e=>{
  if(/input|textarea/i.test((e.target.tagName||''))) return;
  const n=state.approvals.length;
  if(e.key==='j'){ state.sel=Math.min(n-1,state.sel+1); selectCard(state.sel); }
  else if(e.key==='k'){ state.sel=Math.max(0,state.sel-1); selectCard(state.sel); }
  else if(e.key==='a'&&n){ decide(state.approvals[state.sel],'approve'); }
  else if(e.key==='c'&&n){ const c=document.querySelector('.card[data-i="'+state.sel+'"]');
    if(c) c.querySelectorAll('.btn.soft')[0].click(); }
  else if(e.key==='r'){ e.preventDefault(); refresh(); toast('Refreshed'); }
});
$('#refreshBtn').onclick=()=>{ refresh(); toast('Refreshed'); };
load();
"""


def render_page(bootstrap: str = "null") -> str:
    """Full served HTML document. ``bootstrap`` is a JS literal ('null' → fetch live)."""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta name='color-scheme' content='light dark'>"
        "<title>Account Pool</title><style>"
        + STYLE
        + "</style></head><body>"
        + BODY
        + "<script>window.__ACCOUNT_POOL_BOOTSTRAP__ = "
        + bootstrap
        + ";</script>"
        + "<script>"
        + SCRIPT
        + "</script></body></html>"
    )


# Sample data for the no-backend preview / artifact.
SAMPLE_BOOTSTRAP: dict = {
    "config": {"environment": "dev", "dry_run": True, "server": "account-pool", "auth_required": False},
    "inventory": {
        "total": 7,
        "by_status": {"active": 5, "connected": 1, "draft": 1},
        "by_platform": {"reddit": 2, "mastodon": 1, "bluesky": 1, "twitter": 1, "medium": 1, "substack": 1},
        "open_approvals": 3,
    },
    "approvals": [
        {
            "approval_id": "appr_1",
            "review_state": "open",
            "expired": False,
            "created_at": "2026-07-20T09:12:00Z",
            "expires_at": "2026-07-21T09:12:00Z",
            "platform": "reddit",
            "handle": "brand_reddit",
            "verb": "comment",
            "target": "r/selfhosted/comments/abc/best_tools/",
            "draft": {
                "title": None,
                "body": "We hit the same wall — moving the token refresh into a "
                "background job fixed it for us. Happy to share the snippet if useful.",
            },
            "summary": "comment on r/selfhosted",
        },
        {
            "approval_id": "appr_2",
            "review_state": "open",
            "expired": False,
            "created_at": "2026-07-20T08:40:00Z",
            "expires_at": "2026-07-20T14:40:00Z",
            "platform": "mastodon",
            "handle": "brandvoice",
            "verb": "comment",
            "target": "https://mastodon.social/@someone/1122",
            "draft": {
                "title": None,
                "body": "Love this thread — the point about defaults over config really lands. Bookmarking.",
            },
            "summary": "comment on mastodon.social",
        },
        {
            "approval_id": "appr_3",
            "review_state": "open",
            "expired": False,
            "created_at": "2026-07-19T22:05:00Z",
            "expires_at": "2026-07-20T22:05:00Z",
            "platform": "bluesky",
            "handle": "brand.bsky.social",
            "verb": "comment",
            "target": "at://did:plc:xyz/app.bsky.feed.post/kk9",
            "draft": {
                "title": None,
                "body": "Congrats on the launch! The onboarding felt genuinely calm — rare and appreciated.",
            },
            "summary": "reply on bluesky",
        },
    ],
    "accounts": [
        {
            "account_id": "acct_reddit_brand_reddit_a1",
            "platform": "reddit",
            "handle": "brand_reddit",
            "status": "active",
            "health": "ok",
        },
        {
            "account_id": "acct_reddit_brand_help_b2",
            "platform": "reddit",
            "handle": "brand_help",
            "status": "active",
            "health": "ok",
        },
        {
            "account_id": "acct_mastodon_brandvoice_c3",
            "platform": "mastodon",
            "handle": "brandvoice",
            "status": "active",
            "health": "ok",
        },
        {
            "account_id": "acct_bluesky_brand_d4",
            "platform": "bluesky",
            "handle": "brand.bsky.social",
            "status": "active",
            "health": "ok",
        },
        {
            "account_id": "acct_twitter_brandx_e5",
            "platform": "twitter",
            "handle": "brandx",
            "status": "active",
            "health": "degraded",
        },
        {
            "account_id": "acct_medium_brandmed_f6",
            "platform": "medium",
            "handle": "@brandmed",
            "status": "connected",
            "health": "ok",
        },
        {
            "account_id": "acct_substack_brandletter_g7",
            "platform": "substack",
            "handle": "brandletter",
            "status": "draft",
            "health": "unknown",
        },
    ],
    "platforms": [],  # filled below from platform_overview at build time
    "audit": [
        {
            "event_id": "e1",
            "ts": "2026-07-20T09:14:00Z",
            "actor": "you",
            "verb": "comment",
            "outcome": "allow",
            "message": "executed (dry-run)",
        },
        {
            "event_id": "e2",
            "ts": "2026-07-20T09:10:00Z",
            "actor": "agent-1",
            "verb": "publish",
            "outcome": "allow",
            "message": "executed (dry-run)",
        },
        {
            "event_id": "e3",
            "ts": "2026-07-20T09:02:00Z",
            "actor": "agent-1",
            "verb": "react",
            "outcome": "deny",
            "denial_code": "vote_manipulation_blocked",
            "message": "voting is hard-blocked",
        },
        {
            "event_id": "e4",
            "ts": "2026-07-20T08:55:00Z",
            "actor": "agent-2",
            "verb": "comment",
            "outcome": "route_to_approval",
            "message": "queued approval appr_2",
        },
        {
            "event_id": "e5",
            "ts": "2026-07-20T08:40:00Z",
            "actor": "agent-1",
            "verb": "publish",
            "outcome": "allow",
            "message": "executed (dry-run)",
        },
    ],
}


def sample_bootstrap() -> dict:
    """Sample data with a live platform overview, for the preview/artifact."""
    from ..support import platform_overview

    data = dict(SAMPLE_BOOTSTRAP)
    data["platforms"] = platform_overview()
    return data


def sample_json() -> str:
    return json.dumps(sample_bootstrap())
